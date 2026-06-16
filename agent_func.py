import os
import re
import json
import hashlib
import time as time_module
import xml.etree.ElementTree as _ET
from datetime import datetime, timezone

import ba_ws_sdk.streaming as streaming
from testui.support.testui_driver import TestUIDriver
from dotenv import load_dotenv

load_dotenv()

driver: dict[str, TestUIDriver] = {}
run_test_id = ""
last_returned_value = ""
extra_capabilities: dict = {}
# Per-run default wait timeout (seconds), set by the backend during AI/vision runs.
test_timeout: dict[str, int] = {}
# Cache of (logical_w, logical_h, shot_w, shot_h) per run so we don't take an
# extra screenshot on every coordinate tap just to learn the device pixel ratio.
_screen_scale: dict = {}

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_memory")


def _clean_page_source(content):
    """Remove noisy tags from page source (works for both HTML and mobile XML)."""
    for tag in ['script', 'style', 'svg']:
        content = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', content, flags=re.DOTALL)
    return content


def _get_driver(run_id='1'):
    """Get the TestUIDriver for the given run_id, raising a clear error if missing."""
    if run_id not in driver:
        raise RuntimeError(
            f"No driver found for run_id '{run_id}'. Call create_driver first."
        )
    return driver[run_id]


###############################################################################
# Memory helpers (private)
###############################################################################
def _get_app_identifier() -> str:
    """Return the current app identifier (bundle ID or package name)."""
    return os.getenv("BUNDLE_ID") or os.getenv("APP_PACKAGE") or "unknown_app"


def _get_current_screen(run_id='1') -> str:
    """Best-effort attempt to identify the current screen/activity."""
    try:
        d = _get_driver(run_id).get_driver()
        # Android: current activity
        activity = d.current_activity
        if activity:
            return activity
    except Exception:
        pass
    return "/"


def _memory_file_path(app_id: str) -> str:
    safe_name = re.sub(r'[^\w.\-]', '_', app_id)
    return os.path.join(MEMORY_DIR, f"{safe_name}.json")


def _load_app_memory(app_id: str) -> dict:
    path = _memory_file_path(app_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"app_id": app_id, "updated_at": None, "screens": {}}


def _save_app_memory(app_id: str, data: dict):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(_memory_file_path(app_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _generate_memory_id() -> str:
    return "m_" + hashlib.sha256(
        (datetime.now(timezone.utc).isoformat() + os.urandom(4).hex()).encode()
    ).hexdigest()[:10]


def _get_memories_for_screen(app_id: str, screen: str) -> list:
    data = _load_app_memory(app_id)
    results = []
    screen_data = data.get("screens", {}).get(screen, {})
    results.extend(screen_data.get("memories", []))
    # Also include app-wide memories stored under "/"
    if screen != "/":
        root_data = data.get("screens", {}).get("/", {})
        results.extend(root_data.get("memories", []))
    return results


def _format_memories_block(memories: list) -> str:
    if not memories:
        return ""
    lines = [f"\n--- SCREEN MEMORIES ({len(memories)}) ---"]
    for mem in memories:
        lines.append(f"- [{mem['id']}][{mem.get('category', 'general')}] {mem['observation']}")
    return "\n".join(lines)


###############################################################################
# Driver lifecycle
###############################################################################
def create_driver(_run_test_id='1'):
    """
    Usage = create_driver({})
    Creates a driver that is necessary for the automation to run in the first place.
    Doesn't need any input values to the function and it returns success as string.

    Returns whether an iOS or Android driver is created.
    """
    global driver
    from testui.support.appium_driver import NewDriver

    udid = os.getenv("UDID_ANDROID") or os.getenv("UDID_IOS")
    if not udid:
        return "error: No UDID_ANDROID or UDID_IOS set in environment"

    build_driver = (
        NewDriver()
        .set_logger()
        .set_udid(udid=udid)
        .set_extra_caps({"appium:chromedriverArgs": {}})
    )

    if os.getenv("APP_PACKAGE"):
        build_driver = build_driver.set_app_package_activity(
            app_package=os.getenv("APP_PACKAGE"),
            app_activity=os.getenv("APP_ACTIVITY"),
        )

    if os.getenv("ACCESS_KEY") and os.getenv("ACCESS_TOKEN"):
        build_driver = build_driver.set_extra_caps({
            "df:accesskey": os.getenv("ACCESS_KEY"),
            "df:token": os.getenv("ACCESS_TOKEN"),
            "df:liveVideo": False,
        })

    appium_url = os.getenv("APPIUM_URL")
    if appium_url:
        build_driver = build_driver.set_appium_url(appium_url)

    if os.getenv("APP_PATH") and not os.getenv("APP_PACKAGE"):
        build_driver = (
            build_driver
            .set_app_path(os.getenv("APP_PATH"))
            .set_full_reset(True)
            .set_extra_caps({"appium:enforceAppInstall": True, "appium:noReset": False})
        )

    if os.getenv("BUNDLE_ID") and os.getenv("UDID_IOS"):
        build_driver = (
            build_driver
            .set_platform('ios')
            .set_bundle_id(bundle_id=os.getenv("BUNDLE_ID"))
        )

    # Apply any extra capabilities set via set_capabilities()
    if extra_capabilities:
        build_driver = build_driver.set_extra_caps(extra_capabilities)

    driver[_run_test_id] = build_driver.set_appium_driver()
    streaming.start_stream(driver[_run_test_id], run_id=_run_test_id, fps=1.0, jpeg_quality=10)

    # Go to home screen so the agent starts from a clean state
    try:
        d = driver[_run_test_id].get_driver()
        if os.getenv("UDID_IOS"):
            d.execute_script('mobile: pressButton', {'name': 'home'})
        else:
            d.press_keycode(3)  # Android KEYCODE_HOME
    except Exception:
        pass

    platform = "iOS" if os.getenv("UDID_IOS") else "Android"
    return f"success - {platform} driver created (home screen)"


def stop_driver(_run_test_id='1'):
    """
    Usage = stop_driver({})
    Stops the driver so that later another one can take place,
    and it's always run at the end of the test case.
    Doesn't need any input values to the function and it returns success as string.
    """
    global driver, last_returned_value
    try:
        streaming.stop_stream(_run_test_id)
    except Exception:
        pass
    drv = driver.pop(_run_test_id, None)
    if drv:
        drv.quit()
    # Drop per-run vision state so a future run with the same id (or a device
    # rotation) recomputes the screenshot→logical scale instead of reusing it.
    _screen_scale.pop(_run_test_id, None)
    test_timeout.pop(_run_test_id, None)
    last_returned_value = "success"
    return "success"


def stop_all_drivers(_run_test_id='1'):
    """
    Usage = stop_all_drivers({})
    Stops all the drivers that are running in this agent.
    Doesn't need any input values to the function and it returns 'All drivers stopped and entries cleared.'
    """
    global driver
    try:
        streaming.stop_stream(_run_test_id)
    except Exception:
        pass
    for run_id, drv in list(driver.items()):
        try:
            drv.quit()
        except Exception as e:
            print(f"Error stopping driver '{run_id}': {e}")
    driver.clear()
    return "All drivers stopped and entries cleared."


def set_capabilities(capabilities: str, _run_test_id='1') -> str:
    """
    Usage = set_capabilities({"capabilities": "{\\"appium:noReset\\": true, \\"appium:fullReset\\": false}"})
    Sets extra Appium desired capabilities that will be applied the next time create_driver is called.
    The `capabilities` parameter is a JSON string of key-value pairs.
    These are merged on top of the default capabilities from environment variables.

    Common capabilities:
      - "appium:noReset": true/false - don't reset app state between sessions
      - "appium:fullReset": true/false - fully reinstall the app
      - "appium:autoGrantPermissions": true - auto-grant Android permissions
      - "appium:autoAcceptAlerts": true - auto-accept iOS permission alerts
      - "appium:newCommandTimeout": 300 - seconds before session times out

    Call this BEFORE create_driver. To clear, call clear_capabilities.
    """
    global extra_capabilities
    try:
        caps = json.loads(capabilities)
        if not isinstance(caps, dict):
            return "error: capabilities must be a JSON object (key-value pairs)"
        extra_capabilities.update(caps)
        return f"Capabilities set: {json.dumps(extra_capabilities)}"
    except json.JSONDecodeError as e:
        return f"error: invalid JSON - {e}"


def clear_capabilities(_run_test_id='1') -> str:
    """
    Usage = clear_capabilities({})
    Clears all extra capabilities previously set via set_capabilities.
    The next create_driver call will use only the default capabilities from environment variables.
    """
    global extra_capabilities
    extra_capabilities.clear()
    return "Extra capabilities cleared."


def list_apps(filter_keyword: str = '', _run_test_id='1') -> str:
    """
    Usage = list_apps({})
    Usage = list_apps({"filter_keyword": "barko"})
    Returns a list of installed app package names (Android) or bundle IDs (iOS) on the device.
    Use this to discover which apps are available before calling open_app.
    Optionally pass filter_keyword to only return apps whose name contains that keyword.
    """
    d = _get_driver(_run_test_id).get_driver()
    is_ios = bool(os.getenv("UDID_IOS"))

    app_ids = []
    platform = "iOS" if is_ios else "Android"
    methods_tried = []

    if is_ios:
        # iOS: mobile:listApps
        try:
            apps = d.execute_script('mobile: listApps')
            app_ids = [app.get('CFBundleIdentifier', '') for app in apps if app.get('CFBundleIdentifier')]
            methods_tried.append("mobile:listApps (success)")
        except Exception as e:
            methods_tried.append(f"mobile:listApps (failed: {e})")
    else:
        # Android: try multiple approaches in order of preference
        # 1. mobile:shell (requires --relaxed-security on Appium server)
        try:
            result = d.execute_script('mobile: shell', {'command': 'pm', 'args': ['list', 'packages']})
            lines = result.strip().split('\n') if isinstance(result, str) else []
            app_ids = [line.replace('package:', '').strip() for line in lines if line.startswith('package:')]
            methods_tried.append("mobile:shell (success)")
        except Exception as e:
            methods_tried.append(f"mobile:shell (failed: {e})")

        # 2. Fallback: mobile:getAppStrings to at least confirm current app
        if not app_ids:
            try:
                import subprocess
                udid = os.getenv("UDID_ANDROID", "")
                cmd = ['adb']
                if udid:
                    cmd.extend(['-s', udid])
                cmd.extend(['shell', 'pm', 'list', 'packages'])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    app_ids = [line.replace('package:', '').strip() for line in lines if line.startswith('package:')]
                    methods_tried.append("adb direct (success)")
                else:
                    methods_tried.append(f"adb direct (failed: {result.stderr.strip()})")
            except Exception as e:
                methods_tried.append(f"adb direct (failed: {e})")

    # Apply filter
    if filter_keyword and app_ids:
        kw = filter_keyword.lower()
        app_ids = [a for a in app_ids if kw in a.lower()]

    app_ids.sort()

    if not app_ids:
        return json.dumps({
            "platform": platform,
            "app_count": 0,
            "apps": [],
            "methods_tried": methods_tried,
            "hint": "If listing failed, ask the user for the app package name/bundle ID, or try open_app with a guessed identifier."
        })

    return json.dumps({"platform": platform, "app_count": len(app_ids), "apps": app_ids})


def open_app(app_id: str, clear_state: str = 'true', _run_test_id='1') -> str:
    """
    Usage = open_app({"app_id": "..."})
    Usage = open_app({"app_id": "...", "clear_state": "true"})
    Activates/opens a different app on the device by its package name (Android) or bundle ID (iOS).
    The driver must already be created. This does NOT restart the driver session.

    If clear_state is "true", the app's data/cache is cleared before opening, so it starts fresh
    (like a first install). On Android this clears app data; on iOS it terminates and reinstalls.

    Example: open_app({"app_id": "com.android.settings"})
    Example: open_app({"app_id": "com.myapp", "clear_state": "true"})
    """
    d = _get_driver(_run_test_id).get_driver()
    if clear_state == 'true':
        _clear_app_state(d, app_id)
    d.activate_app(app_id)
    cleared_msg = " (state cleared)" if clear_state == 'true' else ""
    return f"app '{app_id}' opened{cleared_msg}"


def reset_app(app_id: str = '', _run_test_id='1') -> str:
    """
    Usage = reset_app({"app_id": "..."})
    Usage = reset_app({})
    Clears the app's data and cache so it returns to a fresh state (like after first install).
    If app_id is empty, resets the app configured in environment variables.
    The app is terminated first, then its data is cleared, then it is reopened.

    On Android: clears app data via `pm clear`.
    On iOS: terminates the app (full clear requires reinstall via create_driver with fullReset).
    """
    d = _get_driver(_run_test_id).get_driver()
    if not app_id:
        app_id = os.getenv("BUNDLE_ID") or os.getenv("APP_PACKAGE") or ""
    if not app_id:
        return "error: no app_id provided and no APP_PACKAGE/BUNDLE_ID in environment"
    result = _clear_app_state(d, app_id)
    d.activate_app(app_id)
    return f"app '{app_id}' reset and reopened. {result}"


def _clear_app_state(d, app_id: str) -> str:
    """Clear app data/cache. Returns a status message."""
    # Terminate the app first
    try:
        d.terminate_app(app_id)
    except Exception:
        pass

    is_ios = bool(os.getenv("UDID_IOS"))
    if is_ios:
        # iOS doesn't support clearing app data directly via Appium.
        # Best we can do is terminate. Full reset requires reinstall.
        return "iOS: app terminated (for full data clear, use create_driver with fullReset capability)"
    else:
        # Android: try pm clear via mobile:shell, fallback to adb
        try:
            d.execute_script('mobile: shell', {'command': 'pm', 'args': ['clear', app_id]})
            return "app data cleared via mobile:shell"
        except Exception:
            pass
        try:
            import subprocess
            udid = os.getenv("UDID_ANDROID", "")
            cmd = ['adb']
            if udid:
                cmd.extend(['-s', udid])
            cmd.extend(['shell', 'pm', 'clear', app_id])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return "app data cleared via adb"
            else:
                return f"warning: could not clear app data ({result.stderr.strip()})"
        except Exception as e:
            return f"warning: could not clear app data ({e})"


def close_app(app_id: str = '', _run_test_id='1') -> str:
    """
    Usage = close_app({"app_id": "..."})
    Terminates an app on the device by its package name (Android) or bundle ID (iOS).
    If app_id is empty, terminates the app configured in environment variables.

    Example: close_app({"app_id": "com.android.settings"})
    """
    if not app_id:
        app_id = os.getenv("BUNDLE_ID") or os.getenv("APP_PACKAGE") or ""
    if not app_id:
        return "error: no app_id provided and no APP_PACKAGE/BUNDLE_ID in environment"
    _get_driver(_run_test_id).get_driver().terminate_app(app_id)
    return f"app '{app_id}' closed"


###############################################################################
# Element interaction
###############################################################################
def click(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = click({"locator_type": "...", "locator": "..."})
    Clicks/Taps on the element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated.
    """
    _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).click()
    return "clicked successfully"


def send_keys(locator_type: str, locator: str, value: str = None, _run_test_id='1') -> str:
    """
    Usage = send_keys({"locator_type": "...", "locator": "...", "value": "..."})
    Types in the value in the element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated.

    If value is not set, then it will take the value from the returned value of the previous function call.
    """
    global last_returned_value
    if value is None or value == "":
        value = last_returned_value
    _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).clear().send_keys(value=value)
    last_returned_value = value
    return "sent keys"


def long_press(locator_type: str, locator: str, duration: str, _run_test_id='1') -> str:
    """
    Usage = long_press({"locator_type": "...", "locator": "...", "duration": "..."})
    Long presses on the element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated. Duration is in seconds (e.g. "2" for 2 seconds).
    """
    _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).press_hold_for(float(duration))
    return "long pressed successfully"


def get_text(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = get_text({"locator_type": "...", "locator": "..."})
    Gets the visible text of the element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated. The returned value is stored for use by subsequent functions.
    """
    global last_returned_value
    element = _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator)
    text = element.get_attribute("text") or element.get_attribute("label") or element.get_attribute("value") or ""
    last_returned_value = text
    return text


def get_attribute(locator_type: str, locator: str, attribute_name: str, _run_test_id='1') -> str:
    """
    Usage = get_attribute({"locator_type": "...", "locator": "...", "attribute_name": "..."})
    Gets the attribute value of the element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated. The returned value is stored for use by subsequent functions.
    """
    global last_returned_value
    attr_value = _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).get_attribute(attribute_name)
    last_returned_value = attr_value
    return attr_value


###############################################################################
# Element assertions
###############################################################################
def exists(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = exists({"locator_type": "...", "locator": "..."})
    Checks if element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated exists on the screen. Waits up to 10 seconds.
    """
    _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).wait_until_exists(seconds=10)
    return "exists"


def does_not_exist(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = does_not_exist({"locator_type": "...", "locator": "..."})
    Checks if element defined by its `locator_type` (id, accessibility, xpath, classChain, predicate, uiautomator, css)
    and its locator path associated does NOT exist on the screen. Waits up to 5 seconds.
    """
    _get_driver(_run_test_id).e(locator_type=locator_type, locator=locator).no().wait_until_visible(seconds=5)
    return "does not exist"


###############################################################################
# Page & navigation
###############################################################################
def get_page(_run_test_id='1') -> str:
    """
    Usage = get_page({})
    Returns the full page source / DOM of the current screen (cleaned) so that you can
    parse it and find locators for click, send_keys, exists, etc.
    Also auto-loads any saved screen memories and appends them to the output.
    """
    global last_returned_value
    content = _get_driver(_run_test_id).get_driver().page_source
    cleaned = _clean_page_source(content)
    last_returned_value = cleaned
    # Auto-load screen memories
    try:
        app_id = _get_app_identifier()
        screen = _get_current_screen(_run_test_id)
        memories = _get_memories_for_screen(app_id, screen)
        memory_block = _format_memories_block(memories)
        if memory_block:
            cleaned += memory_block
    except Exception:
        pass
    return cleaned


def go_back(_run_test_id='1') -> str:
    """
    Usage = go_back({})
    Presses the back button / navigates back.
    """
    _get_driver(_run_test_id).back()
    return "went back"


###############################################################################
# Scrolling & swiping
###############################################################################
def scroll_down(_run_test_id='1') -> str:
    """
    Usage = scroll_down({})
    Scrolls down on the current screen. Useful for reaching elements that are not yet visible.
    """
    d = _get_driver(_run_test_id).get_driver()
    size = d.get_window_size()
    start_x = size['width'] // 2
    start_y = int(size['height'] * 0.7)
    end_y = int(size['height'] * 0.3)
    d.swipe(start_x, start_y, start_x, end_y, 800)
    return "scrolled down"


def scroll_up(_run_test_id='1') -> str:
    """
    Usage = scroll_up({})
    Scrolls up on the current screen.
    """
    d = _get_driver(_run_test_id).get_driver()
    size = d.get_window_size()
    start_x = size['width'] // 2
    start_y = int(size['height'] * 0.3)
    end_y = int(size['height'] * 0.7)
    d.swipe(start_x, start_y, start_x, end_y, 800)
    return "scrolled up"


def swipe(direction: str, _run_test_id='1') -> str:
    """
    Usage = swipe({"direction": "..."})
    Swipes in the given direction on the screen. Direction must be one of: up, down, left, right.
    """
    d = _get_driver(_run_test_id).get_driver()
    size = d.get_window_size()
    cx, cy = size['width'] // 2, size['height'] // 2
    offsets = {
        'up':    (cx, int(size['height'] * 0.7), cx, int(size['height'] * 0.3)),
        'down':  (cx, int(size['height'] * 0.3), cx, int(size['height'] * 0.7)),
        'left':  (int(size['width'] * 0.8), cy, int(size['width'] * 0.2), cy),
        'right': (int(size['width'] * 0.2), cy, int(size['width'] * 0.8), cy),
    }
    direction = direction.lower().strip()
    if direction not in offsets:
        return f"error: invalid direction '{direction}'. Use: up, down, left, right"
    sx, sy, ex, ey = offsets[direction]
    d.swipe(sx, sy, ex, ey, 800)
    return f"swiped {direction}"


def swipe_coordinates(start_x: str, start_y: str, end_x: str, end_y: str,
                      duration: str = '800', _run_test_id='1') -> str:
    """
    Usage = swipe_coordinates({"start_x": "...", "start_y": "...", "end_x": "...", "end_y": "...", "duration": "800"})
    Performs a custom swipe gesture from (start_x, start_y) to (end_x, end_y).

    Use this when the fixed directions in swipe() are not enough — e.g. dragging
    a slider, swiping a specific card/list row, or a precise drag distance.

    Coordinates are in SCREENSHOT-pixel space (what the vision model sees) and
    are scaled to device logical points, so they land correctly on high-density
    (Retina) screens. duration is the swipe time in MILLISECONDS (default 800);
    a longer duration makes a slower, more deliberate drag.
    """
    d = _get_driver(_run_test_id).get_driver()
    sx, sy = _scale_screenshot_to_logical(d, _run_test_id, float(start_x), float(start_y))
    ex, ey = _scale_screenshot_to_logical(d, _run_test_id, float(end_x), float(end_y))
    try:
        dur = max(50, int(float(duration)))
    except (TypeError, ValueError):
        dur = 800
    d.swipe(int(sx), int(sy), int(ex), int(ey), dur)
    return f"swiped from ({int(sx)}, {int(sy)}) to ({int(ex)}, {int(ey)}) over {dur}ms"


def scroll_to_element(locator_type: str, locator: str, direction: str = "down", max_scrolls: int = 5, _run_test_id='1') -> str:
    """
    Usage = scroll_to_element({"locator_type": "...", "locator": "...", "direction": "down", "max_scrolls": 5})
    Scrolls in the given direction until the element is found or max_scrolls is reached.
    direction defaults to "down". max_scrolls defaults to 5.
    """
    drv = _get_driver(_run_test_id)
    for i in range(int(max_scrolls)):
        try:
            drv.e(locator_type=locator_type, locator=locator).wait_until_exists(seconds=2)
            return f"element found after {i} scrolls"
        except Exception:
            swipe(direction, _run_test_id)
    # One last check
    try:
        drv.e(locator_type=locator_type, locator=locator).wait_until_exists(seconds=2)
        return f"element found after {max_scrolls} scrolls"
    except Exception:
        return f"element not found after {max_scrolls} scrolls"


def tap_coordinates(x: str, y: str, _run_test_id='1') -> str:
    """
    Usage = tap_coordinates({"x": "...", "y": "..."})
    Taps on the screen at the given x, y pixel coordinates. Use this only when no reliable
    locator is available for the target element.
    """
    d = _get_driver(_run_test_id).get_driver()
    _native_tap(d, int(x), int(y))
    return f"tapped at ({x}, {y})"


###############################################################################
# Vision support — coordinate tapping driven by screenshots.
#
# A native mobile app has NO DOM/JS, so the backend's DOM element-map / click
# probe / ai_action (all JavaScript) cannot run here. The backend gracefully
# degrades to the native coordinate click, so the agent must expose:
#   - click_coordinates  (alias of tap, but SCALED screenshot-px -> logical pts)
#   - scroll_by          (mapped to a swipe gesture)
#   - set_default_timeout
# The crucial difference from tap_coordinates: the vision model picks
# coordinates in the SCREENSHOT's pixel space (e.g. 1170px wide on a Retina
# phone), but Appium taps in logical points (e.g. 390px). We scale between them
# so taps land where the model intended.
###############################################################################

def set_default_timeout(timeout: str, _run_test_id='1') -> str:
    """Stores the default wait timeout (in SECONDS) for this run (used by AI/vision runs)."""
    global test_timeout
    try:
        secs = max(1, min(60, int(float(timeout))))
    except (TypeError, ValueError):
        return "invalid timeout"
    test_timeout[_run_test_id] = secs
    return f"default timeout set to {secs}s"


def _get_scale_dims(d, _run_test_id):
    """
    Return (logical_w, logical_h, screenshot_w, screenshot_h) for this run,
    cached. logical = Appium tap/bounds space; screenshot = what the vision
    model sees. They differ by the device pixel ratio on Retina/HiDPI screens.
    """
    global _screen_scale
    cached = _screen_scale.get(_run_test_id)
    if cached is None:
        lw = lh = sw = sh = 0
        try:
            size = d.get_window_size()
            lw, lh = int(size['width']), int(size['height'])
        except Exception as e:
            print(f"[vision] window size unavailable: {e}")
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(d.get_screenshot_as_png()))
            sw, sh = img.size
        except Exception as e:
            print(f"[vision] screenshot sizing failed: {e}")
        # Fall back to whichever dimension we have so ratios are 1.0 (no scaling)
        # rather than zero-division.
        cached = (lw or sw or 1, lh or sh or 1, sw or lw or 1, sh or lh or 1)
        _screen_scale[_run_test_id] = cached
    return cached


def _scale_screenshot_to_logical(d, _run_test_id, px, py):
    """Convert screenshot-pixel coords (model space) to device logical points (tap space)."""
    lw, lh, sw, sh = _get_scale_dims(d, _run_test_id)
    if sw and sh and (sw != lw or sh != lh):
        return px * lw / sw, py * lh / sh
    return px, py


def _native_tap(d, x, y):
    """
    Tap at LOGICAL coordinates using the modern Appium gesture plugins, which
    are reliable on Appium 2 (UiAutomator2 / XCUITest). The legacy TouchAction
    bridge often silently no-ops on launcher icons / app tiles (and can raise the
    raw-body errors seen in agent logs), so it's only the last-resort fallback.
    """
    ix, iy = int(x), int(y)
    plat = ''
    try:
        plat = str((d.capabilities or {}).get('platformName') or '').lower()
    except Exception:
        pass
    try:
        if 'ios' in plat:
            d.execute_script('mobile: tap', {'x': ix, 'y': iy})
        else:
            d.execute_script('mobile: clickGesture', {'x': ix, 'y': iy})
        return
    except Exception as e:
        print(f"[vision] mobile gesture tap failed ({e}); falling back to TouchAction")
    from appium.webdriver.common.touch_action import TouchAction
    TouchAction(d).tap(x=ix, y=iy).perform()


def _parse_node_bounds(attrib):
    """
    Return (x1, y1, x2, y2) in LOGICAL points for an Appium XML node, or None.
    Android exposes bounds="[x1,y1][x2,y2]"; iOS exposes x/y/width/height.
    """
    b = attrib.get('bounds')
    if b:
        nums = re.findall(r'-?\d+', b)
        if len(nums) == 4:
            x1, y1, x2, y2 = (int(n) for n in nums)
            return (x1, y1, x2, y2)
    if 'x' in attrib and 'width' in attrib:
        try:
            x = int(float(attrib['x']))
            y = int(float(attrib['y']))
            w = int(float(attrib['width']))
            h = int(float(attrib['height']))
            return (x, y, x + w, y + h)
        except (ValueError, TypeError):
            return None
    return None


def _node_identity(attrib):
    """
    Best stable identity for an Appium node → (strategy, locator, text).
    strategy is one of: 'id' (resource-id), 'accessibility' (content-desc/name),
    'xpath' (by visible text), or None when nothing stable is available.
    """
    text = (attrib.get('text') or attrib.get('label') or attrib.get('value') or '').strip()
    rid = (attrib.get('resource-id') or '').strip()
    cdesc = (attrib.get('content-desc') or '').strip()
    name = (attrib.get('name') or '').strip()
    if rid:
        return 'id', rid, (text or name)
    if cdesc:
        return 'accessibility', cdesc, (text or name)
    if name:
        return 'accessibility', name, (text or name)
    if text:
        esc = text.replace('"', '')
        return 'xpath', f'//*[@text="{esc}" or @label="{esc}"]', text
    return None, None, ''


def inspect_point(x: str, y: str, _run_test_id='1') -> str:
    """
    Resolve the element behind a tap (the Appium-XML analog of the web's
    elementFromPoint probe). Coordinates are in SCREENSHOT-pixel space; we scale
    to logical points, find the smallest element whose bounds contain the point,
    walk to the nearest node carrying a stable identity, and return that identity
    plus the element's center (reported back in screenshot space).

    Returns JSON: {status: HIT|MISS, strategy, locator, text, cls, center:[x,y], aim:[x,y]}.
    """
    d = _get_driver(_run_test_id).get_driver()
    lw, lh, sw, sh = _get_scale_dims(d, _run_test_id)
    ax, ay = int(float(x)), int(float(y))
    lx = float(x) * (lw / sw if sw else 1.0)
    ly = float(y) * (lh / sh if sh else 1.0)
    try:
        root = _ET.fromstring(d.page_source)
    except Exception as e:
        return json.dumps({"status": "MISS", "aim": [ax, ay], "reason": f"page_source parse failed: {e}"})

    containing = []
    for node in root.iter():
        bb = _parse_node_bounds(node.attrib)
        if not bb:
            continue
        x1, y1, x2, y2 = bb
        if x2 <= x1 or y2 <= y1:
            continue
        if x1 <= lx <= x2 and y1 <= ly <= y2:
            containing.append(((x2 - x1) * (y2 - y1), bb, node.attrib))
    if not containing:
        return json.dumps({"status": "MISS", "aim": [ax, ay]})

    containing.sort(key=lambda t: t[0])  # smallest (most specific) first
    chosen = None
    for _area, bb, attrib in containing:
        strat, loc, text = _node_identity(attrib)
        if strat:
            chosen = (bb, attrib, strat, loc, text)
            break
    if chosen is None:
        bb, attrib = containing[0][1], containing[0][2]
        strat, loc = None, None
        text = (attrib.get('text') or attrib.get('label') or '').strip()
    else:
        bb, attrib, strat, loc, text = chosen

    x1, y1, x2, y2 = bb
    scx = int((x1 + x2) / 2 * (sw / lw if lw else 1.0))
    scy = int((y1 + y2) / 2 * (sh / lh if lh else 1.0))
    return json.dumps({
        "status": "HIT",
        "strategy": strat or "coordinate",
        "locator": loc or "",
        "text": (text or "")[:80],
        "cls": (attrib.get('class') or attrib.get('type') or '')[:60],
        "center": [scx, scy],
        "aim": [ax, ay],
    })


def get_element_map(_run_test_id='1') -> str:
    """
    Enumerate visible, identifiable/clickable elements on the current screen with
    their centers (in SCREENSHOT space) and stable identity — the Appium-XML
    analog of the web element map used by inspect_streaming.

    Returns JSON: {count, elements:[{text, strategy, locator, cls, center:[x,y]}]}.
    """
    d = _get_driver(_run_test_id).get_driver()
    lw, lh, sw, sh = _get_scale_dims(d, _run_test_id)
    try:
        root = _ET.fromstring(d.page_source)
    except Exception as e:
        return json.dumps({"count": 0, "elements": [], "error": str(e)})
    elements = []
    for node in root.iter():
        bb = _parse_node_bounds(node.attrib)
        if not bb:
            continue
        x1, y1, x2, y2 = bb
        if x2 <= x1 or y2 <= y1:
            continue
        attrib = node.attrib
        strat, loc, text = _node_identity(attrib)
        clickable = (attrib.get('clickable') == 'true') or (attrib.get('accessible') == 'true')
        if not (strat or clickable or text):
            continue
        # Convert bounds (logical) → screenshot space so the backend can draw
        # the numbered element map directly over the screenshot it streams.
        rx = (sw / lw) if lw else 1.0
        ry = (sh / lh) if lh else 1.0
        sx1, sy1, sx2, sy2 = int(x1 * rx), int(y1 * ry), int(x2 * rx), int(y2 * ry)
        elements.append({
            "text": (text or "")[:60],
            "strategy": strat or "",
            "locator": loc or "",
            "tag": (attrib.get('class') or attrib.get('type') or '')[:40],
            "box": [sx1, sy1, sx2, sy2],
            "center": [int((sx1 + sx2) / 2), int((sy1 + sy2) / 2)],
        })
    return json.dumps({"count": len(elements), "elements": elements})


def tap_element_by_identity(strategy: str = '', locator: str = '', text: str = '',
                            cx: str = '0', cy: str = '0', action: str = 'click',
                            value: str = '', _run_test_id='1') -> str:
    """
    Replay an ai_action recorded by the vision loop: re-find the element by its
    stable identity (resource-id / accessibility id / text xpath) and tap it;
    fall back to a scaled coordinate tap at (cx, cy) when identity re-find fails.
    Returns JSON: {status: DONE|NOMATCH, via}.
    """
    drv = _get_driver(_run_test_id)
    d = drv.get_driver()
    last_err = ""
    if strategy and locator and strategy != 'coordinate':
        try:
            el = drv.e(locator_type=strategy, locator=locator)
            el.wait_until_exists(seconds=int(test_timeout.get(_run_test_id, 5)))
            if action == 'type':
                el.clear().send_keys(value=value)
            else:
                el.click()
            return json.dumps({"status": "DONE", "via": strategy})
        except Exception as e:
            last_err = str(e)
    # Coordinate fallback (cx/cy are screenshot-space → scale to logical).
    try:
        lx, ly = _scale_screenshot_to_logical(d, _run_test_id, float(cx), float(cy))
        _native_tap(d, int(lx), int(ly))
        return json.dumps({"status": "DONE", "via": "coordinate"})
    except Exception as e:
        return json.dumps({"status": "NOMATCH", "reason": (last_err or str(e))})


# Focused element across platforms: Android exposes @focused, iOS @hasKeyboardFocus.
_FOCUSED_XPATH = '//*[@focused="true" or @hasKeyboardFocus="true"]'


def type_keys(value: str, _run_test_id='1', clear: str = 'false', use_vars: str = 'false') -> str:
    """
    Types text into the currently focused field (no locator) — used after a
    coordinate tap focuses an input. Set clear='true' to clear it first.
    Name-compatible with the web agents so the vision pipeline can drive mobile.
    """
    drv = _get_driver(_run_test_id)
    try:
        # A short wait — this checks what is focused RIGHT NOW (after a click);
        # waiting longer won't make an unfocused field appear, it just stalls.
        el = drv.e(locator_type='xpath', locator=_FOCUSED_XPATH)
        el.wait_until_exists(seconds=2)
        if clear == 'true':
            try:
                el.clear()
            except Exception:
                pass
        el.send_keys(value=value)
        return "typed"
    except Exception as e:
        return f"could not type into focused element: {e}"


def press_key(key: str, _run_test_id='1') -> str:
    """
    Presses a single key. On Android uses key-event codes (Enter, Back, Tab, …);
    otherwise sends the key to the focused field. Vision-pipeline compatible.
    """
    d = _get_driver(_run_test_id).get_driver()
    k = str(key).strip().lower()
    android_codes = {
        'enter': 66, 'back': 4, 'home': 3, 'tab': 61, 'delete': 67,
        'backspace': 67, 'space': 62, 'search': 84, 'escape': 111,
    }
    if k in android_codes and hasattr(d, 'press_keycode'):
        try:
            d.press_keycode(android_codes[k])
            return f"pressed {key}"
        except Exception:
            pass
    try:
        from selenium.webdriver.common.keys import Keys
        keymap = {
            'enter': Keys.ENTER, 'tab': Keys.TAB, 'backspace': Keys.BACK_SPACE,
            'delete': Keys.DELETE, 'escape': Keys.ESCAPE,
        }
        drv = _get_driver(_run_test_id)
        el = drv.e(locator_type='xpath', locator=_FOCUSED_XPATH)
        el.send_keys(value=keymap.get(k, key))
        return f"pressed {key}"
    except Exception as e:
        return f"could not press {key}: {e}"


def click_coordinates(x: str, y: str, _run_test_id='1') -> str:
    """
    Taps at the given SCREENSHOT-pixel coordinates. Coordinates are scaled to
    the device's logical points (handles Retina/high-density screens), so taps
    land where the vision model intended. Name-compatible with the web agents'
    click_coordinates so the same backend vision pipeline can drive mobile.
    Use only when no reliable locator is available.
    """
    d = _get_driver(_run_test_id).get_driver()
    lx, ly = _scale_screenshot_to_logical(d, _run_test_id, float(x), float(y))
    _native_tap(d, int(lx), int(ly))
    return f"tapped at ({int(lx)}, {int(ly)})"


def scroll_by(dx: str, dy: str, _run_test_id='1') -> str:
    """
    Scrolls the screen by approximately the given amounts (vision-pipeline
    compatible). Positive dy scrolls content DOWN, negative UP; dx scrolls
    horizontally. Mapped to a swipe gesture (mobile has no pixel-precise scroll).
    """
    d = _get_driver(_run_test_id).get_driver()
    size = d.get_window_size()
    w, h = int(size['width']), int(size['height'])
    cx, cy = w // 2, h // 2
    try:
        fdx, fdy = float(dx), float(dy)
    except (TypeError, ValueError):
        fdx, fdy = 0.0, 0.0
    if abs(fdy) >= abs(fdx):
        # Content scrolls DOWN when the finger swipes UP (and vice versa).
        if fdy >= 0:
            d.swipe(cx, int(h * 0.7), cx, int(h * 0.3), 600)
        else:
            d.swipe(cx, int(h * 0.3), cx, int(h * 0.7), 600)
    else:
        if fdx >= 0:
            d.swipe(int(w * 0.7), cy, int(w * 0.3), cy, 600)
        else:
            d.swipe(int(w * 0.3), cy, int(w * 0.7), cy, 600)
    return f"scrolled by ({dx}, {dy})"


###############################################################################
# App lifecycle
###############################################################################
def send_app_background(_run_test_id='1') -> str:
    """
    Usage = send_app_background({})
    Sends the app to background.
    """
    _get_driver(_run_test_id).background_app(-1)
    return "app in background"


def app_foreground(_run_test_id='1') -> str:
    """
    Usage = app_foreground({})
    Brings the app back to the foreground.
    """
    bundle_or_package = os.getenv("BUNDLE_ID") or os.getenv("APP_PACKAGE")
    if bundle_or_package:
        _get_driver(_run_test_id).get_driver().activate_app(bundle_or_package)
    return "app in foreground"


###############################################################################
# Screen memory (public)
###############################################################################
def save_screen_memory(screen: str, observation: str, category: str = 'general', _run_test_id='1') -> str:
    """
    Usage = save_screen_memory({"screen": "...", "observation": "...", "category": "..."})
    Saves an observation/learning about a specific screen for future runs.
    Use this when you discover something non-obvious about how a screen works:
    element types that differ from expectations, locator strategies, timing requirements, workarounds, etc.

    The `screen` parameter should be the activity name (e.g. ".MainActivity") or a descriptive
    screen identifier (e.g. "/login", "/settings"). Use "/" for app-wide observations.

    Categories: locator_hint, element_type, flow_behavior, timing, workaround, general
    """
    app_id = _get_app_identifier()
    data = _load_app_memory(app_id)
    if screen not in data["screens"]:
        data["screens"][screen] = {"memories": []}
    for mem in data["screens"][screen]["memories"]:
        if mem["observation"] == observation and mem["category"] == category:
            return f"Memory already exists: {mem['id']}"
    now = datetime.now(timezone.utc).isoformat()
    memory_id = _generate_memory_id()
    data["screens"][screen]["memories"].append({
        "id": memory_id,
        "observation": observation,
        "category": category,
        "created_at": now,
        "updated_at": now,
    })
    _save_app_memory(app_id, data)
    return f"Memory saved: {memory_id}"


def get_screen_memories(screen: str = '', _run_test_id='1') -> str:
    """
    Usage = get_screen_memories({"screen": "..."})
    Retrieves all saved memories for a specific screen.
    If screen is empty, tries to detect the current screen automatically.
    Returns memories for the exact screen AND app-wide memories (screen="/").
    Note: get_page already auto-loads memories, so use this only when you need
    to check memories without fetching the page source.
    """
    app_id = _get_app_identifier()
    if not screen:
        screen = _get_current_screen(_run_test_id)
    memories = _get_memories_for_screen(app_id, screen)
    if not memories:
        return json.dumps({"app_id": app_id, "screen": screen, "memories": [], "message": "No memories found for this screen."})
    return json.dumps({"app_id": app_id, "screen": screen, "memory_count": len(memories), "memories": memories})


def update_screen_memory(memory_id: str, observation: str = '', delete: str = 'false', _run_test_id='1') -> str:
    """
    Usage (update) = update_screen_memory({"memory_id": "m_a1b2c3", "observation": "New correct observation"})
    Usage (delete) = update_screen_memory({"memory_id": "m_a1b2c3", "delete": "true"})
    Updates or deletes an existing screen memory by its ID.
    Use this when you discover a previous observation is outdated or wrong.
    """
    if not os.path.exists(MEMORY_DIR):
        return f"Memory {memory_id} not found."
    for filename in os.listdir(MEMORY_DIR):
        if not filename.endswith(".json"):
            continue
        app_id = filename[:-5]
        data = _load_app_memory(app_id)
        for screen_key, screen_data in data.get("screens", {}).items():
            for i, mem in enumerate(screen_data.get("memories", [])):
                if mem["id"] == memory_id:
                    if delete == 'true':
                        screen_data["memories"].pop(i)
                        _save_app_memory(app_id, data)
                        return f"Memory {memory_id} deleted."
                    else:
                        mem["observation"] = observation
                        mem["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _save_app_memory(app_id, data)
                        return f"Memory {memory_id} updated."
    return f"Memory {memory_id} not found."


###############################################################################
# Utilities
###############################################################################
def wait_seconds(time_sec, _run_test_id='1') -> str:
    """
    Usage = wait_seconds({"time_sec": "..."})
    Waits for the specified number of seconds.
    """
    time_module.sleep(float(time_sec))
    return f"waited {time_sec} seconds"


def hide_keyboard(_run_test_id='1') -> str:
    """
    Usage = hide_keyboard({})
    Hides the on-screen keyboard if it is currently visible.
    """
    try:
        _get_driver(_run_test_id).get_driver().hide_keyboard()
    except Exception:
        pass  # keyboard may not be visible
    return "keyboard hidden"

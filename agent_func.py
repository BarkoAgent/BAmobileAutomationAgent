import os
import re
import json
import hashlib
import time as time_module
from datetime import datetime, timezone

import ba_ws_sdk.streaming as streaming
from testui.support.testui_driver import TestUIDriver
from dotenv import load_dotenv

load_dotenv()

driver: dict[str, TestUIDriver] = {}
run_test_id = ""
last_returned_value = ""
extra_capabilities: dict = {}

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
    from appium.webdriver.common.touch_action import TouchAction
    d = _get_driver(_run_test_id).get_driver()
    TouchAction(d).tap(x=int(x), y=int(y)).perform()
    return f"tapped at ({x}, {y})"


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

import re
import ba_ws_sdk.streaming as streaming
from testui.support.testui_driver import TestUIDriver
from dotenv import load_dotenv

load_dotenv()

driver: dict[str, TestUIDriver] = {}
run_test_id = ""
last_returned_value = ""


def clean_html(html_content):
    for tag in ['script', 'style', 'svg']:
        html_content = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html_content, flags=re.DOTALL)
    return html_content


###############################################################################
# Below are your appium-related functions
###############################################################################
def create_driver(_run_test_id='1'):
    """
    Usage = create_driver({})
    Creates a driver that is necessary for the automation to run in the first place.
    Doesn't need any input values to the function and it returns success as string

    Returns whether an iOS or Android driver is created
    """
    global driver
    from testui.support.appium_driver import NewDriver
    import os
    if os.getenv("UDID_ANDROID"):
        udid = os.getenv("UDID_ANDROID")
    elif os.getenv("UDID_IOS"):
        udid = os.getenv("UDID_IOS")
    build_driver = (
        NewDriver()
        .set_logger()
        .set_udid(udid=udid)
        .set_extra_caps({"appium:chromedriverArgs": {}})
    )
    if os.getenv("APP_PACKAGE"):
        app_package = os.getenv("APP_PACKAGE")
        app_activity = os.getenv("APP_ACTIVITY")
        build_driver = (
            build_driver
            .set_app_package_activity(app_package=app_package, app_activity=app_activity)
        )
    if os.getenv("ACCESS_KEY") and os.getenv("ACCESS_TOKEN"):
        access_key = os.getenv("ACCESS_KEY")
        access_token = os.getenv("ACCESS_TOKEN")
        build_driver = (
            build_driver
            .set_extra_caps({"df:accesskey": access_key , "df:token": access_token, "df:liveVideo": False})
        )
    if os.getenv("APPIUM_URL") != "":
        appium_url = os.getenv("APPIUM_URL")
        build_driver = (
            build_driver
            .set_appium_url(appium_url)
        )
    if os.getenv("APP_PATH") and os.getenv("APP_PACKAGE") == "":
        app_path = os.getenv("APP_PATH")
        build_driver = (
            build_driver
            .set_app_path(app_path).set_full_reset(True)
            .set_extra_caps({"appium:enforceAppInstall": True, "appium:noReset": False})
        )
    if os.getenv("BUNDLE_ID") and os.getenv("UDID_IOS"):
        bundle_id = os.getenv("BUNDLE_ID")
        build_driver = (
            build_driver
            .set_platform('ios')
            .set_bundle_id(bundle_id=bundle_id)
        )
    driver[_run_test_id] = build_driver.set_appium_driver()
    streaming.start_stream(driver[_run_test_id], run_id="1", fps=1.0, jpeg_quality=10)
    return "success"

def stop_all_drivers(_run_test_id='1'):
    """
    Usage = stop_all_drivers({})
    Stops all the drivers that are running in this agent.
    Doesn't need any input values to the function and it returns  'All drivers stopped and entries cleared.'
    """
    global driver
    for run_id, drv in list(driver.items()):
        try:
            drv.quit()
            print(f"✅ Driver '{run_id}' stopped.")
        except Exception as e:
            print(f"⚠️ Error stopping driver '{run_id}': {e}")
    driver.clear()
    return "🗑️ All drivers stopped and entries cleared."

def stop_driver(_run_test_id='1'):
    """
    Usage = stop_driver({})
    Stops the driver so that later another one can take place,
    and it's always run at the end of the test case.
    Doesn't need any input values to the function and it returns success as string
    """
    global driver, last_returned_value
    try:
        streaming.stop_stream("1")
    except Exception:
        print("Failed to stop stream cleanly")
    driver[_run_test_id].quit()
    last_returned_value = "success"    
    return "success"


def send_keys(locator_type: str, locator: str, value: str = None, _run_test_id='1') -> str:
    """
    Usage = send_keys({"locator_type": "...", "locator": "...", "value": "..."})
    Types in the value in the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.

    if value is not set, then it will take the value from the returned value of the previous function call.
    """
    global driver, last_returned_value
    if value is None or value == "":
        value = last_returned_value
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).clear().send_keys(value=value)
    last_returned_value = value
    return "sent keys"

def exists(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = exists({"locator_type": "...", "locator": "..."})
    checks if element defined by its `locator_type` (id, css, xpath)
    and its locator path associated exists in the web page
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).wait_until_exists(seconds=10)
    return "exists"

def does_not_exist(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = does_not_exist({"locator_type": "...", "locator": "..."})
    checks if element defined by its `locator_type` (id, css, xpath)
    and its locator path associated does NOT exist in the web page
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).no().wait_until_visible(seconds=5)
    return "doesn't exists"

def click(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = click({"locator_type": "...", "locator": "..."})
    Clicks/Taps in the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).click()
    return "clicked successfully"

def long_press(locator_type: str, locator: str, time: str, _run_test_id='1') -> str:
    """
    Usage = long_press({"locator_type": "...", "locator": "...", "time": "..."})
    Long presses on the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).press_hold_for(float(time))
    return "long pressed successfully"


def get_page(_run_test_id='1') -> str:
    """
    Usage = get_page({})
    Returns the full DOM of the page (cleaned) so that you can parse it for exists or
    click, send_keys, etc. on some element.
    """
    global driver, last_returned_value
    content = driver[_run_test_id].get_driver().page_source
    html_content = clean_html(content)
    last_returned_value = html_content
    return html_content


def go_back(_run_test_id='1') -> str:
    """
    Usage = go_back({})
    Goes back in the browser history.
    """
    global driver
    driver[_run_test_id].back()
    return "went back"

def wait_seconds(time_sec, _run_test_id='1') -> str:
    """
    Usage = wait_seconds({"time": "..."})
    Waits for the specified number of seconds.
    """
    global driver
    import time
    time.sleep(float(time))
    return "waited successfully"

def get_attribute(locator_type: str, locator: str, attribute_name: str, _run_test_id='1') -> str:
    """
    Usage = get_attribute({"locator_type": "...", "locator": "...", "attribute_name": "..."})
    Gets the attribute value of the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.
    """
    global driver, last_returned_value
    attr_value = driver[_run_test_id].e(locator_type=locator_type, locator=locator).get_attribute(attribute_name)
    last_returned_value = attr_value
    return attr_value

def send_app_background(_run_test_id='1') -> str:
    """
    Usage = send_app_background({})
    Sends the app to background.
    """
    global driver
    driver[_run_test_id].background_app(-1)
    return "app in background"

def app_foreground(_run_test_id='1') -> str:
    """
    Usage = app_foreground({})
    Sends the app to foreground.
    """
    global driver
    import os
    if os.getenv("BUNDLE_ID"):
        driver[_run_test_id].get_driver().activate_app(os.getenv("BUNDLE_ID"))
    elif os.getenv("APP_PACKAGE"):
        driver[_run_test_id].get_driver().activate_app(os.getenv("APP_PACKAGE"))
    return "app in foreground"
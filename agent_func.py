import inspect
import re
import textwrap
import os
import streaming
from testui.support.testui_driver import TestUIDriver
from dotenv import load_dotenv

load_dotenv()

driver: dict[str, TestUIDriver] = {}
run_test_id = ""


def clean_html(html_content):
    for tag in ['script', 'style', 'svg']:
        html_content = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html_content, flags=re.DOTALL)
    return html_content

def log_function_definition(fn, *args, **kwargs):
    """
    Writes a transformed version of the function's source code to `function_calls.py`, removing:
      1. The `def function_name(...):` line
      2. Any `log_function_definition(...)` lines
      3. Replacing param=param with param="actual_value" for each argument actually passed
      4. Removing indentation
      6. Removing lines that start with 'return' (i.e., removing all return statements)
      7. Removing any triple-quoted docstrings, such as:
         \"\"\"
         This code is used like ...
         \"\"\"
    """

    # 1. Grab the original function source
    source = inspect.getsource(fn)

    # 2. Split into lines
    lines = source.splitlines()

    # 3. Remove the first line if it starts with 'def '
    trimmed_lines = []
    skip_first_def = True
    for line in lines:
        if skip_first_def and line.strip().startswith("def "):
            skip_first_def = False
            continue
        trimmed_lines.append(line)

    # 4. Remove lines containing `log_function_definition(...)`,
    #    lines that start with 'return', and lines that start with 'global'
    #    Also track and remove triple-quoted docstrings.
    filtered_lines = []
    in_docstring = False
    for line in trimmed_lines:
        stripped_line = line.strip()

        # Toggle docstring detection whenever we see triple quotes
        if '"""' in stripped_line:
            in_docstring = not in_docstring
            # We skip the line that has the triple quotes too
            continue

        # If we are inside a triple-quoted docstring, skip all those lines
        if in_docstring:
            continue

        # remove lines that call log_function_definition(...)
        if "log_function_definition(" in line:
            continue
        # remove lines that call log_function_definition(...)
        if "clean_html(" in line:
            continue
        # remove lines that start with "return"
        if stripped_line.startswith("return"):
            continue
        # remove lines that start with "global"
        if stripped_line.startswith("global"):
            continue

        filtered_lines.append(line)

    # 5. Replace references to parameters with actual values, e.g. param=param -> param="actual"
    from inspect import signature
    sig = signature(fn)
    param_names = list(sig.parameters.keys())

    # Pair them up: param -> actual_value
    param_values = {}
    # We'll assume *args align in order to param_names
    for name, val in zip(param_names, args):
        param_values[name] = val
    # And also handle any named arguments in **kwargs
    for k, v in kwargs.items():
        param_values[k] = v

    replaced_lines = []
    for line in filtered_lines:
        new_line = line

        # (A) Replace param=param with param="actual_val"
        for param, actual_val in param_values.items():
            pattern = rf"\b{param}={param}\b"
            repl = f'{param}={repr(actual_val)}'
            new_line = re.sub(pattern, repl, new_line)
        
        pattern = r"driver\[_run_test_id\]"
        repl = f'driver'
        new_line = re.sub(pattern, repl, new_line)

        replaced_lines.append(new_line)

    # 6. Dedent (remove indentation)
    dedented_code = textwrap.dedent("\n".join(replaced_lines)).rstrip() + "\n"

    # Ensure the 'tests' directory exists; if not, create it.
    directory = "tests"
    if not os.path.exists(directory):
        os.makedirs(directory)

    # Build the file path using os.path.join for portability.
    file_path = os.path.join(directory, f"function_calls{kwargs['_run_test_id']}.py")

    # 7. Append everything to function_calls.py in the tests directory
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(dedented_code)

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
    driver[_run_test_id] = (
        NewDriver()
        .set_logger()
        .set_udid(udid=udid)
        .set_extra_caps({"appium:chromedriverArgs": {}})
    )
    if os.getenv("APP_PACKAGE"):
        app_package = os.getenv("APP_PACKAGE")
        app_activity = os.getenv("APP_ACTIVITY")
        driver[_run_test_id] = (
            driver[_run_test_id]
            .set_app_package_activity(app_package=app_package, app_activity=app_activity)
        )
    if os.getenv("APPIUM_URL") != "":
        appium_url = os.getenv("APPIUM_URL")
        driver[_run_test_id] = (
            driver[_run_test_id]
            .set_appium_url(appium_url)
        )
    if os.getenv("APP_PATH") and os.getenv("APP_PACKAGE") == "":
        app_path = os.getenv("APP_PATH")
        driver[_run_test_id] = (
            driver[_run_test_id]
            .set_app_path(app_path)
            .set_extra_caps({"appium:enforceAppInstall": True})
        )
    if os.getenv("BUNDLE_ID") and os.getenv("UDID_IOS"):
        bundle_id = os.getenv("BUNDLE_ID")
        driver[_run_test_id] = (
            driver[_run_test_id]
            .set_platform('ios')
            .set_bundle_id(bundle_id=bundle_id)
        )
    driver[_run_test_id] = driver[_run_test_id].set_appium_driver()
    streaming.start_stream(driver[_run_test_id], run_id="1", fps=1.0, jpeg_quality=10)
    log_function_definition(create_driver, _run_test_id=_run_test_id)
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
    global driver
    try:
        streaming.stop_stream("1")
    except Exception:
        print("Failed to stop stream cleanly")
    driver[_run_test_id].quit()
    log_function_definition(stop_driver, _run_test_id=_run_test_id)
    return "success"


def send_keys(locator_type: str, locator: str, value: str, _run_test_id='1') -> str:
    """
    Usage = send_keys({"locator_type": "...", "locator": "...", "value": "..."})
    Types in the value in the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).clear().send_keys(value=value)
    log_function_definition(send_keys, locator_type, locator, value, _run_test_id=_run_test_id)
    return "sent keys"


def exists(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = exists({"locator_type": "...", "locator": "..."})
    checks if element defined by its `locator_type` (id, css, xpath)
    and its locator path associated exists in the web page
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).wait_until_visible(seconds=5)
    log_function_definition(exists, locator_type, locator, _run_test_id=_run_test_id)
    return "exists"

def does_not_exist(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = does_not_exist({"locator_type": "...", "locator": "..."})
    checks if element defined by its `locator_type` (id, css, xpath)
    and its locator path associated does NOT exist in the web page
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).no().wait_until_visible(seconds=5)
    log_function_definition(does_not_exist, locator_type, locator, _run_test_id=_run_test_id)
    return "doesn't exists"

def click(locator_type: str, locator: str, _run_test_id='1') -> str:
    """
    Usage = click({"locator_type": "...", "locator": "..."})
    Clicks/Taps in the element defined by its `locator_type` (id, css, xpath)
    and its locator path associated.
    """
    global driver
    driver[_run_test_id].e(locator_type=locator_type, locator=locator).click()
    log_function_definition(click, locator_type, locator, _run_test_id=_run_test_id)

    return "clicked successfully"


def get_page(_run_test_id='1') -> str:
    """
    Usage = get_page({})
    Returns the full DOM of the page (cleaned) so that you can parse it for exists or
    click, send_keys, etc. on some element.
    """
    global driver
    content = driver[_run_test_id].get_driver().page_source
    html_content = clean_html(content)
    return html_content


def go_back(_run_test_id='1') -> str:
    """
    Usage = go_back({})
    Goes back in the browser history.
    """
    global driver
    driver[_run_test_id].back()
    log_function_definition(go_back, _run_test_id=_run_test_id)
    return "went back"

def send_app_background(_run_test_id='1') -> str:
    """
    Usage = send_app_background({})
    Sends the app to background.
    """
    global driver
    driver[_run_test_id].background_app(-1)
    log_function_definition(send_app_background, _run_test_id=_run_test_id)
    return "app in background"

"""Shared fixtures for agent_func tests.

All external dependencies (Appium, TestUIDriver, ba_ws_sdk) are mocked so that
tests run without a real device or Appium server.
"""

import sys
import types
import os
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock heavy third-party modules before importing agent_func
# ---------------------------------------------------------------------------

def _install_mock_modules():
    """Insert mock modules into sys.modules so `import agent_func` succeeds."""
    # ba_ws_sdk
    ba_ws_sdk = types.ModuleType("ba_ws_sdk")
    ba_ws_sdk.streaming = MagicMock()
    sys.modules["ba_ws_sdk"] = ba_ws_sdk
    sys.modules["ba_ws_sdk.streaming"] = ba_ws_sdk.streaming

    # testui
    testui = types.ModuleType("testui")
    testui_support = types.ModuleType("testui.support")
    testui_driver_mod = types.ModuleType("testui.support.testui_driver")
    testui_driver_mod.TestUIDriver = MagicMock
    testui_appium = types.ModuleType("testui.support.appium_driver")
    testui_appium.NewDriver = MagicMock

    sys.modules["testui"] = testui
    sys.modules["testui.support"] = testui_support
    sys.modules["testui.support.testui_driver"] = testui_driver_mod
    sys.modules["testui.support.appium_driver"] = testui_appium

    # appium (for tap_coordinates)
    appium = types.ModuleType("appium")
    appium_wc = types.ModuleType("appium.webdriver")
    appium_wcc = types.ModuleType("appium.webdriver.common")
    appium_ta = types.ModuleType("appium.webdriver.common.touch_action")
    appium_ta.TouchAction = MagicMock
    sys.modules["appium"] = appium
    sys.modules["appium.webdriver"] = appium_wc
    sys.modules["appium.webdriver.common"] = appium_wcc
    sys.modules["appium.webdriver.common.touch_action"] = appium_ta


_install_mock_modules()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_agent_globals():
    """Reset agent_func global state before each test."""
    import agent_func

    agent_func.driver.clear()
    agent_func.last_returned_value = ""
    agent_func.extra_capabilities.clear()
    yield


@pytest.fixture()
def mock_testui_driver():
    """Return a MagicMock that behaves like a TestUIDriver instance.

    It has:
      - .get_driver() -> appium_driver mock (with page_source, swipe, etc.)
      - .e(locator_type, locator) -> element mock (with click, send_keys, etc.)
      - .back(), .quit(), .background_app()
    """
    appium_drv = MagicMock()
    appium_drv.page_source = "<hierarchy></hierarchy>"
    appium_drv.current_activity = ".MainActivity"
    appium_drv.get_window_size.return_value = {"width": 1080, "height": 1920}

    element = MagicMock()
    element.click.return_value = None
    element.clear.return_value = element
    element.send_keys.return_value = None
    element.get_attribute.return_value = "attr_value"
    element.wait_until_exists.return_value = element
    element.no.return_value = element
    element.wait_until_visible.return_value = element
    element.press_hold_for.return_value = None

    testui_drv = MagicMock()
    testui_drv.get_driver.return_value = appium_drv
    testui_drv.e.return_value = element
    testui_drv.back.return_value = None
    testui_drv.quit.return_value = None
    testui_drv.background_app.return_value = None

    return testui_drv


@pytest.fixture()
def register_driver(mock_testui_driver):
    """Register a mock driver in agent_func.driver['1']."""
    import agent_func
    agent_func.driver["1"] = mock_testui_driver
    return mock_testui_driver


@pytest.fixture()
def tmp_memory_dir(tmp_path, monkeypatch):
    """Point MEMORY_DIR to a temp directory for screen memory tests."""
    import agent_func
    monkeypatch.setattr(agent_func, "MEMORY_DIR", str(tmp_path))
    return tmp_path

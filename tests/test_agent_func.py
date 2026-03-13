"""Unit tests for agent_func.py.

All Appium / device interactions are mocked. No real device needed.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import agent_func


# ============================================================================
# Pure helpers
# ============================================================================

class TestCleanPageSource:
    def test_removes_script_tags(self):
        html = '<div><script type="text/javascript">alert(1)</script><p>hi</p></div>'
        assert "<script" not in agent_func._clean_page_source(html)
        assert "<p>hi</p>" in agent_func._clean_page_source(html)

    def test_removes_style_tags(self):
        html = "<style>body{color:red}</style><span>ok</span>"
        assert "<style" not in agent_func._clean_page_source(html)
        assert "<span>ok</span>" in agent_func._clean_page_source(html)

    def test_removes_svg_tags(self):
        html = '<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg><div>a</div>'
        result = agent_func._clean_page_source(html)
        assert "<svg" not in result
        assert "<div>a</div>" in result

    def test_leaves_clean_content_unchanged(self):
        xml = "<hierarchy><node text='Hello'/></hierarchy>"
        assert agent_func._clean_page_source(xml) == xml


class TestGenerateMemoryId:
    def test_format(self):
        mid = agent_func._generate_memory_id()
        assert mid.startswith("m_")
        assert len(mid) == 12  # "m_" + 10 hex chars

    def test_unique(self):
        ids = {agent_func._generate_memory_id() for _ in range(50)}
        assert len(ids) == 50


class TestFormatMemoriesBlock:
    def test_empty_list(self):
        assert agent_func._format_memories_block([]) == ""

    def test_single_memory(self):
        mems = [{"id": "m_abc", "category": "general", "observation": "test obs"}]
        result = agent_func._format_memories_block(mems)
        assert "SCREEN MEMORIES (1)" in result
        assert "[m_abc]" in result
        assert "test obs" in result

    def test_multiple_memories(self):
        mems = [
            {"id": "m_1", "category": "locator_hint", "observation": "use id"},
            {"id": "m_2", "category": "timing", "observation": "wait 2s"},
        ]
        result = agent_func._format_memories_block(mems)
        assert "SCREEN MEMORIES (2)" in result


class TestGetDriver:
    def test_raises_when_missing(self):
        with pytest.raises(RuntimeError, match="No driver found"):
            agent_func._get_driver("missing")

    def test_returns_driver(self, register_driver):
        assert agent_func._get_driver("1") is register_driver


# ============================================================================
# Capabilities
# ============================================================================

class TestSetCapabilities:
    def test_valid_json(self):
        result = agent_func.set_capabilities('{"appium:noReset": true}')
        assert "Capabilities set" in result
        assert agent_func.extra_capabilities == {"appium:noReset": True}

    def test_merges(self):
        agent_func.set_capabilities('{"a": 1}')
        agent_func.set_capabilities('{"b": 2}')
        assert agent_func.extra_capabilities == {"a": 1, "b": 2}

    def test_invalid_json(self):
        result = agent_func.set_capabilities("not json")
        assert "error: invalid JSON" in result

    def test_non_dict_json(self):
        result = agent_func.set_capabilities("[1, 2, 3]")
        assert "error: capabilities must be a JSON object" in result


class TestClearCapabilities:
    def test_clears(self):
        agent_func.extra_capabilities["foo"] = "bar"
        result = agent_func.clear_capabilities()
        assert "cleared" in result.lower()
        assert agent_func.extra_capabilities == {}


# ============================================================================
# Driver lifecycle
# ============================================================================

class TestCreateDriver:
    @patch.dict(os.environ, {"UDID_ANDROID": "emulator-5554", "APP_PACKAGE": "com.test", "APP_ACTIVITY": ".Main"}, clear=False)
    @patch("agent_func.streaming")
    def test_android_driver(self, mock_streaming):
        from testui.support.appium_driver import NewDriver
        mock_builder = MagicMock()
        mock_builder.set_logger.return_value = mock_builder
        mock_builder.set_udid.return_value = mock_builder
        mock_builder.set_extra_caps.return_value = mock_builder
        mock_builder.set_app_package_activity.return_value = mock_builder
        mock_builder.set_appium_driver.return_value = MagicMock()
        NewDriver.return_value = mock_builder

        result = agent_func.create_driver("test_run")
        assert "success" in result
        assert "Android" in result
        assert "test_run" in agent_func.driver

    @patch.dict(os.environ, {"UDID_ANDROID": "", "UDID_IOS": "", "APP_PACKAGE": ""}, clear=False)
    def test_no_udid_returns_error(self):
        # Clear both UDIDs
        with patch.dict(os.environ, {"UDID_ANDROID": "", "UDID_IOS": ""}, clear=False):
            os.environ.pop("UDID_ANDROID", None)
            os.environ.pop("UDID_IOS", None)
            result = agent_func.create_driver()
            assert "error" in result.lower()


class TestStopDriver:
    def test_stops_and_removes(self, register_driver):
        result = agent_func.stop_driver("1")
        assert result == "success"
        assert "1" not in agent_func.driver
        register_driver.quit.assert_called_once()

    def test_missing_driver_no_error(self):
        result = agent_func.stop_driver("nonexistent")
        assert result == "success"


class TestStopAllDrivers:
    def test_stops_all(self, mock_testui_driver):
        agent_func.driver["a"] = mock_testui_driver
        agent_func.driver["b"] = MagicMock()
        result = agent_func.stop_all_drivers()
        assert "stopped" in result.lower()
        assert len(agent_func.driver) == 0


# ============================================================================
# Element interaction
# ============================================================================

class TestClick:
    def test_click(self, register_driver):
        result = agent_func.click("id", "my_button")
        assert result == "clicked successfully"
        register_driver.e.assert_called_with(locator_type="id", locator="my_button")


class TestSendKeys:
    def test_with_value(self, register_driver):
        result = agent_func.send_keys("id", "input_field", "hello")
        assert result == "sent keys"
        assert agent_func.last_returned_value == "hello"

    def test_uses_last_returned_value(self, register_driver):
        agent_func.last_returned_value = "previous_value"
        result = agent_func.send_keys("id", "input_field")
        assert result == "sent keys"
        assert agent_func.last_returned_value == "previous_value"

    def test_empty_string_uses_last(self, register_driver):
        agent_func.last_returned_value = "prev"
        agent_func.send_keys("id", "input_field", "")
        assert agent_func.last_returned_value == "prev"


class TestLongPress:
    def test_long_press(self, register_driver):
        result = agent_func.long_press("id", "elem", "3")
        assert result == "long pressed successfully"
        register_driver.e.return_value.press_hold_for.assert_called_with(3.0)


class TestGetText:
    def test_returns_text(self, register_driver):
        register_driver.e.return_value.get_attribute.return_value = "Hello World"
        result = agent_func.get_text("id", "label")
        assert result == "Hello World"
        assert agent_func.last_returned_value == "Hello World"


class TestGetAttribute:
    def test_returns_attribute(self, register_driver):
        register_driver.e.return_value.get_attribute.return_value = "enabled"
        result = agent_func.get_attribute("id", "btn", "clickable")
        assert result == "enabled"
        assert agent_func.last_returned_value == "enabled"


# ============================================================================
# Assertions
# ============================================================================

class TestExists:
    def test_exists(self, register_driver):
        assert agent_func.exists("id", "elem") == "exists"

    def test_raises_on_timeout(self, register_driver):
        register_driver.e.return_value.wait_until_exists.side_effect = Exception("timeout")
        with pytest.raises(Exception):
            agent_func.exists("id", "missing_elem")


class TestDoesNotExist:
    def test_does_not_exist(self, register_driver):
        assert agent_func.does_not_exist("id", "elem") == "does not exist"


# ============================================================================
# Page & navigation
# ============================================================================

class TestGetPage:
    def test_returns_cleaned_source(self, register_driver):
        appium_drv = register_driver.get_driver.return_value
        appium_drv.page_source = "<hierarchy><script>bad</script><node/></hierarchy>"
        result = agent_func.get_page()
        assert "<script" not in result
        assert "<node/>" in result

    def test_sets_last_returned_value(self, register_driver):
        appium_drv = register_driver.get_driver.return_value
        appium_drv.page_source = "<root/>"
        agent_func.get_page()
        assert agent_func.last_returned_value == "<root/>"


class TestGoBack:
    def test_go_back(self, register_driver):
        assert agent_func.go_back() == "went back"
        register_driver.back.assert_called_once()


# ============================================================================
# Scrolling & swiping
# ============================================================================

class TestScrollDown:
    def test_scroll_down(self, register_driver):
        result = agent_func.scroll_down()
        assert result == "scrolled down"
        register_driver.get_driver.return_value.swipe.assert_called_once()


class TestScrollUp:
    def test_scroll_up(self, register_driver):
        result = agent_func.scroll_up()
        assert result == "scrolled up"
        register_driver.get_driver.return_value.swipe.assert_called_once()


class TestSwipe:
    @pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
    def test_valid_directions(self, register_driver, direction):
        result = agent_func.swipe(direction)
        assert f"swiped {direction}" == result

    def test_invalid_direction(self, register_driver):
        result = agent_func.swipe("diagonal")
        assert "error" in result


class TestScrollToElement:
    def test_found_immediately(self, register_driver):
        result = agent_func.scroll_to_element("id", "target")
        assert "found after 0 scrolls" in result

    def test_not_found(self, register_driver):
        register_driver.e.return_value.wait_until_exists.side_effect = Exception("not found")
        result = agent_func.scroll_to_element("id", "target", max_scrolls=2)
        assert "not found after 2 scrolls" in result


class TestTapCoordinates:
    def test_tap(self, register_driver):
        mock_action = MagicMock()
        mock_action.tap.return_value = mock_action
        mock_action.perform.return_value = None
        with patch("agent_func.TouchAction", return_value=mock_action, create=True):
            # Need to patch at import level since it's imported inside the function
            import appium.webdriver.common.touch_action as ta_mod
            ta_mod.TouchAction = MagicMock(return_value=mock_action)
            result = agent_func.tap_coordinates("100", "200")
            assert "tapped at (100, 200)" == result


# ============================================================================
# App lifecycle
# ============================================================================

class TestSendAppBackground:
    def test_background(self, register_driver):
        assert agent_func.send_app_background() == "app in background"
        register_driver.background_app.assert_called_with(-1)


class TestAppForeground:
    @patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False)
    def test_foreground(self, register_driver):
        assert agent_func.app_foreground() == "app in foreground"


# ============================================================================
# App management
# ============================================================================

class TestOpenApp:
    def test_open_with_clear(self, register_driver):
        with patch.dict(os.environ, {"UDID_IOS": ""}, clear=False):
            result = agent_func.open_app("com.test.app", clear_state="true")
            assert "opened" in result
            assert "state cleared" in result

    def test_open_without_clear(self, register_driver):
        result = agent_func.open_app("com.test.app", clear_state="false")
        assert "opened" in result
        assert "state cleared" not in result


class TestCloseApp:
    def test_close_with_id(self, register_driver):
        result = agent_func.close_app("com.test.app")
        assert "closed" in result

    def test_close_no_id_no_env(self, register_driver):
        with patch.dict(os.environ, {"BUNDLE_ID": "", "APP_PACKAGE": ""}, clear=False):
            os.environ.pop("BUNDLE_ID", None)
            os.environ.pop("APP_PACKAGE", None)
            result = agent_func.close_app("")
            assert "error" in result


class TestResetApp:
    def test_reset_with_id(self, register_driver):
        with patch.dict(os.environ, {"UDID_IOS": ""}, clear=False):
            result = agent_func.reset_app("com.test.app")
            assert "reset and reopened" in result

    def test_reset_no_id_uses_env(self, register_driver):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.env.app", "BUNDLE_ID": "", "UDID_IOS": ""}, clear=False):
            result = agent_func.reset_app("")
            assert "com.env.app" in result


class TestListApps:
    @patch.dict(os.environ, {"UDID_IOS": "iphone-123"}, clear=False)
    def test_ios_list(self, register_driver):
        appium_drv = register_driver.get_driver.return_value
        appium_drv.execute_script.return_value = [
            {"CFBundleIdentifier": "com.apple.settings"},
            {"CFBundleIdentifier": "com.test.app"},
        ]
        result = json.loads(agent_func.list_apps())
        assert result["platform"] == "iOS"
        assert result["app_count"] == 2

    @patch.dict(os.environ, {"UDID_IOS": ""}, clear=False)
    def test_android_list_via_shell(self, register_driver):
        appium_drv = register_driver.get_driver.return_value
        appium_drv.execute_script.return_value = "package:com.android.settings\npackage:com.test.app\n"
        result = json.loads(agent_func.list_apps())
        assert result["platform"] == "Android"
        assert result["app_count"] == 2

    @patch.dict(os.environ, {"UDID_IOS": "iphone-123"}, clear=False)
    def test_filter(self, register_driver):
        appium_drv = register_driver.get_driver.return_value
        appium_drv.execute_script.return_value = [
            {"CFBundleIdentifier": "com.apple.settings"},
            {"CFBundleIdentifier": "com.test.app"},
        ]
        result = json.loads(agent_func.list_apps(filter_keyword="test"))
        assert result["app_count"] == 1
        assert "com.test.app" in result["apps"]


# ============================================================================
# Screen memory
# ============================================================================

class TestScreenMemory:
    def test_save_and_retrieve(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            result = agent_func.save_screen_memory("/login", "username field uses accessibility id", "locator_hint")
            assert "Memory saved" in result

            memories = json.loads(agent_func.get_screen_memories("/login"))
            assert memories["memory_count"] == 1
            assert memories["memories"][0]["observation"] == "username field uses accessibility id"

    def test_deduplication(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            agent_func.save_screen_memory("/login", "same obs", "general")
            result = agent_func.save_screen_memory("/login", "same obs", "general")
            assert "already exists" in result

    def test_app_wide_memories_included(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            agent_func.save_screen_memory("/", "app-wide note", "general")
            agent_func.save_screen_memory("/settings", "settings note", "general")

            memories = json.loads(agent_func.get_screen_memories("/settings"))
            assert memories["memory_count"] == 2

    def test_update_memory(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            save_result = agent_func.save_screen_memory("/page", "old obs", "general")
            memory_id = save_result.split(": ")[1]

            update_result = agent_func.update_screen_memory(memory_id, "new obs")
            assert "updated" in update_result

            memories = json.loads(agent_func.get_screen_memories("/page"))
            assert memories["memories"][0]["observation"] == "new obs"

    def test_delete_memory(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            save_result = agent_func.save_screen_memory("/page", "to delete", "general")
            memory_id = save_result.split(": ")[1]

            delete_result = agent_func.update_screen_memory(memory_id, delete="true")
            assert "deleted" in delete_result

            memories = json.loads(agent_func.get_screen_memories("/page"))
            assert memories.get("memory_count", 0) == 0 or "No memories" in memories.get("message", "")

    def test_update_nonexistent(self, tmp_memory_dir):
        result = agent_func.update_screen_memory("m_nonexistent", "obs")
        assert "not found" in result

    def test_no_memories(self, tmp_memory_dir):
        with patch.dict(os.environ, {"APP_PACKAGE": "com.test", "BUNDLE_ID": ""}, clear=False):
            result = json.loads(agent_func.get_screen_memories("/nowhere"))
            assert "No memories" in result.get("message", "")


# ============================================================================
# Utilities
# ============================================================================

class TestWaitSeconds:
    @patch("agent_func.time_module")
    def test_wait(self, mock_time):
        result = agent_func.wait_seconds("2")
        assert "waited 2 seconds" in result
        mock_time.sleep.assert_called_with(2.0)


class TestHideKeyboard:
    def test_hide(self, register_driver):
        assert agent_func.hide_keyboard() == "keyboard hidden"

    def test_no_keyboard_no_error(self, register_driver):
        register_driver.get_driver.return_value.hide_keyboard.side_effect = Exception("no keyboard")
        assert agent_func.hide_keyboard() == "keyboard hidden"

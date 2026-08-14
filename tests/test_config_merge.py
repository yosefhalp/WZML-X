import importlib.util
from pathlib import Path
from unittest import TestCase


PATH = Path(__file__).parents[1] / "bot" / "core" / "config_merge.py"
SPEC = importlib.util.spec_from_file_location("config_merge_test", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigMergeTests(TestCase):
    def test_dashboard_password_change_does_not_erase_saved_session(self):
        old = {"WEB_ACCESS_PASSWORD": "old", "USER_SESSION_STRING": ""}
        new = {"WEB_ACCESS_PASSWORD": "new", "USER_SESSION_STRING": ""}
        saved = {
            "WEB_ACCESS_PASSWORD": "old",
            "USER_SESSION_STRING": "saved-session",
        }
        merged = MODULE.merge_changed_deploy_config(old, new, saved)
        self.assertEqual("new", merged["WEB_ACCESS_PASSWORD"])
        self.assertEqual("saved-session", merged["USER_SESSION_STRING"])

    def test_new_nonempty_session_from_deploy_is_applied(self):
        merged = MODULE.merge_changed_deploy_config(
            {"USER_SESSION_STRING": ""},
            {"USER_SESSION_STRING": "new-session"},
            {"USER_SESSION_STRING": "old-session"},
        )
        self.assertEqual("new-session", merged["USER_SESSION_STRING"])

    def test_nonsecret_empty_value_can_still_be_applied(self):
        merged = MODULE.merge_changed_deploy_config(
            {"LEECH_PREFIX": "prefix"},
            {"LEECH_PREFIX": ""},
            {"LEECH_PREFIX": "prefix"},
        )
        self.assertEqual("", merged["LEECH_PREFIX"])

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "isolated_task_view"
package = types.ModuleType(PACKAGE)
package.__path__ = []
sys.modules[PACKAGE] = package


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load(
    f"{PACKAGE}.status_view",
    ROOT / "bot" / "helper" / "ext_utils" / "status_view.py",
)
view = _load(
    f"{PACKAGE}.task_message_view",
    ROOT / "bot" / "helper" / "ext_utils" / "task_message_view.py",
)


class TaskMessageRtlTests(unittest.TestCase):
    def test_completion_has_hebrew_labels_and_ltr_values(self):
        message = view.rtl_block(
            view.completion_summary(
                name="Reacher.S04E03.mkv",
                size="5.83 GB",
                elapsed="2m 44s",
                input_mode="#Aria2",
                output_mode="#UphosterUpload",
            )
        )
        self.assertTrue(message.startswith(view.RLI))
        self.assertTrue(message.endswith(view.PDI))
        for label in ("המשימה הושלמה בהצלחה", "גודל", "זמן כולל", "מצב קלט", "מצב פלט"):
            self.assertIn(label, message)
        for value in ("Reacher.S04E03.mkv", "5.83 GB", "2m 44s"):
            self.assertIn(f"{view.LRI}{value}{view.PDI}", message)
        self.assertNotIn("Task Size", message)

    def test_failure_escapes_reason_and_keeps_owner_markup(self):
        message = view.failure_summary(
            title="ההעלאה נעצרה",
            reason="bad <token>",
            size="3.9 GB",
            elapsed="20s",
            input_mode="Telegram",
            output_mode="GoFile",
            owner_html="<a href='tg://user?id=7'>יוסף</a>",
        )
        self.assertIn("bad &lt;token&gt;", message)
        self.assertIn("tg://user?id=7", message)
        self.assertNotIn("Upload Stopped", message)

    def test_linked_file_escapes_url_and_name(self):
        line = view.linked_file_line(1, "https://x.test/?a='b", "a<b>.mkv")
        self.assertIn("&#x27;", line)
        self.assertIn("a&lt;b&gt;.mkv", line)


class LegacyMessagePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.he_ui = _load(
            f"{PACKAGE}.he_ui",
            ROOT / "bot" / "helper" / "languages" / "he_ui.py",
        )

    def test_legacy_screen_gets_rtl_wrapper_and_ltr_code(self):
        message = self.he_ui.prepare_message(
            "<b>Task Size</b>: <code>3.9 GB</code>"
        )
        self.assertTrue(message.startswith(chr(0x2067)))
        self.assertTrue(message.endswith(chr(0x2069)))
        self.assertIn("גודל המשימה", message)
        self.assertIn(f"<code>{chr(0x2066)}3.9 GB{chr(0x2069)}</code>", message)

    def test_prepared_screen_is_not_wrapped_twice(self):
        prepared = self.he_ui.prepare_message("<b>שלום</b>")
        self.assertEqual(prepared, self.he_ui.prepare_message(prepared))


if __name__ == "__main__":
    unittest.main()

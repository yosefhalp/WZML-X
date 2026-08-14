import importlib.util
import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path):
    """טוען מודול לוגיקה קטן בלי להפעיל את תהליך הבוט המלא."""

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HE_UI = _load_module(
    "he_ui_guided_bulk_test",
    ROOT / "bot" / "helper" / "languages" / "he_ui.py",
)
GUIDED = _load_module(
    "guided_ui_model_transport_test",
    ROOT / "bot" / "modules" / "guided_ui_model.py",
)
class GuidedBulkTransportTests(unittest.TestCase):
    def test_bulk_command_survives_the_hebrew_renderer_byte_for_byte(self):
        """מגן על התקלה שבה PDI סמוי הפך את ``-b`` לדגל לא מוכר."""

        mapped = GUIDED.guided_text_mode(
            "https://example.test/one\nhttps://example.test/two"
        )
        session = GUIDED.session_defaults("auto")
        session.update(destination="telegram", bulk=mapped["is_bulk"])
        command, handler = GUIDED.build_task_command(
            session,
            mapped["command_input"],
        )

        rendered = HE_UI.prepare_message(command)

        self.assertEqual("leech", handler)
        self.assertEqual("/leech -b", command)
        self.assertEqual(command, rendered)
        self.assertEqual(["/leech", "-b"], rendered.split())
        self.assertNotIn("\u2067", rendered)
        self.assertNotIn("\u2069", rendered)

    def test_follow_up_multi_command_also_remains_machine_readable(self):
        command = "/leech https://example.test/one -i 2 -ut"
        self.assertEqual(command, HE_UI.prepare_message(command))
        self.assertEqual("-ut", HE_UI.prepare_message(command).split()[-1])

    def test_regular_hebrew_screen_still_receives_rtl_isolation(self):
        rendered = HE_UI.prepare_message("המשימה מוכנה להפעלה")
        self.assertTrue(rendered.startswith("\u2067"))
        self.assertTrue(rendered.endswith("\u2069"))

    def test_every_legacy_help_button_has_a_hebrew_label(self):
        # קובץ העזרה מפעיל בעת import מנהל תוספים מלא. לצורך חוזה התוויות
        # קוראים רק את מפתחות המילונים מן ה-AST, בלי להפעיל שירותי בוט.
        help_path = ROOT / "bot" / "helper" / "ext_utils" / "help_messages.py"
        tree = ast.parse(help_path.read_text(encoding="utf-8"))
        relevant_names = {
            "_HE_COMMON_HELP",
            "MIRROR_HELP_DICT",
            "YT_HELP_DICT",
            "CLONE_HELP_DICT",
        }
        keys = set()
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            assigned_names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if not assigned_names & relevant_names:
                continue
            keys.update(
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        keys.discard("main")
        untranslated = {
            key
            for key in keys
            if HE_UI.translate_button(key) == key
            and any("a" <= char.casefold() <= "z" for char in key)
        }
        self.assertEqual(set(), untranslated)


if __name__ == "__main__":
    unittest.main()

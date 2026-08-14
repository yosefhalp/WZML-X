import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVER = ROOT / "web" / "wserver.py"
TEMPLATE = ROOT / "web" / "templates" / "landing.html"


class DashboardManagementContractTests(unittest.TestCase):
    def test_every_mutating_control_posts_with_csrf(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertGreaterEqual(template.count('action="/dashboard/action"'), 7)
        self.assertEqual(
            template.count('action="/dashboard/action"'),
            template.count('name="csrf" value="{{ csrf }}"'),
        )

    def test_dashboard_exposes_existing_bulk_engine_not_a_parallel_implementation(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("guided_text_mode", source)
        self.assertIn("build_task_command", source)
        self.assertIn('session["bulk"] = text_mode["is_bulk"]', source)
        self.assertIn("enqueue_task_request", source)
        worker = (
            ROOT / "bot" / "helper" / "ext_utils" / "task_control.py"
        ).read_text(encoding="utf-8")
        self.assertIn("reply_to_message_id=source.id if source else None", worker)
        self.assertIn('session["upload_source"] = upload_source', source)
        self.assertIn('session["upload_target"] = upload_target', source)

    def test_dashboard_exposes_premium_delivery_without_saved_messages(self):
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn('name="upload_source"', template)
        self.assertIn('name="upload_target"', template)
        self.assertIn('name="upload_channel"', template)
        self.assertIn("Userbot Premium", template)
        self.assertIn("פרטי — הצ׳אט עם הבוט", template)

    def test_dashboard_has_task_cache_backup_and_residual_controls(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        for action in (
            "start_task",
            "cancel_task",
            "cache_scan",
            "cache_clean",
            "clean_downloads",
            "backup_state",
            "backup_full",
        ):
            with self.subTest(action=action):
                self.assertIn(f'value="{action}"', template)

    def test_dashboard_is_scrollable_and_exposes_quick_navigation(self):
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("overflow-y:scroll", template)
        self.assertIn("min-height:100vh", template)
        self.assertIn('class="jump-nav"', template)
        for anchor in ("new-task", "cache", "active-tasks", "file-selection"):
            with self.subTest(anchor=anchor):
                self.assertIn(f'href="#{anchor}"', template)
                self.assertIn(f'id="{anchor}"', template)
        self.assertIn("מקור ויעד בשליטתך", template)
        self.assertIn("width:min(1680px,100%)", template)
        self.assertIn(".half { grid-column:span 6; }", template)
        self.assertIn("repeat(12,minmax(0,1fr))", template)

    def test_residual_cleanup_checks_both_bot_and_engine_activity(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("async with task_dict_lock", source)
        self.assertIn("selection = await _active_selection_tasks()", source)
        self.assertIn('active_ids.add("engine-active")', source)


if __name__ == "__main__":
    unittest.main()

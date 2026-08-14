import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "bot" / "helper" / "ext_utils" / "task_control.py"
SPEC = importlib.util.spec_from_file_location("task_control_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DashboardTaskControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.control = Path(self.temporary.name)
        MODULE.CONTROL_DIR = self.control
        MODULE.STATUS_FILE = self.control / "dashboard-task-status.json"
        MODULE.DEDUPE_FILE = self.control / "dashboard-task-dedupe.json"
        MODULE.REQUEST_LOCK = self.control / "dashboard-task-request.lock"

    def tearDown(self):
        self.temporary.cleanup()

    def test_request_is_atomic_private_and_keeps_bulk_source(self):
        request_id = MODULE.enqueue_task_request(
            command="/leech -b -ut",
            source_text="https://one.example\nhttps://two.example",
            requires_premium=True,
        )
        path = self.control / f"task-request-{request_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("/leech -b -ut", payload["command"])
        self.assertEqual(2, len(payload["source_text"].splitlines()))
        self.assertTrue(payload["requires_premium"])
        if os.name != "nt":
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_public_status_never_returns_command_or_links(self):
        MODULE._atomic_json(
            MODULE.STATUS_FILE,
            {
                "request_id": "123456789abc",
                "state": "success",
                "message": "נמסר",
                "updated_at": "2026-08-13T00:00:00+00:00",
                "command": "/leech secret",
                "source_text": "https://secret.example",
            },
        )

        status = MODULE.read_task_request_status()

        self.assertNotIn("command", status)
        self.assertNotIn("source_text", status)
        self.assertEqual("success", status["state"])

    def test_invalid_command_is_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "פקודת המשימה"):
            MODULE.enqueue_task_request(command="not-a-command")
        self.assertEqual([], list(self.control.glob("task-request-*.json")))

    def test_duplicate_submission_returns_same_request_without_second_file(self):
        first = MODULE.enqueue_task_request(
            command="/leech https://example.test/file", requires_premium=True
        )
        second = MODULE.enqueue_task_request(
            command="/leech https://example.test/file", requires_premium=True
        )

        self.assertEqual(first, second)
        self.assertEqual(1, len(list(self.control.glob("task-request-*.json"))))

    def test_status_filename_cannot_match_the_request_pattern(self):
        self.assertFalse(MODULE.STATUS_FILE.name.startswith("task-request-"))


if __name__ == "__main__":
    unittest.main()

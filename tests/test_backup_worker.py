import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BACKUP_CONTROL = _load(
    "backup_control_test",
    ROOT / "bot" / "helper" / "ext_utils" / "backup_control.py",
)
BACKUP_WORKER = _load(
    "backup_worker_test",
    ROOT / "deploy" / "server" / "backup_worker.py",
)
GUIDED_MODEL = _load(
    "guided_ui_model_backup_test",
    ROOT / "bot" / "modules" / "guided_ui_model.py",
)


class BackupControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        control = Path(self.temporary.name)
        self.original = (
            BACKUP_CONTROL.CONTROL_DIR,
            BACKUP_CONTROL.SETTINGS_FILE,
            BACKUP_CONTROL.STATUS_FILE,
            BACKUP_CONTROL.REQUEST_LOCK,
        )
        BACKUP_CONTROL.CONTROL_DIR = control
        BACKUP_CONTROL.SETTINGS_FILE = control / "backup-settings.json"
        BACKUP_CONTROL.STATUS_FILE = control / "backup-status.json"
        BACKUP_CONTROL.REQUEST_LOCK = control / "backup-request.lock"

    def tearDown(self):
        (
            BACKUP_CONTROL.CONTROL_DIR,
            BACKUP_CONTROL.SETTINGS_FILE,
            BACKUP_CONTROL.STATUS_FILE,
            BACKUP_CONTROL.REQUEST_LOCK,
        ) = self.original
        self.temporary.cleanup()

    def test_request_is_atomic_and_blocks_a_second_job(self):
        job_id = BACKUP_CONTROL.request_full_backup(chat_id=12345)
        request = BACKUP_CONTROL.CONTROL_DIR / f"backup-request-{job_id}.json"
        payload = json.loads(request.read_text(encoding="utf-8"))

        self.assertEqual(
            {"version", "job_id", "chat_id", "origin", "mode", "include_images", "created_at"},
            set(payload),
        )
        self.assertEqual(12345, payload["chat_id"])
        self.assertEqual("full", payload["mode"])
        self.assertTrue(payload["include_images"])
        self.assertTrue(BACKUP_CONTROL.REQUEST_LOCK.is_file())
        self.assertEqual("queued", BACKUP_CONTROL.read_backup_status().state)
        with self.assertRaisesRegex(RuntimeError, "כבר קיים גיבוי"):
            BACKUP_CONTROL.request_full_backup(chat_id=12345)

    def test_container_created_files_are_assigned_to_the_host_worker_owner(self):
        owner = BACKUP_CONTROL.CONTROL_DIR.stat()
        with patch.object(BACKUP_CONTROL.os, "fchown", create=True) as fchown:
            BACKUP_CONTROL._match_parent_owner(77, BACKUP_CONTROL.CONTROL_DIR)
        fchown.assert_called_once_with(77, owner.st_uid, owner.st_gid)

    def test_daily_setting_is_persistent_and_uses_owner_chat(self):
        settings = BACKUP_CONTROL.ensure_backup_settings(98765)
        self.assertTrue(settings.daily_enabled)
        self.assertEqual((4, 15, 98765), (settings.daily_hour, settings.daily_minute, settings.daily_chat_id))

        BACKUP_CONTROL.set_daily_backup(enabled=False, chat_id=98765)
        reloaded = BACKUP_CONTROL.read_backup_settings()
        self.assertFalse(reloaded.daily_enabled)
        self.assertEqual(98765, reloaded.daily_chat_id)

    def test_daily_time_buttons_adjust_and_wrap_without_losing_settings(self):
        settings = BACKUP_CONTROL.ensure_backup_settings(98765)
        settings.daily_enabled = False
        settings.daily_hour = 23
        settings.daily_minute = 45
        BACKUP_CONTROL.save_backup_settings(settings)

        changed = BACKUP_CONTROL.adjust_daily_backup_time(minutes=15, chat_id=98765)
        self.assertEqual((0, 0), (changed.daily_hour, changed.daily_minute))
        self.assertFalse(changed.daily_enabled)
        changed = BACKUP_CONTROL.adjust_daily_backup_time(minutes=-60, chat_id=98765)
        self.assertEqual((23, 0), (changed.daily_hour, changed.daily_minute))
        self.assertEqual("Asia/Jerusalem", changed.daily_timezone)
        self.assertEqual(98765, changed.daily_chat_id)

    def test_daily_time_adjustment_rejects_unapproved_steps(self):
        with self.assertRaisesRegex(ValueError, "אינו נתמך"):
            BACKUP_CONTROL.adjust_daily_backup_time(minutes=7, chat_id=98765)

    def test_fast_handoff_request_is_explicitly_without_images(self):
        job_id = BACKUP_CONTROL.request_backup(
            chat_id=12345,
            include_images=False,
        )
        payload = json.loads(
            (BACKUP_CONTROL.CONTROL_DIR / f"backup-request-{job_id}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("state", payload["mode"])
        self.assertFalse(payload["include_images"])

    def test_daily_request_cannot_be_created_without_images(self):
        with self.assertRaisesRegex(ValueError, "גיבוי יומי"):
            BACKUP_CONTROL.request_backup(
                chat_id=12345,
                include_images=False,
                origin="daily",
            )

    def test_status_reader_exposes_only_the_fixed_schema(self):
        BACKUP_CONTROL.STATUS_FILE.write_text(
            json.dumps({"state": "success", "delivered": True, "bot_token": "secret"}),
            encoding="utf-8",
        )
        status = BACKUP_CONTROL.read_backup_status()
        self.assertEqual("success", status.state)
        self.assertTrue(status.delivered)
        self.assertFalse(hasattr(status, "bot_token"))

    def test_backup_callback_parser_covers_schedule_actions(self):
        for callback in (
            "ui backup",
            "ui backup handoff",
            "ui backup full",
            "ui backup state",
            "ui backup daily",
            "ui backup dailyrun",
            "ui backup refresh",
            "ui backup restore",
            "ui backup dailyon",
            "ui backup dailyoff",
            "ui backup timem60",
            "ui backup timep60",
            "ui backup timem15",
            "ui backup timep15",
            "ui backup guide 012345abcdef",
        ):
            self.assertEqual("backup", GUIDED_MODEL.parse_ui_callback(callback)[0])
        with self.assertRaises(ValueError):
            GUIDED_MODEL.parse_ui_callback("ui backup delete")


class BackupWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.control = self.project / "runtime" / "control"
        self.backups = root / "backups"
        self.control.mkdir(parents=True)
        self.backups.mkdir()
        self.original = (
            BACKUP_WORKER.PROJECT_DIR,
            BACKUP_WORKER.CONTROL_DIR,
            BACKUP_WORKER.BACKUP_ROOT,
            BACKUP_WORKER.SETTINGS_FILE,
            BACKUP_WORKER.STATUS_FILE,
            BACKUP_WORKER.DAILY_LEDGER_FILE,
            BACKUP_WORKER.REQUEST_LOCK,
        )
        BACKUP_WORKER.PROJECT_DIR = self.project
        BACKUP_WORKER.CONTROL_DIR = self.control
        BACKUP_WORKER.BACKUP_ROOT = self.backups
        BACKUP_WORKER.SETTINGS_FILE = self.control / "backup-settings.json"
        BACKUP_WORKER.STATUS_FILE = self.control / "backup-status.json"
        BACKUP_WORKER.DAILY_LEDGER_FILE = self.control / "backup-daily-ledger.json"
        BACKUP_WORKER.REQUEST_LOCK = self.control / "backup-request.lock"

    def tearDown(self):
        (
            BACKUP_WORKER.PROJECT_DIR,
            BACKUP_WORKER.CONTROL_DIR,
            BACKUP_WORKER.BACKUP_ROOT,
            BACKUP_WORKER.SETTINGS_FILE,
            BACKUP_WORKER.STATUS_FILE,
            BACKUP_WORKER.DAILY_LEDGER_FILE,
            BACKUP_WORKER.REQUEST_LOCK,
        ) = self.original
        self.temporary.cleanup()

    def _request(self, job_id="012345abcdef"):
        path = self.control / f"backup-request-{job_id}.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "job_id": job_id,
                    "chat_id": 12345,
                    "origin": "manual",
                    "mode": "full",
                    "include_images": True,
                    "created_at": "2026-08-12T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        BACKUP_WORKER.REQUEST_LOCK.write_text(job_id, encoding="ascii")
        return path

    def _managed_archive(self, size=64):
        archive = self.backups / "wzmlx-full-20260812T120000Z.tar"
        archive.write_bytes(b"x" * size)
        (self.backups / f"{archive.name}.managed").write_text("version=1\n", encoding="utf-8")
        (self.backups / "LATEST").write_text(str(archive), encoding="utf-8")
        return archive

    def test_daily_scheduler_queues_one_full_request(self):
        BACKUP_WORKER.SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "daily_enabled": True,
                    "daily_hour": 4,
                    "daily_minute": 15,
                    "daily_chat_id": 12345,
                }
            ),
            encoding="utf-8",
        )
        now = datetime(2026, 8, 12, 4, 16, tzinfo=ZoneInfo("Asia/Jerusalem"))
        self.assertTrue(BACKUP_WORKER.queue_daily_backup_if_due(now))
        requests = list(self.control.glob("backup-request-*.json"))
        self.assertEqual(1, len(requests))
        payload = json.loads(requests[0].read_text(encoding="utf-8"))
        self.assertEqual("daily", payload["origin"])
        self.assertEqual("full", payload["mode"])
        self.assertTrue(payload["include_images"])
        self.assertFalse(BACKUP_WORKER.queue_daily_backup_if_due(now))

    def test_daily_ledger_blocks_a_duplicate_after_status_is_overwritten(self):
        BACKUP_WORKER.SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "daily_enabled": True,
                    "daily_hour": 4,
                    "daily_minute": 15,
                    "daily_chat_id": 12345,
                }
            ),
            encoding="utf-8",
        )
        now = datetime(2026, 8, 12, 4, 16, tzinfo=ZoneInfo("Asia/Jerusalem"))
        self.assertTrue(BACKUP_WORKER.queue_daily_backup_if_due(now))

        # מדמה מסך ידני שכתב סטטוס ישן ואיבד את השדה של המתזמן.
        BACKUP_WORKER.STATUS_FILE.write_text(
            json.dumps({"version": 1, "state": "success"}),
            encoding="utf-8",
        )
        for request in self.control.glob("backup-request-*.json"):
            request.unlink()
        BACKUP_WORKER.REQUEST_LOCK.unlink()

        self.assertFalse(BACKUP_WORKER.queue_daily_backup_if_due(now))
        ledger = json.loads(BACKUP_WORKER.DAILY_LEDGER_FILE.read_text(encoding="utf-8"))
        self.assertEqual("2026-08-12", ledger["last_attempt_date"])
        self.assertFalse(list(self.control.glob("backup-request-*.json")))

    def test_daily_delivery_has_a_server_independent_rich_guide(self):
        archive = self.backups / "wzmlx-full-20260812T120000Z.tar"
        rich = BACKUP_WORKER._deployment_rich_message(
            archive,
            "012345abcdef",
            "full",
        )
        self.assertTrue(rich["is_rtl"])
        self.assertIn("<details", rich["html"])
        self.assertIn(archive.name, rich["html"])
        self.assertIn("012345abcdef", rich["html"])
        self.assertIn("Worker הגיבוי", rich["html"])
        self.assertIn("systemctl --user is-active", rich["html"])
        self.assertIn("חזרה לאחור", rich["html"])
        self.assertNotIn("callback_data", rich["html"])
        self.assertNotIn("פתח מדריך פריסה", rich["html"])

    def test_rich_deployment_guide_is_rtl_and_uses_the_actual_archive(self):
        archive = self.backups / "wzmlx-state-20260812T120000Z.tar"
        rich = BACKUP_WORKER._deployment_rich_message(
            archive,
            "012345abcdef",
            "state",
        )
        self.assertTrue(rich["is_rtl"])
        self.assertIn(archive.name, rich["html"])
        self.assertIn("ללא קובצי Image", rich["html"])
        self.assertIn("<details>", rich["html"])
        self.assertIn("Worker הגיבוי", rich["html"])
        self.assertIn("חזרה לאחור", rich["html"])
        self.assertNotIn("callback_data", rich["html"])

    def test_full_flow_requires_verify_restore_and_telegram_confirmation(self):
        request = self._request()
        archive = self._managed_archive()
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        with (
            patch.object(BACKUP_WORKER, "_bot_token", return_value="12345:" + "a" * 24),
            patch.object(BACKUP_WORKER, "_send_message") as send_message,
            patch.object(BACKUP_WORKER, "_send_rich_message") as send_rich,
            patch.object(BACKUP_WORKER, "_send_document") as send_document,
            patch.object(BACKUP_WORKER.subprocess, "run", return_value=completed) as run,
        ):
            BACKUP_WORKER.process_request(request)

        status = json.loads(BACKUP_WORKER.STATUS_FILE.read_text(encoding="utf-8"))
        self.assertEqual("success", status["state"])
        self.assertTrue(status["integrity_verified"])
        self.assertTrue(status["restore_verified"])
        self.assertTrue(status["delivered"])
        self.assertEqual(3, run.call_count)
        send_document.assert_called_once()
        send_message.assert_called_once()
        send_rich.assert_called_once()
        rich_payload = send_rich.call_args.args[2]
        self.assertTrue(rich_payload["is_rtl"])
        self.assertIn("<details>", rich_payload["html"])
        self.assertTrue(archive.exists(), "ארכיון שנמסר צריך להישאר נגיש לפי מדיניות השימור")
        self.assertFalse(request.exists())
        self.assertFalse(BACKUP_WORKER.REQUEST_LOCK.exists())

    def test_oversized_archive_is_not_sent(self):
        request = self._request()
        archive = self._managed_archive()
        # truncate יוצר קובץ sparse מהיר ואינו מקצה בפועל שני גיגה־בתים בדיסק.
        with archive.open("r+b") as handle:
            handle.truncate(BACKUP_WORKER.TELEGRAM_MAX_BYTES + 1)
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with (
            patch.object(BACKUP_WORKER, "_bot_token", return_value="12345:" + "a" * 24),
            patch.object(BACKUP_WORKER, "_send_message"),
            patch.object(BACKUP_WORKER, "_send_document") as send_document,
            patch.object(BACKUP_WORKER.subprocess, "run", return_value=completed),
        ):
            with self.assertRaisesRegex(RuntimeError, "2000MB"):
                BACKUP_WORKER.process_request(request)
        send_document.assert_not_called()
        self.assertTrue(archive.exists())

    def test_errors_redact_tokens_and_paths(self):
        secret = "123456:" + "A" * 24
        text = BACKUP_WORKER._safe_error_text(
            RuntimeError(f"{secret} {self.project} http://127.0.0.1:8081/bot{secret}/sendDocument")
        )
        self.assertNotIn(secret, text)
        self.assertNotIn(str(self.project), text)

    def test_request_rejects_extra_fields(self):
        with self.assertRaisesRegex(ValueError, "שדות שאינם מותרים"):
            BACKUP_WORKER._validate_request(
                {
                    "version": 1,
                    "job_id": "012345abcdef",
                    "chat_id": 12345,
                    "origin": "manual",
                    "mode": "full",
                    "include_images": True,
                    "created_at": "now",
                    "command": "dangerous",
                }
            )

    def test_retention_targets_only_managed_markers(self):
        script = (ROOT / "deploy" / "server" / "full-backup.sh").read_text(encoding="utf-8")
        self.assertIn('wzmlx-${backup_mode}-*.tar.managed', script)
        self.assertIn('old_archive="${old_marker%.managed}"', script)
        self.assertNotIn("-name 'wzmlx-full-*.tar' -printf", script)

    def test_backup_verifier_requires_the_worker_and_its_installer(self):
        script = (ROOT / "deploy" / "server" / "verify-full-backup.sh").read_text(
            encoding="utf-8"
        )
        for required in (
            "./deploy/server/backup_worker.py",
            "./deploy/server/install-daily-backup.sh",
            "./deploy/server/full-backup.sh",
            "./deploy/server/full-restore.sh",
        ):
            self.assertIn(required, script)
        self.assertIn('source_listing="$(tar -tzf "${source_archive}")"', script)
        self.assertNotIn('tar -tzf "${source_archive}" | grep -Fxq', script)


if __name__ == "__main__":
    unittest.main()

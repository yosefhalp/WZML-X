import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CACHE_CONTROL = _load(
    "cache_control_host_test",
    ROOT / "bot" / "helper" / "ext_utils" / "cache_control.py",
)
CACHE_WORKER = _load(
    "cache_worker_host_test",
    ROOT / "deploy" / "server" / "backup_worker.py",
)


class CacheControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        control = Path(self.temporary.name)
        self.original = (
            CACHE_CONTROL.CONTROL_DIR,
            CACHE_CONTROL.STATUS_FILE,
            CACHE_CONTROL.REQUEST_LOCK,
        )
        CACHE_CONTROL.CONTROL_DIR = control
        CACHE_CONTROL.STATUS_FILE = control / "cache-status.json"
        CACHE_CONTROL.REQUEST_LOCK = control / "cache-request.lock"

    def tearDown(self):
        CACHE_CONTROL.CONTROL_DIR, CACHE_CONTROL.STATUS_FILE, CACHE_CONTROL.REQUEST_LOCK = self.original
        self.temporary.cleanup()

    def test_scan_request_is_atomic_and_blocks_double_click(self):
        request_id = CACHE_CONTROL.request_cache_action("scan")
        request = CACHE_CONTROL.CONTROL_DIR / f"cache-request-{request_id}.json"
        payload = json.loads(request.read_text(encoding="utf-8"))
        self.assertEqual("scan", payload["action"])
        self.assertEqual("queued", CACHE_CONTROL.read_cache_status().state)
        with self.assertRaises(RuntimeError):
            CACHE_CONTROL.request_cache_action("clean_safe")

    def test_container_created_cache_files_use_the_worker_owner(self):
        owner = CACHE_CONTROL.CONTROL_DIR.stat()
        with patch.object(CACHE_CONTROL.os, "fchown", create=True) as fchown:
            CACHE_CONTROL._match_parent_owner(88, CACHE_CONTROL.CONTROL_DIR)
        fchown.assert_called_once_with(88, owner.st_uid, owner.st_gid)

    def test_status_schema_does_not_expose_paths_or_commands(self):
        CACHE_CONTROL.STATUS_FILE.write_text(
            json.dumps(
                {
                    "state": "success",
                    "docker_reclaimable_bytes": 123,
                    "host_path": "/secret/path",
                    "command": "rm something",
                }
            ),
            encoding="utf-8",
        )
        status = CACHE_CONTROL.read_cache_status()
        self.assertEqual(123, status.docker_reclaimable_bytes)
        self.assertFalse(hasattr(status, "host_path"))
        self.assertFalse(hasattr(status, "command"))


class CacheWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.control = root / "control"
        self.control.mkdir()
        self.original = (
            CACHE_WORKER.CONTROL_DIR,
            CACHE_WORKER.CACHE_STATUS_FILE,
            CACHE_WORKER.CACHE_REQUEST_LOCK,
        )
        CACHE_WORKER.CONTROL_DIR = self.control
        CACHE_WORKER.CACHE_STATUS_FILE = self.control / "cache-status.json"
        CACHE_WORKER.CACHE_REQUEST_LOCK = self.control / "cache-request.lock"

    def tearDown(self):
        CACHE_WORKER.CONTROL_DIR, CACHE_WORKER.CACHE_STATUS_FILE, CACHE_WORKER.CACHE_REQUEST_LOCK = self.original
        self.temporary.cleanup()

    def _request(self, action="clean_safe"):
        request_id = "012345abcdef"
        path = self.control / f"cache-request-{request_id}.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "request_id": request_id,
                    "action": action,
                    "created_at": "2026-08-12T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        CACHE_WORKER.CACHE_REQUEST_LOCK.write_text(request_id, encoding="ascii")
        return path

    def test_docker_sizes_are_parsed(self):
        self.assertEqual(4_114_000_000, CACHE_WORKER._size_bytes("4.114GB"))
        self.assertEqual(0, CACHE_WORKER._size_bytes("-9.1GB"))
        self.assertEqual(10_340_000, CACHE_WORKER._size_bytes("10.34MB (10%)"))

    def test_safe_cleanup_only_prunes_old_build_cache(self):
        before = {
            "python_files": 3,
            "python_bytes": 100,
            "docker_build_count": 10,
            "docker_build_bytes": 1000,
            "docker_reclaimable_bytes": 800,
            "bot_api_files": 4,
            "bot_api_bytes": 400,
            "bot_api_large_files": 1,
            "bot_api_large_bytes": 200,
            "bot_api_old_files": 1,
            "bot_api_old_bytes": 200,
        }
        after = {**before, "python_files": 0, "python_bytes": 0, "docker_build_bytes": 300}
        request = self._request()
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with (
            patch.object(CACHE_WORKER, "_cache_snapshot", side_effect=[before, after]),
            patch.object(CACHE_WORKER, "_python_cache_info", return_value=(3, 100)),
            patch.object(CACHE_WORKER.subprocess, "run", return_value=completed) as run,
        ):
            CACHE_WORKER.process_cache_request(request)
        command = run.call_args.args[0]
        self.assertEqual(["docker", "builder", "prune", "--force", "--filter", "until=168h"], command)
        status = json.loads(CACHE_WORKER.CACHE_STATUS_FILE.read_text(encoding="utf-8"))
        self.assertEqual("success", status["state"])
        self.assertEqual(800, status["removed_bytes"])
        self.assertEqual(400, status["bot_api_bytes"], "מטמון Bot API צריך להימדד אך לא להימחק")

    def test_worker_source_never_deletes_shared_bot_api_cache(self):
        source = (ROOT / "deploy" / "server" / "backup_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("docker exec tg-bot-api rm", source)
        self.assertNotIn("docker volume prune", source)
        self.assertNotIn("docker image prune", source)

    def test_bot_api_scan_uses_nul_paths_and_never_publishes_names(self):
        now = 2_000_000_000
        discovered = SimpleNamespace(
            returncode=0,
            stdout=b"/var/lib/telegram-bot-api/media.bin\0/var/lib/telegram-bot-api/state.db\0",
            stderr=b"",
        )
        measured = SimpleNamespace(
            returncode=0,
            stdout=f"52428800|{now}\n1024|{now}\n".encode(),
            stderr=b"",
        )
        with (
            patch.object(CACHE_WORKER.subprocess, "run", side_effect=[discovered, measured]) as run,
            patch.object(CACHE_WORKER.time, "time", return_value=now),
        ):
            result = CACHE_WORKER._bot_api_cache_info()
        self.assertEqual((1, 52428800, 1, 52428800, 0, 0, 1, 1024), result)
        self.assertIn("-print0", run.call_args_list[0].args[0])
        self.assertEqual("%s|%Y", run.call_args_list[1].args[0][5])


if __name__ == "__main__":
    unittest.main()

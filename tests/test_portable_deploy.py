import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "deploy" / "server"
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location("portable_deploy", SERVER_DIR / "portable_deploy.py")
portable_deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(portable_deploy)


class PortableDeployTests(unittest.TestCase):
    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                member = tarfile.TarInfo("../outside.txt")
                payload = b"forbidden"
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
            with self.assertRaises(portable_deploy.DeploymentError):
                portable_deploy.safe_extract(archive, root / "target")
            self.assertFalse((root / "outside.txt").exists())

    def test_safe_extract_rejects_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "link.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                member = tarfile.TarInfo("escape")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                bundle.addfile(member)
            with self.assertRaises(portable_deploy.DeploymentError):
                portable_deploy.safe_extract(archive, root / "target")

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(portable_deploy.DeploymentError):
                portable_deploy.read_state({"DEPLOYMENT_STATE_FILE": str(state_path)})

    def test_external_bot_api_is_checked_without_starting_it(self):
        values = {
            "WZMLX_BOT_API_MODE": "external",
            "WZMLX_BOT_API_BASE_URL": "http://127.0.0.1:18081",
            "DEPLOYMENT_TEST_MODE": "1",
        }
        with patch.object(portable_deploy.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            portable_deploy, "run"
        ) as run_mock, patch.object(portable_deploy, "check_url") as check_mock:
            portable_deploy.preflight(values)
        run_mock.assert_called_once_with(["docker", "compose", "version"])
        check_mock.assert_called_once_with("http://127.0.0.1:18081")

    def test_managed_bot_api_is_not_treated_as_external_dependency(self):
        values = {"WZMLX_BOT_API_MODE": "managed", "DEPLOYMENT_TEST_MODE": "1"}
        with patch.object(portable_deploy.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            portable_deploy, "run"
        ), patch.object(portable_deploy, "check_url") as check_mock:
            portable_deploy.preflight(values)
        check_mock.assert_not_called()

    def test_status_contains_no_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            state.write_text(json.dumps({"version": 1, "current": "r2", "previous": "r1"}), encoding="utf-8")
            values = {
                "DEPLOYMENT_NAME": "test",
                "DEPLOYMENT_ROOT": str(root),
                "DEPLOYMENT_STATE_FILE": str(state),
                "DEPLOYMENT_CURRENT_LINK": str(root / "current"),
                "WZMLX_BOT_API_MODE": "external",
                "BOT_TOKEN": "must-not-leak",
            }
            result = portable_deploy.status(values)
            self.assertNotIn("must-not-leak", json.dumps(result))
            self.assertEqual("r2", result["current"])

    def test_cleanup_requires_matching_owner_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "deployment"
            root.mkdir()
            (root / ".deployment-owner").write_text("another-project\n", encoding="utf-8")
            values = {
                "DEPLOYMENT_NAME": "our-project",
                "DEPLOYMENT_ROOT": str(root),
                "DEPLOYMENT_STATE_FILE": str(root / "state.json"),
            }
            with self.assertRaises(portable_deploy.DeploymentError):
                portable_deploy.cleanup(values, "our-project")
            self.assertTrue(root.exists())


if __name__ == "__main__":
    unittest.main()

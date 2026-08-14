import importlib.util
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "deploy" / "server"
SPEC = importlib.util.spec_from_file_location("deployctl", SERVER_DIR / "deployctl.py")
deployctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deployctl)


class DeployControllerTests(unittest.TestCase):
    def test_example_profile_has_complete_schema(self):
        values = deployctl.load_profile(SERVER_DIR / "controller.env.example")
        self.assertEqual("1", values["CONTROLLER_PROFILE_VERSION"])
        self.assertIn("LOCAL_DEPLOYMENT_ENV_FILE", values)

    def test_duplicate_profile_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.env"
            path.write_text("CONTROLLER_NAME=test\nCONTROLLER_NAME=test\n", encoding="utf-8")
            with self.assertRaises(deployctl.ControllerError):
                deployctl.load_profile(path)

    def test_repository_package_excludes_ignored_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            (repository / ".gitignore").write_text("deployment.env\n", encoding="utf-8")
            (repository / "public.txt").write_text("public", encoding="utf-8")
            (repository / "deployment.env").write_text("BOT_TOKEN=forbidden", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "public.txt"], cwd=repository, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"],
                cwd=repository,
                check=True,
            )
            archive = repository / "release.tar.gz"
            deployctl.package_repository(repository, archive)
            with tarfile.open(archive, "r:gz") as bundle:
                names = set(bundle.getnames())
            self.assertIn("public.txt", names)
            self.assertNotIn("deployment.env", names)

    def test_remote_paths_must_be_absolute(self):
        text = (SERVER_DIR / "controller.env.example").read_text(encoding="utf-8")
        text = text.replace("REMOTE_CONTROLLER_DIR=/var/lib/wzmlx/controller", "REMOTE_CONTROLLER_DIR=../escape")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.env"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(deployctl.ControllerError):
                deployctl.load_profile(path)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "server" / "deployment_profile.py"
EXAMPLE_PATH = ROOT / "deploy" / "server" / "deployment.env.example"
SPEC = importlib.util.spec_from_file_location("deployment_profile", MODULE_PATH)
deployment_profile = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deployment_profile)


class DeploymentProfileTests(unittest.TestCase):
    def setUp(self):
        self.values = deployment_profile.load_env(EXAMPLE_PATH)

    def test_example_is_valid(self):
        self.assertEqual([], deployment_profile.validate(self.values))

    def test_duplicate_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.env"
            path.write_text("DEPLOYMENT_VERSION=1\nDEPLOYMENT_VERSION=1\n", encoding="utf-8")
            with self.assertRaises(deployment_profile.DeploymentProfileError):
                deployment_profile.load_env(path)

    def test_root_and_path_escape_are_rejected(self):
        values = dict(self.values)
        values["DEPLOYMENT_ROOT"] = "/"
        values["WZMLX_CONFIG_PATH"] = "/etc/wzmlx/config.py"
        errors = deployment_profile.validate(values)
        self.assertTrue(any("DEPLOYMENT_ROOT" in error for error in errors))
        self.assertTrue(any("WZMLX_CONFIG_PATH" in error for error in errors))

    def test_port_collision_is_rejected(self):
        values = dict(self.values)
        values["WZMLX_MONGO_PORT"] = values["WZMLX_HOST_PORT"]
        self.assertTrue(any("מתנגש" in error for error in deployment_profile.validate(values)))

    def test_external_bot_api_requires_valid_url(self):
        values = dict(self.values)
        values["WZMLX_BOT_API_BASE_URL"] = "not-a-url"
        self.assertTrue(any("BOT_API_BASE_URL" in error for error in deployment_profile.validate(values)))

    def test_adapt_rewrites_all_server_paths_and_reserves_port_order(self):
        adapted = deployment_profile.adapt(
            self.values,
            target_root="/srv/lab/wzmlx-e2e",
            name="wzmlx-e2e-20260814",
            port_base=18080,
            bot_api_url="http://127.0.0.1:28081",
        )
        self.assertEqual("18080", adapted["WZMLX_HOST_PORT"])
        self.assertEqual("28081", adapted["WZMLX_BOT_API_PORT"])
        self.assertEqual("18082", adapted["WZMLX_MONGO_PORT"])
        self.assertEqual("external", adapted["WZMLX_BOT_API_MODE"])
        self.assertEqual("http://127.0.0.1:28081", adapted["WZMLX_BOT_API_BASE_URL"])
        for key in deployment_profile.PATH_KEYS:
            if key != "DEPLOYMENT_LOCK_FILE":
                self.assertNotIn("/srv/wzmlx/", adapted[key])
        deployment_profile.require_valid(adapted)

    def test_atomic_writer_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.env"
            deployment_profile.write_env(path, self.values)
            # ב-Windows ביטי POSIX אינם מיוצגים במלואם; ההרשאה נבדקת ב-Linux ב-E2E.
            if os.name != "nt":
                self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
            self.assertEqual(self.values, deployment_profile.load_env(path))

    def test_safe_summary_hides_secret_values(self):
        values = dict(self.values)
        values["BOT_TOKEN"] = "must-not-leak"
        self.assertNotIn("must-not-leak", str(deployment_profile.safe_summary(values)))


if __name__ == "__main__":
    unittest.main()

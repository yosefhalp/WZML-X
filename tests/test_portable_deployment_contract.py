import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortableDeploymentContractTests(unittest.TestCase):
    def test_application_compose_uses_profile_paths_and_names(self):
        compose = (ROOT / "docker-compose.server.yml").read_text(encoding="utf-8")
        for variable in (
            "WZMLX_IMAGE",
            "WZMLX_CONTAINER_NAME",
            "WZMLX_ENV_PATH",
            "WZMLX_CONFIG_PATH",
            "WZMLX_ACCOUNTS_DIR",
            "WZMLX_DOWNLOADS_DIR",
            "WZMLX_CONTROL_DIR",
            "WZMLX_BOT_API_BASE_URL",
        ):
            self.assertIn("${" + variable, compose)

    def test_mongodb_compose_uses_unique_profile_resources(self):
        compose = (ROOT / "deploy" / "server" / "mongodb.compose.yml").read_text(encoding="utf-8")
        for variable in (
            "WZMLX_MONGO_CONTAINER_NAME",
            "WZMLX_MONGO_ENV_PATH",
            "WZMLX_MONGO_PORT",
            "WZMLX_MONGO_VOLUME_NAME",
            "WZMLX_NETWORK_NAME",
        ):
            self.assertIn("${" + variable, compose)

    def test_restore_does_not_own_external_bot_api(self):
        restore = (ROOT / "deploy" / "server" / "full-restore.sh").read_text(encoding="utf-8")
        external_branch = restore.split('if [[ "${bot_api_mode}" == "external" ]]', 1)[1].split("else", 1)[0]
        self.assertIn("getMe", external_branch)
        self.assertNotIn("docker run", external_branch)
        self.assertNotIn("docker rm", external_branch)
        self.assertNotIn("docker stop", external_branch)

    def test_private_profiles_and_encrypted_bundles_are_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("deployment.env", "controller.env", "*.age", "*.agekey"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main()

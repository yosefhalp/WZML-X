import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


SCRIPT = (
    Path(__file__).parents[1]
    / "deploy"
    / "server"
    / "validate_deployment_secrets.py"
)
SPEC = importlib.util.spec_from_file_location("validate_deployment_secrets", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class DeploymentSecretsTests(TestCase):
    def _validate(self, config_text, env_text):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = root / "config.py"
            env = root / ".env.server"
            config.write_text(config_text, encoding="utf-8")
            env.write_text(env_text, encoding="utf-8")
            return VALIDATOR.validate(config, env)

    def _valid_config(self, password="one-secret"):
        return (
            'BOT_TOKEN = "token"\n'
            "OWNER_ID = 123\n"
            "TELEGRAM_API = 456\n"
            'TELEGRAM_HASH = "hash"\n'
            f'WEB_ACCESS_PASSWORD = "{password}"\n'
        )

    def test_single_password_source_is_valid(self):
        errors = self._validate(
            self._valid_config(), "DATABASE_URL=mongodb://database/wzmlx\n"
        )
        self.assertEqual([], errors)

    def test_matching_password_override_is_valid(self):
        errors = self._validate(
            self._valid_config(),
            "DATABASE_URL=mongodb://database/wzmlx\nWEB_ACCESS_PASSWORD=one-secret\n",
        )
        self.assertEqual([], errors)

    def test_conflicting_password_sources_are_rejected(self):
        errors = self._validate(
            self._valid_config(),
            "DATABASE_URL=mongodb://database/wzmlx\nWEB_ACCESS_PASSWORD=other-secret\n",
        )
        self.assertIn(
            "WEB_ACCESS_PASSWORD שונה בין config.py לבין .env.server", errors
        )

    def test_all_required_parameters_are_reported_together(self):
        errors = self._validate("", "")
        for key in (
            "BOT_TOKEN",
            "OWNER_ID",
            "TELEGRAM_API",
            "TELEGRAM_HASH",
            "DATABASE_URL",
            "WEB_ACCESS_PASSWORD",
        ):
            self.assertTrue(any(key in error for error in errors), key)

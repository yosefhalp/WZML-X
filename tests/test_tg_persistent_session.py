import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TG_CLIENT = ROOT / "bot" / "core" / "tg_client.py"
MAIN = ROOT / "bot" / "__main__.py"
WEB_SERVER = ROOT / "web" / "wserver.py"
REQUIREMENTS = ROOT / "requirements.txt"


class TelegramPersistentSessionTests(unittest.TestCase):
    def test_main_bot_uses_a_stable_disk_session(self):
        source = TG_CLIENT.read_text(encoding="utf-8")
        self.assertIn('kwargs.pop("persistent_session", False)', source)
        self.assertIn('kwargs["in_memory"] = not persistent_session', source)
        self.assertIn('"workdir": "/usr/src/app/accounts"', source)
        self.assertIn('client_options["persistent_session"] = True', source)
        self.assertIn('client_options["session_string"] = saved_session', source)
        self.assertIn("await cls._save_bot_session_string()", source)
        self.assertIn('.session-string"', source)

    def test_session_directory_is_persistent_and_backed_up(self):
        compose = (ROOT / "docker-compose.server.yml").read_text(encoding="utf-8")
        backup = (ROOT / "deploy" / "server" / "full-backup.sh").read_text(encoding="utf-8")
        self.assertIn("${WZMLX_ACCOUNTS_DIR:-./accounts}:/usr/src/app/accounts", compose)
        self.assertIn('wzmlx-runtime-data.tar.gz" "$(basename "${accounts_dir}")"', backup)

    def test_session_file_keeps_the_host_volume_owner(self):
        source = TG_CLIENT.read_text(encoding="utf-8")
        self.assertIn("directory_owner = path.parent.stat()", source)
        self.assertIn(
            "chown(temporary, directory_owner.st_uid, directory_owner.st_gid)",
            source,
        )
        self.assertIn("chmod(temporary, 0o600)", source)

    def test_custom_keyword_is_removed_before_pyrogram_client_call(self):
        tree = ast.parse(TG_CLIENT.read_text(encoding="utf-8"))
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "wztgClient"
        ]
        self.assertEqual(1, len(methods))
        calls = [node for node in ast.walk(methods[0]) if isinstance(node, ast.Call)]
        self.assertTrue(
            any(
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "pop"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "persistent_session"
                for call in calls
            )
        )

    def test_invalid_saved_bot_session_falls_back_without_blocking_startup(self):
        source = TG_CLIENT.read_text(encoding="utf-8")
        self.assertIn("timeout=cls.START_TIMEOUT", source)
        self.assertIn("_quarantine_bot_sessions", source)
        self.assertIn("bot_token=Config.BOT_TOKEN", source)
        self.assertIn("persistent_session=True", source)

    def test_invalid_user_session_does_not_stop_the_main_bot(self):
        source = TG_CLIENT.read_text(encoding="utf-8")
        self.assertIn("Userbot Session אינו תקין או שאינו זמין", source)
        self.assertIn("cls.user = None", source)
        self.assertIn("await cls._stop_client_safely(cls.user)", source)

    def test_session_refresh_verifies_connections_without_restart(self):
        tree = ast.parse(TG_CLIENT.read_text(encoding="utf-8"))
        reload_method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "reload"
        )
        attributes = [
            node.attr for node in ast.walk(reload_method) if isinstance(node, ast.Attribute)
        ]
        self.assertIn("get_me", attributes)
        self.assertNotIn("restart", attributes)

    def test_health_endpoint_depends_on_a_fresh_telegram_rpc(self):
        main = MAIN.read_text(encoding="utf-8")
        server = WEB_SERVER.read_text(encoding="utf-8")
        self.assertIn("telegram_health_watchdog", main)
        self.assertIn("telegram-health.json", server)
        self.assertIn("status_code=200 if telegram_ok else 503", server)
        self.assertIn("marker_age <= 90", server)

    def test_wzgram_version_is_pinned(self):
        requirements = REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("wzgram==3.0.31", requirements.splitlines())


if __name__ == "__main__":
    unittest.main()

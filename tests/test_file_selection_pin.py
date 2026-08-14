import ast
import asyncio
import json
from hashlib import sha256
from hmac import new as hmac_new
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


ROOT = Path(__file__).parents[1]
BOT_UTILS = ROOT / "bot" / "helper" / "ext_utils" / "bot_utils.py"
WEBSERVER = ROOT / "web" / "wserver.py"


class _FakeButtonMaker:
    """שומר את הכפתורים בזיכרון כדי לבדוק את נתוני ה-callback והקישור."""

    def __init__(self):
        self.items = []

    def url_button(self, text, url, **kwargs):
        self.items.append(("url", text, url, kwargs))

    def data_button(self, text, data, **kwargs):
        self.items.append(("data", text, data, kwargs))

    def build_menu(self, _columns):
        return self.items


def _load_selected_functions(path, names, namespace):
    """טוען רק פונקציות שנבחרו, בלי להפעיל את שירותי הבוט בזמן בדיקה."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FileSelectionPinTests(TestCase):
    def _bot_helpers(self, web_pincode=True):
        config = SimpleNamespace(
            BOT_TOKEN="123456:test-token",
            BASE_URL="https://example.test",
            WEB_PINCODE=web_pincode,
        )
        namespace = {
            "Config": config,
            "ButtonMaker": _FakeButtonMaker,
            "ButtonStyle": SimpleNamespace(PRIMARY="primary", SUCCESS="success", DANGER="danger"),
            "hmac_new": hmac_new,
            "sha256": sha256,
            "_PIN_SALT": b"wzmlx_v3_pin_salt",
            "_PIN_LEN": 4,
        }
        return _load_selected_functions(
            BOT_UTILS,
            {"_resolve_bot_id", "derive_pin", "bt_selection_buttons", "bt_selection_controls"},
            namespace,
        )

    def test_pin_is_visible_in_telegram_and_matches_callback(self):
        helpers = self._bot_helpers(web_pincode=True)
        full_gid = "0123456789abcdef0123456789abcdef"
        text, buttons = helpers["bt_selection_controls"](full_gid)
        pin = helpers["derive_pin"](full_gid, "123456")

        self.assertIn(f"\u2066{pin}\u2069", text)
        self.assertIn("קוד הגישה", text)
        self.assertIn(
            ("data", "Pincode", f"sel pin {full_gid[:12]} {pin}", {}),
            buttons,
        )
        self.assertIn(
            ("url", "Select Files", f"https://example.test/app/files?gid={full_gid}", {"style": "primary"}),
            buttons,
        )

    def test_disabled_pin_mode_puts_pin_in_link(self):
        helpers = self._bot_helpers(web_pincode=False)
        gid = "abcdef123456"
        text, buttons = helpers["bt_selection_controls"](gid)
        pin = helpers["derive_pin"](gid, "123456")

        self.assertNotIn("קוד הגישה", text)
        self.assertTrue(
            any(item[0] == "url" and item[2].endswith(f"gid={gid}&pin={pin}") for item in buttons)
        )

    def test_web_server_derives_the_same_pin(self):
        helpers = self._bot_helpers(web_pincode=True)
        gid = "same-task-id"
        web = _load_selected_functions(
            WEBSERVER,
            {"_derive_pin", "_verify_pin"},
            {
                "hmac_new": hmac_new,
                "sha256": sha256,
                "_PIN_SALT": b"wzmlx_v3_pin_salt",
                "_PIN_LEN": 4,
                "_BOT_ID": "123456",
                "_SAFE_PIN": __import__("re").compile(r"^\d{4}$"),
            },
        )
        pin = helpers["derive_pin"](gid, "123456")
        self.assertEqual(pin, web["_derive_pin"](gid))
        self.assertTrue(web["_verify_pin"](gid, pin))
        self.assertFalse(web["_verify_pin"](gid, "0000" if pin != "0000" else "1111"))

    def test_every_selection_message_uses_the_combined_controls(self):
        paths = [
            ROOT / "bot" / "modules" / "file_selector.py",
            ROOT / "bot" / "helper" / "listeners" / "aria2_listener.py",
            ROOT / "bot" / "helper" / "mirror_leech_utils" / "download_utils" / "aria2_download.py",
            ROOT / "bot" / "helper" / "mirror_leech_utils" / "download_utils" / "qbit_download.py",
            ROOT / "bot" / "helper" / "mirror_leech_utils" / "download_utils" / "nzb_downloader.py",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("bt_selection_controls(", source)
                self.assertNotIn("bt_selection_buttons(", source)

    def test_dashboard_never_opens_a_pin_screen_without_a_task(self):
        dashboard = (ROOT / "web" / "templates" / "landing.html").read_text(
            encoding="utf-8"
        )
        selector = (ROOT / "web" / "templates" / "page.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('href="/app/files"', dashboard)
        self.assertIn("selection_tasks", dashboard)
        self.assertIn("if (!urlParams.gid)", selector)
        self.assertIn("אין משימה לבחירת קבצים", selector)

    def test_authenticated_dashboard_builds_task_specific_pin_links(self):
        source = WEBSERVER.read_text(encoding="utf-8")
        self.assertIn("async def _active_selection_tasks()", source)
        self.assertIn('f"/app/files?gid={gid}&pin={_derive_pin(gid)}"', source)
        self.assertIn('"selection_tasks": selection_tasks', source)

    def test_dashboard_never_exposes_a_dead_download_engine_link(self):
        async def no_tasks():
            return []

        async def no_dashboard_tasks():
            return []

        ready_ports = {8090}
        web = _load_selected_functions(
            WEBSERVER,
            {"_dashboard_context"},
            {
                "virtual_memory": lambda: SimpleNamespace(percent=25, used=1, total=2),
                "disk_usage": lambda _path: SimpleNamespace(percent=40, free=3),
                "cpu_percent": lambda interval: 10,
                "loads": json.loads,
                "Path": Path,
                "JSONDecodeError": json.JSONDecodeError,
                "_human_size": lambda value: str(value),
                "_port_ready": lambda port: port in ready_ports,
                "_service_pwd": lambda service: f"pwd-{service}",
                "_active_selection_tasks": no_tasks,
                "_active_task_rows": no_dashboard_tasks,
                "residual_download_status": lambda *_args, **_kwargs: {
                    "entries": 0,
                    "files": 0,
                    "bytes": 0,
                    "protected_entries": 0,
                    "cleanup_allowed": False,
                },
                "read_cache_status": lambda: SimpleNamespace(
                    state="idle", stage="", python_bytes=0, docker_build_bytes=0,
                    docker_reclaimable_bytes=0, bot_api_bytes=0,
                    bot_api_protected_bytes=0, scanned_at="",
                ),
                "read_task_request_status": lambda: {},
                "DOWNLOAD_DIR": ".",
                "Config": SimpleNamespace(
                    DISABLE_TORRENTS=False,
                    DISABLE_YTDLP=False,
                    DISABLE_NZB=True,
                    USENET_SERVERS=[],
                    DISABLE_JD=True,
                    JD_EMAIL="",
                    JD_PASS="",
                ),
            },
        )

        context = asyncio.run(web["_dashboard_context"](authorized=True))

        self.assertTrue(context["qbit_url"])
        self.assertEqual("", context["nzb_url"])
        self.assertIn(("SABnzbd", False), context["services"])

    def test_dashboard_exposes_sabnzbd_only_after_the_port_is_ready(self):
        async def no_tasks():
            return []

        async def no_dashboard_tasks():
            return []

        web = _load_selected_functions(
            WEBSERVER,
            {"_dashboard_context"},
            {
                "virtual_memory": lambda: SimpleNamespace(percent=25, used=1, total=2),
                "disk_usage": lambda _path: SimpleNamespace(percent=40, free=3),
                "cpu_percent": lambda interval: 10,
                "loads": json.loads,
                "Path": Path,
                "JSONDecodeError": json.JSONDecodeError,
                "_human_size": lambda value: str(value),
                "_port_ready": lambda port: port in {8070, 8090},
                "_service_pwd": lambda service: f"pwd-{service}",
                "_active_selection_tasks": no_tasks,
                "_active_task_rows": no_dashboard_tasks,
                "residual_download_status": lambda *_args, **_kwargs: {
                    "entries": 0,
                    "files": 0,
                    "bytes": 0,
                    "protected_entries": 0,
                    "cleanup_allowed": False,
                },
                "read_cache_status": lambda: SimpleNamespace(
                    state="idle", stage="", python_bytes=0, docker_build_bytes=0,
                    docker_reclaimable_bytes=0, bot_api_bytes=0,
                    bot_api_protected_bytes=0, scanned_at="",
                ),
                "read_task_request_status": lambda: {},
                "DOWNLOAD_DIR": ".",
                "Config": SimpleNamespace(
                    DISABLE_TORRENTS=False,
                    DISABLE_YTDLP=False,
                    DISABLE_NZB=True,
                    USENET_SERVERS=[],
                    DISABLE_JD=True,
                    JD_EMAIL="",
                    JD_PASS="",
                ),
            },
        )

        context = asyncio.run(web["_dashboard_context"](authorized=True))

        self.assertTrue(context["nzb_url"].startswith("/nzb/?pass="))
        self.assertIn(("SABnzbd", True), context["services"])

    def test_real_gofile_preflight_does_not_require_an_existing_token(self):
        source = (ROOT / "bot" / "helper" / "common.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        gofile_blocks = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            comparison = ast.unparse(node.test)
            if comparison == "service == 'gofile'":
                gofile_blocks.append(node)
        self.assertEqual(1, len(gofile_blocks))
        block = gofile_blocks[0]
        self.assertTrue(any(isinstance(node, ast.Continue) for node in block.body))
        # בודקים רק את גוף GoFile ולא את שרשרת ה-elif של השירותים האחרים,
        # שממשיכים בצדק לדרוש מפתחות משלהם.
        body = ast.Module(body=block.body, type_ignores=[])
        self.assertFalse(any(isinstance(node, ast.Raise) for node in ast.walk(body)))

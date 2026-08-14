"""שירות HTTP זעיר לבדיקת מנגנון release בלי להפעיל Bot Token אמיתי."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    """מחזיר את גרסת ה-release ומאפשר הזרקת כשל מבוקרת."""

    def do_GET(self):
        release = Path("/release")
        version_path = release / "deploy" / "server" / "e2e" / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "unknown"
        release_id_path = release / ".release-id"
        release_id = release_id_path.read_text(encoding="utf-8").strip() if release_id_path.is_file() else "unknown"
        failed = (release / "E2E_FAIL").exists()
        status = 503 if failed else 200
        payload = json.dumps({"ok": not failed, "release": version, "release_id": release_id}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        """משתיק לוג גישה כדי שפלט בדיקת הפריסה יישאר ממוקד."""


server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("E2E_PORT", "8080"))), Handler)
server.serve_forever()

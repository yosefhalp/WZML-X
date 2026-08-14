#!/usr/bin/env bash
set -Eeuo pipefail

# ההתקנה משתמשת ב-systemd של המשתמש, ולכן אינה דורשת sudo בשרת Linux.
# worker יחיד מטפל גם בכפתור הידני וגם בתזמון היומי, כדי שלא ייווצרו שני גיבויים במקביל.
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unit_dir="${HOME}/.config/systemd/user"
control_dir="${project_dir}/runtime/control"
mkdir -p "${unit_dir}"
mkdir -p "${control_dir}"
chmod 700 "${control_dir}"

# אם טרם נשמרו הגדרות, בעל הבוט מה-config.py הופך ליעד המסירה היומי.
python3 - "${project_dir}" <<'PY'
import ast
import json
import os
import sys
from pathlib import Path

project = Path(sys.argv[1]).resolve()
settings = project / "runtime" / "control" / "backup-settings.json"
if not settings.exists():
    tree = ast.parse((project / "config.py").read_text(encoding="utf-8"))
    owner_id = 0
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "OWNER_ID" for target in targets):
            owner_id = int(ast.literal_eval(node.value))
            break
    if owner_id <= 0:
        raise SystemExit("OWNER_ID חסר או אינו תקין")
    payload = {
        "version": 1,
        "daily_enabled": True,
        "daily_hour": 4,
        "daily_minute": 15,
        "daily_timezone": "Asia/Jerusalem",
        "daily_chat_id": owner_id,
    }
    temporary = settings.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, settings)
PY

cat > "${unit_dir}/wzmlx-backup-worker.service" <<EOF
[Unit]
Description=WZML-X full backup worker
After=default.target

[Service]
Type=simple
WorkingDirectory=${project_dir}
ExecStart=/usr/bin/python3 ${project_dir}/deploy/server/backup_worker.py
Environment=WZMLX_BACKUP_RETAIN=2
Environment=WZMLX_PROJECT_DIR=${project_dir}
Restart=always
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=default.target
EOF
# יחידות מהגרסה הישנה מושבתות כדי למנוע הפעלה כפולה.
systemctl --user disable --now wzmlx-full-backup.timer wzmlx-backup-request.path >/dev/null 2>&1 || true
systemctl --user daemon-reload
systemctl --user enable --now wzmlx-backup-worker.service
systemctl --user status wzmlx-backup-worker.service --no-pager

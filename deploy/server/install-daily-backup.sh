#!/usr/bin/env bash
set -Eeuo pipefail

# ההתקנה משתמשת ב-systemd של המשתמש, ולכן אינה דורשת sudo בשרת Linux.
# worker יחיד מטפל גם בכפתור הידני וגם בתזמון היומי, כדי שלא ייווצרו שני גיבויים במקביל.
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
deployment_env="${WZMLX_DEPLOYMENT_ENV:-}"
profile_value() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${deployment_env}"; }
if [[ -n "${deployment_env}" ]]; then
  python3 "${project_dir}/deploy/server/deployment_profile.py" validate "${deployment_env}" >/dev/null
  project_dir="$(profile_value DEPLOYMENT_CURRENT_LINK)"
  deployment_name="$(profile_value DEPLOYMENT_NAME)"
  control_dir="$(profile_value WZMLX_CONTROL_DIR)"
  config_path="$(profile_value WZMLX_CONFIG_PATH)"
  backup_root="$(profile_value DEPLOYMENT_BACKUP_DIR)"
  bot_api_base="$(profile_value WZMLX_BOT_API_BASE_URL)"
else
  deployment_name="wzmlx"
  control_dir="${project_dir}/runtime/control"
  config_path="${project_dir}/config.py"
  backup_root="${HOME}/wzmlx-backups"
  bot_api_base="http://127.0.0.1:8081"
fi
unit_name="${deployment_name}-backup-worker.service"
unit_dir="${HOME}/.config/systemd/user"
mkdir -p "${unit_dir}"
mkdir -p "${control_dir}"
chmod 700 "${control_dir}"

# אם טרם נשמרו הגדרות, בעל הבוט מה-config.py הופך ליעד המסירה היומי.
python3 - "${control_dir}" "${config_path}" <<'PY'
import ast
import json
import os
import sys
from pathlib import Path

control = Path(sys.argv[1]).resolve()
config = Path(sys.argv[2]).resolve()
settings = control / "backup-settings.json"
if not settings.exists():
    tree = ast.parse(config.read_text(encoding="utf-8"))
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

cat > "${unit_dir}/${unit_name}" <<EOF
[Unit]
Description=WZML-X full backup worker
After=default.target

[Service]
Type=simple
WorkingDirectory=${project_dir}
ExecStart=/usr/bin/python3 ${project_dir}/deploy/server/backup_worker.py
Environment=WZMLX_BACKUP_RETAIN=2
Environment=WZMLX_PROJECT_DIR=${project_dir}
Environment=WZMLX_CONTROL_DIR=${control_dir}
Environment=WZMLX_CONFIG_PATH=${config_path}
Environment=WZMLX_BACKUP_ROOT=${backup_root}
Environment=WZMLX_BOT_API_BASE=${bot_api_base}
Environment=WZMLX_DEPLOYMENT_ENV=${deployment_env}
Restart=always
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=default.target
EOF
# יחידות מהגרסה הישנה מושבתות כדי למנוע הפעלה כפולה.
if [[ "${deployment_name}" == "wzmlx" ]]; then
  systemctl --user disable --now wzmlx-full-backup.timer wzmlx-backup-request.path >/dev/null 2>&1 || true
fi
systemctl --user daemon-reload
systemctl --user enable --now "${unit_name}"
systemctl --user status "${unit_name}" --no-pager

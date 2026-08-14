#!/usr/bin/env bash
set -Eeuo pipefail

# הגיבוי נוצר כחבילה עצמאית: קוד, סודות, נתונים ותמונות Docker שבבעלות הפריסה.
# מטמון Telegram Bot API אינו נכלל, משום שהוא זמני ויכול להגיע לעשרות גיגה־בתים.
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
deployment_env="${WZMLX_DEPLOYMENT_ENV:-}"
profile_value() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${deployment_env}"; }
if [[ -n "${deployment_env}" ]]; then
  python3 "${project_dir}/deploy/server/deployment_profile.py" validate "${deployment_env}" >/dev/null
  project_dir="$(profile_value DEPLOYMENT_CURRENT_LINK)"
  backup_root="$(profile_value DEPLOYMENT_BACKUP_DIR)"
  config_path="$(profile_value WZMLX_CONFIG_PATH)"
  app_env_path="$(profile_value WZMLX_ENV_PATH)"
  mongo_env_path="$(profile_value WZMLX_MONGO_ENV_PATH)"
  accounts_dir="$(profile_value WZMLX_ACCOUNTS_DIR)"
  control_dir="$(profile_value WZMLX_CONTROL_DIR)"
  app_container="$(profile_value WZMLX_CONTAINER_NAME)"
  mongo_container="$(profile_value WZMLX_MONGO_CONTAINER_NAME)"
  bot_api_container="$(profile_value WZMLX_BOT_API_CONTAINER_NAME)"
  bot_api_mode="$(profile_value WZMLX_BOT_API_MODE)"
else
  backup_root="${WZMLX_BACKUP_ROOT:-${HOME}/wzmlx-backups}"
  config_path="${project_dir}/config.py"
  app_env_path="${project_dir}/.env.server"
  mongo_env_path="${WZMLX_MONGO_DIR:-${HOME}/wzmlx-mongodb}/.env.mongo"
  accounts_dir="${project_dir}/accounts"
  control_dir="${project_dir}/runtime/control"
  app_container="wzmlx-hebrew-bot"
  mongo_container="wzmlx-mongodb"
  bot_api_container="tg-bot-api"
  bot_api_mode="managed"
fi
retain_count="${WZMLX_BACKUP_RETAIN:-2}"
backup_mode="${WZMLX_BACKUP_MODE:-full}"
case "${backup_mode}" in
  full|state) ;;
  *) echo "מצב הגיבוי אינו נתמך." >&2; exit 1 ;;
esac
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
package_name="wzmlx-${backup_mode}-${timestamp}"
work_dir="${backup_root}/.building-${package_name}"
package_dir="${work_dir}/${package_name}"
archive="${backup_root}/${package_name}.tar"
status_file="${control_dir}/backup-status.json"

write_status() {
  # קובץ הסטטוס הוא ערוץ חד־כיווני ובטוח בין מארח Docker לבין ממשק הבוט.
  # כאשר ה־worker מנהל את התהליך הוא מפרסם סטטוס עשיר יותר, ולכן הסקריפט לא דורס אותו.
  [[ "${WZMLX_BACKUP_STATUS_EXTERNAL:-0}" == "1" ]] && return 0
  python3 - "$status_file" "$1" "$2" "${3:-}" "${4:-0}" <<'PY'
import json, os, sys
from datetime import datetime, timezone
path, state, stage, archive, size = sys.argv[1:]
payload = {
    "state": state,
    "stage": stage,
    "archive": archive,
    "size_bytes": int(size or 0),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
if state in {"success", "failed"}:
    payload["finished_at"] = payload["updated_at"]
temporary = path + ".new"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.replace(temporary, path)
PY
}

on_error() {
  write_status failed "הגיבוי נכשל" "${archive}" 0 || true
}

mkdir -p "${backup_root}"
mkdir -p "${control_dir}"
chmod 700 "${backup_root}"
chmod 700 "${control_dir}"
write_status running "מתחיל גיבוי מלא"
exec 9>"${backup_root}/.backup.lock"
flock -n 9 || { echo "כבר מתבצע גיבוי WZML-X." >&2; exit 1; }
# בדיקת הגבול מונעת ממחיקה רקורסיבית להגיע מחוץ לתיקיית הגיבויים.
case "${work_dir}" in
  "${backup_root}"/.building-wzmlx-full-*|"${backup_root}"/.building-wzmlx-state-*) ;;
  *) echo "נתיב העבודה הזמני אינו בטוח." >&2; exit 1 ;;
esac
rm -rf "${work_dir}"
trap 'rm -rf "${work_dir}"' EXIT
trap on_error ERR
mkdir -p "${package_dir}"/{images,payload,secrets}
chmod 700 "${package_dir}" "${package_dir}/secrets"

for command_name in docker gzip tar sha256sum python3; do
  command -v "${command_name}" >/dev/null || { echo "חסרה פקודה: ${command_name}" >&2; exit 1; }
done
docker inspect "${mongo_container}" >/dev/null 2>&1 || { echo "הקונטיינר ${mongo_container} לא נמצא." >&2; exit 1; }
if [[ "${bot_api_mode}" == "managed" ]]; then
  docker inspect "${bot_api_container}" >/dev/null 2>&1 || { echo "הקונטיינר ${bot_api_container} לא נמצא." >&2; exit 1; }
fi
[[ -s "${config_path}" && -s "${app_env_path}" ]] || { echo "חסרים קובצי הסודות של WZML-X." >&2; exit 1; }
[[ -s "${mongo_env_path}" ]] || { echo "חסר ${mongo_env_path}." >&2; exit 1; }

if docker inspect "${app_container}" >/dev/null 2>&1; then
  wzmlx_image="$(docker inspect -f '{{.Config.Image}}' "${app_container}")"
else
  wzmlx_image="wzmlx-hebrew:server"
fi
mongo_image="$(docker inspect -f '{{.Config.Image}}' "${mongo_container}")"
bot_api_image=""
[[ "${bot_api_mode}" == "managed" ]] && bot_api_image="$(docker inspect -f '{{.Config.Image}}' "${bot_api_container}")"
docker image inspect "${wzmlx_image}" "${mongo_image}" >/dev/null
[[ -z "${bot_api_image}" ]] || docker image inspect "${bot_api_image}" >/dev/null

echo "[1/7] שומר את קוד הבוט ואת הנתונים המקומיים..."
write_status running "שומר קוד ונתוני ריצה"
tar -C "${project_dir}" --exclude=.git --exclude='*.zip' --exclude='*.tar' --exclude='*.tar.gz' --exclude='downloads/*' --exclude='accounts/*' --exclude='runtime/control/*' -czf "${package_dir}/payload/wzmlx-source.tar.gz" .
# תיקיית downloads היא שטח עבודה זמני ואינה חלק מגיבוי המערכת היומי.
# כך משימות פעילות אינן מושהות וקובצי מדיה גדולים אינם מנפחים את הגיבוי.
tar -C "$(dirname "${accounts_dir}")" -czf "${package_dir}/payload/wzmlx-runtime-data.tar.gz" "$(basename "${accounts_dir}")"
if [[ -s "${control_dir}/backup-settings.json" ]]; then
  install -m 0600 "${control_dir}/backup-settings.json" "${package_dir}/payload/backup-settings.json"
fi

echo "[2/7] יוצר dump עקבי של MongoDB..."
write_status running "מגבה את MongoDB"
database_url="$(sed -n 's/^DATABASE_URL=//p' "${app_env_path}" | head -n 1)"
[[ -n "${database_url}" ]] || { echo "DATABASE_URL חסר." >&2; exit 1; }
docker exec -e "WZMLX_DATABASE_URL=${database_url}" "${mongo_container}" sh -c 'mongodump --quiet --uri="$WZMLX_DATABASE_URL" --archive --gzip' > "${package_dir}/payload/mongodb.archive.gz"

echo "[3/7] אוסף סודות ותיאור חיבור ל-Local Bot API..."
write_status running "אוסף הגדרות וחיבורי שירותים"
install -m 0600 "${config_path}" "${package_dir}/secrets/config.py"
install -m 0600 "${app_env_path}" "${package_dir}/secrets/wzmlx.env"
install -m 0600 "${mongo_env_path}" "${package_dir}/secrets/mongodb.env"
[[ -z "${deployment_env}" ]] || install -m 0600 "${deployment_env}" "${package_dir}/secrets/source-deployment.env"
if [[ "${bot_api_mode}" == "managed" ]]; then
  docker inspect "${bot_api_container}" > "${package_dir}/secrets/telegram-bot-api.inspect.json"
  docker inspect "${bot_api_container}" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(TELEGRAM_API_ID|TELEGRAM_API_HASH|TELEGRAM_LOCAL|TELEGRAM_TEMP_DIR|TELEGRAM_WORK_DIR)=' > "${package_dir}/secrets/telegram-bot-api.env"
fi
chmod 600 "${package_dir}/secrets/"*

if [[ "${backup_mode}" == "full" ]]; then
  echo "[4/7] שומר את תמונות Docker המלאות..."
  write_status running "שומר תמונות Docker"
  docker save "${wzmlx_image}" | gzip -1 > "${package_dir}/images/wzmlx.tar.gz"
  docker save "${mongo_image}" | gzip -1 > "${package_dir}/images/mongodb.tar.gz"
  [[ -z "${bot_api_image}" ]] || docker save "${bot_api_image}" | gzip -1 > "${package_dir}/images/telegram-bot-api.tar.gz"
else
  echo "[4/7] מצב מהיר: משתמש בתמונות שכבר קיימות בשרת היעד."
  write_status running "יוצר ערכה מהירה ללא תמונות Docker"
fi

echo "[5/7] מוסיף כלי שחזור ואימות..."
install -m 0700 "${project_dir}/deploy/server/full-restore.sh" "${package_dir}/restore.sh"
install -m 0700 "${project_dir}/deploy/server/verify-full-backup.sh" "${package_dir}/verify.sh"
install -m 0700 "${project_dir}/deploy/server/restore-drill.sh" "${package_dir}/restore-drill.sh"
python3 - "${package_dir}/manifest.json" "${wzmlx_image}" "${mongo_image}" "${bot_api_image}" "${backup_mode}" "${bot_api_mode}" <<'PY'
import json, platform, sys
from datetime import datetime, timezone
path, wzmlx, mongo, bot_api, mode, bot_api_mode = sys.argv[1:]
manifest = {
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "architecture": f"linux/{platform.machine()}",
    "mode": mode,
    "images": {"wzmlx": wzmlx, "mongodb": mongo, "telegram_bot_api": bot_api},
    "includes": {"source": True, "secrets": True, "mongodb_dump": True, "runtime_data": True, "images": mode == "full", "backup_worker": True, "backup_worker_installer": True, "bot_api_cache": False, "deployment_map": True},
    "bot_api_restore_mode": bot_api_mode,
}
open(path, "w", encoding="utf-8").write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
PY
cat > "${package_dir}/README-HE.md" <<'EOF'
# גיבוי מלא של WZML-X

החבילה כוללת את קוד הבוט, הסודות, נתוני הריצה, dump של MongoDB ותמונות Docker שבבעלות הפריסה.
גם Worker הגיבוי, מתקין שירות ה-systemd שלו והגדרות התזמון כלולים. בסיום `restore.sh` השירות מותקן, מופעל ומאומת אוטומטית.

מטמון ההורדות של Telegram Bot API אינו נכלל משום שהוא זמני. כאשר מפת הפריסה מסמנת אותו כחיצוני, החבילה שומרת את חוזה החיבור בלבד ואינה מעתיקה, מפעילה או מוחקת את השירות המשותף. תמונה והגדרות שירות נכללות רק במצב `managed` מפורש.

אימות בלבד: `./verify.sh .`

שחזור לשרת חלופי: `CONFIRM_RESTORE=YES ./restore.sh . /home/$USER/wzmlx-restored`
EOF

echo "[6/7] מחשב SHA-256 ומוודא את החבילה..."
write_status running "מאמת את שלמות הגיבוי"
(cd "${package_dir}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
"${package_dir}/verify.sh" "${package_dir}"

echo "[7/7] אורז ושומר מדיניות שימור..."
tar -C "${work_dir}" -cf "${archive}.new" "${package_name}"
mv "${archive}.new" "${archive}"
chmod 600 "${archive}"
archive_size="$(stat -c '%s' "${archive}")"
printf '%s\n' "${archive}" > "${backup_root}/LATEST"
chmod 600 "${backup_root}/LATEST"
# רק ארכיון שנוצר בגרסה זו מקבל סמן managed. כך ארכיון ישן או ידני לעולם
# לא יימחק אוטומטית על ידי מדיניות השימור.
managed_marker="${archive}.managed"
printf 'version=1\narchive=%s\nsize_bytes=%s\n' "$(basename "${archive}")" "${archive_size}" > "${managed_marker}.new"
mv "${managed_marker}.new" "${managed_marker}"
chmod 600 "${managed_marker}"
mapfile -t old_markers < <(find "${backup_root}" -maxdepth 1 -type f -name "wzmlx-${backup_mode}-*.tar.managed" -printf '%T@ %p\n' | sort -nr | tail -n "+$((retain_count + 1))" | cut -d' ' -f2-)
for old_marker in "${old_markers[@]}"; do
  old_archive="${old_marker%.managed}"
  rm -f -- "${old_archive}" "${old_marker}"
done
write_status success "הגיבוי הושלם ואומת" "${archive}" "${archive_size}"
echo "הגיבוי הושלם: ${archive}"

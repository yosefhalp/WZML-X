#!/usr/bin/env bash
set -Eeuo pipefail

# תרגיל השחזור אינו נוגע במסד הפעיל: ה-dump נטען למסד זמני שנמחק תמיד בסיום.
archive="${1:-$(cat "${HOME}/wzmlx-backups/LATEST")}"
[[ -s "${archive}" ]] || { echo "ארכיון הגיבוי לא נמצא." >&2; exit 1; }
temporary_dir="$(mktemp -d)"
verify_db="wzmlx_restore_verify_$(date +%s)"
mongo_env="${temporary_dir}/mongodb.env"
bot_config="${temporary_dir}/config.py"
mapfile -t archive_entries < <(tar -tf "${archive}")
prefix="${archive_entries[0]%%/*}"
tar -xOf "${archive}" "${prefix}/secrets/mongodb.env" > "${mongo_env}"
tar -xOf "${archive}" "${prefix}/secrets/config.py" > "${bot_config}"
chmod 600 "${mongo_env}" "${bot_config}"
set -a
source "${mongo_env}"
set +a

cleanup() {
  docker exec -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD -e VERIFY_DB="${verify_db}" wzmlx-mongodb \
    sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.getSiblingDB(\"$VERIFY_DB\").dropDatabase()"' >/dev/null 2>&1 || true
  rm -rf "${temporary_dir}"
}
trap cleanup EXIT

echo "משחזר את MongoDB למסד בדיקה מבודד..."
tar -xOf "${archive}" "${prefix}/payload/mongodb.archive.gz" \
  | docker exec -i -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD -e VERIFY_DB="${verify_db}" wzmlx-mongodb \
      sh -c 'mongorestore --quiet --host 127.0.0.1 --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --nsFrom="wzmlx.*" --nsTo="$VERIFY_DB.*"'

collection_count="$(docker exec -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD -e VERIFY_DB="${verify_db}" wzmlx-mongodb \
  sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.getSiblingDB(\"$VERIFY_DB\").getCollectionNames().length"' | tail -n 1)"
[[ "${collection_count}" =~ ^[0-9]+$ ]] || { echo "לא התקבלה ספירת אוספים תקינה ממסד הבדיקה." >&2; exit 1; }

echo "מוודא זיהוי וחיבור ל-Local Telegram Bot API..."
bot_token="$(python3 - "${bot_config}" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'^BOT_TOKEN\s*=\s*["\x27]([^"\x27]+)', text, re.MULTILINE)
if not match:
    raise SystemExit("BOT_TOKEN חסר בקובץ הגיבוי")
print(match.group(1))
PY
)"
curl -fsS "http://127.0.0.1:8081/bot${bot_token}/getMe" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("ok") else 1)'
echo "תרגיל השחזור עבר: MongoDB שוחזר למסד זמני ו-Bot API זוהה וחובר בהצלחה."

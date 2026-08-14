#!/usr/bin/env bash
set -Eeuo pipefail

# שחזור משנה שירותים ונתונים ולכן הוא מחייב אישור מפורש בסביבת ההרצה.
[[ "${CONFIRM_RESTORE:-}" == "YES" ]] || { echo "להפעלת שחזור יש להריץ עם CONFIRM_RESTORE=YES." >&2; exit 1; }
package_dir="$(cd "${1:-.}" && pwd)"
target_dir="${2:-${HOME}/wzmlx-restored}"
"${package_dir}/verify.sh" "${package_dir}"
shopt -s nullglob
for image_archive in "${package_dir}"/images/*.tar.gz; do gzip -dc "${image_archive}" | docker load >/dev/null; done
if [[ -e "${target_dir}" && "${ALLOW_RESTORE_OVERWRITE:-}" != "YES" ]]; then echo "נתיב היעד כבר קיים. לדריסה מכוונת הוסף ALLOW_RESTORE_OVERWRITE=YES." >&2; exit 1; fi
mkdir -p "${target_dir}"
tar -C "${target_dir}" -xzf "${package_dir}/payload/wzmlx-source.tar.gz"
tar -C "${target_dir}" -xzf "${package_dir}/payload/wzmlx-runtime-data.tar.gz"
install -m 0600 "${package_dir}/secrets/config.py" "${target_dir}/config.py"
install -m 0600 "${package_dir}/secrets/wzmlx.env" "${target_dir}/.env.server"
if [[ -s "${package_dir}/payload/backup-settings.json" ]]; then
  mkdir -p "${target_dir}/runtime/control"
  chmod 700 "${target_dir}/runtime/control"
  install -m 0600 "${package_dir}/payload/backup-settings.json" "${target_dir}/runtime/control/backup-settings.json"
fi

# שירות משותף קיים מקבל עדיפות; כך נמנעים משני Bot API על אותו פורט.
bot_token="$(sed -nE "s/^BOT_TOKEN[[:space:]]*=[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" "${target_dir}/config.py" | head -n 1)"
if docker inspect tg-bot-api >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:8081/bot${bot_token}/getMe" | grep -q '"ok":true' || { echo "נמצא tg-bot-api, אך הוא אינו מאמת את הבוט. השחזור נעצר כדי לא לפגוע בשירות משותף." >&2; exit 1; }
else
  bot_api_image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"]["telegram_bot_api"])' "${package_dir}/manifest.json")"
  docker volume create wzmlx-telegram-bot-api-data >/dev/null
  docker run -d --name tg-bot-api --restart unless-stopped --env-file "${package_dir}/secrets/telegram-bot-api.env" -p 127.0.0.1:8081:8081 -v wzmlx-telegram-bot-api-data:/var/lib/telegram-bot-api "${bot_api_image}" >/dev/null
fi

# אם MongoDB כבר קיים משתמשים בו; אחרת מקימים אותו מהתמונה והסודות שבחבילה.
if ! docker inspect wzmlx-mongodb >/dev/null 2>&1; then
  mongo_image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"]["mongodb"])' "${package_dir}/manifest.json")"
  docker volume create wzmlx-mongo-data >/dev/null
  docker run -d --name wzmlx-mongodb --restart unless-stopped --env-file "${package_dir}/secrets/mongodb.env" -p 127.0.0.1:27017:27017 -v wzmlx-mongo-data:/data/db "${mongo_image}" mongod --auth --bind_ip_all --wiredTigerCacheSizeGB 0.25 >/dev/null
fi
set -a
source "${package_dir}/secrets/mongodb.env"
set +a
for _ in $(seq 1 60); do
  docker exec -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD wzmlx-mongodb sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "quit(db.adminCommand(\"ping\").ok ? 0 : 2)"' >/dev/null 2>&1 && break
  sleep 2
done
root_uri="mongodb://${MONGO_INITDB_ROOT_USERNAME}:${MONGO_INITDB_ROOT_PASSWORD}@127.0.0.1:27017/?authSource=admin"
docker exec -i -e "ROOT_URI=${root_uri}" wzmlx-mongodb sh -c 'mongorestore --quiet --drop --uri="$ROOT_URI" --archive --gzip' < "${package_dir}/payload/mongodb.archive.gz"
cd "${target_dir}"
docker compose -f docker-compose.server.yml up -d
./deploy/server/install-daily-backup.sh
echo "השחזור הושלם. WZML-X משתמש ב-MongoDB וב-Local Bot API שזוהו או הוקמו, ו-worker הגיבוי הופעל."

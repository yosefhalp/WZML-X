#!/usr/bin/env bash
set -Eeuo pipefail

# שחזור משנה שירותים ונתונים ולכן הוא מחייב אישור מפורש בסביבת ההרצה.
[[ "${CONFIRM_RESTORE:-}" == "YES" ]] || { echo "להפעלת שחזור יש להריץ עם CONFIRM_RESTORE=YES." >&2; exit 1; }
package_dir="$(cd "${1:-.}" && pwd)"
target_dir="${2:-${HOME}/wzmlx-restored}"
deployment_env="${WZMLX_DEPLOYMENT_ENV:-}"
profile_value() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${deployment_env}"; }
if [[ -n "${deployment_env}" && ! -s "${deployment_env}" ]]; then
  echo "מפת פריסת היעד חסרה: ${deployment_env}" >&2
  exit 1
fi
"${package_dir}/verify.sh" "${package_dir}"
shopt -s nullglob
for image_archive in "${package_dir}"/images/*.tar.gz; do gzip -dc "${image_archive}" | docker load >/dev/null; done
if [[ -e "${target_dir}" && "${ALLOW_RESTORE_OVERWRITE:-}" != "YES" ]]; then echo "נתיב היעד כבר קיים. לדריסה מכוונת הוסף ALLOW_RESTORE_OVERWRITE=YES." >&2; exit 1; fi
mkdir -p "${target_dir}"
tar -C "${target_dir}" -xzf "${package_dir}/payload/wzmlx-source.tar.gz"
tar -C "${target_dir}" -xzf "${package_dir}/payload/wzmlx-runtime-data.tar.gz"
install -m 0600 "${package_dir}/secrets/config.py" "${target_dir}/config.py"
install -m 0600 "${package_dir}/secrets/wzmlx.env" "${target_dir}/.env.server"
if [[ -n "${deployment_env}" ]]; then
  python3 "${target_dir}/deploy/server/deployment_profile.py" validate "${deployment_env}" >/dev/null
  config_path="$(profile_value WZMLX_CONFIG_PATH)"
  app_env_path="$(profile_value WZMLX_ENV_PATH)"
  mongo_env_path="$(profile_value WZMLX_MONGO_ENV_PATH)"
  accounts_dir="$(profile_value WZMLX_ACCOUNTS_DIR)"
  control_dir="$(profile_value WZMLX_CONTROL_DIR)"
  mongo_container="$(profile_value WZMLX_MONGO_CONTAINER_NAME)"
  mongo_volume="$(profile_value WZMLX_MONGO_VOLUME_NAME)"
  mongo_port="$(profile_value WZMLX_MONGO_PORT)"
  bot_api_mode="$(profile_value WZMLX_BOT_API_MODE)"
  bot_api_base="$(profile_value WZMLX_BOT_API_BASE_URL)"
  bot_api_container="$(profile_value WZMLX_BOT_API_CONTAINER_NAME)"
  bot_api_volume="$(profile_value WZMLX_BOT_API_VOLUME_NAME)"
  bot_api_port="$(profile_value WZMLX_BOT_API_PORT)"
  mkdir -p "$(dirname "${config_path}")" "$(dirname "${app_env_path}")" "$(dirname "${mongo_env_path}")" "${accounts_dir}" "${control_dir}"
  chmod 700 "$(dirname "${config_path}")" "${accounts_dir}" "${control_dir}"
  install -m 0600 "${package_dir}/secrets/config.py" "${config_path}"
  install -m 0600 "${package_dir}/secrets/wzmlx.env" "${app_env_path}"
  install -m 0600 "${package_dir}/secrets/mongodb.env" "${mongo_env_path}"
  rm -rf "${accounts_dir:?}"/*
  cp -a "${target_dir}/accounts/." "${accounts_dir}/"
else
  config_path="${target_dir}/config.py"
  app_env_path="${target_dir}/.env.server"
  mongo_env_path="${package_dir}/secrets/mongodb.env"
  accounts_dir="${target_dir}/accounts"
  control_dir="${target_dir}/runtime/control"
  mongo_container="wzmlx-mongodb"
  mongo_volume="wzmlx-mongo-data"
  mongo_port="27017"
  bot_api_mode="managed"
  bot_api_base="http://127.0.0.1:8081"
  bot_api_container="tg-bot-api"
  bot_api_volume="wzmlx-telegram-bot-api-data"
  bot_api_port="8081"
fi
if [[ -s "${package_dir}/payload/backup-settings.json" ]]; then
  mkdir -p "${control_dir}"
  chmod 700 "${control_dir}"
  install -m 0600 "${package_dir}/payload/backup-settings.json" "${control_dir}/backup-settings.json"
fi

# שירות חיצוני לעולם אינו מוקם או נמחק בידי השחזור; הוא רק עובר אימות.
bot_token="$(sed -nE "s/^BOT_TOKEN[[:space:]]*=[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" "${config_path}" | head -n 1)"
if [[ "${bot_api_mode}" == "external" ]]; then
  curl -fsS "${bot_api_base%/}/bot${bot_token}/getMe" | grep -q '"ok":true' || { echo "Local Bot API החיצוני אינו מאמת את הבוט; השחזור נעצר ללא שינוי בשירות המשותף." >&2; exit 1; }
else
  [[ -s "${package_dir}/secrets/telegram-bot-api.env" ]] || { echo "מצב managed דורש הגדרות Bot API בחבילה." >&2; exit 1; }
  bot_api_image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"]["telegram_bot_api"])' "${package_dir}/manifest.json")"
  docker inspect "${bot_api_container}" >/dev/null 2>&1 || {
    docker volume create "${bot_api_volume}" >/dev/null
    docker run -d --name "${bot_api_container}" --restart unless-stopped --env-file "${package_dir}/secrets/telegram-bot-api.env" -p "127.0.0.1:${bot_api_port}:8081" -v "${bot_api_volume}:/var/lib/telegram-bot-api" "${bot_api_image}" >/dev/null
  }
fi

# אם MongoDB כבר קיים משתמשים בו; אחרת מקימים אותו מהתמונה והסודות שבחבילה.
if ! docker inspect "${mongo_container}" >/dev/null 2>&1; then
  mongo_image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"]["mongodb"])' "${package_dir}/manifest.json")"
  docker volume create "${mongo_volume}" >/dev/null
  docker run -d --name "${mongo_container}" --restart unless-stopped --env-file "${mongo_env_path}" -p "127.0.0.1:${mongo_port}:27017" -v "${mongo_volume}:/data/db" "${mongo_image}" mongod --auth --bind_ip_all --wiredTigerCacheSizeGB 0.25 >/dev/null
fi
set -a
source "${mongo_env_path}"
set +a
for _ in $(seq 1 60); do
  docker exec -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD "${mongo_container}" sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "quit(db.adminCommand(\"ping\").ok ? 0 : 2)"' >/dev/null 2>&1 && break
  sleep 2
done
root_uri="mongodb://${MONGO_INITDB_ROOT_USERNAME}:${MONGO_INITDB_ROOT_PASSWORD}@127.0.0.1:27017/?authSource=admin"
docker exec -i -e "ROOT_URI=${root_uri}" "${mongo_container}" sh -c 'mongorestore --quiet --drop --uri="$ROOT_URI" --archive --gzip' < "${package_dir}/payload/mongodb.archive.gz"
cd "${target_dir}"
if [[ -n "${deployment_env}" ]]; then
  docker compose --project-name "$(profile_value DEPLOYMENT_COMPOSE_PROJECT)" --env-file "${deployment_env}" -f docker-compose.server.yml up -d
else
  docker compose -f docker-compose.server.yml up -d
fi
./deploy/server/install-daily-backup.sh
echo "השחזור הושלם. WZML-X משתמש ב-MongoDB וב-Local Bot API שזוהו או הוקמו, ו-worker הגיבוי הופעל."

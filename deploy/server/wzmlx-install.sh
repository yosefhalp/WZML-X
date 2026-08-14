#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
[[ -s config.py ]] || { echo "חסר config.py הסודי." >&2; exit 1; }
[[ -s .env.server ]] || { echo "חסר .env.server הסודי." >&2; exit 1; }

mkdir -p accounts downloads runtime/control
chmod 700 runtime runtime/control
chmod 600 config.py .env.server

# הבדיקה עוצרת מראש סודות חסרים או כפולים לפני שמתחילה בניית Docker.
python3 deploy/server/validate_deployment_secrets.py

if ! docker inspect wzmlx-mongodb >/dev/null 2>&1; then
  deploy/server/install.sh
fi
docker compose -f docker-compose.server.yml config --quiet
docker compose -f docker-compose.server.yml build
docker compose -f docker-compose.server.yml up -d
deploy/server/install-daily-backup.sh

echo "הבוט הופעל. לבדיקת מצב: deploy/server/wzmlx-status.sh"

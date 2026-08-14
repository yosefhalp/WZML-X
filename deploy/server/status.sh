#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
status="$(docker inspect wzmlx-mongodb --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')"
echo "מצב MongoDB: $status"

if [[ "$status" != "healthy" ]]; then
  docker logs --tail 80 wzmlx-mongodb
  exit 1
fi

docker exec wzmlx-mongodb sh -lc \
  'mongosh --quiet --host 127.0.0.1 --username "$WZMLX_MONGO_USERNAME" --password "$WZMLX_MONGO_PASSWORD" --authenticationDatabase wzmlx wzmlx --eval "quit(db.adminCommand(\"ping\").ok ? 0 : 2)"'
echo "בדיקת החיבור של משתמש הבוט עברה בהצלחה."

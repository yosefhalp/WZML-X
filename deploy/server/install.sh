#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -s .env.mongo ]]; then
  echo "חסר הקובץ .env.mongo שמכיל את פרטי הגישה." >&2
  exit 1
fi

chmod 600 .env.mongo DATABASE_URL.secret 2>/dev/null || true
docker compose -f mongodb.compose.yml config --quiet
docker compose -f mongodb.compose.yml pull
docker compose -f mongodb.compose.yml up -d

for _ in $(seq 1 40); do
  status="$(docker inspect wzmlx-mongodb --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
  [[ "$status" == "healthy" ]] && break
  sleep 2
done

./status.sh

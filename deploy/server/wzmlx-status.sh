#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
docker compose -f docker-compose.server.yml ps
docker inspect wzmlx-hebrew-bot --format 'מצב={{.State.Status}} בריאות={{if .State.Health}}{{.State.Health.Status}}{{else}}ללא בדיקה{{end}} אתחולים={{.RestartCount}}'
docker logs --tail 100 wzmlx-hebrew-bot

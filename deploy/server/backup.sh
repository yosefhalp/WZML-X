#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="backups/wzmlx-${stamp}.archive.gz"

docker exec wzmlx-mongodb sh -lc \
  'mongodump --quiet --host 127.0.0.1 --username "$WZMLX_MONGO_USERNAME" --password "$WZMLX_MONGO_PASSWORD" --authenticationDatabase wzmlx --db wzmlx --archive --gzip' \
  > "$target"

chmod 600 "$target"
sha256sum "$target" > "${target}.sha256"
echo "הגיבוי נשמר ב־$target"

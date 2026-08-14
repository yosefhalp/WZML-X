#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
archive="${1:-}"

if [[ -z "$archive" || ! -f "$archive" ]]; then
  echo "שימוש: ./restore.sh backups/wzmlx-YYYYMMDDTHHMMSSZ.archive.gz" >&2
  exit 1
fi

echo "השחזור יחליף את תוכן מסד wzmlx בקובץ: $archive"
read -r -p "כדי להמשיך, הקלד בדיוק RESTORE: " confirmation
[[ "$confirmation" == "RESTORE" ]] || { echo "השחזור בוטל."; exit 1; }

docker exec -i wzmlx-mongodb sh -lc \
  'mongorestore --quiet --host 127.0.0.1 --username "$WZMLX_MONGO_USERNAME" --password "$WZMLX_MONGO_PASSWORD" --authenticationDatabase wzmlx --db wzmlx --drop --archive --gzip' \
  < "$archive"

./status.sh
echo "השחזור הושלם."

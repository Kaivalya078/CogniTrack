#!/usr/bin/env bash
# Nightly backup: dump the database, check the dump reads back, copy it off the VM, keep 14 days
# locally. Cron runs it (docs/deploy.md); a failure exits non-zero and says why in the log.
#
#   infra/backup.sh                     # uses .env in the repo root
#   ENV_FILE=/path/.env infra/backup.sh
set -euo pipefail
umask 077  # dumps hold the whole ledger: readable by this user only

repo=$(cd "$(dirname "$0")/.." && pwd)
env_file=${ENV_FILE:-$repo/.env}
backup_dir=${BACKUP_DIR:-/var/backups/cognitrack}
keep_days=14

# Read single settings from .env without `source`, which would run it as shell code.
setting() { grep -E "^$1=" "$env_file" | tail -n 1 | cut -d= -f2- || true; }
user=$(setting POSTGRES_USER)
db=$(setting POSTGRES_DB)
# A write-only pre-authenticated request (PAR) URL for an Object Storage bucket, ending in /o/.
upload_url=$(setting BACKUP_UPLOAD_URL)
[ -n "$upload_url" ] || { echo "BACKUP_UPLOAD_URL is not set in $env_file" >&2; exit 1; }

compose=(docker compose -f "$repo/infra/docker-compose.prod.yml" --env-file "$env_file")
mkdir -p "$backup_dir"
name="cognitrack-$(date +%Y%m%d-%H%M%S).dump"
file="$backup_dir/$name"

"${compose[@]}" exec -T db pg_dump -U "$user" -d "$db" --format=custom > "$file.partial"
mv "$file.partial" "$file"
# A dump that pg_restore can't list is no backup.
"${compose[@]}" exec -T db pg_restore --list < "$file" > /dev/null

# The URL is a secret (it grants writes): pass it on stdin, not argv, where `ps` would show it.
printf 'url = "%s%s"\n' "$upload_url" "$name" |
  curl --config - --fail --silent --show-error --retry 3 --upload-file "$file"

find "$backup_dir" -name 'cognitrack-*.dump' -mtime +"$keep_days" -delete
echo "$(date -Is) ok $name $(wc -c < "$file") bytes"

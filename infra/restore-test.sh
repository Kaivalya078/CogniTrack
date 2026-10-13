#!/usr/bin/env bash
# Prove a backup restores: load it into a throwaway Postgres, then print the migration version and
# the ledger summary from the restored copy. Compare the summary with the live app's.
#
#   infra/restore-test.sh /var/backups/cognitrack/cognitrack-20261014-023000.dump
# Needs the cognitrack-api image (built by `docker compose ... up --build`).
set -euo pipefail

dump=${1:?usage: infra/restore-test.sh path/to/cognitrack-....dump}
container=cognitrack-restore-test
url=postgresql+psycopg://restore:restore@127.0.0.1:5432/restore

docker run -d --rm --name "$container" \
  -e POSTGRES_USER=restore -e POSTGRES_PASSWORD=restore -e POSTGRES_DB=restore postgres:16 > /dev/null
trap 'docker stop "$container" > /dev/null' EXIT

# Wait for TCP, not pg_isready: during first-start setup Postgres answers only on its socket.
for _ in $(seq 60); do
  docker exec "$container" psql -h 127.0.0.1 -U restore -d restore -c 'select 1' > /dev/null 2>&1 && break
  sleep 1
done

# --no-owner: the dump's role names don't exist here. Any error fails the test.
docker exec -i "$container" pg_restore -U restore -d restore --no-owner --exit-on-error < "$dump"

run() { docker run --rm --network "container:$container" -e DATABASE_URL="$url" \
  -e ALLOWED_HOSTS='["localhost"]' cognitrack-api "$@"; }
run alembic current
run python -m app.ledger.summary "${@:2}"
echo "Restore OK: $dump"

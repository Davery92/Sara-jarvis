#!/bin/sh
# Load the disposable test database's schema from the checked-in fixture,
# instead of pg_dump'ing production on every run.
#
# 2026-09-22 incident follow-up: `alembic upgrade head` cannot rebuild the
# schema from an empty database (the migration history has gaps assuming a
# pre-alembic baseline already existed — see docs/plans/incidents/
# 2026-09-22_test_run_against_live_db.md §7, deliberately not "fixed" here;
# that is a separate, real problem this script works around rather than
# solves). tests/fixtures/sara_hub_schema.sql is a one-time, read-only,
# schema-only (`pg_dump --schema-only`, no data rows) capture — regenerate
# it only when the real schema changes meaningfully and structural parity
# actually matters, not on every test run.
#
# Usage (from the repo root):
#   docker compose -f docker-compose.test.yml up -d --wait test-db test-redis
#   ./backend/scripts/provision_test_schema.sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHEMA_FILE="$SCRIPT_DIR/../tests/fixtures/sara_hub_schema.sql"
CONTAINER="${TEST_DB_CONTAINER:-sara-disposable-test-test-db-1}"

if [ ! -f "$SCHEMA_FILE" ]; then
  echo "Schema fixture not found at $SCHEMA_FILE" >&2
  exit 1
fi

docker exec "$CONTAINER" psql -U sara_test -d sara_hub_test -c \
  "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null

docker cp "$SCHEMA_FILE" "$CONTAINER":/tmp/sara_hub_schema.sql
docker exec "$CONTAINER" psql -U sara_test -d sara_hub_test -f /tmp/sara_hub_schema.sql >/tmp/provision_schema.log 2>&1
docker exec "$CONTAINER" rm -f /tmp/sara_hub_schema.sql

TABLE_COUNT=$(docker exec "$CONTAINER" psql -U sara_test -d sara_hub_test -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "Loaded schema fixture into sara_hub_test: $TABLE_COUNT tables."

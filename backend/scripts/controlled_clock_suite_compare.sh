#!/bin/bash
# Run the same test selection against two source trees at the same moment.
#
# The correction is explicit about why this exists: *"Use controlled-clock
# comparisons for the nine extra test failures; file modification dates alone do
# not establish that a failure is unrelated."* A file's mtime says when someone
# saved it. It says nothing about whether the test that fails today failed
# yesterday, and several of this suite's tests are time-sensitive by design
# (cooldown windows, recency ranking, "today" boundaries). The only thing that
# settles it is running both trees against the same clock, the same database
# engine, the same image, minutes apart.
#
#   BASELINE   the 2026-09-24 study's frozen source snapshot. It predates every
#              change this task made. It is NOT a perfect control: it also
#              predates David's own 09-25..09-28 working-tree changes, so a
#              failure present in the candidate and absent here could belong to
#              either. Where that matters, the module path decides it, and the
#              evidence map records which.
#
#   CANDIDATE  the working tree (the same bytes refreeze_reliable_candidate.sh
#              freezes and build_reliable_candidate_image.sh ships).
#
# Each side gets its OWN database, created fresh, so neither can leave rows that
# change the other's result — the durable idempotency receipts make that a real
# hazard rather than a theoretical one.
#
# Usage:
#   backend/scripts/controlled_clock_suite_compare.sh [pytest args...]
#   backend/scripts/controlled_clock_suite_compare.sh tests/test_unified_notification.py
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BASELINE="$REPO/backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/source_snapshot"
CANDIDATE="$REPO/backend"
OUT="${CONTROLLED_CLOCK_OUT:-$(mktemp -d)}"
mkdir -p "$OUT"
DBC="sara-disposable-test-test-db-1"
IMAGE="jarvis-backend:latest"
NET="sara-disposable-test_test_net"
SEL=("$@")
[ ${#SEL[@]} -eq 0 ] && SEL=("tests/")

[ -d "$BASELINE/app" ] || { echo "baseline snapshot missing: $BASELINE" >&2; exit 1; }
docker ps --format '{{.Names}}' | grep -qx "$DBC" || {
  echo "start the disposable stack first: docker compose -f docker-compose.test.yml -p sara-disposable-test up -d" >&2
  exit 1
}
NET=$(docker inspect "$DBC" -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)

run_side() {
  local name="$1" tree="$2" db="$3"
  docker exec "$DBC" psql -U sara_test -d sara_hub_test -tAc \
    "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    && docker exec "$DBC" psql -U sara_test -d sara_hub_test -c "DROP DATABASE $db" >/dev/null
  docker exec "$DBC" psql -U sara_test -d sara_hub_test \
    -c "CREATE DATABASE $db TEMPLATE sara_hub_test" >/dev/null 2>&1 \
    || docker exec "$DBC" psql -U sara_test -d sara_hub_test -c "CREATE DATABASE $db" >/dev/null
  docker exec "$DBC" psql -U sara_test -d "$db" \
    -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null 2>&1
  # Receipts and pending proposals are durable idempotency state: leaving them
  # in place makes a correct refusal look like a test failure.
  docker exec "$DBC" psql -U sara_test -d "$db" \
    -c "DELETE FROM action_receipt; DELETE FROM chat_pending_proposal;" >/dev/null 2>&1

  echo "--- $name: $(date -u +%Y-%m-%dT%H:%M:%SZ) ---" | tee -a "$OUT/timeline.txt"
  docker run --rm --network "$NET" \
    -v "$tree:/app" -w /app \
    -e SARA_TEST_ENV=disposable \
    -e DATABASE_URL="postgresql+psycopg://sara_test:disposable_test_only_pw@test-db:5432/$db" \
    -e REDIS_URL="redis://test-redis:6379/0" \
    -e EMBEDDING_BASE_URL="http://test-embeddings:8100" \
    -e WORLD_EVENTS_ENABLED=0 \
    -e PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint pytest "$IMAGE" "${SEL[@]}" -q -p no:cacheprovider \
    > "$OUT/$name.txt" 2>&1
  grep -E "^(FAILED|ERROR) " "$OUT/$name.txt" | sed 's/ - .*//' | sort -u > "$OUT/$name.ids"
  echo "$name: $(tail -1 "$OUT/$name.txt")"
}

echo "=== controlled-clock comparison, selection: ${SEL[*]} ==="
run_side baseline  "$BASELINE"  sara_hub_test_cc_baseline
run_side candidate "$CANDIDATE" sara_hub_test_cc_candidate

echo
echo "=== failing in BOTH (pre-existing, not this task's) ==="
comm -12 "$OUT/baseline.ids" "$OUT/candidate.ids" | sed 's/^/  /'
echo
echo "=== failing ONLY in the baseline (this task fixed, or diverged) ==="
comm -23 "$OUT/baseline.ids" "$OUT/candidate.ids" | sed 's/^/  /'
echo
echo "=== failing ONLY in the candidate — MUST be explained ==="
comm -13 "$OUT/baseline.ids" "$OUT/candidate.ids" | sed 's/^/  /'
echo
echo "artifacts: $OUT"

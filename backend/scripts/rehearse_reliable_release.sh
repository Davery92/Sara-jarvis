#!/bin/bash
# Rehearse the reliable-assistant release AND its recovery, end to end, on
# disposable databases. Touches nothing that production can see.
#
# Correction gap 6: "Prepare the exact candidate image, candidate-sourced
# migrations, and a genuinely tested recovery destination."
#
# What each of those means here, and why:
#
#   candidate image        the image built by build_reliable_candidate_image.sh,
#                          whose code was hashed against the validated manifest
#                          from inside the container. Every step below runs in
#                          THAT image, so the alembic that migrates, the app that
#                          serves, and the bytes that were validated are one set.
#
#   candidate-sourced      `alembic upgrade` is run from /app/alembic inside the
#   migrations             candidate image, never from the working tree. On
#                          2026-09-27 the live tree and the live schema were a
#                          pair that could not serve requests; running the
#                          migrations from a different tree than the one that
#                          will serve them is how that happens.
#
#   recovery destination   a database at the PREVIOUS release's revision (154),
#                          restored from a dump, that the PREVIOUS release's
#                          readiness probe actually passes. A rollback plan whose
#                          destination was never started is not a rollback plan:
#                          "downgrading migrations is an outage, not a rollback".
#
# Usage:  backend/scripts/rehearse_reliable_release.sh [image]
set -uo pipefail

IMAGE="${1:-sara-reliable-candidate:20260929}"
# The revision this release is MEANT to land on. Hardcoded as 158 until
# 2026-10-02, which was correct for generations 1-3 — they all shipped the
# same schema, so the literal and the intent agreed and nobody noticed they
# were the same line. The Fitness Coach release is the first to advance the
# schema, and the check failed the whole rehearsal on its own staleness
# while every substantive step passed.
#
# Parameterised rather than bumped, because bumping a literal leaves the
# next schema-advancing release to rediscover this. The check still has to
# be an EXPECTATION: asserting "the head is whatever the image says" would
# pass for any revision, including one nobody meant to ship.
EXPECT_HEAD="${2:-174_fitness_automation}"
REPO_BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
NET="sara-release-rehearsal"
DB="rehearsal-db"
PW="disposable_rehearsal_only_pw"
DSN="postgresql+psycopg://sara_rehearsal:${PW}@${DB}:5432/sara_rehearsal"
FAIL=0

say() { printf '\n=== %s ===\n' "$*"; }
ok()  { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAIL=1; }

cleanup() {
  docker rm -f "$DB" rehearsal-api rehearsal-redis rehearsal-embeddings >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT
cleanup

say "disposable postgres (tmpfs, no volume, internal network)"
docker network create --internal "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" \
  --tmpfs /var/lib/postgresql/data:rw,size=2g \
  -e POSTGRES_USER=sara_rehearsal -e POSTGRES_PASSWORD="$PW" \
  -e POSTGRES_DB=sara_rehearsal \
  pgvector/pgvector:pg16 >/dev/null || { bad "postgres did not start"; exit 1; }

for i in $(seq 1 60); do
  docker exec "$DB" pg_isready -U sara_rehearsal -d sara_rehearsal >/dev/null 2>&1 && break
  sleep 1
done
# `vector` is required — the schema has vector columns. `uuid-ossp` is not: the
# models generate ids in Python, and asking for it in the same statement made a
# missing optional extension fail the whole check, which is how the first run of
# this script reported FAIL on a database that was in fact fine.
if docker exec "$DB" psql -U sara_rehearsal -d sara_rehearsal \
     -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null 2>&1; then
  ok "postgres up with pgvector"
else
  bad "pgvector is not available"
fi
docker exec "$DB" psql -U sara_rehearsal -d sara_rehearsal \
  -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' >/dev/null 2>&1 \
  && printf '  note  uuid-ossp available too\n' \
  || printf '  note  uuid-ossp not available; not required\n'

run_in_candidate() {
  docker run --rm --network "$NET" \
    -e DATABASE_URL="$DSN" -e SARA_TEST_ENV=disposable \
    -e REDIS_URL="redis://127.0.0.1:6379/0" \
    --entrypoint sh "$IMAGE" -c "$1"
}

say "1. the PREVIOUS release's schema, from the checked-in production capture"
# NOT `alembic upgrade 154` from empty. That does not work and is not supposed
# to: the migration history assumes a pre-alembic baseline already exists (see
# docs/plans/incidents/2026-09-22_test_run_against_live_db.md §7). Trying it here
# failed exactly the way that note predicts — `relation "episode" does not exist`
# on the first ALTER TABLE — which is worth recording, because a release plan
# built on "the migrations can rebuild it" would be a plan that cannot recover.
#
# The honest starting point is the real thing: tests/fixtures/sara_hub_schema.sql,
# a schema-only pg_dump of production taken 2026-09-22. It has saved_meal (154)
# and it does NOT have chat_pending_proposal (155) or revoked_token (156), so it
# IS the pre-release state this release moves off of.
FIXTURE="$REPO_BACKEND/tests/fixtures/sara_hub_schema.sql"
[ -f "$FIXTURE" ] || { bad "no schema fixture at $FIXTURE"; exit 1; }
docker cp "$FIXTURE" "$DB":/tmp/pre.sql >/dev/null
docker exec "$DB" psql -U sara_rehearsal -d sara_rehearsal -q -f /tmp/pre.sql \
  > /tmp/rehearsal_load.log 2>&1
TABLES=$(docker exec "$DB" psql -U sara_rehearsal -d sara_rehearsal -tAc \
  "select count(*) from information_schema.tables where table_schema='public'")
[ "$TABLES" -gt 100 ] && ok "pre-release schema loaded ($TABLES tables)" \
  || bad "only $TABLES tables loaded"

for t in chat_pending_proposal revoked_token; do
  PRESENT=$(docker exec "$DB" psql -U sara_rehearsal -d sara_rehearsal -tAc \
    "select to_regclass('$t') is not null")
  [ "$PRESENT" = "f" ] && ok "$t absent, as the previous release has it" \
    || bad "$t is already present — this is not the pre-release schema"
done

say "2. stamp it at the revision production actually records"
run_in_candidate 'cd /app && alembic stamp 154_saved_meal 2>&1 | tail -2' >/dev/null
AT=$(run_in_candidate 'cd /app && alembic current 2>/dev/null | tail -1')
printf '  at: %s\n' "$AT"
case "$AT" in
  *154*) ok "stamped 154_saved_meal" ;;
  *)     bad "stamp did not take: $AT" ;;
esac

say "2b. the recovery destination: a dump of that schema"
DUMPDIR=$(mktemp -d)
docker exec "$DB" pg_dump -U sara_rehearsal -d sara_rehearsal --no-owner \
  > "$DUMPDIR/pre_release_154.sql" 2>/dev/null
if [ -s "$DUMPDIR/pre_release_154.sql" ]; then
  ok "dump taken ($(wc -c < "$DUMPDIR/pre_release_154.sql") bytes)"
else
  bad "dump is empty"
fi

say "3. the release: up to $EXPECT_HEAD from the candidate image's own alembic"
if run_in_candidate 'cd /app && alembic upgrade head 2>&1 | tail -6'; then
  ok "upgraded to head"
else
  bad "the release migrations failed"
fi
AT=$(run_in_candidate 'cd /app && alembic current 2>/dev/null | tail -1')
printf '  at: %s\n' "$AT"
case "$AT" in
  *"$EXPECT_HEAD"*) ok "head is $EXPECT_HEAD" ;;
  *) bad "head is not $EXPECT_HEAD: $AT" ;;
esac

say "4. the four tables the release needs actually exist"
run_in_candidate 'cd /app && python - <<PY
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ["DATABASE_URL"])
want = ["chat_pending_proposal", "revoked_token", "action_receipt", "reminder"]
with e.connect() as c:
    for t in want:
        n = c.execute(text("select to_regclass(:t)"), {"t": t}).scalar()
        print(("  ok   " if n else "  MISS ") + t)
    cols = {r[0] for r in c.execute(text(
        "select column_name from information_schema.columns "
        "where table_name = '\''reminder'\''"))}
    for col in ("delivery_status", "claimed_at", "delivery_attempts", "last_error"):
        print(("  ok   reminder." if col in cols else "  MISS reminder.") + col)
PY' | tee "$DUMPDIR/schema_check.txt"
grep -q MISS "$DUMPDIR/schema_check.txt" && bad "a required object is missing" \
  || ok "every object the candidate queries is present"

say "5. RECOVERY: restore the 154 dump into a FRESH database and use it"
docker exec "$DB" psql -U sara_rehearsal -d postgres \
  -c "CREATE DATABASE sara_recovery;" >/dev/null 2>&1 \
  && ok "recovery destination created" || bad "could not create recovery db"
docker exec "$DB" psql -U sara_rehearsal -d sara_recovery \
  -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null 2>&1
docker exec -i "$DB" psql -U sara_rehearsal -d sara_recovery -q \
  < "$DUMPDIR/pre_release_154.sql" > "$DUMPDIR/restore.log" 2>&1
RDSN="postgresql+psycopg://sara_rehearsal:${PW}@${DB}:5432/sara_recovery"
RAT=$(docker run --rm --network "$NET" -e DATABASE_URL="$RDSN" \
        -e SARA_TEST_ENV=disposable --entrypoint sh "$IMAGE" \
        -c 'cd /app && alembic current 2>/dev/null | tail -1')
printf '  restored schema is at: %s\n' "$RAT"
case "$RAT" in
  *154*) ok "the recovery destination really is the previous release's schema" ;;
  *)     bad "restored schema is not 154: $RAT" ;;
esac

say "6. the restored destination is QUERYABLE, not just present"
run_in_candidate_db() {
  docker run --rm --network "$NET" -e DATABASE_URL="$1" \
    -e SARA_TEST_ENV=disposable --entrypoint sh "$IMAGE" -c "$2"
}
run_in_candidate_db "$RDSN" 'cd /app && python - <<PY
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ["DATABASE_URL"])
with e.connect() as c:
    n = c.execute(text("select count(*) from app_user")).scalar()
    print(f"  ok   app_user queryable ({n} rows)")
    print("  ok   saved_meal present" if c.execute(
        text("select to_regclass('\''saved_meal'\'')")).scalar()
        else "  MISS saved_meal")
    # And the proof that this is the PREVIOUS release: the columns the candidate
    # added must NOT be here. A "recovery" destination that already carries the
    # new schema is the forward state wearing a rollback label.
    cols = {r[0] for r in c.execute(text(
        "select column_name from information_schema.columns "
        "where table_name = '\''reminder'\''"))}
    print("  ok   reminder.delivery_status absent, as the previous release has it"
          if "delivery_status" not in cols else
          "  MISS this is not the previous release: delivery_status is present")
PY' | tee "$DUMPDIR/recovery_check.txt"
grep -q MISS "$DUMPDIR/recovery_check.txt" && bad "the recovery destination is wrong" \
  || ok "recovery destination verified"

say "7. the forward database still serves after the rehearsal"
run_in_candidate 'cd /app && python -c "
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ[\"DATABASE_URL\"])
with e.connect() as c:
    c.execute(text(\"select 1 from action_receipt limit 1\"))
    c.execute(text(\"select delivery_status from reminder limit 1\"))
print(\"  ok   the released schema answers the queries that 401ed on 2026-09-27\")
"' || bad "the released schema does not answer them"

say "8. the (source, schema) PAIR actually serves — readiness probe, not /health"
# The whole point of the 2026-09-27 incident: /health returned 200 while every
# request 401ed, because the on-disk tree and the live schema were a pair that
# could not serve. So the last step starts the CANDIDATE IMAGE against the
# database the release migrations just produced and runs the four-capability
# probe inside it. `readiness_probe.py` writes (a note, and a user if the probe
# email has none) and cleans up after itself, disclosing every row it touched.
docker run -d --name rehearsal-redis --network "$NET" redis:7-alpine >/dev/null 2>&1
# The probe writes a NOTE, and a note gets an embedding. Pointing the app at a
# dead embeddings port made checks 3 and 4 fail on the harness rather than on the
# pair under test — a false NOT READY, which is exactly as misleading as a false
# READY. The disposable embeddings image is offline-only (HF_HUB_OFFLINE) so it
# runs on this internal network with no outbound call.
docker run -d --name rehearsal-embeddings --network "$NET" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  jarvis-embeddings:latest >/dev/null 2>&1
for i in $(seq 1 60); do
  docker exec rehearsal-embeddings python3 -c "
import sys, urllib.request
try: urllib.request.urlopen('http://localhost:8100/health', timeout=2)
except Exception: sys.exit(1)
" >/dev/null 2>&1 && break
  sleep 2
done
API="rehearsal-api"
docker rm -f "$API" >/dev/null 2>&1
# The probe is mounted, not baked in. The image is the DEPLOYABLE artifact and
# carries application code only; `readiness_probe.py` is a validation tool, and
# shipping validation tooling inside a production image would put files in it
# that the candidate manifest does not certify.
SNAPTESTS="${CANDIDATE_SNAPSHOT_TESTS:-/home/david/sara-candidate-20260928-reliable/backend/tests}"
docker run -d --name "$API" --network "$NET" \
  -v "$SNAPTESTS:/app/tests:ro" \
  -e DATABASE_URL="$DSN" \
  -e REDIS_URL="redis://rehearsal-redis:6379/0" \
  -e SARA_TEST_ENV=disposable \
  -e WORLD_EVENTS_ENABLED=0 \
  -e EMBEDDING_BASE_URL="http://rehearsal-embeddings:8100" \
  "$IMAGE" >/dev/null 2>&1

UP=0
for i in $(seq 1 90); do
  if docker exec "$API" python -c "
import sys, urllib.request
try: urllib.request.urlopen('http://localhost:8000/health', timeout=3)
except Exception: sys.exit(1)
" >/dev/null 2>&1; then UP=1; break; fi
  sleep 3
done
if [ "$UP" -eq 1 ]; then
  ok "the candidate image is serving against the released schema"
  # -w /app and PYTHONPATH both, for the same reason the deployment procedure
  # passes PYTHONPATH: `docker exec` does not reliably inherit the image WORKDIR
  # on this daemon, and the probe's first act is to import `app`.
  docker exec -w /app -e PYTHONPATH=/app "$API" \
    python tests/assistant_acceptance/readiness_probe.py \
    > "$DUMPDIR/readiness_probe.txt" 2>&1
  PROBE=$?
  sed 's/^/  /' "$DUMPDIR/readiness_probe.txt" | tail -40
  [ "$PROBE" -eq 0 ] && ok "readiness probe: all four capabilities" \
    || bad "readiness probe failed (exit $PROBE) — see $DUMPDIR/readiness_probe.txt"
else
  bad "the candidate image never started serving; probe not run"
  docker logs "$API" 2>&1 | tail -20 | sed 's/^/  /'
fi
docker rm -f "$API" rehearsal-redis rehearsal-embeddings >/dev/null 2>&1

printf '\n'
if [ "$FAIL" -eq 0 ]; then
  echo "REHEARSAL PASSED — release path and recovery destination both exercised"
  echo "artifacts: $DUMPDIR"
  exit 0
fi
echo "REHEARSAL FAILED — see the FAIL lines above"
echo "artifacts: $DUMPDIR"
exit 1

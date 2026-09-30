#!/bin/bash
# One independently reset trial of the reliable-assistant journeys.
#
# Reliable-assistant plan §10 "Identity and pass rules": "Reset fixtures,
# conversation state, user-scoped memory, pending jobs, caches, and adapter
# receipts between independent trials." Each journey also gets a state dump
# taken straight from the database afterwards — the hidden outcome card is
# checked against that, never against Sara's account of what she did.
#
# Usage (from the repo root, with the validation env sourced):
#   backend/scripts/run_reliable_trial.sh trial1 J1_notes_facts J2_reminder_calendar ...
set -uo pipefail

TRIAL="$1"; shift
ART="${ASSISTANT_ACCEPTANCE_ARTDIR:?source the validation env first}"
UID_="${VAL_UID:?}"
TOKEN="${VAL_TOKEN:?}"
DC="docker compose -f docker-compose.assistant-acceptance.yml -f docker-compose.reliable-assistant.yml -p sara-reliable-validation"

OUT="$ART/$TRIAL"
mkdir -p "$OUT"

echo "=== $TRIAL: wait for the api to actually be listening ==="
# The api takes ~2-3 minutes to start (route registration, event bus, model
# catalog). The first dev-pass attempt ran six turns against a closed socket
# because nothing waited — six "Connection refused" turns, zero generations
# consumed, and no evidence. Poll rather than sleep.
for attempt in $(seq 1 90); do
  if $DC exec -T api python -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://localhost:8000/health', timeout=3)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
    echo "api is listening (after ${attempt} attempts)"
    break
  fi
  sleep 5
done

echo "=== $TRIAL: reset ==="
$DC exec -T -e PYTHONPATH=/app api python - <<PY 2>&1 | tail -20
from sqlalchemy import text
from app.db.base import SessionLocal
db = SessionLocal()
cleared = {}
for t in ("reminder", "timer", "daily_task", "list_item", "food_log", "note",
          "note_connection", "recipe", "action_receipt", "chat_pending_proposal",
          "notification_log", "conversation_turn", "episode"):
    try:
        cleared[t] = db.execute(
            text(f"DELETE FROM {t} WHERE user_id = :u"), {"u": "$UID_"}).rowcount
    except Exception as exc:
        db.rollback()
        cleared[t] = f"skip ({type(exc).__name__})"
db.commit()
print(cleared)
PY

echo "=== $TRIAL: flush redis (session tool cache, pending action state) ==="
$DC exec -T test-redis redis-cli FLUSHALL

echo "=== $TRIAL: seed the second plant-ish reminder (J6 ambiguity) ==="
$DC exec -T -e PYTHONPATH=/app api \
  python tests/assistant_acceptance/reliable_check.py "$UID_" seed-plants 2>&1 | tail -3

for J in "$@"; do
  echo
  echo "=== $TRIAL / $J ==="
  $DC exec -T -e PYTHONPATH=/app api python \
    tests/assistant_acceptance/reliable_drive.py "$TOKEN" \
    "tests/assistant_acceptance/journeys/${J}.json" \
    "/evidence/$TRIAL/${J}_transcript.json" 2>&1 | tee "$OUT/${J}_run.log"
  $DC exec -T -e PYTHONPATH=/app api python \
    tests/assistant_acceptance/reliable_check.py "$UID_" > "$OUT/${J}_state.json" 2>&1
  echo "--- state dumped to $OUT/${J}_state.json ---"
done

echo
echo "=== $TRIAL complete ==="

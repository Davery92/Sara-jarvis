#!/usr/bin/env bash
# Validate that all Celery queues used in routing/scheduling are covered
# by at least one worker's -Q subscription in docker-compose.dev.yml.
#
# Understands multiple workers (celery-worker, celery-acs, celery-critical, etc.)
#
# Usage: ./scripts/validate_queue_topology.sh [compose-file]
# Exit code 0 = all queues covered, 1 = drift detected

set -euo pipefail

COMPOSE_FILE="${1:-docker-compose.dev.yml}"

echo "Checking queue topology against $COMPOSE_FILE..."

# Extract ALL -Q queue lists from every celery worker command in the compose file
ALL_WORKER_QUEUES=$(grep -oP '(?<=-Q\s)[^\s"]+' "$COMPOSE_FILE" | tr ',' '\n' | sort -u)
if [ -z "$ALL_WORKER_QUEUES" ]; then
    echo "ERROR: Could not parse any -Q flags from $COMPOSE_FILE"
    exit 1
fi

echo "Worker queue subscriptions (all workers combined):"
echo "$ALL_WORKER_QUEUES" | sed 's/^/  /'

# Show per-worker breakdown
echo ""
echo "Per-worker breakdown:"
grep -P 'celery .* worker .* -Q' "$COMPOSE_FILE" | while read -r line; do
    QUEUES=$(echo "$line" | grep -oP '(?<=-Q\s)[^\s"]+')
    NAME=$(echo "$line" | grep -oP '(?<=-n\s)\S+' || echo "(default)")
    echo "  $NAME: $QUEUES"
done

# Extract queue names from celery_app.py beat_schedule and task_routes
CELERY_FILE="backend/app/celery_app.py"

# Queues from beat_schedule options
BEAT_QUEUES=$(grep -oP '"queue":\s*"([^"]+)"' "$CELERY_FILE" | grep -oP '"([^"]+)"$' | tr -d '"' | sort -u)

echo ""
echo "Queues referenced in beat_schedule:"
echo "$BEAT_QUEUES" | sed 's/^/  /'

# Queues from task_routes mapping
ROUTE_QUEUES=$(grep -oP "'queue':\s*'([^']+)'" "$CELERY_FILE" | grep -oP "'([^']+)'$" | tr -d "'" | sort -u || true)
# Also check for {"queue": "..."} syntax in routes
ROUTE_QUEUES2=$(grep -oP '"queue":\s*"([^"]+)"' "$CELERY_FILE" | grep -oP '"([^"]+)"$' | tr -d '"' | sort -u || true)

# Also extract queue names used in @celery_app.task(queue=...) across task files
TASK_QUEUES=""
for f in backend/app/tasks/*.py; do
    if [ -f "$f" ]; then
        TQ=$(grep -oP 'queue\s*=\s*["\x27]([^"\x27]+)["\x27]' "$f" 2>/dev/null | grep -oP '["\x27]([^"\x27]+)["\x27]$' | tr -d "\"'" || true)
        if [ -n "$TQ" ]; then
            TASK_QUEUES="$TASK_QUEUES $TQ"
        fi
    fi
done

# Combine all discovered queues
ALL_QUEUES=$(echo "$BEAT_QUEUES $ROUTE_QUEUES $ROUTE_QUEUES2 $TASK_QUEUES" | tr ' ' '\n' | sort -u | grep -v '^$')

echo ""
echo "All queues referenced (beat_schedule + task_routes + task files):"
echo "$ALL_QUEUES" | sed 's/^/  /'

# Find queues not covered by ANY worker subscription
MISSING=""
for q in $ALL_QUEUES; do
    if ! echo "$ALL_WORKER_QUEUES" | grep -qx "$q"; then
        MISSING="$MISSING $q"
    fi
done

if [ -n "$MISSING" ]; then
    echo ""
    echo "ERROR: The following queues are not covered by any worker's -Q subscription:"
    for q in $MISSING; do
        echo "  - $q"
    done
    exit 1
else
    echo ""
    echo "OK: All queues covered by at least one worker."
    exit 0
fi

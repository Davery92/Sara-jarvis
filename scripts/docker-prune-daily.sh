#!/usr/bin/env bash
#
# Daily docker artifact prune.
#
# Removes:
#   - Dangling images (untagged layers left behind by `docker compose build`).
#   - Unused build cache.
#   - Orphan anonymous volumes (NOT named volumes — postgres_data, neo4j_data,
#     etc. are safe).
#
# Does NOT remove:
#   - Images currently used by any container (running or stopped).
#   - Named volumes.
#   - Anything still referenced.
#
# Logs reclaimed space to /var/log/jarvis-docker-prune.log so growth can be
# correlated with rebuild activity.

set -euo pipefail

LOG="${HOME}/.local/share/jarvis-docker-prune.log"
mkdir -p "$(dirname "${LOG}")"
TS=$(date '+%Y-%m-%d %H:%M:%S %Z')

# df before/after for context
BEFORE=$(df -h --output=used / | tail -1 | tr -d ' ')

{
    echo "── ${TS} ──"
    echo "before: ${BEFORE} used on /"

    echo "image prune -f:"
    docker image prune -f 2>&1 | tail -1 | sed 's/^/  /'

    echo "builder prune -f:"
    docker builder prune -f 2>&1 | tail -1 | sed 's/^/  /'

    echo "volume prune -f:"
    docker volume prune -f 2>&1 | tail -1 | sed 's/^/  /'

    AFTER=$(df -h --output=used / | tail -1 | tr -d ' ')
    echo "after:  ${AFTER} used on /"
    echo
} >> "${LOG}" 2>&1

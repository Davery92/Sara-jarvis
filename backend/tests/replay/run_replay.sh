#!/usr/bin/env bash
# Run the 2026-09-09/10 replay suite.
#
#   backend/tests/replay/run_replay.sh              # all replays
#   backend/tests/replay/run_replay.sh -k calendar  # pytest args pass through
#
# Provisions sara_replay if it isn't there, then runs pytest inside the
# backend container with every store pointed somewhere disposable:
#
#   DATABASE_URL -> sara_replay   (built from the fixture by provision.py)
#   REDIS_URL    -> redis db 15   (working memory, caches, session state)
#
# The harness refuses to run at all if DATABASE_URL doesn't name the replay
# database, so a mistake here fails loudly instead of quietly replaying
# against David's real data.
#
# The compose file is named explicitly (2026-10-01). This used to be a bare
# `docker compose exec`, which resolved docker-compose.yml by default — that
# file has since been archived, so a bare call would now fail outright. `exec`
# only attaches to an already-running container, so this was never dangerous
# the way the rebuild scripts were; it just needs to say which project it means.
#
# Note this runs the suite inside PRODUCTION's backend container (project
# `jarvis`), which is also the pinned artifact — so it tests the deployed code,
# not the working tree. To replay the working tree, or to satisfy
# tests/env_guard.py's disposable-stack requirement, provision into a test
# stack instead; see provision.py's SARA_REPLAY_COMPOSE_* overrides.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if ! python3 backend/tests/replay/provision.py --check >/dev/null 2>&1; then
    echo "sara_replay not present — building it from the fixture..."
    python3 backend/tests/replay/provision.py
fi

LIVE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
if [[ -z "${LIVE_URL}" ]]; then
    echo "DATABASE_URL not found in .env" >&2
    exit 1
fi
REPLAY_URL="${LIVE_URL%/*}/sara_replay"

exec docker compose -f docker-compose.dev.yml -p jarvis exec -T \
    -e DATABASE_URL="${REPLAY_URL}" \
    -e REDIS_URL="redis://redis:6379/15" \
    -e SARA_REPLAY=1 \
    -e WORLD_EVENTS_ENABLED=0 \
    backend python -m pytest tests/replay -p no:cacheprovider "$@"

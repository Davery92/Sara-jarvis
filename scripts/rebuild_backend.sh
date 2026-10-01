#!/bin/bash
#
# OBSOLETE — and dangerous as written. Refuses by default. (2026-10-01)
#
# What this used to do, and why it cannot be allowed to:
#
#   DOCKER_BUILDKIT=1 docker compose build backend
#   docker compose up -d backend
#
# Those are BARE `docker compose` calls. With no `-f`, compose resolved
# `docker-compose.yml` into project `jarvis` — production — whose `backend`
# service declared `build:` against the working tree and carried no read-only
# `app/` mount. So this script's two lines meant:
#
#   * rebuild production's backend image from whatever is on disk right now, and
#   * recreate the container WITHOUT docker-compose.incident-recovery.yml,
#
# i.e. exactly the 2026-09-29 incident, from a script whose name invites use
# after any code change. (`docker-compose.yml` has since been archived to
# deploy/archive-compose/docker-compose.legacy.yml, so these calls would now
# fail for lack of a default file — but failing by accident is not a safeguard.)
#
# Production runs ONE pinned artifact. Code changes reach it by cutting a new
# generation, not by rebuilding a container in place:
#
#   1. commit the change (the pin is cut from committed git, not a dirty tree)
#   2. backend/scripts/refreeze_reliable_candidate.sh  <new snapshot path>
#   3. backend/scripts/build_reliable_candidate_image.sh <snapshot> <tag>
#   4. backend/scripts/rehearse_reliable_release.sh <tag>
#        -> must print REHEARSAL PASSED, including the readiness probe
#   5. python backend/scripts/check_extracted_route_names.py   (if routes moved)
#   6. update the four EXPECT_* values at the top of scripts/sara-prod AND the
#      image + frozen path in docker-compose.incident-recovery.yml
#   7. scripts/sara-prod cutover
#
# Full procedure and rollback: RECOVERY.md
#
# To see the live stack without changing it:  scripts/sara-prod verify | ps | logs
#
set -euo pipefail

cat >&2 <<'MSG'
REFUSING: scripts/rebuild_backend.sh is obsolete.

  It ran a bare `docker compose build backend && docker compose up -d backend`,
  which rebuilt production from the working tree and recreated it without the
  pin overlay — the 2026-09-29 incident.

  To get a code change into production, cut a new pinned generation:
    refreeze_reliable_candidate.sh -> build_reliable_candidate_image.sh
    -> rehearse_reliable_release.sh -> update sara-prod + the pin overlay
    -> scripts/sara-prod cutover
  See the comments at the top of this file, and RECOVERY.md.

  To look at production without changing it:
    scripts/sara-prod verify | ps | logs [svc]
MSG
exit 1

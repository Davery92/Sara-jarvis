#!/bin/bash
#
# OBSOLETE — see scripts/rebuild_backend.sh for the full explanation. (2026-10-01)
#
# This was the "code only, assume dependencies unchanged" variant and carried
# the identical hazard: a bare `docker compose build backend` followed by
# `docker compose up -d backend` rebuilt production's backend from the working
# tree and recreated it without docker-compose.incident-recovery.yml.
#
# Code reaches production by cutting a new pinned generation. See
# scripts/rebuild_backend.sh and RECOVERY.md.
#
set -euo pipefail

cat >&2 <<'MSG'
REFUSING: scripts/quick_rebuild_backend.sh is obsolete.

  Same hazard as scripts/rebuild_backend.sh — it recreated production's backend
  from the working tree with no pin. Read that file's header for the
  new-generation procedure, or RECOVERY.md.

  Production, without changing it:  scripts/sara-prod verify | ps | logs [svc]
MSG
exit 1

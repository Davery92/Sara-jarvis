#!/bin/sh
# Re-freeze the reliable-assistant candidate from the working tree.
#
# The candidate is a frozen SOURCE SNAPSHOT: the validation stack mounts it, so
# the bytes that were validated and the bytes that would deploy are the same
# bytes. Any application change means re-freezing and re-running whatever live
# evidence that change could have affected — which is the plan's "change code
# only between frozen runs; record which evidence must be rerun".
#
# Excluded deliberately: venv, docker, static, uploads, data, sara_hub.db,
# celerybeat-schedule. None is imported code; see CANDIDATE_IDENTITY.txt.
set -eu
SNAP="${1:-/home/david/sara-candidate-20260928-reliable}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

for d in app alembic scripts migrations tests; do
  rsync -a --delete \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    --exclude='artifacts' \
    "$SRC/$d/" "$SNAP/backend/$d/"
done
cp "$SRC/alembic.ini" "$SRC/pytest.ini" "$SNAP/backend/"
[ -f "$SRC/requirements.txt" ] && cp "$SRC/requirements.txt" "$SNAP/backend/"

# The anonymous-volume mountpoints docker-compose.dev.yml declares INSIDE the
# read-only frozen mount must exist in the snapshot, or the container cannot
# start at all: runc has to create the mountpoint, and it cannot mkdir inside a
# read-only bind. This cost a short production outage during the 2026-09-30
# cutover — every application container came up "Created" and refused to start
# with `mkdirat .../app/app/__pycache__: read-only file system`.
#
# Generation 1 only worked by accident: its snapshot had root-owned __pycache__
# directories left behind before the mount went read-only. rsync excludes
# __pycache__ above (correctly — stale .pyc must never ship), so the directory
# has to be recreated empty here, deliberately.
#
# Keep this in sync with the `- /app/app/__pycache__` volume lines in
# docker-compose.dev.yml. /app/__pycache__ needs nothing: /app itself is not
# bind-mounted, so that mountpoint is created in the image's writable layer.
mkdir -p "$SNAP/backend/app/__pycache__"

cd "$SNAP"
find backend/app backend/alembic -type f ! -name '*.pyc' -print0 \
  | sort -z | xargs -0 sha256sum > CANDIDATE_MANIFEST.sha256
sha256sum CANDIDATE_MANIFEST.sha256 | awk '{print $1}' > CANDIDATE_MANIFEST_HASH
echo "files: $(wc -l < CANDIDATE_MANIFEST.sha256)"
echo "manifest sha256: $(cat CANDIDATE_MANIFEST_HASH)"
sha256sum -c --quiet CANDIDATE_MANIFEST.sha256 && echo "verified clean"

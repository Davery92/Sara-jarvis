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

cd "$SNAP"
find backend/app backend/alembic -type f ! -name '*.pyc' -print0 \
  | sort -z | xargs -0 sha256sum > CANDIDATE_MANIFEST.sha256
sha256sum CANDIDATE_MANIFEST.sha256 | awk '{print $1}' > CANDIDATE_MANIFEST_HASH
echo "files: $(wc -l < CANDIDATE_MANIFEST.sha256)"
echo "manifest sha256: $(cat CANDIDATE_MANIFEST_HASH)"
sha256sum -c --quiet CANDIDATE_MANIFEST.sha256 && echo "verified clean"

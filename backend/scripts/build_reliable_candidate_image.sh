#!/bin/sh
# Build the reliable-assistant candidate as an IMAGE, and prove the code inside
# it is the candidate's own bytes.
#
# Why an image and not the bind mount the validation stack uses (correction
# gap 6): a bind-mounted snapshot proves the bytes on the HOST, at the moment
# the container reads them. What deploys is an image. The two can differ — a
# stray edit, a rsync that missed a directory, a .pyc shadowing a deleted
# module — and the only way to know they don't is to build the image and hash
# what is inside it against the manifest that was validated.
#
# The base is `jarvis-backend:latest`, the same image the validation stack ran,
# so the dependency layer is byte-identical to the one the evidence was gathered
# on and this build changes exactly one thing: the application code. Building
# from backend/Dockerfile instead would re-resolve pip, which would make the
# image's dependency set a NEW untested variable at the last possible moment.
#
# Usage:
#   backend/scripts/build_reliable_candidate_image.sh [snapshot] [tag]
set -eu

SNAP="${1:-/home/david/sara-candidate-20260928-reliable}"
TAG="${2:-sara-reliable-candidate:20260929}"
BASE="${CANDIDATE_BASE_IMAGE:-jarvis-backend:latest}"

[ -f "$SNAP/CANDIDATE_MANIFEST.sha256" ] || {
  echo "no manifest at $SNAP — run refreeze_reliable_candidate.sh first" >&2
  exit 1
}

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

cat > "$BUILD/Dockerfile" <<EOF
FROM $BASE
WORKDIR /app
# The candidate's code replaces the base image's. Copied as separate layers so
# \`docker history\` shows exactly which directories this build changed.
COPY app /app/app
COPY alembic /app/alembic
COPY scripts /app/scripts
COPY migrations /app/migrations
COPY alembic.ini pytest.ini /app/
COPY CANDIDATE_MANIFEST.sha256 CANDIDATE_MANIFEST_HASH /candidate/
CMD ["uvicorn", "app.main_simple:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

cp -a "$SNAP/backend/app" "$SNAP/backend/alembic" "$SNAP/backend/scripts" \
      "$SNAP/backend/migrations" "$BUILD/" 2>/dev/null || true
cp "$SNAP/backend/alembic.ini" "$SNAP/backend/pytest.ini" "$BUILD/"
cp "$SNAP/CANDIDATE_MANIFEST.sha256" "$SNAP/CANDIDATE_MANIFEST_HASH" "$BUILD/"

# A .pyc left behind by a host-side pytest run would ship inside the image and
# could shadow a module the candidate no longer has. The manifest does not cover
# .pyc files, so this is the one thing the hash check below could not catch.
find "$BUILD" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -name '*.pyc' -delete 2>/dev/null || true

echo "=== building $TAG from $SNAP on $BASE ==="
docker build -t "$TAG" "$BUILD"

echo
echo "=== verifying the code INSIDE the image against the validated manifest ==="
# The manifest's paths are relative to the snapshot root (backend/app/...), and
# inside the image the same files live at /app/app/... — so verify from a
# directory where `backend/` resolves to /app.
docker run --rm --entrypoint sh "$TAG" -c '
  set -e
  mkdir -p /verify && ln -sfn /app /verify/backend
  cd /verify
  sha256sum -c --quiet /candidate/CANDIDATE_MANIFEST.sha256
  echo "image code matches the manifest: $(wc -l < /candidate/CANDIDATE_MANIFEST.sha256) files"
  echo "manifest sha256 in image: $(cat /candidate/CANDIDATE_MANIFEST_HASH)"
'

echo
echo "=== the modules this task added must actually be importable in the image ==="
# A placeholder DSN, because a route or task module builds an engine at
# import time and `settings.database_url` is empty in a bare container. The
# question here is "does this module import", not "can it connect": the DSN
# is never dialled, and it points at a port nothing listens on so a
# regression that DID try to connect fails loudly rather than reaching
# anything.
docker run --rm --entrypoint sh \
  -e DATABASE_URL='postgresql+psycopg://import_check:unused@127.0.0.1:1/unused' \
  "$TAG" -c '
  cd /app && python -c "
import importlib
for m in (
    \"app.services.operation_contract\",
    \"app.services.outcome_grounding\",
    \"app.services.reference_resolution\",
    \"app.services.request_recovery\",
    \"app.services.civil_time\",
    \"app.services.session_cache\",
    # Fitness Coach (FITNESS_COACH_IMPLEMENTATION_PLAN, steps 0-31). Listed
    # for the reason this check exists: a module can be present in the
    # manifest, registered in a router, and still fail to import — and 13
    # imports were dropped exactly that way moving handlers out of
    # main_simple. A file count proves the bytes shipped, not that they run.
    \"app.services.fitness.state\",
    \"app.services.fitness.consumers\",
    \"app.services.fitness.review_audit\",
    \"app.services.fitness.reviews\",
    \"app.services.fitness.safety\",
    \"app.services.fitness.recommendations\",
    \"app.services.fitness.coaching_jobs\",
    \"app.services.fitness.proactive\",
    \"app.services.fitness.photos\",
    \"app.services.fitness.photo_analysis\",
    \"app.services.fitness.science\",
    \"app.services.fitness.programming\",
    \"app.services.fitness.automation\",
    \"app.services.fitness.longitudinal\",
    \"app.services.fitness.sources\",
    \"app.services.fitness.privacy\",
    \"app.routes.fitness_coach\",
    \"app.routes.fitness_science\",
    \"app.tasks.fitness_coach\",
    \"app.tasks.fitness_science\",
):
    importlib.import_module(m)
    print(\"ok\", m)
"'

echo
echo "candidate image built and verified: $TAG"
echo "host manifest sha256: $(cat "$SNAP/CANDIDATE_MANIFEST_HASH")"

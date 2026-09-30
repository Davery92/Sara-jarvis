#!/bin/bash
# Run docker compose against a DISPOSABLE test stack, never production.
#
# Why this exists (2026-09-26): the reminder release-candidate work brought
# an acceptance stack up without an explicit `-p`. Compose defaulted the
# project name to the directory — `jarvis` — and placed 14 test containers
# in the SAME project as the running production stack. Nothing production
# was created, stopped or restarted, and the strays were removed by
# explicit name. But a later `docker compose down` in that project would
# have taken production with it. The default project name is the hazard;
# this script removes the default.
#
# Usage:
#   backend/scripts/disposable_compose.sh <project> <compose-args...>
#   backend/scripts/disposable_compose.sh sara-rc3-test -f docker-compose.test.yml up -d --wait
#   backend/scripts/disposable_compose.sh sara-rc3-test -f docker-compose.test.yml down -v
set -eu

PROD_PROJECT="jarvis"

if [ $# -lt 2 ]; then
  echo "usage: $0 <project-name> <docker-compose args...>" >&2
  echo "  project name is REQUIRED and must not be '$PROD_PROJECT'" >&2
  exit 2
fi

PROJECT="$1"; shift

# 1. The production project is never a valid target.
case "$PROJECT" in
  "$PROD_PROJECT"|"$PROD_PROJECT"_*|"")
    echo "REFUSED: '$PROJECT' is (or shadows) the production compose project." >&2
    echo "Disposable stacks must use their own project name, e.g. sara-<purpose>-test." >&2
    exit 1
    ;;
esac

# 2. The name must look disposable, so a typo cannot silently become a
#    long-lived stack sharing a namespace with something real.
case "$PROJECT" in
  sara-*-test|sara-*-study|sara-disposable-*) : ;;
  *)
    echo "REFUSED: '$PROJECT' does not look like a disposable project." >&2
    echo "Use sara-<purpose>-test, sara-<purpose>-study, or sara-disposable-<purpose>." >&2
    exit 1
    ;;
esac

# 3. Teardown is the dangerous verb: verify every container we are about to
#    remove actually belongs to this project before removing anything.
for arg in "$@"; do
  case "$arg" in
    down|rm|stop|kill)
      strays="$(docker ps -a \
        --filter "label=com.docker.compose.project=$PROJECT" \
        --format '{{.Names}}' | grep -vE "^${PROJECT}[-_]" || true)"
      if [ -n "$strays" ]; then
        echo "REFUSED: containers labelled project=$PROJECT but not named ${PROJECT}-*:" >&2
        echo "$strays" >&2
        echo "Refusing to tear down a project whose membership cannot be verified." >&2
        exit 1
      fi
      owned="$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
                 --format '{{.Names}}' | wc -l)"
      prod="$(docker ps -a --filter "label=com.docker.compose.project=$PROD_PROJECT" \
                --format '{{.Names}}' | wc -l)"
      echo "teardown target: project=$PROJECT ($owned containers). " \
           "production project '$PROD_PROJECT' holds $prod containers and is not a target."
      break
      ;;
  esac
done

exec docker compose -p "$PROJECT" "$@"

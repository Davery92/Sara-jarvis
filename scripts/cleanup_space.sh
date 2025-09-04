#!/usr/bin/env bash
set -euo pipefail

# Cleanup script to reclaim space in this repo.
# Dry-run by default: pass --apply to execute deletions.

APPLY=0
TARGETS=()

usage() {
  cat <<USAGE
Usage: $0 [--apply] [targets...]

Targets:
  venv            Remove backend Python virtualenv (reinstall later)
  node            Remove frontend/node_modules (reinstall later)
  builds          Remove build artifacts (frontend/dist)
  pycache         Remove __pycache__, .pytest_cache, .mypy_cache
  gitgc           Run 'git gc --prune=now --aggressive' to shrink .git
  dockerbin       Remove backend/docker bundled binaries (if unused)
  report          Only show size report (default)

Examples:
  $0                        # report only
  $0 venv node              # report + show deletions (dry-run)
  $0 --apply venv node      # actually delete venv and node_modules
  $0 --apply venv node builds pycache gitgc dockerbin
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage; exit 0
fi

for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    venv|node|builds|pycache|gitgc|dockerbin|report) TARGETS+=("$a") ;;
    *) echo "Unknown arg: $a"; usage; exit 1 ;;
  esac
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  TARGETS=(report)
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🔎 Size report (top-level):"
du -h -d 1 "$ROOT" | sort -h | tail -n 20 || true

echo "\n🔎 Backend breakdown:"
du -h -d 1 "$ROOT/backend" | sort -h | tail -n 20 || true

echo "\n🔎 Frontend breakdown:"
du -h -d 1 "$ROOT/frontend" | sort -h | tail -n 20 || true

do_delete() {
  local path="$1"
  if [[ $APPLY -eq 1 ]]; then
    echo "❌ Deleting: $path"
    rm -rf -- "$path"
  else
    echo "(dry-run) Would delete: $path"
  fi
}

for t in "${TARGETS[@]}"; do
  case "$t" in
    report) ;; # already printed
    venv)
      do_delete "$ROOT/backend/venv"
      ;;
    node)
      do_delete "$ROOT/frontend/node_modules"
      ;;
    builds)
      do_delete "$ROOT/frontend/dist"
      ;;
    pycache)
      echo "Scanning for caches…"
      mapfile -t caches < <(find "$ROOT" \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \) -type d)
      for c in "${caches[@]:-}"; do do_delete "$c"; done
      ;;
    gitgc)
      if [[ $APPLY -eq 1 ]]; then
        echo "Running git gc…"
        (cd "$ROOT" && git gc --prune=now --aggressive || true)
      else
        echo "(dry-run) Would run: git gc --prune=now --aggressive"
      fi
      ;;
    dockerbin)
      do_delete "$ROOT/backend/docker"
      ;;
  esac
done

if [[ $APPLY -eq 0 ]]; then
  echo "\nNo changes made (dry-run). Re-run with --apply to execute."
fi


#!/usr/bin/env bash
#
# One-command deploy + version stamping (Phase 7).
#
#   deploy/deploy.sh backend       build + recreate backend/celery, verify /health/version
#   deploy/deploy.sh daemon        rsync acs-daemon/ -> Sara VM, restart unit, verify heartbeat
#   deploy/deploy.sh jetson        rsync jetson/sara-voice/ -> Jetson, restart service, probe
#   deploy/deploy.sh all           backend, then daemon, then jetson
#
# Every target stamps the deployed git SHA so drift ("daemon is 3 commits behind")
# is detectable. Idempotent and safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
FULL_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

DAEMON_HOST="${SARA_DAEMON_HOST:-sara@10.185.1.176}"
DAEMON_PATH="${SARA_DAEMON_PATH:-/opt/acs-daemon}"
DAEMON_KEY="${SARA_DAEMON_KEY:-$HOME/.ssh/sara_agent}"
JETSON_HOST="${JETSON_HOST:-david@10.185.1.84}"
JETSON_PATH="${JETSON_PATH:-/home/david/sara-voice}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
COMPOSE="docker compose -f docker-compose.dev.yml"

log() { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[deploy:err]\033[0m %s\n' "$*" >&2; }

stamp_version() {  # writes backend/VERSION consumed by app.core.version
  echo "$FULL_SHA $BUILT_AT" > "$REPO_ROOT/backend/VERSION"
  log "stamped backend/VERSION = $SHA $BUILT_AT"
}

deploy_backend() {
  stamp_version
  log "building backend image…"
  $COMPOSE build backend
  log "recreating backend + celery (--force-recreate for the celery include gotcha)…"
  $COMPOSE up -d --force-recreate backend celery-worker celery-beat
  log "waiting for /health/version…"
  for i in $(seq 1 30); do
    if v=$(curl -fsS "$BACKEND_URL/health/version" 2>/dev/null); then
      log "backend deployed: $v"; return 0
    fi
    sleep 3
  done
  err "backend did not report /health/version in time"; return 1
}

deploy_daemon() {
  stamp_version
  if ! ssh -i "$DAEMON_KEY" -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new "$DAEMON_HOST" true 2>/dev/null; then
    err "cannot reach daemon host $DAEMON_HOST (key $DAEMON_KEY)"; return 1
  fi
  log "rsync acs-daemon/ -> $DAEMON_HOST:$DAEMON_PATH…"
  rsync -az --delete -e "ssh -i $DAEMON_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude '__pycache__' --exclude '.venv' --exclude '*.pyc' \
    "$REPO_ROOT/acs-daemon/" "$DAEMON_HOST:$DAEMON_PATH/"
  # stamp the daemon's deployed SHA so its heartbeat can report it
  ssh -i "$DAEMON_KEY" "$DAEMON_HOST" "echo '$FULL_SHA $BUILT_AT' | sudo tee $DAEMON_PATH/VERSION >/dev/null"
  log "restarting daemon unit…"
  ssh -i "$DAEMON_KEY" "$DAEMON_HOST" "sudo systemctl restart acs-daemon" || {
    err "daemon restart failed"; return 1; }
  sleep 4
  log "daemon status:"
  ssh -i "$DAEMON_KEY" "$DAEMON_HOST" "systemctl is-active acs-daemon && tail -n 3 /var/log/acs-daemon.log 2>/dev/null || true"
  log "daemon deployed ($SHA)"
}

deploy_jetson() {
  if ! ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new "$JETSON_HOST" true 2>/dev/null; then
    err "cannot reach Jetson $JETSON_HOST"; return 1
  fi
  log "rsync jetson/sara-voice/ -> $JETSON_HOST:$JETSON_PATH…"
  rsync -az --delete -e "ssh -o StrictHostKeyChecking=accept-new" \
    --exclude '.venv' --exclude '__pycache__' --exclude 'models/*.onnx' --exclude 'models/*.bin' \
    "$REPO_ROOT/jetson/sara-voice/" "$JETSON_HOST:$JETSON_PATH/"
  log "restarting sara-voice service (Jetson has NO passwordless sudo — may prompt)…"
  ssh -t "$JETSON_HOST" "sudo systemctl restart sara-voice" || {
    err "jetson service restart failed (sudo?)"; return 1; }
  sleep 4
  ssh "$JETSON_HOST" "systemctl is-active sara-voice || true"
  log "jetson deployed — verify a wake event lands within a few minutes"
}

TARGET="${1:-}"
case "$TARGET" in
  backend) deploy_backend ;;
  daemon)  deploy_daemon ;;
  jetson)  deploy_jetson ;;
  all)     deploy_backend && deploy_daemon && deploy_jetson ;;
  *) echo "usage: $0 {backend|daemon|jetson|all}"; exit 2 ;;
esac

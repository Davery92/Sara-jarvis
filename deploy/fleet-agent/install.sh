#!/usr/bin/env bash
#
# sara-fleet-agent installer (FLEET_DESIGN.md §8).
#
#   curl -fsSL https://sara.avery.cloud/api/fleet/install.sh | sudo bash -s -- \
#     --enroll <FLEET_ENROLL_SECRET> [--name gpu-box] [--url https://sara.avery.cloud]
#
# Idempotent: re-running upgrades the agent and re-enrolls. `--uninstall` reverses it.
# Contains NO secrets — the enroll secret is passed on the command line by David
# (from the app's "Add machine" sheet).
set -euo pipefail

URL="https://sara-api.avery.cloud"   # API domain (the SPA host sara.avery.cloud does NOT proxy /api)
ENROLL_SECRET=""
NAME=""
UNINSTALL=0

AGENT_BIN="/usr/local/bin/sara-fleet-agent"
CONFIG_DIR="/etc/sara-agent"
CONFIG_FILE="${CONFIG_DIR}/config.json"
SPOOL_DIR="/var/spool/sara-agent"
UNIT_FILE="/etc/systemd/system/sara-fleet-agent.service"
SVC_USER="sara-agent"

log() { echo -e "\033[36m[sara-fleet-agent]\033[0m $*"; }
err() { echo -e "\033[31m[sara-fleet-agent] ERROR:\033[0m $*" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enroll)    ENROLL_SECRET="${2:-}"; shift 2;;
    --name)      NAME="${2:-}"; shift 2;;
    --url)       URL="${2:-}"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) err "unknown argument: $1"; exit 2;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  err "must run as root (use sudo). On hosts without passwordless sudo, run inside 'sudo -i'."
  exit 1
fi

URL="${URL%/}"

# --------------------------------------------------------------------------
# Uninstall
# --------------------------------------------------------------------------
if [[ $UNINSTALL -eq 1 ]]; then
  log "uninstalling…"
  systemctl disable --now sara-fleet-agent.service 2>/dev/null || true
  rm -f "$UNIT_FILE" "$AGENT_BIN"
  rm -rf "$CONFIG_DIR" "$SPOOL_DIR"
  systemctl daemon-reload 2>/dev/null || true
  userdel "$SVC_USER" 2>/dev/null || true
  log "removed. (fleet registry row on the backend is untouched — revoke it in the app if you want it gone.)"
  exit 0
fi

# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------
if [[ -z "$ENROLL_SECRET" ]]; then
  err "missing --enroll <secret>. Get the full command from the app: Machines → Add machine."
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found. Install python3 (>= 3.8) and re-run."
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
log "python3 ${PYV} detected"

MACHINE_ID=""
[[ -r /etc/machine-id ]] && MACHINE_ID=$(cat /etc/machine-id)
[[ -z "$MACHINE_ID" && -r /var/lib/dbus/machine-id ]] && MACHINE_ID=$(cat /var/lib/dbus/machine-id)
if [[ -z "$MACHINE_ID" ]]; then
  err "no /etc/machine-id on this host; cannot enroll."
  exit 1
fi
HOSTNAME_S=$(hostname)
[[ -z "$NAME" ]] && NAME="$HOSTNAME_S"

# --------------------------------------------------------------------------
# Service user + directories
# --------------------------------------------------------------------------
if ! id "$SVC_USER" >/dev/null 2>&1; then
  log "creating system user ${SVC_USER}"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
fi

install -d -m 0755 "$CONFIG_DIR"
install -d -m 0755 -o "$SVC_USER" -g "$SVC_USER" "$SPOOL_DIR"

# --------------------------------------------------------------------------
# Fetch the agent + unit from the backend (served at /api/fleet/*)
# --------------------------------------------------------------------------
log "downloading agent…"
curl -fsSL "${URL}/api/fleet/agent.py" -o "$AGENT_BIN"
chmod 0755 "$AGENT_BIN"
chown root:root "$AGENT_BIN"

log "installing systemd unit…"
curl -fsSL "${URL}/api/fleet/agent.service" -o "$UNIT_FILE"
chmod 0644 "$UNIT_FILE"

# --------------------------------------------------------------------------
# Enroll → obtain per-host token
# --------------------------------------------------------------------------
log "enrolling with ${URL}…"
ENROLL_BODY=$(printf '{"enroll_secret":"%s","machine_id":"%s","hostname":"%s","name":"%s"}' \
  "$ENROLL_SECRET" "$MACHINE_ID" "$HOSTNAME_S" "$NAME")
ENROLL_RESP=$(curl -fsSL -X POST "${URL}/api/fleet/enroll" \
  -H "Content-Type: application/json" -d "$ENROLL_BODY") || {
    err "enrollment failed — check the enroll secret and that ${URL} is reachable."
    exit 1
  }

TOKEN=$(printf '%s' "$ENROLL_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')
INTERVAL=$(printf '%s' "$ENROLL_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("report_interval",300))')
if [[ -z "$TOKEN" ]]; then
  err "enroll response had no token: $ENROLL_RESP"
  exit 1
fi

log "writing config…"
umask 077
cat > "$CONFIG_FILE" <<EOF
{
  "url": "${URL}",
  "token": "${TOKEN}",
  "report_interval": ${INTERVAL}
}
EOF
chmod 0640 "$CONFIG_FILE"
chown root:"$SVC_USER" "$CONFIG_FILE"

# --------------------------------------------------------------------------
# Enable + start
# --------------------------------------------------------------------------
log "enabling service…"
systemctl daemon-reload
systemctl enable --now sara-fleet-agent.service

sleep 2
if systemctl is-active --quiet sara-fleet-agent.service; then
  log "✅ sara-fleet-agent is running as '${NAME}'. First report will land within ${INTERVAL}s."
  log "   Watch it in the app: Machines. Logs: journalctl -u sara-fleet-agent -f"
else
  err "service failed to start. Inspect: journalctl -u sara-fleet-agent -n 50"
  exit 1
fi

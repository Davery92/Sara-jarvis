#!/usr/bin/env bash
# Install / refresh the ACS daemon on the Sara VM.
# Run as root inside the VM. Idempotent.
set -euo pipefail

INSTALL_DIR=/opt/acs-daemon
CONFIG_DIR=/etc/acs-daemon
LOG_DIR=/var/log/acs-daemon
STATE_DIR=/var/lib/acs-daemon
SERVICE_USER=acs

if [[ $EUID -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

# 0. apt deps (Ubuntu) — idempotent
need_apt=()
command -v python3 >/dev/null 2>&1 || need_apt+=(python3)
python3 -c 'import venv' >/dev/null 2>&1 || need_apt+=(python3-venv)
command -v rsync >/dev/null 2>&1 || need_apt+=(rsync)
if (( ${#need_apt[@]} > 0 )); then
  echo "installing apt deps: ${need_apt[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${need_apt[@]}"
fi

# 1. user
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# 2. dirs
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$INSTALL_DIR" "$LOG_DIR" "$STATE_DIR"
install -d -m 750 -o root -g "$SERVICE_USER" "$CONFIG_DIR"

# 3. code (rsync from the dir this script lives in)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rsync -a --delete \
  --exclude venv --exclude __pycache__ --exclude '*.pyc' --exclude install.sh \
  "$SRC_DIR/" "$INSTALL_DIR/"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# 4. venv
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
  python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/venv"

# 5. config (only if missing — never overwrite an existing token)
if [[ ! -f "$CONFIG_DIR/config.env" ]]; then
  cat >"$CONFIG_DIR/config.env" <<'EOF'
# ACS daemon configuration. Restart the service after editing.
ACS_BACKEND_URL=https://sara-api.avery.cloud
ACS_DAEMON_TOKEN=replace-me-with-the-token-from-backend-env
ACS_LLM_URL=http://100.104.68.115:8081/v1
ACS_LLM_MODEL=qwen3.6-27b
ACS_TICK_INTERVAL=60
ACS_LOG_LEVEL=INFO
EOF
  chmod 640 "$CONFIG_DIR/config.env"
  chown root:"$SERVICE_USER" "$CONFIG_DIR/config.env"
  echo
  echo "WROTE $CONFIG_DIR/config.env — edit it and set ACS_DAEMON_TOKEN before starting."
  echo
fi

# 6. systemd unit
install -m 644 "$SRC_DIR/acs-daemon.service" /etc/systemd/system/acs-daemon.service
systemctl daemon-reload

echo "Installed. To start:"
echo "  sudo systemctl enable --now acs-daemon"
echo "Logs:"
echo "  sudo journalctl -u acs-daemon -f"

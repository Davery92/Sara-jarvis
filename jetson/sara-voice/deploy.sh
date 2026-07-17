#!/bin/bash
# Deploy sara-voice from the jarvis monorepo checkout to the Jetson device.
#
# Usage: JETSON_HOST=<host-or-ip> ./deploy.sh
# Defaults assume SSH access as the `david` user with a key already trusted
# (same pattern as the Sara VM access), and a deploy target of
# /home/david/sara-voice on the Jetson (matches systemd/sara-voice.service).

set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson.local}"
JETSON_USER="${JETSON_USER:-david}"
JETSON_PATH="${JETSON_PATH:-/home/david/sara-voice}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Deploying sara-voice to ${JETSON_USER}@${JETSON_HOST}:${JETSON_PATH} ==="

rsync -avz --delete \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='logs/*.log' \
  --exclude='models/*.onnx' \
  --exclude='models/*.bin' \
  --exclude='models/*.npy' \
  "${SCRIPT_DIR}/" "${JETSON_USER}@${JETSON_HOST}:${JETSON_PATH}/"

echo ""
echo "=== Installing systemd unit + restarting service ==="
ssh "${JETSON_USER}@${JETSON_HOST}" "\
  sudo cp ${JETSON_PATH}/systemd/sara-voice.service /etc/systemd/system/sara-voice.service && \
  sudo systemctl daemon-reload && \
  cd ${JETSON_PATH} && \
  (test -d .venv || python3 -m venv --system-site-packages .venv) && \
  .venv/bin/pip install -q --upgrade pip && \
  .venv/bin/pip install -q -r requirements.txt && \
  sudo systemctl restart sara-voice && \
  sleep 2 && \
  sudo systemctl status sara-voice --no-pager -l | head -15 \
"

echo ""
echo "=== Deploy complete. Model files (models/*.onnx, *.bin, *.npy) are NOT synced by this script — ==="
echo "=== copy them manually once if the target directory is new.                                    ==="

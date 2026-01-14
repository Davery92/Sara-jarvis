# Sara Headless Agent

A lightweight background service that connects Linux servers to Sara, providing system metrics and remote command capabilities.

## Features

- **System Metrics**: CPU, RAM, disk, network, and GPU (NVIDIA) monitoring
- **Real-time Updates**: Sends metrics to Sara backend via WebSocket
- **Remote Commands**: Execute allowed commands from Sara chat
- **Systemd Integration**: Runs as a proper Linux service
- **Security Hardened**: Runs as unprivileged user with restricted permissions

## Quick Install

```bash
# Download and extract
curl -L https://sara.avery.cloud/api/downloads/sara-agent-linux.tar.gz | tar xz
cd sara-agent

# Install (will prompt for auth token)
sudo ./install.sh

# Or with token directly
sudo ./install.sh --token YOUR_TOKEN_HERE
```

## Manual Install

1. Install Python 3.8+ and pip
2. Copy files to `/opt/sara-agent/`
3. Create virtual environment: `python3 -m venv /opt/sara-agent/venv`
4. Install deps: `/opt/sara-agent/venv/bin/pip install -r requirements.txt`
5. Create config at `/etc/sara-agent/config.json`
6. Install systemd service
7. Start: `systemctl start sara-agent`

## Configuration

Config file: `/etc/sara-agent/config.json`

```json
{
    "backend_url": "https://sara-api.avery.cloud",
    "backend_ws_url": "wss://sara-api.avery.cloud/api/devices/ws",
    "auth_token": "YOUR_TOKEN_HERE",
    "heartbeat_interval": 30,
    "metrics_interval": 60
}
```

## Commands

```bash
# Service management
sudo systemctl status sara-agent
sudo systemctl restart sara-agent
sudo systemctl stop sara-agent

# View logs
sudo journalctl -u sara-agent -f

# Uninstall
sudo /opt/sara-agent/install.sh --uninstall
```

## Getting Your Auth Token

1. Log in to Sara web app
2. Go to Settings
3. Find the "Connected Devices" section
4. Copy your authentication token

## Metrics Collected

- **CPU**: Usage %, core count, frequency, load average
- **Memory**: Total, used, available, swap
- **Disk**: Per-partition usage
- **Network**: Bytes sent/received, packets, errors
- **GPU** (if NVIDIA): Utilization, memory, temperature, power

## Security

The agent runs with minimal privileges:
- Dedicated `sara-agent` user
- No shell access
- Restricted filesystem access
- Only whitelisted commands can be executed remotely

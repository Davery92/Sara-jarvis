# ACS daemon — Sara's in-VM cognitive process

This is the new ACS, replacing the per-session container model. The dedicated
Ubuntu VM (`10.185.1.76`) is Sara's body; this daemon is her continuous mind.
Boots, ticks, stays alive across restarts, lives in the VM permanently.

**Phase 1 (this version)**: empty cognitive loop. Boots, posts a heartbeat to
the backend every 60s, handles SIGTERM cleanly, restarts on crash. No tools, no
LLM, no work. The point is to prove the body is alive.

Future phases fill in ambient self-context, the honest `notify_david` tool, the
inbox / hybrid trigger model, and recall-before-research. See the project
`MEMORY.md` and the discussion that produced this.

## Architecture

```
┌─────────────────────────┐  POST /api/acs/v2/heartbeat   ┌─────────────────┐
│   Sara VM 10.185.1.76   │ ─────────────────────────────▶│  Backend API    │
│   /opt/acs-daemon       │                               │  sara-api...    │
│   acs-daemon.service    │  ◀── (Phase 4: directives)    │                 │
└─────────────────────────┘                               └─────────────────┘
                                                                  │
                                                                  ▼
                                                        sara_daemon_state row
                                                        (singleton, upsert)
```

The daemon is the only thing initiating contact in Phase 1. Phase 4 will add a
control channel via the heartbeat response (queued inbox items, directives).

## Install (on the Sara VM, as root)

Prereqs: `python3`, `python3-venv`, `rsync` (the installer's `apt` step adds
them if missing on a clean Ubuntu).

```bash
# Copy the acs-daemon/ directory onto the VM (rsync from your dev box):
rsync -av --exclude venv /home/david/jarvis/acs-daemon/ sara@10.185.1.76:/tmp/acs-daemon/
ssh sara@10.185.1.76 "cd /tmp/acs-daemon && sudo ./install.sh"

# First-time setup: edit the config and set the daemon token.
sudo $EDITOR /etc/acs-daemon/config.env
#   ACS_BACKEND_URL=https://sara-api.avery.cloud
#   ACS_DAEMON_TOKEN=<same value as backend's ACS_DAEMON_TOKEN env>

sudo systemctl enable --now acs-daemon
sudo journalctl -u acs-daemon -f
```

Re-running `install.sh` updates the code and venv but never overwrites
`config.env`, so it's safe to run after every code change.

## Backend setup

1. Generate a token: `openssl rand -hex 32`
2. Set `ACS_DAEMON_TOKEN=<that value>` in the backend `.env`
3. Run alembic upgrade to create `sara_daemon_state` (migration 058)
4. Restart the backend
5. Set the same token in `/etc/acs-daemon/config.env` on the VM

## Verifying it's alive

```bash
# From your dev box, hitting the backend (replace BASE with sara-api.avery.cloud):
curl -b cookies.txt https://BASE/api/acs/v2/daemon-status | jq
# {
#   "state": "idle",
#   "version": "0.1.0",
#   "is_alive": true,
#   "seconds_since_heartbeat": 12,
#   ...
# }
```

`is_alive` flips to false if no heartbeat has arrived in 180s (3× the tick
interval). If the daemon crashes, systemd restarts it within 5s.

## Files

| Path                                   | What                              |
|----------------------------------------|-----------------------------------|
| `/opt/acs-daemon/daemon.py`            | Main loop                         |
| `/opt/acs-daemon/config.py`            | Env loader                        |
| `/opt/acs-daemon/venv/`                | Python deps                       |
| `/etc/acs-daemon/config.env`           | Backend URL + daemon token        |
| `/etc/systemd/system/acs-daemon.service` | systemd unit                    |
| `/var/log/acs-daemon/`                 | Reserved for future log files     |
| `/var/lib/acs-daemon/`                 | Reserved for future state on disk |

The unit is hardened (NoNewPrivileges, ProtectSystem=strict, etc). If the
daemon ever needs to write to the filesystem outside `/var/log/acs-daemon` or
`/var/lib/acs-daemon`, the unit needs an additional `ReadWritePaths=` entry.

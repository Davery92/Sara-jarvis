# sara-fleet-agent

The single-file health agent installed on every Linux box in David's fleet. See
`FLEET_DESIGN.md` (repo root) for the full design.

## Files

| File | Installed to | Notes |
|---|---|---|
| `sara_fleet_agent.py` | `/usr/local/bin/sara-fleet-agent` | stdlib-only Python 3.8+; collector + command runner + embedded whitelist |
| `sara-fleet-agent.service` | `/etc/systemd/system/` | hardened unit — read-only FS, no caps, MemoryMax/CPUQuota |
| `install.sh` | (run once) | creates `sara-agent` user, fetches the agent, enrolls, starts |

The backend serves all three so the installer can fetch them:
`GET /api/fleet/install.sh`, `/api/fleet/agent.py`, `/api/fleet/agent.service`
(none contain secrets).

## Install

Get the exact one-liner (with the enroll secret) from the app: **Machines → Add
machine**, or `GET /api/fleet/enroll-command`. It looks like:

```bash
curl -fsSL https://sara.avery.cloud/api/fleet/install.sh | sudo bash -s -- \
  --enroll <FLEET_ENROLL_SECRET> [--name gpu-box] [--url https://sara.avery.cloud]
```

Uninstall: `... | sudo bash -s -- --uninstall`.

## The read-only guarantee

Four independent layers (FLEET_DESIGN.md §5):
1. Server-side whitelist (`app/services/fleet/whitelist.py`).
2. **Agent-side whitelist** (embedded copy in `sara_fleet_agent.py`, authoritative).
3. No shell — `shlex.split` → argv → `subprocess.run(..., shell=False)`.
4. Kernel sandbox — the systemd unit makes the FS read-only to the process.

The agent's embedded `RULES`/`validate_command` must stay in sync with the backend
whitelist module. Both are pure stdlib for exactly this reason.

## Backend config

Requires `FLEET_ENROLL_SECRET` in the backend `.env`. Optional:
`FLEET_REPORT_INTERVAL` (default 300s), `FLEET_PUBLIC_URL` (default
`https://sara.avery.cloud`).

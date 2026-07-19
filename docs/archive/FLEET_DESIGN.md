# Sara Fleet — Health Agents + Read-Only Diagnostics for Every Box

**Status:** Design — not yet implemented
**Branch target:** `assistant-experience-jarvis`
**Author:** David + Claude, 2026-07-14

---

## 1. What David asked for

> "Build an agent for all my Linux boxes that reports system health to Sara. Build a
> way for Sara to gain access to every box that has the agent installed to run diag
> commands — just read permissions. I need her aware of everything I have."

Plus (added in review): *"the install command needs to be visible in the app somewhere
so I can always find it — a page on iOS and web with a dashboard of every machine."*

Four deliverables fall out of that:

1. **`sara-fleet-agent`** — a tiny daemon installed on every Linux machine that
   continuously pushes health telemetry to the Sara backend.
2. **A read-only diagnostic channel** — Sara can run a whitelisted, audited set of
   read-only commands on any agent-equipped box, without SSH keys, without inbound
   ports, and with no possibility of mutating the machine.
3. **A Machines dashboard on web + iOS** (§7) — every machine at a glance, with the
   enrollment one-liner one tap away behind an "Add machine" button, so onboarding a
   new box never requires digging through docs.
4. **Awareness, not just a dashboard** — fleet state flows into Sara's existing senses
   (working memory → salience → deliberation), so she *notices* "the Jetson's root
   disk crossed 90%" the same way she notices anything else in her umwelt, and only
   speaks when the attention economy says it's worth David's attention.

---

## 2. What already exists (and how this fits)

| Existing piece | What it does | Relationship to Fleet |
|---|---|---|
| `ManagedHost` model + `routes/hosts.py` | Registry of machines Sara can SSH into ("check out gpu-box") | **Extended, not duplicated.** ManagedHost becomes the single fleet registry; the agent is a second *transport* alongside SSH. |
| `host_inspector.py` | One-shot SSH probe → structured spec → markdown report | Stays, for ad-hoc inspection of boxes *without* the agent (and macOS). Its `render_report()` style is reused for fleet reports. |
| `host_command_handler.py` | Chat intercept for `/host` + "check out \<name\>" | Extended with fleet subcommands and fleet-aware natural language ("how's the fleet"). |
| `Machine` / shadow models (`machine.py`) | Desktop activity shadowing (keyboard/mouse/screenshots) | **Untouched.** Different concern (presence/activity), different lifecycle. Fleet is infrastructure health. |
| `event_bus.py` → `working_memory` → `salience.py` → `deliberation.py` | Sara's cognitive pipeline | Fleet alerts enter here as events — never as a bespoke notification path. |
| `body_sense.py` / interoception | Sara's sense of her *own* infrastructure | Fleet is the same sense pointed at *David's* infrastructure; the sara VM and jarvis host appear in both views from one data source. |
| `app/tools/registry.py` | Chat/ACS tool registry | Gains `fleet_status` and `fleet_diag` tools. |

**One Mind invariant check** (required for new features):

- *Continuity / Umwelt (1, 2):* telemetry lands in one queryable model (`ManagedHost.latest snapshot` + metrics history); alerts are experienced as **change against expectation** (edge-triggered state machine), not re-read rows.
- *Attention economy (3):* fleet alerts emit **intents** onto the event bus; the deliberation gate + attention system decide whether David hears about it. No direct pushes from the alert engine.
- *Single voice (4):* nothing in Fleet composes prose for David; alert intents carry structured payloads and the composer speaks.
- *Agency with a ledger (5):* every diag command is a row in `host_diag_command` — who asked, what ran, what came back. Read-only means undo is never needed, but the ledger exists anyway.
- *Self-maintenance (6):* the sara VM, the jarvis host, and the Proxmox node all run the agent too — Sara's interoception and David's fleet view are the same organ.

---

## 3. Architecture decision: push telemetry, pull commands

```
┌─────────────── every Linux box ───────────────┐
│  sara-fleet-agent (systemd, user sara-agent)  │
│  ┌─────────────┐      ┌─────────────────────┐ │
│  │ collector   │      │ command runner      │ │
│  │ every 60s   │      │ whitelist-enforced  │ │
│  └──────┬──────┘      └──────────▲──────────┘ │
└─────────┼────────────────────────┼────────────┘
          │ POST /api/fleet/report │ GET /api/fleet/commands (long-poll)
          │ (outbound HTTPS only)  │ POST /api/fleet/commands/{id}/result
          ▼                        │
┌──────── Sara backend (routes/fleet.py) ────────┐
│ ingest → ManagedHost.snapshot + host_metric    │
│ alert engine (edge-triggered) → event bus      │
│ command queue (host_diag_command, audited)     │
└──────┬─────────────────────────────────────────┘
       ▼
 working_memory → salience → deliberation → attention economy → David
 fleet context provider → chat/ACS context
 fleet_status / fleet_diag tools → chat, ACS daemon
```

**Why agent-push instead of SSH-pull everywhere:**

- **Coverage.** SSH-pull requires Sara's key on every box, reachable inbound SSH, and
  a poller. The agent needs only *outbound* HTTPS to the backend — works from any
  box, any NAT, no inbound surface.
- **Continuity.** Push every few minutes gives a live umwelt; SSH inspection is a
  snapshot when asked. Offline detection becomes trivial (missed check-ins).
- **Least privilege.** Sara never holds credentials to David's machines. The box
  volunteers data and executes only what its own local whitelist permits. A
  compromised backend still can't write to a fleet box.

**Why pull for commands (agent polls) instead of push (backend connects in):**

- No listening port on any box, no inbound firewall rules, no SSH key sprawl.
- The agent re-validates every command against its **local** whitelist — the backend
  is not trusted to define what "read-only" means on the box.

SSH transport remains for: boxes without the agent yet, macOS (Mac Studio), and as a
fallback when an agent is down ("check out gpu-box" still works).

---

## 4. The agent: `sara-fleet-agent`

### 4.1 Constraints

- **Single file, Python 3.8+ stdlib only.** No pip, no venv, no compiled deps —
  installs identically on Ubuntu, Debian, Proxmox VE nodes, and the Jetson (aarch64).
  Uses `urllib.request`, `json`, `subprocess`, `shlex`, `socket`, `os`, `time`.
- **Tiny footprint.** One process, < 30 MB RSS, negligible CPU. No local database;
  a small on-disk spool for reports made while the backend is unreachable.
- **Outbound only.** Never opens a listening socket.

### 4.2 Files on the box

```
/usr/local/bin/sara-fleet-agent          # the single .py file (mode 0755, root-owned)
/etc/sara-agent/config.json              # {"url", "token", "report_interval": 300} (0600, root:sara-agent 0640)
/etc/systemd/system/sara-fleet-agent.service
/var/spool/sara-agent/                   # offline report spool (owned by sara-agent)
```

### 4.3 systemd unit (hardened — this is half the security model)

```ini
[Unit]
Description=Sara fleet health agent
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/sara-fleet-agent
User=sara-agent
Group=sara-agent
Restart=always
RestartSec=10
# Read-only by construction, not by promise:
NoNewPrivileges=yes
ProtectSystem=strict            # whole FS read-only to the service
ReadWritePaths=/var/spool/sara-agent
ProtectHome=read-only
PrivateTmp=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=
MemoryMax=128M
CPUQuota=10%

[Install]
WantedBy=multi-user.target
```

Even if the command whitelist had a hole, the kernel enforces that this process
cannot write anywhere but its spool, cannot escalate, and cannot load modules.
`sara-agent` is a system user with no shell, no home, no sudo.

### 4.4 Telemetry collected

Collected every 60s; reported every `report_interval` (default 300s), **or
immediately** when an alert condition changes edge (so "disk just crossed 95%"
doesn't wait five minutes). One JSON snapshot per report:

| Group | Fields | Source |
|---|---|---|
| Identity | hostname, machine-id, agent version, OS pretty-name, kernel, arch | `/etc/os-release`, `uname`, `/etc/machine-id` |
| Uptime/load | uptime seconds, load 1/5/15, cpu count | `/proc/uptime`, `/proc/loadavg` |
| CPU | utilization % (delta of `/proc/stat` between ticks), per-core count | `/proc/stat` |
| Memory | total/used/available, swap total/used | `/proc/meminfo` |
| Disks | per real mount: size/used/avail/%, inode %; skip tmpfs/overlay/squashfs | `os.statvfs` over `/proc/mounts` |
| Network | per iface rx/tx bytes + computed rates, default route iface | `/proc/net/dev`, `/proc/net/route` |
| Temps | max + per-zone °C | `/sys/class/thermal/*/temp`, `/sys/class/hwmon` |
| systemd | failed unit names, `reboot-required` flag | `systemctl --failed --plain --no-legend`, `/var/run/reboot-required` |
| Updates | pending package count (checked hourly, cached) | `apt-get -s dist-upgrade` count / `dnf check-update` |
| Docker | if present: running/exited counts, unhealthy container names | `docker ps` (requires sara-agent in `docker` group — *optional*, off by default since docker group ≈ root; without it, field is absent) |
| GPU | if present: name, mem used/total, util %, temp | `nvidia-smi --query-gpu` / Jetson `/sys/devices/gpu.0/load` |
| Sessions | logged-in user count | `who` |
| Top | top 5 processes by CPU and by RSS | `ps -eo` |

Report payload target: **< 8 KB**. The backend stores the whole snapshot as
`latest`, and extracts a compact numeric row into `host_metric` for history.

### 4.5 Report loop behavior

- `POST {url}/api/fleet/report` with `Authorization: Bearer <host-token>`.
- Backend unreachable → spool the snapshot (keep last 24, drop oldest), retry with
  exponential backoff + jitter (10s → 5min cap). On reconnect, send the spool so
  Sara can backfill the gap.
- Clock skew immune: the server stamps arrival time; agent timestamps are advisory.

### 4.6 Command channel

- `GET {url}/api/fleet/commands?wait=25` — long-poll; returns `[]` on timeout or a
  list of pending commands. Effective diag latency ≈ instant while costing one idle
  HTTP request per 25s. (Boxes where that matters can set `wait=0, poll=60`.)
- For each command: validate against **the agent's own whitelist** (§5), execute
  via `subprocess.run(argv, shell=False, timeout=30)`, cap output at 64 KB,
  `POST /api/fleet/commands/{id}/result` with `{exit_code, stdout, stderr, denied?}`.
- A command the agent's whitelist rejects returns `denied` with the reason — it is
  **never** executed, regardless of what the server said.

---

## 5. The read-only guarantee (defense in depth)

Read-only is enforced at **four independent layers** — any one failing still leaves
the machine safe:

1. **Server-side whitelist.** `fleet_diag` validates the command against the shared
   whitelist before enqueueing. Bad requests never reach a box.
2. **Agent-side whitelist (authoritative).** The agent ships its own copy and
   re-validates. The backend is untrusted input as far as the box is concerned.
3. **No shell, ever.** Commands are parsed with `shlex.split` and executed as an
   argv array with `shell=False`. Pipes, redirection, `$(...)`, `;`, `&&` are
   simply inert characters that fail argv validation. No `bash -c` anywhere.
4. **Kernel enforcement.** The systemd sandbox (§4.3) makes the filesystem
   read-only to the process and blocks privilege escalation, so even a whitelist
   bug cannot mutate the system.

### 5.1 Whitelist format

Not a list of strings — a list of **rules**: allowed binary + argument policy.

```python
RULES = {
  "uptime":    Any(),
  "free":      Flags("-b", "-h", "-m"),
  "df":        Flags("-h", "-i", "-B1", "-x", "--output=..."),
  "lsblk":     Flags("-f", "-o", "..."),
  "ps":        Flags("-e", "-o", "--sort", "aux", ...),
  "ss":        Flags("-t","-u","-l","-n","-p","-s"),
  "ip":        Subcommands("addr", "route", "link", "-s"),      # never "ip link set"
  "uname":     Any(),
  "lscpu":     Any(),
  "dmesg":     Flags("--level", "-T", "--since"),               # may need kernel.dmesg_restrict=0
  "journalctl":Flags("-u","-n","--since","--until","-p","--no-pager","-k"),  # -f (follow) rejected
  "systemctl": Subcommands("status","list-units","list-timers","show","is-active","is-failed","cat"),  # start/stop/restart/enable rejected
  "docker":    Subcommands("ps","inspect","logs","stats --no-stream","images","system df"),  # logs requires --tail<=500; exec/run/rm rejected
  "nvidia-smi":Any(),
  "sensors":   Any(),
  "who":       Any(), "last": Flags("-n"),
  "du":        PathRestricted(depth-limited),
  "ls":        PathRestricted(),
  "cat":       PathRestricted(),   # also head/tail (tail -f rejected)
  "find":      PathRestricted(no "-exec", no "-delete"),
  "vgs/lvs/pvs/zpool/btrfs fi usage": read subcommands only,
}
```

**`PathRestricted`** — file-reading commands only accept absolute paths under an
allow-prefix list: `/proc`, `/sys`, `/var/log`, `/etc` — **minus** a deny list
(`/etc/shadow*`, `/etc/ssh/*_key`, `*.pem`, `/etc/sara-agent/*`, `/proc/*/environ`,
anything matching `*secret*|*credential*|*token*|*.key`). Paths are resolved with
`os.path.realpath` **before** checking (no symlink escapes), and must be regular
files/dirs.

Anything not matching a rule → denied, logged, reported back with the reason so
Sara can tell David *why* she couldn't run it instead of silently failing.

**Deliberately excluded from v1:** `smartctl` and anything needing root. If SMART
health is wanted later, the add-on is a single sudoers line
(`sara-agent ALL=(root) NOPASSWD: /usr/sbin/smartctl -H *`) installed explicitly —
never bundled silently.

### 5.2 Audit ledger

Every diag command is a `host_diag_command` row: host, requester (chat message /
deliberation run / ACS task id), argv, verdicts at each layer, exit code, output,
timings. `/api/fleet/audit` lists them; nothing executes off-ledger.

---

## 6. Backend changes

### 6.1 Registry: extend `ManagedHost` (one registry, two transports)

New columns (all nullable — existing SSH-only rows are untouched):

```
transport            String(16)  default "ssh"      # ssh | agent | both
machine_id           String(64)  unique-nullable    # /etc/machine-id, joins agent→row
agent_token_hash     String(64)                     # sha256 of per-host bearer token
agent_version        String(16)
agent_enrolled_at    DateTime(tz)
agent_last_report_at DateTime(tz)                   # freshness / offline detection
agent_snapshot       JSONB                          # latest full telemetry payload
agent_alert_state    JSONB                          # per-rule edge state (§6.4)
```

`last_inspection` (SSH) and `agent_snapshot` (push) coexist; readers prefer the
fresher one.

### 6.2 New tables

```
host_metric        — id, host_id FK, ts (server), cpu_pct, load1, mem_pct, swap_pct,
                     disk_max_pct, temp_max_c, net_rx_bps, net_tx_bps,
                     failed_units int, extras JSONB
                     • one row per report (~288/day/host)
                     • Celery beat prunes > 30 days nightly; index (host_id, ts)

host_alert         — id, host_id FK, rule (disk_critical|host_offline|...), state
                     (firing|resolved), detail JSONB, fired_at, resolved_at,
                     notified bool
                     • the edge-trigger ledger; one open row per (host, rule)

host_diag_command  — id, host_id FK, user_id, requested_by (chat|deliberation|acs|api),
                     request_context (message/run id), argv JSONB, status
                     (pending|running|done|denied_server|denied_agent|timeout|lost),
                     exit_code, stdout Text, stderr Text, created_at, started_at,
                     finished_at
                     • the audit ledger + the queue itself (status=pending is the queue)
```

Naive-datetime gotcha applies: **all timestamps `datetime.now(timezone.utc)`**;
user-facing rendering via `app.core.timezone` (ET).

### 6.3 API surface — `routes/fleet.py`

Agent-facing (auth: per-host bearer token; **no cookie auth**):

| Route | Purpose |
|---|---|
| `POST /api/fleet/enroll` | Body: `{enroll_secret, machine_id, hostname, name?}`. Validates `FLEET_ENROLL_SECRET` (new `.env` var), upserts ManagedHost by `machine_id` (creating with `transport=agent` or upgrading an SSH row to `both` when hostname matches), mints a 32-byte urlsafe token, stores only its sha256, returns the token **once**. |
| `POST /api/fleet/report` | Ingest snapshot → update `agent_snapshot` + `agent_last_report_at`, insert `host_metric`, run alert rules. Accepts a `spool` array for backfill. |
| `GET /api/fleet/commands?wait=25` | Long-poll pending commands for this host. Marks returned rows `running`. |
| `POST /api/fleet/commands/{id}/result` | Store result, mark done/denied. |

User-facing (normal cookie/JWT auth, David only):

| Route | Purpose |
|---|---|
| `GET /api/fleet/overview` | All hosts: name, online/offline, freshness, headline numbers, open alerts. Powers chat digest + future web panel. |
| `GET /api/fleet/hosts/{name}` | Full latest snapshot + open alerts. |
| `GET /api/fleet/hosts/{name}/metrics?hours=24` | History rows for trends/sparklines. |
| `POST /api/fleet/hosts/{name}/diag` | Body `{command}` → server-side whitelist check → enqueue → **wait up to 35s** for the result (covers the long-poll window) → return it. 202 + command id if slower. |
| `GET /api/fleet/audit` | Diag command ledger. |
| `POST /api/fleet/hosts/{name}/revoke` | Null the token hash (kill a lost/compromised box's access); agent re-enrolls with the secret if legitimate. |
| `GET /api/fleet/enroll-command` | Returns the ready-to-paste installer one-liner **including the current enroll secret**. Auth-gated (David only) — this is what the dashboard's "Add machine" button shows, so the command is always findable in the app (§7.3). |

Token handling: hash-compare via constant-time `hmac.compare_digest`; the plaintext
token exists only in the enroll response and `/etc/sara-agent/config.json`.

### 6.4 Alert engine (edge-triggered, anti-nag by construction)

Runs inline on each report ingest + a Celery beat sweep every 5 min for offline
detection. Rules (thresholds live in tunables, not code):

| Rule | Fires when | Clears when |
|---|---|---|
| `host_offline` | no report for 3× interval (15 min) | next report arrives |
| `disk_warning` / `disk_critical` | any mount ≥ 85% / ≥ 95% | back under threshold − 3% (hysteresis) |
| `mem_pressure` | mem ≥ 92% sustained 3 reports | < 85% |
| `load_high` | load1 > 2× cores sustained 3 reports | < 1× cores |
| `temp_high` | any zone ≥ 85 °C (Jetson-aware) | < 78 °C |
| `unit_failed` | a systemd unit enters failed | unit no longer failed |
| `reboot_required` | flag appears | flag gone (informational, low priority) |
| `updates_pending` | > 25 packages (weekly digest material, never a push) | — |

Mechanics that honor the feedback laws (**no repetitive nags**):

- State machine per (host, rule): alerts emit an event **only on the
  false→true edge** (and optionally a quiet resolved event). A disk sitting at 96%
  fires *once*, not every 5 minutes.
- Re-escalation only if severity increases (warning→critical) or after 24h
  still-firing.
- Alert events go to the **event bus** with structured payload
  (`fleet.alert`, host, rule, severity, numbers) → salience scoring → deliberation
  gate → attention economy. Fleet code never pushes.
- Severity mapping matters because of the attention-queue gotcha (normal-priority
  pushes become silent inbox items): `host_offline` and `*_critical` map to
  **high**; warnings map to normal (inbox/digest); `reboot_required`/`updates`
  are digest-only.

### 6.5 Sara's awareness (the actual point)

1. **Fleet context provider** (`services/fleet_context.py`) — produces a compact
   digest (≤ ~400 tokens, ContextBudget-aware): `6 hosts · all reporting · open
   alerts: jetson disk 91% (firing 2h)`. Injected into chat context when the
   conversation touches servers/infra (context router decides), and always
   available to deliberation.
2. **Tools** in `app/tools/registry.py`:
   - `fleet_status(host?)` — overview or one host's snapshot + recent trend.
   - `fleet_diag(host, command)` — the read-only diag channel; the tool description
     embeds the whitelist summary so the model proposes only runnable commands.
   Both usable from chat and the ACS daemon (host-targeted dispatch already exists;
   this gives it a safe read-only fast path that needs no SSH).
3. **Chat intercept** — extend `host_command_handler.py`:
   - `/host list` now shows live agent health (`● online · disk 91% ⚠` vs `○ ssh-only`).
   - `/fleet` (alias `/host fleet`) — full fleet digest.
   - Natural language: "how's the fleet", "are my servers ok", "anything wrong
     with my machines" → fleet digest; "why is \<host\> slow" → Sara chains
     `fleet_status` + `fleet_diag` (top, journalctl) and explains.
4. **PKG** — hosts become facts (`David owns host jetson (Jetson Orin Nano, at
   10.185.1.84, runs sara-voice)`) via the existing `upsert_fact()` path, so
   "what do I have running at home?" is answerable from memory even without a
   live query.
5. **Morning brief** — one line only when something is open: "Fleet: jetson root
   disk at 91%, everything else green." Silence when green.

---

## 7. The Machines dashboard (web + iOS)

Sara being aware is half the ask; David seeing everything at a glance is the other
half. One page, same layout on both clients, backed entirely by the §6.3 user-facing
endpoints (no new backend work beyond `GET /api/fleet/enroll-command`).

### 7.1 Web — `Machines` view

- **Files:** `frontend/src/components/machines/MachinesDashboard.tsx` (+
  `MachineDetail.tsx`). Follows the `system/SystemDashboard.tsx` pattern (same
  card/stat idiom, dark theme, `timeAgo` freshness).
- **Wiring:** new `machines` case in App-interactive.tsx's view-based routing,
  sidebar entry ("Machines", server icon) next to The System, and a Command
  Palette entry so `⌘K → mach…` always gets there.
- **Layout — overview grid.** One card per ManagedHost:
  - Header: name, `●` online / `○` offline / `◌` ssh-only (no agent), OS +
    arch chip, "last report 42s ago".
  - Body: three compact bars — CPU %, memory %, worst-disk % (color shifts at
    the §6.4 warning/critical thresholds) — plus load, temp, uptime.
  - Badges: open alerts (⚠ disk 91%), failed units count, reboot-required,
    pending updates.
  - Fleet header strip above the grid: `6 machines · 5 online · 1 alert`, and
    the **Add machine** button (§7.3).
- **Detail drawer/panel** (click a card):
  - Full latest snapshot (disks table, network rates, GPU, top processes,
    logged-in users).
  - 24h sparklines (CPU, mem, load, disk) from `GET /hosts/{name}/metrics` —
    plain SVG polylines, no chart lib needed.
  - Open + recent alerts with fired/resolved times.
  - **Diag console:** recent `host_diag_command` audit rows for this host, and a
    read-only command runner (input + a picker of common whitelisted commands:
    `journalctl -u X -n 100`, `df -h`, `ps aux --sort -pcpu`…) hitting
    `POST /hosts/{name}/diag`. Same channel Sara uses — David sees exactly what
    she can and can't run.
  - Actions: "Ask Sara about this machine" (opens chat pre-filled), SSH inspect
    (agent-less hosts), copy install command, revoke token, remove host.
- **Refresh:** poll `GET /api/fleet/overview` every 30s while the view is open
  (matches report cadence; no websocket needed for v1).

### 7.2 iOS — `Machines` screen

- **Files:** `ios-app/src/screens/machines/MachinesScreen.tsx` (+
  `MachineDetailScreen.tsx`), service calls in `src/services/`.
- **Wiring:** `Stack.Screen name="Machines"` in `AppNavigator.tsx`, and a
  **Machines** row in MoreScreen's existing **System** section (next to "The
  System"). JS-only change — a Metro reload gets it into David's EAS dev client,
  no native rebuild.
- **Layout:** same information architecture as web, phone-shaped: fleet summary
  header → vertical card list (name, status dot, three mini-bars, alert badge) →
  tap for detail screen (snapshot sections, sparklines via the existing Skia
  chart components from the fitness Progress tab, alerts, diag audit). Pull to
  refresh.
- Push notifications for critical alerts already come via the normal attention
  pipeline (§6.4) — the screen deep-links from those notifications
  (`machine:<name>` route param).

### 7.3 The install command — always findable

The enrollment one-liner must never live only in a doc or David's shell history:

- **"Add machine"** on the dashboard (both clients) opens a small sheet:
  the full `curl -fsSL … | sudo bash -s -- --enroll …` command rendered from
  `GET /api/fleet/enroll-command` with a copy button, plus the two variant flags
  (`--name`, `--uninstall`) and a note for the no-passwordless-sudo case
  (Jetson: paste it in an interactive root shell).
- The endpoint is auth-gated; the secret never appears in any unauthenticated
  page or in `install.sh` itself.
- Same text is available in chat: `/host help` and `/fleet` mention "say *add a
  machine* or open Machines → Add machine", and Sara can paste the command on
  request (`fleet_status` tool exposes it to her).
- When a brand-new host enrolls, the dashboard card appears on next poll —
  install feedback is visible within a minute, no page reload.

---

## 8. Installer & rollout

### 8.1 Installer

`deploy/fleet-agent/` in this repo: `sara_fleet_agent.py`, `sara-fleet-agent.service`,
`install.sh`. The backend serves them: `GET /api/fleet/install.sh` (public route,
contains no secrets).

```bash
curl -fsSL https://sara.avery.cloud/api/fleet/install.sh | sudo bash -s -- \
  --enroll <FLEET_ENROLL_SECRET> [--name gpu-box] [--url https://sara.avery.cloud]
```

install.sh: checks python3 ≥ 3.8 → creates `sara-agent` system user → writes the
three files → `POST /api/fleet/enroll` → writes config with the returned token →
`systemctl enable --now sara-fleet-agent` → prints the first snapshot. Idempotent
(re-running upgrades the agent file and re-enrolls). `--uninstall` reverses it all.

### 8.2 Rollout inventory (initial enrollment order)

| Box | Address | Notes |
|---|---|---|
| jarvis host (this machine) | 10.185.1.180 | Backend host — enroll first, easiest to debug |
| sara VM | 10.185.1.176 | ACS daemon host; feeds interoception too |
| sara-node (Proxmox) | 10.185.1.203 | PVE = Debian; agent works as-is |
| GPU host | 10.185.1.8 | Whisper/ASR box |
| Jetson (david-jetson) | 10.185.1.84 | **No passwordless sudo** — David runs the installer interactively; aarch64 fine (stdlib only) |
| Mac Studio | 100.104.68.115 | **macOS — out of scope for the Linux agent v1.** Stays on SSH transport (`/host check`); a darwin collector is a v2 item |

TLS note: boxes on the LAN can use `https://sara.avery.cloud` (public cert via
nginx proxy manager) — simplest and encrypted. Fallback `http://10.185.1.180:8000`
works but sends the token in the clear on the LAN; default to the domain.

---

## 9. Failure modes considered

| Failure | Behavior |
|---|---|
| Backend down / unreachable | Agent spools reports (last 24), backoff+jitter retry, backfills on reconnect. Sara notices her *own* outage via interoception, not false host-down alerts (offline sweep suppressed when ingest itself was down). |
| Host powered off | `host_offline` fires after 15 min, resolves on first report back. Deliberate shutdowns: Sara learns patterns over time; v1 just states facts once. |
| Token leaked | Token only grants: post telemetry + receive/answer diag commands for that one host. Revoke endpoint kills it; re-enroll mints a new one. |
| Enroll secret leaked | Worst case: attacker registers a fake host and feeds fake telemetry (annoying, not destructive). Rotate the `.env` secret; existing host tokens unaffected. |
| Agent bug / runaway | systemd `MemoryMax=128M`, `CPUQuota=10%`, `Restart=always`. Agent is a leaf — it can't take anything down with it. |
| Whitelist bypass attempt | Four layers (§5); the interesting ones are argv-only execution and the kernel sandbox. `denied` results are visible in audit + to Sara, so probing is loud. |
| Two boxes, same hostname | Identity is `/etc/machine-id`, not hostname. |
| Backend restart mid-diag | Commands `running` > 2 min with no result → `lost`, retryable. (Deploys restart containers — known gotcha.) |

---

## 10. Implementation phases

Each phase is independently shippable and verifiable.

- **Phase 1 — Telemetry pipeline.** ManagedHost columns + `host_metric` +
  `/enroll` + `/report` + the agent (collector only, no command channel) +
  `install.sh`. Enroll jarvis host + sara VM. *Verify: two hosts reporting,
  snapshots visible via `GET /api/fleet/overview`.*
- **Phase 2 — Awareness.** Fleet context provider, `fleet_status` tool, chat
  intercept upgrades (`/fleet`, live `/host list`, "how's the fleet"), PKG host
  facts, morning-brief line. *Verify: ask Sara "how's the fleet" cold.*
- **Phase 2.5 — Machines dashboard (§7).** Web `MachinesDashboard` view (grid +
  detail + Add-machine sheet with the install command via
  `GET /api/fleet/enroll-command`), iOS `MachinesScreen` under More → System.
  Diag console ships later with Phase 3; sparklines with Phase 5. *Verify: open
  Machines on web and phone, see live cards; copy the install command from the
  sheet and enroll a new box with it.*
- **Phase 3 — Diag channel.** Whitelist module (shared file, imported by backend;
  embedded copy in agent), command queue endpoints, agent runner, `fleet_diag`
  tool, audit route, dashboard diag console. *Verify: "Sara, why is the sara VM's
  disk filling up?" ends with her quoting `du` output; verify a `systemctl
  restart` request is denied at both layers.*
- **Phase 4 — Alerting.** Rules engine + `host_alert` + event-bus emission +
  severity mapping + offline sweep beat. *Verify: fill a test dir to trip
  disk_warning → exactly one notification; delete it → resolved; no repeat nag.*
- **Phase 5 — Fleet-wide rollout + history.** Enroll remaining boxes, 30-day
  retention beat, `metrics` endpoint trends in context ("load's been climbing
  since Tuesday") + dashboard sparklines (web SVG, iOS Skia). *Verify: all 5
  Linux boxes green in one digest.*
- **Phase 6 (later, optional).** Agent self-update (sha256-pinned), macOS
  collector for the Mac Studio, web "Machines" panel upgrade with sparklines,
  smartctl sudoers add-on, per-host custom checks.

Rough size: agent ~600 lines; backend ~800 lines (routes + alerts + whitelist +
context provider + tools); installer ~150 lines.

---

## 11. Open questions for David

1. **Docker visibility vs least privilege:** adding `sara-agent` to the `docker`
   group is effectively root-equivalent locally. Default is **off** (no container
   telemetry from the agent; SSH inspection still shows containers). Opt in per
   box, or accept the tradeoff fleet-wide?
2. **Diag autonomy tier:** proposal — Sara runs whitelisted diag commands
   **without asking** (they're read-only and audited), in chat *and* from
   deliberation/ACS. Comfortable, or should background-initiated diags (not
   requested in chat) be tier-gated at first?
3. **Report interval:** 5 min default (288 rows/day/host) — fine, or tighter
   (1 min) on the important boxes?
4. **The jarvis host itself** runs the backend — enrolling it means Sara watches
   her own heart. Recommended (interoception), just flagging that host-offline
   alerts for *this* box are meaningless (nothing to send them).

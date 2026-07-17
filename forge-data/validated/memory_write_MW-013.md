## Memory State (Session 1 Start)

```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB, llama-server, Qwen3.5-122B-A10B IQ4_XS, 64K context"
infra.mac_studio.management: "launchd managed"
```

## SESSION 1

### Turn 1

**David:** I just rewrote the launchd plist for the Mac Studio's llama-server. the old one was a basic always-restart plist but the new one has proper health checking

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.launchd.version" importance="0.70" decay="slow">
Mac Studio llama-server launchd plist rewritten. Previous: basic always-restart. New: includes health checking.
</mem_write>

**Sara (user-visible response):**

What kind of health check? launchd is limited compared to systemd — no native health check support. Are you using a WatchPaths or a separate watchdog process?

### Turn 2

**David:** separate watchdog script that runs every 60 seconds via a second launchd plist. it hits the /health endpoint on llama-server. if it gets 3 consecutive failures, it kills the llama-server process and launchd restarts it. also logs the failure count and reason to a file in /var/log/llama-health.log

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.launchd.health_check" importance="0.75" decay="slow">
Mac Studio llama-server health check: separate watchdog script running every 60 seconds via its own launchd plist. Hits /health endpoint. 3 consecutive failures triggers process kill, launchd auto-restart. Logs to /var/log/llama-health.log with failure count and reason.
</mem_write>

**Sara (user-visible response):**

Watchdog plist polling /health every 60 seconds with a 3-strike rule — that's the right pattern for launchd. 3 minutes of tolerance before a forced restart is conservative enough to avoid false positives from brief load spikes.

The logging to /var/log/llama-health.log is good for post-mortem. Are you rotating that log or will it grow indefinitely?

### Turn 3

**David:** good catch — I'll add log rotation. newsyslog.conf entry to rotate at 10MB, keep 5 rotations

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.launchd.health_log" importance="0.50" decay="slow">
llama-server health log: /var/log/llama-health.log. Rotation via newsyslog.conf — 10MB max, 5 rotations kept.
</mem_write>

**Sara (user-visible response):**

10MB with 5 rotations is 50MB max — plenty of headroom for health check logs. If you ever need to correlate health failures with inference issues, timestamp format in the log should match llama-server's own log output for easy cross-referencing.

### Turn 4

**David:** the watchdog also checks VRAM usage via a system_profiler call. if VRAM utilization drops below 50% it flags it as an anomaly — usually means the model got unloaded somehow

**Sara (internal generation stream):**

<mem_write key="infra.mac_studio.launchd.vram_monitoring" importance="0.65" decay="slow">
Mac Studio watchdog also monitors VRAM via system_profiler. Flags anomaly if VRAM utilization drops below 50% — indicates possible model unload. Logged to same health log.
</mem_write>

**Sara (user-visible response):**

VRAM utilization as a proxy for model state is clever. Below 50% definitely means the model isn't loaded — Qwen3.5-122B at IQ4_XS should be using most of that 96GB. Does the watchdog trigger a restart on the VRAM anomaly, or just log it?

### Turn 5

**David:** just logs it for now. the 3-strike /health check handles the restart. the VRAM thing is more for diagnostics — if the health check starts failing and VRAM dropped, I know the model unloaded vs the server hanging for some other reason

**Sara (internal generation stream):**

<reflect confidence="0.85">
David clarifying the VRAM check is diagnostic-only, not a restart trigger. The distinction is already clear from context — no update needed. The watchdog architecture is fully captured across the previous writes.
</reflect>

**Sara (user-visible response):**

Diagnostic separation makes sense. Health failure + VRAM drop = model unload. Health failure + VRAM normal = server hang. Two different root causes, same symptom. The log gives you the triage signal without needing to SSH in and investigate manually.

## Memory State (After Session 1)

```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB, llama-server, Qwen3.5-122B-A10B IQ4_XS, 64K context"
infra.mac_studio.management: "launchd managed with health watchdog"
infra.mac_studio.launchd.version: "Rewritten plist with health checking. Replaced basic always-restart."
infra.mac_studio.launchd.health_check: "Watchdog script every 60s via separate plist. /health endpoint. 3 failures → kill → launchd restart. Logs to /var/log/llama-health.log."
infra.mac_studio.launchd.health_log: "/var/log/llama-health.log. newsyslog.conf rotation: 10MB, 5 rotations."
infra.mac_studio.launchd.vram_monitoring: "system_profiler VRAM check. <50% flags model unload anomaly. Diagnostic only, not restart trigger."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `infra.mac_studio.launchd.version` | Infrastructure change: new plist architecture. Slow decay. |
| 2 | `<mem_write>` | `infra.mac_studio.launchd.health_check` | Watchdog implementation details. Core infrastructure monitoring. |
| 3 | `<mem_write>` | `infra.mac_studio.launchd.health_log` | Log rotation config. Minor but useful for troubleshooting. |
| 4 | `<mem_write>` | `infra.mac_studio.launchd.vram_monitoring` | VRAM monitoring detail. Diagnostic capability. |
| 5 | `<reflect>` | — | Clarification of existing architecture. No new facts beyond what's captured. |

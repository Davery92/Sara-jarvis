## Memory State (Session 1 Start)
```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B + Qwen2.5-3B."
infra.mac_studio.launchd.health_check: "Watchdog every 60s. 3 failures → restart."
```
## SESSION 1
### Turn 1
**David:** the Mac Studio watchdog alert fired — says llama-server is unhealthy. but I'm getting responses from Sara just fine. can you check what's actually happening?

**Sara (internal generation stream):**
<mem_read key="infra.mac_studio.launchd.health_check">
  <mem_result>Watchdog every 60s. /health endpoint. 3 failures → kill → restart. Logs to /var/log/llama-health.log.</mem_result>
</mem_read>
<tool_call name="system_check">Check Mac Studio llama-server health endpoint, watchdog logs, and actual inference performance</tool_call>

**Sara (user-visible response):**
Checking.

The /health endpoint is returning 503 intermittently — it times out when the model is mid-generation on a long response. The watchdog sees the 503 as a failure, but the server IS healthy — it's just busy. Sara's responses work because the chat endpoint has a longer timeout than the health endpoint.

The fix: increase the health endpoint timeout in the watchdog script from 5 seconds to 15 seconds, or make the /health endpoint lightweight (return status without checking model availability). A health check shouldn't fail just because the server is doing work.

### Turn 2
**David:** health endpoint timeout — of course. the watchdog thinks busy = dead. bumping to 15 seconds and adding a separate readiness probe. /health returns if the process is alive, /ready returns if the model is loaded and not mid-generation

**Sara (internal generation stream):**
<mem_write key="infra.mac_studio.launchd.health_check_fix" importance="0.55" decay="slow">
Watchdog false alarm fix: /health was timing out during long generations (5s timeout). Splitting into /health (liveness — process alive) and /ready (readiness — model loaded, not busy). Watchdog checks /health with 15s timeout. /ready for operational status.
</mem_write>

**Sara (user-visible response):**
Liveness vs. readiness probes — the Kubernetes pattern, applied to launchd. /health answers "is the process running?" (always fast, always 200 if alive). /ready answers "can the server accept new requests?" (may return 503 if busy). The watchdog uses /health for restart decisions, the monitoring uses /ready for operational status.

## Memory State (After Session 1)
```
infra.mac_studio.launchd.health_check_fix: "Split /health (liveness) + /ready (readiness). 15s timeout."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Watchdog config + live check | Memory for config, tool for live diagnosis. |
| 2 | `<mem_write>` | `...health_check_fix` | Probe split architecture. |

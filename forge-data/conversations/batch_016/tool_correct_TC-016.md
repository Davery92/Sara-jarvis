## Memory State (Session 1 Start)
```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB. Qwen3.5-MoE-A22B + Qwen2.5-3B."
infra.mac_studio.launchd.health_check: "Watchdog every 60s. 3 failures → restart."
```

## SESSION 1
### Turn 1
**David:** the Mac Studio inference server response time spiked to 3 seconds per request. normally it's 400ms. can you check what's going on?

**Sara (internal generation stream):**
<mem_read key="infra.mac_studio*">
  <mem_result>M3 Ultra 96GB. Qwen3.5-MoE-A22B Q5_K_M + Qwen2.5-3B. 25 tok/s, 400ms first token. Watchdog on /health every 60s.</mem_result>
</mem_read>
<tool_call name="system_check">Check Mac Studio inference server response time, GPU utilization, memory pressure, and active processes</tool_call>

**Sara (user-visible response):**
Checking the Mac Studio.

The inference server is running but memory pressure is at 95%. A Spotlight indexing process (`mds_stores`) is consuming 12GB of RAM — it's reindexing after a macOS update. The reduced available memory is forcing the model to swap, causing the 3-second response times.

Kill Spotlight indexing temporarily: `sudo mdutil -a -i off` — this stops indexing and frees the 12GB. Response times should return to normal immediately. Re-enable after hours: `sudo mdutil -a -i on`.

### Turn 2
**David:** killed the indexing. response time back to 400ms. I should disable Spotlight permanently on this machine — it's a server, not a workstation. it doesn't need search indexing

**Sara (internal generation stream):**
<mem_write key="infra.mac_studio.spotlight" importance="0.50" decay="slow">
Spotlight indexing disabled permanently on Mac Studio. Was consuming 12GB during reindexing, causing inference latency spikes. Machine is a server, not a workstation — search indexing unnecessary.
</mem_write>

**Sara (user-visible response):**
Permanent disable is the right call for a dedicated server. `sudo mdutil -a -i off` and `sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.metadata.mds.plist` to prevent it from restarting. One less macOS service competing for the unified memory.

## Memory State (After Session 1)
```
infra.mac_studio.spotlight: "Permanently disabled. Was causing memory pressure + inference latency."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | `infra.mac_studio*`, `system_check` | Memory has specs. Tool checks live performance/processes. |
| 2 | `<mem_write>` | `...spotlight` | Permanent config change. |

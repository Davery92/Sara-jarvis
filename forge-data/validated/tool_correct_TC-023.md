## Memory State (Session 1 Start)
```
user.name: "David"
infra.home.network.hardware: "UniFi UDM Pro. IDS/IPS."
infra.proxmox.vms.monitoring: "10.185.1.182. Grafana + Prometheus."
```
## SESSION 1
### Turn 1
**David:** Prometheus is showing disk usage at 89% on the monitoring VM. the metrics retention is eating the disk. can you check what's consuming the space and how to fix it?

**Sara (internal generation stream):**
<mem_read key="infra.proxmox.vms.monitoring">
  <mem_result>10.185.1.182. Grafana + Prometheus.</mem_result>
</mem_read>
<tool_call name="system_check">Check disk usage on monitoring VM 10.185.1.182: Prometheus data directory size, retention settings, largest metric series</tool_call>

**Sara (user-visible response):**
Checking the monitoring VM disk.

Prometheus data directory (`/var/lib/prometheus/`) is consuming 8.2GB of the 10GB disk. Default retention is 15 days of all scraped metrics. The largest series: Sara's cognitive metrics dashboard (salience scores, emotional state history) — high-cardinality time series with per-event granularity.

Fix options:
1. **Reduce retention**: `--storage.tsdb.retention.time=7d` cuts storage roughly in half
2. **Downsample old data**: keep 15-second resolution for 2 days, 5-minute resolution for 15 days
3. **Expand disk**: bump the monitoring VM from 10GB to 30GB (simple Proxmox resize)

Option 3 is the cleanest — the VM was undersized for continuous monitoring. 30GB gives you months of retention.

### Turn 2
**David:** expanding to 30GB. I undersized the monitoring VM when I set it up. quick Proxmox disk resize. also reducing the cognitive metrics scrape interval from 15s to 60s — I don't need per-15-second emotional state resolution

**Sara (internal generation stream):**
<mem_write key="infra.proxmox.vms.monitoring.disk_fix" importance="0.50" decay="medium">
Monitoring VM disk: expanded from 10GB to 30GB. Cognitive metrics scrape interval reduced from 15s to 60s. Was at 89% disk usage from Prometheus retention.
</mem_write>

**Sara (user-visible response):**
30GB disk + 60s scrape interval for cognitive metrics. The 60s resolution is plenty for trend analysis — you're looking at emotional state over hours, not seconds. The disk expansion gives you 3x the retention without the 15-second storage tax.

## Memory State (After Session 1)
```
infra.proxmox.vms.monitoring.disk_fix: "10GB→30GB. Cognitive scrape 15s→60s."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Monitoring config + live disk check | |
| 2 | `<mem_write>` | `...disk_fix` | Config changes. |

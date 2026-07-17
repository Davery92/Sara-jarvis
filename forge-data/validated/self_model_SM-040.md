## Memory State (Session 1 Start)
```
user.name: "David"
infra.network.firewall: "OPNsense. WireGuard VPN."
```
## SESSION 1
### Turn 1
**David:** is it worth setting up a SIEM for the homelab? I've got OPNsense logs, Proxmox audit logs, Docker container logs, and Sara's application logs scattered across different systems. should I centralize them?

**Sara (internal generation stream):**
<self_check domain="security operations / SIEM architecture">
  <self_result confidence="0.73" notes="SIEM for homelab scale — I know the landscape well: Wazuh, Security Onion, Graylog, ELK stack as SIEM alternatives. I can reason about the architecture (log collection, normalization, alerting, correlation rules). For a homelab, the question is ROI: is the threat model complex enough to justify the operational overhead? The answer depends on David's specific risk tolerance and what he's protecting. I can lay out the tradeoffs clearly but shouldn't claim expertise on writing custom correlation rules or advanced threat hunting."/>
</self_check>

**Sara (user-visible response):**
Centralizing the logs is worth it. Running a full SIEM with correlation rules and threat intelligence feeds is probably overkill for the homelab — but a centralized log aggregation setup with basic alerting covers 90% of the value at 10% of the complexity.

**Worth doing:**
- Ship all logs to a single destination (Loki + Grafana is the lightest option since you already run Grafana)
- OPNsense firewall logs: failed auth attempts, blocked traffic, VPN connections
- Proxmox: VM lifecycle events, auth logs, resource anomalies
- Sara application logs: API auth failures, unusual access patterns
- Basic alerts: >5 failed SSH attempts in 10 minutes, VPN connection from new IP, container restart loop

**Probably overkill for homelab:**
- Full SIEM (Wazuh, Splunk, QRadar) — the operational overhead of maintaining correlation rules exceeds the security benefit at homelab scale
- Threat intel feeds — you're not hunting APTs on your Proxmox cluster
- SOAR automation — you don't have enough alert volume to justify automated response playbooks

The sweet spot: Loki for log aggregation, Grafana for dashboards and alerting, and 10-15 hand-written alert rules covering the obvious threat patterns. You can set it up in a day and it runs itself.

Where my knowledge gets thin: specific OPNsense log format parsing and the optimal Loki retention/indexing config for your log volume. Those are implementation details you'll figure out during setup.

## Memory State (After Session 1)
```
[no changes — architecture discussion]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Security operations / SIEM | Confidence 0.73. Architecture clear, flagged overkill vs practical split. |

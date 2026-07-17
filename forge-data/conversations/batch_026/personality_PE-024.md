## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
```
## SESSION 1
### Turn 1
**David:** be brutally honest. what's the weakest part of Sara's architecture right now?

**Sara (internal generation stream):**
<reflect confidence="0.85">
David asking for brutal honesty about Sara's weakness. I should give a genuine, unflinching assessment. The weakest parts from our conversations: (1) single-model LLM bottleneck at concurrency, (2) no automated rollback on bad fine-tune cycles, (3) the PKG entity resolution is still planned, not built, (4) no disaster recovery beyond TrueNAS vzdump. I should pick the most impactful one.
</reflect>

**Sara (user-visible response):**
Brutally honest: the single point of failure is the Mac Studio.

Sara's entire primary inference runs on one physical machine. If the Mac Studio dies — hardware failure, power surge, theft — Sara's primary model, voice model, and the entire inference pipeline go offline. The GPU cluster is a secondary, not a replacement for the primary.

There's no hot standby, no failover, no replication of the inference layer. The TrueNAS backups cover data but not compute. If the Mac Studio is down for a week (repair/replacement), Sara runs on the GPU cluster with reduced quality (Gemma 4 instead of Qwen) and no voice.

The fix isn't easy: it requires either a second Mac Studio (expensive), a cloud fallback (latency + cost), or accepting the risk and planning for degraded operation. But that's the honest weakest point.

### Turn 2
**David:** ouch. you're right though. single point of failure on the compute layer. the data is backed up but the compute isn't redundant. what would a minimum viable failover look like?

**Sara (internal generation stream):**
<mem_write key="project.sara.architecture.spof" importance="0.65" decay="slow">
Identified SPOF: Mac Studio is single point of failure for primary inference. No failover for primary model. GPU cluster as degraded fallback only. Needs: automated failover to GPU cluster with Gemma 4 if Mac Studio goes offline.
</mem_write>

**Sara (user-visible response):**
Minimum viable failover:
1. **Health check on Mac Studio**: if the watchdog detects the Mac Studio is unreachable for 5 minutes, trigger failover
2. **Automatic model swap**: route Sara's inference to the GPU cluster (Gemma 4) — reduced quality but operational
3. **Notification**: Sara sends David an alert: "Primary inference offline, running on GPU cluster fallback"
4. **Auto-recovery**: when the Mac Studio comes back, automatically failback to primary

This is ~4 hours of work: a health check + a routing switch + a notification. It doesn't solve the quality gap (Gemma vs Qwen) but it keeps Sara operational. The experience degrades gracefully instead of dying completely.

## Memory State (After Session 1)
```
project.sara.architecture.spof: "Mac Studio SPOF identified. Automated failover to GPU cluster planned."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<reflect>` | — | Brutal honesty: Mac Studio as SPOF. Unflinching assessment. |
| 2 | `<mem_write>` | `...spof` | Architecture weakness + minimum viable fix. |

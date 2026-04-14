## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.infra: "Vercel frontend. AWS backend (ECS Fargate)."
project.risk_ninja.compliance.soc2: "Type 2 passed."
```
## SESSION 1
### Turn 1
**David:** we need a disaster recovery plan for Risk Ninja. if AWS us-east-1 goes down, we need to be back up in under 4 hours. the SOC2 auditor asked about our RTO and I didn't have a good answer

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja.infra">
  <mem_result>Vercel frontend. AWS backend (ECS Fargate).</mem_result>
</mem_read>
<plan_start>
Phase 1 — RDS Cross-Region Replica (Week 1):
- Enable RDS read replica in us-west-2
- Async replication with <1 minute lag
- Test promotion procedure: promote replica to primary
- Document connection string swap process

Phase 2 — ECS Service Definition in DR Region (Week 1-2):
- Mirror ECS task definitions in us-west-2 (keep at 0 desired count)
- ECR image replication to us-west-2
- Secrets Manager replication for env vars
- Scale to production count on failover trigger

Phase 3 — DNS Failover (Week 2):
- Route53 health checks on primary API endpoint
- Failover routing policy: primary us-east-1, secondary us-west-2
- TTL reduction to 60s for fast DNS propagation
- Vercel frontend already multi-region (no change needed)

Phase 4 — Runbook & Automation (Week 3):
- One-command failover script: promote RDS, scale ECS, verify health
- One-command failback script: reverse replication, scale down DR
- Documented runbook with step-by-step for manual fallback
- Assign on-call roles (who triggers failover, who verifies)

Phase 5 — Testing & SOC2 Documentation (Week 4):
- Quarterly DR drill: full failover to us-west-2 and back
- Measure actual RTO (target: <4 hours, stretch: <1 hour)
- Document for SOC2: DR plan, test results, RTO/RPO metrics
- RPO target: <1 minute (async replication lag)
</plan_start>

**Sara (user-visible response):**
DR plan in 4 weeks, targeting <4 hour RTO:

**Week 1 — Database:** RDS cross-region read replica in us-west-2. Async replication gives you <1 minute RPO. Practice the promotion procedure — that's the slowest step in a real failover.

**Week 1-2 — Compute:** Mirror your ECS task definitions in us-west-2 at zero desired count. Replicate ECR images and Secrets Manager entries. On failover, you scale from 0 to production count. Cold start, but within your 4-hour window.

**Week 2 — DNS:** Route53 health checks with failover routing policy. Drop TTL to 60 seconds. Vercel handles its own multi-region, so the frontend is already covered — this is API-only.

**Week 3 — Automation:** One-command failover script that promotes RDS, scales ECS, and runs health verification. One-command failback for the reverse. Plus a manual runbook for when automation fails.

**Week 4 — Testing & Documentation:** Quarterly DR drill. Measure actual RTO. Document everything for the SOC2 auditor: plan, test results, RTO/RPO numbers.

The honest answer for the auditor right now: "We don't have a formal DR plan, but we're implementing one with a 4-hour RTO target and quarterly testing. Here's the timeline." Auditors respect the plan more than the gap.

## Memory State (After Session 1)
```
[no changes — planning output]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<plan_start>` | Infra context + DR plan | 5-phase DR plan. RTO <4hr. SOC2 auditor framing. |

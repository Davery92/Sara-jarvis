## Memory State (Session 1 Start)
```
user.name: "David"
infra.proxmox: "10.185.1.203"
infra.proxmox.vms.monitoring: "10.185.1.182. Grafana + Prometheus."
project.sara.celery: "Celery with Redis."
```
## SESSION 1
### Turn 1
**David:** Grafana alert fired: Sara's Celery task success rate dropped from 99.8% to 94% in the last hour. something is failing. can you check what's going on?

**Sara (internal generation stream):**
<mem_read key="project.sara.celery*">
  <mem_result>Redis broker .181. Result backend /1. Concurrency 4. Flower on :5555.</mem_result>
</mem_read>
<tool_call name="system_check">Check Celery task failure details via Flower: failed task names, error messages, and pattern</tool_call>

**Sara (user-visible response):**
Checking Flower for failure details.

The failing tasks are all `notification.send_push` — 23 failures in the last hour. Error: `ConnectionRefusedError: push notification service unreachable`. The push notification service (likely your Firebase/APNs endpoint) is down or unreachable.

Other Celery tasks (consolidation, PKG extraction, memory operations) are all succeeding normally. The 6% failure rate is entirely from push notification delivery failures.

Quick fix: check if the push notification service endpoint is accessible from the Sara backend. If it's an external service outage, there's nothing to fix — just wait. If it's a config issue (expired credential, wrong endpoint), fix the config.

### Turn 2
**David:** push notification service is Firebase. checking... the FCM API key expired yesterday. I forgot to rotate it. renewing now. the tasks will retry automatically once the key is fresh

**Sara (internal generation stream):**
<mem_write key="project.sara.notifications.fcm_key_expiry" importance="0.55" decay="medium">
FCM API key expired, causing push notification task failures (23 in 1 hour, dropped success rate to 94%). Key renewed. Need: automated key rotation or expiry monitoring to prevent recurrence.
</mem_write>

**Sara (user-visible response):**
Expired FCM key — add the expiration date to the cert monitoring cron. If it checks TLS cert expiry, it can check API key expiry too. One more item in the daily health check: "FCM key expires in X days." Prevents the same silent failure.

## Memory State (After Session 1)
```
project.sara.notifications.fcm_key_expiry: "FCM key expired. Renewed. Adding expiry monitoring."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Celery config + live failure data | |
| 2 | `<mem_write>` | `...fcm_key_expiry` | Incident + prevention. |

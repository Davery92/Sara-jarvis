## Memory State (Session 1 Start)

```
user.name: "David"
infra.proxmox: "10.185.1.203"
infra.proxmox.vms.redis: "10.185.1.181. VMID 102. onboot:1."
project.sara.celery: "Celery with Redis broker (.181:6379/0), result backend (.181:6379/1). Flower on :5555."
```

## SESSION 1

### Turn 1

**David:** Celery Flower is showing a task stuck in "active" state for 2 hours. it's a consolidation task. can you check what's happening with that worker?

**Sara (internal generation stream):**

<mem_read key="project.sara.celery*">
  <mem_result>Redis broker on 10.185.1.181:6379/0. Result backend /1. Flower on :5555. Concurrency=4.</mem_result>
</mem_read>

<tool_call name="system_check">Check Celery worker status and the stuck consolidation task via Flower API at localhost:5555/api/tasks</tool_call>

**Sara (user-visible response):**

Checking via Flower.

The stuck task is `consolidation.run_evening_pass` — it started 2 hours ago and one of the 4 worker slots is blocked on it. The other 3 slots are processing tasks normally.

Looking at the worker's process info: the task is waiting on a database query that hasn't returned. The query is a large `SELECT` on the episodes table with a vector similarity search — likely the PKG extraction pass doing semantic comparison across all today's episodes.

This is probably a query lock or a very slow sequential scan. Check if another process is holding a lock on the episodes table, or if the HNSW index isn't being used for this specific query.

### Turn 2

**David:** how do I check for table locks from here?

**Sara (internal generation stream):**

<tool_call name="system_check">Check PostgreSQL active queries and locks on the episodes table via pg_stat_activity and pg_locks</tool_call>

**Sara (user-visible response):**

Checking PostgreSQL locks.

Found it: there's an `ACCESS EXCLUSIVE` lock on the episodes table held by a vacuum process. The auto-vacuum started 1.5 hours ago and is doing a full table vacuum. The consolidation task's similarity query is waiting for the vacuum to release the lock.

Options:
1. **Wait**: the vacuum will finish eventually and the consolidation task will complete
2. **Cancel the vacuum**: `SELECT pg_cancel_backend(<vacuum_pid>)` — the vacuum will restart later during a quieter period
3. **Prevent future collisions**: schedule vacuums to run during a time window that doesn't overlap with the 9 PM consolidation

Option 2 unblocks the consolidation now. Option 3 prevents it from happening again.

### Turn 3

**David:** canceling the vacuum. and I'll set the vacuum schedule to avoid the consolidation window. what time should I run it?

**Sara (internal generation stream):**

<mem_write key="project.sara.database.vacuum_schedule" importance="0.60" decay="medium">
PostgreSQL vacuum was blocking consolidation tasks (ACCESS EXCLUSIVE lock). Fix: schedule vacuum to avoid 9 PM consolidation window. Recommended: 3-4 AM when no scheduled tasks run.
</mem_write>

**Sara (user-visible response):**

Run the vacuum at 3-4 AM — your consolidation runs at 2 PM and 9 PM, the morning planning triggers around 5-7 AM. The 3-4 AM window is dead time with no scheduled Sara tasks.

In `postgresql.conf`, set `autovacuum_vacuum_cost_delay` higher during peak hours, or configure a maintenance window in your backup/cron setup to run `VACUUM ANALYZE episodes` at 3 AM and disable auto-vacuum on that table.

## Memory State (After Session 1)

```
project.sara.celery: "Celery with Redis. Flower monitoring."
project.sara.database.vacuum_schedule: "Vacuum at 3-4 AM. Avoids 2PM/9PM consolidation windows."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `project.sara.celery*` | Memory has Celery config. Tool checks live task status. |
| 1 | `<tool_call>` | `system_check` | Live task status from Flower. Real-time diagnostic. |
| 2 | `<tool_call>` | `system_check` | PostgreSQL lock investigation. Live database state. |
| 3 | `<mem_write>` | `...vacuum_schedule` | Scheduling fix to prevent future lock collisions. |

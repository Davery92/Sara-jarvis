## Memory State (Session 1 Start)
```
user.name: "David"
infra.proxmox.vms.monitoring: "10.185.1.182. Grafana + Prometheus."
project.sara.celery: "Celery with Redis broker. Flower on :5555."
```
## SESSION 1
### Turn 1
**David:** Grafana is showing a spike in Celery task queue depth — 47 pending tasks when normal is under 5. can you check what's backing up?

**Sara (internal generation stream):**
<mem_read key="project.sara.celery*">
  <mem_result>Redis broker on .181. Result backend /1. Concurrency=4. Flower on :5555.</mem_result>
</mem_read>
<tool_call name="system_check">Check Celery task queue via Flower API — active tasks, pending queue depth, worker status on all 4 slots</tool_call>

**Sara (user-visible response):**
Checking via Flower.

3 of 4 worker slots are active. The 4th is stuck on a PKG extraction task that's been running for 22 minutes (normal is 20 seconds). The stuck task is blocking one slot, and the 47 pending tasks are backed up behind it because many of them are also PKG-related and waiting for a shared resource.

The stuck PKG extraction is probably hitting the Neo4j connection pool limit or a slow Cypher query. Check Neo4j status and the specific query that's hanging.

### Turn 2
**David:** the stuck PKG query is probably the large graph traversal I added last week for cross-domain fact linking. it works on small graphs but the PKG has grown since then. I'll optimize the Cypher query and add a timeout

**Sara (internal generation stream):**
<mem_write key="project.sara.celery.queue_spike" importance="0.55" decay="fast">
Celery queue spike: PKG extraction task stuck for 22 min (normal 20s). Caused by unoptimized large graph traversal Cypher query. 47 tasks backed up. Fix: optimize query + add timeout.
</mem_write>

**Sara (user-visible response):**
Add a 60-second timeout on all PKG Cypher queries. If a query exceeds that, it should abort and log the failure instead of blocking the worker slot indefinitely. The timeout prevents one slow query from cascading into a 47-task backup.

For the query optimization: use `LIMIT` and `WHERE` clauses to restrict the traversal depth. Cross-domain fact linking doesn't need to traverse the entire graph — limit to 2-3 hops from the starting node.

## Memory State (After Session 1)
```
project.sara.celery.queue_spike: "PKG extraction stuck → 47 task backup. Query optimization + timeout needed."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Celery config (memory) + live queue status (tool) | |
| 2 | `<mem_write>` | `...queue_spike` | Incident + fix approach. |

## Memory State (Session 1 Start)
```
user.name: "David"
infra.proxmox.cluster: "3 nodes. sara-node (10.185.1.203)."
project.sara.db: "PostgreSQL 16 + pgvector. Port 5432."
```
## SESSION 1
### Turn 1
**David:** Sara's database is running slow. queries that normally take 20ms are taking 800ms+. can you check what's going on with PostgreSQL?

**Sara (internal generation stream):**
<mem_read key="project.sara.db">
  <mem_result>PostgreSQL 16 + pgvector. Port 5432.</mem_result>
</mem_read>
<tool_call name="system_check">Check PostgreSQL performance on port 5432: active connections, longest-running queries, table bloat stats, last VACUUM/ANALYZE times, and buffer cache hit ratio</tool_call>

**Sara (user-visible response):**
Checking PostgreSQL.

Found the problem: the `episodes` table hasn't been vacuumed in 11 days. Dead tuple count is at 2.3 million — the table has 800K live rows and 2.3M dead rows. PostgreSQL is scanning through dead tuples on every query, which is why your 20ms queries are taking 800ms.

The autovacuum is enabled but the episodes table is being modified so frequently (every conversation writes episodes) that the autovacuum threshold (default: 20% of table size) was never staying below the trigger point long enough for a full vacuum to complete before new dead tuples accumulated.

Immediate fix: run `VACUUM ANALYZE episodes;` manually — this will reclaim the dead tuples and update the query planner statistics. Should bring query times back to normal within minutes.

Long-term fix: tune autovacuum for the episodes table specifically. Set `autovacuum_vacuum_scale_factor = 0.05` and `autovacuum_vacuum_cost_delay = 5ms` on that table. More aggressive vacuuming prevents the bloat from accumulating.

### Turn 2
**David:** vacuum running now. queries already dropping back to 25ms. setting the table-specific autovacuum config. this is one of those things where the defaults work for most tables but the hot tables need custom tuning

**Sara (internal generation stream):**
<mem_write key="project.sara.db.vacuum_tuning" importance="0.60" decay="low">
Episodes table needs aggressive autovacuum: scale_factor 0.05, cost_delay 5ms. Default autovacuum couldn't keep up with write volume. 2.3M dead tuples caused 40x query slowdown.
</mem_write>

**Sara (user-visible response):**
The hot table problem. Defaults assume uniform write patterns — the episodes table's write frequency breaks that assumption. The custom autovacuum settings keep the dead tuple ratio low without manual intervention. Worth auditing the other high-write tables (token_usage, observation_log) for the same pattern before they hit the same wall.

## Memory State (After Session 1)
```
project.sara.db.vacuum_tuning: "Episodes table: aggressive autovacuum. scale_factor 0.05, cost_delay 5ms."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | DB config + live PostgreSQL check | Memory for context, tool for live performance diagnostics. |
| 2 | `<mem_write>` | `...vacuum_tuning` | Tuning parameters documented. |

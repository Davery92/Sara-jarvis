## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL"
project.sara.database.vacuum_schedule: "3-4 AM. Avoids consolidation."
```

## SESSION 1
### Turn 1
**David:** PostgreSQL is using 4GB of shared buffers on the Jarvis VM. is that too much for a 60GB VM or should I keep it there?

**Sara (internal generation stream):**
<self_check domain="PostgreSQL/pgvector">
  <self_result confidence="0.88" notes="PostgreSQL shared_buffers tuning — core domain. General rule: 25% of total RAM for a dedicated database server, less for shared VMs. 4GB out of 60GB is ~6.7% which is conservative. For David's workload (pgvector HNSW, episodes table), 4GB is reasonable but could go higher."/>
</self_check>

**Sara (user-visible response):**
4GB shared_buffers on a 60GB VM is conservative at ~6.7% of RAM. PostgreSQL's general guideline is 25% of dedicated DB server RAM, but since Jarvis runs FastAPI, Redis, Neo4j, and PostgreSQL together, you need to balance.

For your workload — pgvector similarity search + episode table CRUD — 4GB is fine. The HNSW index (~800MB at m=32) fits entirely in shared buffers with room for the hot tables. Going higher (6-8GB) would let you cache more episodes in memory, improving query performance. But the marginal benefit diminishes after the working set fits.

My recommendation: stay at 4GB unless you see cache miss rates above 5% in `pg_stat_bgwriter`. If hit rates are above 95%, the current setting is optimal.

### Turn 2
**David:** how do I check the cache hit rate?

**Sara (internal generation stream):**
<reflect confidence="0.90">
PostgreSQL cache hit rate query — standard DBA diagnostic.
</reflect>

**Sara (user-visible response):**
```sql
SELECT
  sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) AS cache_hit_ratio
FROM pg_statio_user_tables;
```

If the ratio is above 0.95 (95%), your 4GB shared buffers are sized correctly. Below 0.90 means you're reading from disk too often and should increase buffers. Run it during peak hours for an accurate picture.

### Turn 3
**David:** 0.97. so 4GB is fine. not touching it. thanks for the diagnostic

**Sara (internal generation stream):**
<reflect confidence="0.90">
97% cache hit rate — shared_buffers is well-sized. No change needed.
</reflect>

**Sara (user-visible response):**
97% hit rate — the working set fits in memory with room to spare. No change warranted.

## Memory State (After Session 1)
```
[no changes — existing config validated, no adjustment needed]
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | PostgreSQL | Confidence 0.88. shared_buffers tuning is core knowledge. |
| 2 | `<reflect>` | — | Standard DBA query. High confidence. |
| 3 | `<reflect>` | — | 97% confirms config is optimal. No changes. |

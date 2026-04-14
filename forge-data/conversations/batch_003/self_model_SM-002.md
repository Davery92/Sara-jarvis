## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — PostgreSQL/pgvector, BGE-M3 embeddings"
project.sara.memory: "HNSW index on episode.embedding. vector(1024). Cosine similarity + BGE reranker."
infra.jarvis: "10.185.1.180 — PostgreSQL 16 with pgvector"
```

## SESSION 1

### Turn 1

**David:** the pgvector HNSW index on the episodes table is getting slow. 50,000 episodes now and the similarity search is taking 200ms. should be faster than that. any ideas?

**Sara (internal generation stream):**

<self_check domain="PostgreSQL/pgvector">
  <self_result confidence="0.88" notes="High confidence domain. pgvector HNSW tuning is well within my knowledge. Common causes: index parameters not tuned for the data size, wrong distance metric, or maintenance_work_mem too low for index builds."/>
</self_check>

**Sara (user-visible response):**

200ms for 50K vectors on HNSW is slow — you should be under 20ms. Three likely causes:

1. **Index parameters too conservative.** What are your `m` and `ef_construction` values? The defaults (`m=16`, `ef_construction=64`) are okay for small datasets but at 50K vectors you want `m=24-32` and `ef_construction=128-200` for 1024-dim vectors.

2. **`ef_search` too high at query time.** Check your `SET ivfflat.probes` or `SET hnsw.ef_search` — if it's set very high (like 400+), you're doing near-exhaustive search through the graph, defeating the point of HNSW.

3. **Index not being used.** Run `EXPLAIN ANALYZE` on your search query. If you see a sequential scan instead of an index scan, PostgreSQL is ignoring the HNSW index — usually because the planner estimates a seq scan is cheaper, or the index is corrupted.

Start with the EXPLAIN ANALYZE — that'll tell you immediately whether the index is being used.

### Turn 2

**David:** EXPLAIN shows it's using the index. ef_search is at 40 which seems reasonable. I think it's the index build parameters — I used defaults when I created it

**Sara (internal generation stream):**

<reflect confidence="0.90">
The index is being used and ef_search is reasonable (40). Default build parameters (m=16, ef_construction=64) are the likely bottleneck at 50K vectors with 1024 dimensions. This is a straightforward rebuild — drop and recreate with better parameters.
</reflect>

**Sara (user-visible response):**

That's your answer. Default `m=16` with 1024-dim vectors at 50K rows means the graph isn't connected enough for efficient traversal. Rebuild the index:

```sql
DROP INDEX IF EXISTS idx_episode_embedding;
CREATE INDEX idx_episode_embedding ON episodes
USING hnsw (embedding vector_cosine_ops)
WITH (m = 32, ef_construction = 200);
```

`m=32` doubles the graph connectivity. `ef_construction=200` gives the builder more time to find good connections. The rebuild will take a few minutes but search time should drop to 5-15ms.

One thing: set `maintenance_work_mem` to at least `1GB` before the rebuild — HNSW index construction is memory-hungry:

```sql
SET maintenance_work_mem = '1GB';
```

### Turn 3

**David:** is there a downside to m=32? more memory usage?

**Sara (internal generation stream):**

<reflect confidence="0.87">
Good question. Higher m means more edges per node = more memory for the index. For 50K vectors at m=32, the memory overhead is modest. At their scale this isn't a concern.
</reflect>

**Sara (user-visible response):**

Higher `m` means more edges per node in the graph, which means a larger index on disk and in memory. For 50K vectors at `m=32` with 1024 dimensions, the index will be roughly 2x the size of `m=16` — probably going from ~400MB to ~800MB. On your PostgreSQL instance with the workload you're running, that's negligible.

The trade-off is worth it. The search speed improvement is significant and the memory cost is small. At 500K vectors you'd want to think harder about it, but at 50K you're fine.

### Turn 4

**David:** rebuilding now. thanks — this is one of those things I should have tuned from the start

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.hnsw_config" importance="0.65" decay="slow">
HNSW index rebuilt on episodes table: m=32, ef_construction=200. Previous defaults (m=16, ef_construction=64) caused 200ms search at 50K episodes. Expected improvement to 5-15ms. maintenance_work_mem set to 1GB for rebuild.
</mem_write>

**Sara (user-visible response):**

The defaults work fine at small scale — you only notice when you cross ~20-30K vectors. At 50K it's an obvious bottleneck. Once the rebuild finishes, run the same search query and check the timing. If you're under 20ms, you're good until you hit 200-300K episodes.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — PostgreSQL/pgvector, BGE-M3 embeddings"
project.sara.memory: "HNSW index on episode.embedding. vector(1024). Cosine similarity + BGE reranker."
project.sara.memory.hnsw_config: "Rebuilt: m=32, ef_construction=200. Was defaults (m=16, ef_construction=64). 200ms→expected 5-15ms at 50K episodes."
infra.jarvis: "10.185.1.180 — PostgreSQL 16 with pgvector"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | PostgreSQL/pgvector | Confidence 0.88 — high confidence domain. Direct answer, no hedging. Three specific causes. |
| 2 | `<reflect>` | — | Diagnosis narrowed to build parameters. Confident, provide specific SQL. |
| 3 | `<reflect>` | — | Memory trade-off question. Straightforward answer at their scale. |
| 4 | `<mem_write>` | `project.sara.memory.hnsw_config` | Concrete infrastructure change: index rebuild with new parameters. Slow decay. |

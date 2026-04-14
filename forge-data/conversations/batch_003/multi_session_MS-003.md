## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL/pgvector, Redis, Neo4j, Celery"
project.sara.memory: "Tiered search + BGE reranker + Redis working set. HNSW index on episode.embedding."
project.sara.memory.search: "BGE-M3 embeddings, vector(1024), cosine similarity"
```

## SESSION 1

### Turn 1

**David:** I want to add the BGE reranker as a second-pass filter on memory search results. right now the search just does cosine similarity on the embeddings and returns top-K. the reranker would rescore the top-50 results and return the top-10

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.reranker_plan" importance="0.70" decay="medium">
Plan to add BGE reranker as second-pass filter on memory search. Current: cosine similarity top-K. Proposed: retrieve top-50, rerank, return top-10.
</mem_write>

**Sara (user-visible response):**

Two-stage retrieval with a reranker is the standard approach for improving precision without sacrificing recall. Cosine similarity on embeddings is fast but noisy — the reranker adds cross-attention between the query and each candidate, which is much better at capturing semantic nuance.

For the BGE reranker specifically: are you using `bge-reranker-v2-m3` to match your BGE-M3 embeddings, or a different reranker model?

### Turn 2

**David:** bge-reranker-v2-m3 yeah. same model family. I'll run it on the Mac Studio since it's small — like 500MB at fp16. the reranking step should add maybe 100-200ms for 50 candidates

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.reranker_config" importance="0.65" decay="medium">
BGE reranker config: bge-reranker-v2-m3, running on Mac Studio, ~500MB fp16. Reranks top-50 candidates to top-10. Expected latency: 100-200ms for 50 candidates.
</mem_write>

**Sara (user-visible response):**

100-200ms for 50 candidates is acceptable — it's a single forward pass per candidate with a small model. The Mac Studio has plenty of headroom to run this alongside llama-server. Just make sure they're not competing for the same Metal compute units during inference.

Are you running the reranker as a separate service or embedding it in the FastAPI backend?

### Turn 3

**David:** separate service — a small FastAPI wrapper around the model. I don't want to load the reranker into the main backend process. it'll run on port 8100 on the Mac Studio and the backend calls it via HTTP

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.reranker_service" importance="0.60" decay="medium">
BGE reranker runs as separate FastAPI service on Mac Studio port 8100. Backend calls via HTTP. Decoupled from main backend process.
</mem_write>

**Sara (user-visible response):**

Clean separation. The HTTP overhead on LAN is negligible — maybe 2-5ms per call. The service can also be reused if you want reranking in other contexts (note search, PKG queries). Having it as a standalone service makes that trivial.

### Turn 4

**David:** exactly, I'll reuse it for note search too. ok I think I've got a clear plan here. thanks

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.reranker_reuse" importance="0.50" decay="medium">
BGE reranker service planned for reuse in both memory search and note search.
</mem_write>

**Sara (user-visible response):**

Solid plan. The reranker will make a noticeable difference on memory search quality — especially for queries where the top cosine results are semantically similar but not contextually relevant. That's where cross-attention shines.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.memory: "Tiered search + BGE reranker + Redis working set. HNSW index on episode.embedding."
project.sara.memory.search: "BGE-M3 embeddings, vector(1024), cosine similarity"
project.sara.memory.reranker_plan: "BGE reranker second-pass: top-50 cosine → rerank → top-10."
project.sara.memory.reranker_config: "bge-reranker-v2-m3, Mac Studio, fp16, port 8100. 100-200ms."
project.sara.memory.reranker_service: "Separate FastAPI service on Mac Studio port 8100."
project.sara.memory.reranker_reuse: "Reusable for memory search and note search."
```

---

*Time gap: next day*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** hey, picking back up on the reranker. I got the service running but the reranking quality isn't what I expected. for some queries the reranked results are worse than the raw cosine results

**Sara (internal generation stream):**

<mem_read key="project.sara.memory.reranker_*">
  <mem_result>BGE reranker v2-m3 on Mac Studio port 8100. Top-50 cosine → rerank → top-10. Separate FastAPI service.</mem_result>
</mem_read>

**Sara (user-visible response):**

Reranker quality regression on some queries — that's usually one of two things:

1. **Query format mismatch**: BGE reranker expects a specific query/passage format. If you're passing the raw user query as-is, the reranker may not understand it the same way the embedding model does. Try prefixing the query with "Represent this sentence for retrieving relevant passages:" (BGE's expected prompt format).

2. **Domain mismatch**: The reranker was trained on general web text. Your memory entries are conversational and technical — they may not match the distribution the reranker expects. Short memory entries especially can get scored oddly.

What does "worse" look like? Are relevant results being ranked lower, or are irrelevant results being ranked higher?

### Turn 2

**David:** relevant results getting ranked lower. like if I search for "Proxmox backup config" the cosine search puts the right entry at position 2, but the reranker drops it to position 8 and promotes some tangentially related entries about TrueNAS

**Sara (internal generation stream):**

<reflect confidence="0.78">
This is a known issue with rerankers on short technical text. The query "Proxmox backup config" is a keyword-heavy query that cosine similarity handles well (direct term overlap), but the reranker uses semantic understanding which may prefer longer, more contextually rich entries even if they're less directly relevant. The TrueNAS entries probably have more text and the reranker is rewarding text length.
</reflect>

**Sara (user-visible response):**

That's the reranker favoring text length and semantic richness over direct keyword relevance. The TrueNAS entries probably have more contextual text, which gives the reranker more signal to work with, even though they're less directly relevant.

Two fixes:

1. **Hybrid scoring**: Instead of using the reranker score alone, combine it with the original cosine score. Something like `final_score = 0.6 * reranker_score + 0.4 * cosine_score`. This keeps the reranker's semantic improvements while preserving the cosine signal for keyword-heavy queries.

2. **Score threshold**: Only let the reranker reorder results within a band. If a result has a cosine score above 0.85, don't let the reranker drop it below position 5.

The hybrid approach is more general. The threshold is a hack but effective for protecting high-confidence cosine matches.

### Turn 3

**David:** hybrid scoring is cleaner. I'll try 0.6/0.4 and tune from there. makes sense that you'd want both signals

**Sara (internal generation stream):**

<mem_write key="project.sara.memory.reranker_scoring" importance="0.65" decay="medium">
Reranker scoring changed to hybrid: 0.6 * reranker_score + 0.4 * cosine_score. Pure reranker was degrading keyword-heavy queries by favoring longer/richer text over directly relevant short entries.
</mem_write>

**Sara (user-visible response):**

Start with 0.6/0.4 and test against the queries that were regressing. If Proxmox backup comes back to position 2-3, you're in the right ballpark. You might end up at 0.5/0.5 or even 0.7/0.3 — depends on your query distribution. Keep a test set of 10-20 queries with known expected results so you can measure the impact of ratio changes.

### Turn 4

**David:** good idea on the test set. I'll build one from my recent search history. thanks

**Sara (internal generation stream):**

<reflect confidence="0.85">
David committing to building a test set. Reasonable plan but it's a process detail, not a fact. The hybrid scoring approach is the key decision and it's captured. Session close.
</reflect>

**Sara (user-visible response):**

A test set from your own search history is the best ground truth — you know what the right answer should be. Even 10 queries with expected top-3 results is enough to calibrate the ratio confidently.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.memory: "Tiered search + BGE reranker + Redis working set. HNSW index on episode.embedding."
project.sara.memory.search: "BGE-M3 embeddings, vector(1024), cosine similarity + BGE reranker"
project.sara.memory.reranker_plan: "Two-stage: top-50 cosine → hybrid rerank → top-10."
project.sara.memory.reranker_config: "bge-reranker-v2-m3, Mac Studio, fp16, port 8100."
project.sara.memory.reranker_service: "Separate FastAPI service."
project.sara.memory.reranker_scoring: "Hybrid: 0.6 reranker + 0.4 cosine. Pure reranker degraded keyword queries."
project.sara.memory.reranker_reuse: "Memory search and note search."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.sara.memory.reranker_plan` | New feature plan with specifics. |
| S1T2 | `<mem_write>` | `project.sara.memory.reranker_config` | Implementation details: model, hardware, latency. |
| S1T3 | `<mem_write>` | `project.sara.memory.reranker_service` | Architecture decision: separate service. |
| S1T4 | `<mem_write>` | `project.sara.memory.reranker_reuse` | Planned reuse across search contexts. |
| S2T1 | `<mem_read>` | `project.sara.memory.reranker_*` | Recall reranker context for quality debugging. |
| S2T2 | `<reflect>` | — | Diagnosing the quality regression. Known reranker/text-length bias issue. |
| S2T3 | `<mem_write>` | `project.sara.memory.reranker_scoring` | Key decision: hybrid scoring with ratio. |
| S2T4 | `<reflect>` | — | Test set is a process detail. Key decision (hybrid scoring) already captured. |

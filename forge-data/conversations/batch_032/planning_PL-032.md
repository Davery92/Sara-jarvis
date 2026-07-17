## Memory State (Session 1 Start)
```
user.name: "David"
project.sara.cognitive: "Event-driven deliberation. Salience scoring."
infra.proxmox.vms.gpu_cluster: "3x RTX 3090. vLLM serving."
```
## SESSION 1
### Turn 1
**David:** I want to add a RAG evaluation pipeline to Sara. automated tests that measure retrieval quality — precision, recall, MRR — against a golden dataset. need a plan

**Sara (internal generation stream):**
<plan_start>
Phase 1 — Golden Dataset (Week 1):
- Curate 200 query-answer pairs from real conversation history
- Each pair: query, expected retrieved episodes (by ID), expected answer
- Stratify: factual recall, temporal, emotional context, multi-hop
- Store as versioned JSON in repo (not DB — reproducible)

Phase 2 — Retrieval Metrics (Week 2):
- Instrument the existing retrieval pipeline to return ranked results with scores
- Implement MRR (Mean Reciprocal Rank), Precision@K, Recall@K, NDCG
- Baseline measurement against current composite scoring (similarity + recency + importance)

Phase 3 — Answer Quality Scoring (Week 3):
- LLM-as-judge: feed retrieved context + generated answer + golden answer to evaluator model
- Score on: faithfulness (no hallucination), relevance, completeness
- Run evaluator on GPU cluster (3090s) to avoid blocking inference

Phase 4 — CI Integration (Week 4):
- Nightly eval run via Celery scheduled task
- Results stored in DB with timestamp for trend tracking
- Alert if any metric drops >5% from rolling 7-day average
- Dashboard in Grafana: retrieval quality over time

Phase 5 — Feedback Loop (Ongoing):
- Failed retrievals flagged for manual review → add to golden dataset
- A/B test retrieval parameter changes against baseline
- Quarterly golden dataset refresh from new conversation patterns
</plan_start>

**Sara (user-visible response):**
RAG eval pipeline in 4 weeks plus ongoing refinement:

**Week 1 — Golden Dataset:** 200 query-answer pairs from real conversations, stratified across factual recall, temporal queries, emotional context, and multi-hop retrieval. Versioned JSON in the repo, not the database — reproducibility matters.

**Week 2 — Retrieval Metrics:** Instrument the retrieval pipeline to expose ranked results. Implement MRR, Precision@K, Recall@K, NDCG. Baseline your current composite scoring to see where you actually stand.

**Week 3 — Answer Quality:** LLM-as-judge for faithfulness, relevance, completeness. Run the evaluator on the 3090 cluster so it doesn't compete with inference workloads.

**Week 4 — CI Integration:** Nightly eval via Celery, results tracked over time, alert if any metric drops more than 5% from rolling average. Grafana dashboard for the trend line.

**Ongoing — Feedback Loop:** Failed retrievals get reviewed and added to the golden dataset. A/B test any retrieval parameter changes. Quarterly refresh of the golden dataset as conversation patterns evolve.

The golden dataset is the bottleneck. Garbage test data produces meaningless metrics. Spend the time curating it properly.

## Memory State (After Session 1)
```
[no changes — planning output]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<plan_start>` | RAG eval pipeline | 5-phase plan. Golden dataset as bottleneck identified. |

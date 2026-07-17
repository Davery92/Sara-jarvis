## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.testing: "34 unit tests. Integration tests. CI active."
project.sara.ci: "GitHub Actions. 47s."
```

## SESSION 1
### Turn 1
**David:** need to plan the load testing for Sara. I want to know how many concurrent conversations she can handle before performance degrades. never tested this because it's been single-user, but if I ever open Sara up to others or if the tool calls start stacking, I need to know the limits

**Sara (internal generation stream):**
<mem_write key="project.sara.testing.load_test" importance="0.60" decay="medium">
Planning load testing for Sara. Goal: determine concurrent conversation capacity before performance degradation. Currently untested — single-user system.
</mem_write>
<plan_start goal="Load test Sara's cognitive pipeline">
  <plan_step goal="Define test scenarios and success metrics" status="active" depends_on="none"/>
  <plan_step goal="Build load test harness" status="pending" depends_on="scenarios"/>
  <plan_step goal="Execute tests and measure" status="pending" depends_on="harness"/>
  <plan_step goal="Identify and address bottlenecks" status="pending" depends_on="results"/>
</plan_start>

**Sara (user-visible response):**
Load testing for a cognitive pipeline — different from standard API load testing because each request involves: memory search (pgvector), context assembly, LLM inference, and potentially Celery tasks.

**Plan:**

**Step 1 — Scenarios**
- Baseline: single conversation, measure P50/P95/P99 response times
- Concurrent: 2, 5, 10 simultaneous conversations
- Spike: burst of 10 requests in 1 second
- Sustained: 5 concurrent conversations for 30 minutes

**Step 2 — Harness**
- Use `locust` (Python load testing framework) — it's async and integrates well with FastAPI
- Each simulated user sends a message, waits for response, sends follow-up
- Measure: response time, first token latency, memory search time, Celery task queue depth

**Step 3 — Execute**
- Run against a staging instance (don't load test production Sara)
- Record metrics at each concurrency level
- Find the inflection point where P95 response time exceeds 2 seconds

**Step 4 — Bottleneck analysis**
- Likely bottleneck: LLM inference (single model, one request at a time)
- Secondary: PostgreSQL connection pool exhaustion at high concurrency
- Tertiary: Redis working memory contention

### Turn 2
**David:** the LLM bottleneck is the obvious one — Qwen can only handle one request at a time on llama.cpp. at 5 concurrent conversations, 4 are waiting in queue. is there a way to handle that without a second inference server?

**Sara (internal generation stream):**
<reflect confidence="0.80">
Single-model LLM bottleneck at concurrency > 1. Options: request queuing with priority (urgent conversations first), or the Qwen2.5-3B as a fast fallback for simple queries while Qwen handles complex ones. Both are architectural approaches, not hardware purchases.
</reflect>

**Sara (user-visible response):**
Two approaches without more hardware:

1. **Priority queuing**: urgent conversations (voice, active chat) get LLM access first. Background tasks (consolidation, PKG extraction) queue behind. You already have activity state — use it for inference priority.

2. **Model tiering**: simple queries (status checks, recall-only) route to the Qwen2.5-3B (fast, already running). Complex queries (planning, debugging, multi-step reasoning) route to the main Qwen MoE. The context router already decides query complexity — extend it to choose the model.

Model tiering is the higher-leverage fix because it genuinely doubles your throughput for the common case.

### Turn 3
**David:** model tiering with the context router — that's elegant. simple queries hit the 3B at 220 tok/s, complex queries hit the 22B at 25 tok/s. the 3B handles 80% of interactions anyway. planning this after the load test confirms the bottleneck

**Sara (internal generation stream):**
<mem_write key="project.sara.inference.model_tiering" importance="0.65" decay="medium">
Planned: model tiering via context router. Simple queries → Qwen2.5-3B (220 tok/s). Complex queries → Qwen3.5-MoE-A22B (25 tok/s). 80% of interactions are simple. Doubles effective throughput. Implementing after load test.
</mem_write>

**Sara (user-visible response):**
Load test to confirm the bottleneck, then model tiering to solve it. If 80% of queries can be served by the 3B at 220 tok/s, your effective concurrent capacity jumps from 1 to effectively 5+ for most interactions. The 22B only blocks on the 20% of complex queries.

## Memory State (After Session 1)
```
project.sara.testing.load_test: "Planned. Locust harness, concurrent scenarios."
project.sara.inference.model_tiering: "Planned: context router → 3B for simple, 22B for complex."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_write>` + `<plan_start>` | `...load_test` | Load testing initiative with 4-step plan. |
| 2 | `<reflect>` | — | LLM bottleneck solutions without hardware. |
| 3 | `<mem_write>` | `...model_tiering` | Architectural decision: model tiering. |

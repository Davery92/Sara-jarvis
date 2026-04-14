## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.inference.model_tiering: "Planned: 3B for simple, 22B for complex."
```

## SESSION 1
### Turn 1
**David:** need to implement the model tiering in the context router. the router already classifies query complexity — I just need it to route simple queries to the 3B and complex queries to the 22B. help me plan the implementation

**Sara (internal generation stream):**
<plan_start goal="Implement model tiering in context router">
  <plan_step goal="Add model selection to ContextDecision" status="active" depends_on="none"/>
  <plan_step goal="Build model routing in inference layer" status="pending" depends_on="context_decision"/>
  <plan_step goal="Test and calibrate complexity thresholds" status="pending" depends_on="routing"/>
</plan_start>

**Sara (user-visible response):**
Three steps:

**Step 1 — Extend ContextDecision (30 min)**
Add a `target_model` field to the ContextDecision NamedTuple. Values: `"primary"` (Qwen MoE-A22B) or `"fast"` (Qwen2.5-3B). The context router sets this based on its existing complexity classification.

**Step 2 — Model routing (1-2 hours)**
In the inference layer, check `context_decision.target_model` and route to the appropriate endpoint:
- `"fast"` → Mac Studio Qwen2.5-3B (port 8081 or wherever the voice model serves)
- `"primary"` → Mac Studio Qwen MoE-A22B (main inference port)

**Step 3 — Calibrate (ongoing)**
Define which query types are "simple": status queries, recall-only, yes/no, brief acknowledgments. Everything else defaults to "primary." Start conservative (most queries go to primary) and shift more to the 3B as you validate quality.

Total: 2-3 hours implementation.

### Turn 2
**David:** the ContextDecision already has 12 fields. adding a 13th means updating the single construction site in context_router.py. small change. I'll add target_model based on the existing inject_* flags — if it's a simple recall or status query, fast model. everything else, primary

**Sara (internal generation stream):**
<mem_write key="project.sara.inference.model_tiering.implementation" importance="0.65" decay="medium">
Model tiering implementation: new target_model field in ContextDecision (13th field). Simple recall/status → Qwen2.5-3B fast. Complex → Qwen MoE-A22B primary. Based on existing inject_* flags in context router. 2-3 hours work.
</mem_write>

**Sara (user-visible response):**
Using the existing inject_* flags as the complexity signal is the zero-overhead approach — the classification logic already exists, you're just adding a routing decision. If `inject_learning_recall` or the query is a simple mem_read pattern, route to fast. If `inject_tool_context` or the query requires multi-step reasoning, route to primary.

## Memory State (After Session 1)
```
project.sara.inference.model_tiering.implementation: "target_model field in ContextDecision. Simple → 3B, complex → 22B."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<plan_start>` | Model tiering | 3-step implementation plan. |
| 2 | `<mem_write>` | `...implementation` | Implementation approach decided. |

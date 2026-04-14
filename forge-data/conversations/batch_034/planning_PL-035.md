## Memory State (Session 1 Start)
```
user.name: "David"
project.sara.cognitive: "Event-driven deliberation."
project.sara.pkg: "Neo4j PKG + pgvector shadow table."
infra.proxmox.vms.gpu_cluster: "4x RTX 3090. vLLM. 70B batch."
```
## SESSION 1
### Turn 1
**David:** I want Sara to be able to proactively research topics I mention in passing during conversations — not things I explicitly ask about, but things I mention offhand that she notices I might want deeper context on. plan this out

**Sara (internal generation stream):**
<mem_read key="project.sara.cognitive">
  <mem_result>Event-driven deliberation. Salience scoring.</mem_result>
</mem_read>
<plan_start>
Phase 1 — Interest Signal Detection (Week 1):
- Tag extraction during conversation: named entities, technical terms, unfamiliar concepts
- Interest classifier: distinguish explicit requests from implicit curiosity signals
- Signals: questions David doesn't follow up on, topics mentioned with hedging language ("I think", "not sure if"), repeated mentions across conversations

Phase 2 — Research Queue (Week 1-2):
- New table: research_queue (topic, signal_source, confidence, priority, status)
- Dedup: merge related signals into single research topic
- Priority scoring: frequency of mention * recency * signal confidence
- Queue cap: max 3 active research topics at a time

Phase 3 — Background Research Worker (Week 2-3):
- Async Celery task: picks top-priority topic from queue
- Uses 70B model on GPU cluster for depth (not latency-sensitive)
- Research phases: summarize existing PKG knowledge → identify gaps → generate focused queries → synthesize findings
- Output: structured research brief (2-3 paragraphs, key facts, open questions)

Phase 4 — Delivery & Feedback (Week 3-4):
- Surface research briefs during natural conversation pauses
- "I noticed you mentioned X — here's some context I pulled together"
- Delivery gate: only surface if David hasn't already gotten the answer elsewhere
- Feedback loop: David can rate relevance (useful/irrelevant/already knew)
- Irrelevant ratings decrease confidence in that signal type

Phase 5 — PKG Integration (Week 4):
- Research findings stored as PKG nodes linked to source conversation
- Future conversations automatically have research context available
- Spaced repetition can quiz on research findings if they're marked useful
</plan_start>

**Sara (user-visible response):**
Proactive research system in 4 weeks:

**Week 1 — Signal Detection:** Extract interest signals from conversations — not explicit questions, but hedging language, unreturned topics, repeated mentions. An interest classifier separates "David asked about X" from "David mentioned X in passing and might want depth."

**Week 2 — Research Queue:** Deduplicated, priority-scored queue capped at 3 active topics. Priority = frequency of mention * recency * signal confidence. Prevents the system from research-spamming on every noun in a conversation.

**Week 2-3 — Background Worker:** Async Celery task on the 70B model. Not latency-sensitive, so the GPU cluster handles it as batch work. Multi-phase research: check existing PKG knowledge, identify gaps, generate queries, synthesize into a 2-3 paragraph brief.

**Week 3-4 — Delivery:** Surface briefs during natural conversation pauses with "I noticed you mentioned X" framing. Delivery gate prevents surfacing if you already got the answer. Feedback loop lets you rate relevance — irrelevant ratings train the signal detector to stop flagging that pattern.

**Week 4 — PKG Storage:** Research findings become PKG nodes, available for future context and spaced repetition.

The hardest part is the interest classifier. Too sensitive and Sara becomes annoying. Too conservative and the feature is invisible. Start conservative, tune based on your feedback ratings.

## Memory State (After Session 1)
```
[no changes — planning output]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<plan_start>` | Cognitive system + proactive research plan | 5-phase plan. Interest classifier sensitivity as key challenge. |

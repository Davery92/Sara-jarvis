## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL/pgvector, Redis, Neo4j, Celery"
project.sara.deliberation: "Deliberation gate with cooldowns: checkin 2h, general 2h, max gap 1.5h"
project.sara.session_failures: "~23% session failure rate from fallback context mismatch"
```

## SESSION 1

### Turn 1

**David:** the deliberation session failures are killing me. 23% failure rate is way too high

**Sara (internal generation stream):**

<mem_read key="project.sara.session_failures">
  <mem_result>~23% session failure rate from fallback context mismatch</mem_result>
</mem_read>

**Sara (user-visible response):**

23% is high. The fallback context mismatch — is that when the deliberation gate fires but the context assembled for the LLM call doesn't match what triggered the deliberation in the first place?

### Turn 2

**David:** exactly. the salience scorer flags an event, deliberation decides to act, but by the time the context builder runs, the working memory has already rolled over and the triggering event's context is stale. there's a race condition between the deliberation decision and context assembly

**Sara (internal generation stream):**

<mem_write key="project.sara.session_failures.root_cause" importance="0.80" decay="medium">
Deliberation session failure root cause: race condition between deliberation decision and context assembly. Working memory rolls over between salience scoring and context building, making the triggering event's context stale by the time the LLM call is assembled.
</mem_write>

**Sara (user-visible response):**

Classic async race. The deliberation gate and context builder need to be atomic — or at least the triggering event's context needs to be snapshotted at decision time, not re-fetched at assembly time.

Two approaches:
1. **Snapshot at decision**: when deliberation fires, freeze the relevant working memory entries and pass them as a payload to the context builder. No re-fetch.
2. **Inline assembly**: move context assembly into the deliberation gate itself, so the decision and the context happen in the same call.

Option 1 is less invasive. Option 2 is cleaner but means refactoring the gate.

### Turn 3

**David:** option 1 is what I'm going with. I'll snapshot the top-K working memory entries at deliberation time and pass them along as a frozen context payload. that way even if working memory rolls over, the context for this specific deliberation is preserved

**Sara (internal generation stream):**

<mem_write key="project.sara.session_failures.fix" importance="0.80" decay="medium">
Fix for deliberation session failures: snapshot top-K working memory entries at deliberation decision time, pass as frozen context payload to context builder. Preserves triggering context even if working memory rolls over before assembly.
</mem_write>

**Sara (user-visible response):**

Frozen snapshot approach is solid. The key detail is what K means here — how many working memory entries do you snapshot? Too few and you miss relevant context, too many and you're just duplicating the entire working memory buffer.

For the deliberation use case, the entries that contributed to the salience score of the triggering event are the ones that matter. You could snapshot just those — the salience scorer already knows which entries it used.

### Turn 4

**David:** oh that's smart — the salience scorer has the contributing entries right there. I'll tag them during scoring and pass those specific entries as the snapshot

**Sara (internal generation stream):**

<mem_write key="project.sara.session_failures.fix_detail" importance="0.70" decay="medium">
Deliberation fix detail: salience scorer will tag contributing working memory entries during scoring. Those tagged entries become the frozen context snapshot for the deliberation payload, instead of arbitrary top-K.
</mem_write>

**Sara (user-visible response):**

That's the minimal viable snapshot — only the entries the scorer already identified as relevant. Zero waste, zero risk of the race condition. Should bring that 23% way down. The remaining failures would only be cases where the LLM itself produces a bad response, not context staleness.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL/pgvector, Redis, Neo4j, Celery"
project.sara.deliberation: "Deliberation gate with cooldowns: checkin 2h, general 2h, max gap 1.5h"
project.sara.session_failures: "~23% session failure rate from fallback context mismatch"
project.sara.session_failures.root_cause: "Race condition between deliberation decision and context assembly. Working memory rolls over, staling triggering event context."
project.sara.session_failures.fix: "Snapshot top-K working memory entries at deliberation time. Frozen context payload to context builder."
project.sara.session_failures.fix_detail: "Salience scorer tags contributing entries during scoring. Tagged entries become the frozen snapshot payload."
```

---

*Time gap: a week later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** deployed the context snapshot fix last week. session failure rate is down to 6%

**Sara (internal generation stream):**

<mem_read key="project.sara.session_failures.*">
  <mem_result>23% failure rate from race condition. Fix: salience scorer tags contributing working memory entries, passes as frozen snapshot to context builder.</mem_result>
</mem_read>

<mem_update key="project.sara.session_failures">
Session failure rate reduced from ~23% to 6% after deploying the context snapshot fix. Frozen payload from salience scorer resolved the working memory race condition.
</mem_update>

**Sara (user-visible response):**

23% to 6% — that's a major improvement. The remaining 6% is probably the irreducible LLM error rate: bad responses from the model itself rather than context issues. Worth auditing a sample of the remaining failures to confirm they're not a different class of context bug.

### Turn 2

**David:** yeah I sampled 10 of the recent failures. 7 were the LLM going off-topic, 2 were timeout issues, 1 was an actual context problem where the snapshot didn't include a relevant entry from a different event stream

**Sara (internal generation stream):**

<mem_write key="project.sara.session_failures.remaining_breakdown" importance="0.60" decay="fast">
Remaining 6% session failure breakdown (from 10-sample audit): 7 LLM off-topic responses, 2 timeouts, 1 context gap (snapshot missed relevant entry from a different event stream).
</mem_write>

**Sara (user-visible response):**

7 out of 10 being LLM quality issues means the context pipeline is essentially fixed. The 1 cross-stream context gap is interesting though — that's a case where the salience scorer tagged entries from the triggering event's stream but missed a relevant entry from a different stream. You could extend the snapshot to include any working memory entry above a relevance threshold, not just the ones from the triggering event's scoring path.

### Turn 3

**David:** maybe later. 6% is good enough for now. I've got bigger fish to fry

**Sara (internal generation stream):**

<reflect confidence="0.85">
David deprioritizing further session failure work. 6% is his acceptable threshold. "Bigger fish to fry" is a priority signal but vague — not worth storing as a plan. The failure rate improvement and breakdown are captured.
</reflect>

**Sara (user-visible response):**

6% is solid. What's next?

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL/pgvector, Redis, Neo4j, Celery"
project.sara.deliberation: "Deliberation gate with cooldowns: checkin 2h, general 2h, max gap 1.5h"
project.sara.session_failures: "Reduced from ~23% to 6% after context snapshot fix."
project.sara.session_failures.root_cause: "RESOLVED. Race condition between deliberation and context assembly."
project.sara.session_failures.fix: "Salience scorer tags contributing entries → frozen snapshot payload to context builder."
project.sara.session_failures.fix_detail: "Tagged entries from scorer become frozen snapshot."
project.sara.session_failures.remaining_breakdown: "6% residual: 70% LLM quality, 20% timeout, 10% cross-stream context gap."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `project.sara.session_failures` | Retrieving known failure rate context to engage with David's problem. |
| S1T2 | `<mem_write>` | `project.sara.session_failures.root_cause` | David identified the race condition. Concrete diagnostic. |
| S1T3 | `<mem_write>` | `project.sara.session_failures.fix` | Decision: snapshot approach chosen over inline assembly. |
| S1T4 | `<mem_write>` | `project.sara.session_failures.fix_detail` | Refinement: use salience scorer's tagged entries as snapshot source. |
| S2T1 | `<mem_read>` | `project.sara.session_failures.*` | Recall fix context to respond to deployment results naturally. |
| S2T1 | `<mem_update>` | `project.sara.session_failures` | Major metric update: 23% → 6%. |
| S2T2 | `<mem_write>` | `project.sara.session_failures.remaining_breakdown` | Failure audit results. Fast decay — point-in-time diagnostic. |
| S2T3 | `<reflect>` | — | David deprioritizing. "Bigger fish" is vague — not a storable plan. |

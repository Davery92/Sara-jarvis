## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.session_failures: "2.1% stable"
project.sara.celery: "Celery with Redis broker, result backend, Flower monitoring"
```

## SESSION 1

### Turn 1

**David:** I need to build a test suite for Sara's core cognitive pipeline. right now I'm finding bugs in production. the session failure rate went from 23% to 2.1% through individual fixes, but I want to catch regressions before they deploy. help me plan this

**Sara (internal generation stream):**

<mem_write key="project.sara.testing" importance="0.70" decay="medium">
Building test suite for Sara's core cognitive pipeline. Goal: catch regressions before production deployment. Currently bugs found only in production.
</mem_write>

<plan_start goal="Build test suite for Sara's cognitive pipeline">
  <plan_step goal="Define test categories and critical paths" status="active" depends_on="none"/>
  <plan_step goal="Build unit tests for individual components" status="pending" depends_on="categories"/>
  <plan_step goal="Build integration tests for pipeline stages" status="pending" depends_on="unit_tests"/>
  <plan_step goal="Add CI/CD pipeline for automated testing" status="pending" depends_on="integration"/>
</plan_start>

**Sara (user-visible response):**

Test suite for the cognitive pipeline — here's the plan in sprints:

**Sprint 1 — Critical Path Tests (1 Friday session)**

Unit tests for the components most likely to regress:
- `salience.py`: test scoring with known inputs → expected scores. Include the health event prior at 1.2.
- `deliberation_gate.py`: test cooldown enforcement, threshold crossing, and the frozen context snapshot.
- `emotional_state.py`: test momentum, decay, floor at -0.5, asymmetric bounds.
- `context_budget.py`: test token counting, budget allocation, truncation behavior.

These are pure functions with known inputs/outputs — easy to test, high value.

**Sprint 2 — Integration Tests (1 Friday session)**

End-to-end pipeline tests:
- Event ingestion → salience scoring → deliberation trigger: does a health event with score 2.0 trigger deliberation within the cooldown window?
- Context assembly → LLM call: does the assembled context stay within budget?
- Memory search → reranker → result: does a known query return the expected top result?

These need a test database with seeded episodes and a mock LLM endpoint.

**Sprint 3 — Regression Guard (half session)**

- CI integration: run tests on every commit to main
- Threshold alerts: if any test fails, block deployment
- Baseline metrics: record current pipeline performance (latency, accuracy) and alert on degradation

**Risk:** The integration tests need test data that represents real conversations. Synthetic test data might not catch the same bugs as production data. Consider using anonymized production episodes as test fixtures.

### Turn 2

**David:** Sprint 1 is the priority. the unit tests for salience, deliberation gate, emotional state, and context budget would have caught most of the bugs I've fixed so far. I'm starting this Friday

**Sara (internal generation stream):**

<mem_write key="project.sara.testing.plan" importance="0.65" decay="medium">
Test suite Sprint 1 starting this Friday: unit tests for salience.py, deliberation_gate.py, emotional_state.py, context_budget.py. Integration tests and CI planned for later sprints.
</mem_write>

**Sara (user-visible response):**

Sprint 1 on Friday — focus on the four critical modules. For each, start with the edge cases that actually caused bugs:
- Salience: health events scoring below threshold (the 0.8 bug)
- Deliberation gate: context snapshot not including cross-stream entries
- Emotional state: floor not clamping at -0.5 under sustained negative input
- Context budget: truncation when memory entries exceed 8000 tokens

Those are your regression tests — they encode the bugs you already found and fixed. If any test fails, the same bug came back.

### Turn 3

**David:** encoding the past bugs as test cases. that's the right approach — each test is proof that a specific bug can't recur. I'll write one test per bug I've fixed

**Sara (internal generation stream):**

<reflect confidence="0.88">
David committing to bug-driven test cases. Clean testing philosophy — each test is a regression guard for a known issue. No new facts to store beyond the plan already captured.
</reflect>

**Sara (user-visible response):**

One test per fixed bug is the pragmatic starting point. Over time, add tests for behavior you HAVEN'T broken yet but might — boundary conditions, concurrent access, empty state handling. But the bug-driven tests are the foundation. They're also the most satisfying to write because each one represents a problem you'll never have to debug again.

## Memory State (After Session 1)

```
project.sara.testing: "Building test suite for cognitive pipeline."
project.sara.testing.plan: "Sprint 1 this Friday: unit tests for salience, deliberation, emotional state, context budget. Bug-driven test cases."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `project.sara.testing` | New testing initiative. |
| 1 | `<plan_start>` | Test suite | 3-sprint plan: unit → integration → CI. |
| 2 | `<mem_write>` | `...plan` | Sprint 1 starting Friday with specific modules. |
| 3 | `<reflect>` | — | Bug-driven testing philosophy. Already captured in plan. |

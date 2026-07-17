## Memory State (Session 1 Start)
```
user.name: "David"
project.sara.cognitive: "Event-driven deliberation. Salience scoring. Threshold 1.5."
project.sara.memory: "Tiered search + BGE reranker + Redis working set."
```
## SESSION 1
### Turn 1
**David:** I want to add a sleep mode to Sara's cognitive system. between midnight and 6am, she should batch low-priority observations instead of processing them in real-time, reduce notification frequency to emergencies only, and run a nightly consolidation pass. plan it out

**Sara (internal generation stream):**
<mem_read key="project.sara.cognitive">
  <mem_result>Event-driven deliberation. Salience scoring. Threshold 1.5.</mem_result>
</mem_read>
<plan_start>
Phase 1 — Sleep State Detection (2 days):
- Add SLEEP state to activity state machine (midnight-6am ET, configurable)
- Override interruptibility score to 0.1 during sleep window
- HA bridge integration: bedroom presence sensor + phone charging state as signals

Phase 2 — Observation Batching (3 days):
- New sleep_observation_queue table: event_id, salience_score, received_at
- During SLEEP: events below salience 3.0 queued instead of processed
- Events above 3.0 (security alerts, system failures) still process immediately
- Queue drains at wake-up time via Celery task

Phase 3 — Notification Suppression (2 days):
- Sleep-aware notification gate: only CRITICAL priority during sleep window
- Existing cooldowns still apply post-sleep
- Morning digest: batched observations summarized into single notification at wake-up

Phase 4 — Nightly Consolidation (3 days):
- Scheduled at 3am ET (deep sleep, no user interaction expected)
- Memory consolidation: compact low-importance episodes, merge similar observations
- PKG maintenance: prune stale edges, refresh embeddings on recently updated nodes
- Working memory cleanup: expire Redis entries older than decay threshold

Phase 5 — Wake-Up Sequence (2 days):
- Drain observation queue, process in salience order
- Generate morning brief from batched observations + calendar
- Transition activity state from SLEEP → IDLE
- Resume normal salience thresholds and notification cadence
</plan_start>

**Sara (user-visible response):**
Sleep mode in 5 phases, ~12 days:

**Days 1-2 — Sleep State:** Add SLEEP to the activity state machine. Midnight-6am ET, with HA bridge signals (bedroom presence + phone charging) as confirmation. Interruptibility drops to 0.1.

**Days 3-5 — Observation Batching:** Events under salience 3.0 get queued to a sleep_observation_queue table instead of triggering deliberation. Anything above 3.0 (security, system failure) still fires immediately. Queue drains at wake-up.

**Days 6-7 — Notification Suppression:** Only CRITICAL notifications during sleep. Everything else batches into a morning digest — one notification summarizing the night's observations.

**Days 8-10 — Nightly Consolidation:** 3am job that compacts low-importance memories, prunes stale PKG edges, refreshes embeddings, and cleans the Redis working set. This is the maintenance window Sara has been missing.

**Days 11-12 — Wake-Up Sequence:** Drain the queue in salience order, generate a morning brief, transition from SLEEP to IDLE, restore normal thresholds.

The salience threshold split is the key design decision: 3.0 for sleep vs 1.5 for awake. That ratio determines what's "emergency enough" to wake you. Too low and sleep mode leaks; too high and you miss real problems.

## Memory State (After Session 1)
```
[no changes — planning output]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<plan_start>` | Cognitive system + sleep mode plan | 5-phase plan with salience threshold as key decision. |

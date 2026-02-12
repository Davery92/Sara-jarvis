# Sara Heartbeat Subconscious Specification

## 1. Purpose

Define a single, coherent architecture for Sara as a 15-minute subconscious loop that:

1. Reads explicit operating instructions from `backend/data/HEARTBEAT.md`.
2. Uses complete and relevant current context.
3. Executes pre-authorized behavior through standing orders.
4. Executes mechanical recurring behavior through automations.
5. Records what happened so future runs are stateful and trustworthy.

This specification is optimized for a single-user deployment (`David only`), but still enforces internal safety and auditability.

## 2. Product Intent

Sara should feel like a human subconscious layer:

1. Always-on situational awareness.
2. Continuous background thinking, not constant interruption.
3. Distinct memory of what she already did and why.
4. Clear distinction between policy decisions and mechanical execution.
5. Predictable behavior with reversible actions.

## 3. Scope and Non-Goals

### In scope

1. Heartbeat run lifecycle (`SENSE -> THINK -> ACT -> RECORD`).
2. Context assembly contract for each run.
3. Standing-order semantics and lifecycle.
4. Automation semantics and lifecycle.
5. Background processes including dream sequencing and Celery workers.
6. Observability, trust UX, and failure handling.

### Out of scope

1. Frontend visual design.
2. Multi-user tenancy design.
3. External enterprise auth architecture.

## 4. Core Principles

1. `Predictability over cleverness`
2. `Explicit authority boundaries`
3. `Deterministic execution paths for device control`
4. `Every autonomous action is explainable and reversible`
5. `Context freshness before context volume`
6. `One scheduler authority per concern`

## 5. Canonical Role Boundaries

### 5.1 Heartbeat (Subconscious)

The heartbeat decides "what matters now" and may:

1. Trigger tools for additional checks.
2. Queue notifications.
3. Execute standing orders that are due.
4. Produce handoff notes for the next run.

It should not become a generic cron executor.

### 5.2 Standing Orders (Policy Layer)

Standing orders encode pre-authorized intent and judgment policy.

Examples:

1. "When timer X ends, turn off heater."
2. "At 23:00, check lights and apply house wind-down behavior."
3. "When event starts in 30m, notify me."

Characteristics:

1. User-approved once, then reusable.
2. Context-aware and semi-semantic.
3. Undo-tracked and auto-paused when repeatedly undone.

### 5.3 Automations (Execution Layer)

Automations are mechanical schedules and action sequences.

Examples:

1. "Run every 2 hours."
2. "Run once at 14:00."
3. "Run if state changed from A to B."

Characteristics:

1. Deterministic scheduling (`next_wake_at`, step progression, retries).
2. Primitive/action level safety checks.
3. No hidden policy inference.

### 5.4 Reflection and Dreaming (Meta Layer)

These layers generate insight and synthesis. They should:

1. Produce hypotheses, summaries, and patterns.
2. Feed heartbeat context.
3. Not directly execute high-authority home actions.

## 6. Runtime Architecture (Current + Target)

### 6.1 Main loop owner

Primary owner is Celery task:

1. `app.tasks.autonomy.unified_agent` every 15 minutes (defined in `backend/app/celery_app.py`).

### 6.2 Four phases

Heartbeat run in `backend/app/services/unified_agent.py` should remain:

1. `SENSE`: gather raw signals and compute state.
2. `THINK`: LLM-guided reasoning with tool loop and HEARTBEAT rules.
3. `ACT`: notification and low-latency action dispatch.
4. `RECORD`: journals, run logs, context updates, memory extraction.

### 6.3 Scheduler authority

Each recurring concern must have one runtime owner:

1. Heartbeat cadence: Celery beat only.
2. Nightly dream scheduler: intelligence pipeline-managed singleton, with startup fallback only if pipeline unavailable.
3. Automation execution cadence: automation watcher only.

## 7. Context Contract for Each Heartbeat Run

## 7.1 Context objective

Each run consumes "max relevant current context", not "all historical data."

## 7.2 Required context domains

### Tier A (must-have, every run)

1. Current time/day and local timezone.
2. Last conversation timestamp and recent conversation digest.
3. Current activity state and interruptibility.
4. Current pending reminders and near-future calendar.
5. Notifications already sent today (for dedupe).
6. Last few heartbeat handoffs and run outcomes.
7. Standing orders status and due evaluations.
8. Active automation health summary.
9. `HEARTBEAT.md` content.

### Tier B (high-value, pulse or deep runs)

1. Recent notes changes.
2. Habit completion and pending habit signals.
3. Active learning/review queue.
4. Open conversation threads.
5. Behavioral patterns.
6. Recent background task completions.

### Tier C (deep runs only)

1. Relevant episodic memory retrieval.
2. PKG project/goal snapshot.
3. Mood trajectory over recent days.
4. Latest dream insight summary.

## 7.3 Freshness and staleness policy

1. Tier A data should be refreshed within the run and considered stale after 15 minutes.
2. Tier B data should refresh at least once per hour.
3. Tier C data can be up to 24 hours stale.
4. Any stale/missing domain must be explicitly tagged as unavailable in the prompt context.

## 7.4 Context budgeting

Prompt composition should reserve space by priority:

1. System instructions and HEARTBEAT rules.
2. Dedupe and safety memory.
3. Tier A.
4. Tier B.
5. Tier C.

When near token limits:

1. Summarize older/low-priority sections.
2. Never drop dedupe or explicit rules first.

## 8. Heartbeat Behavior Specification

## 8.1 Phase 1: SENSE

Outputs canonical `SensedState` with:

1. Presence/activity/interruptibility.
2. Body and mood estimates.
3. Conversation velocity and digest.
4. Notes, habits, learning, document, automation signals.
5. System health.

Persistence:

1. Upsert `subconscious_state`.
2. Append `body_state_history`.
3. Update `unified_context` snapshot fields.
4. Refresh conversation thread caches.

## 8.2 Phase 2: THINK

Inputs:

1. `SensedState`.
2. HEARTBEAT instructions.
3. Enriched context bundle.
4. Prior run memory.
5. Today notification log.

Required behavior:

1. Execute explicit HEARTBEAT rules first.
2. Evaluate due time standing orders deterministically before discretionary LLM actions.
3. Use tool loop only when needed.
4. Enforce dedupe by topic/category.
5. Produce `THOUGHT` and `HANDOFF` sections.

## 8.3 Phase 3: ACT

Notification path:

1. Queue first, send consolidated.
2. Respect interruptibility and defer low-priority messages when needed.
3. Enforce category/topic dedupe and cooldown.

Action path:

1. Restrict to approved primitives.
2. Log action details with success/failure.

## 8.4 Phase 4: RECORD

Must write:

1. Journal entry.
2. `agent_run_log` with context summary, actions, notifications, handoff.
3. Context snapshot heartbeat markers.
4. Optional PKG lightweight extraction.

Failure path:

1. Write error run log.
2. Preserve queued high-priority notifications where safe.

## 9. Standing Orders Specification

## 9.1 Purpose

Represent policy-like, reusable user-approved behavior.

## 9.2 Lifecycle

1. Created by user intent or promoted pattern.
2. Status transitions: `active`, `paused`, `completed`, `deleted`.
3. Evaluated by trigger type (`time`, `timer`, `presence`, `climate`, `state`).
4. Logged in action ledger.
5. Undo path can auto-pause chronic misfires.

## 9.3 Trigger semantics

1. `time`: within heartbeat window and day constraints.
2. `timer`: fire when matched timer completion observed.
3. `presence/climate/state`: matched against current context/event payload.
4. Optional cooldown and one-shot behavior.

## 9.4 Action semantics

Allowed action classes:

1. `home_control`
2. `notification`
3. `all_lights_off`
4. `lock_all`

Every execution writes:

1. `standing_order_id`
2. Trigger context
3. Success/failure
4. Undo eligibility window

## 9.5 Learning/undo policy

1. Repeated undos are not ignored.
2. At configurable threshold, order auto-pauses.
3. User is informed with concise rationale.

## 10. Automations Specification

## 10.1 Purpose

Reliable mechanical execution for recurring and sequenced tasks.

## 10.2 Lifecycle

1. `pending_confirmation`
2. `active`
3. `paused`
4. `completed`
5. `failed`
6. `cancelled`

## 10.3 Scheduler model

1. Watcher scans `active` tasks where `next_wake_at <= now`.
2. Executor locks row and runs next step.
3. Executor updates `current_step`, `next_wake_at`, `execution_count`, and errors.

## 10.4 Schedule definitions

1. `interval`
2. `cron`
3. `one_time`
4. `state_change`

One-time contract:

1. Initial run should always get a concrete first `next_wake_at`.
2. Once complete or no longer eligible, task transitions to terminal state, not inert active state.

## 10.5 Conditions and retries

1. If conditions fail and schedule is recurring, reschedule.
2. If conditions fail for one-time after time window, complete terminally.
3. Consecutive errors increment safety counters.
4. Auto-pause/failed state after threshold.

## 10.6 Separation from standing orders

1. If intent is policy with context interpretation, use standing order.
2. If intent is deterministic recurrence/sequence, use automation.
3. Avoid dual-authority definitions for same behavior.

## 11. Background Process Inventory

## 11.1 Celery beat recurring tasks (core)

Defined in `backend/app/celery_app.py`:

1. Consolidation watcher.
2. Working memory refresh and cleanup.
3. System heartbeat.
4. Reflection cycle and maintenance.
5. Unified agent (15 minutes).
6. Morning/evening anticipation.
7. Nightly memory consolidation.
8. Weekly digest.
9. PKG extraction passes.
10. Idle processing.
11. Weather and home-state summaries.
12. Email sync tasks.
13. Automation watcher.
14. Learning pollers.

## 11.2 Dream sequencing and consolidation

Two dream-related paths exist conceptually:

1. `NightlyDreamService` scheduler loop (2:00-3:00 AM ET window).
2. `DreamConsolidationService` pipeline for clustering/summarization insights.

Required contract:

1. Exactly one scheduler loop active per runtime.
2. Dream outputs are consumable context artifacts, not direct command triggers.
3. Parser robustness must handle dict/string/fenced JSON responses.

## 11.3 Context maintenance

1. `unified_context` snapshot acts as shared state.
2. `context_writer` performs partial updates and notable change tracking.
3. Snapshot rebuild path restores state after cache loss.

## 12. Worker and Queue Topology

## 12.1 Queues

Current task queues:

1. `cognitive`
2. `health`
3. `input`
4. `reflection`
5. `maintenance`
6. `low_priority`

## 12.2 Worker command contract

Production worker command must subscribe to all required queues for deployed features, including:

1. `reflection`
2. `autonomy` routes if explicitly routed that way

Queue mismatch between routing and worker subscription is treated as a release blocker.

## 12.3 Concurrency and exclusivity

1. Use coordinator-based exclusive groups for heavy LLM work.
2. Keep one-flight guarantees for expensive or duplicate-prone loops.

## 13. Safety and Trust Model

Even single-user systems need internal trust guarantees.

## 13.1 Authority tiers

1. Tier 0: read-only sensing and summarization.
2. Tier 1: notifications and reminders.
3. Tier 2: reversible home actions.
4. Tier 3: irreversible/destructive actions (disabled by default).

## 13.2 Reversibility

1. Every Tier 2 action should create undo metadata.
2. Undo should be available for a bounded window.
3. Repeated undos should adapt policy.

## 13.3 Quiet mode

Global mode should immediately downgrade autonomy:

1. Keep sensing and recording.
2. Suppress non-urgent actions/notifications.
3. Preserve logs and handoffs.

## 13.4 Deduplication

Dedupe key must include:

1. Topic/category.
2. Time bucket.
3. Optional cooldown window.

## 14. Observability Requirements

## 14.1 Must-log entities

1. Heartbeat run start/end/duration/result.
2. Context load completeness and stale domains.
3. Tools called and outcomes.
4. Standing-order evaluations and executions.
5. Automation watcher dispatch stats.
6. Notification sends/deferrals/dedup suppressions.
7. Dream cycle start/end/insight count.

## 14.2 Health dashboards

Minimum views:

1. Last 24h heartbeat outcomes.
2. Notification volume and dismiss rates.
3. Standing-order execution and undo rates.
4. Automation active/failed/completed counts.
5. Queue lag and worker heartbeat.

## 15. Known Design Risks and Mitigations

1. Context overload causes noisy decisions.
Mitigation: relevance tiers and token budgeting.

2. Duplicate scheduler loops create race conditions.
Mitigation: one owner per scheduler concern and startup guards.

3. Policy/execution blur causes inconsistent behavior.
Mitigation: strict standing-order vs automation boundary.

4. Silent worker queue mismatch drops tasks.
Mitigation: startup queue contract validation.

5. Repeated low-value check-ins reduce trust.
Mitigation: dedupe + outcome-aware throttling.

## 16. Acceptance Criteria

System is considered aligned with this spec when:

1. Unified heartbeat runs every 15 minutes and records all phases.
2. Each run has Tier A context coverage or explicit missing-domain markers.
3. Standing orders and automations are behaviorally distinct and non-overlapping.
4. One-time automations never remain `active` with null wake.
5. Exactly one nightly dream scheduler is active.
6. Every autonomous action is visible in logs and reversible when applicable.
7. Notification dedupe prevents repeated same-topic spam.

## 17. Recommended Implementation Plan

## Phase 1: Contract hardening

1. Add explicit context bundle schema and completeness checks.
2. Add startup invariant checks for worker queue subscriptions and singleton schedulers.
3. Add heartbeat run-quality metrics.

## Phase 2: Context quality

1. Add relevance ranking/scoring to enriched context assembly.
2. Introduce token budget enforcement with section truncation priorities.
3. Add stale-domain annotations into prompt.

## Phase 3: Policy and execution clarity

1. Enforce intent classifier for standing-order vs automation routing.
2. Add conflict detection for duplicate intent definitions across both layers.
3. Extend undo learning and adaptive cooldowns.

## Phase 4: Trust UX and control

1. Add daily autonomy digest.
2. Add global quiet mode and emergency action kill switch.
3. Add explicit "why this happened" trace for each action.

## 18. Notes for Single-User Operation

Because this system is permanently single-user:

1. Keep auth simple.
2. Keep internal safeguards strict.
3. Prioritize behavior correctness and trust over access-control complexity.
4. Use user-specific assumptions to simplify schema and prompt logic where it improves reliability.

## 19. File and Module Mapping

Primary implementation touchpoints:

1. `backend/app/services/unified_agent.py`
2. `backend/app/tasks/autonomy.py`
3. `backend/app/services/standing_order_service.py`
4. `backend/app/tasks/automation.py`
5. `backend/app/tools/automation.py`
6. `backend/app/celery_app.py`
7. `backend/app/services/intelligence_pipeline.py`
8. `backend/app/services/nightly_dream_service.py`
9. `backend/app/services/dream_consolidation.py`
10. `backend/app/services/unified_context.py`
11. `backend/app/services/context_writer.py`
12. `backend/data/HEARTBEAT.md`

## 20. Current Codebase Alignment Notes

These are concrete items to align implementation with this spec.

1. Standardize heartbeat lineage to one implementation path.
Current repo still contains legacy heartbeat modules (`heartbeat_agent`, `unified_heartbeat`) alongside `unified_agent`.
Expected: one canonical runtime path, others clearly deprecated or removed.

2. Align automation status vocabulary across modules.
`automation_task` lifecycle uses `pending_confirmation` and `active`, while some sensing queries still look for `pending` and `running`.
Expected: one shared enum or constants module used by all reads/writes.

3. Align run-log source naming.
Some snapshot rebuild paths still reference `unified_heartbeat` while active write path uses `unified_agent`.
Expected: canonical `source` value with migration/compatibility mapping.

4. Define single source of truth for heartbeat policy state.
Both `HEARTBEAT.md` rules and `heartbeat_items` table exist.
Expected: either explicit dual-model policy with merge order, or one primary model and one deprecated path.

5. Keep queue-route declarations and worker subscription lists validated at startup.
Expected: boot-time invariant check that fails fast on queue drift in production.

6. Ensure dream scheduling singleton invariant is test-covered.
Expected: runtime guard plus integration test proving no duplicate nightly scheduler loops.

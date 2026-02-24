# Non-Fitness Autonomy + UX Plan

Date: February 12, 2026  
Scope: Excludes fitness and habits work by request

## 1) Goal

Improve reliability and perceived "Jarvis/Cortana" quality by:

1. Closing non-fitness stub/incomplete areas that break trust.
2. Safely rolling out autonomy features currently defaulted off.
3. Refactoring and simplifying the web UX around an ambient assistant workflow.

---

## 2) In-Scope Gaps (Non-Fitness)

These are current gaps to close first.

### 2.1 Security and Access-Control Gaps

1. `backend/app/routes/automation_admin.py`: admin check is placeholder (`require_admin` currently allows any authenticated user).
2. `backend/app/routes/automation.py`: WebSocket auth is TODO and currently hardcoded to `"default"` user.
3. `backend/app/models/user.py`: no role/permission field exists today, so admin authorization requires schema + model updates.

Impact:

1. Weak authorization boundary for high-impact automation surfaces.
2. Elevated risk of unintended control/data access.

### 2.2 Stubbed/Incomplete Execution Paths

1. `backend/app/services/morning_proactive_service.py`: automation action path logs "Would execute automation" instead of invoking executor.
2. `backend/app/routes/memory.py`: `/memory/consolidate` marked as lightweight stub (limited summarization/edge richness).
3. `backend/app/tasks/reflection.py`: skip behavior (`"Proposal not implemented"`) may be intentional; upstream proposal lifecycle/status transitions need validation.
4. `backend/app/services/vision.py` route path (`backend/app/routes/vision.py`): screenshot storage path has TODO for MinIO persistence.

Impact:

1. Assistant can suggest actions but not always complete them.
2. Memory/insight quality ceiling remains below product narrative.
3. Users see partial autonomy loops (detect -> suggest, but not execute/verify consistently).

### 2.2.1 Definition of Done: Memory Consolidation Upgrade

1. Replace stub-grade daily summary with LLM-assisted summary generation.
2. Add richer edge extraction beyond basic same-day linking:
   1. temporal continuity edges
   2. semantic similarity edges
   3. open-loop/commitment carry-forward edges
3. Persist summary and edge metadata with clear provenance fields.
4. Add regression checks proving behavior exceeds current baseline:
   1. summary quality checks
   2. minimum edge coverage checks
   3. deterministic fallback behavior when LLM is unavailable

### 2.3 Placeholder Architecture in Runtime Tree

1. `backend/app/services/task_runner/__init__.py`: Phase 6 placeholder package.
2. `backend/app/services/monitors/__init__.py`: only calendar monitor exported; other monitors remain TODO.

Impact:

1. Maintenance complexity without immediate user value.
2. Roadmap debt increases and slows confidence in autonomy roadmap.

### 2.4 Quality/Consistency Gaps

1. `backend/app/tasks/working_memory.py`: timezone TODO ("use user's timezone").
2. `backend/app/services/bge_reranker.py`: remote reranking path not implemented, fallback only.

Impact:

1. Lower precision in relevance and time-based behavior.
2. Uneven assistant quality across contexts.

### 2.5 Explicit Closure Workstream for 2.3 and 2.4

1. `task_runner` placeholder:
   1. Decision gate: either implement minimal runner for currently shipped flows or mark package deprecated and remove active references.
   2. Do not leave placeholder architecture as implied capability.
2. `monitors` package:
   1. Implement `reminder_monitor` for non-fitness proactive coverage.
   2. Keep `habit_monitor` out of scope (see exclusions).
3. `working_memory` timezone fix:
   1. Use per-user timezone source from profile/settings.
   2. Remove server-local-hour assumptions in inference path.
4. `bge_reranker` remote path:
   1. Implement remote rerank client path with health checks and timeout policy.
   2. If remote reranking remains unsupported, remove/disable configuration path to avoid false expectation.

---

## 3) Default-Off Autonomy Features: Impact and Rollout

Current defaults in `backend/app/core/config.py`:

1. `autonomy_structured_plan=False`
2. `autonomy_policy_engine=False`
3. `autonomy_attention_enabled=False`
4. `autonomy_missions_enabled=False`
5. `autonomy_policy_candidates_enabled=False`

### 3.1 Product Impact of Staying Off

1. No full 6-phase control loop by default (`SENSE -> PLAN -> SIMULATE -> EXECUTE -> VERIFY -> RECORD`), reducing determinism.
2. Policy engine remains mostly hard-gated rather than fully risk-scored.
3. Notifications route direct instead of inbox-first attention workflow.
4. Mission progression and resumable multi-step execution stays inactive.
5. Reflection/dream-to-policy learning loop stays mostly manual.

### 3.2 Observability Prerequisite (Must Be Done Before Any Flag Enablement)

1. Add dashboards and counters for:
   1. action allow/deny/defer rates by tool and risk tier
   2. structured plan parse/fallback rates
   3. notification routing split (direct push vs attention queue)
   4. mission lifecycle throughput and failure reasons
2. Add trace sampling and drill-down views for:
   1. autonomy run_id to action trace lineage
   2. simulator outcomes vs execution outcomes
3. Define SLO-style thresholds used by rollout and rollback criteria.
4. Require observability readiness sign-off before enabling any autonomy flag in production.

### 3.3 Safe Rollout Order

1. Complete observability prerequisite.
2. Enable `autonomy_attention_enabled` first.
3. Enable `autonomy_structured_plan` in canary/shadow verification mode.
4. Enable `autonomy_policy_engine` after trace review.
5. Enable `autonomy_missions_enabled` with strict action limits.
6. Enable `autonomy_policy_candidates_enabled` once review UX is in place.

### 3.4 Exit Criteria per Flag

1. Attention: lower push noise, higher actionable open/read rates.
2. Structured plan: parse-failure fallback rate under agreed threshold.
3. Policy engine: deny/defer decisions match expected risk policy.
4. Missions: successful completion rate and rollback behavior validated.
5. Policy candidates: accepted/rejected throughput visible and auditable.

### 3.5 Rollback Criteria per Flag

1. `autonomy_attention_enabled` rollback trigger:
   1. push or queue misrouting above threshold for two consecutive review windows
2. `autonomy_structured_plan` rollback trigger:
   1. parse/fallback rate above threshold
   2. simulator/execution mismatch spikes above threshold
3. `autonomy_policy_engine` rollback trigger:
   1. false denies or unsafe allows above threshold during trace audits
4. `autonomy_missions_enabled` rollback trigger:
   1. mission failure/retry storm or stuck-state growth above threshold
5. `autonomy_policy_candidates_enabled` rollback trigger:
   1. candidate noise exceeds review capacity
   2. low precision of accepted candidates over rolling window

---

## 4) Web UX Plan

## 4.1 Current UX Constraints

1. Main web app mounts the monolithic interactive shell (`frontend/src/main.tsx` -> `App-interactive.tsx`).
2. `App-interactive.tsx` is large stateful orchestration (~2.2k lines) with many direct fetch/poll loops.
3. Command palette includes dead destinations that are not rendered view targets (notably `memory-garden` and `insights`).
4. Navigation exposes too many peer-level sections, increasing cognitive load.
5. Home and Chat experiences read as generic productivity SaaS rather than operator console.

### 4.2 UX Target State

1. Route-driven app shell with deep links and predictable browser navigation.
2. "Mission Control" home with three lanes:
   1. `Now` (urgent + in-progress)
   2. `Soon` (scheduled and queued)
   3. `Needs Decision` (confirm/defer items)
3. Chat centered on action chips and next-step execution.
4. Inbox-first autonomy UX as a first-class navigation destination.
5. Command palette backed by actual route/action registry (no dead commands).

### 4.3 UX Implementation Phases

#### Phase UX-1 (Foundation)

1. Move view switching from local `view` state to route-based navigation.
2. Create shared data hooks (React Query) for timers/reminders/inbox/status.
3. Remove duplicate polling patterns from single mega component.

Deliverables:

1. Stable app shell with route boundaries.
2. Fewer cross-feature regressions from local state coupling.

#### Phase UX-2 (Core Surfaces)

1. Redesign Home into Mission Control lanes.
2. Add explicit Attention Inbox page and wire counts/badges.
3. Rework Chat empty state to context-aware quick actions (calendar, inbox, standing orders, missions).

Deliverables:

1. A visible autonomy workflow users can monitor and trust.
2. Lower time-to-action for common decisions.

#### Phase UX-3 (Polish and Consistency)

1. Simplify nav to core destinations + "More".
2. Replace browser-native confirms with in-app modal/decision patterns.
3. Align visual tokens and status colors around action urgency and confidence.
4. Remove/replace dead command entries (`memory-garden`, `insights`) and derive command palette options from active routes/actions only.

Deliverables:

1. Reduced cognitive load.
2. Consistent interaction model across pages.

---

## 5) Acceptance Metrics

1. Security:
   1. No placeholder auth paths in automation admin/websocket routes.
   2. Role/permission enforcement in place for admin endpoints.
   3. WebSocket auth implemented via explicit token validation path.
2. Reliability:
   1. No "would execute" placeholder in proactive automation flow.
   2. Memory consolidate endpoint meets defined DoD in section 2.2.1.
   3. Reflection proposal lifecycle validated: implemented proposals are reachable and measured.
   4. Vision screenshot persistence path writes to MinIO with traceable metadata.
3. Autonomy:
   1. Observability prerequisite from section 3.2 is complete before any flag enablement.
   2. Rollback criteria from section 3.5 are configured and tested.
   3. Attention queue enabled and used for normal/low priority.
   4. Structured plan and policy engine enabled with acceptable fallback/deny drift.
4. Runtime hygiene:
   1. `task_runner` placeholder resolved (implemented or explicitly deprecated with references removed).
   2. `reminder_monitor` implemented and active.
   3. `working_memory` timezone behavior uses user timezone.
   4. `bge_reranker` remote path implemented or configuration path removed.
5. UX:
   1. Route-driven navigation in production shell.
   2. Command palette has no dead routes/commands.
   3. Home experience centered on actionable autonomy state.

---

## 6) Risks and Mitigations

1. Risk: enabling policy engine blocks expected actions.
   1. Mitigation: staged rollout with trace audit and explicit allowlist review.
2. Risk: UX migration introduces regressions.
   1. Mitigation: incremental route cutover + smoke tests per route.
3. Risk: mission/candidate features add noise.
   1. Mitigation: confidence thresholds + strict inbox prioritization rules.

---

## 7) Explicit Exclusions

Per request, this plan excludes:

1. Fitness stubs and fitness integration work.
2. Habit stubs and habit feature completion work.
3. `habit_monitor` implementation in monitors package (deferred with habits scope).

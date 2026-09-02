# Agent Task Visibility (iOS) + Single-Flight Research — Plan

**Date:** 2026-09-01
**Trigger:** The Salem research incident. David asked Sara to hand off a research task; the handoff worked all three times, but (a) nothing on iOS showed a task was running, so David had to rely on Sara's word, and (b) Sara's own status tools couldn't see research plans, so she falsely reported "nothing is running." The duplicate re-handoffs this provoked ran two research agents concurrently against the Mac Studio bg lane (:8081), which OOM'd with 507s and killed all three plans — which were then marked `complete` with zero output and no failure notification.

**Two non-negotiable outcomes:**
1. **Every agent task, no matter what kind, is visible on iOS** — a floating indicator appears the moment Sara dispatches anything, on every screen.
2. **Concurrent research tasks are not allowed** — duplicates are killed at the door, execution is strictly one-at-a-time, and 507s pause a plan instead of shredding it.

---

## Ground truth (verified 2026-09-01, all in the running containers)

| Piece | State |
|---|---|
| `GET /api/background-tasks/active` + `/recent` | **Already merge** `background_task` + `research_plan` rows (`_recent_research_plans`, `_merge_task_lists` in `backend/app/routes/background_tasks.py`). Deployed in `jarvis-backend-1`. The data David needed existed the whole time. |
| Web `BackgroundTasksIndicator.tsx` | Polls `/recent` every 5s, header badge + panel. Works. |
| iOS `BackgroundTasksContext.tsx` | Mounted in `App.tsx`. Polls `/active`+`/recent` (10s active / 60s idle), drives the "Sara is working" Live Activity + clarification modal. |
| iOS `src/components/BackgroundTasksIndicator.tsx` | **Exists but is imported by NOTHING.** No in-app visual anywhere. This is the primary visibility gap. |
| Live Activity | Only starts/updates from in-app polling → invisible if the app isn't foregrounded; also requires a current native build (EAS lag risk). |
| Sara's `get_background_tasks` **tool** | Reads `background_task` only → blind to research plans. Source of the false "zero active tasks." |
| Sara's `research_plan_status` tool | Exact-match `WHERE id = :id`; Sara quotes 8-char prefixes in prose and reads them back → "Plan not found" for a running plan. |
| `david_priority` Celery worker | `--concurrency=2` (docker-compose.dev.yml:441). Only `run_research_plan` routes here → 2 concurrent research agents possible, which is exactly what OOM'd the lane. |
| Research executor (`backend/app/services/research/executor.py`) | No retry on LLM 5xx; failed step → continue; plan unconditionally marked `complete` (line ~192) even at 0/6 steps; synthesis failure swallowed (line ~671); no failure push. Plan 3 "completed" all 6 steps in 1.3 seconds of instant 507s. |

---

## Phase 1 — One source of truth for "what is Sara doing" (backend)

**Goal:** every dispatch path lands in the same merged feed the UI and Sara's tools both read.

1. **Extract the merge into a service.** New `backend/app/services/agent_activity.py` with `get_agent_activity(db, user_id, limit, include_active) -> list[TaskResponse]`. Move `_task_to_response`, `_research_plan_to_response`, `_recent_research_plans`, `_merge_task_lists` out of the route into it. Route becomes a thin wrapper — response shape unchanged, so web + iOS keep working with zero client changes.
2. **Audit every dispatch path** and confirm each one is visible in that feed:
   - `background_task` table: chat handoffs, agent dispatch, code mode ✅ (already in)
   - `research_plan` (origin `david_chat`) ✅ (already in)
   - `research_plan` (origin `sara_internal` / autonomous) — include, tagged so the UI can badge it differently
   - `meeting_research` (cognitive queue), `automation_task`, fleet/host dispatch — verify each either writes a `background_task` row for its lifetime or gets added to the merge. Anything that runs on Sara's behalf and can't be seen here is a bug.
3. **Fix Sara's `get_background_tasks` tool** to call `get_agent_activity()` — the same function the UI uses. Sara can never again see a different world than David.
4. **Fix `research_plan_status` tool:**
   - Prefix match: `WHERE id LIKE :id || '%' AND user_id = :uid` (min 8 chars, error on ambiguity).
   - On not-found: instead of a bare failure, return the user's 5 most recent plans (id, title, status) so the model self-corrects instead of concluding the plan doesn't exist.
5. **Add `status_label` freshness**: `_research_plan_to_response` already emits "Step N of M" — also surface the current step *title* so the iOS pill can show "Researching: Peabody Essex Museum deep-dive".

**Files:** `backend/app/services/agent_activity.py` (new), `backend/app/routes/background_tasks.py`, `backend/app/tools/background_tasks*.py` (wherever `get_background_tasks` lives), `backend/app/tools/research_plan.py`.

---

## Phase 2 — iOS floating task indicator (the actual ask)

**Goal:** the moment Sara dispatches anything, something visibly pops up on iOS, on every screen, without David asking.

1. **`FloatingTaskPill` component** (new, `ios-app/src/components/FloatingTaskPill.tsx`), mounted in `AuthenticatedOverlays.tsx` next to `TimerOverlayContainer` / `FloatingAssistant` so it renders above **all** screens:
   - Hidden when `activeCount === 0` and no recent failure.
   - Active: animated slide/fade in — spinner + count badge (mirrors the web icon) + marquee of the current `status_label`.
   - Failure state: if any task in the last hour is `failed`, pill shows red with an error glyph until tapped (failures must be as loud as activity).
   - Tap → **TaskActivitySheet**: adapt the existing orphaned `ios-app/src/components/BackgroundTasksIndicator.tsx` into a bottom sheet listing Active / Recent tasks with status, step label, elapsed time, error message, and "view result note" for completed ones. Add a Cancel button per active task (wired to Phase 3's cancel endpoint).
2. **Instant appearance on dispatch** (no 10–60s polling gap): after every chat turn completes, the chat service calls `backgroundTaskService.fetchTasks()` (hook in `ios-app/src/services/chat.ts` on stream end). Additionally, the backend chat SSE stream already emits `tool_executing` events — when the client sees `create_research_plan` / any dispatch tool execute, optimistically show the pill immediately and reconcile on next fetch.
3. **Live Activity hardening** (lock screen / Dynamic Island when the app is closed):
   - Keep the existing foreground-driven activity in `BackgroundTasksContext`.
   - Wire task start/step/completion to the push-driven Live Activity path (`liveActivityDelivery.ts` + existing push token infra) so the activity starts and updates even when the app is backgrounded. Backend: emit a task-lifecycle push (silent/activity update) on plan start, step transition, completion, and **failure**.
   - ⚠️ Native/widget changes ride the existing EAS dev-client workflow — JS-only pieces (pill, sheet, polling hook) work with the current build; anything touching `targets/widget` or `modules/sara-native` needs a fresh build.
4. **Failure push notification**: a normal-priority push when any agent task ends in `failed`/`stalled` ("Research plan failed after step 2 — LLM lane out of memory"). Silence is what burned us; completed AND failed both notify.

**Files:** `ios-app/src/components/FloatingTaskPill.tsx` (new), `ios-app/src/components/TaskActivitySheet.tsx` (new, from orphaned indicator), `ios-app/src/components/AuthenticatedOverlays.tsx`, `ios-app/src/context/BackgroundTasksContext.tsx`, `ios-app/src/services/chat.ts`, `ios-app/src/services/backgroundTasks.ts`, backend push emit in research executor + background task service.

---

## Phase 3 — Single-flight research: kill concurrency at three layers

**Goal:** two research agents must never hit the bg lane at once; duplicates die at creation; a sick lane pauses work instead of destroying it.

1. **Create-time guard (kills the duplicate storm).** In `CreateResearchPlanTool.execute`:
   - Query for any plan `status IN ('draft','running','stuck')` for this user.
   - If one exists → **refuse creation**. Return the active plan's full id, title, status, and step progress: *"A research plan is already running: 'Salem MA historical guide' — step 3/6. Not starting a duplicate. Say 'cancel it and restart' to replace it."*
   - This alone would have prevented the entire incident: Sara's 2nd and 3rd handoffs would have answered David's "is it running" question truthfully.
2. **Explicit kill path.** New `CancelResearchPlanTool` + `POST /api/research-plans/{id}/cancel`:
   - Store the Celery task id on the `research_plan` row at dispatch (`celery_task_id` column, migration).
   - Cancel = `revoke(terminate=True)` + status `cancelled`. Executor's external-pause check (it already reloads the plan each step) also honors `cancelled`.
   - Replace-flow: cancel old → create new. Never both.
3. **Execution-level serialization (belt and braces).**
   - `docker-compose.yml` + `docker-compose.dev.yml`: `david_priority` worker `--concurrency=2` → `--concurrency=1`. (Verified: only `run_research_plan` routes to this queue, so nothing else is starved; queued plans wait their turn instead of running in parallel.)
   - Redis lock in the executor (`research_executor_lock:{user}` with TTL + heartbeat) so even a misrouted or second worker can't double-run. Second acquirer re-queues itself with a delay rather than executing.
4. **507/5xx circuit breaker in the executor** (stop terminating tasks because the lane hiccuped):
   - Per-LLM-call retry: 3 attempts, backoff 30s / 2m / 5m on any 5xx.
   - If a step still fails with 507/5xx after retries → set plan status **`stalled`** (not failed), stop consuming steps, and schedule one resume attempt via Celery countdown (e.g. 15 min). Never fall through and instant-fail the remaining steps — plan 3 burned 6 steps in 1.3 seconds.
   - On resume, previously `complete` steps are skipped (already supported).
5. **Honest terminal status.** At end of the step loop:
   - All steps complete → `complete`.
   - Some complete → `partial` (findings synthesized from what exists).
   - None complete → `failed`, `error_log` populated with the last real exception (per the tool-exception-logging rule).
   - Synthesis failure is no longer swallowed silently: log + mark `partial`, and the Phase 2 failure push fires for `failed`/`stalled`.

**Files:** `backend/app/tools/research_plan.py`, `backend/app/services/research/executor.py`, `backend/app/tasks/research.py`, new migration (add `celery_task_id`, allow `cancelled`/`stalled`/`partial` statuses), `docker-compose.yml`, `docker-compose.dev.yml`, new route in `backend/app/routes/` (or extend background_tasks router).

---

## Phase 4 — Verification (repro the incident, watch it behave)

1. **Duplicate kill test:** dispatch a research plan, immediately ask Sara to dispatch the same thing again → tool refuses, cites the running plan id + step. `research_plan` table shows exactly one active row.
2. **Visibility test (iOS):** dispatch from chat → floating pill appears within ~2s on the chat screen, persists while navigating to Fitness/Notes/etc., sheet shows "Step 1 of 6" with the step title. Web badge shows the same count (contract parity).
3. **507 test:** point `research_llm_url` at a mock returning 507 (or stop the Mac lane) mid-plan → step retries with backoff, plan goes `stalled` (not `complete`), pill turns red, failure/stall push arrives on the phone, `error_log` has the real HTTPStatusError.
4. **Status-tool test:** while a plan runs, ask Sara "is it running" → `get_background_tasks` now lists it; ask with a truncated id → prefix match resolves it.
5. **Cancel test:** cancel from the iOS sheet → Celery task revoked, status `cancelled`, pill disappears, no zombie worker.
6. **Deployed-artifact check** (standing gotcha): after backend rebuild, `docker exec jarvis-backend-1 grep -c agent_activity /app/app/routes/background_tasks.py` before declaring done; iOS native/widget changes verified on a fresh EAS build, JS changes on the dev client.

---

## Sequencing & effort

| Order | Work | Size | Needs |
|---|---|---|---|
| 1 | Phase 3.1 + 3.3 (create-guard, concurrency=1) | Small | Backend rebuild only — **do first, it's the safety fix** |
| 2 | Phase 1 (unified feed + tool fixes) | Medium | Backend rebuild |
| 3 | Phase 2.1–2.2 (pill + sheet + instant fetch) | Medium | JS only, current dev client |
| 4 | Phase 3.2 + 3.4–3.5 (cancel, breaker, honest status, migration) | Medium | Backend rebuild + migration |
| 5 | Phase 2.3–2.4 (push-driven Live Activity, failure push) | Medium | EAS build for native bits |
| 6 | Phase 4 verification pass | Small | — |

**Out of scope:** the Mac Studio lane's 507-under-concurrent-load regression itself (MTPLX 88G uplift follow-up) — this plan makes the system survive a sick lane; fixing the lane's memory behavior is tracked separately.

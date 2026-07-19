# System Audit Fix Plan — July 2026

Source: full-system audit on 2026-07-07 (backend runtime, DB data health, iOS, webapp,
fitness, voice, cognitive pipeline). Every item below was verified against live logs,
live DB state, or code — no speculative findings.

Scope note: the iOS `auth.ts` forgot/reset-password dead code is intentionally
**excluded as a feature** — David does not want a "forgot password" flow. The only
action there is deleting the dead client methods (Phase 4), never implementing the
endpoints.

---

## Phase 1 — Broken, fix first (each actively failing in production)

### 1.1 Importance rescoring: 100% failure every night ⚠️ highest leverage
- **Symptom**: all 8,378 episodes error nightly at 03:00 with
  `can't subtract offset-naive and offset-aware datetimes`; 0 episodes rescored.
  Memory importance decay has not run in an unknown but long time, so retrieval
  ranking is stale.
- **Root cause**: `episode.created_at` / `last_accessed` are
  `timestamp without time zone` (naive), subtracted from
  `datetime.now(timezone.utc)` in `backend/app/services/importance_scorer.py:63`
  and `:93`.
- **Fix**: add a small `_ensure_aware(dt)` helper (naive → `replace(tzinfo=timezone.utc)`)
  and apply in `calculate_recency_factor` and `calculate_frequency_factor`.
- **Same bug, two more sites** (fix in the same pass):
  - `backend/app/services/daily_brief/moment_layer.py` — "Error updating moment layer"
  - session-gap detection in `backend/app/main_simple.py` — "Error detecting session gap"
- **Longer term (optional follow-up)**: migrate `episode.created_at` /
  `last_accessed` to `timestamptz` so the class of bug dies at the schema level.
  (Known systemic gotcha — naive datetimes have bitten multiple features.)
- **Verify**: run the rescore task manually; expect `rescored ≈ 8378, failed = 0`;
  spot-check `importance_last_updated` is fresh.

### 1.2 Multi-step task planner: dead on arrival
- **Symptom**: every planned step fails with
  `InternalToolAgent.__init__() got an unexpected keyword argument 'db'`.
- **Root cause**: `backend/app/services/task_planner.py:54` calls
  `InternalToolAgent(db=…, user_id=…, active_categories=…, max_iterations=…)`
  but the constructor (`internal_tool_agent.py:158`) takes
  `(task_id, mission_id, user_id, categories)`.
- **Fix**: reconcile the call site with the real signature (pass task/mission IDs,
  rename `active_categories` → `categories`; drop `db`/`max_iterations` or add them
  to the constructor if genuinely needed).
- **Verify**: dispatch a multi-step task end-to-end; confirm steps execute and the
  result is delivered.

### 1.3 ACS `update_goal` tool: 500 on every call
- **Symptom**: 12× `POST /api/acs/v2/tools/update_goal → 500`,
  `invalid UUID '0db148a8': length must be between 32..36 characters`.
- **Root cause**: the daemon sees shortened goal IDs (8-char prefix) and echoes them
  back; the route binds them directly into a UUID column.
- **Fix** (both ends, prefer a): 
  a) route resolves 8-char prefixes: `WHERE id::text LIKE :prefix || '%'` with an
     ambiguity guard; b) audit what renders goal IDs into the daemon prompt and give
     it full UUIDs.
- **Verify**: replay the failing call with a short ID; expect 200 and goal updated.

### 1.4 FatSecret food details + recipe IDs: two breaks in one endpoint
- **Symptom A** (8×): `GET /api/fitness/foods/fs-*/details` → psycopg
  `syntax error at or near ":"`.
- **Root cause A**: `backend/app/routes/food_database.py:423` uses
  `:servings_json::jsonb` — the known `::`-cast-vs-param-binding gotcha.
- **Fix A**: `CAST(:servings_json AS jsonb)`.
- **Symptom B** (4×): `GET /api/fitness/foods/recipe-*/details` →
  `invalid input syntax for type uuid: "recipe-…"`.
- **Root cause B**: Phase U.6 recipe search returns `recipe-<uuid>` IDs; the details
  endpoint never learned the prefix.
- **Fix B**: in the details route, detect the `recipe-` prefix, strip it, and serve
  details from the `recipe` table (macros per serving), mirroring whatever shape the
  iOS food detail sheet expects.
- **Verify**: from iOS (or curl with a JWT), open details for an `fs-` food and a
  `recipe-` item; both return 200 with servings/macros.

### 1.5 `home_state_summary` table never created
- **Symptom**: hourly `app.tasks.autonomy.home_state_hourly_summary` fails with
  `relation "home_state_summary" does not exist` — forever — while reporting
  task success (error swallowed into the return dict).
- **Fix**: run `backend/migrations/add_home_state_summary.py` against the live DB.
  Then make the task actually fail (or at least log at ERROR) when the write fails,
  so the next missing table isn't invisible.
- **Verify**: next hourly run inserts a row; `SELECT count(*) FROM home_state_summary`
  grows.

### 1.6 iOS ACS status card permanently blank
- **Symptom**: `ACSStatusCard.tsx:112` and `DailyPlanScreen.tsx:26` poll
  `/api/acs/snapshot` every 30s; backend only serves `/api/acs/v2/*`; the 404 is
  silently caught so the card renders empty forever.
- **Fix**: decide the contract — either add a `/api/acs/v2/snapshot` aggregate
  endpoint (daemon-status + focus + activity in one payload) and point iOS at it,
  or rewrite the card to compose from the existing v2 endpoints. Prefer the single
  snapshot endpoint (one round-trip on a 30s poll).
- **Verify**: card shows live daemon state on device/simulator; no 404s in backend
  logs from these paths.

### 1.7 Voice pipeline disconnected
- **Symptom**: `voice_interaction_log` has 0 rows ever; no Jetson health posts in
  24h; `GET /api/sensory/voice-agent/listening` → connection refused 19×/day.
- **Fix**: this is an ops task, not code: SSH to the Jetson
  (`david@10.185.1.84`, no passwordless sudo) and check the sara-voice service
  state; restart/repair; confirm it points at the current backend URL and auth.
  Separately: if `voice_interaction_log` is supposed to be written by the backend
  voice-event endpoints, trace why the write never happens once events flow again
  (0 rows *ever* suggests the write path may be missing, not just idle).
- **Verify**: wake-word round trip on the Jetson lands a row in
  `voice_interaction_log` and a jetson health heartbeat in backend logs.

---

## Phase 2 — Silent degradation (working-looking, quietly wrong)

### 2.1 Retention cleanup poisons its transaction; embedding backfill starves
- **Symptom**: in `autonomy_retention_cleanup`, a failed step aborts the shared
  transaction (per-step `except` without rollback) → `action_ledger` cleanup fails
  with `InFailedSQLTransactionError`; then the episode-embedding backfill dies with
  `cannot call PreparedStatement.fetch(): the underlying connection is closed`.
  Net effect: 137 episodes with NULL embeddings (112 `fitness_food`; 33 added in
  the last 7 days) are invisible to semantic search and never repaired.
- **Fix**:
  1. `backend/app/tasks/autonomy.py` (~line 1187 onward): `await db.rollback()` in
     every per-step `except`, or run each step in its own transaction/session.
  2. Move `_backfill_episode_embeddings` onto a fresh session (it currently inherits
     the poisoned/closed connection), and make each embed+update its own short
     transaction so one embedding-service timeout doesn't kill the batch.
  3. Bump the embedding call timeout or add one retry — the embeddings service
     (port 8100) times out at 60s occasionally (6× in 48h) and each timeout both
     seeds a NULL row and killed the old backfill.
- **Verify**: run the task manually; `SELECT count(*) FROM episode WHERE embedding
  IS NULL` drops to ~0 and stays there across a week.

### 2.2 "One voice" holes — pushes that bypass the unified pipeline
- **Symptom**: `task_result_delivery.py:358` (`_send_push`) posts raw to the push
  API; called by `agent_dispatch.py:2855` and `background_task_service.py:383`.
  `background_task_service.py:439` has a second raw "fallback" sender. These skip
  dedupe, cooldowns, `notification_log`, the attention queue, and payload lint —
  exactly the layers Phase T built.
- **Fix**: route both through `unified_notification.send_notification` with
  `category="background_task"`, a stable `topic` (task id) for dedupe, and delete
  the raw senders. If a "unified failed" fallback is truly wanted, keep it but log
  loudly and still write `notification_log`.
- **Verify**: complete a background task; the push appears in `notification_log`
  with the right category; no direct exp.host POSTs remain outside
  `unified_notification.py` (grep).

### 2.3 `check_in` vs `checkin` category split
- **Symptom**: `deliberation.py:33` documents the category as `check_in`; every
  cooldown/cap/tunable keys on `checkin` (`unified_notification.py:34,156,1108`,
  `notify.category_limit.*`). A `check_in` notification (1 already in the last 7
  days) bypasses the check-in cap and cooldown entirely.
- **Fix**: normalize at ingestion in `send_notification`
  (`category.lower().replace("_", "").replace("-", "")` → canonical map), AND fix
  the `deliberation.py` docstring/prompt to say `checkin`. Backfill: update the
  stray `check_in` rows in `notification_log` so history queries group correctly.
- **Verify**: send a test notification with `category="check_in"`; confirm it hits
  the checkin cooldown path.

### 2.4 Pattern tables still empty (June audit item, still open)
- **Symptom**: `user_pattern`, `detected_patterns`, `correlation_pattern`,
  `movement_patterns` all at 0 rows — nothing writes to them. Only
  `behavioral_pattern` (46 rows) is alive. The learned-attention story runs on one
  table.
- **Fix — decide, don't drift** (pick one per table):
  a) wire a producer (the consolidation runs at 2PM/9PM are the natural home for
     correlation/movement pattern extraction), or
  b) drop the table and delete its read paths.
  Recommendation: wire `movement_patterns` (location data exists via
  `location_event`/`known_place`) and `correlation_pattern` (health × behavior is
  Sara's strongest data); drop `user_pattern`/`detected_patterns` if nothing reads
  them (verify readers first with grep).
- **Verify**: after one consolidation cycle, chosen tables have rows and something
  downstream (deliberation context, briefs) references them.

---

## Phase 3 — Scheduled follow-through (calendar items, not code-now)

### 3.1 Phase T.3 suppression-layer cutover — due ~July 14
- The legacy limits + divergence logging started 2026-07-07 00:24. After a week of
  parallel logging: review `limit_divergence` entries, then flip
  `notify.legacy_limits` → false if the learned layer's decisions look sane.
- First data point already logged: the old `checkin` hard cap (1/6h) is *more*
  conservative than the learned layer. Watch whether that stays true.
- **Action**: on/after July 14, pull all divergence logs, tabulate
  old-vs-learned decisions, cut over or extend the observation window.

### 3.2 Notification variety — the 85% problem
- 126 of 148 notifications last week were `checkin`. The machinery for richer
  payloads exists and is populated: 7 open `followup_thread`s, 113 people in the
  person graph (growing since Phase D), calendar-prep, email. They almost never
  speak (9 `general`, 1 `email`, 1 `calendar_prep`).
- **Fix direction**: rebalance in `deliberation_prompt.py` / the deliberation
  action-selection so commitment follow-ups, people context ("you haven't talked
  to X since…"), and calendar prep are first-class candidates rather than
  fallbacks; consider a soft per-week floor/ceiling mix instead of checkin-first.
- This is the single biggest "make her feel smarter" lever — zero new
  infrastructure, prompt + selection logic only.
- **Verify**: category mix over the following 2 weeks; target checkin < 50%.

---

## Phase 4 — Dead code cleanup (low risk, do in one sweep)

- **`exercise_history` routes**: `backend/app/routes/fitness.py:5269-5359`
  (`/sessions/{id}/complete` aggregation + `/exercise-history` reader). Table has
  0 rows ever; live path is `workout-session/complete` + `workout_log` (105 rows /
  30d); `progressive_overload.py` already documents the table as dead. Delete the
  routes; drop the table.
- **iOS habits scaffolding**: `FitnessScreen.tsx` — `'habits'` ViewMode,
  `habitStreaks` state, `habitCard/*` styles; `services/fitness.ts:638-651` stubs;
  `HabitLog`/`HabitStreak` types in `types/api.ts`. The backend Habits vertical was
  deleted (Phase U.3); remove the client remnants.
- **iOS `auth.ts` forgot/reset-password methods**: no backend, no UI entry point —
  **delete the methods; do NOT implement the feature** (explicitly unwanted).
- **`notification_service.py` raw `send_push`**: once 2.2 lands, check whether the
  legacy raw sender still has callers (`health_consolidation/runner.py:361`,
  `automation/primitives.py:203` route via `main_simple.send_push_notification_async`
  — verify those go through unified) and delete what's unreachable.

---

## Suggested execution order

| Order | Item | Why first |
|-------|------|-----------|
| 1 | 1.1 importance scorer (+ 2 sibling sites) | Touches memory quality everywhere; trivial fix |
| 2 | 1.2 task planner constructor | One-line-class fix, unblocks planned tasks |
| 3 | 1.5 home_state_summary migration | One command + logging tweak |
| 4 | 1.4 food details (both bugs) | Daily-use fitness feature, small fixes |
| 5 | 1.3 update_goal UUID | Unblocks ACS daemon goal loop |
| 6 | 2.1 retention/backfill transactions | Stops the NULL-embedding bleed |
| 7 | 2.3 category normalization | Small; closes a cap-bypass hole |
| 8 | 2.2 one-voice push routing | Medium; needs a careful pass over senders |
| 9 | 1.6 iOS ACS snapshot endpoint | Needs a small API design decision |
| 10 | 1.7 Jetson voice revival | Ops session on the Jetson |
| 11 | 2.4 pattern tables decision | Needs a wire-or-drop decision per table |
| 12 | Phase 4 dead-code sweep | Anytime; zero risk |
| 13 | 3.1 T.3 cutover | Calendar-gated: ~July 14 |
| 14 | 3.2 notification variety | After T.3 cutover so tuning lands on the new stack |

Items 1–7 are each small enough to fix + verify in a single session; 8–11 are
half-day items; 3.2 is iterative tuning.

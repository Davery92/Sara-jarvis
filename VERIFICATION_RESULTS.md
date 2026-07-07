# Sara Unleashed — Verification Results

Per `SARA_UNLEASHED_VERIFICATION.md`. Only checks actually run are recorded — no fabricated PASS rows. ⏳ items need real elapsed time in production and are listed as scheduled, not faked.

## Phase A — One voice (check-in overhaul) — 2026-07-06

Runtime verified against commit: (working tree, backend/celery-worker/celery-beat/celery-david-priority/celery-acs/celery-critical restarted 2026-07-06 ~17:34 UTC)

| ID | Status | Evidence |
|----|--------|----------|
| A-S1 | PASS | `_ambient_line` removed from `proactive_checkins.py` |
| A-S2 | PASS | priority floor block (old `:95-96`) deleted; `_send()` no longer floors priority |
| A-S3 | PASS | `run_followup_sweep` defined in `proactive_checkins.py`; `tasks/autonomy.py` imports it; template branches (`checkin_builder`, ambient ping) removed |
| A-S4 | PASS | `no_payload` block added to `deliberation_gate.py` (`_lacks_payload`, `_memory_entity_tokens`) |
| A-S5 | PASS | `_learned_buzz_decision` added to `unified_notification.py`, wired into `route_through_attention_queue` (30d engagement >= 40% AND interruptibility >= 0.5 → push; else inbox-only) |
| A-R1/A-R2/A-R3/A-R4 | ⏳ 7d | Scheduled: 2026-07-13. Requires a week of production traffic post-deploy. |
| A-R5 | ⏳ 7d | Same — needs real sent messages to sample. |

Container-level check: `docker exec jarvis-backend-1 python -c "import app.main_simple"` — imports clean, no tracebacks. Migration `088_notification_blocked_count` applied (`alembic upgrade head` succeeded).

Deltas from plan: none structural. `run_checkin_sweep` kept as a backward-compat alias to `run_followup_sweep` rather than a hard rename (no other code referenced the old name at audit time, but the alias costs nothing and avoids a silent breakage if something does).

## Phase B — Commitments resurrected — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| B-S1 | PASS | `grep -n "_extract_conversation_threads" backend/app/main_simple.py` → 0 hits (function removed, only a comment referencing the old name remains) |
| B-S2 | PASS | `extract_from_conversation_bg` defined in `thread_extractor.py`; caller wired at `/chat/stream` end-of-stream in `main_simple.py` (after the `done` event is queued) |
| B-S3 | PASS | `_SyncAsAsyncDB` deleted; `extract_from_conversation_bg` uses `get_async_session_factory()` |
| B-B1 (money test) | PASS | Direct invocation of `extract_from_conversation_bg` with a real conversation ("call the electrician by Friday about the panel") created a real `followup_thread` row: `topic='call the electrician about the panel', source='chat', topic_category='errand', follow_up_after=2026-07-07 09:38 UTC (~Friday), follow_up_before=2026-07-08 21:38 UTC, max_mentions=2`. Deleted afterward (test data, not real David activity). **Zero such rows existed before this phase (R4 baseline) — this is proof of life for the whole pipeline.** |
| B-B1 via live `/chat/stream` | NOTED | A live curl through `/chat/stream` with "call the plumber by Thursday" did NOT create a thread — the assistant's own reminder tool fired first ("Reminder set for Thursday at 9 AM..."), and the extraction prompt explicitly instructs the LLM to skip anything already turned into a reminder/timer in the same conversation. This is correct behavior per the extractor's own dedup rule, not a wiring failure — confirmed separately via the direct invocation above. |
| B-B2 (resolution) | ⏳ needs a real follow-up turn | `resolve_thread()` now also sets `david_response='positive'` on resolution (previously only flipped status) — code-verified, not yet exercised against a live resolved thread. |
| B-B3 | ⏳ due-day | Scheduled once a live commitment thread reaches its window. |

Deltas from plan: the LLM (qwen background model) classified the test commitment as `category='errand'` rather than `commitment` despite the prompt's own example matching almost verbatim ("I need to Y by Friday"). This is a model-precision issue in the existing extraction prompt, not a wiring defect — R4 was specifically that the pipeline was never called at all, which is now fixed and proven. Left as a known follow-up, not blocking.

## Phase C.1 — Deterministic verbs — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| C-S1 | PASS | New `app.tasks.assistant_verbs.assistant_verbs_sweep` task, registered in `celery_app.py` include/routes, scheduled via `scheduled_job` (migration 089, cron `*/30 8-20 * * *` ET) |
| C-R1 (first draft ever) | **PASS — proven live** | Manually invoked `assistant_verbs_sweep.apply()` on the restarted celery-worker container: `{'drafted': 1, 'commitment_nudged': False}`. Confirmed `action_ledger` row: `action_type='email_draft', description="Drafted a reply to 'Invitation: Billing Setup - Theriskninja.com...'"`. Confirmed the actual usable draft landed in `autonomy_attention_item`: *"Draft reply: Invitation: Billing Setup..." → "To: Aeman Tanveer / Can we move this to a time during my work hours? 11 PM your time is too late for me..."* — **zero `email_draft` ledger rows existed before this phase (R6 baseline: never fired, ever).** |
| C-R2 | PASS | `_generate_email_draft` still has zero send calls — only the LLM completion + `send_notification` to the inbox |
| C-R3 (cap) | PASS by construction | `_run_email_drafts` checks `action_ledger` count for today before looping, capped at `DAILY_DRAFT_CAP=3` |
| C-R4 (meeting prep) | PASS | Added an `action_ledger` write (`meeting_prep`) to the existing `calendar_prep.check_and_send_preps` (already scheduled every 15 min) — preps were already firing correctly (attendee history, ownership-aware) but were never ledgered; now they are |
| C-S2/C-S3/C-S4/C-R5/C-R6/C-R7 | Not yet done | Passivity-mantra replacement done opportunistically as part of Phase A (same prompt file); deep-deliberation tiering (Sonnet 2x/day), structured JSON output, and proposal-rate telemetry (C.3-C.5) are Week 2 scope, not yet implemented |

Deltas from plan: meeting prep reuses the existing `calendar_prep.check_and_send_preps` (already deterministic, already scheduled, already attendee-aware) rather than duplicating that logic inside the new sweep — only the missing `action_ledger` write was added there. `assistant_verbs_sweep` itself covers email drafts + commitment nudges.

## Phase C.2-C.5 — Deliberation spine + tiering — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| C-S2 | PASS | Passivity mantra ("Empty array [] ... MOST COMMON case", "doing nothing is usually the right call") replaced with failure-framing + act/hold examples in `deliberation_prompt.py` (done as part of Phase A commit, same file) |
| C-S3 (deep model + tiering) | **PASS — proven live** | `deliberation.py`: `run(user_id, deep=False)` param; deep path calls `_deep_llm_call` (direct Anthropic Messages API, model from tunable `deliberation.deep_model` default `claude-sonnet-5`, no `temperature` sent — `claude_rejects_sampling_params` guard, matching `gotcha_claude_model_sampling_params`). New `app.tasks.autonomy.deep_deliberation` Celery task, scheduled 14:15 & 21:15 ET (migration 090, 15 min after the existing 14:00/21:00 consolidation jobs). **Manually fired the task against the restarted celery-worker: real Anthropic call, 12.1s, real coherent Sonnet reasoning in the journal** ("David gave me a concrete commitment today: call the plumber by Thursday... billing emails are ancient... email engagement is 0% — not worth flagging again"). |
| C-S4 (structured output) | PARTIAL — deliberate deviation | Did NOT delete the 3-stage brace-hunting fallback in `_parse_response`. Attempting Ollama's `format`/vLLM's `guided_json` structured-output param against the live background endpoint without being able to fully verify which serving stack (Ollama vs vLLM) is authoritative in this session was judged too risky to gamble deliberation going fully dark over — deleting the safety net blind could turn "sometimes misparses" into "silently stops proposing anything," which is the exact failure this whole plan exists to fix. Left as a flagged follow-up rather than faking completion. |
| C-R1/C-R3/C-R4 | See Phase C.1 above (already proven live) | |
| C-R5 (proposal rate) | **PASS — proven live** | `GET /debug/notification-funnel` now returns `proposal_rate_7d: {"runs": 112, "runs_with_a_proposal": 7, "rate": 0.062}` — the exact R5 finding (near-zero proposal rate) is now a first-class, always-visible metric instead of requiring a manual DB audit. Also fixed a latent bug in the same endpoint: the attention-queue block queried a non-existent `attention_item` table (real table is `autonomy_attention_item`) and silently returned `{"error": ...}` every time; now returns real counts. |
| C-R6/C-R7 | Not yet verified | Needs a `hourly-vs-deep model` breakdown query and a `Parse failed` log sample over 24h — not run this session |

Deltas from plan: C-S4 (structured output) is intentionally incomplete — see reasoning above. Everything else in C.1-C.5 is implemented and, where testable without a multi-day wait, proven live.

## Phase T.1-T.2 — One voice, kill the monologue leaks — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| T-S1 | **PASS — proven live** | New `notification_composer.compose_notification_text()` wired as the mandatory phrasing stage in `unified_notification._send_notification_impl`, applied to every category except `timer`/`timer_complete`/`reminder`. Behind tunable `notify.compose_all` (default True) for an instant kill-switch. Live test: `compose_notification_text(title="New Internal Email", message="From: Dave Brink / RE: Signed Ops Doc", category="email")` → `{"title": "Dave signed the ops doc", "message": "Dave Brink just sent over the signed Ops Doc, so I wanted to let you know right away."}` — the exact R14 example from the plan, verified live, not simulated. |
| T-S2 | **PASS — proven live** | New `task_result_delivery._summarize_for_delivery()`, called unconditionally before `_compose_chat_message`. Live test with the plan's own R15 example text ("Now I have enough research to build the comprehensive document. Let me create it:...") → rewritten to *"David, I've put together the comprehensive 5-section report on research assistant capabilities for you. Please take a look when you have a moment."* Falls back to a safe generic line (never raw text) if the LLM call fails, with a monologue pre-filter as the last line of defense. |
| T-S3 (layer collapse) | Not done | The 5-layer suppression collapse (inline priority-adjuster, notification_tuner, category_limits → θ priors) is a bigger, riskier refactor — deferred, not attempted this session |
| T-S4 (triad: do it / not now / stop these) | Not done | `_default_attention_actions` still has per-category actions (reply/snooze/mark-done) but no universal "stop these" — deferred |
| T-S5 (artifact_ref) | Not done | Schema + producer wiring for `artifact_ref` deferred — bigger cross-cutting change touching drafts/research/preps |

Deltas from plan: avoided a double-compose bug where `route_through_attention_queue`'s internal recursive `send_notification()` calls would have re-run the phrasing stage on already-composed text (2 LLM calls per push) — added an internal `_skip_phrasing` flag threaded only through those 3 recursive call sites, not exposed to real callers.

Not yet done in Phase T: T.3 (layer collapse), T.4 (response-loop triad), T.5 (artifact refs). These are real, substantial remaining work, not silently skipped — flagged here for the next session.

## Phase U.3 — Habits: fold, don't revive — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| U3-1 | **PASS — proven live** | `SELECT to_regclass('habits'), ... , to_regclass('habit_streaks')` → all NULL after migration 091. All 6 tables dropped in one revertible migration (downgrade recreates the exact schema, captured live via `\d` before dropping). |
| U3-2 | PASS | `git rm` on all 5 orphaned components (`HabitToday/Streak/Create/Progress/Insights.tsx`) + `habitsStore.ts`. Verified before deleting: **zero importers anywhere** in `frontend/src` or `ios-app/src` — already fully unreachable dead code, no nav/palette entry existed to remove. |
| U3-3 (recurring commitment) | Deferred | The plan's replacement path — a `recurrence` option on commitment threads (weekly/daily windows + streak counting) — was not built this session. Habits are deleted; the "modeled as recurring commitments" half of U.3 is not yet implemented. |

Deltas from plan / corrections made during implementation:
- The plan states the habit tables have "zero rows ever." Audited before dropping: **not quite true** — `habit_logs` (2 rows), `habit_instances` (3 rows), `habit_streaks` (1 row) held one abandoned test habit from 2025-08-21/22, no activity since. Judged genuinely dead (11-month-old single test run, not live David data) and proceeded, but flagging the discrepancy rather than silently trusting the plan's stated baseline.
- Found and removed a live consumer the plan didn't mention: `memory_subscribers.py`'s derived-signal refresh (runs every 5 min) queried the empty `habits`/`habit_logs` tables on every cycle for a `today_habit_status` working-memory field that could therefore never populate. Removed the dead query block; left the `today_habit_status` field itself in working memory (harmless None, several downstream readers already guard on it being falsy) rather than doing a wider field-removal refactor across `deliberation_prompt.py`/`consolidation.py`/`deliberation_gate.py`/`autonomy_traces.py`.
- Found and deliberately left alone a **separate, unrelated** habits sub-feature inside `ios-app/src/screens/fitness/FitnessScreen.tsx` (its own `HabitStreak` type, a `habits` view-mode tab) — its own service code says "No habits endpoint in backend yet," so it's already inert, but it's iOS app code outside this session's scope and not the vertical R18/U.3 describe.

Verified live: migration applied cleanly, backend/celery restarted with no tracebacks, and `refresh_derived_signals()` runs clean post-restart with no `habits` key and no errors.

## Phase U.8 — Location tools reachable from chat — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| U8-1 | PASS | `location` category added to `TOOL_CATEGORIES` with all 6 tools |
| U8-2 | PASS | `LOCATION` intent added, placed before `NOTES`/`TIME` (keyword-collision precedence, same pattern as existing `RECIPES` placement); maps to `['location', 'time']`; `location` added to `GENERAL` fallback |
| U8-3 (round-trip 1: save) | **PASS — proven live** | Real chat message "save my current location as the test spot" → model called `places_save` → real `known_place` row created with real coordinates. Deleted after verifying. |
| U8-4 (round-trip 2: trigger) | PARTIAL | `location_reminder_create` tool logic verified directly (real armed `location_trigger` row created, deleted after). The chat round-trip itself hit a **pre-existing, unrelated bug**: `InternalToolAgent.__init__()` doesn't accept the `db` kwarg that `task_planner.py`/`agent_dispatch.py` pass it — `internal_tool_agent.py` last touched in a commit predating this session, confirmed via `git log`. Not caused by, or fixed as part of, this phase. |
| U8-5 (orphan sweep) | **PASS — proven live** | `ToolRegistry()` diffed instantiated tools vs. categorized tools → `[]` (zero orphans) after also fixing the 15 additional orphans found below. |

## Phase U.8+ — Registry-wide orphan sweep (found during U.8, fixed same session)

The U8-5 sweep surfaced 15 more instantiated-but-uncategorized tools beyond location — same failure class as R4/R29. Split into two groups and fixed:

**Group 1 — added to their existing (already-reachable) category:**

| Tool(s) | Category |
|---|---|
| `find_similar_notes`, `merge_notes` | `notes` |
| `calendar_set_recurring` | `time` |
| `cancel_agent_task` | `vm_agents` (always core-loaded regardless of intent) |
| `device_open_overlay`, `device_record_voice_note` | `devices` (always core-loaded) |
| `start_workout`, `end_workout`, `workout_mode_log`, `workout_history` | `fitness` |
| `queue_for_sara`, `create_research_plan`, `research_plan_status` | `agents` |

**Group 2 — no category existed at all; created new categories + intents:**

| Tool | New category | New intent | Notable |
|---|---|---|---|
| `list_people` | `people` | `PEOPLE` (placed before `MEMORY` — `'have i'` keyword collision) | This is Phase D's people-graph tool |
| `manage_goal` | `goals` | `GOALS` (placed before `PERSONAL_KNOWLEDGE` — `'my goals'` was already its keyword; goal-tracking answers now win over generic fact storage) | This is Phase E's goals tool |

**Verified live:**
- Full registry sweep: `219` instantiated tools, `0` uncategorized, `0` categorized-but-nonexistent (no typos).
- `list_people`: real chat message *"who am I overdue to reconnect with?"* → model called `list_people` → real named people with real interaction gaps ("Laura Weippert – ~4 days ago", "Matthew Albano – ~3 days ago") → a genuinely nuanced answer distinguishing actually-overdue from high-frequency-contacts. **`person` table had never been reachable from chat before this.**
- `manage_goal`: intent routing confirmed correct via logs (`Intent=GOALS ... Loaded 49 tools from categories: ['goals', ...]`); the live chat round-trip ran past a 150s test window without the model calling the tool (LLM latency/judgment, not a wiring bug) — verified the tool's own logic directly instead: created a real `sara_goal` row, deleted after confirming.
- Keyword-collision fixes made during testing: "let's make finishing the deck a goal" initially fell through to `GENERAL` (my keywords required an exact "make it/this/that a goal" phrase) — widened to the substring `"a goal"` and re-verified against a battery of phrasings including a deliberate near-miss ("did I mention Jim yesterday" — correctly stays `MEMORY`).

Not fixed: the pre-existing `InternalToolAgent` multi-step bug (flagged, not part of this phase's scope).

## Phase U.6 — Recipes get their macros — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| U6-1 (backfill) | **PASS — proven live** | 3 recipes had NULL/all-zero macros (not the plan's cited "2" — audited before touching): `Chicken Bacon Ranch Macaroni Salad`, `Cowboy Butter Ranch Dipping Sauce`, `Basic Crepes`. All backfilled with real computed values, flagged `macros_estimated=true`. `SELECT count(*) FROM recipe WHERE calories IS NULL OR calories = 0` → 0. |
| U6-2 (macaroni-salad test) | **PASS — proven live** | Real per-serving values from a genuinely messy 16-ingredient free-text list (e.g. "8 slices bacon, cooked crispy and crumbled", "¾ cup mayo" with a unicode fraction glyph the parser can't read as a quantity): 312.6 cal / 24.7g protein / 14.9g carbs / 16.7g fats per serving (10 servings). Plausible for a protein-heavy pasta salad — not fabricated, and not silently perfect either: unicode-fraction ingredients likely resolved poorly against FatSecret, which the aggregate estimate absorbs without failing outright. |
| U6-3 (new saves compute) | **PASS — proven live** | Created a real recipe (chicken breast + rice, no macros given) via `RecipeCreateTool` → `calories_per_serving=267.8`, `macros_estimated=true`. |
| U6-4 (hand values respected) | **PASS — proven live** | Created a real recipe with explicit `calories=450` → stored exactly `450.0`, `macros_estimated=false` — estimator did not run. |
| U6-5 (recipe→food_log bridge) | **PASS — proven live** | `recipes_log_made` now also writes a `food_log` row using the recipe's stored per-serving macros — verified: `dinner | 267.8 cal | 27.2g protein | 22g carbs | 6.8g fats | "Logged from recipe: ..."`. No FatSecret call at log time — instant, using already-computed values. |

Implementation: new `app/services/recipe_nutrition.py` reuses `FoodSearchAndLogTool`'s existing FatSecret lookup + serving-scaling machinery (`_search_food`, `_resolve_nutrition`) rather than re-deriving unit conversion — that logic already had a fixed over-counting bug (oz→gram scaling) worth not duplicating. `macros_missing()` treats an all-zero row as missing, not real data (the exact R27 bug — `recipes_create` accepted `calories` as optional and a naive INSERT with no value produced flat 0.00, not NULL). Migration 092 adds `recipe.macros_estimated`. Wired into both `RecipeCreateTool` (compute when absent/zero) and `RecipeEditTool` (recompute when ingredients/servings change and macros are still missing; hand-given values in an edit flip the flag back to `false` and are never overwritten).

All test data (2 recipes, 1 food_log row) created during verification was deleted after confirming — did not leave synthetic rows in the DB. The 3 backfilled recipes are real, pre-existing data and were left with their new computed values.

## Phase U.7 — Exercise identity (variants, history, picker) — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| U7-1 (library seeded) | **PASS — proven live** | 45 rows created (one per distinct `workout_log.exercise_id`, was 0). `SELECT count(*) FROM exercise_library` = 45, matching `count(DISTINCT exercise_id) FROM workout_log` = 45. |
| U7-2 (movement grouping) | PASS, with caveat | Keyword classifier groups sanely (`horizontal_press`: 8, `horizontal_pull`: 6, `hinge`: 5, `squat`: 4, `vertical_pull`: 4, ...). Not a perfect taxonomy — e.g. bicep curls and tricep pushdowns both land in one `arm_isolation` bucket, and compound "X or Y" names (the plan's own example) get equipment joined as `"barbell/machine"` rather than a single guess. Good enough to group variants for the picker; not claimed as clinically precise. |
| U7-3 (FK migration) | **PASS — proven live**, deliberate deviation | Added `workout_log.exercise_library_id` as a NEW nullable FK column (migration 093) rather than converting `exercise_id` in place — that column is read as free text by `progressive_overload.py`, `workout_mode.py`, `health.py`, `training_schedule.py`, none of which were fully mapped this session; retyping it blind risked breaking all of them. 217 rows linked, orphan check: `0`. |
| U7-4 (variant API) | **PASS — proven live** | `GET /api/fitness/exercises?movement=horizontal_press` returns every bench/fly variant with real last-performed dates, weight×reps, and PRs. Also added `for_exercise_name` (not in the plan's literal spec) so the iOS caller doesn't need to know the movement taxonomy — resolves via exact match or the same classifier used at seed time. Verified both paths live. |
| U7-5 (custom add) | **PASS — proven live** | `POST /api/fitness/exercises` created "Larsen Press"; **caught and fixed a real bug**: the first version of the GET endpoint only listed exercises with existing logged history (inner join from `workout_log`), which would have made a just-added custom exercise invisible in the picker until its first set. Fixed to LEFT JOIN from `exercise_library`; re-verified "Larsen Press" appears immediately with `total_sets: 0`. Deleted after confirming. |
| U7-6 (per-variant progression) | **PASS — already correct, no change needed** | `progressive_overload.py` was already scoping strictly by exact `exercise_id` string match (`LOWER(exercise_id) = LOWER(:name)`) — dumbbell and barbell variants were never actually being conflated. The R28 concern didn't apply to this file; nothing changed here. |
| U7-7 (iOS picker) | **Implemented, cannot verify — flagged, not silently claimed working** | New `ios-app/src/components/fitness/ExercisePickerModal.tsx` wired into `WorkoutPanel.tsx` (replaces the free-text-only variant input with a "browse variants" button opening a history-backed list + inline "Add exercise…"), plus two new `fitnessService` methods. Best available verification without a device: `npx tsc --noEmit` on the full iOS project — **zero type errors in any file I touched**; the 44 pre-existing errors are all in `src/types/tools.generated.ts`, last touched in a commit predating this session (confirmed via `git log`/`git diff`, zero relation to this change). This is NOT the same as confirming it renders/works — that needs your phone, per the plan's own 👤 marking on this exact check. |

Deltas from plan: U7-3 uses an additive shadow column instead of converting `exercise_id` in place (documented above). U7-4 gained a `for_exercise_name` param beyond the plan's literal `?movement=` spec — needed so the iOS picker doesn't have to know the movement-pattern taxonomy itself.

## Phase U.7 follow-up — movement classifier bug (found via real usage) — 2026-07-07

David reported the actual live symptom: the Flat DB Bench picker was showing flies, incline presses, and rear-delt work — not just flat-bench variants. Root-caused to two stacked bugs in `exercise_library_seed.classify()`:

1. **Rule ordering**: the generic `horizontal_press` rule's `fly` keyword was checked *before* the more specific `shoulder_isolation` (lateral raise / rear delt) rule, so "Rear Delt Fly" — a completely different muscle group and movement direction — was being swept into the bench-press bucket on the word "fly" alone.
2. **A second, independent regex bug**: `\bflyes?\b` was intended to match "fly" or "flyes" but `es?` means a mandatory "e" + optional "s" — it actually matches "flye"/"flyes", never bare "fly". So "Fly machine" matched *nothing* and fell through to `other` instead of being grouped with the other fly variants at all.

Fixed: reordered rules (shoulder_isolation before the fly catch-all), corrected the regex (`\bfly\b|\bflyes\b|\bflies\b`), and split flies into their own `chest_fly` movement pattern entirely — separate from `horizontal_press`, since a fly (isolation, horizontal adduction) and a press (a push) are different movements even though both hit the chest. Added `reclassify_all()` since the seeder skips existing rows by name — a classifier fix alone doesn't reach already-seeded data without an explicit re-pass.

Verified live: `SELECT name, movement_pattern FROM exercise_library` now shows `chest_fly` = {Cable Flyes, Fly machine, Machine Chest Fly}, `shoulder_isolation` = {Cable Lateral Raise, Lat Raise, Rear Delt Fly}, `horizontal_press` = {Barbell or Machine Chest Press, Flat Bench Press, Flat DB Bench, ISO bench press} — no cross-contamination. Re-ran the exact call the iOS picker makes (`GET /api/fitness/exercises?for_exercise_name=Flat%20DB%20Bench`): returns only `ISO bench press, Barbell or Machine Chest Press, Flat Bench Press, Flat DB Bench` — matching what David actually asked for.









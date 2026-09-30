# Two-A-Day AM Sessions (Top/Backoff Sets) + Food Logging Repeats — Plan

Date: 2026-09-18 (Fri, program week 1 just finished)
Status: PLAN ONLY — nothing implemented. Approve per part.
Source of truth for the program: `docs/fitness/TWO_A_DAY_POWERBUILDING_RECOMP_2026_09_14.md`.
Previous cutover: commit `aab62d5f` + `docs/plans/HRV_PIPELINE_AND_TWO_A_DAY_PROGRAM_2026_09_14.md` Part B.
Previous food plan: `docs/plans/SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16.md` (Stage A partly shipped, Stage B not started).

---

## 0. What actually happened this week (evidence)

Pulled from `active_workout_session` / `workout_log` for 2026-09-14..17:

| Day | Session | What the plan said | What got logged |
|---|---|---|---|
| Mon | AM NewTech | 270×2 top, 3×4–6 @230 | **no AM session at all** (program started at the PM session) |
| Tue | AM Deadlift | 315×1–3 top, 2×3–5 @275 | 3 × (225×5) — every set identical |
| Wed | AM Smith OHP | 145×2–4 top, 3×4–6 @130 | 3 × (135×6) — 4 sets prescribed, 3 logged, all identical |
| Thu | AM Squat | 225×2–4 top, 3×4–6 @200 | 4 × (225×2) — every set identical, RPE 7 |
| Thu | 13:05 | PM Legs | a **second "Thu AM — Squat" session was started and abandoned 4 s later**, then PM was started |

All 55 sets this week are `set_kind='working'` with identical weight/reps per exercise and RPE 7. No warm-ups were logged anywhere.

### Why — the causes are all in code, not in the data

1. **The AM prescription is not structured.** The importer only had `sets` / `reps` / `notes`, so each AM lift is one exercise `sets: 4, reps: "2-6"` and the 8-week top/backoff table is a text blob in `notes` (`backend/scripts/plans/two_a_day_2026_09_14.json`, `postprocess_two_a_day_2026_09_14.py`). Only `workout_prescription.py` (used by the brief, chat summary and `workout_suggest`) parses it back. **The workout engine never reads it.**

2. **Snapshot builder ignores the plan.** `workout_command_service._create_session()` (`backend/app/services/workout_command_service.py:357-440`) builds one flat entry per exercise: a single `suggested_weight` from `progressive_overload.compute_progression()` and the combined rep range. The Thursday snapshot literally was: `Back Squat, sets 4, reps "2-6", approved_weight 225, calculated_suggestion 235, progression_note "Last session felt easy (RPE 7.0). Adding 10lbs."` — derived from a "Squat" variant last logged **2025-11-10** (`fetch_last_session`, `progressive_overload.py:36`). Nothing in the snapshot says set 1 is a top set at 225×2–4 and sets 2–4 are 200×4–6.

3. **Phone prefill is per-exercise, not per-set.** `WorkoutPanel.tsx:64-72` seeds `customWeight = suggested_weight` and `customReps = low end of "2-6"` once per exercise and never changes them between sets. That is exactly how 4 × 225×2 gets logged: tap Log Set four times. The Watch does the same from `approvedWeight`/`targetReps` (`ActiveWorkoutView.swift:230-237`).

4. **Server-side defaults are wrong for a top/backoff scheme.** `_apply_log_set` (`workout_command_service.py:759-766`) defaults `weight = approved_weight` and `reps = low+1` for every set when the client omits them.

5. **No warm-up path from the phone.** Backend and `WorkoutModeContext` support `set_kind: 'warmup'`, but `LogSetRequest` (`routes/fitness.py:5680`) has no `set_kind` and `WorkoutPanel` has no warm-up toggle. The ramp-up lines in notes ("45x8, 135x5, 185x3, 205x1") are unreachable.

6. **Deload will double-apply in week 4.** `_create_session` halves sets and `compute_progression` multiplies weight by 0.6 when `get_deload_state().is_deload` is true. The Deload phase has `deload_week=1`, and the program *already* specifies exact deload loads (230×4 + 210×5×2). Left alone, week 4 would prescribe ~0.6 × (whatever) with 2 sets, ignoring the table.

7. **Week indexing has two conventions.** The snapshot stores `week_of_phase` (phase-relative, `progressive_overload.get_deload_state`), while the loading table is keyed by program week (`workout_prescription.program_week`). Build 2 starts 2026-10-12 as phase-week 1 but program-week 5. Any engine change must key on program week.

8. **"Which session is next" is matched by title on the phone.** `FitnessScreen.tsx:232-252` decides AM vs PM by comparing template names against titles from `GET /api/fitness/workouts` (which ignores its `start_date`/`end_date` params and returns the last 200 joined rows). The Thursday 13:05 abandoned AM start is consistent with the hero still pointing at AM after it was completed. Not fully proven; the fix below removes the guesswork regardless.

9. **Exercise identity drift.** Logged names this week: `Squat` (variant on "Back Squat"), `m-torture Incline`, `Cable Flyes`, `M-Torture Wide Flat`, `ISO-Lat Row`, `Chest-Supported T-Bar`, `Cable or Machine Triceps Pushdown`, `M-Torture`. Variants are fine (that's the design), but progression for a plan-driven AM lift should not be keyed off whichever variant string was typed. Plan-driven lifts take their load from the plan; history is informational.

---

## Part A — AM sessions: structured top set / backoff prescription

### A1. Data: a per-set plan on the template exercise (additive, no table change)

`fitness_template.exercises` is a JSON list; add an optional key per exercise:

```json
"set_plan": {
  "kind": "top_backoff",
  "warmup": [{"weight": 45, "reps": 8}, {"weight": 135, "reps": 5}, {"weight": 185, "reps": 3}, {"weight": 205, "reps": 1}],
  "weeks": {
    "1": {"top": {"weight": 225, "reps": "2-4", "rpe_cap": 8}, "backoff": {"weight": 200, "reps": "4-6", "sets": 3, "rir": "1-2"}},
    "2": {"top": {"weight": 230, "reps": "2-4", "rpe_cap": 8}, "backoff": {"weight": 205, "reps": "4-6", "sets": 3}},
    "3": {"top": {"weight": 235, "reps": "2-4", "rpe_cap": 8}, "backoff": {"weight": 210, "reps": "4-6", "sets": 3}},
    "4": {"label": "DELOAD", "top": {"weight": 205, "reps": "3"}, "backoff": {"weight": 180, "reps": "5", "sets": 2}},
    "5": {"top": {"weight": 235, "reps": "2-4"}, "backoff": {"weight": 210, "reps": "4-6", "sets": 3}},
    "6": {"top": {"weight": 240, "reps": "2-4"}, "backoff": {"weight": 215, "reps": "4-6", "sets": 3}},
    "7": {"top": {"weight": 245, "reps": "1-3"}, "backoff": {"weight": 220, "reps": "4-6", "sets": 3}},
    "8": {"label": "REP PR", "top": {"weight": 230, "reps": "4+"}, "backoff": {"weight": 205, "reps": "4-6", "sets": 3}}
  },
  "advance_rule": "clean_top_set_rpe_le_8"
}
```

- Week keys are **program weeks** (1–8), matching the spec's tables and `workout_prescription.program_week()`.
- `sets` on the exercise stays = 1 + backoff sets so every existing reader (`target_sets_for`, totals, Watch) keeps working.
- `notes` stays as human text; the `TOP:`/`BACKOFF:` lines can remain for now (parser fallback) and be dropped once A2 lands.
- **Migration script** `backend/scripts/plans/add_set_plan_two_a_day.py`: for the 4 AM lifts × 4 phases (16 template rows) build `set_plan` from the same numbers as `two_a_day_2026_09_14.json` (hand-written dict, exact numbers, no LLM). Idempotent: skips exercises that already carry `set_plan`. Verify with a SELECT that every AM template in every phase of the active program has `set_plan.weeks["1".."8"]`.
- `plan_importer` (`app/services/plan_importer.py`) accepts `set_plan` pass-through so future imports can carry it; `template_tools.py` / `PATCH /templates/{id}/exercises/{eid}` must not strip it.

### A2. Engine: resolve the plan into per-set targets at session start

In `_create_session` (`workout_command_service.py`), after loading specs:

- Compute `week = workout_prescription.program_week(db, user_id, local_today())` once per session and store it in the snapshot as `program_week` (keep `week_of_phase` for display).
- New helper `app/services/set_plan.py`:
  - `resolve_set_plan(spec, week, last_top_set) -> {"sets": [...], "effective_week": int, "held": bool, "note": str}` producing an ordered list like
    `[{"index": 0, "kind": "warmup", "weight": 45, "reps": "8"}, …, {"index": 4, "kind": "top", "weight": 225, "reps": "2-4", "rpe_cap": 8}, {"index": 5, "kind": "backoff", "weight": 200, "reps": "4-6"}, …]`
  - **Advance rule** (spec §6: "advance only when the top set is clean and ≤ RPE 8, else repeat the previous week"): look up the last logged `set_kind='working'` set with `flags.role='top'` for this lift (see A5). If it exists and had `rpe > 8` or reps below the low end of that week's range, use the previous week's row and set `held=true`, note "Holding week N loads — last top set was RPE 9". First session of a lift uses the planned week.
  - Deload: when the week row carries `label: DELOAD` the loads are authoritative — **skip** the halving in `_create_session` and the ×0.6 in `compute_progression` for exercises with a `set_plan`. Exercises without a plan (all PM work) keep the existing deload behaviour.
- Snapshot exercise gains: `set_plan_resolved` (the list above), `program_week`, `effective_week`, `held`. For plan-driven exercises: `approved_weight` = top-set weight, `calculated_suggestion` = same (no competing +10 proposal), `progression_note` = the plan note ("Week 1: top 225×2–4, then 3×4–6 @200"). `last_session` still attached for context.
- `sets` = number of working entries (top + backoff). Warm-ups do **not** count toward `target_sets` (they already don't: `counts_toward_target=false`).
- PM exercises are untouched by this part (double progression stays on `progressive_overload`).

### A3. Projection + wire contract (4 copies)

`_exercise_view` (`workout_command_service.py:2276`) adds:

- `set_plan`: the resolved list;
- `next_set`: the entry for the set about to be performed = `set_plan[completed_warmups + completed_working]` keyed by kind (warm-ups consumed first, then working); `null` when the exercise is done;
- `effective_week`, `held`, `plan_note`.

Bump `SCHEMA_VERSION`. Update all four contract copies and run `ios-app/scripts/check-workout-contract-parity.mjs`:
`workout_command_service.py` → `ios-app/src/context/WorkoutModeContext.tsx` types → `ios-app/targets/watch/WorkoutWireModels.swift` → `frontend/src/types` (whichever file the parity script lists). Memory gotcha: "Workout wire contract x4".

### A4. Phone: per-set prefill and a real top/backoff UI

`ios-app/src/components/fitness/WorkoutPanel.tsx`:

- Prefill from `currentExercise.next_set` and re-run the prefill effect whenever `next_set.index` changes (today it only runs on exercise change — that is the root of 4 × 225×2).
- Header line becomes kind-aware: `WARM-UP 2 of 4 · 135 × 5`, `TOP SET · 225 × 2–4 · cap RPE 8`, `BACKOFF 1 of 3 · 200 × 4–6 · 1–2 RIR`. Keep the existing `SET x OF y` bar for working sets only.
- Show the whole resolved list for the current exercise as a compact table (weight/reps/kind, ticked as logged) so David can see the session shape at the rack. This table replaces the 💡 notes dump for plan-driven lifts.
- Warm-up toggle: a "Warm-up" chip next to Log Set that sends `set_kind: 'warmup'` (`WorkoutModeContext.logSet` already accepts `setKind`; wire `LogSetRequest.set_kind` on the backend route `routes/fitness.py:5680` and pass it through `/workout-session/log-set`). Auto-select the chip while `next_set.kind === 'warmup'`; allow "Skip warm-ups" which advances past all warm-up entries without logging.
- `held` banner: "Holding week 1 loads (last top set RPE 9)" with a one-tap "Use week 2 anyway" that calls a new `set_plan_week` command (A5).
- Watch `ActiveWorkoutView.swift`: seed weight/reps from `nextSet` when present, fall back to `approvedWeight`/`targetReps`. Show the kind label. Warm-ups on the Watch are a "Warm-up" toggle on the log screen; no separate view.

### A5. Backend log-set semantics

- `_apply_log_set`: when the payload omits weight/reps, default from `next_set` (kind-aware) instead of `approved_weight` / `low+1`.
- Stamp the role on the row: `workout_log.flags = {"role": "top"|"backoff"|"warmup", "plan_week": N}` so the advance rule (A2), PR detection and the brief can tell a 225×2 top set from a 225×2 backoff. No schema change (`flags` is JSON).
- New command `set_plan_week` (payload `exercise_index`, `week`) that re-resolves `set_plan_resolved` for that exercise in the live snapshot (used by the "use week N anyway" tap and by chat).
- Post-workout proposals (`_maybe_propose_weight`, `_create_next_session_proposals`): skip plan-driven exercises. The plan already says what next week is; a "+10 lb?" proposal on the squat contradicts it.
- `recalculate_session` / `completed_for`: warm-ups continue to not count; the cursor should also not consider an exercise "complete" until working sets are done (already true).

### A6. "Which session is next today" — server decides, by template id

- `GET /templates/today` (`routes/fitness.py:3927`): join `active_workout_session` for today (ET) by `template_id` and return per template `session_status: null | 'active' | 'completed' | 'abandoned'` and `completed_at`. Use `training_day.templates_for_day()` instead of the route's own loop (same order guarantee, one code path).
- `training_day.is_training_day()`: `templates[]` entries gain the same `session_status`; `template_id`/`template_name` become "the next outstanding" rather than "the first" (Watch catalog reads `today_template_id`, `workout_command_service.catalog()`).
- `FitnessScreen.tsx` `nextTemplateToday`: use `session_status` from the API; delete the title matching. Hero shows AM until it's completed, then PM; after both, "Done for today" with both cards collapsed. Start button on a completed template asks "Log another AM session?" instead of silently starting a duplicate.
- `GET /api/fitness/workouts`: honour `start_date`/`end_date` (currently accepted and ignored) and apply `LIMIT` to workouts, not joined rows. Small, but it's why the phone's "today" logic was fragile.

### A7. Readers that describe the day

- `workout_prescription.describe_exercise()`: prefer `set_plan` when present, fall back to the notes parser. Output stays one line: `Back Squat — warm-up 4 sets, top 225×2–4, 3×4–6 @200 [week 1]`.
- `tools/fitness/workout_suggest.py` (lines 165, 248, 291): read `set_plan` the same way; it currently re-parses notes.
- Morning brief + `fitness_context.py`: no change beyond the helper; verify the rendered line with `backend/tests/test_two_templates_per_day.py`.
- Chat `workout_mode.py` tool: expose `next_set` in `get_workout_context()` (`workout_session_service.py:775`) so Sara can say "top set now: 225 for 2–4" instead of a suggested weight.

### A8. Tests

- `backend/tests/test_set_plan.py`: resolve week 1/4/8 for each of the 4 AM lifts against the spec numbers; hold rule (RPE 9 last top → previous week; first session → planned week); deload row not halved / not ×0.6; program-week vs phase-week (2026-10-12 → week 5); missing `set_plan` → legacy path unchanged.
- Extend `test_two_templates_per_day.py`: `/templates/today` reports AM completed → next outstanding is PM.
- Command-service test: `log_set` with no payload defaults to `next_set` for warmup → top → backoff in order; `flags.role` stamped; proposals skipped for plan-driven lifts.
- Parity script passes with the new fields.

### A9. Not doing (in this part)

- Rewriting this week's logs. Tue/Wed/Thu stay as logged; week 2 resolves from the plan (the hold rule only looks at `flags.role='top'`, which none of this week's sets have, so week 2 starts on the planned row).
- Changing PM progression, superset/drop-set mechanics, HealthKit meld.

### A10. Order of work (Part A)

1. A1 migration + verification SELECT (data only, reversible: the key is additive).
2. A2 + A5 backend (engine, defaults, flags, no-double-deload) + A8 tests.
3. A3 projection + contracts + parity script.
4. A4 phone, then Watch (needs an EAS build — see `reference_ios_build_workflow`).
5. A6 today-session status (backend, then phone).
6. A7 readers.

Deploy note: the backend container must be rebuilt (`docker compose -f docker-compose.dev.yml build backend`) — memory gotcha "Deployed code lags working tree". Monday 2026-09-21 07:00 AM NewTech is the first real test: expected snapshot = warm-ups 90×10 / 180×5 / 230×2, top 270×3 (week 2), 3×4–6 @230.

---

## Part B — Food logging: remember the last serving, then the MFP/Lose It flow

### B0. Where we are

- Stage A of the 2026-08-16 plan partly shipped: canonical item v2 (`ios-app/src/services/foodContracts.ts`, `frontend/src/types/foodContracts.ts`, `backend/tests/test_food_item_v2_contract.py`, `ios-app/scripts/check-food-contract-parity.mjs`), idempotent create, backend re-derives totals from `detailed_items`.
- Stage B (diary, composer, repeats, ranking) never started. No `saved_meal`, no `/repeat`, no `/copy-day`, no `/food-diary` endpoint exists.
- `food_log_item` table exists with **0 rows**; everything lives in `food_log.detailed_items` JSONB. Keep it that way for this plan (don't start a second store).
- What David hits today: tap "Boneless Skinless Chicken Thighs" under Recent → modal calls `handleSelectQuickFood` → `handleSelectFood` (`FoodLogModal.tsx:219-235`, `451-470`) which **resets quantity to 1 and applies `servings[0]`** (whatever FatSecret lists first), discarding the 6 oz he logged the last three days. The `recent-foods` endpoint (`routes/fitness.py:986`) also drops `serving_id` and returns the *scaled* macros labelled as `serving_size: 6, serving_unit: "serving"`, which is not what any client expects.

### B1. Remembered serving (do this first; small, high value)

Backend:

- `GET /food-log/recent-foods`: for each food key also return
  `last_serving_id`, `last_serving_description`, `last_quantity`, `last_unit`, `last_meal_type`, `last_logged_at`, `times_30d`, plus **per-serving** macros (`calories_per_serving`, …) computed as logged macros ÷ quantity so the client can scale. Keep the old fields for older builds.
- `GET /food-log/yesterday` `all_foods[]`: same shape per item (it already has quantity/unit/serving_id in `detailed_items`, just surface them).
- New `GET /food-log/last-used?food_ids=fs-61258,fs-17905017` → `{food_id: {serving_id, serving_description, quantity, unit, meal_type, logged_at}}` from the most recent `detailed_items` entry per id (30-day window, JSONB scan is fine at this volume; add `ix_food_log_user_logged_at (user_id, logged_at DESC)` if it isn't there). Search results and barcode hits call this so a *searched* chicken thigh also opens at 6 oz.
- `FoodItemV2` gets optional `last_used` (same object) — additive, bump nothing.

iOS `FoodLogModal.tsx`:

- `handleSelectFood(food, preset?)`: after fetching servings and building synthetic g/oz/ml, choose the serving whose `serving_id` matches `preset.serving_id` (synthetic ids are stable: `synthetic-oz`), else match on `serving_description`, else `servings[0]`. Set `quantity = preset.quantity`, `unit` accordingly, and `mealType = preset.meal_type` only if the modal was opened without an explicit meal.
- Recent/Yesterday rows show the remembered amount inline: "Boneless Skinless Chicken Thighs · **6 oz** · 213 kcal · 3× this week".
- Search results and barcode hits: if `last_used` is present, show the same "last: 6 oz" hint and preset it.
- Edit path (`rehydrate` ~line 383) already does this for editing a row — reuse that serving-matching code for the preset case rather than writing a second matcher.

Web `frontend/src/components/fitness/FoodItemSelector.tsx` / `AddMealForm.tsx`: same preset behaviour (parity test in `check-food-contract-parity.mjs` fixtures: "recent item with last_used → preset serving + quantity").

Chat tool `backend/app/tools/fitness/food_log.py` + `food_search_log.py`: when Sara logs "6 oz chicken thighs" from chat, write `detailed_items` with `food_id`, `serving_id`, `quantity`, `unit` (today `food_log.py` writes `quantity: 1, unit: "serving"` — those rows then poison Recent with a 1-serving memory). `food_search_log.py` already resolves FatSecret; make sure its item shape matches the v2 contract.

Tests: `test_food_recent_last_used.py` — chicken thighs logged 6 oz twice and 4 oz once → `last_quantity 6`, per-serving macros = 213/6; yesterday endpoint carries serving ids; `last-used` returns the newest entry per id; chat-logged item surfaces with its serving.

### B2. Diary: one screen that reads like MFP's day view

- Backend `GET /api/fitness/food-diary?date=YYYY-MM-DD` (ET) → `{date, is_training_day, targets{calories, protein, carbs, fats} (from /today-target logic), totals, remaining, meals: {breakfast: {items[], subtotal}, lunch, dinner, snack}}`. Items are the v2 canonical shape with `log_id` + `line_id` so a row can be edited/deleted in place. `?days=7` variant for the week strip. `FitnessScreen.tsx:1579-1810` currently filters the 7-day `foodLogs` array client-side; replace that with this endpoint and stop shipping console logs.
- iOS Nutrition tab: date header with ‹ › and "Today"; ring/row of calories + P/C/F remaining vs target (reuse `components/fitness/ui/MacroRings.tsx`); four meal sections, each with subtotal and a `+` that opens the composer with that meal preselected; swipe-to-delete on a row; tap to edit (existing edit rehydration).
- Web `FoodLog.tsx` + `FitnessSection.tsx`: consume the same endpoint; the dashboard's Log Meal button wires to the composer.

### B3. Composer (cart), not a one-food modal

Rework `FoodLogModal` into a composer that stays open:

- Top: meal chip (preselected) + time; search field with barcode button (existing).
- Groups below search when the query is empty: **Recent** (B1 shape, ranked per B5), **Yesterday** (per meal, with "Add all from yesterday's lunch"), **My Foods** (`food_database`, 12 rows today), **Recipes**, **Saved Meals** (B4).
- Every row has a trailing **+** that adds it with the remembered serving in one tap (no detail screen). Tapping the row body opens the serving/quantity detail (existing UI: quantity stepper + serving picker incl. synthetic g/oz/ml).
- Cart at the bottom: each added line shows name · qty unit · kcal, editable inline, removable; sticky subtotal (kcal + P/C/F) and **Log 3 items** primary button.
- Submit: one `POST /food-log` with N `detailed_items` and one `idempotency_key` (backend already accepts multi-item + derives totals). Drafts are client-local and survive an app kill (AsyncStorage, keyed by meal+date), per the August plan §3.2.
- Undo: after logging, a snackbar "Logged lunch · 3 items · Undo" for ~8 s that calls `DELETE /food-log/{id}`.

### B4. Repeats and saved meals

- `POST /food-log/{id}/repeat` (body: `meal_type?`, `logged_at?`, `idempotency_key`) → new row copying `detailed_items` snapshot.
- `POST /food-log/copy-day` (`from_date`, `to_date`, `meals[]?`) → one row per source row.
- `saved_meal` (id, user_id, name, default_meal_type, items JSONB snapshot, archived_at) with CRUD + `POST /saved-meals/{id}/log`. "Save as meal" action on any logged meal section and on the composer cart.
- Diary per-meal cards when the section is empty: "Same lunch as yesterday? (chicken thighs 6 oz, jasmine rice 8 oz, potatoes 4 oz · 681 kcal)" → one tap logs it, Undo available.

### B5. Ranking of Recent (deterministic, explainable)

Score per food key = frequency (30 d) + recency decay + same-meal-type bonus + same-time-bucket bonus + training-day match; every row carries `reason` ("Usual lunch", "Logged yesterday", "Used 8×"). Implemented server-side in the recent-foods endpoint (it already counts frequency); the client only orders by the returned `score`. No model. "Hide from Recent" writes a small `food_preference` row (`user_id, food_key, hidden_at`) — the only new preference table, and only if David actually uses hide.

### B6. Serving math hygiene (while in there)

- Quantity input accepts decimals and fractions ("0.5", "1/2"); stepper steps by 0.5 for servings and by 1 for g/oz.
- The synthetic g/oz/ml builder exists twice (iOS `FoodLogModal.tsx:303`, web `FoodItemSelector.tsx:98`); extract once per client into the shared helpers the August plan called for and add fixture tests so 6 oz of fs-61258 = 213 kcal on both.
- Meal-type sanity: `logged_at` for a "lunch" chosen from Yesterday defaults to now, not yesterday.

### B7. Tests + parity

- Backend: `test_food_diary.py` (targets/remaining, ET day boundaries, multi-item subtotals), `test_food_repeat_copy.py` (idempotent repeat, copy-day), `test_food_recent_ranking.py` (fixed history → deterministic order + reasons).
- `check-food-contract-parity.mjs` fixtures: `last_used` present/absent; composer cart → `detailed_items`; saved meal snapshot.
- Manual acceptance (David): chicken thighs from Recent opens at 6 oz in ≤1 tap; a 3-item lunch logs without the composer closing; yesterday's lunch repeats in 2 taps; totals on the diary equal the sum of rows.

### B8. Order of work (Part B)

1. B1 remembered serving — backend, iOS, chat tool, web (1 commit each). This alone fixes the complaint.
2. B2 diary endpoint + iOS Nutrition tab.
3. B3 composer/cart + Undo.
4. B4 repeats + saved meals.
5. B5 ranking, B6 hygiene, B7 tests as each lands.

Decision gate from the August plan still applies: use B1–B4 daily for two weeks before considering the voice/photo stages.

---

## Out of scope for this plan

- PM double-progression automation (still `progressive_overload`).
- `food_log_item` normalisation (stays empty; JSONB `detailed_items` remains the store).
- New iOS native modules; everything here is JS + one Watch Swift view change, but the Watch/phone still need a fresh build to pick up contract changes.

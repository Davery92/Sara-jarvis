# HRV Pipeline Fix + Two-A-Day Powerbuilding Program Cutover

**Date:** 2026-09-14 (Monday)
**Branch:** feat/sara-mind-v2
**Status:** PLANNED — agent-executable. Do the parts in order; each has its own verification gate.
**Rules that apply to every step:** backend runs in Docker only (`docker compose exec backend …`, never a local uvicorn). User-facing times are ET via `app.core.timezone`. Log the real exception class before any catch-all returns a generic failure. `health_metric` is the single authority for body numbers (see `docs/plans` health-data-accuracy work); do not add a second read path for HRV, fix the write path.

---

## Part A — HRV: "no HRV logged in the last 36 hours" is a write-path bug

### A0. Root cause (verified 2026-09-14, do not re-derive)

Sara's chat reply on 2026-09-14 10:57 ET said both "your HRV swung between 16 and 137 last week" and "no HRV logged in 36 hours". Both were faithfully read from the DB. They came from two different tables that disagree:

| Store | HRV Sep 13 | HRV Sep 14 | Written by | Read by |
|---|---|---|---|---|
| `daily_recovery_log.hrv` | 137 | 64 | `POST /api/health/sync-recovery` (`main_simple.py:7670`, from iOS `healthSync.ts` → `getLatestHRV()` = latest sample in 24h) | weekly health note, morning brief, `progressive_overload.py`, recovery tool |
| `health_metric` (`hrv_morning`) | — | — | `POST /api/health/metrics/batch` (`routes/health_metrics.py:137`, from iOS `backgroundHealthSync.ts:103-155`) | `context_snapshot.py` health_today slice (the chat's "36h" line), `body_state_service.py`, `readiness_engine.py`, `emotional_state.py`, `world_brief.py`, `health_baselines.py` |

Why `hrv_morning` is missing on most days: the iOS batch path only looks at HRV samples in the **last 4 hours** at sync time AND only emits `hrv_morning` when the sync runs **between 05:00 and 07:59 local**. Sunday's sync ran at 08:00:32 (fails the hour gate); Monday's ran at 06:49 with no sample inside 02:49–06:49. Result: `hrv_morning` exists on 11 of the last 30 days; `daily_recovery_log.hrv` exists on all of them. 43 days in the last 90 have recovery-log HRV and no `hrv_morning`. Raw `hrv` samples stopped landing 2026-05-05 (stale iOS build; already in memory), so there is no fallback stream.

Both stores receive the same watch reading via two HTTP calls one second apart (see backend log 2026-09-14 06:49:30 / 06:49:31). The fix is to make the authoritative store receive it too.

### A1. Mirror HRV into `health_metric` at ingest (backend, no iOS rebuild)

**New file:** `backend/app/services/health_metric_mirror.py`

```python
def mirror_hrv_morning(db, user_id: str, hrv: int | float | None,
                       on_date: date | None = None, source: str = "apple_health",
                       via: str = "sync-recovery") -> bool:
    """Upsert the canonical hrv_morning row (06:00 ET stamp) for on_date.
    Returns True if a row was inserted. Never raises; logs exception class."""
```
- `recorded_at` = 06:00 **ET** on `on_date` (default `app.core.timezone.today()`), converted to aware UTC — this is exactly the stamp iOS uses (`hrvRecordedAt.setHours(6,0,0,0)` → ISO), so the existing unique index `ix_health_metric_dedup (user_id, metric_type, recorded_at)` makes the write idempotent against a later iOS `hrv_morning` for the same day. Use `INSERT … ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING RETURNING id`.
- `metadata` = `{"morning_reading": true, "sample_count": 1, "via": via}`.
- Skip when `hrv` is None or `<= 0` or not finite. Do not clamp/convert — iOS already converts seconds→ms.
- Do NOT commit inside the helper; callers own the transaction.

**Call sites (all three):**
1. `backend/app/main_simple.py` `/api/health/sync-recovery` handler (~line 7670-7800): after the update/insert of `daily_recovery_log`, before `db.commit()`, call `mirror_hrv_morning(db, user_id, data.hrv, via="sync-recovery")`.
2. `backend/app/routes/health_metrics.py` `_update_daily_recovery()` (~line 221): call `mirror_hrv_morning(db, user_id, recovery.hrv, via="metrics-batch-daily-recovery")`. Note the batch handler passes `daily_recovery.hrv` from the raw `hrv` sample list, so on the stale iOS build this is usually None — harmless.
3. Manual entries: `backend/app/tools/fitness/recovery_log.py` (~line 145/174) and `backend/app/routes/fitness.py` recovery-log create/update (~line 4733/4759) → `mirror_hrv_morning(db, user_id, hrv, on_date=log_date, source="manual", via="recovery-log")`. A number David types into the recovery card is still the day's HRV.

Also add one `logger.info` in the `/sync-recovery` handler when HRV is present: `hrv_morning mirrored=<bool>` so the next "no HRV" report can be checked from the log in one grep.

### A2. Backfill the gap

**New script:** `backend/scripts/backfill_hrv_morning_from_recovery_log.py` (create `backend/scripts/` if absent; look at `backend/add_folder_column.py` for the DB-connection pattern). Run with `docker compose exec backend python scripts/backfill_hrv_morning_from_recovery_log.py --days 120 [--dry-run]`.

```sql
INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source, metadata)
SELECT gen_random_uuid()::text, r.user_id, 'hrv_morning', r.hrv,
       (r.log_date::timestamp + interval '6 hours') AT TIME ZONE 'America/New_York',
       'apple_health',
       '{"morning_reading": true, "sample_count": 1, "via": "backfill-daily-recovery-log"}'::jsonb
FROM daily_recovery_log r
WHERE r.hrv IS NOT NULL AND r.hrv > 0
  AND r.log_date >= current_date - :days
  AND NOT EXISTS (
    SELECT 1 FROM health_metric h
    WHERE h.user_id = r.user_id AND h.metric_type = 'hrv_morning'
      AND (h.recorded_at AT TIME ZONE 'America/New_York')::date = r.log_date)
ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING;
```
Expected: ~43 rows for `--days 90`. Print the count and the min/max dates. Then run `backend/app/tasks/health_baselines.py`'s recompute (whatever the Celery task entrypoint is — find it, call it once) so the HRV baseline and the 14-day median in `context_snapshot.py` use the full series.

### A3. iOS (deferred — needs a rebuild on a woken Mac, see `reference_ios_build_workflow`)

`ios-app/src/services/backgroundHealthSync.ts:103-155`:
- Replace the 4-hour HRV window with 24 hours for the raw `hrv` samples (dedup is by `recorded_at`, so overlap is free).
- Replace the `hour >= 5 && hour < 8` gate + morning filter: emit `hrv_morning` whenever there is at least one sample in the last 24h, value = the **latest** sample (matches `getLatestHRV()` so both paths agree), `recorded_at` = 06:00 local today. Keep `sample_count` honest.
- Keep the "0 samples → watch may be unworn" log.
Commit the code now; it ships with the next build. Until then A1 covers it.

### A4. Tests

- `backend/tests/test_health_metric_mirror.py`: (a) stamp is 06:00 ET → 10:00 UTC in September, 11:00 UTC in January (DST); (b) second call same day is a no-op; (c) None/0/NaN skipped; (d) iOS `hrv_morning` arriving after the mirror does not duplicate (same recorded_at).
- Extend `backend/tests/test_health_data_accuracy.py` (or add `test_context_snapshot_hrv_from_recovery_sync.py`): seed only a `daily_recovery_log`-style ingest through the mirror, assert the health_today slice renders `hrv=64 (measured …)` and NOT `unavailable (nothing recorded in the last 36h)`.
- Run `docker compose exec backend python -m pytest tests/test_health_data_accuracy.py tests/test_recovery_score_hrv_outlier.py tests/test_health_metric_mirror.py -q`.

### A5. Verification gate (must all pass before Part B)

```sql
-- 1. every recovery-log HRV day in the last 90d now has an hrv_morning row
SELECT count(*) FROM daily_recovery_log r WHERE r.hrv IS NOT NULL AND r.log_date > current_date-90
  AND NOT EXISTS (SELECT 1 FROM health_metric h WHERE h.user_id=r.user_id AND h.metric_type='hrv_morning'
                  AND (h.recorded_at AT TIME ZONE 'America/New_York')::date = r.log_date);   -- expect 0
-- 2. today's row exists
SELECT value, recorded_at AT TIME ZONE 'America/New_York', metadata FROM health_metric
 WHERE metric_type='hrv_morning' AND recorded_at > now() - interval '36 hours';
```
Then in chat: ask Sara "what's my HRV today?" — the answer must be the `daily_recovery_log` number and must not contain "36 hours". Rebuild backend first: `docker compose build backend && docker compose up -d backend` (verify runtime artifacts, per `gotcha_deployed_code_lags`).

### A6. Observed, out of scope (record, don't fix here)
- Same conversation, 10:53 and 10:56 ET: two turns announced "let me pull up your nutrition plan" and executed zero tools (`chat_turn_trace.tools_called = []`, `ended_by = model`). That is the "failing at tool calls" complaint. Separate bug; file under the chat-harness work.

---

## Part B — Two-A-Day Powerbuilding Recomp Program (starts 2026-09-14)

Program spec (verbatim from David): `docs/fitness/TWO_A_DAY_POWERBUILDING_RECOMP_2026_09_14.md`. Read it fully before starting. It is the source of truth for every number below.

### B0. Decisions already made — implement, don't re-litigate

1. **Mechanism:** create a NEW active `fitness_program` via `app.services.plan_importer.apply_imported_plan(db, user_id, parsed, source_text, start_date="2026-09-14")`. It deactivates "The Forge — 16-Week Powerbuilding" (kept as history; its Block 3 / Peak phases become inert because `get_effective_phase` only consults the active program). Do NOT use `parse_plan_document` (LLM extraction) — hand-write the parsed dict below so the numbers are exact.
2. **Two templates per training day** (AM strength, PM hypertrophy), `order_in_phase` AM before PM, names prefixed `Mon AM — …` / `Mon PM — …`. Two sessions per date are legal (`workout_session` has no per-date unique index). Consumers that assume one template per weekday are fixed in B4.
3. **Phases:** four dated phases covering 8 weeks from Mon 2026-09-14 to Sun 2026-11-08: Build 1 (Wk 1–3, Sep 14–Oct 4), Deload (Wk 4, Oct 5–11), Build 2 (Wk 5–7, Oct 12–Nov 1), Rep PR (Wk 8, Nov 2–8). Importer copies the same templates into every phase; B3 then edits the Deload copies.
4. **Nutrition:** training days (Mon–Thu) 2,760 kcal / 240P / 270C / 80F per the spec. **Rest days (Fri–Sun) are not specified in the spec — ASSUMPTION:** 2,500 kcal / 240P / 205C / 80F (protein and fat held, carbs down ~65 g; matches the current Block 3 rest-day calorie level). Flat `calories_target` = weekly average 2,650 / carbs 242. Flag this assumption in the completion report so David can change it in one sentence to Sara (`phase_update` tool supports the split fields).
5. **Exercise names** must match the names already in `workout_log.exercise_id` where a history exists, because `progressive_overload.py` matches by name and a rename orphans the history: `Newtech Flat`, `Smith Machine Press`, `Incline Press`, `Triceps Pushdown`, `Lat Pulldown`, `Rear Delt Fly`, `Lateral Raise`, `Cable Lateral Raise`, `Seated DB Shoulder Press`, `Leg Press`, `Leg Extension`, `Leg Curl`, `Calf Raise`. New names (no usable history): `Deadlift` (nothing logged in 120 days), `Back Squat` (the old "Back Squat (Barbell / Hack Squat or Leg Press)" rows carry ambiguous units — do not inherit), `Cable Fly`, `Chest Press Machine`, `Overhead Cable Triceps Extension`, `Chest-Supported Row`, `Single-Arm Cable Lat Row`, `Straight-Arm Pulldown`, `Hammer Curl`, `Cable Curl`.
6. **AM lifts are one template exercise each** (not "top set" + "backoff" entries, which would split the log history). `sets` = top + backoffs, `reps` = the combined range, `rpe_target` 8, and the **full 8-week loading table lives in that exercise's `notes`** (same convention Block 3 used: "Wk11: 75% 4×5 · …"). Warm-up ramp goes in notes too.
7. **Anchors are David's claims, not logged data.** Logged maxima: Newtech Flat 230×6 (Aug 31), Smith Machine Press 135×4 (Aug 27), no deadlift, no clean barbell squat. Record the spec's anchors in `program.notes` as "programming anchors (unverified)"; do not create `exercise_pr` rows for them.
8. **Cardio:** update `cardio_settings` to the spec (`weekly_min_minutes` 30, `weekly_max_minutes` 60, keep `steps_floor` 8000, add menu item `{"key":"stairs","label":"StairMaster / incline walk — after AM lift","typical_minutes":12,"worth_minutes":12,"note":"2–4 mornings/wk, easy-moderate. Never before the lift; no hard intervals around Tue/Thu."}`; keep existing menu entries). Route: `PATCH` via `update_cardio_settings` in `backend/app/routes/cardio.py:486` or direct SQL.
9. `fitness_goals` legacy row: leave alone (ignored whenever an active phase exists).

### B1. The parsed plan (hand-written; save as `backend/scripts/plans/two_a_day_2026_09_14.json`)

Reps are strings, sets are ints, days lowercase. `rest_seconds`: AM main lifts 180–240, PM compounds 120, isolation 60–90.

```json
{
  "program": {
    "name": "Two-A-Day Powerbuilding Recomp (Sep 14 – Nov 8)",
    "goal": "recomp",
    "duration_weeks": 8,
    "notes": "One powerbuilding program split into two daily windows: AM (~7:00) = one heavy primary lift, 3-5 work sets, RPE <= 8, no grinders; PM (~1:00) = hypertrophy volume, compounds 1-2 RIR, isolation 0-2 RIR. Mon chest / Tue back / Wed shoulders / Thu legs; Fri-Sun no required lifting. Tue deadlift volume deliberately low so Thu squat stays productive; if Thu squat repeatedly declines, cut Tue deadlift backoffs first. Cardio AFTER the AM lift only: 10-15 min StairMaster/incline walk, 2-4 mornings/wk, easy-moderate; no hard intervals around deadlift/squat days. Do not add AM bodybuilding work. Reduce volume (never add) on joint irritation, worse sleep, falling performance, unusual fatigue. Programming anchors (David's numbers, unverified in the log): NewTech Flat 270 total plates x2-3; Deadlift ~365 1RM; Smith OHP 135x4x4 (~180 e1RM, provisional); Squat ~265 1RM. Load convention: NewTech = total plates both sides; Smith OHP same convention as the logged 135x4x4."
  },
  "phases": [
    {"name": "Build 1 (Weeks 1-3)", "goal": "recomp", "order_index": 0, "duration_weeks": 3, "deload_week": null,
     "notes": "Learn a recoverable workload. AM: Wk1/2/3 top sets per the loading table in each AM exercise's notes; advance only when the top set is clean and <= RPE 8, else repeat the week. PM: double progression - same load until every set hits the top of the range at the intended RIR, then add load and rebuild reps.",
     "nutrition": {"calories_target": 2650, "protein_target": 240, "carbs_target": 242, "fat_target": 80,
                   "calories_training_day": 2760, "calories_rest_day": 2500, "carbs_training_day": 270, "carbs_rest_day": 205,
                   "fat_training_day": 80, "fat_rest_day": 80, "training_days_per_week": 4}},
    {"name": "Deload (Week 4)", "goal": "recomp", "order_index": 1, "duration_weeks": 1, "deload_week": 1,
     "notes": "Deload. AM: NewTech 230x4 + 210x5x2; Deadlift 285x2 + 250x3x1-2; Smith OHP 125x4 + 115x5x2; Squat 205x3 + 180x5x2. PM: ~50% of sets, stay 3-4 RIR.",
     "nutrition": {"calories_target": 2650, "protein_target": 240, "carbs_target": 242, "fat_target": 80,
                   "calories_training_day": 2760, "calories_rest_day": 2500, "carbs_training_day": 270, "carbs_rest_day": 205,
                   "fat_training_day": 80, "fat_rest_day": 80, "training_days_per_week": 4}},
    {"name": "Build 2 (Weeks 5-7)", "goal": "recomp", "order_index": 2, "duration_weeks": 3, "deload_week": null,
     "notes": "Beat Weeks 1-3 with clean progression. Wk7 approaches the top of the block: if 340 deadlift, 165 Smith OHP or 245 squat would be a grinder, repeat Wk6 or use the smallest available increase.",
     "nutrition": {"calories_target": 2650, "protein_target": 240, "carbs_target": 242, "fat_target": 80,
                   "calories_training_day": 2760, "calories_rest_day": 2500, "carbs_training_day": 270, "carbs_rest_day": 205,
                   "fat_training_day": 80, "fat_rest_day": 80, "training_days_per_week": 4}},
    {"name": "Rep PR (Week 8)", "goal": "recomp", "order_index": 3, "duration_weeks": 1, "deload_week": null,
     "notes": "Controlled rep-PR week at familiar loads, no true max testing. Targets: NewTech 270x5, Deadlift 325x3, Smith OHP 155x4+, Squat 230x4+. Backoffs: NewTech 235x4-6x3, Deadlift 280x3-5x2, Smith OHP 140x4-6x3, Squat 205x4-6x3. PM normal-to-slightly reduced volume.",
     "nutrition": {"calories_target": 2650, "protein_target": 240, "carbs_target": 242, "fat_target": 80,
                   "calories_training_day": 2760, "calories_rest_day": 2500, "carbs_training_day": 270, "carbs_rest_day": 205,
                   "fat_training_day": 80, "fat_rest_day": 80, "training_days_per_week": 4}}
  ],
  "templates": [
    {"name": "Mon AM — NewTech Flat Press (Strength)", "scheduled_days": ["monday"], "order_in_phase": 0,
     "notes": "AM strength, ~7:00. One lift: 1 top set + 3 backoffs. RPE <= 8, no grinders. Optional 10-15 min StairMaster/incline walk AFTER. Loads = total plates both sides.",
     "exercises": [
       {"name": "Newtech Flat", "sets": 4, "reps": "2-6", "rpe_target": 8, "rest_seconds": 240, "is_per_side": false, "metric_type": "reps",
        "notes": "Warm-up: 90x10, 180x5, 230x2 (easy). Set 1 = TOP SET, sets 2-4 = BACKOFF x4-6 @1-2 RIR.\nTOP: Wk1 270x2 · Wk2 270x3 · Wk3 270x4 · Wk4 DELOAD 230x4 · Wk5 280x2 · Wk6 280x3 · Wk7 280x4 · Wk8 REP PR 270x5 target\nBACKOFF: Wk1 230 · Wk2 230 · Wk3 240 · Wk4 DELOAD 210x5x2 · Wk5 240 · Wk6 250 · Wk7 250 · Wk8 235\nAdvance only when the top set is clean and <= RPE 8; otherwise repeat the previous week."}
     ]},
    {"name": "Mon PM — Chest + Triceps (Hypertrophy)", "scheduled_days": ["monday"], "order_in_phase": 1,
     "notes": "PM hypertrophy, ~1:00. Compounds 1-2 RIR, isolation 0-2 RIR. Double progression. The AM NewTech sets already count toward weekly chest volume.",
     "exercises": [
       {"name": "Incline Press", "sets": 3, "reps": "6-10", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "Incline DB or incline machine. 1-2 RIR."},
       {"name": "Cable Fly", "sets": 3, "reps": "10-15", "rpe_target": 9, "rest_seconds": 90, "is_per_side": false, "metric_type": "reps", "notes": "Controlled stretch; 0-2 RIR."},
       {"name": "Chest Press Machine", "sets": 2, "reps": "8-12", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "Converging / chest press machine. 1-2 RIR."},
       {"name": "Triceps Pushdown", "sets": 3, "reps": "10-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Rope pressdown. 0-2 RIR."},
       {"name": "Overhead Cable Triceps Extension", "sets": 2, "reps": "10-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "0-2 RIR."}
     ]},
    {"name": "Tue AM — Deadlift (Strength)", "scheduled_days": ["tuesday"], "order_in_phase": 2,
     "notes": "AM strength, ~7:00. 1 top set + 2 backoffs ONLY. No 5x5, no deficits, no extra heavy hinging - keep Thursday squats productive. Stop top set at RPE 7.5-8.",
     "exercises": [
       {"name": "Deadlift", "sets": 3, "reps": "1-5", "rpe_target": 8, "rest_seconds": 240, "is_per_side": false, "metric_type": "reps",
        "notes": "Warm-up: 135x5, 185x3, 225x2, 275x1. Set 1 = TOP SET x1-3 (RPE 7.5-8), sets 2-3 = BACKOFF x3-5, clean technique, no grinding.\nTOP: Wk1 315 · Wk2 320 · Wk3 325 · Wk4 DELOAD 285x2 · Wk5 330 · Wk6 335 · Wk7 340x1-2 · Wk8 REP PR 325x3 target\nBACKOFF: Wk1 275 · Wk2 280 · Wk3 285 · Wk4 DELOAD 250x3x1-2 · Wk5 290 · Wk6 295 · Wk7 300 · Wk8 280\nIf Wk7 340 would be a grinder, repeat Wk6 or take the smallest increase."}
     ]},
    {"name": "Tue PM — Back + Biceps (Hypertrophy)", "scheduled_days": ["tuesday"], "order_in_phase": 3,
     "notes": "PM hypertrophy, ~1:00. Build the back without loading the erectors again. Double progression.",
     "exercises": [
       {"name": "Lat Pulldown", "sets": 3, "reps": "6-10", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "1-2 RIR."},
       {"name": "Chest-Supported Row", "sets": 3, "reps": "8-12", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "1-2 RIR. (Chest-supported T-bar counts.)"},
       {"name": "Single-Arm Cable Lat Row", "sets": 2, "reps": "10-15", "rpe_target": 8, "rest_seconds": 90, "is_per_side": true, "metric_type": "reps", "notes": "Drive elbow toward hip."},
       {"name": "Straight-Arm Pulldown", "sets": 2, "reps": "12-15", "rpe_target": 8, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Lat isolation."},
       {"name": "Rear Delt Fly", "sets": 2, "reps": "12-20", "rpe_target": 8, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Cable rear-delt fly or reverse pec deck. Controlled reps."},
       {"name": "Hammer Curl", "sets": 3, "reps": "8-12", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Forearm-friendly grip."},
       {"name": "Cable Curl", "sets": 2, "reps": "10-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Avoid painful straight/EZ-bar variations."}
     ]},
    {"name": "Wed AM — Smith Overhead Press (Strength)", "scheduled_days": ["wednesday"], "order_in_phase": 4,
     "notes": "AM strength, ~7:00. 1 top set + 3 backoffs. RPE <= 8. Same load convention as the logged 135x4x4. Optional cardio after.",
     "exercises": [
       {"name": "Smith Machine Press", "sets": 4, "reps": "2-6", "rpe_target": 8, "rest_seconds": 180, "is_per_side": false, "metric_type": "reps",
        "notes": "Smith machine OHP. Warm-up: 65x8, 95x5, 115x3, 135x1. Set 1 = TOP SET x2-4, sets 2-4 = BACKOFF x4-6 @1-2 RIR. Provisional e1RM anchor 180 - let progression validate it.\nTOP: Wk1 145 · Wk2 150 · Wk3 155 · Wk4 DELOAD 125x4 · Wk5 155 · Wk6 160 · Wk7 165x1-3 · Wk8 REP PR 155x4+ target\nBACKOFF: Wk1 130 · Wk2 135 · Wk3 140 · Wk4 DELOAD 115x5x2 · Wk5 140 · Wk6 145 · Wk7 150 · Wk8 140"}
     ]},
    {"name": "Wed PM — Delts + Arms (Hypertrophy)", "scheduled_days": ["wednesday"], "order_in_phase": 5,
     "notes": "PM hypertrophy, ~1:00. Bias side/rear delts, not more pressing - the AM press already counts.",
     "exercises": [
       {"name": "Seated DB Shoulder Press", "sets": 2, "reps": "6-10", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "Machine or DB. 1-2 RIR."},
       {"name": "Lateral Raise", "sets": 3, "reps": "12-20", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "DB lateral raise. 0-2 RIR."},
       {"name": "Cable Lateral Raise", "sets": 3, "reps": "12-20", "rpe_target": 9, "rest_seconds": 60, "is_per_side": true, "metric_type": "reps", "notes": "0-2 RIR."},
       {"name": "Rear Delt Fly", "sets": 3, "reps": "12-20", "rpe_target": 8, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Controlled; avoid momentum."},
       {"name": "Triceps Pushdown", "sets": 2, "reps": "10-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Rope pressdown. 0-2 RIR."},
       {"name": "Hammer Curl", "sets": 2, "reps": "10-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Hammer or cable curl. 0-2 RIR."}
     ]},
    {"name": "Thu AM — Squat (Strength)", "scheduled_days": ["thursday"], "order_in_phase": 6,
     "notes": "AM strength, ~7:00. 1 top set + 3 backoffs. RPE <= 8. Optional cardio after; no hard intervals today.",
     "exercises": [
       {"name": "Back Squat", "sets": 4, "reps": "2-6", "rpe_target": 8, "rest_seconds": 240, "is_per_side": false, "metric_type": "reps",
        "notes": "Warm-up: 45x8, 135x5, 185x3, 205x1. Set 1 = TOP SET x2-4, sets 2-4 = BACKOFF x4-6 @1-2 RIR. Anchor ~265 1RM (unverified).\nTOP: Wk1 225 · Wk2 230 · Wk3 235 · Wk4 DELOAD 205x3 · Wk5 235 · Wk6 240 · Wk7 245x1-3 · Wk8 REP PR 230x4+ target\nBACKOFF: Wk1 200 · Wk2 205 · Wk3 210 · Wk4 DELOAD 180x5x2 · Wk5 210 · Wk6 215 · Wk7 220 · Wk8 205\nIf Wk7 245 would be a grinder, repeat Wk6."}
     ]},
    {"name": "Thu PM — Legs (Hypertrophy)", "scheduled_days": ["thursday"], "order_in_phase": 7,
     "notes": "PM hypertrophy, ~1:00. No RDL - Tuesday already supplied the heavy hinge; leg curls cover hamstrings.",
     "exercises": [
       {"name": "Leg Press", "sets": 3, "reps": "8-12", "rpe_target": 8, "rest_seconds": 120, "is_per_side": false, "metric_type": "reps", "notes": "Leg press or hack squat. 1-2 RIR. If unavailable: heel-elevated goblet squat 3x10-15."},
       {"name": "Leg Extension", "sets": 3, "reps": "10-15", "rpe_target": 9, "rest_seconds": 90, "is_per_side": false, "metric_type": "reps", "notes": "Hard squeeze at lockout."},
       {"name": "Leg Curl", "sets": 3, "reps": "8-15", "rpe_target": 9, "rest_seconds": 90, "is_per_side": false, "metric_type": "reps", "notes": "Controlled eccentric."},
       {"name": "Calf Raise", "sets": 3, "reps": "8-15", "rpe_target": 9, "rest_seconds": 60, "is_per_side": false, "metric_type": "reps", "notes": "Full stretch and pause."}
     ]}
  ],
  "nutrition_guide": {
    "goal": "Recomp on a two-a-day split: fuel a heavy 7 AM lift, a 1 PM volume session, and recovery - at a starting intake, not a growing one.",
    "how_it_works": "Training days (Mon-Thu) ~2,760 kcal / 240P / 270C / 80F across five feeds timed to the two sessions. Rest days (Fri-Sun) hold protein and fat, drop carbs (~2,500 kcal / 240P / 205C / 80F - starting assumption, adjust from trends). Treat 2,760 as a starting intake: adjust from bodyweight/waist trends, gym performance, hunger and recovery after several weeks of consistent data. Do not raise calories just because there are two sessions.",
    "weekly_average": "~2,650 cal/day · 240g protein every day · scale roughly flat week-over-week with the waist shrinking and the AM lifts climbing",
    "macros": [
      {"label": "Calories", "training": "~2,760", "rest": "~2,500"},
      {"label": "Protein", "training": "240g", "rest": "240g"},
      {"label": "Carbs", "training": "270g", "rest": "~205g"},
      {"label": "Fat", "training": "80g", "rest": "80g"}
    ],
    "rules": [
      {"title": "Training-day feed schedule", "body": "5:00-5:30 wake/water · 6:15-6:40 Nurri + easy carbs 30P/38C/3F (fuels the 7 AM lift) · 8:00-8:15 office breakfast 45P/52C/15F · 11:30 main pre-workout meal 50P/75C/12F (largest carb feed, for the 1 PM session) · 2:15-2:30 post-workout 50P/65C/15F · 6:30-7:00 dinner 65P/40C/35F. Total 240P/270C/80F ≈ 2,760."},
      {"title": "Fast morning fuel stays", "body": "Nurri plus banana / rice cake / honey - the AM session is heavy but intentionally low-volume, so it needs quick carbs, not a full meal."},
      {"title": "Biggest carbs before 1 PM", "body": "The PM bodybuilding session creates far more repeated-set glycogen demand than a few heavy AM sets. The 11:30 meal is the main carb feed."},
      {"title": "Don't add calories for the second session", "body": "Start at the planned recomp intake; let performance and body-composition trends decide whether more food is needed."},
      {"title": "Protein stays distributed", "body": "Five feeds provide repeated high-quality protein doses; no late-night meal required."}
    ],
    "carb_timing": {"days": "Tue (deadlift) and Thu (legs) matter most", "pre": "11:30 meal, 75g carbs", "post": "2:15 meal, 65g carbs", "note": "If carbs ever get redistributed, bias them toward Tue/Thu rather than adding calories blindly."},
    "staples": {"carbs": "rice, oats, banana / rice cake / honey pre-lift", "protein": "Nurri, chicken, beef, eggs", "watch_out": "Heavy-fat meals before the PM session delay gastric emptying; keep fat low in the 6:15 and 11:30 feeds."},
    "self_check": ["Was the AM top set clean and at or under RPE 8?", "Did the 11:30 meal happen before the 1 PM session?", "Is the scale flat week-over-week while the waist tape drops?", "Any joint irritation, worse sleep or falling performance? Then reduce, don't add."]
  }
}
```

### B2. Apply

```bash
docker compose exec -T backend python - <<'PY'
import json
from app.db.base import SessionLocal
from app.services.plan_importer import apply_imported_plan, validate_parsed
parsed = json.load(open("scripts/plans/two_a_day_2026_09_14.json"))
print(validate_parsed(parsed))               # expect []
src = open("/app/docs/fitness/TWO_A_DAY_POWERBUILDING_RECOMP_2026_09_14.md").read()  # mount or copy the file in first
db = SessionLocal()
print(json.dumps(apply_imported_plan(db, "64f37c56-85cb-4590-8de9-adfc17d343ed", parsed, source_text=src, start_date="2026-09-14"), indent=2))
PY
```
- User id `64f37c56-85cb-4590-8de9-adfc17d343ed` is David (the only real user). The docs file may not be mounted in the container; if not, `docker cp` it or read it host-side and pass the text in. `plan_markdown` must be the verbatim spec — it is what the web Plan tab renders.
- Expected summary: program start 2026-09-14, end 2026-11-08, 4 phases, 8 workouts.

### B3. Post-import edits (SQL or the `template_update` tool)

1. **Deload phase templates** (phase "Deload (Week 4)"): for the four PM templates, halve `sets` (round down, min 1) and change every `rpe_target` to 6-7 (3-4 RIR); set each AM exercise's `reps`/notes to the deload row (already in the notes table — additionally prepend "DELOAD WEEK: " to the AM exercise `notes`). Keep names unchanged.
2. **Rep PR phase** AM exercise notes: prepend "REP PR WEEK - targets: …" from the phase notes.
3. **Cardio settings** per B0.8.
4. Verify old program `is_active = false` and exactly one active program.

### B4. Backend: stop assuming one template per weekday

Every "today's workout" reader picks the first matching template and stops. With AM/PM that hides the PM session from Sara, the brief, and suggestions. Fix all of them to return the day's templates **ordered by `order_in_phase`** and render "AM: … · PM: …":

- `backend/app/services/morning_brief_service.py:1823-1829` and `:2244-2250` — collect all matches; brief line like "Today: AM NewTech Flat (top set 270×2, 3×4–6 @230) · PM Chest + Triceps (5 exercises)". Pull the week's target line from the AM exercise notes (`Wk<n>` where n = weeks since program start + 1) so Sara states the actual prescribed load, not just the name.
- `backend/app/tools/fitness/workout_suggest.py:120-134` — if multiple, return suggestions for each (AM first) or accept an optional `session` param (`am|pm`); do not silently take `[0]`.
- `backend/app/services/training_day.py` — returns the first template; extend the dict with `templates: [{id,name,order_in_phase}]` (keep `template_id`/`template_name` = first, for compatibility).
- `backend/app/services/fitness_context.py` — add one line after the Phase line: today's sessions (AM/PM names + AM prescribed top set). This is the context the chat persona reads; without it Sara knows the macros but not the sessions.
- `backend/app/tools/fitness/summary.py`, `training_schedule.py`, `workout_command_service.py:2111` — audit for `[0]`/`break` on scheduled_days matches; make them list-aware.
- Add `backend/tests/test_two_templates_per_day.py`: seed a phase with AM+PM templates on monday; assert `is_training_day` true with both listed, morning brief text contains both names, `workout_suggest` returns both.

### B5. iOS (deferred to the next build)

`ios-app/src/screens/fitness/FitnessScreen.tsx:527-528, 1088` show `todaysTemplates[0]` as the hero. Change to "next not-yet-completed template today" (AM until a session for it is completed, then PM). The template list already renders both, and either can be started, so this is cosmetic until the rebuild.

### B6. Verification gate

```sql
SELECT name, start_date, end_date, is_active FROM fitness_program WHERE is_active;           -- exactly 1, the new one
SELECT name, start_date, end_date, calories_training_day, carbs_training_day FROM fitness_phase
 WHERE program_id = (SELECT id FROM fitness_program WHERE is_active) ORDER BY order_index;  -- 4 rows, Sep14/Oct5/Oct12/Nov2
SELECT p.name, t.order_in_phase, t.name, t.scheduled_days FROM fitness_template t JOIN fitness_phase p ON p.id=t.phase_id
 WHERE p.program_id = (SELECT id FROM fitness_program WHERE is_active) ORDER BY p.order_index, t.order_in_phase;  -- 32 rows
```
Python (in the backend container): `training_day.is_training_day` → true Mon–Thu with two templates, false Fri–Sun; `get_effective_phase(today)` → "Build 1 (Weeks 1-3)"; `GET /api/fitness/today-target` (`routes/fitness.py:3489`) → 2760/240/270/80 on Monday, 2500/240/205/80 on Friday.
Chat: "what's my workout today?" → Sara names both the AM NewTech session with the Week-1 top set (270×2) and the PM chest session. Morning brief for Tue 2026-09-15 → deadlift AM 315×1–3 + back PM.

### B7. Close-out
- Commit message: `feat(fitness+health): two-a-day program cutover; mirror HRV into health_metric at ingest`.
- Report to David: the rest-day macro assumption (B0.4), that anchors are unverified (B0.7), the cardio settings change (B0.8), and the two deferred iOS items (A3, B5).
- Update memory: `project_fitness_plan_control.md` (program cutover), and add a gotcha "iOS batch HRV window is 4h — hrv_morning must be mirrored server-side".

### Known gaps (accepted)
- `progressive_overload.py` suggests flat +5/+10 increments by RPE. For the AM lifts the prescribed weekly table wins; the notes carry it and B4 surfaces it, but the `/weight-suggestion` endpoint will still propose its own number. Reconcile later (a `progression_rule: "WEEKLY_TABLE"` that reads the notes, or a per-week `starting_weights` JSON on the template).
- The "you normally head to the gym around 1:08" routine signal will keep firing for the PM session; the 7 AM AM session is a new pattern the learner has to observe. Nothing to change; watch that check-ins do not nag about "leaving late" at 7 AM.

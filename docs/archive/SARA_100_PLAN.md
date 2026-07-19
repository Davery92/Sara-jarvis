# SARA 100% PLAN — Closing the Last 15%

**Date:** 2026-07-03
**Branch context:** `assistant-experience-jarvis`, after PHENOMENAL_ASSISTANT_PLAN Phases 1–8 + geolocation.
**Verdict from the July 3 full audit:** the nervous system is real and running — location flows into deliberation live, 30 high-confidence behavioral patterns with 38 days of evidence, attention theta learning on a timer, PKG at 475 facts, ~14 deliberations/day, anti-nag holding. What's missing is one big organ (a model of David's day), a handful of severed connections between subsystems that each work alone, and hygiene debt that silently wastes 7x compute nightly.

This plan is ordered by leverage. Phase 1 is an afternoon. Phase 2 is the headline feature. Phases 3–5 turn "working subsystems" into "one organism." Phase 6 is the proof loop.

---

## Scorecard: where the missing 15% lives

| Gap | Symptom | Phase |
|---|---|---|
| No model of David's typical day | `detected_pattern` empty since June audit; schedule detectors are dead code; nothing knows "wake ~5 AM, gym days, home by 9:30 PM" as data | 2 |
| Nightly learning runs for 6 test accounts | 258 `behavioral_pattern` rows, only 44 real; 7x nightly LLM spend | 1 |
| Two weekly digests both scheduled | Old non-pattern digest (Sun 10 AM) + new Phase 6 digest (Sun 7 PM) will both fire July 5 | 1 |
| Geofence enter spam, no exits recorded | Duplicate `enter` pairs 1–2s apart; re-enters while sitting at home; `location_event` has 13 enters / 0 exits | 1 |
| Predictive engine blind to learned patterns | `predictive_engine.py` reads only `calendar_event`; never touches `behavioral_pattern` | 3 |
| Location learning is spatial only | Place discovery clusters *where*, never *when* — no "leaves for gym ~5:45 AM Tue/Thu" | 3 |
| Pattern → standing-order promotion unproven | Suggestion loop now runs (9 AM), but no pattern has ever reached `status='confirmed'` → promotion never exercised | 3 |
| HRV + continuous heart-rate data dead since May 5 | `health_metric`: hrv/heart_rate stop 2026-05-05; resting_hr/sleep still flowing | 4 |
| June audit leftovers | 425k Neo4j ActionItem bloat, Live Activity end-signal gaps, no calendar ownership reasoning, no motion sensors in HA log | 4 |
| Commitment capture has zero data | Shipped 7/2; needs a live prove-out + a watch that it actually extracts | 5 |
| No standing verification loop | Every audit (June, July) finds "built but not wired" drift; nothing catches it between audits | 5 |

---

## Phase 1 — Hygiene sweep (quick wins, ~1 session)

Everything here is a small, safe, verifiable fix. Do them together, one restart at the end.

### 1.1 Scope nightly learning to the real user
- `backend/app/services/nightly_dream_service.py:128-130` — `_run_nightly_dream_cycle` does `db.query(User).all()` and loops all 7 `app_user` rows (6 are test accounts: test@example.com, testios@test.com, …). HA events aren't user-scoped, so every test account gets a clone of David's home patterns.
- **Fix:** adopt the existing convention — `SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-…")` as in `tasks/morning_proactive.py:21`, `tasks/morning_brief.py:16`, `tasks/research_brief.py:13`. Replace the all-users loop with the solo user. (Do NOT delete the test accounts outright — FK cascades touch episodes/notes; scoping the loop is the safe move. A separate cleanup can come later if desired.)
- **Also purge the clone rows:** `DELETE FROM behavioral_pattern WHERE user_id != '64f37c56-85cb-4590-8de9-adfc17d343ed';` (214 rows). Verify count drops 258 → 44.
- Audit the other all-users loops while in there: grep `query(User).all()` across services/tasks; anything that fans out per-user LLM work gets the same treatment.

### 1.2 Retire the old weekly digest
- `scheduled_job` still has `weekly-digest` → `autonomy.weekly_learning_digest` (Sun 10 AM) alongside the new `learning-digest-weekly` → `learning_digest.send_weekly_digest` (Sun 7 PM). The new one is the Phase 6 pattern-aware digest; the old one reads no pattern tables.
- **Fix:** migration `082` (or direct SQL + migration for reproducibility): `UPDATE scheduled_job SET enabled = false WHERE key = 'weekly-digest';` Leave the row for history/rollback.
- **Deadline: before Sunday July 5** or David gets two digests.

### 1.3 Geofence enter-event dedup (server-side state guard)
- Root cause: `resyncGeofences()` re-registers regions on every app foreground (`AuthenticatedOverlays.tsx:228`), and iOS fires an initial-state "enter" for any region the device is already inside. Result: duplicate `enter` pairs seconds apart and re-enters with no exit between them (13 enters / 0 exits in `location_event`).
- **Fix in `location_service.handle_geofence_event`:** before logging/emitting, check current state — if the incoming event is `enter` for a place the user is already marked present at (per `unified_context` `current_place` or last event for that place being an un-exited `enter`), swallow it: no `location_event` row, no event-bus emission, no trigger fire. Same guard for duplicate `exit`.
- Keep raw dedup cheap: also skip if an identical (place_id, event_type) row exists within the last 120s.
- **Verify:** foreground the app 3x while home → zero new enter rows.

### 1.4 `visit_count` parity
- `location_service.py:153-157` bumps `visit_count` only on the significant-report path; native geofence enters (`handle_geofence_event`) don't bump it. After 1.3's state guard, a *real* (state-changing) geofence enter should increment `visit_count` + `last_seen_at` too.

### 1.5 Cosmetic enum: discovered places
- `discover_and_stage_places` sets `KnownPlace.source="suggested"` (`location_service.py:484`) but the documented enum is user/chat/learned (`models/location.py:20`) and `status` already carries "suggested". Set `source="learned"` at creation; drop the confirm-time rewrite in `routes/location.py:157` or keep as no-op safety.

### 1.6 Restart discipline
- One backend + celery-worker rebuild/restart at the end of the phase. Remember the gotcha: restarting kills in-flight dispatch tasks — do it at a quiet moment.

**Phase 1 acceptance:** `behavioral_pattern` count = real rows only; exactly one digest fires Sunday; a day of location data shows 1 enter per actual arrival, exits present, visit_count advancing.

---

## Phase 2 — The Daily Rhythm Engine (the missing organ)

**Goal:** a persistent, queryable model of David's typical day — wake/sleep windows, work blocks, gym windows, meal times, home/away rhythm, weekday vs weekend — continuously re-derived from data Sara already collects, and injected everywhere she reasons.

### Why not resurrect `proactive_intelligence.py`?
The orphaned detectors (`_detect_sleep_schedule_pattern` etc., `proactive_intelligence.py:127-235`) are shallow: naive hour extraction (no ET handling — violates the no-UTC rule), single-signal, average-only ("averages 7.2h sleep" is not a schedule), and they write to `detected_pattern`, a table nothing reads. **Decision: delete the dead detector code in Phase 4, build fresh.** The `DetectedPattern` dataclass shape is fine to steal.

### 2.1 Data model — `daily_rhythm` table (migration 082)
One row per (user_id, rhythm_key, day_scope):

```
daily_rhythm
  id                uuid pk
  user_id           varchar fk app_user
  rhythm_key        varchar(50)   -- wake, bedtime, first_activity, leave_home, return_home,
                                  -- work_start, work_end, gym_window, lunch, dinner, winddown
  day_scope         varchar(10)   -- 'weekday' | 'weekend' | 'mon'..'sun' (start with weekday/weekend)
  window_start      time          -- ET
  window_end        time          -- ET
  median_time       time          -- ET
  confidence        float         -- 0-1, driven by sample size + variance
  sample_count      int
  variance_minutes  int           -- spread; high variance → low confidence, wide window
  evidence          jsonb         -- last N observations with source tags, for explainability
  computed_at       timestamptz
  UNIQUE (user_id, rhythm_key, day_scope)   -- UPSERT, never duplicate
```

All times stored as ET local times (`app.core.timezone` helpers — hard rule). `extend_existing=True` on the model. Model in `models/rhythm.py`, imported in `models/__init__.py`.

### 2.2 The learner — `services/daily_rhythm.py` + `tasks/daily_rhythm.py`
Nightly task `recompute_daily_rhythm` (seed `scheduled_job` row in migration 082: cron `45 3 * * *` ET, queue `cognitive` — after place-discovery at 3:30, before attention-learn cleanup windows). 30-day lookback, decayed weighting (recent weeks count more). **Pure SQL/statistics — no LLM call needed**; it's percentile math over existing tables:

| rhythm_key | Sources (all already populated) |
|---|---|
| wake | `behavioral_pattern` "David's iPhone Focus active around 05:00" class signals; first `health_metric` steps sample of day; first chat/episode activity; HA first-motion when sensors arrive (Phase 4) |
| bedtime | last HA entity activity cluster (lights out), last phone activity, sleep_hours anchoring from `health_metric` (sleep_* rows, current through 7/2) |
| leave_home / return_home | `location_event` enter/exit per known_place Home (clean after Phase 1.3) — this is why geofence hygiene comes first |
| gym_window | `workout_log` timestamps + `training_day.is_training_day()` weekday split |
| lunch / dinner | `food_log.logged_at` histograms |
| work_start / work_end | weekday calendar_event density + chat activity + (later) work-place location events |
| winddown | SHIELD/Family Room ~19:00 pattern class from `behavioral_pattern` |

Method per key: gather observations → split weekday/weekend → drop outliers (IQR) → median + P20/P80 window → confidence = f(sample_count, variance). UPSERT by unique key. Skip (retain old row, decay confidence slightly) when a source has <5 samples.

### 2.3 Injection — make it felt everywhere
1. **UnifiedContextSnapshot** (`services/unified_context.py`): add a compact `rhythm_summary` string (built at context-refresh, cached daily): e.g. `"Rhythm: wake ~5:00, gym Tu/Th ~17:30, dinner ~19:00, winddown ~21:00, bed ~22:30 (weekday)"`. NOTE the gotcha: if this rides `ContextDecision`, that NamedTuple has 12 fields and ALL construction sites must update (currently 1 in context_router.py).
2. **Deliberation prompt** (`services/deliberation_prompt.py`): rhythm line + derived flags: `off_rhythm: true` when now deviates (e.g., away from home at 23:00 on a weekday, no workout by end of usual gym window on a training day). Off-rhythm is a *salience input*, not an auto-notification — let the gate decide.
3. **Salience** (`services/salience.py`): new derived signal class `rhythm_deviation` (modest weight, 0.3–0.5) so deviations can tip deliberation when combined with other signals.
4. **Morning brief** (`services/morning_brief_service.py`): one line when today deviates from rhythm ("You're up 40 min earlier than usual").
5. **Chat personality context** (`main_simple.py` ~8747, next to the Location line): same compact rhythm summary so conversational Sara knows the shape of his day.
6. **Weekly digest** (`tasks/learning_digest.py`): add rhythm drift week-over-week ("bedtime slipped ~25 min later this week") — this is the "make the learning felt" payoff.
7. **API + UI (read-only v1):** `GET /api/rhythm` route; a small "Your rhythm" card in webapp Settings or the Insights page — median times + confidence bars. Sara being able to *show* the schedule she's learned is the single most tangible proof of learning.

### 2.4 Anti-nag guardrails (hard requirements)
- Rhythm deviations NEVER push directly; they only feed salience/deliberation, which already has cooldowns + the gate.
- No "you're off schedule" more than once per rhythm_key per day; respect the feedback rule about not re-roasting the same item daily.

**Phase 2 acceptance:** after 3 nightly runs, `daily_rhythm` has ≥6 keys with confidence >0.5; deliberation `context_summary` strings visibly reference rhythm; morning brief mentions a deviation when one exists; `/api/rhythm` renders.

---

## Phase 3 — Connect the severed brains

Each of these subsystems works alone today. Wire them to each other.

### 3.1 Predictive engine ← learned patterns
- `services/predictive_engine.py:39-146` derives "patterns" from `calendar_event` history only.
- **Fix:** feed it `behavioral_pattern` (status active/confirmed, confidence ≥0.8) and `daily_rhythm` as first-class prediction sources. Example outputs: "gym window opens in 45 min on a training day," "SHIELD time approaching." Predictions flow into the existing 30-min `predictive-engine` tick and its existing surfacing path — no new notification channel.

### 3.2 Temporal location routines
- Place discovery clusters *where* (`location_service.discover_and_stage_places`); nothing learns *when*. After Phase 2, this is nearly free: `leave_home`/`return_home` rhythm keys already capture the home rhythm. Extend to per-place: for each confirmed non-home `known_place`, compute typical visit days/hours from `location_event` history into `daily_rhythm` rows (`rhythm_key = 'place:<place_id>'`). Surfaces "David usually hits the gym Tue/Thu after work" once a gym place is confirmed.
- Requires exits to be recorded (Phase 1.3) for dwell/visit windows — sequencing matters.

### 3.3 Prove the pattern → standing-order promotion pipeline
- The morning suggestion loop now runs (`morning-proactive-check`, 9 AM ET, verified in `scheduled_job` and firing — the "EV Lights?" pushes). But no pattern has ever hit `status='confirmed'`, so promotion to `standing_order` (`standing_order_service.py:639`) has never executed in production.
- **Action:** accept one real suggestion end-to-end this week (e.g., the SHIELD ~19:00 one). Trace: `times_accepted` increments → status flips → promotion creates a standing order → standing order actually fires next evening → undo window works. Fix whatever breaks; this path has never carried live traffic.

### 3.4 Consolidation "patterns_noticed" → structured
- Consolidation's LLM already emits `patterns_noticed` as prose (`consolidation.py:118-123` → journal/working memory only). Add a light bridge: when a noticed pattern matches the shape "recurring behavior + time," stage it as a `behavioral_pattern` in `learning` status (dedup via existing `find_similar_pattern`) instead of letting the observation evaporate into prose. Low effort, closes the loop between the narrative brain and the structured one.

**Phase 3 acceptance:** one prediction sourced from a behavioral pattern visibly surfaces; one standing order exists that was born from a promoted pattern; a consolidation run stages ≥1 structured pattern.

---

## Phase 4 — Data integrity & June-audit debt

Sara's inferences are only as good as the streams feeding her.

### 4.1 HRV / continuous heart-rate flatline (May 5)
- `health_metric`: `hrv` (20,834 rows) and `heart_rate` (9,638) both stop 2026-05-05 while resting_hr/steps/sleep continue — so HealthKit sync works but two sample types dropped, almost certainly a casualty of the HealthKit v13 workout-stats migration (`getStatistic()` change) or a permissions/type registration regression in `backgroundHealthSync.ts`.
- **Fix:** inspect the sample-type list in `ios-app/src/services/backgroundHealthSync.ts`, re-add/repair HRV + HR sample queries, backfill via anchored query if possible. These feed recovery scoring and body-state calibration — silent degradation.

### 4.2 Neo4j ActionItem bloat (425k nodes, June audit)
- One-time cleanup job + a cap/TTL at the writer so it can't regrow. Then re-run PKG reconciliation (`pkg-reconciliation` hourly task exists). Bloat slows graph queries that PKG context assembly depends on.

### 4.3 Dead code deletion
- Delete `ProactiveIntelligenceEngine` pattern/suggestion code (`proactive_intelligence.py:58-235, 477-522`) — superseded by Phase 2. KEEP module-level `cross_reference_check` (`:644`) — `calendar_prep.py:51` uses it. Drop the now-writer-less `detected_pattern` table in a migration (verify zero rows first).
- Grep for other never-called learning services while in there (the audit pattern: "built, never wired" is Sara's recurring failure mode).

### 4.4 June-audit leftovers (schedule, don't block on)
- **Motion sensors absent from HA log** — hardware/HA config task; when they arrive, wake detection and home-state fidelity improve for free (rhythm engine picks them up as a new source).
- **Live Activity end-signal gaps** — iOS: ensure workout/timer Live Activities always receive a terminal update.
- **Calendar ownership reasoning** — attendees/organizer landed in Phase 5 of PHENOMENAL_ASSISTANT_PLAN; add "is this David's meeting vs one he was CC'd into" weighting in calendar_prep prioritization.

**Phase 4 acceptance:** HRV rows resume with current dates; Neo4j node count sane and stable week-over-week; `detected_pattern` gone; no orphaned learning modules in grep sweep.

---

## Phase 5 — Prove-out & the standing verification loop

The recurring disease: things get built, wiring silently doesn't happen, and it takes a manual audit weeks later to notice. Close the meta-loop.

### 5.1 Live prove-outs (this week)
- **Commitment capture:** tell Sara "I'll call the plumber Friday" in chat → verify `followup_thread` row with `source='commitment'`, due-anchored window → verify the nudge arrives inside the window via the gate → verify resolution on "done." Zero rows exist today; it has never been exercised.
- **Weekly digest:** Sunday 7 PM ET — confirm the new digest arrives, reads patterns/theta drift, and the old one stayed silent.
- **Place discovery first run:** 3:30 AM tonight — confirm it stages nothing weird from 1 day of data (it needs ≥3 distinct visit-days, so should no-op cleanly; check logs, not just absence of errors).
- **Leave-home flow:** next time David actually leaves, verify exit event, `current_place` clears, and (if a location reminder is pending) the geofence path fires.

### 5.2 Self-auditing — `system_wiring_check` task (weekly, Sun 8 AM ET)
Small, cheap, high-leverage. A task that asserts the wiring invariants this plan restores and pushes ONE summary line to the unified inbox (never a nag):
- every `@celery_app.task` module in `include` has either a `scheduled_job` row or an explicit allowlist entry (catches "built but never scheduled" — the #1 recurring failure)
- key learning tables advanced in the last N days: `behavioral_pattern` evidence updates, `daily_rhythm.computed_at`, `attention_policy` updates, `pkg_embedding` count, `location_event` recency
- `scheduled_job` rows with `last_status='error'` or stale `last_run_at`
- container image age vs code mtime (the "deployed code lags working tree" gotcha, mechanized)

Green = one quiet line in the weekly digest ("all 14 learning loops ran"). Red = a Needs-You inbox item naming the broken loop.

### 5.3 Definition of 100%
Sara is at 100% when, for a full week, all of the following are simultaneously true and *observable in her own words*:
1. Morning brief references his rhythm and any deviation.
2. At least one proactive act per week originates from a *learned* pattern (not a hardcoded rule), and it lands well (no ignore/negative feedback).
3. A stated commitment in chat comes back at the right moment without being asked.
4. Location arrivals/departures are clean in the data and reflected in her context within a minute.
5. The weekly digest accurately narrates what she learned, citing real pattern/theta/rhythm deltas.
6. The wiring check reports all loops green without human auditing.

---

## Sequencing & effort

| Phase | Depends on | Effort | Target |
|---|---|---|---|
| 1 Hygiene | — | ~1 session | before Sun Jul 5 (digest dedupe is date-bound) |
| 2 Rhythm engine | 1.3 (clean location events) | 2–3 sessions | week of Jul 6 |
| 3 Connections | 2 (rhythm table) for 3.1/3.2; 3.3 anytime | 1–2 sessions | week of Jul 13 |
| 4 Data integrity | independent; 4.3 after 2 | 1–2 sessions | interleave |
| 5 Prove-out + wiring check | 1–4 landed | ~1 session + a week of observation | rolling; declare 100% after one fully-green week |

**Standing rules for all phases** (from hard-won gotchas): ET everywhere via `app.core.timezone`, never naive `datetime.now()`; `CAST(:param AS vector)` for pgvector; `extend_existing=True` on models over existing tables; route registration outside try/except; rebuild+restart containers after backend changes and verify the *running* artifact; `enable_thinking: False` on short LLM calls; no new notification channels — everything proactive rides salience → deliberation → gate.

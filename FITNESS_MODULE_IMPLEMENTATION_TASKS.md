# Fitness Module — Implementation Tasks (No-Code Plan)

This document turns the Fitness Module integration spec into an actionable, code-free implementation plan tailored to this repo (FastAPI backend, React frontend, Postgres/pgvector, Redis, Neo4j optional, ntfy, existing scheduler). It defines deliverables, endpoints/contracts, data model, workflows, tests, and sequencing.

## Scope & Outcomes
- Chat-first onboarding runs only from Fitness Settings.
- Program generator creates a phased plan and bulk-schedules discrete workout events.
- Daily readiness ingests HRV/RHR/sleep + survey, computes score, and auto-adjusts today.
- In-workout flow provides set-by-set logging, rest timers, supersets/circuits, substitutions.
- Push/skip reflows schedule respecting constraints and deload cadence.
- Privacy controls for export/delete/reset and Health permissions.

## Components & Ownership
- `backend/app/routes/fitness/*`: API endpoints.
- `backend/app/services/fitness/*`: business logic (templates, generator, readiness, scheduler, state machine).
- `backend/app/routes/calendar.py`: minimal calendar CRUD (source=fitness) or dedicated `calendar` package.
- `backend/app/db/migrations/*`: Postgres schemas (pgvector present for optional embeddings).
- `frontend/src/features/fitness/*`: Fitness Settings, Morning Check, In-Workout UI, summaries.
- `scripts/*`: migration helpers, backfills, exports.

---

## Deliverables Checklist (Codex)
1) Data layer: migrations for fitness + calendar entities.
2) Endpoints: onboarding/plan/commit; readiness intake; workout start/log/adjust; push/skip; schedule week; calendar CRUD.
3) LLM tools: validated tool interfaces + JSON schemas; strict I/O validation.
4) Plan templates: JSON library (splits/phases/progression) + substitution matrix + time-cap rules.
5) Readiness engine: baselines, scoring thresholds, deterministic adjustment policies, change-log writer.
6) Scheduler worker: push/skip reflow with spacing/deload constraints.
7) In-workout state machine: server-side session state; rest timer semantics; PR detection; summary.
8) Notifications: ntfy messages for morning, pre-session, and reflow outcomes.
9) HealthKit bridge (iOS): permissions + ingest; web manual fallback.
10) UI (web/iOS): Fitness Home/Settings, Morning Check card, In-Workout screen.
11) Privacy controls: export/delete/reset; Health disconnect.
12) QA scenarios: green/yellow/red days; skip/push; equipment/unavailable; injury; offline logging; conflicts; deload.

---

## Phased Implementation Plan

### Phase 0 — Foundations & Scaffolding
- Migrations: `fitness_profiles`, `fitness_goals`, `fitness_plans`, `workouts`, `workout_logs`, `morning_readiness`, `calendar_events` (discrete instances; `source=fitness`; `metadata.workout_id`).
- Wire Postgres + pgvector (already planned in repo); keep Neo4j optional.
- Create packages: `backend/app/services/fitness/` and `backend/app/routes/fitness/`.
- Redis keys: `fitness:onboarding:{user}`, `fitness:session:{user}`, `fitness:timer:{session}`.
- Events enum and audit log strategy.
- Idempotency: `client_txn_id` on all mutations with de-dupe table.

### Phase 1 — Onboarding (Chat-First)
- Endpoints:
  - `POST /fitness/onboarding/start|step|save|end` (stateful via Redis + DB checkpoints)
  - `POST /fitness/plan/propose` → returns draft
  - `POST /fitness/plan/commit` → persists workouts + calendar bulk create
- LLM tools + schemas: `fitness.save_profile`, `fitness.save_goals`, `fitness.propose_plan`, `fitness.commit_plan`.
- Branching Q&A: minimal-next-question policy using tool state.

### Phase 2 — Plan Templates & Generator
- Templates: `backend/app/services/fitness/templates/*.json`
  - Splits: 3d FB, 4d UL/UL, 5–6d PPL, 2–3d KB-only, 3–4d hybrid.
  - Phasing: 4-week microcycles (3 build + 1 deload) or 5-week variants.
  - Progressions: strength (top-set @RPE8 + back-offs), hypertrophy (double-progression RIR 0–2), endurance (Z2 base + 1 quality).
- Substitution matrix by movement pattern and equipment feasibility.
- Time-cap rules: trim accessories → reduce sets → reduce rest; preserve main stimulus.
- Generator: produce `workouts[]` with blocks/exercises/sets×reps/intensity/RPE targets and default rest.

### Phase 3 — Calendar Integration (Minimal Service)
- Endpoints:
  - `POST /calendar/events` (create single events; avoid complex RRULEs)
  - `PATCH /calendar/events/:id` (move/update)
  - `POST /calendar/events/:id/complete`
  - `GET /calendar/events?source=fitness`
- Behavior: write explicit instances for each workout; link `metadata.workout_id`.
- Conflict policy: propose nearest viable slot; else mark “floating.”

### Phase 4 — Daily Readiness Engine
- Intake endpoint: `POST /fitness/readiness` (HealthKit values if present; else survey-only).
- Baselines: 14‑day EWMA for HRV and RHR; normalize vs bands.
- Score: HRV 40% + inv RHR 20% + sleep vs 7.5h 20% + survey composite 20%.
- Thresholds: Green ≥80, Yellow 60–79, Red <60.
- Adjustment policy:
  - Green: normal progression; optional +1 accessory
  - Yellow: −20–30% accessory volume; cap top-set RPE 8; maintain mains
  - Red: swap to recovery or move session
  - Time-available cap: keep mains, trim to fit
- Effects: persist readiness; patch today’s workout prescription and calendar description; store human-readable change-log.

### Phase 5 — In-Workout Flow & State Machine
- State: `idle → warmup → working_set ↔ resting … → summary → completed`.
- Endpoints:
  - `POST /fitness/workouts/:id/start`
  - `POST /fitness/workouts/:id/set` (log set; weight/reps/RPE/flags; returns next prescription)
  - `POST /fitness/workouts/:id/rest/start|end`
  - `POST /fitness/workouts/:id/substitute`
  - `POST /fitness/workouts/:id/complete`
- Features: warm-up builder; supersets/circuits; EMOM/AMRAP handling; tempo cues; autoregulation prompts; rest timer semantics; PR detection; summary report.

### Phase 6 — Scheduler & Auto-Reflow
- Triggers: user Push/Skip; detection of missed sessions.
- Constraints: 24–48h spacing for same pattern; deload cadence; no-go times.
- Algorithm: search next 7 days; place earliest valid; else set floating; recommend plan tweak on repeated misses.
- Worker: start with existing scheduler (APScheduler) patterns; keep interfaces Temporal-ready.
- Endpoints: `POST /fitness/workouts/:id/push|skip` → proposes slot; applies on confirm.

### Phase 7 — Notifications (ntfy)
- Morning 6:30: readiness summary and adjustment notice.
- Pre-session 45 min: reminder with duration.
- After rest: ready-for-next-set prompts.
- Missed session: propose two alternatives.

### Phase 8 — Privacy & Controls
- Endpoints: export JSON/CSV; delete plan; reset onboarding; disconnect Health.
- Storage: encrypt at rest; explicit Health permissions.

### Phase 9 — Web UI (MVP to Spec)
- Fitness Settings: Start New Journey / Change Goals.
- Morning Check card: shows score, adjustments, review CTA.
- In-Workout: Now Card, micro-log sheet, rest timer, supersets/circuits, substitution, summary.

---

## Data Model (Conceptual → Migrations)
- `fitness_profiles`: demographics, equipment, preferences, constraints, injuries
- `fitness_goals`: goal_type, targets, timeframe, status
- `fitness_plans`: metadata, phases, days/week, time-caps, status
- `workouts`: prescription (phase/week/dow, duration, blocks), status, `calendar_event_id`
- `workout_logs`: per-set actuals, timestamps, notes, flags
- `morning_readiness`: HRV/RHR/sleep/survey inputs, score, recommendation, adjustments
- `calendar_events`: title, start, end, `source=fitness`, status, `metadata.workout_id`
- Idempotency table: `client_txn_id`, `hash`, `applied_at`

---

## LLM Tooling & Guardrails
- Tools exposed: `fitness.save_profile`, `fitness.save_goals`, `fitness.propose_plan`, `fitness.commit_plan`, `fitness.adjust_today`, `calendar.bulk_create`, `calendar.move`.
- JSON schema validation on all tool requests/responses.
- LLM writes only via tools; never direct DB writes.
- Onboarding asks only branch-relevant questions.

---

## Read/Write Contracts (Endpoints, No Code)

### Plan Draft
- Input: `profile`, `goals`, `constraints`, `equipment`, `days_per_week`, `session_len_min`, `preferences`.
- Output: `plan_id (draft)`, `phases[]`, `weeks`, `days[]` → `workouts[{ title, duration_min, blocks[exercises, sets×reps/intensity/RPE, rest] }]`.

### Commit Plan
- Input: `plan_id (draft)`, optional edits (days/times/substitutions).
- Output: `workouts[]` persisted; `calendar.events[]` created; summary.

### Morning Readiness
- Input: `hrv_ms?`, `rhr?`, `sleep_hours?`, `energy 1..5`, `soreness 1..5`, `stress 1..5`, `time_available_min`.
- Output: `score 0..100`, `recommendation (keep|reduce|swap|move)`, `adjustments[]`, `message`.

### Workout Logging
- Input (per set): `workout_id`, `exercise_id`, `set_index`, `weight`, `reps`, `rpe?`, `notes?`, `flags?`.
- Output: `accepted`, `autoreg_suggestion?`, `next_set prescription`.

### Push/Skip
- Input: `workout_id`, `reason`, `constraints?`.
- Output: suggested slot or floating; updated calendar/workout status.

### Calendar
- `POST /calendar/events`, `PATCH /calendar/events/:id`, `POST /calendar/events/:id/complete`, `GET /calendar/events?source=fitness`.

---

## Events & Observability
- Key events: 
  - `FITNESS.ONBOARDING.START/STEP/SAVE/END`
  - `FITNESS.PLAN.PROPOSED/COMMITTED/UPDATED`
  - `FITNESS.CALENDAR.EVENT.CREATED/MOVED/COMPLETED`
  - `FITNESS.READINESS.RECEIVED/SCORED/APPLIED`
  - `FITNESS.WORKOUT.STARTED/SET.LOGGED/REST.STARTED/REST.ENDED/SUBSTITUTED/SKIPPED/COMPLETED`
  - `FITNESS.SCHEDULE.REFLOW.REQUESTED/PROPOSED/APPLIED`
- Tracing: wrap plan commit and reflow jobs.

---

## Non-Functional Requirements
- Latency: <150 ms set-log → next prescription (cached + lean payloads).
- Offline: in-workout logging and timers; server reconciliation on reconnect.
- Resilience: idempotent mutations; optimistic UI + reconciliation.
- Security: encrypted at rest; scoped Health permissions.

---

## Acceptance Tests (Scenarios)
- AT-1 Onboarding: Start → tailored Qs → plan proposed → commit → events created, Fitness does not re-run onboarding.
- AT-2 Readiness Green: high HRV; plan unchanged; +accessory suggestion.
- AT-3 Readiness Yellow: volume trimmed; top-set capped; visible change-log.
- AT-4 Readiness Red: recovery/move; calendar updated; user notified.
- AT-5 Push/Skip: nearest valid slot or floating.
- AT-6 In-Workout: warm-up → straight sets with timers → superset → substitution → summary saved.
- AT-7 Offline: 3 sets offline → reconcile without duplication.
- AT-8 Privacy: export fitness data; delete plan; disconnect HealthKit.

---

## Milestone Sequencing (Lean Path)
1) Migrations + skeleton routes/services + calendar CRUD.
2) Plan templates + propose/commit workflow with calendar bulk create.
3) Morning readiness intake + deterministic adjustments.
4) In-workout state machine + logging + summary + event completion.
5) Push/Skip + reflow worker + conflicts.
6) Notifications + privacy exports/deletes.
7) Frontend Fitness pages aligned to contracts.

---

## Repository Conventions
- Python: PEP8, type hints where practical; HTTP handlers in `backend/app/routes`, business logic in `backend/app/services`.
- Tests: root `test_*.py` integration scripts hitting running APIs (configurable `BASE_URL`).
- Data/logs: avoid committing large artifacts; use `uploads/`, `logs/`.


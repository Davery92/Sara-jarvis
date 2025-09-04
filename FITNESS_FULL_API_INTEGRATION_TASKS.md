# Fitness Module — Full API Integration Tasks (Full API Only)

Scope: Integrate the Fitness module end-to-end into this FastAPI/Postgres stack, align with existing services, and remove all dev SQLite paths. No code here — just concrete tasks mapped to this repo.

## A) Map To Current Code
- Backend: `backend/app`
  - Models: `models/fitness.py`, `models/calendar.py`, `models/user.py`
  - Services: `services/fitness/{generator.py,readiness.py,state_machine.py,scheduler.py}`, `services/notification_service.py`
  - Routes: `routes/fitness.py`, `routes/calendar.py`
  - Infra: `core/{config.py,llm.py}`, `db/{session.py,base.py}` (pgvector)
- Data: Postgres + pgvector only (no SQLite dev path)
- Redis: live state (onboarding and in-workout)
- Neo4j: optional enrichment (defer if not needed for MVP)

## B) Data & Migrations (Alembic)
- Confirm/extend DDL for: `fitness_profile`, `fitness_goal`, `fitness_plan`, `workout`, `workout_log`, `morning_readiness`, `fitness_idempotency`.
- Calendar: ensure `event` has `source='fitness'`, `metadata.workout_id`, indexes on `(user_id, starts_at)`.
- Constraints: FK from `workout.calendar_event_id -> event.id`; cascade deletes on user.

## C) Backend Services
- Generator: finalize plan templates under `services/fitness/templates/*`; implement `propose_plan(profile, goals)` returning Draft Plan JSON.
- Commit: persist workouts; call calendar bulk create; link `workout.calendar_event_id`.
- Readiness: complete scoring in `services/fitness/readiness.py` (baselines, thresholds); apply adjustments to today’s workout and event description; write changelog.
- State machine: ensure `services/fitness/state_machine.py` supports warmup/sets/rest/supersets/intervals; expose next-step contract.
- Reflow: in `services/fitness/scheduler.py` implement push/skip reflow respecting spacing/constraints; mark floating when needed.
- Notifications: use `notification_service.py` + ntfy topics for morning, pre-session, and reflow.
- Redis: ephemeral session state for onboarding and active workouts.

## D) API Endpoints (routes)
- Fitness (`routes/fitness.py`):
  - Onboarding: start/save step/end; profile/goals persistence; return Draft Plan.
  - Plan: `propose`, `commit`, `update`.
  - Readiness: morning intake → score + adjustments.
  - Workout flow: start, next, log set, substitute, complete; push/skip.
- Calendar (`routes/calendar.py`): add `bulk_create`, `move`, `complete`, `list?source=fitness`; conflict detection + suggestions.
- Tooling: JSON schemas and validators for LLM tools; wire into `app.tools.registry` (no direct DB writes from LLM).

## E) Frontend (high-level tasks)
- Settings entry: Start New Journey / Change Goals.
- Morning Readiness card: intake + summary of adjustments.
- In-Workout UI: Now Card, micro-log sheet, rest timer, supersets/circuits, summary.
- Notifications: surface ntfy and in-app banners.

## F) Remove Dev SQLite (always full API)
- Delete `backend/app/main_simple.py`; remove any imports/usages.
- Purge SQLite conditionals/fields and scripts: `run-local.sh` SQLite lines, local `sara_hub.db`, README links to `main_simple.py`.
- Update docs to only use: `uvicorn app.main:app --reload` and Docker Compose.
- Fix tests importing `main_simple` (e.g., `test_dream_cycle.py`) to hit full API/services.

## G) Validation & Tests
- Run Alembic to head; verify pgvector extension and embeddings.
- Scenario tests: onboarding → commit → events created; green/yellow/red readiness; push/skip reflow; in-workout logging; privacy export/delete.
- Non-regression: notes/docs search, scheduler startup, knowledge graph unaffected.

## H) Acceptance Checklist
- Full API boots; no SQLite references remain.
- Workouts scheduled to calendar with links; readiness adjusts today’s session; push/skip reflows; notifications sent.
- In-workout flow completes with logs and summary; exports work; tests green.


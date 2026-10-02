# Sara Fitness Coach Implementation Plan

Planning baseline: repository inspected on 2026-10-01. This document is a blueprint for a future coding agent; no Fitness Coach code was implemented during its preparation. Source inspection, migration inspection, and the checked-in schema fixture establish the findings below. Production database contents, actual model capabilities, and deployed source/schema parity were not probed.

**Path convention:** a repository path without a `PROPOSED:` prefix exists in the inspected tree. Every `PROPOSED:` path names a new file or directory; create it only in its assigned step. API paths and table names are contracts, not filesystem paths. Migration identifiers below are logical labels, not reserved Alembic revision numbers. Recheck the head before assigning a real revision.

## 1. Executive Summary

Extend Sara's existing fitness module into an ongoing bodybuilding, powerlifting, powerbuilding, nutrition, recovery, and progress coach. This is a consolidation and extension project: Sara already logs food, recovery, weight, training programs, phases, templates, individual sets, PRs, and progress photos. Replacing these with a parallel fitness database or another assistant would lose working features and fragment truth.

The core flow is **owned structured records → deterministic application analytics → versioned Fitness State → Qwen interpretation → reviewable recommendations**. Numeric facts never come from reconstructed chat history. Current goals and historical targets drive interpretation. Missing data remains unknown. Coaching decisions preserve the state, metrics, evidence references, and model/template versions that explain them.

The first intelligent milestone is an on-demand Weekly Coach Review. Foundational APIs and set logging work when all LLM endpoints are unavailable. Proactive behavior, vision comparisons, curated sports-science RAG, and automated programming follow incrementally. All phases support multiple users, despite existing owner-specific code.

A prerequisite phase repairs authentication and source-of-truth gaps. In particular, `backend/app/routes/fitness.py:get_current_user_id()` returns `SOLO_USER_ID`/`default-user`; workout v2 imports the same dependency. These routes currently do not derive identity from the requester. This must be corrected before shipping new athlete data.

## 2. Current Sara Architecture

### 2.1 Runtime and entry points

- Backend ASGI application: `backend/app/main_simple.py`, still containing `SimpleLLMClient`, `/chat/stream`, `/chat/models`, voice handlers, runtime settings, and lifecycle hooks. Both backend Dockerfiles run `uvicorn app.main_simple:app`. Feature routers live in `backend/app/routes/` and are mounted here. Many older mounts use try/except; new mounts must fail visibly and sit outside catch-all registration blocks.
- Web bootstrap: `frontend/index.html` → `frontend/src/main.tsx` → `frontend/src/App.tsx`. React 18/Vite, TypeScript, Tailwind. `main.tsx` supplies TanStack Query and `AuthProvider`.
- Additional consumers: `ios-app/` includes HealthKit synchronization, workout UI, progress-photo UI, Watch contracts, and native workout modules. Fitness backend changes are cross-client changes even when the main deliverable is web.
- `docker-compose.dev.yml` defines PostgreSQL/pgvector PG16, Neo4j, Redis, MinIO, embedding service, API, web, and Celery lanes. `backend/Dockerfile.dev` and `backend/Dockerfile` define backend containers. Do not start this API directly on the host.
- Production is separately pinned through `docker-compose.incident-recovery.yml` and `scripts/sara-prod`; read `RECOVERY.md` before deployment work. Source changes do not imply deployed changes. Never use an unqualified compose command or rebuild the production working-tree service to test fitness.
- No active NATS/JetStream or Temporal wiring was found in backend source/dependencies or the authoritative compose topology. Redis is the actual Celery broker and pub/sub transport. APScheduler remains in a few older service helpers; the standard periodic job system is database-backed Celery Beat.

### 2.2 Database, models, migrations, configuration

- `backend/app/db/base.py`: SQLAlchemy declarative `Base`, synchronous engine, pooled `SessionLocal`. `backend/app/db/session.py:get_db()` yields a request session; `get_async_session_factory()` supplies async sessions and rebuilds the engine across Celery event loops/processes.
- ORM: SQLAlchemy, mixed with substantial parameterized SQL using `sqlalchemy.text`. Fitness has many raw-SQL tables and route-local Pydantic models rather than a complete ORM model module.
- `backend/app/models/` holds modular models such as `User`, `UserSettings`, `UserProfile`, `ProgressPhoto`, and `HealthWeeklyReport`. **Two declarative bases exist:** `main_simple.py` also creates a Base. `backend/alembic/env.py` targets the monolith Base. Do not casually merge bases or trust autogenerate to see every new model. Hand-reviewed explicit migrations are the default here.
- Alembic: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/`. Inspected latest chain ends at `158_reminder_delivery_state`. Historical scripts in `backend/migrations/` and root backend one-shots explain original tables but must not be rerun: some contain production-shaped fallback connection strings.
- Fresh `alembic upgrade head` is not a proven empty-database bootstrap. `backend/scripts/provision_test_schema.sh` documents pre-Alembic gaps and provisions `backend/tests/fixtures/sara_hub_schema.sql`. This fixture is schema evidence, not proof of current production parity.
- `backend/app/core/config.py:Settings` is Pydantic Settings; `backend/app/core/llm_config.py:LLMConfig` reads LLM environment configuration. Runtime `app_settings` rows override several LLM selections. `backend/app/core/feature_flags.py` provides existing rollout switches. Read `.env.example`, never publish `.env` values.
- `backend/app/core/timezone.py` uses America/New_York for existing user-facing dates. Food `logged_at` is naive ET; other legacy timestamps include naive UTC; new timestamps should be aware UTC plus an explicit athlete local date/timezone. Existing frontend `frontend/src/utils/dateUtils.ts` uses browser-local dates, which can disagree with server ET.

### 2.3 Authentication, users, permissions

- `backend/app/models/user.py:User` maps `app_user`: string UUID, email, password hash, creation timestamp.
- `backend/app/routes/auth.py` handles signup/register/login, cookie/Bearer flows, and logout. Tokens carry JWT subject and per-issuance `jti`; `backend/app/core/auth.py` checks durable revocation in `revoked_token` and fails closed on revocation-store failure.
- `backend/app/core/deps.py:get_current_user()` accepts cookie, Bearer, or registered `X-Device-Token` and returns `User`. `get_current_user_sync()` accepts JWT only; `get_streaming_user()` authenticates without holding a database session for an SSE lifetime. Do not interchange their scopes accidentally.
- `backend/app/models/user_role.py:UserRole` maps `app_user_role`; admin checks are route-specific, e.g. `backend/app/routes/automation_admin.py:require_admin()`. There is no universal fitness permission layer. Normal athlete access should be strictly owner-based, not an admin exemption.
- Critical divergence: `backend/app/routes/fitness.py:get_current_user_id()` is a solo-owner stub. `backend/app/routes/workout_v2.py` imports it. No application override of this dependency was found. Passing credentials from the web does not fix a route that ignores those credentials.
- Authenticated alternatives exist: `backend/app/routes/fitness_inline.py` recovery routes, `backend/app/routes/health_metrics.py`, and `backend/app/routes/progress_photos.py`. Their overlapping writers must converge on shared services rather than drift.

### 2.4 Existing fitness data and behavior

| Existing concept | Actual implementation and significance |
|---|---|
| Nutrition | `backend/app/routes/fitness.py`: food-log CRUD, diary, copy/repeat, saved meals, goals, recipes. `food_log` has totals and `detailed_items`; `backend/app/schemas/food_item.py` defines a richer shared item contract. Existing food totals are app-calculated where detailed items exist. |
| Daily summaries | `fitness_daily_log` summarizes counts/macros. Original definition: `backend/migrations/add_fitness_daily_log.py`; route helper `update_daily_log()` updates it. It is a projection, not reliable evidence that a day is completely logged. |
| Recovery and health | `daily_recovery_log` has daily HRV, heart rate, sleep, soreness, weight/units, notes. `health_metric` has metric type, value, observation time, source, metadata and dedup index; created by `backend/alembic/versions/029_health_monitoring_system.py`. |
| Weight | `weight_trend` created in `backend/alembic/versions/018_fitness_overhaul.py`; `/weight` applies an alpha=.1 EWMA and compares against the seventh previous reading, not necessarily seven calendar days ago. Separate recovery weight also exists. |
| Program/block | `fitness_program`, `fitness_phase`, `fitness_template`, `template_exercise`. Phase has dates, goal, training/rest macros, steps and deload settings. Template has JSON serialized in TEXT plus related normalized exercise rows. |
| Phase truth | `backend/app/services/phase_resolution.py:get_effective_phase()` resolves the dated phase of the approved active program. `backend/app/services/plan_adjust.py` trims/splits/shifts phases on explicit program changes. Preserve this timeline model. |
| Plan import | `backend/app/services/plan_importer.py` parses a supplied training document into JSON with local Qwen, then applies only after preview/confirmation through `/import-plan/parse` and `/import-plan/apply`. Reuse this draft/application separation; new target history must also cover importer writes. |
| Daily prescription | `backend/app/services/training_day.py` resolves scheduled templates/session status/day overrides. `backend/app/services/workout_prescription.py` resolves program week and text-based prescriptions; `backend/app/services/set_plan.py` resolves structured week/set prescriptions. |
| Exercise identity | Global `exercise_library` has names, movement patterns, JSON muscles/equipment and metadata. `backend/app/services/exercise_library_seed.py` derives rows by existing names and keyword classification. `backend/alembic/versions/093_workout_log_exercise_fk.py` adds a nullable canonical shadow FK while retaining legacy text `exercise_id`. Aliases are not a robust normalized identity system today. |
| Workout | `workout_session` is planned/calendar-linked; `active_workout_session` holds current versioned state and snapshot; `workout` is another legacy aggregate; `workout_log` rows represent performed sets. Keep their compatibility relationships explicit. |
| Mutation protocol | `backend/app/services/workout_command_service.py:WorkoutCommandService` implements command replay, session locks, expected version, sets, corrections, voiding, rest, proposals, policies, event sync. `backend/app/services/workout_session_service.py` provides compatibility adapters. Logging commits before optional LLM feedback. |
| Flexible sets | `backend/alembic/versions/125_flexible_workout_sets.py`: working/warmup/drop, group/parent links, corrections and voids. `backend/app/services/workout_recalc.py` derives completion and volume, and withdraws PRs. Warmups/drop segments do not consume prescribed working slots. |
| PR/progression | `exercise_pr`; `backend/app/services/progressive_overload.py` computes deterministic suggestions/recovery adjustment; command service stores proposals in `workout_adjustment_proposal` and approved bounds in `workout_approved_policy`. |
| Photos | `backend/app/models/progress_photo.py:ProgressPhoto`, `backend/app/routes/progress_photos.py`; image + thumbnail in MinIO, metadata owned by user, optional text critique. iOS already has `ios-app/src/services/progressPhotos.ts` and `ios-app/src/components/fitness/views/ProgressPhotosView.tsx`. No equivalent web fitness photo view was found. |
| Weekly report | `backend/app/models/health_weekly_report.py:HealthWeeklyReport`, `backend/app/services/health_consolidation/`, `backend/app/tasks/health_weekly.py`, `backend/app/routes/health_reports.py`. Three LLM stages analyze app-collected data; stores stats/markdown/model/status and a linked note. Current task defaults to David/first user if no ID. |

General profiles in `backend/app/models/profile.py` include `UserProfile.profile_data`, autonomy/communication/channel settings, reflection/privacy settings and activity logs. `backend/app/models/user_settings.py` holds preferences and vision model/endpoint. General goal infrastructure exists in `backend/app/services/goal_manager.py` and `backend/app/tools/goals.py`; it is not historical athlete target resolution. Habit-related tests/older systems exist, but no normalized relational athlete-measurement or complete athlete-profile table was found in the schema fixture. Do not reuse habituation of notifications as exercise adherence.

### 2.5 LLM, prompts, tools, memory, context

- `backend/app/main_simple.py:SimpleLLMClient` supports provider-specific chat and OpenAI tool schemas, streaming tool dispatch, and tool-result messages. `backend/app/core/app_state.py` holds model catalog/runtime chat defaults. User-selected chat can differ from local background inference.
- Qwen3.8-27B is the local default in `backend/app/core/config.py`, `backend/app/core/llm_config.py`, and compose environment. Chat and background lanes differ. Persisted settings and catalog `base_url` can override environment configuration. Document the **resolved** model for each review, not the compile-time default. The current chat generation mode defaults to `ar`; repository code records tool-bearing MTP corruption. Do not enable speculative generation for new fitness tools without separate parity evidence.
- Background work: `backend/app/core/llm.py:get_background_llm_client()` with persisted settings and failover; `backend/app/services/llm_broker.py` maps existing capability classes to settings. It is an incremental abstraction, not universal: chat still has its own path; its inspected capability map does not yet contain a working vision capability.
- Stable persona: `backend/app/prompts/chat_system_prompt.py:build_chat_system_prompt()`. Fitness legacy persona: `backend/app/prompts/fitness_system_prompt.py`; application skill loading/injection: `backend/app/skills/loader.py`, `backend/app/skills/injector.py`. Existing `backend/skills/fitness-coaching/SKILL.md` contains owner-specific wording and tells Sara to search memory for workouts; that instruction conflicts with structured-data coaching and must change later.
- Main chat reads cached `backend/app/services/context_snapshot.py`, extended signals, query-specific `backend/app/services/memory_recall.py`, intent graph, and `backend/app/services/world_state/chat_facts.py`. `backend/app/services/chat_assembly.py` enforces live-context allocation, with priority for dialogue corrections and core current-world facts; `backend/app/services/context_budget.py` implements budgets. Adding a giant appended fitness block can silently lose important state.
- `backend/app/services/fitness_context.py:get_fitness_context()` builds today's nutrition/prescription text from SQL and dated phase resolution. It is used directly by voice and by `backend/app/services/world_brief.py` for current body/training context that main chat consumes. It is not a comprehensive deterministic athlete-state contract.
- Conversation history: `episode` and conversation IDs; main chat restores database history if client history is missing/partial, removes overlaps, and separately recalls long-term traces. Incremental enrichment and watermark logic live in `backend/app/tasks/episode_enrichment.py` and related services.
- Tools: `backend/app/tools/base.py:BaseTool`, `ToolResult`; `backend/app/tools/registry.py:ToolRegistry`, `execute_tool(name, user_id, parameters, context)` and category registrations. Every tool executes `async execute(self, user_id, **kwargs)` and returns `ToolResult`. User identity is supplied by orchestration, never a model argument. Tool schemas are JSON Schema; Pydantic is used for API and contracts.
- Selection: `backend/app/services/tool_retrieval.py` bounds the tool menu (35 max at inspection). Existing `fitness_summary`, `food_log_*`, `workout_*`, `recovery_log_*`, program/phase/template tools should be extended before inventing redundant tools.
- Mutation controls: `backend/app/tools/mutating.py`, `backend/app/services/tool_mutation.py`, `operation_contract.py`, `reference_resolution.py`, `target_authorization.py`, `action_receipt_service.py`, `outcome_grounding.py`. These are separate boundaries for intent, operation, owned target, committed receipt, and truthful confirmation. New action tools need all relevant classifications and contracts, not just a prompt warning.
- Structured LLM output is partial: weekly health `_llm_json()` requests JSON then parses fenced/prefixed text; other services parse their own JSON. No universal guarantee of provider-enforced strict schemas was established. Add Pydantic validation at the coaching boundary regardless of provider response-format support.
- Memory: `backend/app/models/episode.py`, `memory_trace.py`, `memory.py`; `backend/app/services/memory_service.py`, `memory_recall.py`, `working_memory.py`. pgvector similarity, composite ranking, reranking, Redis working sets, and consolidation coexist.
- Neo4j PKG: `backend/app/services/personal_knowledge_graph.py`, `pkg_realtime_extractor.py`, `pkg_context_provider.py`, with `backend/app/models/pkg_embedding.py` as pgvector shadow. PKG explicitly refuses measured body facts because `health_metric` is their authority. Some target-like intentions are currently permitted; the fitness extension must prevent those from competing with approved effective-dated targets.
- `backend/app/services/body_state_projection.py` describes **Sara's operational services**, not athlete physiological recovery. Do not attach athlete state to this operational contract merely because it is named BodyState.

### 2.6 Storage, events, scheduling, notifications

- Object abstraction: `backend/app/services/docs_ingest.py:DocumentProcessor.store_file()/get_file()/delete_file()` uses configured shared `sara-docs` bucket and random keys. It also extracts document text. It is a modest storage abstraction, not an ownership layer; route/model ownership protects bytes. Its current client forces insecure MinIO transport and photo decoding has permissive fallback behavior; harden deliberately.
- Documents: `backend/app/models/doc.py:Document` plus native-vector `DocChunk` (`doc_chunk`); `backend/app/models/document_chunk.py:DocumentChunk` maps another `document_chunk` table with TEXT embeddings. Current `backend/app/routes/documents.py` writes the latter and `backend/app/tools/documents.py` casts TEXT to vector for retrieval. Both tables exist in the fixture. Reuse extraction/storage/embedding, but choose a native-vector evidence-chunk authority explicitly.
- Redis: Celery broker/result backend; `backend/app/services/event_bus.py` publishes user-keyed fitness/health/etc. events; `unified_context.py` and `context_snapshot.py` cache state; search and working memory use caches. Pub/sub is best effort, not durable ingestion.
- Durable domain spine: `backend/app/services/world_state/writer.py:append_world_event()` writes in the caller transaction and dispatches after commit; workout command service already uses it. `backend/app/models/event_outbox.py` is a Neo4j sync outbox, not a generic notification queue; do not repurpose it blindly.
- Scheduling: `backend/app/celery_app.py` registers task modules/routes; `backend/app/celery_beat/db_scheduler.py:DBScheduler` reads `backend/app/models/scheduled_job.py:ScheduledJob`, reloads about once a minute, supports interval/cron and per-row timezone. Queue names are contracts: reuse health for coaching, low_priority for research.
- `backend/app/routes/schedules.py` exposes global schedule settings to authenticated users, with arbitrary kwargs edits; `scheduled_job` has no owner column. Do not expose per-athlete reminders by giving ordinary users control of global task rows.
- `backend/app/celery_signals.py` records execution; Beat's success means dispatch, not successful task completion. New fitness jobs need their own durable completion/error state.
- Notifications: `backend/app/services/unified_notification.py` implements category normalization, preferences, topic dedup, cooldowns, attention/inbox routing, interruptibility and Expo push. `backend/app/services/notification_service.py` wraps it; some wrappers use owner defaults or bypass attention. `backend/app/models/notification_preference.py`, `push_token.py`, `backend/app/routes/push_tokens.py` support channels.
- Autonomous mouth: `backend/app/services/say_candidate.py:create_candidate()` → judge → compose → review/deliver task flow, with TTL/topic dedup. Some module comments are stale; judge/compose/tasks are actually wired. Favor this flow for unsolicited coaching. Explicitly requested reminders/results may use the existing notification delivery path according to their intent, without bypassing user quiet/notification settings.
- Legacy `NTFYService` and in-process `NotificationScheduler` remain in `main_simple.py`; primary reusable mobile delivery is unified pipeline/Expo, not a new NTFY subsystem. Do not duplicate existing daily brief or weekly health pushes.

### 2.7 Frontend and tests

- `frontend/src/navigation/views.ts` defines `AppView` and `/fitness`; `App.tsx` uses view state/browser path mapping for main shell navigation. `frontend/src/main.tsx` does have an outer React Router BrowserRouter: `/overlay/:kind` is a standalone route and the wildcard hosts App. Extend fitness inside the shell view-state convention, not by replacing that outer router. `frontend/src/components/shell/ShellWorkspaceContent.tsx` hosts existing surfaces.
- `frontend/src/components/fitness/FitnessSection.tsx` already contains dashboard/program manager and subviews for plan, programs, templates, recovery, cardio, nutrition, food, workouts, notes; it owns local tabs.
- Existing workout components: `WorkoutLogEnhanced.tsx`, `ActiveWorkout.tsx` use legacy fitness endpoints; current web workflow is not automatically a v2 cross-device controller. Preserve adapters while moving the fast active logging UI to v2.
- API: `frontend/src/config.ts:APP_CONFIG.apiUrl`; `frontend/src/api/client.ts` wraps Axios with credentials; older fitness components use credentialed fetch directly. `frontend/src/utils/api.ts` is another helper. New typed fitness client should follow the existing API base/credentials and normalize errors.
- Server state: TanStack Query is installed and provided. Zustand stores in `frontend/src/stores/` cover auth/chat/notes; fitness primarily uses local React state/effects. Use Query for fitness server state and local reducer/state for transient set inputs, not another application-wide store.
- UI: `frontend/DESIGN_LANGUAGE.md` specifies dark slate/teal, flat sections, one containment level and primary action, understated error/status treatment; reusable primitives in `frontend/src/components/ui/`. Recharts already installed; react-hook-form/Zod available. No new chart library needed.
- Backend tests: `backend/pytest.ini`, `backend/tests/conftest.py`, `backend/tests/env_guard.py` require disposable targets and neutralize real dispatch. SQLite/fakeredis/mocks support units; real PostgreSQL tests cover locks/JSONB/indexes and world-state integration. Test instructions embedded in older test docstrings may still mention production/dev containers; follow the disposable guard instead.
- Existing useful tests: `backend/tests/test_workout_command_service.py`, `test_workout_flexible_sets.py`, `test_workout_set_correction.py`, `test_workout_approval_enforcement.py`, `test_workout_session_legacy_compat.py`, `test_workout_world_state_integration_pg.py`, `test_health_world_state_integration_pg.py`, `test_health_data_accuracy.py`, `test_recovery_score_hrv_outlier.py`, `test_fitness_system_prompt.py`, `test_plan_adjust.py`, `test_tool_mutation.py`, `test_target_authorization.py`, `test_unified_notification.py`, `test_db_scheduler_beat_double_fire.py`.
- Frontend: `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`, Testing Library, jsdom. `frontend/package.json` has test/build/lint scripts; build is Vite, not a guaranteed TypeScript typecheck.
- Workout parity: `ios-app/scripts/check-workout-contract-parity.mjs` checks Python routes/service, iOS TypeScript, Watch Swift, and phone Swift copy. It does not prove web UI consumes that contract; test web separately.

## 3. Existing Components We Can Reuse

| Component | Location | Fitness Coach use and caveat |
|---|---|---|
| Authenticated subject | `backend/app/core/deps.py`, `backend/app/models/user.py` | Resolve the actor for all routes; supply explicit ID to jobs/tools. Replace solo stub without inventing another user table. |
| Request/job sessions | `backend/app/db/session.py` | Shared session factories; explicit unit-of-work, transaction ownership, no session across network waits. |
| Program timeline | `backend/app/services/phase_resolution.py`, `backend/app/services/plan_adjust.py` | Current training phase/plan changes. Add historical revisions rather than override this authority. |
| Training-day resolver | `backend/app/services/training_day.py` | Today and each historical date's schedule/day type. Snapshot prescribed sessions before mutable schedules can alter past adherence. |
| Plan importer | `backend/app/services/plan_importer.py`, `frontend/src/components/fitness/PlanImporter.tsx` | Existing parse/preview/apply flow; strengthen typed validation/history rather than invent another import pipeline. |
| Prescription/progression | `backend/app/services/set_plan.py`, `workout_prescription.py`, `progressive_overload.py` | Reuse pure prescription calculations; do not let LLM write expected next load directly. |
| Workout commands | `backend/app/services/workout_command_service.py`, `workout_recalc.py` | Single mutation path, offline retries, corrections, PR retraction; extend additively. |
| Food/recipe contracts | `backend/app/schemas/food_item.py`, `backend/app/services/recipe_nutrition.py`, `backend/app/routes/food_database.py` | Existing logs/catalog/totals, preserving item provenance and estimated nutrition flags. |
| Recovery calculation | `backend/app/services/recovery_score.py:compute_readiness()` | Preserve established score when enough inputs exist; wrap with coverage/unknown state. Today an empty object yields 100: never call that evidence of excellent recovery. |
| Canonical measurements | `backend/app/routes/health_metrics.py`, `backend/app/services/health_metric_mirror.py` | Existing integration ingestion and source stamps; extend supported types/units and deterministic resolution. |
| Profile/preference storage | `backend/app/models/user_settings.py`, `backend/app/models/profile.py` | General communication/privacy preferences remain here; athlete fields use a dedicated typed extension. |
| Photo storage | `backend/app/models/progress_photo.py`, `backend/app/routes/progress_photos.py`, `backend/app/services/docs_ingest.py` | Extend existing photo metadata/API and object lifecycle; no second photo table for the same original image. |
| Embeddings/text retrieval | `backend/app/services/embedding_service.py`, `embeddings.py`, `search_service.py`, `backend/app/models/doc.py` | Extraction, 1024-dimensional embeddings, reranking/native-vector chunks; curation and evidence metadata must be added. |
| Weekly report artifact | `backend/app/models/health_weekly_report.py`, `backend/app/services/health_consolidation/runner.py`, `backend/app/routes/health_reports.py` | Keep existing health reports working; share analytics and optionally link a Coach Review. Do not overwrite historical reports with a new output schema. |
| Domain events | `backend/app/services/world_state/writer.py`, `event_bus.py` | Durable thin events and best-effort cache invalidation. Numeric fitness truth stays in owned records. |
| Recurring jobs | `backend/app/celery_app.py`, `backend/app/celery_beat/db_scheduler.py`, `backend/app/models/scheduled_job.py` | Global sweep/research schedules; resolve per-user preferences in the task. |
| Delivery controls | `backend/app/services/say_candidate.py`, `unified_notification.py`, `backend/app/models/notification_preference.py` | Propose one bounded missing-data request/review announcement; obey TTL, opt-in, quiet and dedup. |
| Action audit | `backend/app/services/action_receipt_service.py`, `outcome_grounding.py` | Real record writes/accepted proposals produce durable receipts. A generated recommendation is not a completed target change. |
| Existing fitness surface | `frontend/src/components/fitness/FitnessSection.tsx` | Add athlete settings/Today/Coach/Progress within existing navigation, keeping food/training screens working. |

## 4. Architectural Decisions

1. **One relational fitness subsystem inside the existing API.** Add services under the existing fitness service directory. Use PostgreSQL for targets, programs, workouts, measurements, reviews and source provenance. No microservice/new database/broker/vector store.
2. **Body observations have one authority.** `health_metric` owns physical observed numbers; extend with explicit units and provenance. Recovery/weight trend are compatibility projections. Subjective daily responses belong to extended `daily_recovery_log`; meals to `food_log`; sets to `workout_log`. No new table that independently stores weight/sleep/macros again.
3. **Preserve the approved phase timeline.** Goals gain a typed dated athlete-goal history; nutrition targets gain append-only **revisions of the existing phase/default target**, not a competing override table. Current phase selection remains `get_effective_phase()`. One target resolver used by all consumers resolves phase → applicable approved revision → explicit legacy fallback → unknown. New edits to phase macros must enter that resolver's history atomically.
4. **History is valid time plus provenance.** Goals/targets use half-open effective-date ranges; existing phase ends are inclusive and must be adapted explicitly. Preserve original records, source IDs, corrections/revisions. Use recorded-at for observations, not ingestion/created-at as the event date. Backfills must not invent when a target began.
5. **Use the workout aggregate already running.** Active session + snapshot + command rows remain mutation authority. Planned sessions link to active sessions; a new exercise-performance child adds stable occurrence IDs and pain fields, while existing set rows remain performed sets. Do not create a second parallel session/set system.
6. **Canonical exercise variant is the comparison identity.** Aliases resolve to an existing `exercise_library` row; distinct equipment/ROM/variation do not collapse into a shared PR. Add scoped aliases and explicit parent/variation metadata. Do not trust fuzzy name matching for irreversible historical reclassification.
7. **Deterministic analytics, one versioned state.** Services build unit-tagged nullable metrics with date ranges, source counts, coverage and limitations. UI, tools, review, voice/world brief all consume this projection. Qwen interprets values and selects suggestions; it does not calculate trends or diagnose disease.
8. **Redis is expendable.** Cache Fitness State by user/as-of/date/timezone/schema/data revision with short TTL. Correctness must survive Redis outages and missed pub/sub invalidations; immutable review inputs never come solely from cache.
9. **MinIO stores photo bytes; metadata owns access.** Extend existing photo model; preserve old random keys; scoped new keys are desirable but not a reason to migrate every object. Owner checks protect full images, thumbnails, analysis and comparisons. No photo bytes in prompts/audit tables/logs.
10. **pgvector for curated evidence only.** Reuse native `doc_chunk` plus sports-science metadata/chunk annotations, choosing it deliberately over TEXT-cast `document_chunk`. Do not index accepted evidence as personal episodes or automatically extract it into PKG.
11. **Neo4j retains stable qualitative knowledge.** Preferences and stable relationships can stay in memory/PKG with provenance. Exclude raw body observations, target revisions, workouts and review numeric claims. Never rely on globally owner-centered PKG queries for cross-user athlete facts without a scope audit.
12. **No second autonomous brain.** Fitness jobs generate state/review artifacts/candidates within existing scheduling and delivery. Weekly Coach is a domain service, not a new independent agent/persona orchestrator.
13. **Actions are separated from recommendations.** A Weekly Review is read-only. Accepting a material nutrition/program change is a separate owner-authenticated, validated, idempotent action against the review's revision preconditions. Existing workout proposal policies remain narrowly bounded.
14. **Timezone is a data contract.** Athlete timezone defaults to Sara's existing ET; calendar dates are athlete-local. Store new timestamps aware UTC and explicit local date. Convert legacy ET wall-clock and source-specific UTC conventions in one data-access layer; test DST/travel/midnight.
15. **Small additions first.** No enormous exercise catalog, novel readiness algorithm, automatic diet adjustments, meal-photo estimates, photograph body-fat estimates or broad medical rules engine in foundation phases.

## 5. Proposed Fitness Domain Model

All new owned rows use string UUIDs consistent with `app_user`, foreign keys with deliberate deletion policy, `created_at/updated_at` aware UTC where mutable, and `(user_id, date/time)` indexes. Every child relationship must validate that parent belongs to the same user; an FK to a UUID alone does not enforce ownership. Default units: kg/cm internally for new physical measures, seconds/minutes for time, grams for macros; existing lbs/integer-load contracts stay compatible through adapters. Numeric precision must support 0.25kg/2.5lb changes without truncation.

### 5.1 Athlete, goals and targets

| Entity / status | Responsibility, fields, relationships and historical behavior |
|---|---|
| AthleteProfile — NEW | `fitness_athlete_profile`, unique `user_id`; height_cm, optional date_of_birth, optional calculation_sex with unknown/prefer-not-to-say, training_experience_years/level, timezone, unit preferences, available_days, preferred_duration_minutes, equipment, exercise preferences/exclusions by canonical ID, dietary restrictions/preferences, supplements, coaching style, monitoring consent. Current weight is resolved from observations, never a copied authoritative field. Stable profile can be edited; row version and sparse change audit capture material edits; historically relevant constraints are snapshotted in reviews. |
| AthleteGoal — NEW | `fitness_athlete_goal`, user, goal kind (hypertrophy/strength/powerbuilding/gain/cut/recomp/maintenance), priority, rationale, optional target_weight_kg, target_rate_kg_week or rate_percent_week with explicit choice, optional strength targets, `valid_from`, `valid_until`, recorded_at, supersedes_id, source/approval. Multiple compatible priorities allowed; one primary goal valid on a date. Lock per athlete and enforce nonoverlap of primary intervals, dates valid and units/rate signs coherent. Preserve superseded intervals; no permanent profile goal. |
| TargetRevision — NEW, versions EXISTING targets | `fitness_target_revision`: user, optional phase_id, scope `phase`/`default`, valid_from/until, version, base phase/default revision, approved_at/by, source, review recommendation ID; complete calories/protein/carbs/fat training/rest/default values, sleep/water/steps goals, tolerances. Append a complete resolved snapshot, not an ambiguous patch. Unique source/version/effective start; reject overlapping approved ranges for a scope with row/advisory locking and suitable constraint. Legacy phase/default macro fields remain compatibility current projections. A target edit closes previous range and creates next; historical targets with unknown start are explicitly marked unknown before first provable date. |
| AthleteLimitation — NEW | `fitness_athlete_limitation`: user, user-reported area/description, excluded/modified exercises, effective start/end, status, notes, severity flags. No diagnosis field; profile can expose active limitations by reference. Historical limitations retained. Index user/status/dates. |
| General preferences — REUSE | `user_settings`, `user_profile`, privacy/channel tables retain general app/coaching delivery preferences. Fitness preferences reference them where appropriate rather than copying all profile JSON. |

### 5.2 Observations and daily check-ins

- **HealthMetric — EXTEND existing raw-SQL `health_metric`.** Keep id/user/type/value/recorded_at/source/metadata; add canonical `unit`, optional external ID, original value/unit, logical date, source-quality and correction/supersession metadata. Add a source-identifier idempotency index for supported providers. Preserve existing `(user,type,time)` uniqueness initially; where distinct sources collide at identical stamps, record conflict/provenance rather than silently choose last ingestion. Only widen uniqueness after updating HealthKit ON CONFLICT callers together. Metric types cover weight, sleep duration, steps, water and extensible measurements. Existing sleep aliases/HRV remain supported. Provenance includes actual measurement time; do not synthesize a morning timestamp as if actually measured then.
- **DailyCheckIn — EXTEND `daily_recovery_log`, do not create a duplicated daily fitness truth table.** Unique `(user_id, log_date)`; optional bedtime/wake timestamp, sleep quality, energy, fatigue, soreness, stress, motivation, subjective readiness (separate from computed score), daily notes, `nutrition_status=unknown/partial/complete`, completion timestamp, row version, field-source map. Validate scales (document 1–10 directions for each), explicit null vs omitted on PATCH, positive time durations and finite numeric values. Weight/sleep/steps/water responses read canonical health metrics. Legacy weight/sleep columns are maintained compatibility mirrors by a common ingest service; no independent second calculation.
- **MeasurementType — NEW.** `fitness_measurement_type`: stable code (`waist_circumference`, `chest_circumference`, etc.), label, quantity/unit, permitted sites/sides, optional owner for custom codes, active flag and protocol guidance. Global seeds for common circumferences, user-private custom types. Unique normalized code within global/user namespace; custom definitions need no migration.
- **MeasurementPeriod — NEW.** `fitness_measurement_period`: user, measured_on/at, protocol, notes, optional photo-period label. Groups a tape session/photo set. User/date index.
- **BodyMeasurement — REUSE HealthMetric observation, annotated rather than duplicated.** Type code/site/side/period ID/source/protocol recorded in validated metadata (or explicit linking fields). The descriptor is in MeasurementType; observation values remain `health_metric`. API response exposes a typed measurement, not arbitrary unchecked JSON. Both sides of period/type references must be owner/global-accessible. Body weight remains `weight`, not an extra tape-metric copy.
- **FoodLog — REUSE.** Canonical meals and detailed items; no daily calories/macros stored as another authority in check-ins. Explicit aggregate-only daily entry, if needed, is a distinguishable manual `food_log` entry and cannot be added to independently imported full-day totals without a replacement/conflict policy. Log status marks completeness; a missing day is not 0 calories.
- **WeightTrend / FitnessDailyLog — REUSE projections.** Define source revision and rebuildability. Backfills/corrections update affected projections; coach analytics calculate calendar-window metrics from selected raw observations, never from old EWMA fields.

### 5.3 Exercise identity and prescription

- **ExerciseLibrary — EXTEND existing `exercise_library`.** Canonical variant name, optional parent canonical movement, variation code, equipment, primary/secondary muscle codes, movement pattern, unilateral/bilateral, load convention (`total`, `per_hand`, assisted, bodyweight), optional ROM/technique, metadata, optional owner, archive status. Keep existing JSON fields/readers compatible. Global seeded rows visible to all; private custom rows visible only to owner. Existing seeded user names have no provenance: classify safely, do not declare all private names globally public by default.
- **ExerciseAlias — NEW `fitness_exercise_alias`.** Normalized alias, exercise_library_id, owner/global scope, locale, review/source. Unique normalized alias in scope unless deliberately ambiguous. Exact normalized lookup only; fuzzy search suggests choices. "Bench" can require clarification if multiple variants apply. Barbell and dumbbell bench can share movement parent but retain separate histories.
- **Program/Phase/Template/TemplateExercise — REUSE and evolve.** Program is a macrocycle/container; phase is block/mesocycle with valid dates and training emphasis; week is derived from block date, not a required new table initially. Existing `template_exercise` is the prescription child: add canonical ID, target_RIR, load convention, typed progression metadata, optional prescribed set plan. `fitness_template.exercises` is currently live authority for several readers: use a single normalizer/updater to synchronize JSON and related rows; do not switch authority silently. Later introduce immutable `fitness_template_revision` and FK/snapshot versions if typed week plans exceed current set_plan model.
- **Prescribed sets — reuse existing set-plan JSON initially.** Stable slot IDs, set count/type, low/high reps, RIR/RPE, rest, optional tempo, week-specific changes and rule version. Keep structural kinds warmup/working/drop; top/backoff/AMRAP/failure are added as a `set_role`/intent flag instead of breaking existing `set_kind` counting rules. A typed parser rejects inconsistent RPE/RIR and incomplete schemas.

### 5.4 Performed training and pain

- **TrainingSession — REUSE workout_session + active_workout_session link.** Planned status/calendar/template on planned row; actual snapshot/version/start/end/progress on active row. Add only missing display name, planned/unplanned indicator, subjective session difficulty and notes. Establish one read projection that de-duplicates linked rows, handles legacy orphan histories and two sessions/day. Do not count `workout`, planned and active rows as three sessions.
- **ExercisePerformance — NEW `fitness_exercise_performance`.** user, active_session_id, stable occurrence ID, template slot/revision, canonical exercise ID, captured variation/name/load convention, order index, notes, pain summary. Unique session/occurrence; repeated same exercise in one session remains two occurrences. Backfill conservatively from snapshot slot and existing set links; unresolved legacy names remain flagged rather than guessed.
- **SetPerformance — EXTEND existing workout_log.** Retain legacy fields, canonical shadow FK, command ID, set_kind/group/corrections/void state. Add exercise_performance_id, fractional decimal load with explicit unit via an additive field/adapter initially, RIR, decimal RPE where needed, set_role, actual rest, tempo, explicit failure flag/completed status. Existing integer `weight` is a compatibility projection, never the source for fractional new logs; old contracts must never silently truncate. Effective load/units belong in one adapter shared with recalc/progression.
- **ExercisePR — EXTEND existing exercise_pr.** Canonical variant ID, PR kind, reps/normalized load/e1RM, formula version, source set ID, achieved time/date, withdrawn_at/reason. Correction/void triggers recomputation against all eligible remaining sets. Stable uniqueness/indices by user, variant, PR kind/date. Preserve legacy text compatibility, do not award another person's or another variant's PR.
- **PainReport — NEW `fitness_pain_report`.** user, occurrence/session/optional set, occurred_at/local date, pain_present, severity 0–10, location/side, onset/context, user notes, resolved/superseded correction marker. Optional nonsession entry. Owner/time/canonical exercise indexes. Derived summaries count distinct sessions with reports, not set count. No diagnostic conclusion.
- **Workout proposals/policy/commands/events — REUSE.** In-session adjustments remain existing `workout_adjustment_proposal` and command protocol. Weekly target/program recommendations are separately linked durable recommendations because they have longer validity and different acceptance operations.

### 5.5 Coaching/audit, schedules, photos, science

- **CoachReview — NEW `fitness_coach_review`.** user, period_start/end_exclusive, kind, status pending/running/complete/failed/insufficient_data, input state JSON (compact), state/data/analytics versions/hash, evaluated_at, actual model/provider, prompt version/hash, validated output, summary, evidence references, error category, run ID and attempt. Unique idempotency key `(user,kind,period,input_hash,prompt_version)`; a retry returns same run. A rerun after corrected data creates a linked revision, preserving old result. No raw multi-month history or full duplicated prompt.
- **CoachRecommendation — NEW `fitness_coach_recommendation`.** review/user, category/action, rationale, confidence basis and limitations, metric paths, evidence IDs, typed proposed change, current target/program revision, expires_at, decision status/time/actor, accepted action receipt ID. Bounded confidence labels are model interpretation, distinct from data coverage. Rejected/expired proposals retained.
- **CoachingSchedulePreference — NEW `fitness_coaching_schedule`.** user, kind, enabled/consented, local time/weekdays, cadence days, timezone, quiet overrides only within app policy, next_due_at, last evaluation/completion, snooze, version. Unique user/kind. For 14/28-day cadence use anchored due dates, not `day_of_month */14` pretending to mean every two weeks. Add durable `fitness_coaching_job_run` for user/kind/occurrence status/candidate/review ID/retries/error; unique occurrence key. Global ScheduledJob sweeps enabled preferences, ordinary users cannot choose arbitrary task names/kwargs/users.
- **ProgressPhoto — EXTEND existing model/table.** Add view front/side/back/other, period link, capture protocol/quality metadata, bodyweight observation reference, consent and analysis status. Existing explicit bodyweight is contextual snapshot, not authoritative new weight. Keep original nullable critique as legacy output; never treat it as validated observation.
- **PhotoAnalysis — NEW `fitness_photo_analysis`.** owned source/comparison photo IDs, capture dates, model/provider/prompt/schema versions, immutable structured observations, comparison quality, uncertainty, analysis time/status/failure. Index user/period/model; prevent comparison across owners; no body-fat percentage field or diagnosis.
- **ScienceRecord — NEW `fitness_science_record`.** user curator/owner, linked Document ID, title/authors/journal/publication/date, evidence type, topic/population/sex/age/training status, intervention/duration/outcomes/findings/limitations/takeaway, source URL/DOI, confidence basis, accepted/new/rejected/superseded status, curator/time, version/hash and retraction flags. Start owner-scoped curated library; shared public catalog needs explicit admin/public publishing later. Unique owner+normalized DOI or source/hash. No fabricated missing bibliographic fields.
- **ScienceChunkAnnotation — NEW `fitness_science_chunk`.** science_record_id + DocChunk ID, section/page/source location, outcome/topic tags, revision/checksum. DocChunk holds native-vector embedding; annotation holds evidence linkage, no parallel vector database. Unique record/version/chunk. Parent Document ownership must match record owner for private records.
- **ScienceCurationEvent — NEW `fitness_science_curation_event`.** record/revision, prior/new status, actor/reason/time, source reference. Accepted revisions immutable; replacement is new version with supersedes relationship. Recommendations store exact evidence revision/chunk IDs.

## 6. Proposed Backend Architecture

Keep routes thin, services own policy and transactions, analytics functions pure, and data access centralized. Use sync SQLAlchemy sessions in the established fitness HTTP path; jobs can use short sync transactions around network-free work and shared async sessions where required by candidate delivery. Never run simultaneous operations on a shared sync session.

**New paths (all PROPOSED, with one caveat):** the directory `backend/app/services/fitness/` already exists. It has no `__init__.py` and contains exactly one orphaned module, `backend/app/services/fitness/conversational.py` (a fitness-onboarding question generator; no module imports `app.services.fitness.` anywhere). The files listed below are new, but creating the package `__init__.py` makes that orphan importable — Step 3 disposes of it explicitly.

| PROPOSED path | Responsibility |
|---|---|
| `PROPOSED: backend/app/models/fitness_coach.py` | New athlete/goal/target revision/limitation/measurement-period/alias/performance/pain/review/recommendation/schedule/science model definitions. Split photos/science into their own modules when added, not prematurely. |
| `PROPOSED: backend/app/schemas/fitness_coach.py` | Validated API DTOs, nullable metrics, FitnessStateV1, CoachReviewOutputV1 and proposal payloads. |
| `PROPOSED: backend/app/services/fitness/data_access.py` | Owner-scoped bounded queries and legacy row/time/unit adapters; no parallel generic repository framework. |
| `PROPOSED: backend/app/services/fitness/profile.py` | Athlete profile/goals/limitations operations and dated selection. |
| `PROPOSED: backend/app/services/fitness/targets.py` | Dated target revision resolver/writer shared by old phase/default endpoints, analytics and UI. |
| `PROPOSED: backend/app/services/fitness/observations.py` | Canonical health/measurement ingest, source resolution, check-in PATCH, projection maintenance. |
| `PROPOSED: backend/app/services/fitness/exercises.py` | Scoped catalog, normalized aliases, ambiguity handling and reviewed backfill. |
| `PROPOSED: backend/app/services/fitness/analytics.py` | Pure weight/nutrition/sleep/training/pain/quality calculations; split by metric group only if size warrants. |
| `PROPOSED: backend/app/services/fitness/state.py` | Database collection → analytics → compact deterministic athlete state; cache policy and rendering. |
| `PROPOSED: backend/app/services/fitness/reviews.py` | Snapshot/read-only LLM review, validation, audit and regeneration. |
| `PROPOSED: backend/app/services/fitness/recommendations.py` | Owner decisions, acceptance validation/idempotency/revision checks and action receipts. |
| `PROPOSED: backend/app/services/fitness/safety.py` | Small fitness/medical boundary, severe-pain flags, output policy validation. |
| `PROPOSED: backend/app/services/fitness/coaching_jobs.py` | Due preference selection, occurrence ledger, missing-data priorities and candidates. |
| `PROPOSED: backend/app/services/fitness/photos.py` | Existing photo metadata/upload lifecycle orchestration and analysis. |
| `PROPOSED: backend/app/services/fitness/science.py` | Ingestion metadata, curation, accepted-only retrieval/ranking/refresh. |
| `PROPOSED: backend/app/routes/fitness_coach.py` | Athlete/goals/check-in/measurements/state/reviews/schedule APIs under `/api/fitness/coach`. |
| `PROPOSED: backend/app/routes/fitness_science.py` | Owned science records and explicit curation, added in science phase. |
| `PROPOSED: backend/app/tasks/fitness_coach.py` | Bounded jobs using existing health queue. |
| `PROPOSED: backend/app/tasks/fitness_science.py` | Low-priority research ingestion/refresh, no automatic curation. |
| `PROPOSED: backend/app/tools/fitness/coach.py` | Typed narrow read tools and validated user-origin action tools. |
| `PROPOSED: backend/app/prompts/fitness_coach_review.py` | Versioned review prompt with serious resistance-training interpretation and output schema instructions. |
| `PROPOSED: backend/app/prompts/fitness_photo_observations.py` | Later structured vision prompt, comparison conditions, no composition estimates. |

**Existing files to modify incrementally:** `backend/app/routes/fitness.py` and `workout_v2.py` authentication/shared service delegation; `health_metrics.py` and `fitness_inline.py` canonical ingest; `main_simple.py` explicit router registration and small context integration hooks; `fitness_context.py`/`world_brief.py` deterministic state rendering; `context_snapshot.py`/`chat_assembly.py` bounded fitness-context allocation; `workout_command_service.py`/`workout_recalc.py` canonical set metadata and corrections; `progressive_overload.py`, `training_day.py`, `plan_adjust.py` shared historical resolutions; `tools/registry.py`, `tools/mutating.py` and action boundary services for tools; `celery_app.py` task registration/routing; existing photo routes/model; existing health consolidation readers. Each actual edit is assigned in Section 15.

API shape: athlete `/profile`, dated `/goals`, `/targets?on_date=`, `/check-ins/{date}`, `/measurement-types`, `/measurement-periods`, `/measurements`, `/state`, `/analytics?start=&end=`, `/reviews`, `/reviews/{id}`, `/recommendations/{id}/decision`, `/schedules`, all inside `/api/fitness/coach`. Collection routes cap page size/date span. Writes use row version or idempotency key where retries matter. Legacy `/api/fitness/*` paths stay adapters; there is one service truth behind both.

## 7. Proposed Frontend Architecture

Extend existing `/fitness`; no second top-level app, auth provider or router. Initial new subviews: **Today**, **Coach**, **Settings**, **Progress**. Keep food/workout/plan/recovery and existing functions reachable. Measurements live under Progress. Photos and research become Progress/Coach subsections later; avoid eleven new empty tabs.

| PROPOSED path | Purpose |
|---|---|
| `PROPOSED: frontend/src/api/fitnessCoach.ts` | Typed credentialed calls, version/idempotency headers, normalized errors using APP_CONFIG. |
| `PROPOSED: frontend/src/types/fitnessCoach.ts` | API/state/review DTOs, units and nullable coverage; keep frontend arithmetic display-only. |
| `PROPOSED: frontend/src/hooks/useFitnessCoach.ts` | Query keys scoped to user/date/period; mutations invalidate dependent state/reviews/old dashboard data. |
| `PROPOSED: frontend/src/components/fitness/AthleteSettings.tsx` | Profile, goals, targets history, limitations, cadence/consent. |
| `PROPOSED: frontend/src/components/fitness/DailyCheckIn.tsx` | Quick partial updates; source tags for wearable/manual readings; missing values stay blank. |
| `PROPOSED: frontend/src/components/fitness/CoachOverview.tsx` | Goal/phase/current state, trends, targets, today's sessions and one coaching priority. |
| `PROPOSED: frontend/src/components/fitness/Measurements.tsx` | Period-based custom type/site/side entries and honest sparse charts. |
| `PROPOSED: frontend/src/components/fitness/CoachReviews.tsx` | Request/poll review, read rationale/data coverage/evidence and review proposed changes. |
| `PROPOSED: frontend/src/components/fitness/ProgressPhotos.tsx` | Existing API gallery/standardized capture guidance/period comparisons. |
| `PROPOSED: frontend/src/components/fitness/ScienceLibrary.tsx` | Curated sources + distinct unreviewed inbox and explicit acceptance. |
| `PROPOSED: frontend/src/hooks/useWorkoutCommands.ts` | Reuse v2 start/projection/commands/sync, stable command IDs and conflict refresh for web. |

Modify `FitnessSection.tsx` to compose these; incrementally extract its large dashboard/program pieces if necessary without unrelated UI rewrite. Use current primitives, Tailwind and Recharts. React Hook Form/Zod validate entry; backend remains authority. TanStack Query owns remote state; clear user-scoped queries on logout/account change. Numeric zero and unknown must render differently; every trend displays available days and period.

Fast workout interface extends `ActiveWorkout.tsx` and `WorkoutLogEnhanced.tsx`: one screen with exercise list, previous performed loads/reps, current set weight/reps/RIR, keyboard/touch entry, duplicate previous completed set, rest timer and finish. One submission logs a set; no modal navigation per set. Preserve entered values on network failure; persist a command ID before transmission, replay exact payload on retry, avoid automatic re-submission against a conflicting session version. Durable acknowledgment is independent of coaching prose. Provide clear cross-device refresh/conflict handling. Local/offline queue later; initial reliable online retry is sufficient.

Daily nutrition reuses FoodLog rather than another macro input screen. Remaining target = resolved target minus known intake, with partial/complete label; negative remaining is allowed and is not hidden. Today requests at most one useful missing detail at a time, offers skip/snooze, and can finish without data the athlete declines to collect.

## 8. LLM / Sara Integration

### 8.1 Fitness State and context allocation

`FitnessStateV1` is deterministic and schema-versioned: athlete profile/constraints, goals/priorities/effective dates, phase/program revision, current nutrition targets, weight and measurement changes, last photo capture/validated observations, planned/completed training, performance/PRs, nutrition completeness/adherence, sleep/recovery, pain patterns, recent approved changes, quality/missing/stale fields, and accepted evidence references where available.

Each metric includes `value|null`, unit, period `[start,end)`, observed/complete day count, expected days, freshness, quality flags and formula/version. No user ID or photo data enters a model-visible tool parameter. Profile name is resolved from actual user preferences; do not hard-code David for another athlete.

Build two renderings from the same state:

1. **Chat capsule:** initially at most ~1,500 characters when relevant, prioritizing goal/phase, today's targets/session, active limitations and missing freshness. Integrate through existing world brief/context assembly, preserving dialogue/world core budget floors. Tools fetch detailed metric groups. Explicitly test that the fitness section survives allocation during a fitness question without dropping dialogue corrections.
2. **Weekly review input:** compact structured 7/14/28-day aggregate state, starting max ~6,000 input tokens, bounded exercise summaries/top pain patterns/changes/evidence. No months of set rows or photographs. Collect full raw details in tools only on explicit scope/date/variant request.

These are initial budgets to measure, not extra unbounded allowances on top of current chat budgets. Use existing budget utilities; no hidden LLM summarizer required to build basic fitness state.

### 8.2 Qwen review contract

Use `get_background_llm_client()` and resolved local model; set max_tokens and nested `chat_template_kwargs.enable_thinking=False` for JSON. Record actual model/endpoint capability class and fallback result. Do not hard-code an endpoint or claim Qwen3.8-27B has working vision because it handles text reasoning.

`CoachReviewOutputV1`: review summary; coaching priority; observations referencing known metric IDs/paths; limitations/missing data; confidence category with basis; recommendations limited to maintain, progress, reduce, exercise change, volume change, nutrition change, prioritize recovery, request data, or flag concern; each recommendation has rationale, supporting metric references, supplied evidence revision IDs, typed proposed value/scope/effective date or no action. Output includes no executed-action status.

Validation pipeline: bounded response → parse JSON → Pydantic strict enums/types → validate metric/evidence IDs against supplied snapshot → bounds/safety rules → reject invalid action fields → persist. One bounded repair request may correct syntax/schema, using same input and recording attempt. No endless retries. Persistent malformed/empty output marks review failed, preserves deterministic analytics, and offers retry. Insufficient data produces maintain/request-data with honest limitations, not invented rate or automatic calorie adjustment. Do not store reasoning_content/hidden chain-of-thought.

### 8.3 Tools (consistent with existing snake_case BaseTool conventions)

Names below are recommendations for NEW tools; existing names are retained. Use consolidated read tools to protect the per-turn menu budget.

| Status/name | Proposed signature excluding injected user_id | Boundary |
|---|---|---|
| Existing `fitness_summary` | keep `days_back`, add optional section/date range compatibly | Delegate to FitnessState, stop querying legacy created-at aggregates separately. |
| NEW `fitness_profile_get` | `{on_date?: YYYY-MM-DD}` | Profile, goals, effective targets and limitations, read only. |
| NEW `fitness_analytics_get` | `{section: weight\|nutrition\|sleep\|training\|recovery\|pain\|quality, start_date, end_date, exercise_id?: string}` | Bounded structured analytics; replace redundant math in existing stats/summary readers. |
| NEW `fitness_measurements_get` | `{type_code?: string, start_date?, end_date?, limit?: integer<=100}` | Owned/custom/global-accessible definitions, measured values and protocol. |
| Existing `workout_details`, `workout_stats`, program/template/recovery/food read tools | Preserve actual existing schemas first | Fetch raw details/history as needed via shared owner-scoped data access. |
| NEW `fitness_coach_review_get` | `{review_id?: string, period_end?: date}` | Reads existing review, does not incur hidden new review generation. |
| NEW `fitness_science_search` | `{query: string, topic?: string, limit?: integer<=8}` | Accepted eligible evidence only; source/citation/limitations/revision IDs. |
| NEW `fitness_checkin_update` | `{log_date, fields: validated partial check-in, expected_version?, idempotency_key}` | User-origin write; missing fields not filled by model. Calls same ingest service as UI. |
| NEW `fitness_measurement_log` | `{type_code, value, unit, measured_at, site?, side?, period_id?, idempotency_key}` | User-reported observation with owned references, finite values, source manual. |
| NEW `fitness_coach_review_request` | `{period_end?: date, idempotency_key}` | Explicit requested computation; bounded job creation, read-only to targets. |
| NEW `fitness_recommendation_decide` | `{recommendation_id, decision: accept\|reject, expected_revision, idempotency_key}` | Material action; user-origin, target resolution and action contract; explicit approval. |
| Existing food/workout/program/phase actions | Preserve schemas and receipt paths | Strong validation; major target/template changes require intended operation and owned exact target, including older mutation paths. |

Every new tool returns `ToolResult`; action tools set `requires_user_origin` where appropriate and are classified in mutation gating. JSON schemas reject unknown/injected identity fields. Registration alone is insufficient: add category/retrieval metadata, mutation/operation/target contracts, generated types, and final schema-boundary tests. Use `backend/scripts/generate_tool_types.py` for existing generated frontend types where applicable.

### 8.4 Memory boundary

Structured authority: weight, tape values, sets/reps/load, workouts, calorie/macros/sleep, dated goals/targets, programs, progression, photo metadata and review metrics. Tools/query state resolve these. Episodic memories retain conversations and perceptions, not canonical fitness arithmetic.

Qualitative memory examples: dislikes lunges, enjoys heavy deadlifts, prefers short sessions, dislikes whey in water, wants upper-body thickness. Execution-relevant preferences/exclusions also have typed athlete-profile references. Avoid two independent authorities: when promoted from conversation to profile, retain original memory as a provenance-linked statement and make profile authoritative for exercise generation. A soft conversational preference can remain memory-only until adopted. Goals such as thickness become structured once they drive programming, preserving the original phrase as rationale.

Stop routine food/set/recovery writers from creating redundant authoritative numeric memory summaries for new records. Keep normal chat episodes; legacy memory copies cannot override dated observations. Amend the application fitness skill and PKG extraction exclusion rules, including target-like intentions now owned by TargetRevision. Multi-user coaching must not query globally David-centered PKG as another athlete's preferences; default to owned profile and scoped episodic recall until graph scoping is verified.

## 9. Analytics Engine

Implement in `PROPOSED: backend/app/services/fitness/analytics.py`, with database collection in proposed data_access/state modules. Calculations accept normalized records + explicit as-of + timezone + goal/target timeline; pure functions make results reproducible. Algorithm version belongs in state/review. The following thresholds are conservative engineering eligibility defaults, not scientific prescriptions; expose/configure them and record their version.

### 9.1 Shared rules

- Intervals are calendar-day, half-open, athlete-local; exclude current incomplete day from completed weekly reviews. `end` at local midnight; DST days need not be 24h.
- Deduplicate observations by source ID, logical day and metric protocol. For weight, choose one representative per day by configured manual-confirmed morning/consistent-source preference; do not average all scale readings and give frequently measured days extra influence. Preserve alternatives/conflicts.
- Never fabricate/interpolate missing days into reported averages. Denominator is known eligible days; show expected calendar days separately. Unknown/null is different from zero and invalid/rejected.
- Mixed units convert once; label canonical and display units. Unknown legacy units are unresolved, not guessed. Backfills flag derived provenance. Finite numeric validation avoids NaN/Infinity.
- Exclude future observations, voided sets, skipped sets and withdrawn PRs appropriately. Correction invalidates affected windows and later projections. Calculations distinguish event time vs created time.

### 9.2 Weight

Latest selected weight includes measurement time/source. Last 7 days `[E-7,E)`, previous `[E-14,E-7)`, 14/28-day means use selected daily samples. Weekly velocity = current 7-day mean minus previous 7-day mean, in kg/week; percent velocity divides by previous mean when nonzero. Require at least 3 observed days in each 7-day window and show days/7; below threshold return null velocity and insufficient coverage. A one-day reading does not prove plateau.

Longer trend: linear regression over actual day offsets of selected daily weights, at least 8 distinct days spanning at least 14 days within 28; slope ×7. Missing dates keep their real offsets. Outliers remain visible, flagged; do not silently discard an unexpected genuine gain/loss. Compare to the effective goal's requested velocity, and split/label periods crossing a goal change. No EWMA substituted for a weekly average. Existing EWMA may remain an explicitly labeled display series, recomputed after backdated corrections.

### 9.3 Nutrition

Aggregate known meal values by `logged_at` local date. Unknown macro fields remain unknown/partial rather than silently zero. Reuse food totals/estimation provenance. Complete-day averages include only days marked complete and having valid required totals; separately report all known intake, partial days and logged meals. Macro averaging may have per-field denominators, disclosed.

For each complete day, resolve historically effective calorie/protein target and training/rest variant. Calorie delta = intake-target; relative deviation = delta/target. Adherence initially = complete eligible days within configured tolerance / complete eligible target days, alongside eligible/calendar counts. Protein adherence = eligible days meeting target or configured lower bound / eligible days; do not make an invented clinical upper requirement. Tolerances are explicit versioned settings, not model decisions.

Weight response relative to calorie intake is observational: co-display multiweek complete-day intake, weight velocity, target changes and coverage. Never claim an inferred exact maintenance calorie value or causal calorie effect from sparse data. Potential energy-adjustment proposals require sufficient complete days, weight coverage, stable target period, and user review. Nutrition completion must be revocable/editable with audit.

### 9.4 Sleep and recovery

Use selected nightly duration streams, not sum of overlapping device/manual sleep totals. Prefer canonical HealthKit total for duration, manual correction when explicitly confirmed; exclude naps from nightly duration unless marked; bedtime/wake belong to overnight episode and logical wake date. Sleep mean, deviation from effective sleep target, count/coverage; duration/bedtime/wake variability with sample count. Circular clock arithmetic handles bedtime near midnight (23:50 vs 00:10 is 20 min, not almost 24h).

Subjective quality/fatigue/soreness/readiness mean and 7-vs-prior-7 change use documented scale direction. Don't substitute computed readiness for subjective readiness. Reuse compute_readiness with documented inputs/baselines, add `unknown` when all relevant inputs are missing and `partial` otherwise. An empty input must not display 100/excellent. HRV outlier rules remain qualitative flags, not diagnostics or decisive deload commands. Sleep/subjective decline plus training changes are hypotheses, not proven overtraining.

### 9.5 Training

- Resolve unique sessions via existing planned→active link and legacy mapping. Count distinct completed/skipped/planned-missed sessions. Planned denominator comes from dated prescription snapshot/calendar occurrence, not today's mutated templates. Unknown historical schedule means unknown adherence denominator. Partial/in-progress differs from skipped/missed. Two-a-day means two sessions.
- Count live working sets using existing structural set_kind/counts/void rules. Top/backoff/AMRAP are roles of working sets; drop segments attach to one parent. Preserve extra working sets and avoid warmup inflation. Snapshot prescribed-vs-performed sets separately.
- Muscle exposure = direct primary working sets; show secondary involvement separately, with optional explicitly versioned fractional estimate later. Unknown muscles reported as unclassified, not assigned by LLM. Compounds involve multiple muscles; don't present their sum as total unique sets.
- Tonnage = Σ normalized external load×reps within a meaningful compatible variant/convention, excluding void/skipped and labeling warmup/drop inclusion. Do not compare machine-stack kg, assisted pull-up kg, dumbbell per-hand load and barbell total as universal volume. Never treat tonnage as hypertrophy dose.
- Recent performance: canonical variant + load convention + rep range + RIR/RPE + protocol. Show top/working sets and last comparable session; changes in exercise/ROM/equipment invalidate simple comparison.
- e1RM: initial Epley `load*(1+reps/30)` for positive external-load eligible working sets with 1–10 reps; one rep returns performed load. Record formula version/rep limit, metric assumptions; label estimate. Exclude timed/cardio, warmup/drop, assisted/bodyweight without meaningful total-load convention, skipped/voided sets; flag unknown effort. No universal strength ranking across unrelated movements. Fractional load calculations use full precision then round output.
- PRs: max load for a rep bucket, max reps at a normalized load bucket, and e1RM within variant/protocol. Tie is not a new PR. Correcting/voiding source retracts it and selects next eligible record. Rep bucket/load increments follow equipment/unit settings, not floating equality accidents.
- Strength trend/stagnation/progressive overload: compare at least 3 eligible comparable exposures over at least 14 days; report best/median eligible performance and effort changes. "No recorded improvement" with sparse exposures isn't plateau. Avoid prescribing more volume if pain, inconsistent effort, exercise changes or incomplete data explain the pattern.
- Exercise frequency = distinct days/sessions per canonical variant with selected period. Session difficulty is user-reported; defer a single opaque performance score until validated.

### 9.6 Measurements, pain, data quality

Measurement change compares same type/site/side/unit/protocol and dates/periods, with raw differences and elapsed days. Small tape changes are observations, not guaranteed tissue change. Photos contribute dates/comparison quality/validated qualitative observations only.

Pain pattern: count distinct sessions with explicitly reported pain, severity maximum/trend, location/side, canonical exercise, last report. Missing pain answer isn't absence. Example output: four of six documented barbell curl sessions report forearm discomfort, with reporting coverage; no diagnosis.

Quality is an independent output: observed weights/7, sleep nights/7, nutrition complete/partial/unknown counts, missing fields, unresolved unit/source collisions, unresolved exercise identities, incomplete workouts, overdue measurement/photo cadence by opt-in, stale/missing profile/targets and insufficient comparable exposures. Goals can be intentionally long-lived; stale means review due or no effective target, not automatic expiry. Coverage confidence is separate from model confidence. Every metric includes why it is unavailable and what additional data would help.

## 10. Scientific RAG Architecture

### 10.1 Scope and storage

Reuse DocumentProcessor extraction/MinIO, shared embedding/reranker transports and PostgreSQL pgvector. Sports-science records are a separately curated corpus, not all personal documents or web search results. Use owned Document + native-vector DocChunk and proposed science metadata/annotations. Current live document search uses TEXT-cast DocumentChunk; do not copy that into a new high-quality corpus or indiscriminately migrate generic documents during fitness work.

Start small: administrator/athlete imports a few relevant position statements, systematic reviews/meta-analyses and major exercise/nutrition/sleep papers. No enormous crawler. Metadata records evidence category and applicability; requested prioritization is consensus/position statements → systematic reviews → meta-analyses → RCTs → other peer-reviewed studies → vetted interpretation → anecdote. Systematic review vs meta-analysis rank is a configurable coarse preference, not proof one always outranks the other; risk of bias, population and recency remain visible. Anecdote must be labeled and cannot silently support major adjustments.

### 10.2 Ingestion and retrieval pipeline

1. Register source URL/DOI/upload and rights/access context; fetch through existing search transport with bounded size/time and permitted URLs. Save immutable source checksum, retrieval time and ownership. Avoid resolving arbitrary private-network URLs in a new ingestion endpoint.
2. Extract text, page/section context and bibliographic metadata; parser/LLM may propose missing annotations, all tagged extracted/unreviewed. Never invent authors, population or outcomes.
3. Split semantic sections/chunks with source offsets; embed via shared service and configured dimension. Check dimension/finite values; no padding fabricated failed embeddings. Mark index status; embedding failure is retriable, not accepted evidence silently disappearing.
4. Create ScienceRecord status `new`; annotate population, intervention, duration, outcomes, limitations and takeaway with source citations. Curator explicitly accepts version. Acceptance/edits/withdrawal produce curation events.
5. Retrieve only accepted, nonretracted accessible versions; filter topic/population applicability, then native-vector + lexical recall, rerank candidates, rank with evidence type/quality/applicability, show publication and curation dates. Similarity does not establish scientific quality.
6. Return bounded excerpts/practical summaries with source/chunk/version IDs, URLs/DOIs, population and limitations. Prompt cannot cite IDs not retrieved. Conflicting accepted evidence yields an uncertainty summary; avoid single-study certainty.
7. Save exact retrieved reference IDs/ranking policy version in review. On retraction/supersession keep old audit accessible and flag impacted reviews; do not rewrite old recommendations invisibly.

### 10.3 Refresh

A global low-priority recurring job refreshes configured source/topic searches, deduplicates DOI/URL/checksum and queues new records as `new`. A periodic curated refresh audit checks accepted source status/age. Newly published papers never auto-change target revisions or acceptance. Provide one digest for review, not one notification per paper. Accepted guidance only changes after deliberate curation, and athlete changes still require explicit proposal acceptance. No fake freshness claim when fetch failed; store last attempted/last successful/source-status timestamps.

## 11. Progress Photo Architecture

Reuse existing `ProgressPhoto`, photo API and bucket. Add front/side/back/other, capture period, date/time/notes, weight reference or labeled capture snapshot, capture consistency metadata and opt-in analysis. Existing iOS supports uploads/critique; maintain endpoints while versioning critique behavior. Web Progress exposes this API after ownership groundwork.

Initial upload hardening: authenticated owned user, byte cap and decoded pixel cap, allowlisted MIME with actual decode validation, reject invalid data rather than label original bytes JPEG on fallback, orientation normalize, strip EXIF/GPS, normalize safe image, thumbnail. Clean both objects on DB failure; deletion tracks failed blob cleanup for retry (current route can delete metadata despite object removal failure). Do not publicly expose storage keys or reusable permanent object URLs. Serve authenticated bytes or short-lived owned URLs using an explicit security policy; existing authenticated file route is adequate initially. No automatic full-body crop/segmentation needed.

Future analysis uses `backend/app/routes/vision.py` helpers and `UserSettings` model/endpoint. Qwen3.8-27B text configuration alone does not establish deployed multimodal support. Existing `get_user_vision_settings()` defaults to qwen3-vl; `llm_config` has different vision defaults. Verify chosen endpoint capability on a disposable fixture and route through a shared helper; prefer configured separate vision model while text coach consumes structured observations. Do not send private athlete photos to cloud by silent fallback.

`PhotoObservationV1`: body-region observation text, direction/category (apparent waist change/fullness/development/symmetry), confidence, comparable/not-comparable, pose/lighting/distance/quality issues and reference photo IDs/dates. No precise body-fat percent or clinical assessment. Low consistency can yield "comparison inconclusive". Existing CRITIQUE_PROMPT requests body-fat range; remove that request before any new vision feature is enabled. Store old critique as unvalidated legacy text, exclude it from numeric FitnessState.

Analysis job is optional, asynchronous and owner-scoped; idempotent by photo pair/model/prompt hash. Process bytes outside a DB transaction; save validated results with revision precondition so deleting a photo prevents stale analysis commit. Audit structured observations, model/template versions and uncertainty. Leave clinical image interpretation outside scope.

## 12. Proactive Coaching Architecture

Use existing Celery Beat global jobs and per-user proposed coaching preferences. Seed only one bounded due-sweep on the health queue and one research refresh on low_priority when their phases ship. No per-user arbitrary task entry manipulation, new scheduler or microservice.

The due sweep claims enabled opted-in preference occurrences transactionally, using a unique occurrence ledger and `FOR UPDATE SKIP LOCKED`/equivalent; bounded batches and no long locks around LLM. Each task receives explicit user_id/occurrence ID, recomputes missing state before asking and writes success/failure/noop status. Retries replay existing run/artifact/candidate rather than duplicate deliveries. Persist the next local due time; define DST skip/repeat behavior once. Cadence is configurable and pause/snooze supported.

| Loop | Inputs/action | Initial default proposal, configurable and off until consent |
|---|---|---|
| Morning | Last night's canonical sleep, selected weight, current phase/targets, previous nutrition completeness, today's templates, reported recovery; request highest-value missing field | One local morning check-in; merge with morning brief when enabled. |
| Pre-workout | Prescribed set plan, previous comparable performance, approved progression and pain/limitations | Reminder attached to scheduled session/window; no invented start time. |
| During | Fast command logging, optional bounded existing workout coaching | Existing workout policy controls speech/rest/load proposals. |
| Post-workout | Missing sets/effort/pain, corrected PRs, prescribed/performed comparison | Durable completed-session artifact; one followup only if useful/consented. |
| Nutrition/day | Known intake vs resolved dated targets; logging completeness | Opt-in time, avoid interpreting no log as no food. |
| Evening | Day completeness/recovery, sleep opportunity and tomorrow's plan | Opt-in evening cue, merge with existing bedtime/daily rhythm. |
| Weekly | Prior complete 7 days plus 14/28 history; waist if requested | One Coach Review and optional waist request, dedup with health weekly report. |
| Fortnightly | Tape measurement period and standardized photos | 14-day due dates anchored to last completed period, independently snoozable. |
| Monthly | Deeper 28-day program/physique review | 28-day cadence, enough data before recommendations. |
| Research | New/unreviewed source digest and accepted-corpus freshness | Monthly/selected cadence on low_priority, no automatic curation. |

Unsolicited coaching generates `say_candidate` using stable user+kind+occurrence topic, evidence reference, expiry and short summary. Existing judge/compose/review/delivery applies before push/inbox. Explicit requested review always stays readable in Coach even if delivery suppressed. Respect notification category switches, quiet mode/directives/standing orders, interruptibility, cooldown and daily caps; no bypass flag added just to make coaching push happen.

Avoid a morning brief + fitness check-in + health insight all asking the same weight question. Define a shared missing-data entity key for the date/metric, resolve already-delivered evidence, and choose one request. Show actual completed review status separately from scheduler dispatch status. Job errors/logs omit sensitive body/photo contents.

## 13. Security / Privacy / Safety

- Authentication required across all fitness routes including legacy/v2, uploads, bytes and tool-origin API actions. Use real actor subject, no default user. Jobs require explicit valid user. Return 404 for foreign IDs and no existence leak. Tool ownership is checked within service/target boundary even if chat already authenticated.
- Owner-scope every SELECT/update/delete/join, parent reference, idempotency key, cached state, review, recommendation, photo pair, custom measurement/exercise. Global exercise/evidence seeds have explicit visibility and restricted editing. Strengthen FKs or composite relationships where possible; absence of owner in old global tables is a migration issue.
- Restrict global schedules/admin science publication through established admin checks; ordinary athlete schedule endpoints only touch their preferences. Existing global schedule API lacks this separation; resolve it in scope for coaching integration rather than build on arbitrary kwargs.
- Validate dates, quantities, unit conversion, finite values, enum/scales, max rows/date span, decoded image size, safe filenames and resource references. Parameterized SQL only; no interpolated day intervals like older weight route. Distinguish omitted field vs explicit clear.
- Sensitive profile/pain/fitness/photo data stays private; do not reuse in unsolicited unrelated chat. Honor existing privacy preferences but verify enforcement rather than assume profile flags enforce themselves. Provide owned export and deletion including photos/thumbnails/analysis/cache/reviews; retention cadence set explicitly. Audit evidence can remain public, athlete-specific snapshots cannot remain after privacy deletion unless user chose documented retention.
- Treat imported science text, research pages, photo notes and tool-returned excerpts as untrusted data: they cannot change system instructions, approve recommendations, choose another user or invoke actions. Source/quote validation and explicit separation from instructions belong in the review/retrieval boundary.
- Review audit saves compact inputs and concise rationale, not hidden chain-of-thought, raw image bytes or full transcript. Log IDs/status/timings, not birth dates, medical notes or private object URLs. Use existing configuration secrets; no new credentials in docs.
- Fitness boundary in proposed safety service + prompt + recommendation validation: coach lifting/nutrition/recovery/sleep habits; treat pain as user report. Severe/worsening/persistent pain, neurological symptoms or chest pain/breathlessness are concerns needing appropriate professional help, not a confident injury/condition label or instruction to train through symptoms. Keep a few clear rules and cautious outputs; no diagnosis engine or automated emergency detection claims.
- Do not prescribe medical treatment, extreme restriction, hazardous supplement/drug regimens or override clinician limitations. Unknown age/conditions and declined sex data remain unknown; avoid formulas that require missing inputs. Quantitative nutrition/program changes are proposals with bounds/coverage and approval; exact evidence-backed bounds will be established through curated science rather than hard-coded unsupported coaching claims here.
- Clinical symptoms may require urgent-care wording when explicitly reported; request clarifying information where appropriate, preserve safe fallback, do not classify every ordinary soreness message as a medical event. Safety logic never fabricates symptoms or contacts anyone automatically.

## 14. Implementation Phases

### Phase 0 — Ownership and Compatibility Prerequisites

Authenticate old/v2 fitness routes, map legacy records/source units/time conventions, validate disposable migration baseline, preserve API contracts. Scope exercise custom visibility and global schedule permissions. No new coaching outputs.

### Phase 1 — Fitness Foundation

Typed athlete profile, dated goals/targets and limitation history; owner-safe service layer and settings UI. Reuse existing phase/default target authority and keep old readers consistent.

### Phase 2 — Daily Tracking and Measurements

Extend check-ins, canonical metric ingestion/source resolution and projection updates; nutrition completeness and custom measurement periods/types. Manual entry plus existing HealthKit, no new wearable vendors.

### Phase 3 — Workout Tracking Consolidation

Normalize aliases/variants, stable exercise performances, load/effort/pain metadata, shared recalc/PR correction; migrate web fast UI to v2 while preserving phone/Watch compatibility.

### Phase 4 — Fitness Analytics and State

Deterministic objective metrics, coverage/staleness, state/API/cache, overview/charts, shared summary readers. No LLM dependency.

### Phase 5 — Weekly Coach

Validated local Qwen review, audited immutable inputs/references, on-demand jobs/results, proposals/explicit decisions, shared main chat context/read tools. No silent program/calorie changes.

### Phase 6 — Proactive Coaching

Configurable opted-in due preferences, idempotent job ledger, existing candidate/notification delivery, daily/weekly/monthly loops and duplicate suppression.

### Phase 7 — Progress Photos and Vision

Extend/harden existing photos and web UI; opt-in structured comparisons using verified vision capability, no body-fat estimates.

### Phase 8 — Curated Scientific RAG

Small accepted corpus, native pgvector chunks, metadata/revision/citation validation, unreviewed refresh queue, curated retrieval integrated into Coach reviews.

### Phase 9 — Program Generation and Progression

Typed versioned program templates/set plans and science-informed draft generation; deterministic rule evaluation and explicit activation. Existing dated phase/control mechanisms remain authority.

### Phase 10 — Advanced Coaching

Longitudinal adaptations, bounded user-approved automations, integration adapters, advanced nutrition/sleep/recovery and multi-year analytics. Add only after reliability/quality proves earlier phases.

## 15. STEP-BY-STEP AGENT IMPLEMENTATION INSTRUCTIONS

Follow these tasks in dependency order. Work in isolated development/test infrastructure. Inspect `CLAUDE.md` and `RECOVERY.md` first; respect any newer repository instructions. Existing file references are the baseline, not permission to deploy. Do not bulk-refactor unrelated memory/auth/cognition systems. Complete each listed gate before proceeding. The migration filename placeholders below mean create the next real revision with a valid <=32-character revision ID after checking current head; no literal `<next>` filename.

### Step 1 — Establish the source/schema/client contract baseline

**Goal:** make the implementation target reproducible without touching production.

**Files to inspect first:** `CLAUDE.md`, `RECOVERY.md`, `docker-compose.test.yml`, `backend/scripts/disposable_compose.sh`, `backend/scripts/provision_test_schema.sh`, `backend/tests/env_guard.py`, `backend/tests/fixtures/sara_hub_schema.sql`, `backend/alembic/env.py`, `backend/app/routes/fitness.py`, `backend/app/routes/workout_v2.py`, `ios-app/scripts/check-workout-contract-parity.mjs`.

**Files to create:** `PROPOSED: docs/plans/FITNESS_COACH_CONTRACT_BASELINE.md` (brief implementation-time schema/contract inventory, no private data); later in this step `PROPOSED: docker-compose.fitness-test.yml` only if an isolated MinIO/model-gateway overlay is needed for the planned integration tests.

**Files to modify:** none initially.

**Implementation instructions:**

1. Record current commit, clean/dirty status, actual Alembic graph/head from file parsing or an isolated configured migration environment. Do not import main_simple against ambient production configuration merely to list migrations.
2. Provision a named disposable database/Redis using existing wrapper and fixture. Verify test environment guard and point LLM, embeddings, MinIO and push stubs at isolated targets. Configure source-shaped credentials only through existing test configuration.
3. Existing test compose has database/Redis/embeddings but no test MinIO or real LLM. Add a narrowly scoped test-only overlay for MinIO/fake model transport when their tests need it; reuse existing software/images and isolated credentials, no production bucket or external push. The base test network is explicitly named `sara_test_net` and internal; do not run multiple concurrent stacks assuming distinct project names give distinct networks. Actual LLM/vision smoke tests require a separate deliberately isolated test gateway/runner with explicit approved endpoints, not weakening the disposable network guard.
4. Inventory columns/indexes/FKs needed by this plan in disposable schema, including source units, planned-active workout links, JSON/TEXT templates and native/TEXT chunk tables. Confirm version-table baseline before upgrading; do not `stamp head` to disguise an incomplete schema.
5. Trace route-mounted paths and tool execution/receipt behavior; capture existing web/iOS/Watch request/response examples without personal records. Preserve old field names and status enums.
6. Record baseline focused tests and workout parity outcomes. Baseline failures are issues with exact reproduction, not grounds to silently weaken assertions.

**Tests:** environment guard refuses production-shaped targets without sockets; disposable schema provision succeeds; current workout parity and representative workout/food/health tests run.

**Completion criteria:**

- [ ] Isolated source/schema baseline and current compatibility contracts documented.
- [ ] Test/migration commands cannot target production through defaults.
- [ ] No running production services/config/data changed.

**Do not proceed until:** test targets and current schema prerequisites are explicit; resolve any fixture/head mismatch needed for new tables.

### Step 2 — Authenticate fitness routes and isolate every actor

**Goal:** remove solo-owner identity from all externally callable fitness routes, including v2.

**Files to inspect first:** `backend/app/core/deps.py`, `backend/app/core/auth.py`, `backend/app/routes/fitness.py`, `backend/app/routes/workout_v2.py`, `backend/app/routes/fitness_inline.py`, `backend/app/routes/health_metrics.py`, `backend/app/tools/registry.py`, `backend/app/services/target_authorization.py`.

**Files to create:** `PROPOSED: backend/tests/test_fitness_auth_isolation_pg.py`.

**Files to modify:** `backend/app/routes/fitness.py`, `backend/app/routes/workout_v2.py`; relevant owned lookups in `backend/app/services/workout_session_service.py`, `backend/app/services/workout_command_service.py`, and existing fitness tools only when a traced operation lacks scope.

**Implementation instructions:**

1. Import User and the established dependency, then define `get_current_user_id(current_user: User = Depends(get_current_user)) -> str` returning `current_user.id`. Keep the helper import stable for v2, but explicitly document accepted device-token scope. No empty/missing identity fallback.
2. Audit all routes/helper SQL for parent/template/phase/session/set/recipe ownership. Foreign IDs must return 404; cannot authenticate only collection routes and leave `/chat`, file/action routes open.
3. Audit tool callers: explicit orchestration user must flow into the same owned service operations. A tool must not call solo-helper logic or infer owner from email/default config.
4. Handle existing solo-owned data by read-only ownership report. Do not automatically reassign to the currently logged-in user, first user or David by name. Preserve valid existing `SOLO_USER_ID` rows under their actual `app_user.id`; unresolved `default-user` rows need a separately reviewed mapping (Step 4).
5. Ensure cookie/Bearer/device clients still work; make anonymous old clients return 401 rather than fabricate another athlete.

**Tests:** real two users; unauthenticated read/write/start/command denied; A cannot read/update/delete B's food/target/template/session/set; forged user IDs ignored/rejected; revoked JWT denied; authorized mobile token still works; foreign command/recipe references denied before mutation; tool results/receipts retain actor.

**Completion criteria:**

- [ ] Every externally exposed fitness route derives a real authenticated user.
- [ ] All existing normal web/iOS actions retain response contracts.
- [ ] Cross-user mutations produce no side effects.

**Do not proceed until:** all auth/isolation fixtures pass; do not ship new athlete records behind the old helper.

### Step 3 — Create the shared data-access and validation foundation

**Goal:** owner-scoped read adapters and typed contracts without duplicate business logic.

**Files to inspect first:** `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/schemas/food_item.py`, `backend/app/core/timezone.py`, `backend/app/models/progress_photo.py`, `backend/app/services/workout_recalc.py`.

**Files to create:** `PROPOSED: backend/app/services/fitness/data_access.py`, `PROPOSED: backend/app/schemas/fitness_coach.py`, `PROPOSED: backend/app/services/fitness/__init__.py` (the directory itself already exists without one — see the caveat in Section 6), `PROPOSED: backend/tests/test_fitness_record_adapters.py`.

**Files to modify:** existing fitness routes/readers only for operations assigned below; do not move the whole monolith now.

**Implementation instructions:**

1. Add explicit owned query helpers and row adapters for health observations, food, recovery, planned/active sessions and template snapshots, with bounded periods/pagination. Proposed signatures: `load_observations(db, user_id, metric_types, start_at, end_at)`, `load_food_days(db, user_id, start_date, end_date)`, `load_training_sessions(db, user_id, start_date, end_date)`. No default user in these helpers.
2. Specify time conversion for naive ET food, naive UTC creation timestamps and aware health/session observations. Accept athlete timezone argument; never use ingestion date to refile an event.
3. Add units/conversion utilities and finite-number validation, scale/enums/period DTOs, omission vs clear semantics and versioned metric contract.
4. Establish a caller-owned transaction rule: repositories do not commit; mutation service returns only after commit; network/model work occurs outside transaction. Existing legacy methods that commit require explicit adapters, not pretending they're transactional.
5. Validate all parent IDs and nested payloads; do not permit arbitrary SQL column/type names from measurement/tool parameters.
6. Resolve the preexisting orphan `backend/app/services/fitness/conversational.py` before adding `__init__.py`: nothing imports it, so delete it (preferred) or record a deliberate decision to keep it. Do not let it become silently importable as part of the new package without that decision.

**Tests:** kg/lb/cm conversions and decimal precision; finite bounds; ET/DST midnight; absent vs zero; invalid/future date; cross-owner query constraints; JSON string/object legacy templates parse identically.

**Completion criteria:**

- [ ] Typed adapters do not connect on import or depend on LLM.
- [ ] Unit/date policy has one documented implementation.
- [ ] Session ownership/transaction boundaries are explicit.

**Do not proceed until:** normalization fixtures demonstrate old data can be read honestly, including unknown units.

### Step 4 — Audit and repair legacy ownership/schema prerequisites

**Goal:** make additive migrations safe for preexisting records.

**Files to inspect first:** `backend/tests/fixtures/sara_hub_schema.sql`, `backend/migrations/add_fitness_tables.py`, `backend/migrations/add_fitness_phases_templates.py`, `backend/alembic/versions/018_fitness_overhaul.py`, `backend/alembic/versions/093_workout_log_exercise_fk.py`, `backend/alembic/versions/139_workout_session_active_link.py`.

**Files to create:** `PROPOSED: backend/scripts/fitness_backfill_audit.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_ownership.py`, `PROPOSED: backend/tests/test_fitness_ownership_migration_pg.py`.

**Files to modify:** `backend/tests/fixtures/sara_hub_schema.sql` only through a deliberate isolated schema snapshot update after validated migrations.

**Implementation instructions:**

1. Write dry-run-first audit requiring explicit database target, reporting counts/IDs of owner orphans, duplicate active programs, overlapping phases, alias/units ambiguity and dangling session/canonical FKs. Do not print sensitive values.
2. For legacy custom exercise rows, derive provenance from referencing user rows where unambiguous; separate validated global seeds from user-private variants. Shared ambiguous rows retain restricted/unresolved status until reviewed.
3. Add missing ownership/index constraints only after conflict report and deterministic reconciliation. Foreign UUID alone is insufficient for cross-owner references; child APIs/services enforce it even if legacy DB constraints cannot yet.
4. Any actual data reassignment requires an explicit provided mapping and dry-run review. No new old-script execution; author Alembic changes or controlled migration service.
5. Validate schema fixture baseline vs migrations using disposable databases; checkpoint counts and verify replay is idempotent.

**Tests:** orphan/duplicate fixture rejected or reported; reviewed mapping alters only intended rows; rerun does not duplicate; newly added FKs preserve valid histories.

**Completion criteria:**

- [ ] Ownership inventory is reproducible and conflict policy documented.
- [ ] No implicit reassignment or lossy normalization.
- [ ] Additive schema changes keep old client contracts.

**Do not proceed until:** foundation target rows have valid owners and migration prerequisites are satisfied; ambiguous historical rows may remain quarantined and nonblocking for new records.

### Step 5 — Add athlete/goal/limitation models and first migration

**Goal:** structured athlete identity and historical goal priorities.

**Files to inspect first:** `backend/app/models/user.py`, `backend/app/models/user_settings.py`, `backend/app/models/profile.py`, `backend/app/db/base.py`, `backend/alembic/env.py`, `backend/app/services/goal_manager.py`.

**Files to create:** `PROPOSED: backend/app/models/fitness_coach.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_athlete.py`, `PROPOSED: backend/tests/test_fitness_athlete_models_pg.py`.

**Files to modify:** proposed fitness schemas; `backend/app/models/__init__.py` only if its import conventions require registration. Do not change Alembic's metadata globally to work around duplicate Base.

**Implementation instructions:**

1. Add AthleteProfile/Goal/Limitation as specified in Section 5, FK app_user, unique profile, user/date indexes, valid interval and numeric checks.
2. Implement historical primary-goal exclusion/serialized writer constraint. Additional priority goals may coexist; priorities and conflicts validated.
3. Preserve optional DOB/sex unknown; no default beginner/age/weight assumption and no permanent current-weight column.
4. Add row versions for profile concurrency; model defaults explicit. New migration must expose exact tables/indices/constraints and be safe on baseline fixture.
5. Inspect generated SQL; autogenerate output alone is not sufficient with two Bases. Recheck revision length and down_revision.

**Tests:** goal rollover/as-of dates and overlapping primary rejection; optional personal fields; FK/ownership; index/constraint existence; baseline upgrade and roundtrip in disposable DB.

**Completion criteria:**

- [ ] Athlete tables are additive and multi-user.
- [ ] Historical goals can be queried without reconstructing memory.
- [ ] Migration doesn't alter existing fitness records by default.

**Do not proceed until:** database constraints and goal valid-time semantics pass PostgreSQL tests.

### Step 6 — Implement athlete and historical-target services/APIs

**Goal:** one service truth for profile, goals, phase/default nutrition targets and historical revisions.

**Files to inspect first:** `backend/app/routes/fitness.py` goals/phase/program/today-target handlers, `backend/app/services/phase_resolution.py`, `backend/app/services/plan_adjust.py`, `backend/app/services/training_day.py`, `backend/app/tools/fitness/program_tools.py`, `backend/app/services/fitness_context.py`.

**Files to create:** `PROPOSED: backend/app/services/fitness/profile.py`, `PROPOSED: backend/app/services/fitness/targets.py`, `PROPOSED: backend/app/routes/fitness_coach.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_targets.py`, `PROPOSED: backend/tests/test_fitness_targets_pg.py`.

**Files to modify:** proposed models/schemas/data_access; `backend/app/main_simple.py` router mount; old target writers/readers in `backend/app/routes/fitness.py`, `backend/app/services/plan_adjust.py`, `fitness_context.py`, `backend/app/tools/fitness/program_tools.py` as applicable.

**Implementation instructions:**

1. Implement profile GET/PATCH with expected version; goal create/close/as-of; active limitation operations. Proposed service signatures: `get_athlete_profile(db, user_id)`, `get_goals(db, user_id, on_date)`, `resolve_targets(db, user_id, on_date, day_type)`, `create_target_revision(db, user_id, payload, expected_revision)`. Pass athlete-local `on_date` explicitly to existing phase/training-day resolvers; do not let their global ET default choose another timezone's date. Add authenticated `/api/fitness/coach` router outside import swallowing.
2. Add target revision table; resolve selected phase by existing function then approved historical target revision for that phase/date/day type, otherwise explicit legacy phase values. If no effective phase, resolve approved default revision then legacy fitness_goals with provenance; absent = unknown.
3. Current target updates create append-only approved snapshots with effective range; atomic current compatibility projection update. Bulk phase edits/template imports must delegate to shared target writer and retain history; no hidden second override source.
4. Convert inclusive old phase end to half-open resolution carefully. Ensure plan_adjust splitting/copying preserves revision references and effective dates; avoid applying today's macros to old split blocks.
5. Seed initial snapshots only from known state/date: use deployment migration date unless provable historical dates exist. Do not imply arbitrary current fitness_goals values were targets for all past months.
6. All targets returned include provenance/effective dates and unknown-history flags. Validated API changes need no LLM. User-driven edits are explicit; generated recommendations cannot call writer yet.

**Tests:** profile PATCH conflicts; primary/secondary goals; target midweek/training-rest changes; phase rollover/gap; default fallback; backdated correction/revision; overlapping updates concurrently; plan_adjust split consistency; old/new route output agrees for same date; two-user isolation.

**Completion criteria:**

- [ ] Current and historical target selection uses one resolver.
- [ ] Old macro endpoints and new APIs agree.
- [ ] Goal/target edits preserve prior values and legitimate provenance.

**Do not proceed until:** no known target writer bypasses revision recording, or is explicitly disabled for new coaching target edits until adapted.

### Step 7 — Build the athlete settings frontend

**Goal:** usable deterministic foundation without chat onboarding dependency.

**Files to inspect first:** `frontend/src/components/fitness/FitnessSection.tsx`, `frontend/src/api/client.ts`, `frontend/src/config.ts`, `frontend/src/main.tsx`, `frontend/src/components/ui/input.tsx`, `frontend/DESIGN_LANGUAGE.md`.

**Files to create:** `PROPOSED: frontend/src/api/fitnessCoach.ts`, `PROPOSED: frontend/src/types/fitnessCoach.ts`, `PROPOSED: frontend/src/hooks/useFitnessCoach.ts`, `PROPOSED: frontend/src/components/fitness/AthleteSettings.tsx`, `PROPOSED: frontend/src/components/fitness/__tests__/AthleteSettings.test.tsx`.

**Files to modify:** `frontend/src/components/fitness/FitnessSection.tsx`; auth logout/query handling only where user cache clearing is needed.

**Implementation instructions:**

1. Add typed credentialed API calls and Query keys by authenticated user; normalize 401/404/409/validation errors in human wording.
2. Add Settings subview with optional profile fields, equipment/exercise limitations, multiple ordered goals and effective-date target history. Keep existing program/phase/nutrition editors reachable; use shared target API behind them as adapted.
3. Forms distinguish unknown/declined and empty vs explicit removal; no generated numbers. Explain units and date ranges near input, not technical implementation terminology.
4. Query invalidation refreshes old dashboard/target consumers after edits. No new global fitness store.

**Tests:** empty profile, update conflict, effective date/rate units, unknown sex/DOB, target history display, cache isolation on account change, keyboard/touch forms, request errors.

**Completion criteria:**

- [ ] Athlete can set/edit profile and priorities without LLM.
- [ ] Goals and target revisions are visible with dates.
- [ ] Existing food/plan views remain usable.

**Do not proceed until:** build/typecheck/relevant UI tests pass and two-user API foundation is verified.

### Step 8 — Canonical observation ingest and legacy projection maintenance

**Goal:** weight/sleep/steps/water/body measures have consistent sources across all writers.

**Files to inspect first:** `backend/app/routes/health_metrics.py`, `backend/app/routes/fitness.py` weight/recovery, `backend/app/routes/fitness_inline.py`, `backend/app/services/health_metric_mirror.py`, `backend/app/services/health_insight_service.py`, `ios-app/src/services/healthSync.ts`, `ios-app/src/services/backgroundHealthSync.ts`.

**Files to create:** `PROPOSED: backend/app/services/fitness/observations.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_observations.py`, `PROPOSED: backend/tests/test_fitness_observation_ingest_pg.py`.

**Files to modify:** proposed schemas/data_access; existing health/weight/recovery ingestion paths and `backend/app/tools/fitness/recovery_log.py` to delegate consistently, with legacy request formats preserved.

**Implementation instructions:**

1. Add explicit units/provenance to health_metric; map current metric aliases and actual HealthKit unit contract before backfill. Reject/flag unknown units, no guessing lbs/kg from magnitude alone.
2. Implement idempotent ingest manual/provider samples, optional correction and source conflict tracking. Preserve current dedup keys/ON CONFLICT behavior until all providers are adapted. Manual correction must reference logical observation/date/source intentionally.
3. Select representative observations using deterministic per-metric rules. Sleep overnight totals vs stages are different types; overlapping totals cannot be summed. Daily steps cumulative samples need selected daily total, not raw sample sum.
4. Write canonical values and compatibility recovery/weight projections atomically where necessary; avoid a successful duplicate mirror yielding divergent values. Backdated changes rebuild affected trend projections and invalidate state after commit.
5. HRV existing mirror behavior remains compatible; add provenance flags for synthesized canonical stamps. Canonical time never falsely describes when the original sample was measured.
6. No network/model prerequisite for a numeric write. Failures rollback real writes, respond honestly and support replay; do not silently succeed when source storage failed.

**Tests:** manual + wearable same logical day; sample ID retry; conflict; manual correction; kg/lbs and sleep alias normalization; empty value/no overwrite; projected legacy readers agree; backdated correction; timezone edge; multi-user sources.

**Completion criteria:**

- [ ] All traced relevant ingest paths use shared source resolution.
- [ ] Canonical numbers agree with compatibility outputs or explicitly expose conflicts.
- [ ] Correction/replay doesn't create duplicate observations.

**Do not proceed until:** accepted metric units and source precedence are documented and executable; unresolved legacy source units are flagged separately.

### Step 9 — Extend daily check-ins and nutrition completeness

**Goal:** small partial daily updates with meaningful data-quality status.

**Files to inspect first:** `backend/app/routes/fitness.py` RecoveryLog models/food diary, `backend/app/routes/fitness_inline.py`, `backend/app/services/recovery_score.py`, `backend/app/schemas/food_item.py`.

**Files to create:** `PROPOSED: backend/alembic/versions/<next>_fitness_checkin.py`, `PROPOSED: backend/tests/test_fitness_checkins_pg.py`.

**Files to modify:** proposed models/schemas/observations/router; old recovery adapters as needed.

**Implementation instructions:**

1. Extend existing daily_recovery_log rather than create a separate day record. Add subjective fields/scales, bedtime/wake, nutrition completion, version and field-source map.
2. Add GET/PATCH check-in by local date; concurrent write protection; explicit clear distinct from omitted. Numeric physiological fields delegate to canonical ingest; macros are read from meals.
3. Add explicit nutrition complete/partial/unknown transitions with timestamp/source; completion never inferred from meal count or calories being high. Editing/removing a meal must indicate changed day and preserve or invalidate prior completion by documented policy (default invalidate completeness until reconfirmed).
4. Capture original source vs manual correction per field. Preserve hardware input on omitted manual PATCH.
5. Wrap readiness output: empty inputs unknown, partial inputs labeled partial; do not replace established formula under cover of check-in work.

**Tests:** partial fields preserve sleep/HRV; explicit null clears only chosen subjective field; scale validation; completeness revocation; duplicate day upsert; empty readiness; nutrition unknown fields; no direct double-stored macros.

**Completion criteria:**

- [ ] Day can be partially logged without fabricated values.
- [ ] Nutrition completion is explicit and auditable.
- [ ] Current recovery consumers remain compatible.

**Do not proceed until:** missing-value and concurrency semantics are covered with real PostgreSQL tests.

### Step 10 — Add extensible measurement types and periods

**Goal:** tape measurement history without per-new-measurement migrations.

**Files to inspect first:** `backend/app/routes/health_metrics.py`, `backend/app/models/progress_photo.py`, existing proposed observations/athlete models/schemas.

**Files to create:** `PROPOSED: backend/alembic/versions/<next>_fitness_measurements.py`, `PROPOSED: backend/tests/test_fitness_measurements_pg.py`.

**Files to modify:** proposed models/observations/router/data_access.

**Implementation instructions:**

1. Create global/common and private custom measurement definitions and owned measurement periods; seed waist/chest/neck/hips/arms/thighs/calves, sides/sites where relevant.
2. Store measured numbers as canonical health_metric with typed descriptor/period references, units and protocol. Reuse weight observations rather than another copied bodyweight field.
3. Implement type list/create and period/list/log/correction APIs; cap/custom-code length, compatible quantity/unit and owner checks. A supplied custom type from B cannot be used by A.
4. Preserve historical corrections/supersession; expose selected values and differences only for comparable protocol/site/side.

**Tests:** custom type created/logged with no new migration; duplicate code scope; mixed units; left/right distinction; foreign period/type; corrected series; negative/NaN rejection.

**Completion criteria:**

- [ ] Common and custom measurements work through one schema.
- [ ] Body observations remain single-authority.
- [ ] Protocol/date/side make comparisons reproducible.

**Do not proceed until:** ownership and comparability rules are verified.

### Step 11 — Build Today and measurement entry UI

**Goal:** low-friction daily logging, with truthful missing/source indicators.

**Files to inspect first:** `frontend/src/components/fitness/RecoveryLog.tsx`, `FoodLog.tsx`, `FitnessSection.tsx`, `frontend/src/utils/dateUtils.ts`, proposed fitness API/hook/types.

**Files to create:** `PROPOSED: frontend/src/components/fitness/DailyCheckIn.tsx`, `PROPOSED: frontend/src/components/fitness/Measurements.tsx`, `PROPOSED: frontend/src/components/fitness/__tests__/DailyCheckIn.test.tsx`, `PROPOSED: frontend/src/components/fitness/__tests__/Measurements.test.tsx`.

**Files to modify:** FitnessSection and new API/query layer; RecoveryLog only for shared entry duplication/consistency.

**Implementation instructions:**

1. Add Today quick entry with partial save, date picker, current source values, manual correction label and skip/snooze affordance. Render zero vs unknown distinctly.
2. Route meal entry to existing FoodLog; add explicit nutrition-finished control. Do not collect daily total in parallel with all meals.
3. Use backend athlete-local date as default; browser-local helper alone cannot choose the day for a traveling athlete. Submit timezone/date explicitly.
4. Measurements group by period and allow custom type/side. Preserve form on failures; optimistic updates rollback safely.
5. Show computed readiness only with coverage status, not a fabricated "excellent" empty day.

**Tests:** delayed/wearable data refresh, partial PATCH/null, date timezone, nutrition complete/revoke, custom measures, keyboard accessibility, API failure preserving inputs.

**Completion criteria:**

- [ ] Daily/measurement actions use at most one save per form.
- [ ] No duplicated weight/sleep/macros truth in UI state.
- [ ] Existing recovery/food flows show the same selected readings.

**Do not proceed until:** daily frontend and backend agree on date/source/completeness semantics.

### Step 12 — Normalize exercise identities and aliases

**Goal:** aliases group the same variant without merging different movements or users.

**Files to inspect first:** `backend/app/services/exercise_library_seed.py`, `backend/app/routes/fitness.py` exercise API, `backend/alembic/versions/093_workout_log_exercise_fk.py`, `backend/app/services/progressive_overload.py`, `backend/app/services/workout_command_service.py` variant selection.

**Files to create:** `PROPOSED: backend/app/services/fitness/exercises.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_exercise_alias.py`, `PROPOSED: backend/tests/test_fitness_exercise_normalization_pg.py`.

**Files to modify:** proposed models/data_access; existing exercise API/seed and affected workout/template/PR lookup adapters.

**Implementation instructions:**

1. Add scope/global visibility, alias table and canonical variant metadata with load convention/muscle roles. Start with small explicit catalog + actual histories, not huge imports.
2. Normalize case/whitespace/unambiguous abbreviations for exact alias lookup. Ambiguous labels return candidates; fuzzy matches never silently rewrite a logged set or earn merged PR.
3. Add reviewed alias mapping for Bench Press/Barbell Bench/BB Bench only where equivalent variant. Separate DB bench, machines, inclined, ROM and unilateral variants.
4. Backfill canonical shadow FK in dry-run batches; preserve legacy exercise_id/display name and record mapping provenance. Never infer muscle taxonomy authoritatively from vague "horizontal push" placeholder.
5. Restrict custom exercise visibility and edit permissions; exposed global lookup cannot leak private user-created names.

**Tests:** alias equivalence, ambiguity, equipment variation separation, owner-private names, existing FK/name compatibility, idempotent reviewed backfill, unknown legacy names stay unresolved.

**Completion criteria:**

- [ ] Stable canonical identities power comparisons.
- [ ] Existing variants/history remain available to correct owner.
- [ ] Catalog growth doesn't require schema migrations per exercise.

**Do not proceed until:** load convention and identity/alias scope are explicit for newly logged exercises.

### Step 13 — Add exercise performances, load/effort metadata and pain

**Goal:** session → stable exercise occurrence → existing performed set structure.

**Files to inspect first:** `backend/app/services/workout_command_service.py`, `workout_session_service.py`, `workout_recalc.py`, `set_plan.py`, `backend/app/routes/workout_v2.py`, `backend/alembic/versions/125_flexible_workout_sets.py`, `ios-app/src/services/workoutContracts.ts`.

**Files to create:** `PROPOSED: backend/alembic/versions/<next>_fitness_performance.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_pain.py`, `PROPOSED: backend/tests/test_fitness_performance_pg.py`, `PROPOSED: backend/tests/test_fitness_pain_pg.py`.

**Files to modify:** proposed models/schemas/data_access; existing command/recalc/adapters/routes; contract copies only for deliberate versioned/additive wire change.

**Implementation instructions:**

1. Create stable exercise occurrence per session snapshot slot. Preserve repeated same exercise and set order. Link existing workout_log rows by unambiguous occurrence; unresolved historical rows retain fallback identity.
2. Add fractional canonical load/unit and RIR/decimal effort/role/failure/rest/tempo fields. Introduce central effective-load adapter; compatibility integer values cannot silently erase fractional actual data. If old wire cannot represent new load, reject unsupported write or version contract with explicit old-client fallback, never truncate.
3. Keep structural `set_kind` working/warmup/drop and counts rules. Top/backoff/AMRAP roles are separate. Drop parent must be same user/session/occurrence.
4. Extend command payload validation and revision/void paths; IDs stable/idempotent, recalc from nonvoided records. Every write delegates command service; new coach API cannot bypass lock/version.
5. Pain records attach to actual occurrence/set or standalone day, with explicit pain_present/severity/site/notes; missing is unknown. Corrections preserve provenance.
6. Version stored session snapshot with canonical prescription/target references so future edits cannot rewrite past workouts. Preserve legacy session APIs.

**Tests:** duplicate exercise occurrences; decimal/unit loads; RIR/RPE consistency; working roles; warmup/drop counts; concurrent phone/web commands; retries; correction/void recalculation; PR retraction; pain across four distinct sessions; foreign set/parent references; old-client payloads.

**Completion criteria:**

- [ ] Existing command reliability and completion counting remain valid.
- [ ] Actual load/effort/pain retain precision and identity.
- [ ] Old phone/Watch compatibility passes parity and roundtrip tests.

**Do not proceed until:** every actual set write/correction reader uses the same effective-load/canonical occurrence adapter.

### Step 14 — Put fast web logging on workout v2

**Goal:** one-screen, one-action set logging independent of LLM latency.

**Files to inspect first:** `frontend/src/components/fitness/ActiveWorkout.tsx`, `WorkoutLogEnhanced.tsx`, `backend/app/routes/workout_v2.py`, `backend/app/services/workout_command_service.py`, `ios-app/src/services/workoutContracts.ts`.

**Files to create:** `PROPOSED: frontend/src/hooks/useWorkoutCommands.ts`, `PROPOSED: frontend/src/components/fitness/__tests__/ActiveWorkoutCommands.test.tsx`.

**Files to modify:** ActiveWorkout, WorkoutLogEnhanced, proposed fitness client/types where appropriate.

**Implementation instructions:**

1. Implement authenticated v2 start/active/commands/sync hooks with per-attempt UUID persisted before send, expected version and projection refresh. Existing web has no proven separate workout wire contract; align types explicitly with backend and test.
2. Show current exercise sets/previous comparable performance, inline load/reps/RIR, duplicate-last and large submit; keyboard Enter advances appropriately. No modal per completed set.
3. Failed acknowledgment replays byte-identical command; 409 preserves input and shows reconciliation from current projection. Never allocate new command_id merely because network retry occurred.
4. Rest timing comes from server timestamps; clients compute display countdown only. Finish displays pending/unlogged sets and pain summary without inventing completion.
5. Optional async coaching sentence can arrive later; set durable success visible immediately even if LLM is down.

**Tests:** double tap/disconnect retry one committed set; conflict refresh no silent overwrite; fractional display; duplicate-last; correction/void; two-device sync; keyboard/mobile focus; model unavailable doesn't stall.

**Completion criteria:**

- [ ] Start/log/finish require no extra navigation per set.
- [ ] Web is a reliable v2 controller.
- [ ] Existing iOS/Watch/backend parity remains green.

**Do not proceed until:** manual and automated retry/concurrency scenarios preserve exactly one accepted record.

### Step 15 — Implement weight, nutrition and sleep analytics

**Goal:** reproducible math and honest coverage before any coach reasoning.

**Files to inspect first:** `backend/app/services/health_consolidation/data_collector.py`, `recovery_score.py`, `backend/app/routes/fitness.py` trend/food summaries, proposed data_access/targets/observations.

**Files to create:** `PROPOSED: backend/app/services/fitness/analytics.py`, `PROPOSED: backend/tests/test_fitness_weight_analytics.py`, `PROPOSED: backend/tests/test_fitness_nutrition_analytics.py`, `PROPOSED: backend/tests/test_fitness_sleep_analytics.py`.

**Files to modify:** proposed schemas for typed metric results; established calculation callers only in Step 18.

**Implementation instructions:**

1. Implement explicit as-of calendar windows, representative daily weight means, eligibility thresholds, previous-window/longer slope and goal comparison from Section 9.
2. Implement complete/partial nutrition counts/means and day-specific target adherence with individual field denominators. No averaging over missing days as zero.
3. Implement selected nightly duration/target deviation and circular bedtime/wake consistency, subjective scale trends and coverage.
4. Return numeric raw precision plus display rounding policy, metadata/formula version/unavailable reason. Use hand-derived independent fixtures, not tests that reimplement the same function.
5. Add local-date boundary and goal/target-change fixtures; demonstrate same output when input row order changes.

**Tests:** known means/slope, sparse/missing/duplicate weights, one weight cannot claim stable trend; target changed midweek; rest/training targets; partial macros; zero legitimate values; overnight/DST sleep; outlier flags; unknown vs perfect readiness.

**Completion criteria:**

- [ ] All scalar analytics are pure and independent of LLM/Redis/database availability.
- [ ] Expected values and null cases verified independently.
- [ ] Historical target/date/units changes handled explicitly.

**Do not proceed until:** numerical fixtures and coverage behavior pass.

### Step 16 — Implement training, PR, pain and data-quality analytics

**Goal:** performance/trend metrics reflect real working sets and comparisons.

**Files to inspect first:** `backend/app/services/workout_recalc.py`, `progressive_overload.py`, `training_day.py`, `set_plan.py`, `backend/tests/test_workout_set_correction.py`, `backend/tests/test_workout_flexible_sets.py`, proposed performance/analytics adapters.

**Files to create:** `PROPOSED: backend/tests/test_fitness_training_analytics.py`, `PROPOSED: backend/tests/test_fitness_prs_pg.py`, `PROPOSED: backend/tests/test_fitness_data_quality.py`.

**Files to modify:** proposed analytics/data_access; existing PR calculation/withdrawal paths in command/recalc service through shared helpers; additive PR migration if required by Section 5.

**Implementation instructions:**

1. De-duplicate planned/active/legacy sessions and define historical planned denominator from snapshots. Missing schedule history yields unknown adherence.
2. Compute working sets, primary/secondary muscle exposure, compatible tonnage, frequency and comparable performance. Respect void/skipped/drop/role rules and fractional units.
3. Add Epley eligibility and exact/estimate distinction; deterministic PR categories and tie handling. Ensure source correction/void rescans eligible sets and withdraws old PR.
4. Implement cautious progression/stagnation eligibility and pain distinct-session counts with reporting coverage. Unknown pain not pain-free.
5. Build data-quality summary for missing/stale/unresolved measurements/targets/metrics/photos and incomplete workouts. Overdue checks follow enabled preferences, not a hard-coded judgment.

**Tests:** two-a-day count; superseded/voided/warmup/drop, direct vs indirect muscles; machine/bodyweight limitations; 1 rep and 10+ rep e1RM eligibility; fractional precision; rep/load/e1RM ties; voided source retraction; cross-owner PR; insufficient stagnation data; stale/no target and disabled reminders.

**Completion criteria:**

- [ ] Session/set/PR totals agree with command recalc.
- [ ] Metric limits and missing denominators are explicit.
- [ ] No LLM required to determine PR or trend.

**Do not proceed until:** regression tests prove corrections can't leave false volume/PR/trend claims.

### Step 17 — Assemble FitnessState and add bounded analytics APIs/cache

**Goal:** deterministic current state shared by all consumers.

**Files to inspect first:** `backend/app/services/context_snapshot.py`, `context_budget.py`, `unified_context.py`, `backend/app/services/world_state/writer.py`, proposed metric adapters/schemas.

**Files to create:** `PROPOSED: backend/app/services/fitness/state.py`, `PROPOSED: backend/tests/test_fitness_state.py`, `PROPOSED: backend/tests/test_fitness_state_api_pg.py`.

**Files to modify:** proposed router/data_access; mutation services for post-commit invalidation/event hooks.

**Implementation instructions:**

1. Collect bounded owned inputs at explicit as-of/data revision and resolve goals/targets/prescriptions. Proposed state interface: `build_fitness_state(db, user_id, as_of, period_end=None, sections=None, fresh=False) -> FitnessStateV1`; `render_fitness_capsule(state, char_budget) -> str`. Compute coverage/missing/changes/limitations; parameters cannot fall back to a shared owner.
2. Add `/state` and `/analytics` authenticated endpoints with period bounds, relevant metric groups and source-revision metadata. Read-only, no hidden model calls.
3. Introduce Redis cache optional; key user/date/timezone/state/analytics/data revision. Short TTL plus invalidation after observation/meal/set/goal/target edits. Recompute fresh for audit reviews. The repository pins `redis<5.0.0`: async clients use `.close()`, not `.aclose()` — `.aclose()` does not exist in this version and raises AttributeError at runtime.
4. Append thin durable world events in same transaction for important new writes and trigger invalidation after commit. Best-effort pub/sub failure never loses source data. Avoid copying raw private records into world facts.
5. Include unknown/degraded response if a dependency fails, rather than stale output labeled current. Database failure isn't an empty data set.

**Tests:** state snapshot stable for same input; missing entries survive serialization; no-cross-user cache; Redis down; missed invalidation bounded staleness; backdated update; owner scope; API dates/pagination; no source DB session shared concurrently.

**Completion criteria:**

- [ ] One typed state supplies UI/tools/reviews.
- [ ] Model/Redis outages do not break record logging or deterministic state.
- [ ] State freshness and version are explicit.

**Do not proceed until:** state API and audit collector match for same as-of period.

### Step 18 — Consolidate existing summary readers and build overview/charts

**Goal:** eliminate contradictory fitness math across Sara's surfaces.

**Files to inspect first:** `backend/app/services/fitness_context.py`, `world_brief.py`, `health_consolidation/data_collector.py`, `backend/app/tools/fitness/summary.py`, `food_log.py`, `workout_log.py`, `frontend/src/components/fitness/FitnessSection.tsx`, `RecoveryTrendChart.tsx`.

**Files to create:** `PROPOSED: frontend/src/components/fitness/CoachOverview.tsx`, `PROPOSED: frontend/src/components/fitness/__tests__/CoachOverview.test.tsx`, `PROPOSED: backend/tests/test_fitness_consumer_parity_pg.py`.

**Files to modify:** existing summary/context/readers incrementally; proposed frontend API/hooks/types and FitnessSection.

**Implementation instructions:**

1. Delegate summary/trend readers to shared metric/state methods while preserving old response shapes. Stop using food.created_at as eaten date and arbitrary seven readings as week.
2. Keep current target/training-day resolution consistent in dashboard, voice, world brief, weekly health collector and tools. Linked health report can remain existing format but source analytics match.
3. Overview displays goal/phase, latest/date-tagged weight/trend, known macros/targets, sleep/recovery coverage, today's sessions, latest performance and one priority/missing action.
4. Recharts series show gaps and coverage, no invented points. Measurements compare comparable protocols. Split historical periods/target changes visibly.
5. Measure response/context payload size; render compact state rather than raw months of meals or sets.

**Tests:** same metrics/targets/date from old tool/new API/overview/brief; chart missing-data behavior; one weight no plateau; incomplete nutrition; keyboard quick actions; backdated invalidation updates all relevant screens.

**Completion criteria:**

- [ ] Existing fitness summaries no longer contradict canonical analytics.
- [ ] Fitness Overview works with full/partial/no data.
- [ ] Prior food/training functionality remains available.

**Do not proceed until:** consumer parity fixtures and selected UI tests pass.

### Step 19 — Add immutable Coach Review and recommendation audit models

**Goal:** a reviewable explanation trail before generating recommendations.

**Files to inspect first:** `backend/app/models/health_weekly_report.py`, `backend/app/services/health_consolidation/runner.py`, `backend/app/models/chat_pending_proposal.py`, `backend/app/services/action_receipt_service.py`, proposed state/schemas.

**Files to create:** `PROPOSED: backend/alembic/versions/<next>_fitness_review_audit.py`, `PROPOSED: backend/tests/test_fitness_review_audit_pg.py`.

**Files to modify:** proposed fitness models/schemas/data_access.

**Implementation instructions:**

1. Add review/recommendation schema from Section 5, period hash/version/model/template/input snapshot, status/error, evidence references and proposed-action fields.
2. Unique occurrence/input/prompt key prevents duplicate run on retry; reviewed regeneration after data correction gets a new linked revision, not overwrite.
3. Review snapshot is compact complete necessary state with metric versions; not giant prompt or raw transcript. Record source cutoff/data revision and collected-at; ensure source collection has consistent transaction/isolation or revision check.
4. Define status machine and terminal transitions; persist failure reason category without sensitive prompts. Queries always owned.
5. Recommendation is proposal only; no implicit target/template update in migration/defaults.

**Tests:** idempotent duplicate request; corrected data new version; immutable completed input; failure/no output; owner FKs; stored model/template/evidence hashes; compact serialization bounds.

**Completion criteria:**

- [ ] "Why calories/deload?" can be traced to frozen metrics/references.
- [ ] Recommendation schema cannot masquerade as applied change.
- [ ] Review data retention/deletion follows owned privacy policy.

**Do not proceed until:** storage/audit state machine and idempotency work without model integration.

### Step 20 — Implement safety and validated on-demand Weekly Coach

**Goal:** Qwen interprets objective state with auditable, safe, review-only output.

**Files to inspect first:** `backend/app/core/llm.py`, `backend/app/services/llm_broker.py`, `backend/app/services/health_consolidation/runner.py:_llm_json`, `backend/app/prompts/fitness_system_prompt.py`, proposed FitnessState/audit contracts.

**Files to create:** `PROPOSED: backend/app/services/fitness/safety.py`, `PROPOSED: backend/app/services/fitness/reviews.py`, `PROPOSED: backend/app/prompts/fitness_coach_review.py`, `PROPOSED: backend/app/tasks/fitness_coach.py`, `PROPOSED: backend/tests/test_fitness_review_output.py`, `PROPOSED: backend/tests/test_fitness_reviews_pg.py`.

**Files to modify:** proposed coach router/schemas; `backend/app/celery_app.py` include/task routes, optionally `backend/app/core/feature_flags.py` with disabled-by-default review flag.

**Implementation instructions:**

1. Implement prior 7 full local days plus 14/28 aggregates, active/evaluated goals and historical targets, pain/quality/recent changes. Select fixed input snapshot before releasing DB transaction.
2. Add explicit request endpoint that creates/replays queued review job and returns status ID; GET retrieves/polls result. Job explicit user_id, bounded retry/time limit and health queue; no default owner fallback.
3. Call background local client, use max_tokens/thinking controls; capture actual model/fallback, usage/duration and template version. Existing 3-stage health report isn't mandatory: start one bounded validated coach call unless evidence shows a need for stages.
4. Parse/Pydantic/reference-validate/safety-check output; one repair max. Unknown IDs/invented metrics/unsafe actions reject. Missing science corpus means no scientific citations, clearly limited evidence support.
5. Mark insufficient_data where coverage can't support changes; ask for useful data. Existing prescriptions may be discussed from explicit program rules; new numeric nutrition/volume changes lacking curated support remain provisional proposals, never scientifically claimed certainty.
6. Store validated result/audit then expose to UI. LLM/network errors preserve deterministic state; no held transaction during call. No target writer invoked here.

**Tests:** valid/malformed/fenced/empty JSON, bad enums/evidence/metric IDs, unsupported numeric bounds, severe pain concern vs normal soreness, insufficient logs, provider outage/timeouts, duplicate workers one artifact, request/user isolation, review generation makes zero target/program mutations.

**Completion criteria:**

- [ ] On-demand Weekly Review is inspectable and explains its limits.
- [ ] Structured output validation is enforceable beyond prompt instructions.
- [ ] No major plan/target changes occur during review generation.

**Do not proceed until:** review contract/safety/outage fixtures pass and one real isolated local-model smoke test validates transport/output; mock-only JSON tests cannot prove deployed capability.

### Step 21 — Add explicit recommendation decisions and acceptance

**Goal:** concrete proposals change plans only after verified owner intent.

**Files to inspect first:** `backend/app/services/workout_command_service.py` proposal/approved-policy flow, `backend/app/services/plan_adjust.py`, `backend/app/services/tool_mutation.py`, `operation_contract.py`, `target_authorization.py`, `action_receipt_service.py`, `outcome_grounding.py`.

**Files to create:** `PROPOSED: backend/app/services/fitness/recommendations.py`, `PROPOSED: backend/tests/test_fitness_recommendation_acceptance_pg.py`.

**Files to modify:** proposed coach router/models; shared target/program service hooks; action boundary services only for precisely scoped new operation contracts.

**Implementation instructions:**

1. Show typed old→proposed value, scope/effective date/reason/coverage, valid target/program revision and expiry. Accept/reject are separate owner actions.
2. First enable maintain/request-data decisions and explicit target revisions with complete validated proposed targets; defer complex program restructuring until typed program service Step 29. Unsupported action remains reviewable advice with manual change link.
3. Acceptance locks owned recommendation, rechecks current revision/effective date/limitations/coverage and payload bounds; rejects expired/stale proposals with clear 409 and recompute option.
4. Atomically append target revision or permitted plan action, transition decision, commit action receipt. Duplicate acceptance returns existing receipt; rejected/expired cannot apply.
5. Update older phase/program action-tool gates for major changes, not just new review acceptance. No model-generated confirmation based solely on intent; outcome-grounded message uses committed receipt.

**Tests:** unauthorized/foreign/expired/stale proposal; acceptance exactly once under concurrency; no implicit acceptance in chat; reject no target change; action receipt matches new revision; DB failure leaves unapplied proposal; unsupported actions do not execute.

**Completion criteria:**

- [ ] User approves an exact reviewable change, not a vague intention.
- [ ] Acceptance is idempotent/audited and rollback-safe.
- [ ] Existing in-session workout policy remains separately bounded.

**Do not proceed until:** approval and committed-action boundary tests pass.

### Step 22 — Build Coach review frontend

**Goal:** read reviews, inspect reasoning/data limitations and explicitly decide changes.

**Files to inspect first:** `frontend/src/components/fitness/FitnessSection.tsx`, `frontend/src/components/fitness/PlanView.tsx`, proposed API/state hooks/types and overview.

**Files to create:** `PROPOSED: frontend/src/components/fitness/CoachReviews.tsx`, `PROPOSED: frontend/src/components/fitness/__tests__/CoachReviews.test.tsx`.

**Files to modify:** FitnessSection/new API/hooks/types.

**Implementation instructions:**

1. Add Coach subview list/detail, period/date/goal metadata, structured summary and metric/evidence links. Request review explicit, poll boundedly, support failed/insufficient-data states.
2. Render proposed changes with old/new values/effective date; separate accept/reject with concrete confirmation. Reject stale update gracefully and refresh; do not auto-accept on navigation.
3. Show current complete/partial days and why unavailable. Evidence not yet present means no fabricated citation UI.
4. Query invalidation after acceptance updates target/overview/plan; old review remains unchanged and shows decision receipt status.

**Tests:** queued→running→complete/failed, duplicate click, unknown confidence/data, acceptance confirmation/stale conflict, target invalidation, multiple review versions, account change.

**Completion criteria:**

- [ ] Review and acceptance are fully operable outside chat.
- [ ] Evidence/coverage/rationale accessible without raw JSON.
- [ ] Unsupported actions remain advice, never hidden execution.

**Do not proceed until:** review UX/API contract/outage states verified.

### Step 23 — Wire Sara context, read tools and memory boundary

**Goal:** main Sara knows bounded fitness state without another persona or raw-history calculations.

**Files to inspect first:** `backend/app/main_simple.py` main/voice context and tool selection, `backend/app/services/fitness_context.py`, `world_brief.py`, `context_snapshot.py`, `chat_assembly.py`, `backend/app/tools/base.py`, `registry.py`, `mutating.py`, `backend/app/services/tool_retrieval.py`, `backend/skills/fitness-coaching/SKILL.md`, `backend/app/services/personal_knowledge_graph.py`.

**Files to create:** `PROPOSED: backend/app/tools/fitness/coach.py`, `PROPOSED: backend/tests/test_fitness_context_integration.py`, `PROPOSED: backend/tests/test_fitness_tool_contracts.py`, `PROPOSED: backend/tests/test_fitness_memory_boundary.py`.

**Files to modify:** listed context/tool integration files, `backend/app/prompts/fitness_system_prompt.py`, application fitness skill, `backend/app/services/pkg_realtime_extractor.py` and PKG metric/target exclusion policy where needed, affected fitness numeric-memory writers.

**Implementation instructions:**

1. Implement narrow read tools per Section 8; retain existing names/schemas, delegate summary/read math to shared state. Register category/retrieval metadata and generate tool types.
2. Integrate compact state through fitness_context/world brief then chat assembly allocation; active workout and safety limitations can't be clipped into irrelevance during a fitness turn. Don't append a second duplicate block to every unrelated turn.
3. Adopt one Sara persona with domain guidance; legacy dedicated fitness chat must use same state/tools/mutation boundaries, not diverge or claim older history calculations.
4. Update application skill: retrieve workouts/targets from structured tools, preference memories separately; remove default beginner/owner-only assumptions and blanket repetitive check-in questions.
5. Exclude newly structured body/target facts from authoritative PKG numeric copies. Preserve real chat episodes and old memory provenance; structured current goals outrank stale memories. Do not erase all historic fitness conversations.
6. Add action tools only once corresponding services/receipts exist; register mutation classification/user-origin/operation/owned-target contracts. All output is ToolResult; model cannot supply user_id.
7. Enforce budgets across local and selected cloud chat paths; local coach review stays local regardless of selected chat persona.

**Tests:** fitness relevant/unrelated turns, budget saturation with dialogue corrections/world facts, voice parity, historical numeric memory doesn't override metric, cross-user preference isolation, tool menu limits, malformed args, read tool no mutation, denied action no receipt, valid action outcome-grounded.

**Completion criteria:**

- [ ] Sara responds from deterministic fitness facts across chat/voice/UI.
- [ ] Preference memory and structured record authority do not compete.
- [ ] All new tools follow registry/mutation/receipt conventions.

**Do not proceed until:** conversation/tool/budget regressions pass and no duplicate fitness prompt state remains.

### Step 24 — Add configurable coaching cadence and durable job occurrences

**Goal:** multi-user recurring work using existing scheduler and queues.

**Files to inspect first:** `backend/app/models/scheduled_job.py`, `backend/app/celery_beat/db_scheduler.py`, `backend/app/celery_app.py`, `backend/app/celery_signals.py`, `backend/app/routes/schedules.py`, `backend/app/services/scheduler_diet.py`, `backend/app/tasks/health_weekly.py`.

**Files to create:** `PROPOSED: backend/app/services/fitness/coaching_jobs.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_cadence.py`, `PROPOSED: backend/tests/test_fitness_coaching_schedules_pg.py`.

**Files to modify:** proposed models/router/tasks; celery registration/routes; global schedule API access only where required to enforce ownership/admin separation; AthleteSettings cadence UI.

**Implementation instructions:**

1. Create per-user cadence/preferences and occurrence ledger; default disabled, specific consent toggles for check-in/review/tape/photo. Set timezone/anchor/snooze/next due.
2. Seed one approved global due-sweep ScheduledJob on health queue; routes never let athlete inject task_name/queue/kwargs/user ID. Global schedule control requires proper admin policy rather than trusting any auth.
3. Transactionally claim due occurrences in bounded batch, persist run key, enqueue explicit user task. Reconcile claim-with-enqueue-failure so it retries rather than disappearing; unique ledger prevents duplicate run.
4. Handle clocks/DST/14/28-day anchor and dispatch-vs-completion separately. No fixed owner fallback in new tasks. Jobs check latest preference version before acting; disabled/snoozed occurrence becomes noop. Known DBScheduler gotcha: it has seeded UTC `last_run_at` values that made daily ET crons fire twice (see `backend/tests/test_db_scheduler_beat_double_fire.py`); the unique occurrence ledger must absorb a duplicate dispatch of the sweep into exactly one artifact, and a double-fired sweep in tests is this known behavior, not a ledger bug.
5. Reuse weekly health reports through explicit link or shared review computation, and retire duplicate coaching announcements only after compatibility check.

**Tests:** two-user cadences, cron/sweep reload, DST repeated/skipped hour, 14-day anchor, concurrent sweeps/retry/worker loss, enqueue failure, opt-out/snooze, expired occurrence, global settings unauthorized edit, actual task completion status.

**Completion criteria:**

- [ ] All coaching cadences configurable, per-user and opt-in.
- [ ] Retry/restart never produces two reviews per occurrence.
- [ ] Global schedule configuration cannot be hijacked through athlete settings.

**Do not proceed until:** occurrence/job execution and permission fixtures pass before enabling notifications.

### Step 25 — Route daily loops through existing candidate/delivery controls

**Goal:** useful proactive requests without duplicates or unwanted target changes.

**Files to inspect first:** `backend/app/services/say_candidate.py`, `judge.py`, `compose.py`, `unified_notification.py`, `interruptibility.py`, `backend/app/tasks/mindv2_deliver.py`, `backend/app/services/morning_brief_service.py`, `backend/app/services/daily_rhythm.py`, `backend/app/services/standing_order_service.py`.

**Files to create:** `PROPOSED: backend/tests/test_fitness_proactive_delivery.py`, `PROPOSED: backend/tests/test_fitness_daily_loop_pg.py`.

**Files to modify:** proposed coaching_jobs/tasks/state; existing brief/weekly adapters only to consume shared candidate keys/results.

**Implementation instructions:**

1. Select one priority missing detail per occurrence from quality state: sleep/weight/nutrition completeness/pain as relevant, never all questions simultaneously.
2. Generate owned candidate with stable date+metric/occurrence key, evidence ref/expiry; autonomous delivery via existing judge/compose/review. Explicit reminder results use existing requested-intent delivery policy while honoring notification preferences.
3. Recompute before candidate creation/delivery; data entered since task queued cancels obsolete request. Quiet/directive/standing-order/category opt-out produces recorded suppression/noop, not silent bypass.
4. Coalesce morning brief/check-in/health review missing-data keys and weekly report notices. Deep links open Fitness/Today/Coach with owned query ID; never publish private values on lock screen by default.
5. Ensure pre/post training loops use exact sessions and approved prescriptions; fatigue concern is suggestion, not automatic cancelled workout/deload.

**Tests:** duplicate producers and retries yield one entity candidate; new data suppresses question; cooldown/quiet/directive/snooze; no device tokens still readable Coach artifact; wrong-owner link denied; job complete but notification suppressed distinguished; no program/target mutations.

**Completion criteria:**

- [ ] Daily and weekly loops respect opt-in and delivery gates.
- [ ] Requested artifact available despite push suppression.
- [ ] One source can't bypass another source's dedup key.

**Do not proceed until:** notification preference and duplicate-delivery regression tests pass.

### Step 26 — Harden and extend existing progress-photo storage/metadata

**Goal:** standardized owned capture periods with robust image lifecycle.

**Files to inspect first:** `backend/app/models/progress_photo.py`, `backend/app/routes/progress_photos.py`, `backend/app/services/docs_ingest.py`, `ios-app/src/services/progressPhotos.ts`, `ios-app/src/components/fitness/views/ProgressPhotosView.tsx`.

**Files to create:** `PROPOSED: backend/app/services/fitness/photos.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_photo_metadata.py`, `PROPOSED: frontend/src/components/fitness/ProgressPhotos.tsx`, `PROPOSED: backend/tests/test_fitness_photos_pg.py`, `PROPOSED: frontend/src/components/fitness/__tests__/ProgressPhotos.test.tsx`.

**Files to modify:** existing photo model/routes/storage helpers as needed; proposed API/hook/types and FitnessSection Progress composition; preserve iOS fields/endpoints.

**Implementation instructions:**

1. Add view/period/capture metadata/weight reference/consent. Legacy bodyweight snapshot is display context, never automatic authoritative weight ingestion.
2. Enforce streaming byte limit/decode pixel limit/valid image MIME, normalize orientation and strip EXIF/GPS; reject invalid content, no mislabeled fallback JPEG.
3. Store full/thumbnail through existing object abstraction; maintain TLS/config correctly for new clients. Preserve existing object keys; optional scoped new keys supported additively.
4. Compensate upload DB failure; retain cleanup state on delete failure and retry blobs rather than orphaning private bytes. Owner checks before all reads/analysis/deletion.
5. Web Progress gallery/period/front-side-back upload, date/notes and optional comparison preparation. No new vision analysis enabled yet; remove body-fat request from legacy prompt before exposing critique.

**Tests:** foreign IDs/full/thumb, invalid image/oversized/decompression limit, EXIF removal, wrong period owner, MinIO failure/DB failure cleanup, delete retry, iOS response compatibility, private keys not exposed.

**Completion criteria:**

- [ ] Existing photo storage extended rather than duplicated.
- [ ] Image privacy/cleanup failures are tracked truthfully.
- [ ] Standardized captures work without LLM.

**Do not proceed until:** owned photo lifecycle passes isolated MinIO/Postgres tests.

### Step 27 — Add opt-in structured vision observations

**Goal:** comparable photo observations, not numerical body composition estimates.

**Files to inspect first:** `backend/app/routes/vision.py`, `backend/app/core/vision_formatters.py`, `backend/app/core/llm_config.py`, `backend/app/models/user_settings.py`, existing photo critique route.

**Files to create:** `PROPOSED: backend/app/prompts/fitness_photo_observations.py`, `PROPOSED: backend/app/models/fitness_photo_analysis.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_photo_analysis.py`, `PROPOSED: backend/tests/test_fitness_photo_analysis.py`.

**Files to modify:** proposed photos/task/state/schemas and existing vision helpers only for safe common transport and explicit JSON capability; photo frontend for optional analysis.

**Implementation instructions:**

1. Verify selected endpoint/model with isolated nonpersonal test images; do not assume Qwen text lane handles multimodal input. Resolve actual UserSettings/defaults explicitly and record capability result.
2. Add structured single/pair observations schema with consistency/quality/confidence/no-comparison results and no body-fat fields. Reject ungrounded/malformed outputs with bounded repair/failure.
3. Async analysis outside DB transaction, idempotent pair/model/template hash; owner/consent before bytes and before commit. Deleted/changed source prevents stale results.
4. Store immutable versions/metadata; FitnessState summarizes validated observations only. Legacy critique excluded from numeric/body-composition state.
5. Cloud fallback requires explicit user-approved image provider policy; default no cloud fallback. Analysis failure cannot block upload/logging.

**Tests:** both model request formats where configured; unsupported vision endpoint; paired owner mismatch; lighting/pose inconsistency → inconclusive; invalid/body-fat output rejected; source deleted during run; no bytes/raw hidden reasoning persisted.

**Completion criteria:**

- [ ] Verified vision capability with structured uncertainty output.
- [ ] No precise composition or diagnostic claims.
- [ ] Consent/isolation and audit enforced.

**Do not proceed until:** isolated actual vision roundtrip and privacy fixtures pass.

### Step 28 — Build curated science ingestion, retrieval and refresh

**Goal:** usable accepted evidence before science-based automated programming.

**Files to inspect first:** `backend/app/services/docs_ingest.py`, `embedding_service.py`, `embeddings.py`, `search_service.py`, `backend/app/models/doc.py`, `document_chunk.py`, `backend/app/routes/documents.py`, `backend/app/tools/documents.py`, `backend/app/services/research/tools.py`, `backend/app/services/research/llm_client.py`, `backend/app/routes/automation_admin.py`.

**Files to create:** `PROPOSED: backend/app/models/fitness_science.py`, `PROPOSED: backend/app/services/fitness/science.py`, `PROPOSED: backend/app/routes/fitness_science.py`, `PROPOSED: backend/app/tasks/fitness_science.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_science.py`, `PROPOSED: frontend/src/components/fitness/ScienceLibrary.tsx`, `PROPOSED: backend/tests/test_fitness_science_pg.py`, `PROPOSED: backend/tests/test_fitness_science_refresh.py`.

**Files to modify:** main router registration/celery task includes/routes; proposed tool/review/state schemas and Coach evidence UI; existing storage/embedding facades reused, not generic personal-document retrieval changed wholesale.

**Implementation instructions:**

1. Add ScienceRecord/annotations/curation event schema with source revision/hash and native DocChunk links. Verify embedding dim=1024/config match; fail/retry dimensions or unavailable embeddings, never fabricate/pad.
2. Implement upload/URL registration → extraction → section chunks/native vector → unreviewed metadata. Do not send research documents into personal memory/PKG automatic extraction.
3. Owned curator explicitly accepts revision; curation logs reason/time, rejected/superseded/retracted versions preserved. Global public sharing needs admin publishing scope; start owner-only.
4. Accepted-only retrieval uses native vector cast parameters plus lexical/topic/applicability/quality ranking/reranking; expose DOI/URL/population/limitations/chunk source location. Same subject query cannot retrieve another athlete's private annotations/docs.
5. Add science search tool and inject bounded retrieved evidence into reviews; validation permits only supplied exact IDs. Persist ranking policy/revision references.
6. Low-priority monthly/configured refresh searches approved sources/topics, deduplicates, queues new records and one digest; never auto-promotes or auto-applies target changes. Separate last-success from last-attempt; flag retractions for impacted reviews.
7. Populate and manually review a small corpus before claiming evidence coverage for hypertrophy/strength/nutrition/sleep. Agents must verify primary source details at ingestion time; this plan is not a supplied scientific corpus.

**Tests:** vector dim/index migration; retry extraction/embedding; DOI/checksum dedup; unreviewed excluded even high similarity; owner isolation; ranking with population mismatch; cited ID validation; curation/supersession/retraction preserve old audit; refresh never accepts/applies changes; SSRF/resource bounds; frontend accepted/new distinction.

**Completion criteria:**

- [ ] Small accepted library supports real attributable retrieval.
- [ ] Refresh cannot silently alter coaching evidence/targets.
- [ ] Review citation trail reconstructs exact retrieved versions.

**Do not proceed until:** accepted-only/citation/privacy tests and an isolated retrieval roundtrip pass.

### Step 29 — Version programs and generate reviewable drafts

**Goal:** advanced experienced-lifter programming on existing phase/template/set-plan infrastructure.

**Files to inspect first:** `backend/app/services/plan_importer.py`, `plan_adjust.py`, `phase_resolution.py`, `set_plan.py`, `workout_prescription.py`, `progressive_overload.py`, `backend/app/routes/fitness.py` template-exercise synchronization, `frontend/src/components/fitness/TemplateBuilder.tsx`, `PlanImporter.tsx`.

**Files to create:** `PROPOSED: backend/app/services/fitness/programming.py`, `PROPOSED: backend/alembic/versions/<next>_fitness_program_versions.py`, `PROPOSED: backend/tests/test_fitness_programming_pg.py`.

**Files to modify:** existing importer/template/phase adapters, proposed models/recommendations/state/review contracts and program UI where needed.

**Implementation instructions:**

1. Establish immutable template/program revision references and typed prescribed slot/set-plan schema; synchronize legacy JSON + template_exercise through one writer. Distinguish block/mesocycle/program week without unnecessary separate tables.
2. Draft generation uses owned profile/goals/limitations, available equipment/time, deterministic performance data and accepted evidence. LLM outputs constrained draft only, never writes activated templates.
3. Validate exercise identities, duration plausibility, volume/intensity/RIR/RPE, equipment/limitations and load units. Missing constraints trigger questions; no beginner default if experienced history/profile exists.
4. Deterministic progression applies configured double/linear/percentage rules to comparable performance; recovery/pain can propose holding/reducing/deloading. Existing set_plan holds/overrides and in-session policies remain compatible.
5. Preview exact program/phase/date/targets/template changes; accepting draft atomically versions/activates through existing phase control. New weekly program recommendation actions become supported only now.
6. Past completed session snapshots/review inputs remain unchanged when templates/program are edited. Backdated revisions require explicit effect scope and audit.

**Tests:** typed week/set parser; JSON/normalized parity; missing/invalid equipment; injury limitation respected without diagnosis; experienced lifter plan; multiple goals; progressive-overload fixtures; import/retry compatibility; explicit activation; past snapshots unchanged; proposal stale revision conflict.

**Completion criteria:**

- [ ] Coach produces inspectable valid drafts and deterministic progression.
- [ ] All material activation is explicit and auditable.
- [ ] Existing imported/two-a-day plans and clients remain functional.

**Do not proceed until:** draft/schema/activation/past-history tests pass; no unreviewed model plan is activated.

### Step 30 — Add longitudinal/approved automation capabilities incrementally

**Goal:** multi-month/year coaching after trustworthy foundations.

**Files to inspect first:** completed proposed fitness services, `backend/app/services/workout_command_service.py` approved policy, existing consent/privacy and action receipt boundaries.

**Files to create:** `PROPOSED: backend/tests/test_fitness_approved_automation_pg.py`; integration adapters only through a separately defined narrow contract.

**Files to modify:** proposed recommendations/jobs/programming/state and athlete coaching preferences.

**Implementation instructions:**

1. Add long-term period summaries using the same analytics versions, history and indexed bounded queries. Compare goals/phases/protocols explicitly; do not fit unexplained multi-year correlations.
2. Add only explicitly approved automation policies with action types, numeric bounds, rate limit, minimum coverage, evidence requirements, expiry and rollback/stop. Default disabled; existing workout rest approvals do not authorize calorie/program changes.
3. Re-evaluate policy/current revision/pain/missing data before each action, persist receipt and notify outcome through delivery policy. Major outside-bound changes remain proposals.
4. Add new vendor integrations behind canonical source adapter/idempotency/consent contract, beginning with actual user demand. Existing HealthKit remains supported throughout.
5. Monitor usage/latency/invalid output/deliveries; use rolling phase acceptance evidence rather than expanding automatically because model can generate prose.

**Tests:** expired/revoked/outside-bound policy denies action; sparse-data stop; repeated adjustment cap; stale/current revision; idempotency; source integration conflicts; privacy export/deletion with multi-year history.

**Completion criteria:**

- [ ] Automation uses concrete user-approved bounds and receipts.
- [ ] Any policy can be disabled and future actions stop.
- [ ] Longitudinal insights remain qualified by data quality/history.

**Do not proceed until:** each added automated action passes separate approval/reliability acceptance tests.

### Step 31 — Final phase verification and release handoff

**Goal:** production-ready source/schema pair, without incidental deployment.

**Files to inspect first:** `RECOVERY.md`, `scripts/sara-prod`, `backend/scripts/rehearse_reliable_release.sh`, `backend/tests/assistant_acceptance/readiness_probe.py`, relevant new migrations/tests and `ios-app/scripts/check-workout-contract-parity.mjs`.

**Files to create:** `PROPOSED: docs/plans/FITNESS_COACH_RELEASE_VERIFICATION.md`.

**Files to modify:** this plan/status references only if implementation findings require corrections; deployment pins only through separately authorized release process.

**Implementation instructions:**

1. Rehearse additive migration from inspected baseline and existing populated-data fixtures in disposable DB. Verify row/history/source counts, model fields, indexes and rollback-free restart compatibility.
2. Run targeted backend units/integrations, UI tests/build/typecheck and workout parity; expand checks only for changes affecting shared auth/context/notification/tool infrastructure.
3. Verify readiness capabilities plus explicit fitness contract acceptance: two users, partial data, logged workout, review, explicit target acceptance and photo ownership where phase shipped. Disable push/network to real accounts in acceptance.
4. Record actual source commit/schema revision/config flags/capabilities and model availability; no secret values in report. New phases off by default until gated.
5. Use pinned-generation release rehearsal described in RECOVERY, never downgrade schema as a recovery technique. Old-generation compatibility with additive schema should be proven before cutover. User-visible rollout should be staged and monitor failures.

**Tests:** Section 20 checklist and shipped phase definition of done; actual isolated local-model/vision roundtrips where enabled; migration rehearsal and API readiness.

**Completion criteria:**

- [ ] Reviewable source/schema/config pair and acceptance evidence documented.
- [ ] No critical user-isolation/history/contract regressions.
- [ ] Deferred phases stay disabled/unimplemented as appropriate.

**Do not proceed until:** release validation passes and any deployment follows the repository's explicit release authorization/process.

## 16. Database Migration Sequence

Use additive changes, explicitly configured isolated DATABASE_URL, hand-reviewed SQL and current head. Do not rewrite old migrations or rerun historical bootstrap scripts. Suggested logical sequence (each may split into small revisions, each actual revision ID <=32 characters):

| Order | Logical migration | Dependencies and verification |
|---|---|---|
| M0 | Ownership prerequisites | Audit orphan owners/global custom exercises/session links first. Add constraints only after reviewed reconciliation; no guessed reassignment. |
| M1 | Athlete foundation | User FK; profile, dated prioritized goals, limitations. Check date/priority overlap and user indexes. |
| M2 | Target revisions | M1 and existing program/phase/default tables; immutable approved snapshots, effective ranges, concurrency indices. Known-start backfill only. |
| M3 | Canonical observations | Add units/provenance/corrections to health_metric; preserve integration conflict keys initially. Validate units/alias mappings. |
| M4 | Check-in extension | Existing daily_recovery_log; new subjective/completeness/source/version fields, defaults unknown/null. |
| M5 | Measurement definitions/periods | M3; descriptor/global-owner scope and period linkage. Physical observations remain health_metric. |
| M6 | Exercise alias/catalog scope | Existing exercise_library/canonical shadow FK; reviewed exact aliases and private/global classification. |
| M7 | Exercise performance/set fields | M6 + existing active/planned sessions; additive precision/effort/role fields and occurrence links. Keep old set_kind contracts. |
| M8 | Pain/PR extensions | M7; owned reports, canonical PR identity/formula/source/withdrawal. No mass new PR awards during migration. |
| M9 | Review audit/recommendations | M1/M2 and stable state schema; idempotency/revision links/status. Models add no implicit actions. |
| M10 | Cadence/occurrence ledger | M9 for review refs; athlete preferences and due ledger, seed disabled/opted-in global sweep only. |
| M11 | Existing photo metadata | Measurement periods/observations; pose/consent/source links. Old storage keys/critique retained. |
| M12 | Photo analysis | M11; owned pair references, structured versioned outputs and status. |
| M13 | Science metadata/native-vector annotations | Existing Document/DocChunk plus curation tables; vector dimension/index choices verified on real pgvector. |
| M14 | Program/template versions | Existing phase/template/set-plan; immutable revisions, prescription snapshots/references, JSON/row parity. |

For each revision: rehearse upgrade on fixture-backed baseline and populated throwaway fixtures; inspect generated schema/indexes/constraints; rerun migration chain to verify no unexpected writes; exercise old clients on additive schema. Transactional backfills operate in bounded batches with counts, explicit units/source mapping and resumable IDs. Null unknown values are a valid outcome, not a migration failure to hide.

Do not update schema fixture by dumping live production during tests. Generate an intentional schema-only snapshot from the upgraded disposable baseline if repository conventions call for it, with head/version metadata checked. The repository's pre-Alembic bootstrap gap is real: distinguish fixture-based upgrade verification from fresh empty database installation. A separate baseline-bootstrap repair may be desirable but is not a reason to rebuild all schemas in this feature.

Rollback strategy: code feature flags/old-generation compatibility, explicit reversal/correction of actual approved records if needed, and documented source/schema pair. Never `alembic downgrade` production as a runtime rollback; additive migrations should preserve the prior compatible generation.

## 17. API Implementation Sequence

1. Authenticate existing `/api/fitness/*` and v2 routes; assert 401/404/user separation before adding endpoints.
2. `/api/fitness/coach/profile` GET/PATCH and owned limitation operations; validate row version.
3. `/api/fitness/coach/goals` create/list/as-of/close; `/targets` dated read/write; adapt old goals/phase/today-target paths to shared resolver.
4. Canonical existing health/weight/recovery ingest, then `/check-ins/{date}` GET/PATCH and completeness changes.
5. `/measurement-types`, `/measurement-periods`, `/measurements` owned create/read/correct, custom definitions.
6. Existing `/exercises` owned/global catalog/aliases; existing v2 commands extended compatibly, pain capture through shared command/service flow.
7. `/state` and `/analytics`, bounded history/raw-detail endpoints; no implicit LLM call.
8. `/reviews` POST/list and `/reviews/{id}` GET: queued status contract; `/recommendations/{id}/decision` only supported typed actions.
9. `/schedules` athlete-local preferences/snooze; global task settings restricted, not mixed with athlete endpoints.
10. Existing `/api/fitness/progress-photos` extend upload/metadata/read/delete; optional asynchronous analysis with explicit consent and owned pair.
11. Proposed science router under `/api/fitness/coach/science`: register/ingest/list/search/accept/reject/refresh; ownership and admin publication distinction.
12. Later program draft/version/activation APIs via existing approved program services; introduce automation-policy endpoints last.

All collection routes: validated max page/span, stable ordering, owner filters on joins, no arbitrary source/code injection. Dates are local-date strings and timestamps offset-bearing; response units/provenance explicit. Retried writes preserve idempotency key/payload fingerprint; reuse key for a different payload returns conflict, never an old unrelated success. Idempotency scoped to user/action. API acceptance checks actual committed outcome rather than only a response 200.

## 18. Frontend Implementation Sequence

1. Keep `/fitness` in existing view/path mapping; add typed fitness API/query hooks with current credential/error conventions.
2. AthleteSettings: profile, goals and dated target display; existing program/food editors continue working.
3. Today/DailyCheckIn plus explicit nutrition completeness and quick existing FoodLog navigation.
4. Progress/Measurements: custom descriptors, sides and periods; charts only after metrics ready.
5. Upgrade active workout interface to v2 commands, inline quick fields, previous performance, retry/conflict UI; defer new offline engine.
6. CoachOverview and 7/14/28-day charts from backend state; coverage/unknown/freshness present.
7. CoachReviews: explicit request, status polling, explanation/metrics/limitations and concrete supported proposal decisions.
8. Cadence/consent/snooze settings and stable deep links within existing view-state navigation. A `/fitness?...` subview query can be handled by fitness surface without introducing new app router.
9. ProgressPhotos from existing API; structured comparison/uncertainty after verified vision.
10. ScienceLibrary accepted/unreviewed sections within Coach; cited sources accessible from reviews.
11. Typed program draft preview/version/activation; later approved automation control.

Use relevant Vitest/Testing Library fixtures, `npm run build`, `npx tsc --noEmit`, and lint within frontend. Run existing affected tests; frontend build success alone doesn't validate type contracts or server authorization. If preexisting type/lint failures occur, document exact baseline and fix feature-caused regressions; do not disable checks broadly.

## 19. LLM Integration Sequence

1. Foundation/daily/workout/analytics phases have zero LLM dependencies for persistence or numerical outputs.
2. Build and validate FitnessState before prompt changes. Reconcile existing consumer math first.
3. Add read-only Weekly Review audit + typed schema; local Qwen JSON call with explicit resolved model and bounded validation/repair.
4. Add concrete recommendation acceptance through deterministic services, not model tools changing targets as part of review.
5. Wire main Sara context/read tools and update memory/skill boundary; preserve the shared persona and budget behavior on text/voice/provider paths.
6. Introduce proactive review/candidate jobs only after on-demand reviews and missing-data behavior are reliable.
7. Verify and add separate vision input/output; text Qwen consumes structured observations.
8. Curate accepted science records, verify retrieval/citation validation, then introduce evidence-supported recommendations; earlier reviews never pretend to cite a missing corpus.
9. Constrained draft program generation/progression; bounded approved automation last.

Measure LLM latency/tokens/schema failure rate, evidence use and proposal rejection/staleness. Schema-constrained JSON provider mode can be enabled if actual endpoint supports it, but local Pydantic/reference/safety validation remains mandatory. Model-selection preferences for interactive chat cannot silently move sensitive background/photo processing to a cloud provider.

## 20. Testing / Verification Checklist

### Units: pure math, normalization and output contracts

- [ ] Goal selection/priority and half-open dated intervals; phase inclusive-date adaptation.
- [ ] Historical target resolver, training/rest variants, fallback/unknown provenance and midperiod changes.
- [ ] Missing vs zero vs rejected data; finite checks, unit conversions, fractional load precision.
- [ ] 7/previous-7/14/28 means and time-offset slopes with hand-verified fixtures and eligibility counts.
- [ ] No missing-day zero fill; source conflict, duplicate and backdated corrections.
- [ ] Complete/partial/unknown nutrition; per-field denominators, historical target tolerance/protein checks.
- [ ] Sleep total selection, nap/stage distinction, overnight/DST/circular-time consistency and effective target.
- [ ] Subjective scale directions and unknown/partial computed readiness, existing HRV outlier guards.
- [ ] Canonical alias resolution vs ambiguity, scoped namespace and variation/load convention.
- [ ] Working/warmup/drop/role/void/correction set rules and training session de-duplication.
- [ ] Direct/secondary muscles and tonnage limitations; e1RM formula/eligibility and rounded display only.
- [ ] PR kinds/ties/withdrawal/recompute; insufficient strength/plateau evidence.
- [ ] Pain distinct-session counts, missing-report coverage, non-diagnostic output.
- [ ] Data-quality overdue cadence/target freshness/completeness, disabled tracking not overdue.
- [ ] FitnessState deterministic rendering, size bounds, no implicit model arithmetic.
- [ ] LLM empty/malformed/fenced/invalid JSON, one repair, enums/ranges/reference IDs/safety validators.
- [ ] Science applicability/status/ranking policy; image observations consistency/forbidden composition fields.

### PostgreSQL/API integrations: real persistence, indexes and concurrency

- [ ] Anonymous/cookie/Bearer/device/revoked authentication and multi-user owner scope, including legacy/v2.
- [ ] Cross-user nested parent/template/phase/session/set/recipe/type/period/proposal/photo references denied.
- [ ] Profile PATCH row versions; goal/target overlap and concurrent updates; historical edits preserved.
- [ ] Canonical ingest retries/manual correction/provider collision and existing HealthKit projection parity.
- [ ] Check-in partial/clear fields and completeness changes; unique local date and source stamps.
- [ ] Custom measurement descriptor ownership/quantity/unit/site/side; no migration for new type.
- [ ] Exercise canonical reviewed backfill and private catalog visibility.
- [ ] Workout start/log/retry/concurrency/correction/void/finish, linked sessions/two-a-day and old API compatibility.
- [ ] PR retract/recompute after source correction and alternative eligible records.
- [ ] State data revision/cache invalidation scoped by user; Redis down, missed event and stale cache label.
- [ ] Review input reproducibility/immutable audit/idempotency/rerun after correction, scoped listing and failure states.
- [ ] Review generation does not mutate goals/targets/programs; accepted recommendation changes exactly once and stores receipt.
- [ ] Recommendation expired/stale/foreign/unsupported/DB failure cannot execute.
- [ ] Tool registry and all mutation/operation/reference/target/receipt layers correctly govern new actions.
- [ ] Domain world events append transactionally, event failure does not fabricate successful record state.
- [ ] Photo upload/read/thumb/delete/pair ownership, EXIF/byte/pixel validation, MinIO compensation/cleanup retry.
- [ ] Science record/document/chunk ownership, actual pgvector dimensions/native retrieval, accepted-only filter and provenance.
- [ ] Migration upgrade from exact baseline, populated history preservation and old-generation compatibility; fixture parity is honest.

### Jobs, delivery and model transport

- [ ] Explicit user IDs in every new task; default-owner fallback absent.
- [ ] Sweep claims/dispatch failures/worker loss/retries/concurrent workers produce one occurrence artifact.
- [ ] DST local cadence, 14/28-day anchor, settings reload, disabled/snoozed stale jobs and run-completion status.
- [ ] Proactive candidate TTL/topic dedup/cross-producer dedup, opted-in missing-data request priority.
- [ ] Notification preferences/quiet/directives/interruptibility/attention/daily caps; suppressed push differs from failed review.
- [ ] Weekly health/Coach/morning brief do not emit redundant notices or requests.
- [ ] Research refresh creates only unreviewed records and no target changes; actual source fetch freshness recorded.
- [ ] Isolated background local LLM roundtrip confirms payload/resolved model/JSON contract and usage metadata.
- [ ] Configured vision smoke test confirms actual image capability; no silent cloud fallback.
- [ ] Tests neutralize real push/task dispatch and do not connect to production by fixture defaults.

### Frontend and cross-client acceptance

- [ ] Profile/goals/target history, optional fields and unit/rate validation; per-user Query isolation/logout.
- [ ] Daily partial save/date/source handling/completeness and non-destructive network errors.
- [ ] Sparse chart gaps/counts; no one-sample plateau/perfect missing recovery display.
- [ ] Fast logging start/set/duplicate/keyboard/rest/finish, exact retry IDs, conflict reconciliation and input retention.
- [ ] Coach request/status/failure/insufficient data, old/new proposal confirmation and stale acceptance refresh.
- [ ] Photos/measurements/curation forms and private source links; no raw errors or object keys exposed.
- [ ] Build + explicit TypeScript check + relevant lint/tests.
- [ ] `node ios-app/scripts/check-workout-contract-parity.mjs` and existing legacy compatibility tests.
- [ ] iOS/Watch payload roundtrip after additive wire changes; web separately consumes matching field types.

Use these baseline commands from the repository root after inspecting the test compose/image availability (they are instructions for future implementation, not checks run during this planning session):

```bash
backend/scripts/disposable_compose.sh sara-fitness-test -f docker-compose.test.yml up -d --wait test-db test-redis
TEST_DB_CONTAINER=sara-fitness-test-test-db-1 backend/scripts/provision_test_schema.sh
backend/scripts/disposable_compose.sh sara-fitness-test -f docker-compose.test.yml run --rm backend-test pytest tests/test_workout_command_service.py tests/test_workout_flexible_sets.py tests/test_plan_adjust.py
node ios-app/scripts/check-workout-contract-parity.mjs
```

The runner has an existing backend image dependency and starts its isolated embedding dependency; provision/rebuild a test image through the repository's isolated workflow if unavailable, never rebuild production. For new tests, add exact filenames from each task to the runner command; verify the runner source bind mount and explicit schema baseline. MinIO/model transport tests use the proposed test-only overlay. The internal test network deliberately cannot reach production or external inference endpoints; actual-model smoke verification needs an explicitly isolated gateway/rehearsal setup, not a changed default route or unguarded ambient configuration.

Run backend tests through the disposable environment only, following `backend/scripts/disposable_compose.sh`, `backend/tests/env_guard.py` and `backend/scripts/provision_test_schema.sh`. For selected tests inside a properly isolated runner, use `cd backend && python -m pytest tests/<specific test file>`; the installed runner may use `python3`. Set test target configuration explicitly; never copy an older test docstring's production/dev-container invocation. Include actual PostgreSQL tests for JSONB, partial indexes, uniqueness, locks and vector operations; SQLite cannot prove them. Use mocks/fakeredis for pure units, fake local model server for malformed outputs, actual isolated model smoke tests for transport.

## 21. Definition of Done by Phase

| Phase | Required working behavior before calling complete |
|---|---|
| 0 Ownership | Real actor for all legacy/v2 routes; two-user and revoked-token tests; ownership audit; isolated schema/contract baseline. No source/client regression. |
| 1 Foundation | Typed optional athlete profile + limitations; historical prioritized goals; dated phase/default target revisions; old/new target readers agree; Settings UI works with model offline. |
| 2 Daily | Canonical numeric observation/source/units, partial check-ins, explicit nutrition completion and custom tape measurements/periods; HealthKit compatibility, backdated corrections and Today UI. |
| 3 Workouts | Aliases/variant scope; session-exercise-set projection; precise load/effort/pain; shared reliable commands/PR retraction; fast web logging and phone/Watch parity. |
| 4 Analytics | Independently tested metrics/coverage/quality; versioned state/API/cache; overview/charts and current readers use same truths. Empty data yields unknown, not invented claims. |
| 5 Weekly Coach | Explicit queued request + local validated output + audit + results UI; safe/stale-aware explicit decisions/receipts for supported changes; bounded chat/tools and memory separation. Generation itself read-only. |
| 6 Proactive | Per-user opt-in cadences/snooze; durable occurrence/retry/complete states; existing candidate/notification policies; duplicate and privacy safeguards proven. |
| 7 Photos/Vision | Existing storage hardened/standardized metadata/web display; only verified opt-in model produces structured observations with quality uncertainty and no body-fat estimates. |
| 8 Science | Small curated accepted corpus/native-vector retrieval with applicability/limitations/citations/revision audit; new records separate; refresh never auto-promotes/applies. |
| 9 Programs | Typed versioned set plans/templates, shared legacy normalization, inspectable science-informed draft and explicit activation; deterministic progression and unchanged past snapshots. |
| 10 Advanced | Each automation/integration separately scoped/consented/tested; long-history metrics qualify goal/protocol/data changes; actions bounded/idempotent/auditable and immediately revocable. |

This planning session changed only this Markdown document. Its existing repository path references were checked against disk; proposed paths were checked to be new, all 24 sections and 31 task templates were verified. Application tests, production probes, model calls and migrations were not run because no application behavior changed.

Phase completion includes matching tests, migration rehearsal, failure handling and privacy/ownership, not merely pages rendering or tool schemas registering. Steps 1–4 gate all new records, Steps 15–18 gate coach interpretation, and accepted science gates claims of evidence-backed new programming. Existing workouts need not wait for later phases to remain usable.

## 22. Deferred Features

Do not build these in early foundation/tracking phases:

- New databases, brokers, microservices, autonomous coach brain or universal replacement memory system.
- New wearable/vendor OAuth integrations; existing Apple Health input remains supported.
- Automatic calorie/major macro/volume/exercise/program changes without concrete proposal review.
- Massive exercise/food catalog import; unreviewed fuzzy alias merging across user histories.
- Universal tonnage hypertrophy score, opaque session performance score or diagnosis/overtraining classifier.
- Precise photo-derived body-fat percentages or photo-based medical diagnosis.
- Meal-photo calorie estimation or invented macro values from incomplete descriptions.
- Continuous pose tracking/form-video analysis, automatic camera capture or biometric segmentation.
- Infinite science crawler, auto-curation from new publications, automatic response to every single study.
- Broad predictive multi-year optimization and cross-user model training on private athlete records.
- A new offline synchronization framework before reliable online command retries work.
- Full mobile/Watch UI redesign; preserve contracts and add required compatibility only.
- Full two-Base/migration-history consolidation or replacing both document chunk infrastructures unrelated to fitness.
- Athlete-data graph duplication, global PKG numeric fact migration, or copying all set/food histories into vectors.
- Clinical treatment advice, drug protocols, emergency triage engine or unsolicited contacts.

## 23. Risks / Open Questions

These are uncertainties/gaps observed in source, not generic speculative risks.

| Issue discovered | Recommended default | Blocks? |
|---|---|---|
| Fitness/v2 user dependency is SOLO_USER_ID stub; some legacy rows may have artificial owner | Repair auth first; audited explicit historical mapping only; quarantine unresolved records. | **Yes for shipping new owned data.** Existing historical orphan cleanup need not block new data once isolated. |
| Actual deployed source/schema pair is pinned elsewhere and may differ | Build against inspected working tree + disposable schema; confirm release source/schema through established rehearsal before deployment. Do not claim live parity. | No for planning/development; yes for release validation. |
| Two Bases and incomplete Alembic empty-DB bootstrap | Explicit additive migrations against documented baseline; separate baseline cleanup if desired. | Must resolve test baseline, not rewrite architecture first. |
| Existing food naive ET, other times naive UTC/aware; browser-local date differs | Athlete timezone ET default, aware new timestamps, explicit legacy adapters; future timezone fields per athlete. | Yes for trustworthy periods until policy encoded. |
| Multiple weight/sleep stores and sparse HRV mirror behavior; units not explicit everywhere | Canonical health_metric, typed provenance/source selection; projections maintained by shared ingest; unknown-unit legacy rows flagged. | Yes for numeric confidence; manual/new known-unit records can proceed. |
| Readiness formula yields 100 on empty input | Coverage/unknown wrapper, reuse existing formula when inputs eligible. Avoid rewriting formula without evidence. | Yes for truthful overview/coaching, small contained fix. |
| exercise_library currently global/keyword-seeded and exercise_id remains legacy text | Scoped reviewed aliases + canonical shadow FK; private classification before exposing custom names. | Yes for identity/privacy; unresolved old rows can remain flagged. |
| Workout data has planned/active/legacy aggregates and integer load/RPE | Additive precision/occurrence adapters, one de-duplicated read projection, contract-version changes only with parity checks. | Yes for accurate new fractional logs/analytics; no wholesale table replacement. |
| Template JSON/TEXT and template_exercise both exist | Single normalizer/writer preserving current readers; immutable revisions later. Verify all import/update paths. | Yes for typed program generation; initial manual logging can use existing snapshots. |
| Mutable phase macros/default goals lose historical targets; plan_adjust changes date ranges | Append revisions of existing sources, propagate history through split/copy; mark unprovable past targets unknown. | Yes for historical adherence, not for current profile UI. |
| Existing weekly task defaults to owner/first-user, three loosely validated JSON stages and direct push | New coach explicit user + single validated audit pipeline; reuse shared collector math and dedup delivery; preserve old reports. | Yes before multi-user proactive integration. |
| Global schedule API is authenticated but not owned; arbitrary kwargs and no owner field | Athlete preference table and system sweep; admin restriction for global schedules, no per-user arbitrary task edits. | Yes for safe cadence exposure. |
| Some notification wrappers bypass attention/owner default; fitness cooldown shares health | Use explicit user and existing candidate flow; inspect policy interaction, preserve category settings; do not force bypass. | Yes before proactive enablement; no for on-demand read-only reviews. |
| Actual Qwen/provider structured JSON enforcement not proven | Pydantic/reference validation mandatory; bounded repair; verify actual local transport in isolated smoke test. | Yes for live review acceptance; schema/unit development unblocked. |
| Vision defaults disagree between llm_config and UserSettings/routes; actual endpoint multimodal capability unknown | Use shared user vision resolver and explicit capability probe; separate configured vision model; no text-model assumption or silent cloud fallback. | Only blocks later vision, not upload/tracking/text coach. |
| Existing photo critique asks for body-fat range; upload decode fallback can mislabel bytes; delete can orphan blobs | Remove composition estimate request, strict validated image upload and retryable cleanup, legacy text untrusted. | Yes before exposing new photo/vision coaching. |
| Two chunk systems: native doc_chunk and live TEXT-cast document_chunk | Science explicitly uses native DocChunk plus metadata; reuse storage/extraction/embedding; no general document migration now. | Need explicit selection/index tests for science; foundation unblocked. |
| PKG is owner-centered and some recall fact queries lack user scope; target intentions currently permitted | Athlete structured profile/owned episodes as default; do not use shared global PKG for other users; exclude authoritative targets from graph. | Yes before multi-user graph-derived personalization, not structured coaching. |
| No curated sports-science corpus/acceptance pipeline identified | Small owned accepted corpus built in Phase 8; earlier recommendations cite no nonexistent evidence and remain provisional/user-reviewed. | Blocks claims of curated evidence-backed advanced coaching, not analytics/initial review. |
| Health/privacy preference flags may not be enforced uniformly | Trace actual enforcement when adding each owned API/model path; offer explicit export/delete and local processing consent. | Must verify before sensitive/photo rollout. |

No need to ask the user about speculative training preferences during implementation planning. The implementation supports configurable data. Genuine product choices to confirm at implementation time, if still unspecified: target display units/timezone defaults, cadence opt-ins, allowed accepted-evidence curators and exact automation bounds. Defaults above unblock deterministic development; user authorization is required only for their eventual enabled proactive/automation behavior.

## 24. Final Recommended Build Order

1. Read current repo/release instructions; reproduce isolated schema/client contract baseline.
2. Repair real authenticated fitness/v2 ownership and nested-resource isolation; audit legacy owners.
3. Add typed data-access/time/unit adapters, athlete profile/goals/limitations and dated target revisions using existing phase/default authority.
4. Ship usable Settings; consolidate canonical metric ingestion and compatibility projections.
5. Extend partial check-ins/completeness; custom measurement definitions/periods and Today/Progress entry.
6. Normalize scoped exercise aliases; stable session exercise occurrences, precise sets/effort/pain; preserve command recalc/PR correction.
7. Move fast web workout logging to existing v2 protocol with exact retries and mobile/Watch parity.
8. Implement and independently test objective weight/nutrition/sleep/training/quality analytics.
9. Assemble FitnessState/API/cache; consolidate existing summaries and ship overview/charts.
10. Add immutable review/recommendation audit, validated local on-demand Weekly Coach and concrete acceptance for supported changes.
11. Integrate bounded main Sara context/read tools and enforce memory/action boundaries.
12. Add opted-in user cadence/occurrence ledger and existing candidate/delivery daily/weekly loops.
13. Extend/harden existing progress photos, then opt-in structured verified vision observations.
14. Build small curated sports-science corpus, native pgvector retrieval and separate unreviewed refresh process.
15. Version/generate inspectable programs and deterministic progression through current phase/template control.
16. Add narrowly approved advanced integrations/automation only after preceding phase acceptance evidence.
17. Rehearse each shipped phase's source/schema/config pair and follow pinned release workflow.

The implementing agent should deliver each phase as a working, tested increment with its definition of done and deferred scope intact. Numerical truth belongs to the application; Sara reasons about that truth, explains uncertainty and asks permission for concrete major changes.

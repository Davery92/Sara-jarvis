# Temerant RPG Habit System Implementation Spec

## 0. Document Metadata

- Owner: Sara platform team
- Requested by: David Avery
- Date: 2026-02-20
- Status: Ready for implementation
- Scope: Backend API and logic, web app page, workbench canvas window, iOS screen

## 1. Product Definition

### 1.1 Problem Statement

David wants a narrative progression layer that turns real habit execution into an in-world RPG loop inspired by Temerant:

- Real life actions become in-world actions.
- Progress is tracked as character development.
- The world reacts through oracle events and term outcomes.
- The system exists inside Sara across web, canvas, and iOS.

### 1.2 Product Goals

1. Convert real activity into a coherent character progression system.
2. Keep rules deterministic and auditable.
3. Use LLMs only for narration, not scoring.
4. Support daily loop, oracle events, and monthly admissions.
5. Ship as a first-class feature on:
   - Main web app (`frontend`)
   - Workbench canvas app (`workbench-canvas`)
   - iOS app (`ios-app`)

### 1.3 Non-Goals (V1)

1. Full lore simulation engine.
2. Heavy Neo4j dependency for core gameplay.
3. Perfect auto-ingestion from every subsystem on day one.
4. Multiplayer or social gameplay.

## 2. Current System Baseline (Repo Reality)

This spec aligns to current architecture:

- Backend runtime is `backend/app/main_simple.py` (production path).
- Habit engine exists in `backend/app/routes/habits.py` and `backend/app/models/habit.py`.
- Fitness APIs already exist under `/api/fitness` in `backend/app/routes/fitness.py`.
- Learning APIs already exist under `/api/learn` in `backend/app/routes/learning.py`.
- Web app runtime is `frontend/src/App-interactive.tsx`.
- Canvas app runtime is `workbench-canvas/src/App.tsx` with window registry and Zustand store.
- iOS app uses React Navigation with stack in `ios-app/src/navigation/AppNavigator.tsx` and tabs in `ios-app/src/navigation/MainNavigator.tsx`.

## 3. Domain Model and Rules

### 3.1 Canonical Attributes

Core visible attributes:

- `body`
- `mind`
- `craft`
- `coin`
- `name`

Hidden or secondary stats:

- `alar_strength`
- `naming_affinity`

### 3.2 Ranks

- `elir` (starting rank)
- `relar`
- `elthe`

Rank-up checks run daily and on-demand:

- `relar`: at least 50 XP in 3+ attributes AND 30-day streak in 2+ categories.
- `elthe`: at least 100 XP in 4+ attributes AND 60-day streak AND one completed masterwork.

### 3.3 Sources and Mapping (Deterministic Rules)

Each translated action writes a ledger event with explicit:

- source type
- source reference ID
- mapping rule version
- XP deltas by attribute
- coin delta
- optional oracle modifier contribution

Initial mapping set:

- Strength and workout actions -> `body`
- Study and deep research -> `mind`
- Guitar and coding/build work -> `craft`
- Budget adherence and workday outcomes -> `coin`
- Social and mentorship actions -> `name`
- Meditation and journaling -> `mind` + `alar_strength`

### 3.4 Anti-Grind Controls

- Per-attribute daily XP soft cap.
- Diminishing returns after configurable threshold.
- Duplicate-event idempotency by `(source_type, source_ref_id, user_id)`.
- Cooldowns for high-value bonuses (for example PR bonus once per day per exercise family).

### 3.5 Oracle Rules

Daily oracle roll parameters:

- Base roll: server-side RNG `1..20`.
- Modifier: `+2` if 4+ distinct mapped categories completed that day.
- Trigger:
  - `<15`: quiet day
  - `>=15`: notable event
  - natural `20`: major event

Category roll (`1..6`):

1. academic
2. social
3. discovery
4. financial
5. challenge
6. mystery

Oracle event generation:

- Deterministic structure payload (category, tier, hook, stakes, next choices).
- Optional narrated text generated from payload.

## 4. Data Model (Postgres First)

All IDs are `String` UUIDs to match existing model style.

### 4.1 New Tables

1. `temerant_character`
2. `temerant_attribute_state`
3. `temerant_xp_ledger`
4. `temerant_daily_state`
5. `temerant_oracle_event`
6. `temerant_story_thread`
7. `temerant_term`
8. `temerant_masterwork`
9. `temerant_mapping_rule`
10. `temerant_journal_entry`
11. `temerant_ingestion_cursor`

### 4.2 Table Definitions

#### `temerant_character`

- `id` PK
- `user_id` FK -> `app_user.id` unique
- `character_name` text
- `backstory` text nullable
- `origin` text nullable
- `current_rank` string default `elir`
- `coin_balance` float default `0`
- `alar_strength` int default `0`
- `naming_affinity` int default `0`
- `specialization_track` nullable (`artificer|arcanist|musician|medica`)
- `created_at`, `updated_at`

#### `temerant_attribute_state`

- `id` PK
- `character_id` FK
- `attribute` string (`body|mind|craft|coin|name`)
- `xp_total` int default `0`
- `xp_term` int default `0`
- `level` int default `1`
- unique `(character_id, attribute)`

#### `temerant_xp_ledger`

- `id` PK
- `user_id` FK
- `character_id` FK
- `source_type` string
- `source_ref_id` string nullable
- `idempotency_key` string unique
- `occurred_at` timestamptz
- `local_date` date
- `attribute` string
- `subdomain` string nullable
- `xp_delta` int
- `coin_delta` float default `0`
- `name_delta` int default `0`
- `meta` JSONB (raw source, mapping rule, notes)
- `created_at`

Indexes:

- `(user_id, local_date)`
- `(character_id, attribute, occurred_at desc)`
- `(source_type, source_ref_id)`

#### `temerant_daily_state`

- `id` PK
- `user_id` FK
- `character_id` FK
- `local_date` date
- `categories_completed` int default `0`
- `body_xp` int default `0`
- `mind_xp` int default `0`
- `craft_xp` int default `0`
- `coin_xp` int default `0`
- `name_xp` int default `0`
- `oracle_roll_raw` int nullable
- `oracle_roll_modified` int nullable
- `oracle_event_id` FK nullable
- `term_month` date
- unique `(user_id, local_date)`

#### `temerant_oracle_event`

- `id` PK
- `user_id` FK
- `character_id` FK
- `thread_id` FK nullable
- `local_date` date
- `tier` string (`quiet|notable|major`)
- `category` string
- `title` text
- `hook` text
- `stakes` text nullable
- `options` JSONB nullable
- `resolution` text nullable
- `status` string (`open|resolved|dismissed`) default `open`
- `meta` JSONB
- `created_at`, `resolved_at`

#### `temerant_story_thread`

- `id` PK
- `user_id` FK
- `character_id` FK
- `title` text
- `status` string (`open|resolved|dormant`)
- `last_event_at`
- `meta` JSONB
- `created_at`, `updated_at`

#### `temerant_term`

- `id` PK
- `user_id` FK
- `character_id` FK
- `term_month` date (first day of month)
- `completion_pct` float
- `admissions_result` string (`excellent|good|poor|terrible`)
- `tuition_talents` int
- `xp_multiplier` float
- `coin_delta` float
- `review_markdown` text nullable
- `locked_at` timestamptz nullable
- unique `(user_id, term_month)`

#### `temerant_masterwork`

- `id` PK
- `user_id` FK
- `character_id` FK
- `title` text
- `description` text
- `status` string (`planned|in_progress|completed`)
- `evidence` JSONB nullable
- `completed_at` nullable
- `created_at`, `updated_at`

#### `temerant_mapping_rule`

- `id` PK
- `user_id` FK
- `source_kind` string (`habit|fitness|learning|project|manual|work`)
- `source_ref` string nullable
- `target_attribute` string
- `target_subdomain` string nullable
- `xp_base` int
- `bonus_rules` JSONB
- `daily_cap` int nullable
- `enabled` bool default `true`
- `created_at`, `updated_at`

#### `temerant_journal_entry`

- `id` PK
- `user_id` FK
- `character_id` FK
- `local_date` date
- `summary_structured` JSONB
- `summary_markdown` text
- `source_event_count` int
- `generated_by` string (`rules|llm`)
- `model` string nullable
- `created_at`, `updated_at`
- unique `(user_id, local_date)`

#### `temerant_ingestion_cursor`

- `id` PK
- `user_id` FK
- `source_type` string
- `cursor_value` string
- `updated_at`
- unique `(user_id, source_type)`

### 4.3 Migration Files

Primary migration script:

- `backend/migrations/add_temerant_system.py`

Model registration updates:

- `backend/app/models/temerant.py` (new)
- `backend/app/models/__init__.py` (import new models)

## 5. Backend Service Architecture

### 5.1 New Modules

Create package:

- `backend/app/services/temerant/__init__.py`
- `backend/app/services/temerant/rules_engine.py`
- `backend/app/services/temerant/character_service.py`
- `backend/app/services/temerant/oracle_service.py`
- `backend/app/services/temerant/term_service.py`
- `backend/app/services/temerant/journal_service.py`
- `backend/app/services/temerant/ingestion_service.py`

### 5.2 Responsibilities

`rules_engine.py`

- source event -> XP/coin deltas
- anti-grind caps
- idempotency validation
- writes `temerant_xp_ledger`
- updates `temerant_attribute_state` and `temerant_daily_state`

`oracle_service.py`

- computes oracle eligibility
- rolls and persists events
- thread linking
- event resolution and consequence writeback

`term_service.py`

- monthly admissions scoring
- tuition and multiplier assignment
- term close and term start transitions

`journal_service.py`

- compile daily structured summary from ledger and oracle data
- optional LLM narration with deterministic guardrails

`ingestion_service.py`

- consumes existing Sara domain events from existing DB tables and API actions
- writes translated ledger entries using rules engine
- uses `temerant_ingestion_cursor` for incremental sync

### 5.3 Ingestion Strategy

V1 ingestion sources:

1. Habit logs (`habit_logs`)
2. Fitness logs (`fitness_daily_log`, food/workout/recovery endpoints)
3. Learning sessions (`learning_session`)

V2 ingestion sources:

1. Project activity (`project_tracker` tables)
2. Inbox and communication signals for `name`
3. Workday completion check-ins (manual or integration endpoint)

Real-time hook points:

- `backend/app/routes/habits.py`: after successful log, call ingestion for that event.
- `backend/app/routes/fitness.py`: after create/update actions, call ingestion.
- `backend/app/routes/learning.py`: when session ends, call ingestion.

Batch fallback:

- periodic reconciliation task in `ingestion_service.py`.

## 6. API Contract

Create router:

- `backend/app/routes/temerant.py`

Register in runtime:

- `backend/app/main_simple.py` with prefix `/api/temerant`

### 6.1 Endpoints

1. `POST /api/temerant/character`
   - create character for current user
2. `GET /api/temerant/character`
   - get current character and rank state
3. `PATCH /api/temerant/character`
   - update character metadata and specialization
4. `GET /api/temerant/dashboard?date=YYYY-MM-DD`
   - full daily snapshot for UI
5. `GET /api/temerant/ledger?from=...&to=...&limit=...`
   - paginated translated events
6. `POST /api/temerant/logs/manual`
   - manual activity log and translation
7. `POST /api/temerant/oracle/roll`
   - roll or regenerate daily oracle event if eligible
8. `GET /api/temerant/oracle/events?status=open`
   - oracle event list
9. `POST /api/temerant/oracle/events/{event_id}/resolve`
   - resolve or dismiss event
10. `GET /api/temerant/terms/current`
    - current term status
11. `GET /api/temerant/terms/history`
    - previous terms
12. `POST /api/temerant/terms/close`
    - close active term (admin/internal/manual trigger)
13. `GET /api/temerant/journal?from=...&to=...`
    - journal entries
14. `POST /api/temerant/journal/{date}/generate`
    - generate or regenerate a journal entry
15. `GET /api/temerant/mappings`
    - list mapping rules
16. `PUT /api/temerant/mappings/{rule_id}`
    - update mapping rule

### 6.2 Schema Module

Add:

- `backend/app/schemas/temerant.py`

Key schemas:

- `TemerantCharacterCreate`
- `TemerantCharacterResponse`
- `TemerantDashboardResponse`
- `TemerantLedgerEntryResponse`
- `TemerantManualLogRequest`
- `TemerantOracleEventResponse`
- `TemerantTermResponse`
- `TemerantJournalEntryResponse`
- `TemerantMappingRuleResponse`

### 6.3 Example Dashboard Payload

```json
{
  "date": "2026-02-20",
  "character": {
    "name": "Aelar Vint",
    "rank": "elir",
    "specialization_track": null,
    "coin_balance": 8.4
  },
  "attributes": {
    "body": { "xp_total": 42, "xp_today": 3 },
    "mind": { "xp_total": 47, "xp_today": 2 },
    "craft": { "xp_total": 39, "xp_today": 4 },
    "coin": { "xp_total": 18, "xp_today": 1 },
    "name": { "xp_total": 21, "xp_today": 0 }
  },
  "daily": {
    "categories_completed": 4,
    "oracle_roll_modified": 17
  },
  "oracle_event": {
    "id": "evt_123",
    "tier": "notable",
    "category": "discovery",
    "title": "A Marginalia in Lorren's Stacks",
    "status": "open"
  },
  "rank_progress": {
    "next_rank": "relar",
    "requirements": {
      "attributes_over_50": 1,
      "required_attributes_over_50": 3,
      "streak_categories_over_30": 1,
      "required_streak_categories_over_30": 2
    }
  }
}
```

## 7. Web App Implementation (`frontend`)

### 7.1 Navigation and View Integration

Update:

- `frontend/src/navigation/views.ts`
  - add `temerant` to `AppView`
  - add route `/temerant`
  - add command-palette metadata
- `frontend/src/App-interactive.tsx`
  - import and render `TemerantPage`
  - add nav entries in:
    - `mobileOverlayNavItems`
    - `desktopMoreNavItems`
    - optional `mobileBottomNavItems` (if desired)

### 7.2 New UI Module

Add:

- `frontend/src/components/temerant/TemerantPage.tsx`
- `frontend/src/components/temerant/CharacterCard.tsx`
- `frontend/src/components/temerant/AttributePanel.tsx`
- `frontend/src/components/temerant/OraclePanel.tsx`
- `frontend/src/components/temerant/DailyLogTimeline.tsx`
- `frontend/src/components/temerant/TermPanel.tsx`
- `frontend/src/components/temerant/JournalPanel.tsx`
- `frontend/src/components/temerant/ManualActionModal.tsx`

### 7.3 Data Access

Add:

- `frontend/src/services/temerant.ts`

Use existing auth pattern:

- `credentials: include` via `apiRequest` or `fetch`.

### 7.4 Web UX Requirements

1. Fast initial dashboard load.
2. Manual action logging with optimistic update.
3. Oracle roll button disabled after daily roll unless forced.
4. Journal tab with regenerate action.
5. Term tab with admissions history and tuition trend.

## 8. Canvas App Implementation (`workbench-canvas`)

### 8.1 Window Type Registration

Update:

- `workbench-canvas/src/types/index.ts`
  - add `WindowType = ... | 'temerant'`
  - add `TemerantWindowData` type
- `workbench-canvas/src/store/canvasStore.ts`
  - add default window entry for `temerant`
- `workbench-canvas/src/components/WindowContentRegistry.tsx`
  - map `temerant` -> `TemerantContent`
- `workbench-canvas/src/services/workspaceCommands.ts`
  - add map for backend `window_type: 'temerant'`
- `workbench-canvas/src/components/ModeWheel.tsx`
  - add app launcher tile

### 8.2 New Window Content

Add:

- `workbench-canvas/src/components/windows/TemerantContent.tsx`

Window behavior:

- compact dashboard view
- quick "Log Action" form
- oracle panel
- open journal entry in report window when needed

### 8.3 Canvas Voice/Partner Integration

Backend workspace tools and commands need to recognize this window type:

- `backend/app/tools/workspace.py`
  - add `temerant` to allowed `window_type` enum
  - default title mapping

## 9. iOS App Implementation (`ios-app`)

### 9.1 Navigation

Update:

- `ios-app/src/navigation/AppNavigator.tsx`
  - add `Temerant` stack screen
- `ios-app/src/types/navigation.ts`
  - add `Temerant: undefined` in `AppStackParamList`
- `ios-app/src/screens/more/MoreScreen.tsx`
  - add menu tile for `Temerant`

### 9.2 New Screen + Service

Add:

- `ios-app/src/screens/temerant/TemerantScreen.tsx`
- `ios-app/src/services/temerant.ts`
- `ios-app/src/types/temerant.ts`

### 9.3 iOS UX Requirements

1. Pull-to-refresh dashboard.
2. Segmented tabs:
   - Today
   - Oracle
   - Journal
   - Term
3. Manual action logging sheet.
4. Resolve oracle event action.
5. Lightweight offline cache of last dashboard snapshot using AsyncStorage.

## 10. LLM and Narrative Policy

### 10.1 Deterministic Core

Scoring logic never depends on LLM output.

### 10.2 Narrative Generation

LLM can produce:

- daily narrative summary text
- oracle flavor text
- monthly in-world recap

LLM cannot change:

- xp totals
- coin totals
- rank outcomes
- admissions result

### 10.3 Prompt Inputs

Narrative prompts receive only structured state:

- translated ledger entries
- oracle payload
- active thread summaries
- no hidden scoring controls

## 11. Background Jobs and Scheduling

### 11.1 Jobs

1. `temerant_ingestion_reconcile` (every 5 minutes)
2. `temerant_daily_finalize` (local 23:55)
3. `temerant_monthly_admissions` (first day of month local 00:10)

### 11.2 Integration Point

Register in existing scheduler system used by runtime startup path.
Where production scheduler differs, use the existing worker infrastructure already used by the app and keep jobs idempotent.

## 12. Tooling and Assistant Awareness

### 12.1 Tool Category

Add `temerant` tool category in:

- `backend/app/tools/registry.py`

Add initial tools:

1. `temerant_get_status`
2. `temerant_log_action`
3. `temerant_roll_oracle`
4. `temerant_list_events`
5. `temerant_resolve_event`

### 12.2 Intent Router Updates

Update tool-category routing in `backend/app/main_simple.py` screen-aware map and intent fallbacks:

- map `Temerant` screen -> `['temerant']`

### 12.3 Workspace Command Support

Ensure `workspace_open_window` can open `window_type='temerant'` so voice and chat can launch the canvas window.

## 13. Observability and Metrics

### 13.1 Logs

Structured logs for:

- translation decisions
- skipped duplicate events
- cap applications
- oracle rolls and category picks
- admissions calculations

### 13.2 Operational Metrics

Track:

- daily active users for module
- average mapped actions per user/day
- oracle trigger rate
- journal generation success/failure
- rank progression funnel

## 14. Testing Plan

### 14.1 Backend Unit Tests

Add tests under `backend/tests/`:

- `test_temerant_rules_engine.py`
- `test_temerant_oracle_service.py`
- `test_temerant_term_service.py`
- `test_temerant_ingestion_service.py`

Test cases:

1. deterministic mapping and caps
2. idempotency guarantees
3. oracle threshold and modifier logic
4. rank eligibility checks
5. admissions calculation thresholds

### 14.2 Backend API Tests

Add integration tests in repo root `tests/` style:

- `tests/test_temerant_api.py`

Cover:

1. character create/read/update
2. dashboard endpoint
3. manual log translation
4. oracle roll and resolve
5. term history endpoint

### 14.3 Frontend Tests

- Web: add component tests for key panels and service mocking.
- Canvas: add tests for window registration and command normalization.
- iOS: add service-level tests and basic screen render tests where test setup already exists.

### 14.4 Manual QA Script

Create checklist for:

1. Log workout -> body XP increments.
2. Complete 4 categories -> oracle modifier applied.
3. Resolve event -> journal reflects event.
4. Month boundary -> admissions and tuition update.
5. Feature parity across web, canvas, iOS.

## 15. Security and Data Safety

1. All endpoints require authenticated user context.
2. User-scoped row filtering on all queries.
3. Input validation for manual logs and mapping edits.
4. No executable dynamic rule code in DB.
5. Narrative prompts must not include secrets or raw tokens.

## 16. Rollout Plan

### 16.1 Feature Flags

Add app-level flags:

- `temerant_enabled`
- `temerant_oracle_enabled`
- `temerant_narrative_enabled`
- `temerant_auto_ingestion_enabled`

Flags can live in `app_settings` and be surfaced via existing settings APIs.

### 16.2 Rollout Stages

1. Stage 1: backend tables + core APIs + web page (manual logging only).
2. Stage 2: auto-ingestion from habits and fitness.
3. Stage 3: canvas window + workspace tool integration.
4. Stage 4: iOS screen and mobile parity.
5. Stage 5: narrative enhancements and optional Neo4j relationship layer.

### 16.3 Backfill

Optional one-time backfill job for previous 30 days from:

- `habit_logs`
- fitness logs
- learning sessions

Backfill writes ledger entries with explicit `source_type='backfill'` in metadata and strict idempotency keys.

## 17. Definition of Done

1. Backend endpoints implemented and documented.
2. Web `/temerant` page functional and linked in navigation.
3. Canvas `temerant` window functional and openable from mode wheel and workspace command.
4. iOS Temerant screen accessible from More menu and fully usable.
5. Deterministic scoring validated by tests.
6. Oracle and term systems functioning end-to-end.
7. Feature flags and rollback path in place.

## 18. Implementation Task Breakdown

### Phase A: Backend Foundation

1. Add models and migration.
2. Add schemas and services package.
3. Implement `/api/temerant` routes.
4. Wire router in `backend/app/main_simple.py`.
5. Add unit and API tests.

### Phase B: Web App Page

1. Add `temerant` view route metadata.
2. Add navigation items.
3. Build `TemerantPage` and subcomponents.
4. Add service client and wire to APIs.
5. Add UI tests.

### Phase C: Canvas Window

1. Register `temerant` window type and defaults.
2. Build `TemerantContent`.
3. Add mode wheel launcher tile.
4. Update workspace command type mapping.
5. Add canvas tests.

### Phase D: iOS Screen

1. Add navigation route and More menu entry.
2. Build service module and typed models.
3. Build `TemerantScreen`.
4. Add refresh and manual log flow.
5. Add mobile tests.

### Phase E: Cross-Surface Polish

1. Workspace and chat tools for Temerant actions.
2. Feature flags and staged rollout.
3. Metrics dashboards and QA pass.

## 19. Open Decisions (Need Product Call)

1. Should `coin_balance` be strictly tied to real budget data, or partially gamified in V1?
2. Should oracle rolls be always automatic at day close, or user-triggered plus auto fallback?
3. Should iOS expose Temerant as a main tab or keep it under More?
4. Should web and canvas use identical panel density, or keep canvas compact by design?
5. Should Re'lar and El'the promotions require explicit user confirmation ceremony flow?

## 20. Recommended Defaults for First Build

1. Keep iOS entry under More, not a tab.
2. Keep oracle both auto-at-close and user-triggered once/day.
3. Keep coin partially gamified until finance integration is complete.
4. Keep Postgres-only for core state; defer Neo4j relationship graph to later phase.
5. Keep daily XP caps enabled from day one.

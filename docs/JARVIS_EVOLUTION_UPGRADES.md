# Sara → Jarvis: Autonomous Evolution Upgrades

**Date:** February 20, 2026
**Branch:** `autonomy`

This document describes all upgrades implemented in the Sara → Jarvis Evolution Plan — transforming Sara from a notification bot into a true autonomous AI partner.

---

## Phase 1: Trust Repair

### 1A. Morning Brief Calendar Fix
**Problem:** Morning brief showed stale or missing calendar events because it relied on DB-synced calendar data without freshness validation.

**Changes:**
- `backend/app/services/morning_brief_service.py`
  - Added `_check_calendar_sync_freshness()` — queries latest calendar sync timestamp, warns if >2 hours stale
  - Enhanced `gather_calendar()` — explicit "I couldn't get your calendar" message when data is stale/empty
  - Added `_bootstrap_stable_layer()` — generates stable layer from PKG + episodic memory when missing
  - Context layer staleness now checked with tighter threshold
  - Cron job timezone fixed (was running at 1am ET due to UTC cron)

### 1B. Health/Fitness Notification Ban
**Problem:** Health notifications kept appearing despite HEARTBEAT.md bans. Only the deliberation path checked bans — 12+ other notification paths bypassed them.

**Changes:**
- `backend/app/services/deliberation_gate.py`
  - Expanded `_BANNED_PHRASES` from ~14 to 80+ entries covering all health/fitness/biometric categories
  - Added `_BANNED_CATEGORIES`: `{"health", "fitness", "wellness"}`
  - Added `is_notification_banned()` public function
- `backend/app/services/unified_notification.py`
  - Ban checking moved INTO `send_notification()` — every notification goes through the ban filter
  - Added `_PREF_CACHE` with 5-minute TTL for per-user preferences
  - Added `_check_notification_ban()` combining static bans + dynamic user preferences
- `backend/app/models/notification_preference.py` — NEW model for per-user category toggles
- `backend/alembic/versions/046_notification_preferences.py` — NEW migration (seeded with health/fitness OFF)
- `backend/app/routes/settings.py` — `GET/PUT /api/settings/notification-preferences`
- `backend/app/services/notification_service.py` — Added ban check in `send_wellness_alert()`
- `frontend/src/App-interactive.tsx` — Removed health alert polling that bypassed bans
- `frontend/src/pages/Settings.tsx` — Notification preference toggles UI
- `ios-app/src/screens/settings/SettingsScreen.tsx` — iOS notification toggles

### 1C. Deliberation Visibility
**Problem:** Sara ran 10-20+ deliberations/day producing thoughts, decisions, and actions — but David couldn't see any of it.

**Changes:**
- `frontend/src/components/SaraInnerLife.tsx` — NEW: "Sara's Mind" panel with Overview/Thoughts/Observations tabs, 30s auto-refresh
- `frontend/src/navigation/views.ts` — Added `'saras-mind'` view
- `frontend/src/App-interactive.tsx` — Added navigation entry and rendering
- `workbench-canvas/src/components/PartnerThoughts.tsx` — Rewritten with deliberation history, observations, working memory
- `ios-app/src/screens/sara/SaraActivityScreen.tsx` — Added "Mind" tab as default view

---

## Phase 2: PKG Auditability — "What Does Sara Know About Me?"

### 2A. PKG Viewer Across All Apps
**Problem:** PKG viewer only existed in workbench. Web app and iOS had no way to see Sara's knowledge.

**Changes:**
- **Backend:** `backend/app/routes/personal_knowledge.py`
  - `POST /api/pkg/node` — create new knowledge node
  - `POST /api/pkg/reextract` — trigger re-extraction from recent conversations
  - `GET /api/pkg/summary` — natural language summary of what Sara knows
- **Web App:** `frontend/src/components/PersonalKnowledge.tsx` — NEW: Full PKG viewer with search, category tabs, CRUD, confidence indicators
- **iOS:** `ios-app/src/screens/knowledge/KnowledgeScreen.tsx` — NEW: Card-based viewer with category pills, swipe actions

### 2B. PKG Self-Validation
**Problem:** PKG facts could be stale or wrong but never got re-checked.

**Changes:**
- `backend/app/services/personal_knowledge_graph.py`
  - `validate_against_recent()` — compare PKG facts against 30 days of episodes, flag contradictions
  - `get_needs_review()` — query nodes flagged for review
  - `mark_reviewed()` — clear review flag, optionally update confidence
- `backend/app/services/consolidation.py` — PKG validation step in evening consolidation (9 PM)
- `backend/app/routes/personal_knowledge.py`
  - `GET /api/pkg/needs-review`, `POST /api/pkg/{node_id}/reviewed`, `GET /api/pkg/validation-report`
- `backend/app/services/morning_brief_service.py` — Mentions flagged items in morning brief

---

## Phase 3: Autonomous Task Execution — "Sara, Just Handle It"

### 3A. Natural Chat → Agent Dispatch
**Problem:** Agent dispatch tools existed but Sara didn't use them naturally from chat.

**Changes:**
- `backend/app/main_simple.py` — System prompt updated: when David asks Sara to do something, she dispatches an agent rather than saying "I can't"
- `backend/app/services/event_bus.py` — Added `AGENT_TASK_PROGRESS` EventType
- `backend/app/services/agent_dispatch.py` — `notify_on_complete` param, progress events, completion notifications
- `backend/app/tools/agent_dispatch.py` — Added `DispatchAndMonitorTool` (dispatch + auto-notify David)
- `backend/app/tools/registry.py` — Registered new tool

### 3B. Proactive Task Creation from Deliberation
**Problem:** Sara could only dispatch tasks when David explicitly asked. A Jarvis should notice things and just handle them.

**Changes:**
- `backend/app/services/deliberation.py` — `TaskProposal` dataclass, `task_proposals` on `DeliberationResult`
- `backend/app/services/deliberation_prompt.py` — Autonomy tier rules in prompt
- `backend/app/services/deliberation_gate.py` — Three autonomy tiers:
  - **Auto-execute:** research, PKG updates, home control, maintenance
  - **Propose first:** calendar changes, irreversible actions
  - **Hard block:** email sending (NEVER), purchases
- `backend/app/services/agent_dispatch.py` — `dispatch_from_deliberation()` method

### 3C. Agent Visibility Across Apps
**Problem:** Mission panel existed but no real-time progress or iOS support.

**Changes:**
- `backend/app/services/reactive_engine.py` — `AgentTaskProgressSubscriber` forwarding WebSocket events
- `backend/app/routes/autonomy_missions.py` — `POST /autonomy/missions/{id}/action` for inline clarification
- `frontend/src/components/MissionPanel.tsx` — WebSocket real-time updates, clarification UI, live indicators
- `workbench-canvas/src/components/MissionFeed.tsx` — Same WebSocket updates + clarification panel
- `ios-app/src/screens/agents/AgentTasksScreen.tsx` — NEW: Filter tabs, progress bars, clarification input

### 3D. Skill Learning from Completed Tasks
**Problem:** Sara didn't learn from successful task completions.

**Changes:**
- `backend/app/models/candidate_skill.py` — Added `times_used`, `times_succeeded` columns
- `backend/alembic/versions/048_skill_effectiveness_tracking.py` — NEW migration
- `backend/app/services/agent_dispatch.py` — 4 new methods:
  - `_find_relevant_skills()` — keyword matching against skill library
  - `_extract_skill_recipe()` — LLM-based skill extraction after successful tasks
  - `_track_skill_usage()` — increment success/failure counters
  - `_format_skills_for_prompt()` — inject skill context into orchestrator
- `backend/app/services/sandbox_orchestrator.py` — `skill_context` injection into system prompt

---

## Phase 4: Continuous Evolution — "Always Working, Always Learning"

### 4A. Proactive AI/Tech Intelligence Monitor
**Problem:** AI news was only in morning briefs. David wanted continuous monitoring.

**Changes:**
- `backend/app/models/intelligence_item.py` — NEW: SQLAlchemy model
- `backend/alembic/versions/045_intelligence_items.py` — NEW migration
- `backend/app/services/intelligence_monitor.py` — NEW: 17 RSS sources + HuggingFace + Hacker News
  - Three categories: AI Research, Local/Open-Source AI, Broader Tech
  - Novelty scoring (title similarity, age, HN score)
  - Relevance scoring (PKG interests, category base scores, keyword boosts)
  - LLM-powered digest generation
  - Breaking news detection (novelty > 0.85 + relevance > 0.65)
- `backend/app/tasks/intelligence.py` — NEW: `intelligence_scan` (2h) + `intelligence_digest` (2x daily)
- `backend/app/celery_app.py` — 3 new beat entries
- `backend/app/routes/intelligence.py` — NEW: feed, digest, stats, dismiss, dig-deeper, scan-now
- `frontend/src/components/IntelligenceFeed.tsx` — NEW: Full feed with filters, scores, dig deeper
- `workbench-canvas/src/components/windows/IntelligenceContent.tsx` — NEW: Compact feed window
- `ios-app/src/screens/intelligence/IntelligenceScreen.tsx` — NEW: Card-based feed

### 4B. Notification Feedback Loop
**Problem:** Sara didn't learn from what David ignores vs engages with.

**Changes:**
- `backend/alembic/versions/047_notification_feedback.py` — NEW: read_at, engaged, dismissed_at, response_text columns
- `backend/app/routes/push_tokens.py` — `POST /api/notifications/{id}/feedback`, `GET /api/notifications/engagement-stats`
- `backend/app/services/consolidation.py` — Engagement analysis in evening consolidation, stores per-category rates in working memory
- `backend/app/services/deliberation_prompt.py` — "Notification Engagement" section in deliberation whiteboard
- `backend/app/services/unified_context.py` — `notification_engagement_stats` field
- `backend/app/services/unified_notification.py` — notification_id included in push payload
- `backend/app/services/autonomy/attention_queue.py` — Propagates read/dismiss feedback to notification_log
- Frontend/iOS — engagement tracking on notification interaction

### 4C. Self-Directed Research from Interests
**Problem:** Research only happened when David manually dispatched it.

**Changes:**
- `backend/app/services/deliberation.py` — `research_proposals` field on DeliberationResult
- `backend/app/services/deliberation_prompt.py` — Research proposal rules (3+ topic mentions, max 1/deliberation)
- `backend/app/services/deliberation_gate.py` — Daily research cap (1/day), dispatch + journal logging
- `backend/app/services/consolidation.py` — PKG interests + recent chat topics as context, auto-dispatch from consolidation (shared daily cap)

### 4D. PKG Self-Validation & Growth
**Problem:** PKG facts decayed but never got actively verified or expanded.

**Changes:**
- `backend/app/services/pkg_extractor.py` — `extract_from_behavior()`: notification engagement, topic frequency, response-time patterns (weekly, rate-limited)
- `backend/app/services/personal_knowledge_graph.py` — `identify_knowledge_gaps()`, `promote_high_confidence()`
- `backend/app/services/consolidation.py` — Confidence promotion, gap identification, Sunday behavioral extraction
- `backend/app/services/deliberation_prompt.py` — "Knowledge Gaps" section in whiteboard
- `backend/app/services/unified_context.py` — `pkg_validation_report`, `pkg_knowledge_gaps` fields

### 4E. Behavioral Calibration
**Problem:** Sara's behavior didn't adapt based on what works.

**Changes:**
- `backend/app/services/consolidation.py` — `_generate_weekly_calibration()`: per-category metrics, trends, best/worst hours, natural-language insights (Sundays/every 7th consolidation)
- `backend/app/services/personality_engine.py` — Calibration cache (1-hour TTL), `_load_calibration_data()`, `_build_calibration_directives()` (up to 5 actionable directives)
- `backend/app/services/deliberation_prompt.py` — "Behavioral Calibration (Weekly)" section
- `backend/app/main_simple.py` — Calibration data loaded and passed in both chat paths
- `backend/app/services/unified_context.py` — `behavioral_calibration` field

---

## Database Migrations

| Migration | Table/Columns | Purpose |
|-----------|---------------|---------|
| `045_intelligence_items` | `intelligence_item` | AI/tech intelligence feed storage |
| `046_notification_preferences` | `notification_preference` | Per-user notification category toggles |
| `047_notification_feedback` | `notification_log` +4 columns | Engagement tracking (read, engaged, dismissed, response) |
| `048_skill_effectiveness_tracking` | `candidate_skill` +2 columns | Skill usage and success tracking |

---

## New Frontend Views

| View | Web App | Workbench | iOS |
|------|---------|-----------|-----|
| Sara's Mind | `SaraInnerLife.tsx` | `PartnerThoughts.tsx` (enhanced) | `SaraActivityScreen.tsx` (Mind tab) |
| Knowledge | `PersonalKnowledge.tsx` | Existing `PKGContent.tsx` | `KnowledgeScreen.tsx` |
| Intelligence | `IntelligenceFeed.tsx` | `IntelligenceContent.tsx` | `IntelligenceScreen.tsx` |
| Agent Tasks | `MissionPanel.tsx` (enhanced) | `MissionFeed.tsx` (enhanced) | `AgentTasksScreen.tsx` |
| Settings | Notification prefs added | N/A | Notification prefs added |

---

## Celery Beat Schedule Additions

| Task | Schedule | Queue | Purpose |
|------|----------|-------|---------|
| `intelligence-scan` | Every 2 hours | low_priority | Scan RSS, HN, HuggingFace |
| `intelligence-digest-noon` | 12:30 PM | cognitive | Synthesize morning items |
| `intelligence-digest-evening` | 6:30 PM | cognitive | Synthesize afternoon items |

---

## Autonomy Boundaries

| Tier | Actions | Behavior |
|------|---------|----------|
| **Auto-execute** | Research, PKG updates, note organization, home control, internal maintenance | Execute immediately, notify after |
| **Propose first** | Calendar changes, anything user-facing, irreversible actions | Ask David first |
| **Hard block** | Email sending, purchases, external messaging | NEVER execute |

---

## Key Architectural Decisions

1. **Ban enforcement at pipeline level** — `send_notification()` checks bans before any delivery, not just deliberation path
2. **Shared daily research cap** — deliberation and consolidation share a single daily auto-research limit (1/day)
3. **No LLM in behavioral extraction** — purely data-driven inference from notification engagement and conversation patterns
4. **Skill learning loop** — find skills → inject context → track success → extract new skills → repeat
5. **Calibration data flows through working memory** — consolidation writes weekly calibration to Redis, personality engine reads with 1-hour cache
6. **Event-driven agent progress** — WebSocket broadcasts via ReactiveEngine subscriber pattern

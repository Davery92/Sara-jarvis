# Sara Self-Knowledge: Autonomous Systems

These run independently and inform your awareness:

## Nightly Dream Sequence

**Schedule:** 2:00-3:00 AM Eastern
**Location:** `backend/app/services/nightly_dream_service.py`

Processes the entire day's conversations:
1. Fetch yesterday's episodes for each user
2. Group episodes into conversation sessions (30-minute gap threshold)
3. Content intelligence analysis (entities, relationships, moods)
4. Metadata extraction (tags, importance, novelty)
5. Smart tagging system
6. Store consolidated knowledge in Neo4j
7. Create meaningful connections (entity-based, topic-based, context-based)
8. Generate daily summaries
9. Run cognitive processing (Sara's reflections, hypothesis extraction)
10. Emit importance decay events for memory self-curation
11. Update Daily Brief context layer with dream insights

## Scheduled Jobs (APScheduler)

**Location:** `backend/app/services/scheduler.py`

| Job | Schedule | Purpose |
|-----|----------|---------|
| **daily_compaction** | 2:10 AM | Create daily semantic summaries from episodes |
| **weekly_compaction** | Sunday 3:00 AM | Create weekly synthesis from daily summaries |
| **rating_consolidation** | 2:30 AM | Sync Redis ratings → PostgreSQL, calculate Wilson Scores |
| **reminder_timer_check** | Every 1 minute | Check for due reminders and expired timers |

## Systemd Services

**Location:** `backend/*.service`

### sara-subconscious.service
**Purpose:** Background mental model and awareness service
**Worker:** `app.workers.subconscious_worker`
**Logs:** `/home/david/jarvis/logs/subconscious_worker.log`

Runs the subconscious system that gathers signals from:
- Presence (first activity, last seen, chat frequency)
- Meals (time since eating, typical meal windows)
- Conversations (velocity, focus areas, inferred mood/energy)
- Health (sleep hours, quality, deficits)
- System health (LLM status, Docker health)

Generates nudges when thresholds are crossed. Writes to Sara's inner monologue journal.

### sara-health-watchdog.service
**Purpose:** Proactive health monitoring
**Worker:** `app.workers.health_watchdog`
**Logs:** `/home/david/jarvis/logs/health_watchdog.log`

Monitors health metrics for anomalies:
- HR, HRV, sleep, steps detection
- Maintains rolling baselines
- Correlates with food logs, workouts, conversation stress
- Sends push notifications for warning/urgent severity

### sara-scheduled-home.service
**Purpose:** Execute scheduled home automation actions
**Logs:** `/home/david/jarvis/logs/scheduled_home.log`

Executes home automation actions scheduled via `home_schedule_action`:
- Checks for pending scheduled actions
- Executes when scheduled time arrives
- Handles recurring schedules (daily, weekdays, weekends, weekly)
- Updates status to executed/failed

### sara-ha-listener.service
**Purpose:** Home Assistant event listener
**Logs:** `/home/david/jarvis/logs/ha_listener.log`

Listens to Home Assistant WebSocket for state changes:
- Logs device state changes to `home_activity_log` table
- Enables home status reporting with recent activity

### sara-agent.service
**Location:** `sara-agent/*.service`
**Purpose:** Desktop agent for cross-device control

## Insight Services

### Autonomous Sweep Service
**Location:** `backend/app/services/autonomous_sweep_service.py`

Three sweep types with different interruption thresholds:

1. **Quick Sweep** (priority threshold: 0.6)
   - Fast pattern matching
   - Real-time notifications for urgent items

2. **Standard Sweep** (priority threshold: 0.4)
   - Full analysis with memory context
   - Deduped notifications

3. **Digest Sweep** (priority threshold: 0.2)
   - Comprehensive summary
   - Batch notifications

**Priority Scoring:**
```
priority = relevance × impact × novelty × timing - annoyance
```

### Insight Injection Service
**Location:** `backend/app/services/insight_injection.py`

Proactively surfaces relevant dream insights during conversation:
- Checks conversation embedding similarity to stored insights
- Filters duplicates via 24-hour dedup window
- Respects user preferences on notification frequency
- Tracks accepted/dismissed insights

### Cognitive Services

**Sara Identity Service** (`backend/app/services/sara_identity_service.py`)
- Tracks self-reflections and lessons learned
- Maintains relationship state with user
- Stores communication pattern preferences

**Hypothesis Service** (`backend/app/services/hypothesis_service.py`)
- Extracts beliefs about user with confidence scores
- Automatically updates from conversations
- Decays stale hypotheses

**Body State Service** (`backend/app/services/body_state_service.py`)
- Tracks physiological awareness
- Provides context for health-related responses

**Sara Journal Service** (`backend/app/services/sara_journal_service.py`)
- Maintains Sara's inner monologue
- Stores reflections from subconscious processing

## Event-Driven Processing

### Event Outbox Pattern
**Location:** `EventOutbox` model in `backend/app/main_simple.py`

Events are queued for async processing:
- `importance_decay` - Gradually fade old, unreferenced memories
- Other event types for background processing

### Nightly Rescoring
**Location:** `backend/app/services/nightly_rescoring_job.py`

Recalculates importance scores for episodes:
- Batches 100 episodes at a time
- Uses LLM (with heuristic fallback)
- Scores on: importance, affect, novelty, taskness

## Service Health

All services use systemd with:
- Automatic restart on failure (RestartSec=30)
- Logging to `/home/david/jarvis/logs/`
- Environment variables for database and LLM access

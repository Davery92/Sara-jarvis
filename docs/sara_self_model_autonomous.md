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

<!-- BEGIN GENERATED -->
_Regenerated 2026-09-02 by truth-maintenance._

## Scheduled Jobs

These are the jobs actually enabled in `scheduled_job` right now — not a remembered list.

| Job | Schedule | Queue | Purpose |
|---|---|---|---|
| **automation-watcher** | `every 0 min` | critical | Finds and dispatches due automation tasks every 30 seconds |
| **afternoon-consolidation** | `0 14 * * *` | cognitive | Deep reflection on patterns at 2 PM |
| **attention-escalation-sweep** | `every 30 min` | cognitive | Quietly expires unread attention items past their useful window |
| **autonomy-retention-cleanup** | `0 4 * * *` | maintenance | Daily cleanup of old autonomy logs at 4 AM |
| **container-cleanup** | `0 * * * *` | maintenance | Destroys idle ephemeral containers, hourly |
| **daily-autonomy-digest** | `40 21 * * *` | low_priority | Summary of agent runs and notifications at 9:40 PM |
| **derived-signal-refresh** | `every 5 min` | low_priority | DB-dependent working memory updates: body state, activity, hours-since-chat/meal, habits,  |
| **evening-anticipation** | `20 21 * * *` | cognitive | Prepares for tomorrow at 9:20 PM (staggered from consolidation) |
| **evening-consolidation** | `0 21 * * *` | cognitive | Deep reflection on patterns at 9 PM |
| **home-state-summary** | `5 * * * *` | low_priority | Aggregates HA events for pattern analysis, 5 min past each hour |
| **idle-processing** | `every 10 min` | low_priority | Productive use of quiet time, every 10 minutes |
| **mission-worker** | `every 0 min` | critical | Advances runnable missions every 30 seconds |
| **morning-anticipation** | `0 6 * * *` | cognitive | Prepares anticipated context for the day at 6 AM |
| **nightly-consolidation** | `40 3 * * *` | maintenance | Processes the day's experiences at 3 AM |
| **nightly-dream-cycle** | `0 2 * * *` | cognitive | Memory consolidation 'dream' cycle at 2 AM Eastern |
| **periodic-deliberation-fallback** | `every 30 min` | cognitive | Safety net for event-driven deliberation |
| **proactive_checkin_sweep** | `*/15 8-20 * * *` | cognitive | Occasional 'how's it going' pings and post-meeting follow-ups, gated by interruptibility |
| **sara-self-queue-promote** | `every 20 min` | cognitive | Auto-queues an inbox item from Sara's top stale standing interest when she has nothing act |
| **scan_ended_meetings** | `*/10 7-22 * * *` | cognitive | Detects meetings that just ended and queues a follow-up thread |
| **standing-order-time-check** | `every 2 min` | critical | Ensures time-based standing orders fire even without unified_agent scheduling |
| **weather-context-refresh** | `every 30 min` | low_priority | Updates temperature/conditions in the unified snapshot every 30 min |
| **morning-proactive-check** | `0 * * * *` | cognitive | Evaluates active behavioral patterns against current conditions (weather, day, time) and s |
| **calendar-prep-check** | `every 15 min` | cognitive | Checks upcoming events and sends prep notifications every 15 minutes |
| **cross-system-synthesis** | `every 60 min` | low_priority | Finds connections between email, calendar, and notes hourly |
| **belief-promotion-sweep** | `0 11 * * *` | cognitive | Daily: advance patterns up the ladder (observed→predictive→actionable) and mint standing-o |
| **ml-retrain-inprocess** | `45 2 * * *` | cognitive | Nightly in-process training of model families (notification_value) from labeled outcomes;  |
| **morning-readiness-compute** | `15 5 * * *` | cognitive | Nightly readiness = f(sleep, HRV, RHR vs personal baselines) → morning_readiness (§6 |
| **prediction-calibration** | `0 10 * * 0` | cognitive | Sunday: grade whether stated confidence matched actual hit-rate per domain (§3 |
| **prediction-generate** | `30 4 * * *` | cognitive | Mint the day's predictions from learned rhythm + high-confidence home patterns (§3 |
| **prediction-match** | `every 15 min` | cognitive | Every 15 min: resolve pending predictions confirmed/violated/expired; violations feed sali |
| **assistant-verbs-sweep** | `*/30 8-20 * * *` | cognitive | Deterministic email drafts (unhandled important email >4h old, capped 3/day) + commitment  |
| **deep-deliberation-afternoon** | `15 14 * * *` | cognitive | 14:15 ET deep deliberation on the strong model — wider observation window, higher task-pro |
| **deep-deliberation-evening** | `15 21 * * *` | cognitive | 21:15 ET deep deliberation on the strong model — wider observation window, higher task-pro |
| **mindv2-appraisal-cycle** | `every 3 min` | cognitive | SARA_MIND_V2 Phase 3: reads pending observations + World Brief + Interest Model, writes br |
| **mindv2-batch-flush** | `every 15 min` | cognitive | Arc 1 |
| **mindv2-compose-cycle** | `every 3 min` | cognitive | SARA_MIND_V2 Phase 2: composes + reviews judged_send candidates into composed_utterance fo |
| **mindv2-deliver-cycle** | `every 3 min` | cognitive | Delivers approved/edited composed_utterance rows through the real attention/interruptibili |
| **mindv2-judge-cycle** | `every 3 min` | cognitive | SARA_MIND_V2 Phase 4: ranks pending say_candidates, decides drop/batch/send_now, dispatche |
| **mindv2-say-candidate-purge** | `every 5 min` | cognitive | SARA_MIND_V2 Phase 2: expire say_candidate rows past their valid_until TTL |
| **mindv2-weekly-review** | `15 19 * * 0` | cognitive | SARA_MIND_V2 Phase 4: open commitments, interest-model diff proposals, utterance self-eval |
| **mindv2-world-brief-sweep** | `every 5 min` | cognitive | SARA_MIND_V2 Phase 1: refresh the World Brief patch-backed sections (calendar, open loops, |
| **pkg-stale-goals** | `15 4 * * *` | cognitive | Marks PKG_Goal active rows past target_date+7d as stale to keep chat context fresh |
| **weekly-health-consolidation** | `0 6 * * 1` | cognitive | 3-stage Sunday 6 AM ET pipeline: recovery → activity → synthesizer |
| **daily-brief-archive** | `0 0 * * *` | maintenance | Midnight day-layer archival |
| **daily-brief-consolidate** | `every 30 min` | cognitive | Hourly day-layer consolidation |
| **daily-brief-context-update** | `0 23 * * *` | cognitive | Daily 11 PM context-layer update |
| **daily-brief-weekly-synthesis** | `0 3 * * 0` | cognitive | Sunday 3 AM weekly synthesis of the stable layer |
| **email-sync** | `every 3 min` | low_priority | Fetches new emails from MS Graph every 3 minutes |
| **buffer-cleanup** | `every 5 min` | maintenance | Removes expired entries from the raw observation buffer (TTL enforcement) |
| **consolidation-watcher** | `every 1 min` | critical | Checks every minute if a quiet period has been reached, then triggers consolidation |
| **context-refresh** | `every 1 min` | critical | Refreshes the working memory context window every minute |
| **system-heartbeat** | `every 5 min` | health | Health monitoring ping every 5 minutes |
| **meeting-research-scan** | `every 60 min` | cognitive | Pre-research the counterparty of upcoming business meetings so findings are ready beforeha |
| **fleet-offline-sweep** | `every 5 min` | health | Fires/resolves host_offline for agent-equipped machines that stopped reporting |
| **health-anomaly-detect** | `*/30 6-23 * * *` | health | Compares latest readings against 7-day baselines (z-score) and writes alerts/insights for  |
| **health-baseline-recompute** | `15 2 * * *` | health | Recomputes 7-day and 30-day rolling baselines (avg, std, min, max) for every tracked healt |
| **interoception-self-check** | `5 8 * * *` | health | Daily body-scan: failing tasks, queue depths, heartbeat, voice, backup |
| **predictive-engine** | `every 30 min` | cognitive | Pattern-based forward-looking suggestions every 30 min |
| **check-stuck-research** | `every 3 min` | low_priority | Detects stuck research jobs every 3 minutes |
| **deep-research-poller** | `every 1 min` | cognitive | Processes queued research jobs every 60 seconds |
| **materialize-ml-features** | `30 2 * * *` | cognitive | Nightly rollup of desktop focus, location, sleep/health, workout/food, calendar, notificat |
| **pending-source-fetcher** | `every 2 min` | cognitive | Auto-fetches sources with fetch_status='pending' every 2 minutes |
| **recompute-daily-rhythm** | `45 3 * * *` | cognitive | Nightly percentile pass over location, workout, food, calendar, and behavioral-pattern his |
| **sync-ml-notification-outcomes** | `every 60 min` | cognitive | Hourly: back-fill ml_notification_outcome |
| **location-leave-now-nudges** | `every 15 min` | cognitive | Checks upcoming calendar events with a location against current position and drive time; n |
| **location-place-discovery** | `30 3 * * *` | cognitive | Nightly scan of location history for frequently-visited spots not yet saved as places; sta |
| **fleet-metric-prune** | `17 3 * * *` | maintenance | Nightly prune of host_metric rows older than 30 days |
| **interoception-drain-events** | `every 2 min` | maintenance | Move redis-buffered WARNING+ log records into system_event |
| **interoception-purge-events** | `20 4 * * *` | maintenance | 30-day retention on the system_event ring buffer |
| **tool-call-eval** | `0 5 * * 1` | maintenance | Scripted tool-call suite vs the local model; pass-rate to the ledger |
| **weekly-self-audit** | `30 18 * * 0` | maintenance | Sara reviews her ledger, drift, feed quality + muted interests -> Sunday journal |
| **morning-brief-generate** | `0 6 * * *` | cognitive | Generates the daily morning brief (news, weather, calendar, dream insights) and sends iOS  |
| **calendar-reminder-topup** | `5 3 * * *` | cognitive | Daily task that extends reminders for recurring calendar events past the initial 30-day wi |
| **location-trigger-expiry** | `15 * * * *` | cognitive | Hourly sweep that expires armed one-shot location triggers past their expires_at |
| **morning-inbox-digest** | `0 8 * * *` | cognitive | Reminds about unread Inbox items on phone at 8 AM |
| **notification-predispatch** | `every 0 min` | critical | Finds timers/reminders due in the next ~20 seconds and sends their push notifications |
| **notification-tuner** | `15 6 * * *` | maintenance | Adjusts notification frequency based on engagement, daily 6:15 AM |
| **sync-sent-items** | `every 15 min` | low_priority | Syncs the Sent folder so the person layer sees who David wrote to, not just who wrote to h |
| **pkg-evening-extract** | `0 18 * * *` | cognitive | Mines conversations for personal knowledge graph entries at 6 PM |
| **pkg-midday-extract** | `0 12 * * *` | cognitive | Mines conversations for personal knowledge graph entries at 12 PM |
| **pkg-reconciliation** | `every 60 min` | maintenance | Syncs Neo4j and pgvector shadow table hourly |
| **reflection-cycle** | `0 */4 * * *` | reflection | Meta-cognitive auditing of recent activity, every 4 hours |
| **reflection-report** | `0 9 * * *` | low_priority | Generates the daily reflection report at 9 AM |
| **scratchpad-cleanup** | `0 5 * * *` | maintenance | Removes expired observations from the reflection scratchpad |
| **research-brief-generate** | `0 2 * * *` | cognitive | Fetches arXiv cs |
| **attention-learning-tick** | `30 3 * * *` | low_priority | Learns promotion thresholds per domain×context from engagement + decays toward priors (clo |
| **db-maintenance-analyze** | `0 9 * * 0` | maintenance | Weekly full-database ANALYZE so the planner and stats-reading diagnostics work off real nu |
| **delivery-policy-flush** | `every 15 min` | cognitive | Every 15 min: if David is awake, deliver notifications held overnight as one digest (unifi |
| **departure-brief** | `*/5 6-10 * * 1-5` | cognitive | Every 5 min, 6-10 AM weekdays: fires the second morning push ~25 min before David leaves — |
| **dispatch-watchdog** | `every 30 min` | low_priority | Auto-expires stuck background agent tasks (>4h) and notifies only on repeated failure, sur |
| **intent-graph-sync** | `every 15 min` | maintenance | Keeps the durable intent table current with reminders, standing orders, missions, threads, |
| **learning-digest-weekly** | `0 19 * * 0` | low_priority | Sunday ~7PM ET first-person note on what Sara has learned about when to speak up — theta m |
| **subconscious-tier0-tick** | `every 15 min` | low_priority | Baselines the firehose (health/home) and promotes only anomalies to consciousness |
| **system-wiring-check** | `0 8 * * 0` | low_priority | Weekly self-audit: unscheduled Celery tasks, unhealthy scheduled_job rows, stale learning  |
| **truth-maintenance** | `50 3 * * *` | maintenance | Expires stale threads, reminders and commitments; audits life-fact sanity, contradictory p |
| **world-state-attention-drain** | `every 1 min` | critical | Recovers durable attention wakes and routes them through Sara's single ambient kernel |
| **world-state-drain** | `every 0 min` | critical | Recovers durable world events when immediate dispatch was unavailable |
| **world-state-interpretation-drain** | `every 0 min` | critical | Recovers rich local-model interpretation work after dispatch or model outages |
| **world-state-temporal** | `every 1 min` | critical | Advances calendar starts/ends, due threads, expiry, and stale presence without an app open |
| **bedtime-intelligence** | `0 20-22 * * *` | cognitive | Evening winddown nudge timed from the learned winddown window + sleep debt + tomorrow's fi |
<!-- END GENERATED -->

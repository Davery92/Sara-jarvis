# Jarvis Mode Implementation Guide

This guide walks through the implementation of Jarvis mode - transforming Sara from a reactive assistant into an autonomous personal AI hub.

## Overview

Jarvis mode introduces:
- **Solo User Mode**: Simplified single-user operation
- **Proactive Inbox**: Unified notification system replacing chat spam
- **Daily Briefings**: Morning digest of priorities and insights
- **Memory Consolidation**: Nightly processing and insight generation
- **Autonomous Tasks**: Background multi-tool research and analysis
- **Visual Presence**: Sprite system showing system state

## Phase 1: Foundations ✅ IMPLEMENTED

### Components Created

#### 1. Database Models
- `app/models/jarvis_inbox.py` - Central inbox for all proactive notifications
- `app/models/jarvis_tasks.py` - Background task tracking and audit
- `app/models/daily_brief.py` - Daily briefing cache and metadata

#### 2. Services
- `app/services/jarvis_inbox_service.py` - Core inbox management with nudge policy
- `app/services/daily_brief_service.py` - Intelligent daily brief generation
- `app/services/solo_mode_service.py` - Single-user mode configuration

#### 3. API Routes
- `app/routes/jarvis_inbox.py` - RESTful inbox management
- `app/routes/daily_brief.py` - Daily briefing endpoints

### Database Migration

Run these commands to set up Phase 1:

```sql
-- Add inbox table
CREATE TABLE jarvis_inbox (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    kind VARCHAR(20) CHECK (kind IN ('insight', 'alert', 'reminder', 'suggestion')),
    title VARCHAR(255) NOT NULL,
    body TEXT,
    source VARCHAR(50),
    payload JSONB DEFAULT '{}',
    priority INTEGER DEFAULT 5,
    status VARCHAR(10) DEFAULT 'new' CHECK (status IN ('new', 'read', 'archived')),
    dedupe_key VARCHAR(100),
    batch_id VARCHAR(36),
    created_at TIMESTAMP DEFAULT NOW(),
    read_at TIMESTAMP,
    archived_at TIMESTAMP
);

-- Add daily briefs table
CREATE TABLE daily_briefs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    brief_date DATE NOT NULL,
    sections JSONB DEFAULT '[]',
    generated_at TIMESTAMP DEFAULT NOW(),
    generation_duration_ms INTEGER,
    calendar_events_count INTEGER DEFAULT 0,
    reminders_count INTEGER DEFAULT 0,
    insights_count INTEGER DEFAULT 0,
    dream_highlights_count INTEGER DEFAULT 0,
    cache_key VARCHAR(100),
    cache_expires_at TIMESTAMP,
    viewed_at TIMESTAMP,
    pinned_items JSONB DEFAULT '[]'
);

-- Add tasks table (for Phase 6)
CREATE TABLE jarvis_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    kind VARCHAR(20) CHECK (kind IN ('research', 'draft', 'compare', 'summarize', 'analyze')),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    inputs JSONB DEFAULT '{}',
    state VARCHAR(20) DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'waiting_confirm', 'done', 'failed', 'cancelled')),
    progress INTEGER DEFAULT 0,
    estimated_duration_minutes INTEGER,
    result JSONB DEFAULT '{}',
    summary TEXT,
    artifacts JSONB DEFAULT '[]',
    audit_log JSONB DEFAULT '[]',
    pending_confirmations JSONB DEFAULT '[]',
    priority INTEGER DEFAULT 5,
    timeout_minutes INTEGER DEFAULT 8,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 2,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP,
    worker_id VARCHAR(50),
    queue_name VARCHAR(50) DEFAULT 'default'
);

-- Add indexes
CREATE INDEX idx_inbox_user_status ON jarvis_inbox(user_id, status);
CREATE INDEX idx_inbox_created_at ON jarvis_inbox(created_at);
CREATE INDEX idx_brief_user_date ON daily_briefs(user_id, brief_date);
CREATE INDEX idx_tasks_user_state ON jarvis_tasks(user_id, state);
```

### Environment Configuration

Add to `.env`:

```bash
# Jarvis Mode
JARVIS_MODE=true
PRIVACY_STRICT=true
SOLO_USER_ID=1

# Nudging Policy
NUDGE_WINDOW=08:00-20:00
NUDGE_BATCH_INTERVAL_MIN=30
NUDGE_MAX_PER_DAY=8
DREAM_AT=02:30

# Task Limits
RESEARCH_MAX_MINUTES=8
```

### Integration with main_simple.py

Add these imports and route registrations:

```python
from app.routes.jarvis_inbox import router as inbox_router
from app.routes.daily_brief import router as brief_router
from app.services.solo_mode_service import solo_mode_service

# Register routes
app.include_router(inbox_router, prefix="/api")
app.include_router(brief_router, prefix="/api")

# Add health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": "jarvis" if solo_mode_service.is_solo_mode() else "sara",
        "user": "owner" if solo_mode_service.is_solo_mode() else "multi-tenant"
    }
```

## Phase 2: Memory & Dream (TODO)

### Planned Components

#### 1. Memory Scoring Service
- `app/services/memory_scorer.py` - Score episodes on write path
- Importance, affect, novelty, taskness scores
- Composite scoring for better recall

#### 2. Dream Pipeline
- `app/services/dream_consolidation.py` - Nightly memory processing
- HDBSCAN clustering of recent traces
- Summary generation and Neo4j graph updates
- Insight extraction to inbox

#### 3. Unified Recall
- `app/services/unified_recall.py` - Hybrid search across all memory
- Vector + keyword + graph + recency + importance ranking
- <250ms P50 latency with caching

### Database Changes
```sql
-- Augment existing episode/memory tables
ALTER TABLE episodes ADD COLUMN importance_score REAL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN affect_score REAL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN novelty_score REAL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN taskness_score REAL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN composite_score INTEGER DEFAULT 0;

-- Memory summaries from dream processing
CREATE TABLE memory_summaries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title VARCHAR(255) NOT NULL,
    body TEXT,
    timespan_start TIMESTAMP,
    timespan_end TIMESTAMP,
    source_episode_ids JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Phase 3: Sprite & Presence (TODO)

### Planned Components

#### 1. Presence Event System
- `app/services/presence_service.py` - SSE/WebSocket event broadcasting
- State machine: idle → listening → thinking → tooling → working
- Event types: CHAT_STREAM_START/END, TOOL_START/END, etc.

#### 2. Working Card
- Real-time progress updates for background tasks
- ETA calculations and progress percentages

### Frontend Integration
- Sprite component with Tailwind animations
- EventStream subscription to `/presence/stream`
- Working card overlay for active tasks

## Phase 4: Proactive Monitors (TODO)

### Planned Monitors

#### 1. Calendar Monitor
- `app/services/monitors/calendar_monitor.py`
- Double-bookings, unrealistic gaps, missing locations
- Runs every 30 minutes during active hours

#### 2. Reminder Monitor  
- `app/services/monitors/reminder_monitor.py`
- Overdue tasks, repeated snoozes, missing next steps
- Runs every hour

#### 3. Habit Monitor
- `app/services/monitors/habit_monitor.py` 
- Streak breaks, reward opportunities
- Daily processing

### Nudge Manager
- Batches monitor outputs every 30 minutes
- Respects quiet hours (20:00-08:00 default)
- Deduplication by `dedupe_key`
- Max 8 nudges per day

## Phase 5: Knowledge Garden (TODO)

### Planned Components

#### 1. Enhanced Document Ingestion
- `app/services/enhanced_doc_ingest.py`
- Web scraping with readability
- Intelligent chunking and embedding
- Source tracking and metadata

#### 2. Garden Visualization  
- Neo4j-based graph view
- Node clustering by recency and importance
- Interactive exploration UI

#### 3. Revisit Engine
- `app/services/revisit_engine.py`
- Decay-based importance scoring
- Identifies forgotten high-value content

## Phase 6: Autonomous Tasks (TODO)

### Planned Components

#### 1. Task Runner Infrastructure
- `app/services/task_runner/` - Redis RQ-based worker system
- Task specifications and execution engine
- Retry logic and timeout handling

#### 2. Multi-tool Research Tasks
- Background research using web search + knowledge graph
- Document analysis and comparison
- Summary generation with source citations

#### 3. Confirmation System
- High-impact actions require explicit approval
- Diff previews for destructive operations
- Complete audit trail

### Task Types
- **Research**: Multi-source information gathering
- **Draft**: Document/email generation with sources
- **Compare**: Side-by-side analysis of options
- **Summarize**: Condensed insights from large content
- **Analyze**: Pattern detection in data/conversations

## Frontend Integration

### New Components Needed

#### Phase 1
- `InboxPanel.tsx` - Notification inbox with badges
- `DailyBriefCard.tsx` - Morning briefing display
- Settings integration for Jarvis mode

#### Phase 3
- `JarvisSprite.tsx` - Animated presence indicator
- `WorkingCard.tsx` - Background task progress
- Presence event subscription hook

#### Phase 5
- Enhanced knowledge garden with revisit suggestions
- Document ingestion from search results

### API Integration

Update `config.ts` to include new endpoints:
```typescript
const API_ENDPOINTS = {
  // ... existing
  inbox: '/api/inbox',
  dailyBrief: '/api/brief/daily',
  presence: '/api/presence/stream',
  tasks: '/api/tasks'
};
```

## Cron Jobs & Scheduling

### Daily Brief Generation
```bash
# Generate daily brief at 6:30 AM
30 6 * * * cd /home/david/jarvis && python3 -c "from app.services.daily_brief_service import daily_brief_service; daily_brief_service.generate_brief_for_all_users()"
```

### Dream Processing  
```bash
# Run memory consolidation at 2:30 AM
30 2 * * * cd /home/david/jarvis && python3 -c "from app.services.dream_consolidation import run_dream_pipeline; run_dream_pipeline()"
```

## Testing Strategy

### Phase 1 Tests
- Inbox service unit tests with mocked nudge scenarios
- Daily brief generation with sample data
- Solo mode authentication bypass

### Integration Tests
- End-to-end inbox item creation → display → archive
- Daily brief caching and regeneration
- API contract testing

### Performance Tests
- Brief generation under 250ms (P95)
- Inbox queries with pagination
- Memory usage during dream processing

## Monitoring & Metrics

### Prometheus Metrics
```
# Inbox
jarvis_inbox_items_total{status}
jarvis_nudge_batches_total
jarvis_inbox_latency_ms

# Daily Brief  
jarvis_brief_generation_duration_ms
jarvis_brief_cache_hit_ratio
jarvis_brief_load_time_ms

# Tasks (Phase 6)
jarvis_task_duration_ms{kind}
jarvis_task_failures_total{kind}
```

### Alerting Rules
- Brief generation failures
- Inbox item creation rate anomalies  
- Dream processing timeouts
- Task queue backlog

## Next Steps

1. **Database Migration**: Run the SQL scripts to create new tables
2. **Environment Setup**: Add Jarvis environment variables
3. **Route Registration**: Integrate new routers in main_simple.py
4. **Frontend Integration**: Create React components for inbox and brief
5. **Cron Setup**: Schedule daily brief generation
6. **Testing**: Write unit tests for core services
7. **Documentation**: Update API documentation

Once Phase 1 is stable, proceed with Phase 2 (Memory & Dream) for the full autonomous experience.

## Troubleshooting

### Common Issues

#### Inbox Items Not Appearing
- Check `JARVIS_MODE=true` in environment
- Verify nudge priority is >= `NUDGE_PRIORITY_FLOOR`
- Check quiet hours configuration
- Review daily limit (`NUDGE_MAX_PER_DAY`)

#### Daily Brief Generation Slow
- Add database indexes on date columns
- Consider Redis caching for calendar/reminder queries
- Check LLM endpoint latency for insight generation

#### Solo Mode Authentication Issues
- Ensure `SOLO_USER_ID` matches existing user ID
- Check user table has `is_owner` column
- Verify auth middleware bypasses in solo mode
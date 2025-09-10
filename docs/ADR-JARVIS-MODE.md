# ADR: Jarvis Mode - Autonomous Personal AI Hub

**Status**: Proposed  
**Date**: 2025-09-08  
**Deciders**: System Architect  

## Context and Problem Statement

Sara currently operates as a multi-tenant AI assistant with authentication, user management, and collaborative features. However, the vision is to evolve Sara into "Jarvis" - a truly autonomous personal AI that proactively manages your digital life, learns from your patterns, and provides intelligent assistance without being explicitly asked.

The challenge is transforming Sara from a reactive chat assistant into a proactive digital companion while maintaining the existing technical foundation and user experience quality.

## Decision

We will implement **Jarvis Mode** as a comprehensive transformation of Sara through 6 phases:

1. **Foundations** - Solo user mode, unified inbox, daily briefings
2. **Memory & Dream** - Advanced memory consolidation and intelligent recall
3. **Sprite & Presence** - Visual feedback and activity awareness
4. **Proactive Monitoring** - Calendar, reminder, and habit monitoring
5. **Knowledge Garden** - Advanced document ingestion and knowledge management
6. **Autonomous Tasks** - Background multi-tool task execution with guardrails

## Architecture Overview

### Core Principles

- **Privacy-First**: Solo-user mode eliminates multi-tenancy complexity
- **Proactive Not Reactive**: Background monitors feed unified inbox instead of interrupting chat
- **Memory-Enhanced**: Everything gets consolidated into searchable, connected knowledge
- **Autonomous with Guardrails**: High-impact actions require explicit confirmation
- **Visual Presence**: Sprite system provides immediate feedback on system state

### System Components

#### 1. Solo User Mode
- Remove multi-tenant RBAC complexity
- Single owner profile (user_id=1)
- Simplified authentication flow
- `JARVIS_MODE=true` environment flag

#### 2. Unified Inbox System
```sql
-- New table: jarvis_inbox
CREATE TABLE jarvis_inbox (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  kind VARCHAR(20) CHECK (kind IN ('insight', 'alert', 'reminder', 'suggestion')),
  title VARCHAR(255) NOT NULL,
  body TEXT,
  source VARCHAR(50), -- e.g., 'calendar_monitor', 'dream'
  payload JSONB,
  priority INTEGER DEFAULT 5,
  created_at TIMESTAMP DEFAULT NOW(),
  status VARCHAR(10) DEFAULT 'new' CHECK (status IN ('new', 'read', 'archived'))
);
```

#### 3. Memory Consolidation Pipeline
- **Write-Path Scoring**: Each interaction gets importance/affect/novelty scores
- **Nightly Dream**: Cluster → Summarize → Link → Generate insights
- **Unified Recall**: Hybrid search across traces, summaries, and documents

#### 4. Presence & Sprite System
- State machine: `idle` → `listening` → `thinking` → `tooling` → `working`
- Server-sent events for real-time state updates
- Visual animations reflect system activity

#### 5. Proactive Monitors
- **Calendar Monitor**: Conflicts, gaps, missing locations
- **Reminder Monitor**: Overdue items, repeated snoozes
- **Habit Monitor**: Streak tracking, gap detection
- **Nudge Policy**: Batching, deduplication, quiet hours

#### 6. Background Task System
```sql
-- New table: jarvis_tasks
CREATE TABLE jarvis_tasks (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  kind VARCHAR(20), -- 'research', 'draft', 'compare', 'summarize'
  inputs JSONB,
  state VARCHAR(20) DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'waiting_confirm', 'done', 'failed')),
  progress INTEGER DEFAULT 0,
  result JSONB,
  audit_log JSONB DEFAULT '[]',
  created_at TIMESTAMP DEFAULT NOW()
);
```

### API Design

#### Inbox APIs
- `GET /inbox?status=new|read|archived&limit=20&offset=0`
- `POST /inbox/:id/read`
- `POST /inbox/:id/archive`
- `POST /inbox` (internal use)

#### Daily Brief
- `GET /brief/daily?t=YYYY-MM-DD`
- Response format: `{sections: [{id, title, items: [...]}]}`

#### Memory & Recall
- `GET /memory/recall?q=&k=10&hybrid=true&time_from=&time_to=`
- `POST /memory/consolidate/run` (admin)

#### Tasks & Background Work
- `POST /tasks` `{kind, inputs}` → `{task_id}`
- `GET /tasks/:id` → task details and progress
- `POST /tasks/:id/confirm` → approve pending actions

#### Presence
- `GET /presence/stream` (SSE endpoint)
- `GET /work/status` → active background jobs

### Configuration

#### Environment Variables
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

### Data Flow

1. **Input**: User interactions, calendar events, external data sources
2. **Scoring**: Real-time importance/novelty scoring on write
3. **Storage**: Traces in PostgreSQL with pgvector embeddings
4. **Consolidation**: Nightly clustering and summarization
5. **Monitoring**: Background processes check for patterns and issues
6. **Nudging**: Insights and alerts flow to unified inbox
7. **Presentation**: Daily brief, sprite feedback, and contextual assistance

### Migration Strategy

#### Phase 1: Foundations (Week 1-2)
- Solo mode database migration
- Inbox system implementation
- Daily brief generation

#### Phase 2: Memory Enhancement (Week 2-3)
- Memory scoring implementation
- Dream pipeline development
- Unified recall API

#### Phase 3-6: Progressive Enhancement (Week 3-8)
- Sprite system and presence
- Proactive monitors
- Knowledge garden improvements
- Autonomous task system

## Consequences

### Positive
- **Reduced Cognitive Load**: Proactive assistance reduces need to remember and ask
- **Better Context**: Memory consolidation provides richer, more relevant responses
- **Personalization**: Solo-user mode enables deeper customization and privacy
- **Scalable Intelligence**: Background processing enables complex multi-step tasks
- **Visual Feedback**: Sprite system provides immediate understanding of system state

### Negative
- **Complexity**: Significant increase in system complexity and moving parts
- **Resource Usage**: Background processing increases CPU/memory requirements
- **Development Time**: 6-8 weeks of focused development effort
- **Testing Challenges**: Proactive systems are harder to test comprehensively
- **Privacy Concerns**: More data processing requires careful privacy consideration

### Risks and Mitigations

#### Risk: System Becomes Too "Chatty"
- **Mitigation**: Strict nudge policies, batching, and quiet hours
- **Metric**: Track nudge frequency and user archive rates

#### Risk: Background Tasks Consume Too Many Resources
- **Mitigation**: Task timeouts, resource limits, queue prioritization
- **Metric**: Monitor CPU/memory usage and task completion rates

#### Risk: Memory Consolidation Produces Low-Quality Insights
- **Mitigation**: Scoring thresholds, user feedback loops, manual curation
- **Metric**: Track insight usefulness ratings and archive rates

#### Risk: User Loses Trust Due to Autonomous Actions
- **Mitigation**: Comprehensive audit logging, confirmation workflows for high-impact actions
- **Metric**: User approval rates for autonomous actions

## Implementation Plan

### Phase 1 (Immediate - Week 1)
```
✓ Solo mode database migration
✓ Inbox system (DB + API + UI)  
✓ Daily brief generation with cron scheduling
✓ Basic environment configuration
```

### Phase 2 (Week 2)
```
→ Memory scoring service implementation
→ Dream pipeline (consolidation + summarization)
→ Unified recall API with hybrid ranking
→ Neo4j integration for knowledge graph
```

### Phase 3 (Week 3)
```
→ Presence event system (SSE/WebSocket)
→ Sprite state machine and animations
→ Working card for background tasks
```

### Phase 4 (Week 4-5)
```
→ Nudge manager with policies
→ Calendar monitoring service
→ Reminder slippage detection
→ Habit tracking integration
```

### Phase 5 (Week 6)
```
→ Document ingestion pipeline
→ Knowledge garden visualization
→ Revisit suggestions algorithm
```

### Phase 6 (Week 7-8)
```
→ Task runner infrastructure
→ Autonomous action confirmation system
→ Audit logging and export
→ End-to-end testing and optimization
```

## Success Metrics

### Performance
- P95 latency < 400ms for core APIs (/inbox, /brief/daily, /memory/recall)
- Dream pipeline completes within 10 minutes nightly
- Background tasks respect resource limits

### User Experience
- Daily brief loads by 06:35 local time
- Inbox maintains 1-3 items per batch average
- Sprite state transitions without flickering
- >85% user approval rate for autonomous actions

### System Health
- >99% uptime for core services
- <5% error rate for embedding operations
- Task queue processes without backlog accumulation

## Monitoring and Observability

### Metrics (Prometheus)
```
# Core System
jarvis_inbox_items_total{status}
jarvis_nudge_batches_total
jarvis_dream_runtime_seconds
jarvis_task_duration_seconds{kind}

# Performance
jarvis_api_latency_ms{endpoint}
jarvis_memory_recall_cache_hit_ratio
jarvis_embedding_error_rate

# User Engagement
jarvis_user_action_approval_rate
jarvis_inbox_archive_rate
jarvis_brief_load_time_seconds
```

### Alerting
- Dream pipeline failures
- Task queue backlog > 100 items
- API latency P95 > 1000ms
- Embedding service error rate > 10%

## Future Considerations

- **Multi-Device Sync**: Mobile app integration
- **Voice Interface**: Speech-to-text and text-to-speech
- **External Integrations**: Calendar sync, email monitoring, IoT device control
- **Advanced ML**: Custom model fine-tuning on user data
- **Collaboration Mode**: Selective multi-user features for family/team scenarios

---

This ADR documents the comprehensive transformation from Sara (reactive assistant) to Jarvis (autonomous AI companion) while maintaining the existing technical foundation and ensuring a smooth transition path.
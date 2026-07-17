# Sara Cognitive Architecture - Integration Plan

## Overview

This document details how to integrate the cognitive architecture into Sara's existing system without disruption. The goal is seamless integration that makes Sara feel like she always had these capabilities.

---

## Key Decisions

### 1. Task Queue: Celery vs Existing Workers

**Decision: Adopt Celery**

**Reasoning:**
- Sara's existing workers (`backend/app/workers/`) are ad-hoc Python scripts without a unified scheduler
- Celery provides: beat scheduling, distributed execution, monitoring, retry logic, rate limiting
- The existing workers can be migrated incrementally to Celery tasks
- Redis is already running and can serve as the Celery broker

**Migration Path:**
1. Add Celery to the backend container
2. Create Celery app configuration
3. Migrate existing workers one at a time
4. Add new cognitive architecture workers

### 2. Raw Buffer Storage: Redis Streams vs TimescaleDB

**Decision: Redis Streams**

**Reasoning:**
- Redis is already running and configured
- Redis Streams are designed for exactly this use case (append-only event logs with TTL)
- No new infrastructure needed
- Sufficient for 48-72 hour retention with automatic expiry
- TimescaleDB would add complexity without clear benefit

**Implementation:**
- Stream per input type: `raw_buffer:audio`, `raw_buffer:visual`, `raw_buffer:screen`, etc.
- Use `XTRIM` with `MAXLEN` for automatic size limits
- Use consumer groups for consolidation agent

### 3. Working Memory: Redis Structure

**Decision: Redis Hash + Sorted Sets**

**Reasoning:**
- Already have Redis
- Fast read/write for ephemeral data
- Existing pattern used for `user:{id}:memory:recent`

**Structure:**
```
working_memory:{user_id}:context          # Hash - current context
working_memory:{user_id}:threads          # Sorted set - active threads
working_memory:{user_id}:actions          # Sorted set - pending actions
working_memory:{user_id}:user_state       # Hash - inferred user state
working_memory:{user_id}:system_state     # Hash - system health
```

### 4. Input Stream Processing

**Decision: Start with Text + Screen, Add Audio/Visual in Phase 1b**

**Reasoning:**
- Text and notifications are already flowing through the system
- Screen capture can run locally on the backend server
- Audio/visual require GPU cluster or Jetson for processing
- Better to ship a working Phase 1 with core functionality, then add sensors

**Hardware Assignment:**
- **GPU Cluster (10.185.1.8)**: Whisper transcription, VLLM scene analysis
- **Jetson (10.185.1.155)**: Local visual processing (YOLO, posture detection)
- **Backend Server**: Screen capture, text processing, consolidation

---

## Existing Component Mapping

### Memory Systems (Already Exist)

| New Concept | Existing Implementation | Integration Approach |
|-------------|------------------------|---------------------|
| Short-term memory | Redis `user:{id}:memory:recent` | Extend to working memory structure |
| Episodic memory | `memory_trace` + `memory_embedding` tables | Use as-is, add cognitive metadata |
| Semantic memory | `Episode` model with embeddings | Use as-is |
| Memory retrieval | `memory_service.intelligent_memory_search()` | Add working memory context |
| Memory consolidation | `dream_consolidation.py` | Wrap with consolidation agent |

### Context Systems (Already Exist)

| New Concept | Existing Implementation | Integration Approach |
|-------------|------------------------|---------------------|
| Context building | `context_builder.py` | Inject working memory |
| Intent classification | `intent_classifier.py` | Add cognitive context |
| Context routing | `context_router.py` | Consider working memory |

### Background Processing (Needs Migration)

| New Concept | Existing Implementation | Integration Approach |
|-------------|------------------------|---------------------|
| Health monitoring | `health_watchdog.py` | Migrate to Celery task |
| Pattern detection | `pattern_discovery_worker.py` | Migrate to Celery task |
| Habit processing | `habit_worker_coordinator.py` | Migrate to Celery task |
| Daily briefings | `daily_brief/scheduler.py` | Integrate with anticipation worker |

---

## Database Migrations Required

### Phase 1 Migrations

```sql
-- 1. Raw buffer metadata (streams are in Redis, but we need audit trail)
CREATE TABLE raw_buffer_stats (
    id SERIAL PRIMARY KEY,
    stream_type VARCHAR(50) NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    entries_count INT NOT NULL,
    processed_count INT NOT NULL,
    discarded_count INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. Consolidation run logs
CREATE TABLE consolidation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    raw_entries_processed INT DEFAULT 0,
    entries_kept INT DEFAULT 0,
    entries_discarded INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. Discard log for reflection auditing
CREATE TABLE consolidation_discards (
    id SERIAL PRIMARY KEY,
    consolidation_run_id UUID REFERENCES consolidation_runs(id),
    raw_entry_id VARCHAR(255) NOT NULL,
    stream_type VARCHAR(50) NOT NULL,
    content_preview TEXT,
    relevance_score FLOAT,
    discard_reason VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. Consolidation config (modifiable by reflection agent)
CREATE TABLE consolidation_config (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    config_key VARCHAR(100) NOT NULL,
    config_value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(50),
    UNIQUE(user_id, config_key)
);

-- Index for efficient queries
CREATE INDEX idx_consolidation_runs_user_time ON consolidation_runs(user_id, started_at DESC);
CREATE INDEX idx_consolidation_discards_run ON consolidation_discards(consolidation_run_id);
```

### Phase 2 Migrations (Karma)

```sql
-- Karma tables as specified in phase-2-karma.md
-- Will be added when Phase 1 is complete
```

---

## File Structure

Following existing conventions, new files will be organized as:

```
backend/app/
  services/
    cognitive/                    # NEW: Cognitive architecture services
      __init__.py
      raw_buffer.py              # Raw buffer management
      consolidation_agent.py     # Consolidation logic
      consolidation_config.py    # Config management
      working_memory.py          # Working memory manager
      user_state.py              # User state inference

  workers/                        # MIGRATE: To Celery tasks
    celery_app.py                # NEW: Celery application
    celery_config.py             # NEW: Celery configuration

  tasks/                          # NEW: Celery task definitions
    __init__.py
    input_processing.py          # Audio, visual, screen processing
    consolidation.py             # Consolidation sweep task
    working_memory.py            # Memory management tasks
    health.py                    # System health checks

  models/
    cognitive.py                 # Extend existing with new models

  routes/
    cognitive.py                 # NEW: Cognitive system endpoints

  schemas/
    cognitive.py                 # NEW: Pydantic schemas
```

---

## Integration Points

### 1. Chat Endpoint (`main_simple.py` ~line 8953)

**Current Flow:**
```python
# Memory retrieval
relevant_memories = await intelligent_memory_search(...)
# Context injection
memory_context = format_memories(relevant_memories)
# LLM call
response = await llm_call(messages + memory_context)
```

**New Flow:**
```python
# Get working memory snapshot (NEW)
working_mem = await working_memory.get_snapshot(user_id)

# Memory retrieval (unchanged)
relevant_memories = await intelligent_memory_search(...)

# Context injection (MODIFIED)
memory_context = format_memories(relevant_memories)
cognitive_context = format_working_memory(working_mem)  # NEW

# LLM call (MODIFIED)
response = await llm_call(messages + memory_context + cognitive_context)

# Post-processing (NEW)
await working_memory.update_from_response(user_id, response)
```

### 2. Memory Storage (`memory_service.py`)

**Integration Point:** `store_trace()` method

**Change:** After storing to database, also push to raw buffer for consolidation awareness:
```python
async def store_trace(self, ...):
    # Existing logic
    trace = await db.insert(memory_trace, ...)

    # NEW: Also record in raw buffer stream
    await raw_buffer.add_entry(
        stream_type="text",
        content=trace.content,
        source="memory_trace",
        trace_id=trace.id
    )
```

### 3. System Prompt (`main_simple.py` ~line 9214)

**Current:** Static system prompt

**New:** Inject working memory awareness:
```python
def get_system_prompt(assistant_name, user_email, working_memory=None):
    base_prompt = f"You are {assistant_name}..."

    if working_memory:
        base_prompt += f"""
<working_memory>
{format_working_memory(working_memory)}
</working_memory>
"""
    return base_prompt
```

---

## Implementation Sequence

### Phase 1a: Core Infrastructure (Week 1)

1. **Celery Setup**
   - Add Celery to requirements.txt
   - Create `celery_app.py` with Redis broker
   - Add Celery worker to docker-compose
   - Create basic health check task

2. **Raw Buffer Implementation**
   - Create `raw_buffer.py` service
   - Implement Redis Streams wrapper
   - Add TTL enforcement task
   - Create text stream handler (existing inputs)

3. **Working Memory Structure**
   - Create `working_memory.py` service
   - Implement Redis-backed storage
   - Add capacity management
   - Create snapshot/update methods

### Phase 1b: Consolidation Agent (Week 2)

4. **Consolidation Logic**
   - Create `consolidation_agent.py`
   - Implement rule-based consolidation
   - Add configurable priority rules
   - Create discard logging

5. **Integration with Sara**
   - Modify chat endpoint for working memory
   - Update system prompt with cognitive context
   - Add working memory update on response

6. **Database Migrations**
   - Create Alembic migrations
   - Deploy consolidation tables
   - Seed default config

### Phase 1c: Input Handlers (Week 3)

7. **Screen Capture Handler**
   - Create screen capture service
   - Add VLLM integration for analysis
   - Connect to raw buffer

8. **Notification/Event Handler**
   - Capture system notifications
   - Calendar event integration
   - Home Assistant events

9. **Testing**
   - Unit tests for each component
   - Integration tests for full flow
   - Load testing for buffer/consolidation

### Phase 1d: Sensory Processing (Optional Extension)

10. **Audio Handler** (GPU Cluster)
    - Whisper transcription service
    - Speaker diarization
    - Stream to raw buffer

11. **Visual Handler** (Jetson)
    - YOLO object detection
    - Posture/presence detection
    - Periodic scene analysis

---

## Configuration Defaults

```yaml
# Default consolidation configuration
consolidation:
  window_seconds: 60
  grouping_threshold_ms: 5000
  relevance_threshold: 0.3

  priority_rules:
    - pattern: "source:user_message"
      boost: 0.5
    - pattern: "source:notification"
      boost: 0.3
    - pattern: "source:calendar"
      boost: 0.4

  context_modifiers:
    sleeping:
      relevance_threshold: 0.7
    working:
      relevance_threshold: 0.4
      priority_boost:
        - pattern: "source:calendar"
          boost: 0.3

# Working memory limits
working_memory:
  current_context_segments: 50
  active_threads: 10
  pending_actions: 20
  ttl_seconds: 3600  # 1 hour for most items
```

---

## Risk Mitigation

### Risk 1: Disrupting Existing Functionality

**Mitigation:**
- All new features behind feature flags
- Existing tests must pass before deployment
- Gradual rollout with monitoring

### Risk 2: Redis Overload

**Mitigation:**
- Strict TTL on all raw buffer entries
- Size limits on working memory
- Monitor Redis memory usage

### Risk 3: Celery Worker Failures

**Mitigation:**
- Auto-restart on failure
- Health monitoring
- Graceful degradation if workers down

### Risk 4: LLM API Rate Limits

**Mitigation:**
- Resource budgets in worker coordinator
- Batch processing where possible
- Fallback to simpler models under load

---

## Success Metrics

### Phase 1 Complete When:

1. **Raw Buffer**: Text inputs flowing through buffer with 48hr retention
2. **Consolidation**: Running every 60s, producing valid output
3. **Working Memory**: Integrated with chat endpoint
4. **Discard Log**: Complete audit trail for reflection
5. **Tests**: All unit and integration tests passing
6. **Regression**: Existing functionality unaffected
7. **Documentation**: Updated to reflect new architecture

---

## Next Steps

1. Review and approve this integration plan
2. Set up Celery in the backend container
3. Implement raw buffer with Redis Streams
4. Build working memory service
5. Create consolidation agent
6. Integrate with chat endpoint
7. Deploy and test

---

## Hardware Reference

For later phases requiring sensory input:

- **GPU Cluster**: `ssh david@10.185.1.8` - Whisper, VLLM, heavy inference
- **Jetson**: `ssh david@10.185.1.155` - Edge processing, YOLO, real-time vision

Both available for Phase 1c/1d sensory handler implementation.

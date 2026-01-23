# Phase 1: Foundation — Sara Cognitive Architecture Integration

## Mission Statement

You are integrating a new cognitive architecture into an **existing** Sara AI assistant system. This is NOT a greenfield build. You must study the existing codebase, understand its patterns, conventions, and structure, then seamlessly weave these new capabilities into what already exists. The end result should feel like Sara always had these capabilities—not like something was bolted on.

---

## Critical Integration Requirements

### Before Writing Any Code

1. **Map the existing codebase thoroughly**
   - Identify all existing services, modules, and their responsibilities
   - Document the current data flow and message patterns
   - Understand existing database schemas and models
   - Note coding conventions, naming patterns, and architectural decisions
   - Identify existing configuration management approaches

2. **Find integration points**
   - Where does Sara currently receive inputs?
   - How does Sara currently process context?
   - What existing memory systems are in place?
   - How are background tasks currently handled (if at all)?

3. **Plan the integration path**
   - Write a detailed integration plan before coding
   - Identify which existing components need modification vs. extension
   - Plan database migrations if schema changes are needed
   - Design for backward compatibility where possible

---

## Phase 1 Deliverables

### 1. Raw Buffer Ingestion System

**Purpose:** Capture and store all incoming sensory data with timestamps for later processing and audit.

**Requirements:**

#### Input Stream Handlers

Create handlers for each input type that integrate with existing input mechanisms:

| Stream | Source | Processing | Storage Format |
|--------|--------|------------|----------------|
| Audio | Existing STT pipeline or new microphone input | Whisper transcription → diarization → speaker tagging | `{timestamp, transcript, speakers[], confidence, raw_audio_ref}` |
| Visual | Camera feed / screen capture | YOLO object detection, posture detection, periodic VLLM scene analysis | `{timestamp, objects[], postures[], scene_summary, frame_ref}` |
| Screen | Periodic screenshots | VLLM analysis of screen content | `{timestamp, active_app, content_summary, ocr_text, screenshot_ref}` |
| Text | Notifications, calendar, system events | Tag by source and type | `{timestamp, source, type, content, metadata}` |
| Environmental | Home Assistant or sensor APIs | State change detection | `{timestamp, entity_id, old_state, new_state, attributes}` |

#### Raw Buffer Storage

**Technology:** Use Redis Streams or TimescaleDB (determine based on existing stack)

**Schema Design:**
```
raw_buffer:
  stream_type: enum(audio, visual, screen, text, environmental)
  timestamp: datetime (UTC, microsecond precision)
  data: jsonb
  raw_reference: string (S3/Minio path if binary data)
  processed: boolean (default false)
  retention_expires: datetime (48-72 hours from creation)
```

**Requirements:**
- All entries must have microsecond-precision timestamps
- Binary data (audio files, images) stored in object storage with reference in buffer
- Automatic TTL-based cleanup (configurable, default 48-72 hours)
- Indexed by timestamp and stream_type for efficient windowed queries

#### Integration Points

- Must integrate with any existing input pipelines (don't duplicate)
- If Sara has existing transcription, hook into it—don't create parallel system
- If there's an existing event bus or message queue, use it

---

### 2. Basic Consolidation Agent

**Purpose:** Compress the raw input firehose into digestible context packets for Sara.

**Initial Implementation:** Rule-based (ML-enhanced consolidation comes in later phases)

#### Processing Logic

```
Every 30-60 seconds (configurable):
  1. Query raw buffer for unprocessed entries in time window
  2. Group entries by timestamp proximity (configurable threshold, e.g., 5 seconds)
  3. For each group:
     a. Deduplicate (same object detected multiple times, repeated silence, etc.)
     b. Calculate relevance scores based on:
        - Change detection (new vs. previously seen)
        - Configured priority rules (your voice > ambient noise)
        - Current context flags (home/away, working/relaxing, etc.)
     c. Discard entries below relevance threshold
     d. Summarize where appropriate (multiple similar detections → single summary)
     e. Preserve detail for high-relevance items
  4. Output consolidated context packet
  5. Log discarded items with reasons (for reflection audit)
  6. Mark raw entries as processed
```

#### Consolidation Agent Configuration

Must be stored in a modifiable location (database or config file) because the Reflection Agent will propose changes later:

```yaml
consolidation:
  window_seconds: 60
  grouping_threshold_ms: 5000
  relevance_threshold: 0.3
  
  priority_rules:
    - pattern: "speaker:david"
      boost: 0.5
    - pattern: "type:notification"
      boost: 0.3
    - pattern: "object:person"
      boost: 0.2
      
  summarization_rules:
    - condition: "repeated_object_detection"
      action: "consolidate_to_single"
    - condition: "silence_duration > 30s"
      action: "discard"
      
  context_modifiers:
    sleeping:
      relevance_threshold: 0.7  # More aggressive filtering when sleeping
    working:
      priority_boost:
        - pattern: "app:slack"
          boost: 0.3
```

#### Output Format

```
consolidated_context:
  timestamp: datetime
  window_start: datetime
  window_end: datetime
  segments:
    - type: audio | visual | screen | text | environmental
      timestamp: datetime
      content: string
      relevance_score: float
      source_raw_ids: [ids]  # Traceability to raw buffer
      confidence: float
      
  statistics:
    total_raw_entries: int
    entries_kept: int
    entries_discarded: int
```

#### Discard Log

For reflection agent auditing:

```
discard_log:
  consolidation_run_id: uuid
  timestamp: datetime
  discarded_entries:
    - raw_id: string
      reason: string (below_threshold | duplicate | summarized | rule:X)
      relevance_score: float
      content_preview: string (truncated)
```

---

### 3. Working Memory Structure

**Purpose:** Sara's conscious scratchpad—what she's actively aware of right now.

**Technology:** Redis (for speed) with structured keys

#### Schema

```
working_memory:
  # Current consolidated context
  current_context:
    timestamp: datetime
    segments: []  # From consolidation agent
    
  # Active conversation threads
  active_threads:
    - thread_id: string
      topic: string
      participants: []
      last_updated: datetime
      status: active | waiting | resolved
      summary: string
      
  # Pending actions Sara is considering or tracking
  pending_actions:
    - action_id: string
      type: notify | remind | execute | ask | observe
      priority: float
      context: string
      created_at: datetime
      deadline: datetime (optional)
      
  # Inferred state about the user
  user_state:
    inferred_activity: string
    availability: available | busy | dnd | away | sleeping
    location: home | work | traveling | unknown
    last_interaction: datetime
    mood_signals: [] (optional, inferred from inputs)
    
  # System state
  system_state:
    last_consolidation: datetime
    buffer_health: healthy | lagging | error
    active_workers: []
```

#### Capacity Management

Working memory must be size-limited to force prioritization:

```python
WORKING_MEMORY_LIMITS = {
    "current_context_segments": 50,  # Max items in current context
    "active_threads": 10,
    "pending_actions": 20,
}

# When limit exceeded:
# 1. Sort by relevance/priority
# 2. Remove lowest-scoring items
# 3. Optionally: Write important evicted items to short-term episodic memory
```

#### Integration with Existing Memory

- Working memory is EPHEMERAL—it resets or decays
- Important items must be explicitly written to Sara's existing long-term memory system
- Identify how Sara currently handles memory (Neo4j? Postgres? Vector DB?) and create bridge

---

### 4. Sara Receiving Consolidated Context

**Purpose:** Modify Sara's main processing loop to incorporate the new context stream.

#### Integration Approach

**DO NOT** create a separate Sara. Modify the existing Sara to:

1. **On each invocation (reactive or proactive):**
   - Pull current working memory snapshot
   - Include in context alongside existing memory retrieval
   - Process with awareness of recent environmental context

2. **Context injection format:**
   ```
   <working_memory>
     <current_context>
       [Last 60 seconds of consolidated sensory data]
     </current_context>
     
     <active_threads>
       [Ongoing conversation threads and their status]
     </active_threads>
     
     <pending_actions>
       [Things Sara is tracking or considering]
     </pending_actions>
     
     <user_state>
       [Inferred information about David's current state]
     </user_state>
   </working_memory>
   ```

3. **Sara's prompt modifications:**
   - Add instructions for how to interpret working memory
   - Add instructions for when to write back to working memory
   - Add instructions for when to flag items for reflection

#### Response Handling

Sara's responses should now be able to:
- Update working memory (add pending actions, update thread status)
- Flag items for reflection review
- Trigger immediate actions based on context

---

## Technical Requirements

### Celery Integration

**Add Celery for background task management:**

1. **Install and configure Celery** with Redis as broker (or integrate with existing message queue)

2. **Create task structure:**
   ```
   tasks/
     __init__.py
     input_processing.py      # Audio, visual, screen processing tasks
     consolidation.py         # Consolidation agent tasks
     working_memory.py        # Memory management tasks
   ```

3. **Initial workers:**
   - `process_audio_input` — Handle incoming audio, run through Whisper + diarization
   - `process_visual_input` — Handle camera frames, run YOLO
   - `process_screen_capture` — Periodic screenshot analysis
   - `run_consolidation` — Periodic consolidation sweep
   - `cleanup_raw_buffer` — TTL enforcement

4. **Beat schedule (periodic tasks):**
   ```python
   CELERY_BEAT_SCHEDULE = {
       'consolidation-sweep': {
           'task': 'tasks.consolidation.run_consolidation',
           'schedule': 60.0,  # Every 60 seconds
       },
       'buffer-cleanup': {
           'task': 'tasks.working_memory.cleanup_expired',
           'schedule': 300.0,  # Every 5 minutes
       },
   }
   ```

---

## Database Migrations

If schema changes are needed:

1. Use existing migration tool (Alembic? Django migrations? Prisma?)
2. Create migrations for:
   - Raw buffer tables/collections
   - Consolidation config storage
   - Discard log tables
   - Working memory structures (if persisted)
3. Migrations must be reversible
4. Test migrations on copy of production data structure

---

## Testing Requirements

### Unit Tests

Create tests for:

1. **Input handlers:**
   - Audio transcription pipeline produces correct format
   - Visual processing extracts expected objects
   - Timestamp precision is maintained

2. **Consolidation logic:**
   - Grouping by timestamp works correctly
   - Relevance scoring follows configured rules
   - Deduplication removes true duplicates only
   - Discard logging captures all discards

3. **Working memory:**
   - Capacity limits enforced
   - Eviction prioritizes correctly
   - State updates are atomic

### Integration Tests

1. **End-to-end flow:**
   - Raw input → Buffer → Consolidation → Working Memory → Sara receives
   - Verify no data loss in happy path
   - Verify graceful degradation under load

2. **Existing functionality preservation:**
   - All existing Sara tests still pass
   - Existing conversation flows work unchanged
   - Memory retrieval still works

### Load Tests

1. Simulate realistic input volumes
2. Verify buffer doesn't grow unbounded
3. Verify consolidation keeps up with input rate

---

## Completion Criteria

**This phase is NOT complete until:**

- [ ] All input stream handlers are implemented and tested
- [ ] Raw buffer is storing data with correct timestamps and TTL
- [ ] Consolidation agent runs on schedule and produces valid output
- [ ] Discard log captures all consolidation decisions
- [ ] Working memory structure is implemented with capacity management
- [ ] Sara's main loop successfully receives and uses consolidated context
- [ ] Celery is integrated and workers are running
- [ ] All existing Sara functionality still works (regression tests pass)
- [ ] No stubs, TODOs, or placeholder implementations remain
- [ ] Integration tests demonstrate full data flow
- [ ] Code follows existing project conventions
- [ ] Documentation updated to reflect new architecture

---

## Files to Create/Modify

### New Files (likely, adjust to existing structure)
```
services/
  input_processing/
    __init__.py
    audio_handler.py
    visual_handler.py
    screen_handler.py
    text_handler.py
    environmental_handler.py
    
  consolidation/
    __init__.py
    agent.py
    config.py
    rules.py
    
  working_memory/
    __init__.py
    manager.py
    schemas.py
    
models/
  raw_buffer.py
  consolidation_log.py
  working_memory.py
  
tasks/
  __init__.py
  celery_config.py
  input_tasks.py
  consolidation_tasks.py
  memory_tasks.py
  
tests/
  test_input_processing.py
  test_consolidation.py
  test_working_memory.py
  test_integration_phase1.py
```

### Modified Files (identify actual files in existing codebase)
```
- Sara's main processing module (add working memory injection)
- Configuration files (add new service configs)
- Requirements/dependencies (add Celery, Redis clients, etc.)
- Docker compose (if used, add workers)
```

---

## Notes for Claude

1. **Study first, code second.** Spend significant time understanding the existing system before making changes.

2. **Ask questions if unclear.** If the existing architecture doesn't match assumptions, pause and clarify.

3. **Small commits, clear messages.** Each logical change should be its own commit with clear description.

4. **Test continuously.** Don't wait until the end to test. Test each component as you build it.

5. **Integration is the goal.** A feature that works in isolation but breaks existing functionality is a failure.

6. **No shortcuts.** Every TODO, stub, or "will implement later" is technical debt. Finish what you start.

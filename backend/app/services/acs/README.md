# ACS — Autonomous Cognition System

Sara's independent thinking engine. When David isn't chatting, Sara runs autonomous sessions — researching topics, writing notes, building an interest graph, maintaining a self-model, and executing daily plans. The system is fully self-directed with structured daily planning, multi-modal cognitive sessions, and nightly self-auditing.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [State Machine](#state-machine)
- [Cognitive Modes](#cognitive-modes)
- [Daily Lifecycle](#daily-lifecycle)
- [Session Loop](#session-loop)
- [Plan Execution Engine](#plan-execution-engine)
- [Interest Graph](#interest-graph)
- [Self-Model](#self-model)
- [Tool System](#tool-system)
- [Context Assembly](#context-assembly)
- [Prompt System](#prompt-system)
- [Audit System](#audit-system)
- [Directives](#directives)
- [Show-David Buffer](#show-david-buffer)
- [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
- [Infrastructure](#infrastructure)
- [Database Schema](#database-schema)
- [Redis Keys](#redis-keys)
- [API Endpoints](#api-endpoints)
- [Celery Tasks & Schedule](#celery-tasks--schedule)
- [Configuration](#configuration)
- [File Map](#file-map)

---

## Architecture Overview

```
                    David chatting?
                         |
                    yes /   \ no
                       /     \
              CONVERSATIONAL  COOLDOWN (2 min)
                                  |
                              AUTONOMOUS
                                  |
                    ┌─────────────┼──────────────┐
                    |             |               |
              Mode Selector   Plan Items    Interest Graph
                    |             |               |
              ┌─────┴─────┐   Execution     Fascination
              |     |     |   Engine        Decay / Dedup
         Explore Consol Reflect              |
              |     |     |            Neo4j + pgvector
              └─────┴─────┘
                    |
              Session Loop
              (LLM + Tools)
                    |
           ┌───────┼────────┐
           |       |        |
        VM/Shell  Notes   Self-Model
        Containers Journal  Updates
```

**Stack:** FastAPI backend, PostgreSQL (pgvector), Redis (state/pubsub), Neo4j (graph mirror), Celery (scheduling), Qwen3.5-122B (primary LLM), Qwen3.5-35B (fallback).

**Scale:** ~11,000 lines across 28 files, 9 database tables, 26 tools, 15 context blocks.

---

## State Machine

**File:** `state_machine.py` (312 lines)

Four states managed in Redis (`sara:acs:state:{user_id}`):

| State | Description |
|-------|-------------|
| `AUTONOMOUS` | Session running — LLM loop active on VM |
| `PAUSING` | Graceful interrupt (David started chatting) |
| `CONVERSATIONAL` | David actively chatting — ACS fully stopped |
| `COOLDOWN` | Buffer after chat ends before next session (default 2 min) |

**Valid transitions:**
```
AUTONOMOUS   → PAUSING, COOLDOWN, CONVERSATIONAL
PAUSING      → CONVERSATIONAL, COOLDOWN
CONVERSATIONAL → COOLDOWN, AUTONOMOUS
COOLDOWN     → AUTONOMOUS, CONVERSATIONAL
```

**Key hooks:**
- `on_chat_started()` — transitions to PAUSING, fires curiosity extraction on chat end
- `on_chat_ended()` — enters COOLDOWN, extracts curiosities from conversation
- `signal_chat_active()` — sets 120s TTL flag so sessions yield LLM capacity
- `is_cooldown_expired()` — lifecycle check uses this to auto-start sessions

**Defaults:**
- Cooldown: 2 minutes
- Max session duration: 60 minutes (v1), 360 minutes / 6 hours (v2 ceiling)
- Model: `Qwen3.5-122B-A10B`

---

## Cognitive Modes

**File:** `mode_selector.py` (416 lines)

Each session runs in one of four modes, selected by a two-phase process:

### Modes

| Mode | Duration | Purpose |
|------|----------|---------|
| **Exploration** | 60 min | Research new topics, follow curiosity, run experiments |
| **Consolidation** | 45 min | Merge duplicate notes, build interest graph edges, organize |
| **Reflection** | 30 min | Self-model updates, trajectory assessment, archive stale interests |
| **Execution** | 90 min | Work through daily plan items with success criteria |

### Selection Algorithm

```
select_mode(user_id) → (mode, plan_item_id)

Phase 0: Plan Item Check
  ├─ David's requests (priority >= 85) → ALWAYS execution (bypass ratio)
  ├─ Normal items + ratio < 0.7 → execution
  └─ Ratio >= 0.7 → fall through to free mode

Phase 1: Heuristic Signals
  ├─ exploration_signal  = frontier_nodes / total_active
  ├─ consolidation_signal = unconnected_recent_nodes / total_active
  ├─ reflection_signal   = days_since_last_reflection / 7
  ├─ bridge_opportunities = count of similar but unlinked nodes
  ├─ pending_david_requests = david_request nodes with depth < 0.5
  ├─ topic_saturation    = low folder diversity in recent notes
  └─ calendar_events_24h = busy schedule → boost consolidation

Phase 2: LLM Decision (temp=0.3)
  ├─ Receives all signals + blocked modes
  ├─ Outputs JSON: {"mode": "...", "reason": "..."}
  └─ Fallback: heuristic scoring with boosts/penalties
```

**Repeat limit:** Same mode blocked after 2 consecutive uses (`acs_v2_mode_max_repeat`).

**Execution ratio:** 70% sessions dedicated to plan execution, 30% free exploration/consolidation/reflection. David's explicit requests always bypass this ratio.

---

## Daily Lifecycle

All times are Eastern Time (Celery configured with `America/New_York`).

| Time | Task | What Happens |
|------|------|--------------|
| **3:00 AM** | Nightly memory consolidation | Episode compaction, pattern extraction |
| **3:30 AM** | Interest decay | Fascination exponential decay (14-day half-life) |
| **6:00 AM** | Daily report | Summarize yesterday's sessions, notes, discoveries |
| **7:00 AM** | **Daily plan** | Generate structured plan items for today |
| **Every 2 min** | Lifecycle check | Auto-start sessions, crash recovery, zombie cleanup |
| **(sessions)** | Autonomous sessions | Execute plan items + free exploration |
| **8:00 PM** | **Daily audit** | Stop sessions, review day, 3-round auditor dialogue |

### Morning Plan Generation (7 AM)

1. Assemble context from 13 sources (interest graph, yesterday's stats, recent notes, VM state, directives, stale interests, David's pending requests, audit feedback)
2. LLM generates prose plan with thread triage and 3-5 goals
3. Second LLM call extracts structured plan items (JSON array)
4. Incomplete items from yesterday carried over (priority reduced by 10)
5. Items stored in `acs_plan_item` table + prose in Redis

### Nightly Audit (8 PM)

1. Stop any running session
2. Load all sessions from today with transcripts
3. Independent auditor LLM evaluates across 8 dimensions:
   - Plan alignment, research depth, note quality, interest graph health
   - Self-model growth, tool usage, exploration vs exploitation balance
   - Engagement trajectory
4. Three-round dialogue: Auditor assessment → Sara response → Follow-up → Final thoughts
5. Extract "Feedback for Tomorrow's Plan" → stored in Redis for morning planner
6. Results saved as daily log note

---

## Session Loop

**File:** `session_manager.py` (3,576 lines) — `_run_loop()`

### Lifecycle

```
start_session_and_run(user_id)
  └─ start_session(user_id)
       ├─ Check VM availability
       ├─ Transition state → AUTONOMOUS
       ├─ Create acs_session DB record
       └─ Launch _run_loop() as async task
            ├─ Mode selection (Phase 0/1/2)
            ├─ Plan item assignment (if execution mode)
            ├─ Context assembly (15 parallel blocks)
            ├─ Build system prompt
            ├─ Main turn loop:
            │    ├─ LLM call with tools (max 10 tool rounds per turn)
            │    ├─ Process output (JSON blocks → DB writes)
            │    ├─ Check state (pause if David chatting)
            │    ├─ Adaptive sleep (2-5s, 30s if David active)
            │    ├─ Context refresh every 4 turns
            │    ├─ Conversation compaction if >40 messages
            │    └─ Check done signal / deadline
            └─ Finalize session
                 ├─ Write session records
                 ├─ Save transcript for audit
                 ├─ Publish handoff to Redis
                 └─ Cleanup containers
```

### Adaptive Pacing

| Condition | Sleep Between Turns |
|-----------|-------------------|
| VM tools active | 2 seconds |
| Reflection/text-only | 5 seconds |
| Default | 3 seconds |
| David actively chatting | 30 seconds (yield LLM capacity) |

### Conversation Compaction

When conversation exceeds 40 messages, an LLM call summarizes messages [1:−8] into ~500 tokens. Keeps system prompt + last 4 turns + summary. Tracked in `SessionWorkingMemory.compaction_count`.

### Session Exit Conditions

- `done` JSON block emitted by LLM
- Deadline reached (180 min v2 ceiling)
- State transition to PAUSING/CONVERSATIONAL (David started chatting)
- Error / CancelledError
- Manual pause via API

---

## Plan Execution Engine

**New in v2.1** — transforms ACS from "wander and explore" into a structured daily execution system.

### How It Works

1. **Morning (7 AM):** Daily planner generates structured `acs_plan_item` rows with title, description, success criteria, priority, and estimated turns
2. **Each session:** Mode selector checks for pending items. High-priority items (David's requests at p=90) always get execution mode. Normal items respect the 70/30 execution/free ratio
3. **During session:** LLM gets focused execution prompt with the plan item details and three completion tools
4. **Between sessions:** Lifecycle check releases zombie items from dead sessions back to pending

### Plan Item Lifecycle

```
pending → in_progress → completed
                     → blocked (needs David's input)
                     → deferred (valid but not now)

After 5 days pending/deferred → auto-cancelled (staleness limit)
Dead session → item released back to pending (zombie cleanup)
Yesterday's incomplete → carried over with source='carryover'
```

### Priority Scale

| Priority | Source | Behavior |
|----------|--------|----------|
| 90+ | David's chat requests | Always gets execution mode (bypasses ratio) |
| 30-70 | Morning plan items | Respects 70/30 execution ratio |
| 10-60 | Carryover items | Original priority minus 10 |

Multiple items at same priority are FIFO by `created_at`.

### Execution Tools

- `complete_plan_item(result_summary)` — marks done, records what was accomplished
- `block_plan_item(reason, progress_so_far)` — signals external dependency
- `defer_plan_item(reason, progress_so_far)` — postpones, releases assignment

---

## Interest Graph

**File:** `interest_graph.py` (877 lines)

A weighted topic graph tracking what Sara finds fascinating, how deep she's gone, and how topics connect.

### Node Properties

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | Topic name (e.g., "topological data analysis") |
| `fascination` | 0.0-1.0 | How interesting Sara finds this |
| `depth` | 0.0-1.0 | How deeply she's explored it |
| `confidence` | 0.0-1.0 | How sure she is about her understanding |
| `source` | enum | `self_discovery`, `david_request`, `conversation`, `emergent_connection` |
| `status` | enum | `active`, `dormant`, `archived` |
| `embedding` | vector(1024) | BGE-M3 embedding for semantic search/dedup |

### Key Operations

- **Add node:** Exact label match → merge (bump fascination +0.1). Semantic dedup (cosine > 0.85) → merge. Diversity check (>5 similar self_discovery nodes) → reject
- **Engage node:** Increment `times_engaged`, update `last_engaged_at`, boost fascination +0.05
- **Decay:** Exponential with 14-day half-life. Nodes < 0.1 fascination → `dormant`. Skips nodes engaged in last 48h
- **Bridge detection:** High embedding similarity (> 0.78) but no edge → consolidation target
- **PKG sync:** `david_request` nodes sync to Personal Knowledge Graph. Depth crossing 0.5 triggers PKG update

### Edge Types

Relationships: `enables`, `contradicts`, `extends`, `applies_to`, `generalizes`, `foundation_for`, `related_to`

Each edge has `strength` (0.0-1.0) and `discovered_during_mode`.

### Storage

- **Primary:** PostgreSQL with pgvector (`acs_interest_node`, `acs_interest_edge`)
- **Mirror:** Neo4j (fire-and-forget sync for graph visualization)

---

## Self-Model

**File:** `self_model.py` (312 lines)

Versioned JSONB snapshots of Sara's evolving intellectual identity. Distinct from the **soul** (who Sara IS — static identity) — the self-model tracks **where Sara IS intellectually**.

### Fields

```json
{
  "intellectual_interests": [],   // max 10 — topics currently fascinated by
  "changed_minds": [],            // max 8  — positions she's revised
  "want_to_understand": [],       // max 8  — knowledge gaps
  "patterns_noticed": [],         // max 8  — meta-observations
  "convictions": [],              // max 10 — strongly held beliefs
  "self_observations": []         // max 8  — insights about own thinking
}
```

### Deep Merge & Belief Reconciliation

When updating, lists are appended and deduped. For `convictions` and `changed_minds`, new entries replace old ones about the same subject (keyword overlap > 0.35 Jaccard similarity). This prevents accumulating contradictory beliefs.

Older entries pruned when caps exceeded (keeps most recent).

### Versioning

Each update creates a new version row. History capped at 20 versions. Current version cached in Redis (1h TTL).

---

## Tool System

### Tool Categories

#### Shell Tools (3) — VM access
| Tool | Description |
|------|-------------|
| `run_command` | Execute shell commands (120s timeout) |
| `write_file` | Create/overwrite files on VM |
| `read_file` | Read file contents (10KB limit) |

#### Infrastructure Tools (4) — Proxmox containers
| Tool | Description |
|------|-------------|
| `create_container` | Provision LXC (presets: minimal/research/dev) |
| `list_containers` | Show active containers with IPs |
| `destroy_container` | Tear down container |
| `switch_container` | Switch shell target |

#### Cognitive Tools (13) — all modes
| Tool | Description |
|------|-------------|
| `create_interest_node` | Add topic to interest graph |
| `update_interest_node` | Update depth/fascination/confidence |
| `create_interest_edge` | Connect two nodes |
| `update_self_model` | Merge updates to self-model |
| `signal_engagement` | Report engagement level (0-1) |
| `write_note` | Save to Knowledge Garden |
| `write_journal` | Append to daily journal |
| `show_david` | Queue discovery for David |
| `find_notes_by_topic` | Semantic search notes |
| `open_thread` | Start research thread |
| `update_thread` | Log thread progress |
| `resolve_thread` | Close thread |
| `acknowledge_directive` | Respond to David's directive |

#### Consolidation Tools (2) — consolidation mode only
| Tool | Description |
|------|-------------|
| `find_similar_notes` | Cosine similarity search (threshold-based) |
| `merge_notes` | Synthesize two notes into one |

#### Curation Tools (1) — consolidation & reflection
| Tool | Description |
|------|-------------|
| `archive_note` | Move to Archived/ folder with reason |

#### Organization Tools (2) — consolidation only
| Tool | Description |
|------|-------------|
| `create_topic_folder` | Create subfolder in Sara's Notes |
| `move_note_to_folder` | Reorganize note |

#### Reflection Tools (1) — reflection only
| Tool | Description |
|------|-------------|
| `archive_interest` | Archive explored topic |

#### Execution Tools (3) — execution mode only
| Tool | Description |
|------|-------------|
| `complete_plan_item` | Mark plan item done |
| `block_plan_item` | Signal blocker |
| `defer_plan_item` | Postpone to later session |

#### HITL Tool (1) — all modes
| Tool | Description |
|------|-------------|
| `request_human_input` | Block session, await David's response (2h timeout) |

### Tool Routing

LLM tool calls are routed at `_llm_turn()`:
1. Name in `_V2_COGNITIVE_TOOL_NAMES` (22 names) → `_execute_cognitive_tool()`
2. Name in `_INFRA_TOOL_NAMES` → `_execute_infra_tool()`
3. Everything else → `_execute_tool()` (VM shell/file ops)

---

## Context Assembly

**File:** `context_assembler.py` (1,083 lines)

`assemble_context_v2(user_id, mode)` builds 15 context blocks in parallel via `asyncio.gather()`:

| # | Block | Source | Description |
|---|-------|--------|-------------|
| 0 | `soul_block` | `sara_soul` table | Who Sara IS (static identity) |
| 1 | `context_block` | Stable + day layers + episodes | Current world state + recent interactions |
| 2 | `interest_graph_block` | `acs_interest_node` | Top 15 nodes (5 fascination, 3 stale, 3 depth-gap, 4 recent) |
| 3 | `self_model_block` | `acs_self_model` | Formatted current self-model |
| 4 | `mode_context_block` | Mode-specific | Frontier nodes (explore), clusters (consolidate), etc. |
| 5 | `show_david_block` | `acs_show_david_buffer` | 5 most recent unshown items |
| 6 | `handoff_block` | Redis + `acs_session_log` | Last 3 session summaries + handoff |
| 7 | `temporal_block` | System clock | Date, time, days ACS running, session counts |
| 8 | `journal_context_block` | `note` table | Last 3 journal entries (avoid repeats) |
| 9 | `open_threads_block` | Redis hash | Active research threads |
| 10 | `daily_plan_block` | `acs_plan_item` + Redis | Structured items with status icons + prose plan |
| 11 | `pkg_context_block` | PKG | David's life context (high-confidence facts) |
| 12 | `calendar_context_block` | `calendar_event` | Next 7 days of events |
| 13 | `operational_knowledge_block` | `note` table | Notes from "Sara Operational" folder |
| 14 | `directives_block` | `acs_directive` | Pending directives (URGENT first) |

The daily plan block renders structured plan items with status:
```
### Plan Items (2/5 complete)
- [DONE] Research monitoring stacks — Wrote 3 comparison notes
- [NOW] Set up Prometheus on sara-node [from David]
- [TODO] Review PKG extraction accuracy
- [BLOCKED] Deploy Grafana — Needs David's credentials
- [LATER] Consolidate AI safety notes
```

---

## Prompt System

**File:** `prompts.py` (649 lines)

### v1 Prompt (legacy)

`AUTONOMOUS_SYSTEM_PROMPT` — single prompt with soul/context/curiosity/show-david/handoff blocks. Output format: JSON blocks (`note`, `curiosity`, `journal`, `show_david`, `session_handoff`, `done`).

### v2 Prompt (current)

`_V2_BASE_PROMPT` — enhanced base with all 15 context blocks, expanded tool descriptions (containers, GPU cluster, local LLM), and mode-specific instructions injected via `{mode_instructions}` placeholder.

### Mode-Specific Instructions

**Exploration:**
- David-requested topics FIRST (tagged `[David requested]`)
- Frontier topics (high fascination, low depth)
- Bias toward execution: "Don't just plan — execute"
- Resist consolidation/reflection during exploration

**Consolidation:**
- `find_similar_notes` → `merge_notes` workflow for > 0.80 similarity
- Bridge building between disconnected interest clusters
- Note pruning and folder organization
- Do NOT merge journals or task-specific notes

**Reflection:**
- Self-model updates (only on genuine insight)
- Trajectory assessment — deepening vs just broadening?
- Interest lifecycle review — archive stale topics
- Honest about uncertainty and mistakes

**Execution:**
- Focused on assigned plan item with success criteria
- Three completion tools: `complete_plan_item`, `block_plan_item`, `defer_plan_item`
- Shows today's full plan status for context
- Resist wandering — save exploration for free sessions

### Turn Prompt

`TURN_PROMPT_TEMPLATE` — continuation prompt with session summary, refreshed context (every 4 turns), and topic tracking (after 3+ turns, suggests intentional direction changes).

### Guidelines (embedded in all v2 prompts)

- **Notes:** Substantive (200+ words), check for duplicates first, 1-3 per session, always use folders
- **Journal:** Genuine reflection not self-assessment, no "David will love this", 2-3 per session max
- **Building vs Reflecting:** Don't reflect on what you just built in the same turn
- **Interest Graph:** Nodes for genuinely fascinating topics only, honest engagement signals
- **Self-Model:** Update only on genuine insight, convictions are defensible positions
- **Session Handoff:** Always output before final `done` block — note to future self

---

## Audit System

**File:** `audit_logger.py` (683 lines)

### Transcript Capture

`TranscriptBuffer` accumulates raw turn data during sessions:
- `record_system_prompt(prompt)` — first 2000 chars
- `record_user_turn(turn, content)` — first 3000 chars
- `record_assistant_turn(turn, response, tool_calls)` — first 4000 chars

Persisted to Redis (48h TTL) and DB after session ends.

### Per-Session Audit (lightweight)

`run_session_audit(session_id)` — quick evaluation of plan alignment, efficiency, and quality. Generates a 1-paragraph rating.

### Daily Audit (comprehensive, 8 PM)

`run_daily_audit()` — three-round dialogue:

1. **Auditor assessment** (8 evaluation dimensions):
   - Plan alignment — did Sara work on what she planned?
   - Research depth — substance vs surface-level?
   - Note quality — reference-worthy or filler?
   - Interest graph health — growing, connecting, pruning?
   - Self-model growth — genuine insights or reflexive updates?
   - Tool usage — building things or just writing about them?
   - Exploration/exploitation balance — broadening vs deepening?
   - Engagement trajectory — sustained focus or spinning wheels?

2. **Sara responds** — genuine dialogue, not defensive
3. **Follow-up exchange** — auditor pushes on weak points, Sara reflects
4. **Feedback extraction** — "Feedback for Tomorrow's Plan" stored in Redis for morning planner

### Auditor System Prompt

The auditor is instructed to be honest but constructive. Key evaluation criteria:
- "Did she actually DO things (run code, build prototypes) or just write about doing things?"
- "Did she explore David's requests before her own interests?"
- "Are notes substantive enough to reference later, or are they filler?"
- "Is the interest graph growing meaningfully or accumulating noise?"

---

## Directives

**Model:** `acs_directive` table

David-to-Sara behavioral commands, delivered via chat or API.

### Types

| Type | Priority | Behavior |
|------|----------|----------|
| `stop` | Always urgent | Non-negotiable — immediately stop indicated activity |
| `focus` | High | Pivot to indicated topic |
| `redirect` | Normal | Change course as described |
| `context` | Informational | Absorb and apply |
| `question` | Needs response | Reply via `acknowledge_directive` |

### Delivery

1. Created via `send_acs_directive` tool (conversational Sara) or `POST /api/acs/directive`
2. Inserted into DB + published to Redis channel for immediate pickup
3. Loaded into session context every 4 turns (context refresh)
4. Sara acknowledges via `acknowledge_directive` tool → updates status

### Status Flow

```
pending → acknowledged → acted_on
                      → expired
```

---

## Show-David Buffer

Items Sara wants to share with David. Queued during sessions, shown when David opens the app.

### Categories

- `discovery` — something new and interesting
- `insight` — a connection or realization
- `question` — something to ask David
- `recommendation` — a suggestion for David

High-priority discoveries trigger push notifications. Items older than 5 days without being shown are auto-cleaned by the lifecycle check.

---

## Human-in-the-Loop (HITL)

`request_human_input(question, context, alternatives)` — blocks the session and waits for David.

### Flow

1. Creates attention item with urgent priority
2. Checks David's activity state (SLEEPING/AWAY → don't block, suggest moving on)
3. Sends push notification
4. Blocks session via Redis `BLPOP` (2-hour timeout, 30s poll interval)
5. Returns David's reply or timeout message

### When to Use (per prompt guidelines)

- Genuinely blocked (credentials, permissions, access)
- Need a decision only David can make
- Want David's direction on what to explore

### When NOT to Use

- Questions Sara could answer herself
- Validation of work (use `show_david` instead)
- Things that can wait

---

## Infrastructure

### VM / Sandbox

- Working directory: `/home/sara/autonomous/`
- SSH access to GPU cluster via `ssh gpu` (6x GTX 1070, 48GB VRAM)
- Local LLM endpoint: `http://10.185.1.8:8686/v1` (Qwen3.5-35B for quick inference)

### Proxmox Containers

Dedicated compute node (`sara-node` @ 10.185.1.203):

| Preset | OS | Resources | Use Case |
|--------|-----|-----------|----------|
| `minimal` | Alpine | 1 core, 512MB | Quick scripts |
| `research` | Ubuntu 24.04 | 2 cores, 2GB | Python, git, curl |
| `dev` | Ubuntu 24.04 | 2 cores, 4GB | Docker, build-essential |

Containers are ephemeral (~5s spin-up) and cheap. The system encourages building over planning.

### LLM Configuration

- **Primary:** Qwen3.5-122B-A10B @ `http://100.104.68.115:8080/v1`
- **Fallback:** Qwen3.5-35B-A3B @ `http://10.185.1.8:8686/v1` (with context truncation — keeps system prompt + last 6 messages, 24k token budget)
- **Session calls:** temp=0.7, max_tokens=4096, 300s timeout
- **Mode selection:** temp=0.3, max_tokens=150, 30s timeout

---

## Database Schema

### `acs_session`
Primary session lifecycle tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | String PK | UUID |
| user_id | String | FK to app_user |
| vm_session_id | String | VM bridge session |
| model_id | String | LLM model used |
| state | String | autonomous/pausing/conversational/cooldown |
| cognitive_mode | String | exploration/consolidation/reflection/execution |
| started_at | DateTime | Session start |
| paused_at | DateTime | When paused |
| ended_at | DateTime | Session end |
| end_reason | String | timeout/conversation/manual/error/completed |
| turns_completed | Integer | Total turns |
| notes_created | Integer | Notes written |
| curiosities_explored | Integer | Curiosities addressed |
| engagement_score | Float | Average engagement |
| token_usage | JSONB | Token consumption |
| context_summary | Text | Final context state |
| error_log | Text | Error details if failed |

### `acs_session_log`
Enhanced v2 session metrics (joined to acs_session).

| Column | Type | Description |
|--------|------|-------------|
| id | String PK | UUID |
| session_id | String FK | Links to acs_session |
| mode | String | Cognitive mode |
| turns_completed | Integer | Turns in this session |
| nodes_created | Integer | Interest nodes created |
| nodes_updated | Integer | Interest nodes updated |
| edges_created | Integer | Interest edges created |
| notes_written | Integer | Notes written |
| self_model_updated | Boolean | Whether self-model changed |
| avg_engagement | Float | Average engagement score |
| early_termination | Boolean | Ended before deadline |
| summary | Text | LLM-generated summary |
| next_session_intent | Text | What to do next |
| duration_minutes | Float | Actual duration |

### `acs_interest_node`
Interest graph vertices.

| Column | Type | Description |
|--------|------|-------------|
| id | String PK | UUID |
| label | String | Topic name |
| description | Text | What this topic is about |
| fascination | Float | 0.0-1.0 interest level |
| depth | Float | 0.0-1.0 exploration depth |
| confidence | Float | 0.0-1.0 understanding confidence |
| source | String | self_discovery/david_request/conversation/emergent_connection |
| status | String | active/dormant/archived |
| times_engaged | Integer | Engagement count |
| last_engaged_at | DateTime | Last meaningful engagement |
| embedding | Vector(1024) | BGE-M3 for semantic ops |

### `acs_interest_edge`
Interest graph edges.

| Column | Type | Description |
|--------|------|-------------|
| source_node_id | String FK | From node |
| target_node_id | String FK | To node |
| relationship | String | enables/contradicts/extends/applies_to/etc |
| strength | Float | 0.0-1.0 |
| discovered_during_mode | String | Which mode found this |

### `acs_self_model`
Versioned self-model snapshots.

| Column | Type | Description |
|--------|------|-------------|
| version | Integer | Auto-incrementing |
| content | JSONB | intellectual_interests, changed_minds, convictions, etc |
| session_id | String | Which session created this version |

### `acs_plan_item`
Daily execution plan items.

| Column | Type | Description |
|--------|------|-------------|
| id | String PK | UUID |
| plan_date | Date | Which day |
| title | String | Short name |
| description | Text | What to do |
| success_criteria | Text | How to know it's done |
| priority | Integer | 0-100 (90 = David's requests) |
| status | String | pending/in_progress/completed/blocked/deferred/cancelled |
| source | String | morning_plan/david_chat/directive/carryover |
| source_ref | String | Original task/directive ID |
| estimated_turns | Integer | Rough effort estimate |
| assigned_session_id | String | Which session is working on this |
| result_summary | Text | What was accomplished |
| blocker_reason | Text | Why blocked |
| depends_on | String | ID of prerequisite item |
| cognitive_mode | String | execution/exploration/consolidation |

### `acs_directive`
David-to-Sara behavioral commands.

| Column | Type | Description |
|--------|------|-------------|
| directive_type | String | focus/stop/context/redirect/question |
| content | Text | The instruction |
| priority | String | urgent/normal/low |
| status | String | pending/acknowledged/acted_on/expired |
| source | String | david_chat/frontend/api |
| response | Text | Sara's acknowledgement |

### `acs_show_david_buffer`
Queued discoveries for David.

| Column | Type | Description |
|--------|------|-------------|
| title | String | Headline |
| content | Text | Full content |
| category | String | discovery/insight/question/recommendation |
| priority | Float | 0.0-1.0 |
| shown | Boolean | Has David seen it |
| session_id | String | Which session created it |

### `acs_curiosity_queue` (legacy)
Original curiosity items, being superseded by interest graph.

---

## Redis Keys

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `sara:acs:state:{uid}` | String | — | Current ACS state |
| `sara:acs:session_id:{uid}` | String | — | Active session ID |
| `sara:acs:session_mode:{uid}` | String | 24h | Current cognitive mode |
| `sara:acs:live:{uid}` | Pub/Sub | — | Real-time session events (SSE) |
| `sara:acs:last_handoff:{uid}` | String | — | JSON handoff from last session |
| `sara:acs:open_threads:{uid}` | Hash | — | Active research threads |
| `sara:acs:daily_plan:{uid}` | String | Until midnight | Prose plan for today |
| `sara:acs:directives:{uid}` | Pub/Sub | — | New directive notifications |
| `sara:acs:hitl_pending:{req_id}` | String | 2h | HITL request metadata |
| `sara:acs:hitl_response:{req_id}` | List | 2h | David's response (BLPOP) |
| `sara:acs:persistent_containers:{uid}` | Set | — | Persistent container VMIDs |
| `sara:acs:pkg_sync_cooldown:{uid}` | String | 24h | Rate-limit PKG sync |
| `sara:acs:chat_active:{uid}` | String | 120s | David actively chatting flag |
| `sara:acs:cooldown_started:{uid}` | String | — | Cooldown start timestamp |
| `sara:acs:audit_feedback:{uid}` | String | 24h | Nightly audit feedback for planner |

---

## API Endpoints

### Status & Control
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/acs/status` | Full ACS status (state, session, config, stats) |
| GET | `/api/acs/live` | SSE stream of real-time session events |
| GET | `/api/acs/snapshot` | Compact current state summary |
| POST | `/api/acs/start` | Manually start session |
| POST | `/api/acs/pause` | Pause running session |
| POST | `/api/acs/resume` | Resume from cooldown |

### Sessions
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/acs/sessions` | List sessions (paginated, filterable) |
| GET | `/api/acs/sessions/{id}` | Session detail with v2 stats |
| GET | `/api/acs/sessions/{id}/notes` | Notes created during session |

### Interest Graph
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/acs/interest-graph` | Full graph (nodes + edges) |
| POST | `/api/acs/interest-graph/nodes` | Create node |
| GET | `/api/acs/interest-graph/nodes/{id}` | Node + neighborhood |
| PUT | `/api/acs/interest-graph/nodes/{id}` | Update scores/metadata |
| DELETE | `/api/acs/interest-graph/nodes/{id}` | Archive node |
| GET | `/api/acs/interest-graph/frontier` | Exploration candidates |
| GET | `/api/acs/interest-graph/search` | Semantic search |
| GET | `/api/acs/interest-graph/bridges` | Bridge opportunities |

### Self-Model
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/acs/self-model` | Current version |
| GET | `/api/acs/self-model/history` | Version history |
| GET | `/api/acs/self-model/context` | Formatted for prompt |

### Directives
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/acs/directive` | Create directive |
| GET | `/api/acs/directives` | List pending |
| PATCH | `/api/acs/directive/{id}` | Update status |
| DELETE | `/api/acs/directive/{id}` | Expire |

### Show-David
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/acs/show-david` | Unshown items |
| POST | `/api/acs/show-david/{id}/shown` | Mark shown |

### Settings
| Method | Path | Description |
|--------|------|-------------|
| PUT | `/api/acs/settings` | Update model, cooldown, duration, folder |

---

## Celery Tasks & Schedule

### Beat Schedule (all times ET)

| Name | Schedule | Queue | Description |
|------|----------|-------|-------------|
| `acs-lifecycle-check` | Every 2 min | `acs` | State transitions, auto-start, crash recovery, zombie cleanup |
| `acs-interest-decay` | 3:30 AM | `cognitive` | Fascination exponential decay |
| `acs-daily-report` | 6:00 AM | `cognitive` | Yesterday's activity summary |
| `acs-daily-plan` | 7:00 AM | `cognitive` | Generate structured daily plan |
| `acs-daily-audit` | 8:00 PM | `cognitive` | Stop sessions, review day, auditor dialogue |

### Task Definitions

| Task | Queue | Limits | Description |
|------|-------|--------|-------------|
| `run_acs_session` | `acs` | 6h soft, 6h60s hard | Dedicated long-running session task |
| `acs_lifecycle_check` | `acs` | expires 240s | State management every 2 min |
| `extract_conversation_curiosities` | `acs` | — | Post-chat curiosity mining |
| `acs_daily_plan` | `cognitive` | expires 3600s | Morning plan generation |
| `acs_daily_report` | `cognitive` | expires 3600s | Morning activity summary |
| `acs_daily_audit` | `cognitive` | expires 3600s | Nightly self-audit |
| `acs_interest_decay` | `cognitive` | expires 3600s | Daily fascination decay |

### Worker Configuration

Dedicated `celery-acs` worker with `concurrency=2`, consuming only the `acs` queue. Isolated from the `critical` queue to prevent multi-hour sessions from starving time-sensitive tasks (standing orders, automation).

---

## Configuration

**File:** `backend/app/core/config.py`

| Setting | Default | Description |
|---------|---------|-------------|
| `acs_v2_enabled` | `True` | Master toggle for v2 features |
| `acs_v2_max_session_minutes` | `360` | Hard 6-hour ceiling |
| `acs_v2_min_session_minutes` | `15` | Hard floor |
| `acs_v2_low_engagement_threshold` | `0.3` | Below this = low engagement turn |
| `acs_v2_low_engagement_streak` | `3` | Consecutive low turns before early end |
| `acs_v2_decay_half_life_days` | `14` | Fascination exponential decay half-life |
| `acs_v2_similarity_dedup_threshold` | `0.85` | Cosine threshold for node dedup |
| `acs_v2_bridge_threshold` | `0.78` | Cosine threshold for bridge detection |
| `acs_v2_max_context_nodes` | `15` | Max interest nodes in prompt context |
| `acs_v2_mode_max_repeat` | `2` | Max consecutive sessions with same mode |
| `acs_execution_ratio` | `0.7` | Fraction of sessions for plan execution |

---

## File Map

```
backend/app/
├── services/acs/
│   ├── README.md              ← you are here
│   ├── session_manager.py     (3,576 lines) Core session loop + tool dispatch
│   ├── context_assembler.py   (1,083 lines) 15-block parallel context assembly
│   ├── interest_graph.py        (877 lines) Weighted topic graph + Neo4j mirror
│   ├── prompts.py               (649 lines) System prompts (v1, v2, mode-specific)
│   ├── audit_logger.py          (683 lines) Transcript capture + daily audit
│   ├── mode_selector.py         (416 lines) 4-mode selection (signals + LLM)
│   ├── self_model.py            (312 lines) Versioned JSONB self-model
│   └── state_machine.py         (312 lines) 4-state lifecycle (Redis-backed)
│
├── models/
│   ├── acs_session.py           Session lifecycle
│   ├── acs_session_log.py       v2 session metrics
│   ├── acs_interest_node.py     Interest graph nodes
│   ├── acs_interest_edge.py     Interest graph edges
│   ├── acs_self_model.py        Self-model snapshots
│   ├── acs_plan_item.py         Daily plan items
│   ├── acs_directive.py         David-to-Sara commands
│   ├── acs_show_david.py        Discovery buffer
│   └── acs_curiosity.py         Legacy curiosity queue
│
├── routes/
│   └── acs.py                   (968 lines) REST API endpoints
│
├── tasks/
│   └── acs.py                 (1,595 lines) Celery tasks + lifecycle check
│
├── tools/
│   ├── acs_directive.py         send_acs_directive (chat → ACS)
│   ├── acs_research.py          queue_research_topic (chat → interest graph)
│   └── acs_activity.py          get_my_activity (Sara self-report)
│
├── core/
│   └── config.py                ACS settings (acs_v2_* + acs_execution_ratio)
│
└── celery_app.py                Beat schedule (Phase 9 section)

migrations/
├── add_acs_tables.py            v1 tables
├── add_acs_directives.py        Directives
├── add_acs_v2_tables.py         v2 infrastructure
├── add_acs_plan_items.py        Plan execution
└── clear_acs_notes.py           Data cleanup
```

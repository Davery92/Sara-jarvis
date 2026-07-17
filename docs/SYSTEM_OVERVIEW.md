# Sara — System Overview

Sara is a personal AI assistant built as a full-stack application with an increasingly autonomous "Jarvis-like" backend.

## Core Stack

| Layer | Tech | Entry Point |
|-------|------|-------------|
| Frontend | React + Vite + Tailwind | `App-interactive.tsx` |
| iOS App | React Native | `ios-app/` |
| Desktop | Electron | `sara-desktop/` |
| Backend | FastAPI (monolith) | `main_simple.py` (~9,300 lines) |
| Database | PostgreSQL 16 + pgvector | Semantic search via embeddings |
| Graph DB | Neo4j | Personal knowledge graph |
| Cache | Redis | Event bus, state caching |
| Object Store | MinIO | Document uploads |
| Task Queue | Celery + Redis | Autonomous background work |
| LLM | OpenAI-compatible (local 120B) | Chat, reasoning, agent loops |

## What Sara Does

**Chat** — Conversational AI with tool use (memory search, notes, reminders, timers, calendar, home control, learning). Responses are personality-adapted based on activity state, stress level, and device.

**Memory** — Every interaction becomes an episode with importance scoring and vector embeddings. Composite retrieval (similarity + recency + importance + frequency). A selective RAG router decides when to pull context vs. respond directly.

**Notes** — Obsidian-style knowledge garden with bidirectional `[[links]]`, semantic connections, graph visualization, and timeline view.

**Learning** — Structured learning paths with spaced repetition, deep research workers (5-phase Celery pipeline), and recall testing woven into normal chat.

**Home Automation** — Bidirectional Home Assistant integration. Sara receives real-time HA websocket events (motion, doors, lights, climate) and can control devices via tools.

---

## The Autonomy Stack

This is the "brain" that runs without being asked. It has evolved through several generations.

### Unified Agent (every 15 min)

A single Celery task (`unified-agent`) runs a 4-phase cycle (expandable to 6-phase with feature flags):

```
SENSE → THINK → ACT → RECORD
```

**SENSE** (no LLM) — Gathers signals: calendar events, unread emails, weather, home state, body metrics (Garmin), habits, notes, active learning, documents, automations, followup threads, standing order triggers.

**THINK** (LLM agent loop) — The agent has ~15 tools and reasons about what needs attention. Standing orders fire deterministically before the LLM loop. Mood is inferred from the agent's own reasoning (no separate LLM call).

**ACT** — Sends notifications (interruptibility-aware), creates attention queue items, updates threads.

**RECORD** — Writes a journal entry (`entry_type='unified'`), logs to `agent_run_log` with run metadata, writes action traces.

**Night mode** (1–5 AM): Phase 1 only, skips LLM unless high-priority signals.

### Control Plane (Cortana Evolution)

Adds policy governance, auditability, and structured output on top of the unified agent:

| Component | Purpose |
|-----------|---------|
| **Action Tracer** | Every autonomous action gets a trace record (`autonomy_action_trace`) with risk tier, decision, result |
| **Policy Engine** | Risk-tier gating: Tier 0 (read-only, always allow), Tier 1 (reversible, needs confidence >= 0.7 or standing order), Tier 2 (irreversible, requires standing order) |
| **Hard Safety Gate** | Always active regardless of flags — Tier 2 and unknown tools blocked without explicit standing order |
| **Action Simulator** | Precondition checks: entity exists, temperature bounds, rate limits, standing order conflicts |
| **Attention Queue** | Proactive inbox for non-urgent items. Deferred/low-priority actions land here instead of push notifications |
| **Mission Engine** | Persistent multi-step tasks with state machine (`pending -> running -> awaiting_confirm -> done/failed/cancelled`). Celery worker advances steps every 30s |
| **Policy Candidates** | Dream insights and reflection outputs become reviewable candidates that can be accepted into standing orders |
| **6-Phase Cycle** | When `AUTONOMY_STRUCTURED_PLAN=True`: SENSE -> PLAN -> SIMULATE -> EXECUTE -> VERIFY -> RECORD |

Feature flags let each piece be toggled independently. Flags off = original behavior, tables idle.

### Activity State Machine

Real-time awareness of what the user is doing, fed by Home Assistant events:

```
SLEEPING -> WAKING -> MORNING_ROUTINE -> ACTIVE -> FOCUSED_WORK -> IN_MEETING -> EXERCISING -> COOKING -> WINDING_DOWN -> AWAY -> UNKNOWN
```

Each state has a default interruptibility (0.0–1.0), modulated by body state, calendar, and notification fatigue. Notifications are delivered only when `urgency >= interruptibility`; otherwise queued.

### Personality Engine

Adapts Sara's tone based on:

- **Activity state** — sleeping: gentle, focused: terse
- **Body state** — stressed: warm/patient, alert: precise
- **Interruptibility** — verbosity calibration (ultra_brief / brief / balanced / detailed)
- **Conversation depth** — more detail as conversation deepens
- **Memory nudges** — weaves in personal callbacks from episodic memory

### Other Autonomous Systems

| System | Schedule | What it does |
|--------|----------|-------------|
| **Standing Orders** | Evaluated each heartbeat | User-defined rules with trigger conditions, action execution, 5-min undo window |
| **Reactive Engine** | Real-time (event bus) | Security, comfort, presence, light subscribers react to HA events instantly |
| **Dream Consolidation** | Nightly | Compacts episodic memory, finds behavioral patterns, generates policy candidates |
| **Reflection** | Nightly | Self-assessment, pattern detection, proposal generation |
| **Anticipation** | 7 AM + 9 PM | Morning prep and evening wind-down proactive briefings |
| **PKG Extraction** | After chats + learning | Extracts entities to Neo4j knowledge graph (people, preferences, routines, goals, interests, health, places, facts) |
| **Device Orchestrator** | Per-notification | Routes content to the right device (desktop WebSocket -> mobile push fallback) |
| **Retention Cleanup** | Daily 4 AM | Purges old traces (90d), attention items (30d), missions (180d), auto-expires stale candidates |

---

## Multi-Device

The same data surfaces on web (`frontend/`), iOS (`ios-app/`), and desktop Electron (`sara-desktop/`). The floating desktop circle shows the attention badge count. iOS has activity/attention/missions tabs.

---

## Data Flow Summary

```
User chats ──> main_simple.py (tool use, memory, personality)
                     |
                     |──> Episodes (pgvector)
                     |──> PKG extraction (Neo4j)
                     |──> Thread extraction (followup_thread)
                     └──> Learning recall injection

HA events ──> ha_websocket_service ──> ha_reactive_bridge
                     |
                     |──> Activity State Machine (Redis)
                     |──> Event Bus -> Reactive Engine (instant)
                     └──> Subconscious State (DB)

Every 15 min ──> Unified Agent (SENSE -> THINK -> ACT -> RECORD)
                     |
                     |──> Policy Engine gate
                     |──> Action Traces
                     |──> Attention Queue / Push Notifications
                     |──> Standing Order execution
                     |──> Mission advancement
                     └──> Journal + agent_run_log

Nightly ──> Dream Consolidation -> Policy Candidates
       ──> Reflection -> Proposals -> Standing Orders
```

---

## Feature Flags

| Flag | Default | Effect |
|------|---------|--------|
| `AUTONOMY_TRACES_ENABLED` | `True` | Action trace recording |
| `AUTONOMY_STRUCTURED_PLAN` | `False` | 6-phase cycle with structured JSON plan output |
| `AUTONOMY_POLICY_ENGINE` | `False` | Full policy gating on tool execution (hard safety gate always active) |
| `AUTONOMY_ATTENTION_ENABLED` | `False` | Route notifications through attention queue |
| `AUTONOMY_MISSIONS_ENABLED` | `False` | Mission worker runs |
| `AUTONOMY_POLICY_CANDIDATES_ENABLED` | `False` | Candidate generation from dreams/reflection |

Rollback: disable flag and the system reverts to pre-evolution behavior. Tables remain but idle.

---

## Key File Locations

| Area | Path |
|------|------|
| Backend monolith | `backend/app/main_simple.py` |
| Unified agent | `backend/app/services/unified_agent.py` |
| Policy engine | `backend/app/services/autonomy/policy_engine.py` |
| Action simulator | `backend/app/services/autonomy/action_simulator.py` |
| Action tracer | `backend/app/services/autonomy/action_tracer.py` |
| Attention queue | `backend/app/services/autonomy/attention_queue.py` |
| Mission engine | `backend/app/services/autonomy/mission_engine.py` |
| Policy candidates | `backend/app/services/autonomy/policy_candidate.py` |
| Standing orders | `backend/app/services/standing_order_service.py` |
| Activity state machine | `backend/app/services/activity_state_machine.py` |
| Personality engine | `backend/app/services/personality_engine.py` |
| Reactive engine | `backend/app/services/reactive_engine.py` |
| Device orchestrator | `backend/app/services/device_orchestrator.py` |
| Notification system | `backend/app/services/unified_notification.py` |
| Context router | `backend/app/services/context_router.py` |
| Celery tasks | `backend/app/tasks/autonomy.py` |
| Celery config | `backend/app/celery_app.py` |
| Tool registry | `backend/app/tools/registry.py` |
| HA bridge | `backend/app/services/ha_reactive_bridge.py` |
| PKG service | `backend/app/services/personal_knowledge_graph.py` |
| Dream consolidation | `backend/app/services/dream_consolidation.py` |
| Thread manager | `backend/app/services/thread_manager.py` |
| Autonomy routes | `backend/app/routes/autonomy_*.py` |
| Frontend app | `frontend/src/App-interactive.tsx` |
| iOS chat | `ios-app/src/screens/chat/ChatScreen.tsx` |
| Desktop agent | `sara-desktop/electron/main.ts` |
| Migrations | `backend/migrations/` |
| Tests | `backend/tests/` |

# ACS Standalone Framework — Design Document

## Vision

A standalone, installable framework for running autonomous AI cognition sessions. You point it at any OpenAI-compatible LLM endpoint, seed it with initial interests and directions, and it runs self-directed research/exploration sessions with persistent memory, an evolving interest graph, and self-auditing.

Think of it as a long-running AI agent that doesn't just execute tasks — it develops genuine intellectual depth over time, tracks what it knows, what it's curious about, and what it's already explored.

---

## What Sara's ACS Actually Does (The Reference Implementation)

The system Sara runs today has these core behaviors:

1. **Autonomous sessions** — An LLM runs in a tool-calling agent loop, exploring topics, writing notes, running shell commands, and managing its own interest graph. Sessions run until the agent naturally finishes (up to 6 hours).

2. **Interest graph** — A persistent graph of topics the agent finds fascinating, with fascination scores, depth tracking, semantic dedup, and decay over time. The agent creates/updates nodes and edges as it works.

3. **Self-model** — A versioned record of the agent's convictions, changed minds, intellectual interests, and self-observations. Updated when the agent has genuine insight about its own thinking.

4. **Three cognitive modes** — Exploration (follow curiosity), Consolidation (reduce redundancy, merge notes, build connections), Reflection (step back, assess trajectory, archive stale interests). Mode selected automatically based on recent history.

5. **Session continuity** — Enriched handoffs between sessions (what was accomplished, key findings, files touched, open questions). Smart compaction summarizes long conversations instead of silently dropping context.

6. **Daily planning** — Every morning, the agent generates a plan considering its interest graph health, topic diversity, stale interests, pending requests from the user, and yesterday's audit feedback.

7. **Self-auditing** — After every session, a lightweight audit checks plan alignment and efficiency. End-of-day, a comprehensive auditor↔agent dialogue reviews everything.

8. **Tool use** — Shell commands on a sandbox VM, file I/O, container provisioning, note writing, interest graph manipulation, research thread management.

---

## Architecture for the Standalone Framework

### Core Principle: Provider Interfaces

Everything external is behind an interface. The framework ships with default implementations but every integration point is swappable.

```
┌─────────────────────────────────────────────────────┐
│                    ACS Framework                     │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Session  │  │ Interest │  │    Self-Model      │  │
│  │ Manager  │  │  Graph   │  │   (versioned)      │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
│       │              │                 │              │
│  ┌────┴──────────────┴─────────────────┴──────────┐  │
│  │              Provider Interfaces                │  │
│  │                                                 │  │
│  │  LLMProvider    EmbeddingProvider    Storage     │  │
│  │  ToolProvider   ShellProvider     Scheduler      │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Provider Interfaces

```python
class LLMProvider(Protocol):
    """Any OpenAI-compatible endpoint."""
    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        ...

class EmbeddingProvider(Protocol):
    """Any embedding endpoint — needed for interest graph dedup and note search."""
    async def embed(self, text: str) -> list[float]:
        ...

class StorageProvider(Protocol):
    """Persistence layer — default is PostgreSQL+pgvector, but could be SQLite+numpy."""
    async def execute(self, query: str, params: dict) -> list:
        ...
    async def commit(self) -> None:
        ...

class ShellProvider(Protocol):
    """Optional — gives the agent shell access. Could be local, SSH, Docker, or disabled."""
    async def run_command(self, command: str, timeout: int = 120) -> ShellResult:
        ...
    async def write_file(self, path: str, content: str) -> str:
        ...
    async def read_file(self, path: str) -> str:
        ...

class CacheProvider(Protocol):
    """State machine, handoffs, session data. Default Redis, could be in-memory."""
    async def get(self, key: str) -> str | None:
        ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        ...

class SchedulerProvider(Protocol):
    """Drives the lifecycle. Default Celery, could be simple asyncio loop."""
    def schedule_recurring(self, name: str, interval_seconds: int, func) -> None:
        ...
    def schedule_once(self, name: str, func, delay_seconds: int = 0) -> None:
        ...
```

### Hot-Swappable Models

The LLM endpoint is just a URL + model name. Swapping models mid-run is a config change:

```python
@dataclass
class ModelConfig:
    url: str                          # "http://localhost:11434/v1"
    model: str                        # "qwen3:32b"
    api_key: str = ""                 # Optional
    max_context_tokens: int = 32768   # Drives compaction threshold
    temperature: float = 0.7
    request_timeout: float = 300.0

@dataclass
class ACSConfig:
    # Models — all independently configurable
    session_model: ModelConfig        # Main agent loop
    compaction_model: ModelConfig     # Can be smaller/cheaper for summarization
    audit_model: ModelConfig          # Can be same or different
    planning_model: ModelConfig       # Daily plan generation

    # Embeddings — separate endpoint
    embedding_url: str = "http://localhost:11434/v1"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # Session behavior
    max_session_minutes: int = 360
    turn_sleep_active: int = 2
    turn_sleep_reflection: int = 5
    turn_sleep_default: int = 3
    context_refresh_interval: int = 4
    compaction_threshold: int = 40    # Messages before LLM compaction

    # Interest graph
    similarity_dedup_threshold: float = 0.85
    bridge_threshold: float = 0.78
    decay_half_life_days: int = 14
    max_context_nodes: int = 15

    # Scheduling
    cooldown_minutes: int = 2
    plan_hour: int = 7              # Daily plan generation (local time)
    audit_hour: int = 22            # End-of-day audit (local time)
    timezone: str = "America/New_York"

    # Shell access
    shell_enabled: bool = True
    shell_type: str = "local"       # "local", "ssh", "docker", "none"
    shell_working_dir: str = "/tmp/acs-workspace"

    # Optional
    neo4j_url: str | None = None    # Mirror interest graph to Neo4j
```

---

## Database Schema (Standalone)

Seven tables. All ACS-specific — no dependencies on Sara's note/episode/folder system.

```sql
-- Core session tracking
CREATE TABLE acs_session (
    id UUID PRIMARY KEY,
    model_id TEXT,
    state TEXT NOT NULL DEFAULT 'autonomous',
    cognitive_mode TEXT,                          -- exploration/consolidation/reflection
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    end_reason TEXT,                              -- completed/timeout/error/manual
    turns_completed INTEGER DEFAULT 0,
    notes_created INTEGER DEFAULT 0,
    engagement_score REAL,
    error_log TEXT
);

-- Detailed session logs (v2 stats)
CREATE TABLE acs_session_log (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES acs_session(id),
    mode TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    turns_completed INTEGER DEFAULT 0,
    engagement_scores JSONB,
    avg_engagement REAL,
    nodes_created INTEGER DEFAULT 0,
    nodes_updated INTEGER DEFAULT 0,
    edges_created INTEGER DEFAULT 0,
    notes_written INTEGER DEFAULT 0,
    self_model_updated BOOLEAN DEFAULT FALSE,
    summary TEXT,
    duration_minutes REAL
);

-- Interest graph nodes
CREATE TABLE acs_interest_node (
    id UUID PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT,
    fascination REAL DEFAULT 0.5,
    depth REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT 'self_discovery',         -- self_discovery/user_request/emergent
    source_detail TEXT,
    status TEXT DEFAULT 'active',                 -- active/dormant/archived
    times_engaged INTEGER DEFAULT 0,
    last_engaged_at TIMESTAMPTZ,
    embedding vector(1024),                       -- pgvector; dimension configurable
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_interest_node_status ON acs_interest_node(status);
CREATE INDEX idx_interest_node_fascination ON acs_interest_node(fascination DESC);

-- Interest graph edges
CREATE TABLE acs_interest_edge (
    id UUID PRIMARY KEY,
    source_node_id UUID REFERENCES acs_interest_node(id),
    target_node_id UUID REFERENCES acs_interest_node(id),
    relationship TEXT NOT NULL,                   -- enables/contradicts/extends/applies_to
    description TEXT,
    strength REAL DEFAULT 0.5,
    discovered_during_mode TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Versioned self-model
CREATE TABLE acs_self_model (
    id UUID PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    content JSONB NOT NULL DEFAULT '{}',
    session_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notes (the agent's knowledge base)
CREATE TABLE acs_note (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    tags JSONB DEFAULT '[]',
    folder TEXT,                                  -- Simple folder name, not FK
    embedding vector(1024),
    starred BOOLEAN DEFAULT FALSE,
    archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_note_folder ON acs_note(folder);
CREATE INDEX idx_note_title_trgm ON acs_note USING gin(title gin_trgm_ops);

-- Discoveries/items to surface to the user
CREATE TABLE acs_show_user (
    id UUID PRIMARY KEY,
    session_id UUID,
    title TEXT NOT NULL,
    content TEXT,
    category TEXT DEFAULT 'discovery',
    priority REAL DEFAULT 0.5,
    shown BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**SQLite alternative** — For simpler deployments, the framework should also support SQLite with numpy-based vector operations instead of pgvector. Embedding similarity calculated in Python rather than SQL. This trades query speed for zero-infrastructure setup.

---

## Module Structure

```
acs-framework/
├── pyproject.toml
├── acs/
│   ├── __init__.py              # ACS class — main entry point
│   ├── config.py                # ACSConfig, ModelConfig dataclasses
│   ├── session.py               # SessionManager — the agent loop
│   ├── interest_graph.py        # InterestGraph — nodes, edges, decay, dedup
│   ├── self_model.py            # SelfModel — versioned beliefs/convictions
│   ├── mode_selector.py         # ModeSelector — heuristic + LLM mode choice
│   ├── prompts.py               # System prompts, turn prompts, mode instructions
│   ├── context.py               # ContextAssembler — builds context packet
│   ├── compaction.py            # Smart conversation compaction
│   ├── planner.py               # DailyPlanner — morning plan generation
│   ├── auditor.py               # SessionAuditor + DailyAuditor
│   ├── working_memory.py        # SessionWorkingMemory dataclass
│   ├── state_machine.py         # ACSState enum + transitions
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py              # Tool, ToolResult base classes
│   │   ├── cognitive.py         # Interest graph, self-model, notes tools
│   │   ├── shell.py             # Shell/file tools (uses ShellProvider)
│   │   └── research.py          # Thread management tools
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── protocols.py         # Protocol classes for all providers
│   │   ├── llm.py               # OpenAI-compatible LLM provider
│   │   ├── embedding.py         # Embedding provider
│   │   ├── postgres.py          # PostgreSQL + pgvector storage
│   │   ├── sqlite.py            # SQLite + numpy storage (lightweight)
│   │   ├── redis_cache.py       # Redis cache provider
│   │   ├── memory_cache.py      # In-memory cache (no Redis needed)
│   │   ├── shell_local.py       # Local shell provider
│   │   ├── shell_ssh.py         # SSH shell provider
│   │   ├── shell_docker.py      # Docker shell provider
│   │   └── scheduler_async.py   # asyncio-based scheduler (no Celery)
│   └── cli.py                   # CLI entry point
├── examples/
│   ├── minimal.py               # Simplest possible setup
│   ├── research_agent.py        # Seeded research agent
│   └── multi_model.py           # Different models for different tasks
└── migrations/
    ├── postgres.sql
    └── sqlite.sql
```

---

## API / Usage

### Minimal Setup

```python
from acs import ACS, ModelConfig

agent = ACS(
    model=ModelConfig(
        url="http://localhost:11434/v1",
        model="qwen3:32b",
    ),
    embedding_model=ModelConfig(
        url="http://localhost:11434/v1",
        model="bge-m3",
    ),
    database_url="sqlite:///my-agent.db",   # Or PostgreSQL
)

# Seed with initial interests
agent.seed([
    {"topic": "distributed systems consensus algorithms", "priority": 0.9},
    {"topic": "Rust async runtime design", "priority": 0.7},
    {"topic": "how LLM tokenizers affect reasoning", "priority": 0.8},
])

# Run — blocks until interrupted
agent.run()
```

### Seeded Research Agent

```python
from acs import ACS, ModelConfig, ACSConfig

config = ACSConfig(
    session_model=ModelConfig(
        url="http://gpu-server:8080/v1",
        model="Qwen3.5-122B-A10B",
        max_context_tokens=65536,
    ),
    compaction_model=ModelConfig(
        url="http://gpu-server:8080/v1",
        model="Qwen3.5-35B-A3B",         # Cheaper model for summaries
    ),
    audit_model=ModelConfig(
        url="http://gpu-server:8080/v1",
        model="Qwen3.5-35B-A3B",
    ),
    shell_enabled=True,
    shell_type="docker",                   # Sandboxed shell via Docker
    shell_working_dir="/workspace",
    max_session_minutes=120,
    cooldown_minutes=5,
)

agent = ACS(
    config=config,
    database_url="postgresql+asyncpg://user:pass@localhost/acs",
    redis_url="redis://localhost:6379/0",
)

# Seed with directed research
agent.seed([
    {"topic": "eBPF for network observability", "priority": 0.9, "source": "user_request",
     "detail": "Compare Cilium, Pixie, and Hubble. Build a test setup."},
    {"topic": "WebTransport vs WebSocket performance", "priority": 0.7},
])

# Inject a persona/soul (optional)
agent.set_soul("""
You are a systems engineering researcher focused on infrastructure and networking.
You prefer building prototypes over writing theoretical notes.
When exploring a topic, your first instinct should be to write code and run experiments.
""")

# Run with live event callback
agent.run(on_event=lambda e: print(f"[{e['type']}] {e.get('summary', '')}"))
```

### Hot-Swapping Models at Runtime

```python
# Change the session model without restarting
agent.update_model("session", ModelConfig(
    url="http://other-server:8080/v1",
    model="deepseek-r1:70b",
    max_context_tokens=131072,
))

# Or via CLI
# acs config set session.model deepseek-r1:70b
# acs config set session.url http://other-server:8080/v1
```

### CLI Interface

```bash
# Initialize a new agent
acs init --db sqlite:///agent.db --model "qwen3:32b" --url "http://localhost:11434/v1"

# Seed interests
acs seed "distributed consensus" --priority 0.9
acs seed "Rust async runtimes" --priority 0.7
acs seed "eBPF observability" --priority 0.8 --source user_request

# Set the agent's personality
acs soul set "You are a systems researcher who builds prototypes."

# Run
acs run

# Run in background
acs run --daemon

# Check status
acs status
# Output:
#   State: autonomous (session abc123, turn 7, exploration mode)
#   Interest graph: 23 active nodes, 15 edges
#   Notes: 12 total (3 today)
#   Last session: 14 turns, 2 notes, engagement 0.78

# View live activity
acs live

# View today's plan
acs plan

# List interests
acs interests
# Output:
#   eBPF observability          f=0.92  d=0.30  [user_request]
#   distributed consensus       f=0.85  d=0.15
#   Rust async runtimes         f=0.70  d=0.05

# Add a request mid-run
acs request "Look into QUIC protocol performance on lossy networks"

# View notes
acs notes
acs notes show "eBPF Cilium Architecture"

# View audit
acs audit today

# Swap model
acs config set session.model "deepseek-r1:70b"
acs config set session.url "http://other-gpu:8080/v1"

# Export knowledge
acs export --format markdown --output ./knowledge/
acs export --format json --output ./export.json
```

---

## Key Design Decisions

### 1. No User Concept

Sara's ACS has `user_id` everywhere because it's part of a multi-feature app. The standalone framework drops this — there's one agent per instance. If you want multiple agents, run multiple instances with separate databases.

### 2. Notes Replace Episodes

Sara's ACS writes to a shared `note` table that's also used by the main app. The standalone framework has its own `acs_note` table — simpler schema, no folder FK dependencies, just title/content/tags/folder-as-string.

### 3. SQLite as First-Class

PostgreSQL+pgvector is the performance path, but requiring it kills adoption. The framework should work with SQLite out of the box:
- Vector similarity computed in Python via numpy (slower but functional)
- pg_trgm fuzzy matching replaced with Python `difflib.SequenceMatcher`
- No materialized views or advanced SQL features

### 4. No Celery Required

Sara uses Celery for task scheduling. The standalone framework uses a simple `asyncio` scheduler by default:
- `asyncio.create_task()` for fire-and-forget
- `asyncio.sleep()` loops for periodic tasks (lifecycle check, decay, planning)
- Optional Celery provider for production deployments

### 5. Shell Access is Optional

The agent runs fine without shell access — it just can't execute code or interact with the filesystem. Tools are dynamically included/excluded based on `shell_enabled`. When shell is enabled, the provider determines isolation:
- `local` — direct subprocess (fastest, least safe)
- `docker` — spawns container per session (safe, needs Docker)
- `ssh` — remote execution (for dedicated compute nodes)

### 6. Context Budget Scales with Model

The compaction threshold and context refresh are driven by `max_context_tokens`:
- 8K context → compact aggressively, refresh every 2 turns, top 5 interest nodes
- 32K context → compact at 30 messages, refresh every 4 turns, top 10 nodes
- 64K+ context → compact at 40 messages, refresh every 4 turns, top 15 nodes

### 7. Event System for Integration

Rather than building a web UI into the framework, expose an event stream:

```python
@dataclass
class ACSEvent:
    type: str           # session_started, turn_completed, note_created, compaction, etc.
    timestamp: datetime
    data: dict

# Callback-based
agent.run(on_event=callback)

# Or async generator
async for event in agent.events():
    print(event)
```

This lets users build their own dashboards, send notifications, pipe to logging systems, etc.

---

## What Gets Simplified vs Sara

| Sara's ACS | Standalone Framework |
|-----------|---------------------|
| `user_id` on every table and Redis key | No user concept — one agent per instance |
| Shared `note`/`folder` tables with the main app | Own `acs_note` table, folder is just a string column |
| `episode` table for memory context | Notes ARE the memory — no separate episodic system |
| Soul loader from DB | Soul is a config string or file |
| PKG (Personal Knowledge Graph) via Neo4j | Dropped — interest graph covers this |
| Calendar intelligence | Dropped — no calendar integration |
| Stable/day layers from briefing system | Dropped — context is interest graph + notes + handoff |
| Push notifications via Expo | Event callbacks — user implements their own |
| HITL via attention queue + push | Simpler: pause session, print question, wait for stdin or API |
| Container provisioning via Proxmox API | Shell provider abstraction (local/docker/ssh) |
| `BackgroundLLMClient` with failover | `LLMProvider` with configurable retry/fallback |
| Celery beat for scheduling | `asyncio` scheduler default, Celery optional |
| Redis for state machine | In-memory or Redis (configurable) |

---

## What Gets Preserved

These are the core innovations that make ACS valuable and must carry over:

1. **Interest graph with semantic dedup** — prevents the agent from creating 50 variations of the same topic
2. **Fascination decay** — interests that aren't engaged with naturally fade, keeping the graph healthy
3. **Three cognitive modes** — forced diversity between exploration, consolidation, and reflection
4. **Session working memory** — the agent always knows what it did this session
5. **Smart compaction** — LLM-summarized checkpoints instead of silent context truncation
6. **Enriched handoffs** — next session starts with full picture of what last session accomplished
7. **Daily planning with self-assessment** — the agent plans its day considering topic diversity, stale interests, and past audit feedback
8. **Per-session + daily auditing** — continuous quality feedback loop
9. **Note dedup gate** — fuzzy title matching prevents duplicate notes
10. **Tool-calling agent loop** — real tool use (shell, files, notes, graph), not just text generation

---

## Implementation Phases

### Phase 1: Core Loop (MVP)
- `LLMProvider` (OpenAI-compatible)
- `EmbeddingProvider`
- SQLite storage with numpy vectors
- In-memory cache (no Redis)
- Interest graph (nodes, edges, dedup, decay)
- Self-model (versioned JSONB)
- Session manager with tool-calling loop
- Cognitive tools (write_note, interest graph CRUD, self-model updates)
- `SessionWorkingMemory` + turn prompts
- Basic compaction (strip narration from old turns)
- CLI: `acs init`, `acs seed`, `acs run`, `acs status`

### Phase 2: Continuity + Quality
- Smart compaction (LLM summarization)
- Enriched handoffs (Redis or file-based)
- Mode selector (exploration/consolidation/reflection)
- Per-session audit
- Daily planning
- Daily audit with dialogue
- Note dedup gate with fuzzy matching
- Research threads (open/update/resolve)
- CLI: `acs plan`, `acs audit`, `acs interests`, `acs notes`

### Phase 3: Shell + Compute
- Shell providers (local, Docker, SSH)
- Shell tools (run_command, write_file, read_file)
- Sandboxed execution with timeouts
- File tracking in session working memory
- CLI: `acs config set shell.type docker`

### Phase 4: Production Features
- PostgreSQL + pgvector storage provider
- Redis cache provider
- Celery scheduler provider
- Event streaming (SSE/WebSocket)
- Hot-swap model configuration
- Export/import knowledge base
- Multi-model configuration (different models for session/compaction/audit)
- HITL (human-in-the-loop) via API endpoint
- CLI: `acs export`, `acs live`

### Phase 5: Ecosystem
- Web dashboard (optional add-on)
- REST API for integration
- Plugin system for custom tools
- Pre-built tool packs (web search, API calls, database queries)
- Knowledge sharing between agent instances

---

## Dependencies (Minimal)

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",          # LLM + embedding HTTP calls
    "numpy>=1.26",          # Vector operations (SQLite mode)
    "aiosqlite>=0.20",      # Async SQLite
    "click>=8.1",           # CLI
]

[project.optional-dependencies]
postgres = [
    "asyncpg>=0.29",
    "sqlalchemy[asyncio]>=2.0",
    "pgvector>=0.3",
]
redis = [
    "redis[hiredis]>=5.0",
]
docker = [
    "aiodocker>=0.22",
]
celery = [
    "celery[redis]>=5.3",
]
```

---

## Configuration File Format

```yaml
# acs.yaml — dropped next to the database
models:
  session:
    url: "http://localhost:11434/v1"
    model: "qwen3:32b"
    max_context_tokens: 32768
    temperature: 0.7
  compaction:
    url: "http://localhost:11434/v1"
    model: "qwen3:8b"              # Can be smaller
  audit:
    url: "http://localhost:11434/v1"
    model: "qwen3:32b"
  embedding:
    url: "http://localhost:11434/v1"
    model: "bge-m3"
    dimension: 1024

session:
  max_minutes: 360
  cooldown_minutes: 5
  compaction_threshold: 40
  context_refresh_interval: 4
  turn_sleep:
    active: 2
    reflection: 5
    default: 3

interest_graph:
  dedup_threshold: 0.85
  bridge_threshold: 0.78
  decay_half_life_days: 14
  max_context_nodes: 15

schedule:
  timezone: "America/New_York"
  plan_hour: 7
  audit_hour: 22
  lifecycle_check_seconds: 120
  decay_hour: 2

shell:
  enabled: true
  type: "docker"                    # local | docker | ssh | none
  working_dir: "/workspace"
  timeout: 120
  # ssh-specific:
  # host: "compute-node"
  # user: "agent"
  # key: "~/.ssh/agent_key"

storage:
  type: "sqlite"                    # sqlite | postgres
  url: "sqlite:///agent.db"
  # postgres: "postgresql+asyncpg://user:pass@localhost/acs"

cache:
  type: "memory"                    # memory | redis
  # redis_url: "redis://localhost:6379/0"

soul: |
  You are a research agent with genuine curiosity.
  You prefer building prototypes over writing theoretical notes.
  When you find something interesting, dig deep — don't skim.
```

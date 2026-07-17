# Sara — Personal AI with a Mind of Her Own

Sara is a self-hosted, autonomous personal AI: one assistant with persistent episodic
memory, a personal knowledge graph, proactive (but polite) initiative, and a presence
across web, iOS, desktop, and a dedicated voice device. She doesn't just answer — she
notices, remembers, follows up, and acts on her own schedule.

Everything runs on your own infrastructure against any OpenAI-compatible LLM endpoint.

## What makes Sara different

### One Mind
All cognition flows through a single kernel rather than a pile of parallel bots:

- **Event-driven pipeline**: signals → salience scoring → deliberation → gate → action.
  Sara decides *whether* something is worth thinking about before thinking about it.
- **Interoception**: Sara senses her own body — service health, queue depth, model
  availability — and can tell you when something is wrong (or that all is clear).
- **One voice**: a style contract and linter keep every notification, chat reply, and
  journal entry in the same register. No internal monologue leaking to the user.
- **Emotional state**: a continuous mood model with momentum and decay, shaped by the
  day's events, modulating tone rather than being a gimmick.
- **Model broker**: one place that maps roles (primary, fast, embeddings) to models, so
  swapping an LLM is a single action.

### Memory that behaves like memory
- **Episodic memory** with embeddings (pgvector + HNSW), tiered retrieval, a BGE
  reranker, and a Redis working set for what's hot.
- **Composite recall scoring**: semantic similarity + recency + importance + user
  ratings (Wilson score, Thompson sampling for cold start).
- **Personal Knowledge Graph** (Neo4j + pgvector shadow table): people, places, facts,
  and life details extracted from conversation, with verification loops for uncertain
  facts and forgetting curves for stale ones.
- **Consolidation**: twice-daily reflection passes extract patterns, calibrate
  proactivity, and write the day's emotional arc.

### Proactivity with manners
- **Attention system**: a two-tier subconscious/conscious loop watches everything but
  escalates only what's learned to matter. Notifications carry a full affordance triad
  (act / snooze / never-again), and Sara learns from how you respond.
- **Anti-nag guarantees**: cooldowns, tell-once ledgers, and habituation — ignored
  items get quieter, not louder.
- **Standing orders & goals**: durable instructions and multi-day intents that an
  autonomous daemon works on between conversations.
- **Check-ins and follow-ups**: post-meeting pings and threaded follow-ups that expire
  instead of harping.

### A real body
- **Voice**: dedicated Jetson device — wake word, VAD, Whisper STT, TTS, barge-in,
  face detection for desk presence.
- **Home**: Home Assistant bridge feeds an activity state machine (11 states) that
  gates when and how Sara interrupts.
- **Devices**: iOS app (widgets, Live Activities, Siri intents, push), web app,
  desktop companion, and smart content routing that picks the right surface for the
  moment.
- **Fleet**: enroll your Linux boxes for health monitoring and read-only diagnostics;
  "check out that server" works from chat via SSH host inspection.

### Life management
- **Fitness**: conversational food logging, workout mode with live coaching (rest
  timers, PR detection, progressive overload from actual logged history), cardio +
  interval/Tabata timers, Apple Watch heart-rate meld, recovery-gated suggestions.
- **Knowledge garden**: Obsidian-style notes with `[[bidirectional links]]`, a D3
  graph view, and auto-detected connections to memories.
- **Artifacts studio**: Sara can author documents (DOCX/PDF) and interactive surfaces,
  run long workspace jobs in the background, and hand you the result.
- **Learning system**: deep-research pipeline with spaced review reminders wired into
  the knowledge graph.
- **The usual suspects**: calendar, reminders, timers, document upload with semantic
  search — all feeding the same memory.

## Architecture

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy, Celery for background cognition |
| Databases | PostgreSQL 16 + pgvector, Neo4j (PKG), Redis (cache/working set) |
| Storage | MinIO (S3-compatible) for documents |
| Frontend | React 18 + TypeScript + Vite + Tailwind |
| Mobile | Expo / React Native with native iOS targets |
| Voice | Jetson Orin Nano: OpenWakeWord → VAD → Whisper → TTS |
| LLM | Any OpenAI-compatible endpoint; roles resolved by the model broker |
| Embeddings | bge-m3 (1024-dim) via OpenAI-compatible endpoint |

An autonomous compute daemon (`acs-daemon/`) runs on a separate VM and works on Sara's
goals independently of the request/response loop, reporting back through the backend.

## Getting started

```bash
git clone <repository-url> && cd <repo>
cp .env.example .env        # fill in your endpoints and secrets

# Data services
docker compose up -d db neo4j minio redis

# Backend — always in Docker, never bare python
docker compose -f docker-compose.dev.yml up -d backend

# Frontend
docker compose up -d frontend-dev   # or: cd frontend && npm install && npm run dev
```

Web app on port 3000, API on port 8000 (`/docs` for OpenAPI).

### Configuration

All infrastructure specifics live in `.env` (never committed):

```env
# LLM + embeddings (any OpenAI-compatible endpoints)
OPENAI_BASE_URL=<your-llm-endpoint>/v1
OPENAI_MODEL=<primary-model>
OPENAI_NOTIFICATION_MODEL=<fast-model>
EMBEDDING_BASE_URL=<your-embedding-endpoint>
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Data
DATABASE_URL=postgresql+psycopg://<user>:<password>@db:5432/sara_hub
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=<password>
REDIS_URL=redis://redis:6379/0

# Identity & security
ASSISTANT_NAME=Sara
DOMAIN=<your-domain>
JWT_SECRET=<generate-a-long-random-secret>
COOKIE_DOMAIN=<your-domain>

# Notifications
NTFY_SERVER_URL=<your-ntfy-server>
NTFY_ENABLED=true
```

Timezone note: all user-facing scheduling is local-time aware (Celery crontabs run in
the configured local timezone, not UTC).

## Repo layout

```
backend/          FastAPI app — routes/, services/ (the mind lives here), tools/, models/
frontend/         React web app
ios-app/          Expo iOS app with native targets
acs-daemon/       Autonomous compute daemon (runs on its own host)
jetson/           Voice + vision device code
sara-desktop/     Desktop companion (Electron + Python sidecar)
sara-agent/       Fleet health agent + installer
gpu-cluster/      Whisper/TTS/embedding GPU services
docs/             Reference docs, including the self-model docs Sara reads at runtime
forge-data/       Synthetic-conversation training harness for memory behavior
```

## Status

Personal project, moving fast, batteries very much included. Expect sharp edges,
a large monolith mid-refactor (`backend/app/main_simple.py`), and design docs that
occasionally outrun the code.

## License

MIT — see LICENSE.

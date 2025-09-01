# Human‑Like Memory Stack — Implementation Tasks

Goal: Introduce a Redis working memory + Postgres/pgvector episodic store + lightweight graph-in-Postgres with nightly consolidation, while keeping Sara-Jarvis structure intact and de-emphasizing Neo4j by default.

---

## 0) Infra And Volumes

- [ ] Create VM folders and mount points (ensure permissions):
  - [ ] `/data/postgres` for Postgres data
  - [ ] `/data/redis` for Redis data (AOF)
  - [ ] `/data/app` for repo, logs, configs
- [ ] Add `README` note explaining volumes and backup cadence.

---

## 1) Docker Compose (orchestration)

Edit root `docker-compose.yml` (or add `docker-compose.override.yml`) to reflect:

- [ ] Postgres 16 + pgvector
  - [ ] Service `db`: image `pgvector/pgvector:pg16`
  - [ ] Volumes: map `/data/postgres:/var/lib/postgresql/data`
  - [ ] Healthcheck: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`
  - [ ] Do not bind Postgres to a public interface; keep internal only.
- [ ] Redis 7 (working memory)
  - [ ] Service `redis`: image `redis:7-alpine`
  - [ ] Command: `--appendonly yes --maxmemory 6gb --maxmemory-policy allkeys-lfu`
  - [ ] Volumes: map `/data/redis:/data`
- [ ] Neo4j optional
  - [ ] Gate behind profiles: `profiles: ["graph-neo4j"]` so it doesn’t start by default.
- [ ] Backend / Frontend
  - [ ] Keep ports as-is; ensure `DATABASE_URL` points to `db` service.
  - [ ] Add memory env (see Section 5) without hardcoded IPs.

Validation
- [ ] `docker compose up -d db redis` → healthy
- [ ] `docker compose up -d backend` → healthy

---

## 2) Postgres Schema (Alembic)

Create a new Alembic migration in `backend/alembic/versions/` named like `xxxx_memory_stack.py`:

- [ ] Ensure extension
  - [ ] `CREATE EXTENSION IF NOT EXISTS vector;`
  - [ ] If supported, prefer `halfvec` type; otherwise fallback to `vector`.
- [ ] Tables
  - [ ] `memory_trace` (
        id uuid pk, user_id uuid, content text, role text,
        created_at timestamptz default now(), salience real,
        source jsonb, meta jsonb)
  - [ ] `memory_embedding` (
        trace_id uuid fk → memory_trace(id), head text,
        vec halfvec(768) or vector(768), created_at timestamptz default now())
  - [ ] `memory_edge` (
        src uuid, dst uuid, type text, weight real,
        ts timestamptz default now(), primary key(src,dst,type))
- [ ] Indexes
  - [ ] HNSW on recent embeddings: `CREATE INDEX IF NOT EXISTS ix_mem_semantic_hnsw ON memory_embedding USING hnsw (vec);`
  - [ ] btree on `memory_trace(created_at)`, `memory_trace(salience)`
  - [ ] GIN on `memory_trace(meta)`
- [ ] Optional: monthly partitioning for `memory_embedding` and IVF_* index usage on warm/cold partitions.

Validation
- [ ] `alembic upgrade head` succeeds
- [ ] `SELECT extname FROM pg_extension WHERE extname='vector'` returns row

---

## 3) Backend Services (minimal, surgical)

Files under `backend/app/services` (create if missing):

- [ ] Embedding Service updates (`embedding_service.py` or within existing service)
  - [ ] Support `halfvec` storage where available (or fallback to `vector`).
  - [ ] Support multiple heads: `semantic|entity|situation`.
  - [ ] Normalize to configured dimension (`EMBEDDING_DIM`).
- [ ] Memory Service (`memory_service.py`)
  - [ ] Write path: create `memory_trace`, store one or more `memory_embedding` rows per head.
  - [ ] Retrieval pipeline:
    - [ ] 1) Redis recency (working set / focus buffer)
    - [ ] 2) Postgres HNSW in hot tier (recent N days)
    - [ ] 3) 1–2 SQL hops via `memory_edge` for related items
    - [ ] 4) Optional re-rank by recency + salience
- [ ] Consolidation Job (`nightly_dream_service.py`)
  - [ ] Summarize prior day into `memory_trace` with type/role marker (e.g., `summary`).
  - [ ] Extract triples/edges and insert into `memory_edge`.
  - [ ] Downshift old traces: move embeddings to warm partitions; drop extra heads on low-salience rows.

Validation
- [ ] Unit tests for embedding normalization and multi-head writes.
- [ ] Manual run of consolidation task without errors.

---

## 4) API Routes (FastAPI)

Add to `backend/app/routes` (new file `memory.py`) and include in `main.py` or `main_simple.py`:

- [ ] `GET /memory/recall` (params: `q`, `k`, `heads`, `time_window`) → returns ordered traces with scores and optional edges used.
- [ ] `POST /memory/consolidate` (admin only) → triggers one-shot consolidation.
- [ ] `POST /memory/forget` (body: scope/id) → deletes trace + embeddings + edges; returns tombstone result.

Validation
- [ ] Swagger docs show new routes.
- [ ] 200 responses with expected shapes.

---

## 5) Environment and Settings

Update `.env.example` (no hardcoded IPs):

```
# Memory backends
GRAPH_BACKEND=postgres
MEMORY_HOT_DAYS=30
MEMORY_K=10
MEMORY_SALIENCE_WRITE_THRESHOLD=0.35

# Embeddings
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=768
EMBEDDING_PRECISION=fp16

# Redis (working memory)
REDIS_URL=redis://redis:6379/0
REDIS_FOCUS_TTL_SECONDS=172800

# Postgres
DATABASE_URL=postgresql+psycopg://sara:***@db:5432/sara_hub
```

- [ ] Backend reads new env vars with sane defaults.
- [ ] Add feature flag `GRAPH_BACKEND=postgres|neo4j` (default `postgres`).

---

## 6) Data Migration (incremental, safe)

- [ ] Back up current Postgres volume.
- [ ] Run Alembic migration to create new tables.
- [ ] One-time script `scripts/migrate_episodes_to_memory.py`:
  - [ ] Read existing `episodes` (and related) → insert into `memory_trace`.
  - [ ] Generate embeddings for selected heads → `memory_embedding`.
  - [ ] Derive initial `memory_edge` based on same-day/topic/participants.
- [ ] Verify counts and sampling queries.

---

## 7) Performance Knobs

- [ ] Postgres tuning via mounted config or env:
  - [ ] `shared_buffers=6GB`, `effective_cache_size=18GB`
  - [ ] `work_mem=32MB`, `maintenance_work_mem=2GB`
  - [ ] `wal_compression=on`, `max_wal_size=6GB`
- [ ] Redis maxmemory 4–6 GB with LFU policy.
- [ ] Schedule nightly job: summarize, move cold vectors to warm partitions, prune low salience.

---

## 8) Tests (repo root `test_*.py`)

- [ ] `test_memory_recall.py` — end-to-end latency <100 ms on hot items.
- [ ] `test_consolidation.py` — creates daily summary, edges, downshifts.
- [ ] `test_forget.py` — deletes trace + embeddings + edges; verifies no leaks.
- [ ] `test_notes_kg.py` — existing note save still suggests connections using Postgres edges.

---

## 9) Rollout Sequence

- [ ] Add `docker-compose.override.yml` mapping `/data` volumes.
- [ ] Bring up `db` + `redis` only; run `alembic upgrade head`.
- [ ] Run migration script; validate.
- [ ] Start `backend` with `GRAPH_BACKEND=postgres`; verify health + `/settings/ai/test`.
- [ ] Start `frontend`; verify Notes / Memory / Search flows.
- [ ] Optionally start `neo4j` via profile for graph viz parity.

---

## Acceptance Criteria

- [ ] Embeddings are stored as `halfvec(768)` (or `vector(768)` fallback) with HNSW index for hot tier.
- [ ] Redis working set improves recall for recent context.
- [ ] `/memory/recall` fuses Redis + Postgres HNSW + edges and returns relevant results.
- [ ] Nightly consolidation emits day summaries and edges, and compacts older vectors.
- [ ] No hardcoded IPs; AI settings are managed via `/settings/ai` and survive restarts (either via env or persisted config).


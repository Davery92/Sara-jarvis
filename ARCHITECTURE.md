# Architecture Overview

This document explains how the app is organized, what databases it uses, and how data flows through core features.

## App Overview
- Backend: FastAPI service in `backend/app` with routers under `routes/`, business logic in `services/`, and DB setup in `db/`.
- Frontend: Vite + React + TypeScript in `frontend/` that calls the API (see `docker-compose.yml` for local orchestration).
- Background Jobs: `services/scheduler.py` runs periodic tasks (reminders/timers every minute, daily/weekly memory compaction) when `app/main.py` starts.
- External Services: OpenAI‑compatible LLM + embeddings, Redis cache (web search), SearXNG metasearch, optional reranker, MinIO/S3 for document storage, Neo4j for the knowledge graph, ntfy for notifications.

## Data Persistence
Primary DB is PostgreSQL (pgvector enabled); SQLite dev paths have been removed.

PostgreSQL (SQLAlchemy models in `backend/app/models`):
- Users: `app_user` (id, email, password_hash).
- Notes & Folders: `note` (title, content, `embedding` Vector(1024), `user_id`, optional `folder_id`), `folder` (hierarchy via `parent_id`, `sort_order`).
- Documents: `document` (title, storage_key, mime_type, meta), `doc_chunk` (chunk_idx, text, breadcrumb, `embedding`).
- Calendar & Reminders: `event` (title, starts_at/ends_at, location, description), `reminder`, `timer`.
- Memory System: `episode` (source, role, content, meta, importance), `memory_vector` (per‑chunk text + embedding, episode_id), `memory_hot` (recent access tracking), `semantic_summary` (daily/weekly summaries with embedding + coverage JSON).
- Fitness: `fitness_profile`, `fitness_goal`, `fitness_plan`, `workout` (optional link to `event`), `workout_log`, `morning_readiness`, `fitness_idempotency`.

Neo4j Knowledge Graph (see `services/neo4j_service.py`, `services/enhanced_neo4j_schema.py`):
- Nodes: `User`, `Content`, `Chunk`, `Entity`, `Topic`, `Tag`, `TemporalInfo`, `ActionItem`.
- Relationships: `(:User)-[:CREATED]->(:Content)`, `(:Content)-[:HAS_CHUNK]->(:Chunk)`, `(:Content)-[:CONTAINS_ENTITY]->(:Entity)`, `(:Content)-[:HAS_TOPIC]->(:Topic)`, `(:Content)-[:HAS_TAG]->(:Tag)`, `(:Content)-[:HAS_TEMPORAL_INFO]->(:TemporalInfo)`, `(:Content)-[:HAS_ACTION_ITEM]->(:ActionItem)`.

## How It Works (Key Flows)
- Auth & Sessions: `routes/auth.py`; dependencies in `core/deps.py` enforce user context per request.
- Notes: `POST /notes` creates a note, generates a 1024‑d embedding, and stores it in Postgres for semantic search.
- Documents: `POST /docs/upload` ingests a file, extracts text, chunks it, embeds each chunk, and saves `doc_chunk` rows; `/docs/search` uses pgvector `<=>` for similarity.
- Memory: Chat, tool outputs, and system events become `episode` rows; content is chunked to `memory_vector`. Scheduler creates `semantic_summary` daily/weekly using the LLM + embeddings.
- Knowledge Graph: Content intelligence stores enriched nodes/edges in Neo4j; `routes/knowledge_graph.py` exposes graph queries and filters.
- Search: `services/search_service.py` queries SearXNG, caches pages in Redis, optionally reranks (cross‑encoder or bi‑encoder via embeddings).
- Fitness: Planner/scheduler generates `workout` prescriptions and may place `event` calendar slots; readiness input adjusts daily recommendations.

## Environments
- Dev/Full API: `uvicorn app.main:app --reload` after `pip install -r backend/requirements.txt`.
- Docker: `docker-compose up -d` to run API, DBs, and services together.

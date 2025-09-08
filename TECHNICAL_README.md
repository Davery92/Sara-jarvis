# Sara Hub — Technical README

This document provides an in‑depth technical overview of the Sara Hub application: architecture, key modules, configuration, deployment, and troubleshooting.

## Overview

- Monorepo with a FastAPI backend and a Vite/React/TypeScript frontend.
- Personal AI assistant: chat with tool calling, memory, notes, reminders, calendar, documents, and web search.
- OpenAI‑compatible model endpoints (Ollama or compatible) for chat and embeddings.
- Persistent Postgres (with pgvector) via Docker Compose; SQLite available for lightweight setups.

## Repository Structure

- `backend/app`
  - `main_simple.py`: Full single‑file FastAPI app with routes, services, models, streaming SSE chat, tools integration, memory, and schedulers.
  - `main.py`: Modular FastAPI entry when using `app/routes/` and service modules.
  - `routes/`: Modular routers (auth, chat, notes, reminders, memory, docs, search).
  - `core/`: Config (`config.py`), shared LLM client (`llm.py`), DB base/session.
  - `services/`: Search service (SearXNG), nightly/dream services, vulnerability, etc.
  - `tools/`: Tool system (memory, notes, reminders, timers, calendar, knowledge_graph, web_search, open_page). Global registry in `tools/registry.py`.
  - `db/`: SQLAlchemy engine/session and model glue; alembic present for migrations.
- `frontend/src`
  - `components/`: Chat UI (SSE streaming), sprite, knowledge graph, privacy, etc.
  - `pages/Settings.tsx`: AI/embedding configuration UI.
  - `api/client.ts`: HTTP client, typed endpoints including `/settings/ai`.
  - `config.ts`: Computes `APP_CONFIG.apiUrl` from env or location.
- Ops & scripts
  - `docker-compose.yml`: Full stack (backend, frontend, db, redis, minio, neo4j).
  - `backend/Dockerfile`: Python 3.11 slim with cached pip layers (BuildKit).
  - `start-production.sh`: Convenience launcher; honors env like `DATABASE_URL`, `CORS_ORIGINS`, `SEARXNG_BASE_URL`.

## Key Data Flows

- Chat streaming (SSE):
  - POST `/chat/stream` accepts messages; backend streams `data: {type, data}` events.
  - Frontend buffers by `\n\n` event boundaries to parse JSON lines robustly.
- Memory traces:
  - Frontend best‑effort POSTs `/memory/trace` for user and assistant messages.
  - Backend stores trace and (if available) embeddings; if embedding fails, trace still persists.
- Tools & multi‑round calls:
  - Backend’s `SimpleLLMClient.chat_with_tools` supports multiple tool rounds (up to 10), streaming intermediate events (`tool_calls_start`, `tool_executing`, `thinking`).
  - Tools come from `app.tools.registry.tool_registry.get_openai_schemas()` and include `web_search` and `open_page`.

## Configuration

- Primary env variables (see `.env.example`, `backend/.env`, `DEPLOYMENT.md`):
  - `OPENAI_BASE_URL` (default: `http://100.104.68.115:11434/v1`)
  - `OPENAI_MODEL` (default: `gpt-oss:120b`)
  - `EMBEDDING_BASE_URL` (default: `http://100.104.68.115:11434`)
  - `EMBEDDING_MODEL` (default: `bge-m3`), `EMBEDDING_DIM` (default: `1024`)
  - `SEARXNG_BASE_URL` (default: `http://10.185.1.8:4000`) for web_search tool
  - `REDIS_URL` for result/page caching and memory recency buffer
  - `DATABASE_URL` (Postgres recommended in production)
  - `CORS_ORIGINS` and optional `CORS_ALLOW_REGEX`
- CORS defaults accept both:
  - Dev: `http://10.185.1.180:3000`
  - Prod: `http://10.185.1.188:3000`
  - Localhost, and `https://sara.avery.cloud`.
- Settings page (`/settings`):
  - Prefilled defaults for both chat and embeddings.
  - Backend normalizes/validates on update:
    - `openai_base_url` must include http(s) and end with `/v1`.
    - `embedding_base_url` must include http(s) and must NOT end with `/v1` (service appends `/v1/embeddings`).

## Backend Architecture Highlights

- Models: SQLAlchemy ORM models for users, notes, timers, reminders, documents, conversations, episodic memory, and memory embeddings (pgvector).
- Memory system:
  - Traces (`memory_trace`) + per‑head embeddings (`memory_embedding`).
  - Recall via pgvector or Python fallback.
  - Consolidation endpoint `/memory/consolidate` creates summaries and edges.
- LLM integration:
  - Chat and streaming via OpenAI‑compatible `/chat/completions` with tool support.
  - Embeddings via `/v1/embeddings` (EmbeddingService) and `core/llm.py` (shared primitive embedding path).
  - Emotional analyzer uses fast model endpoint and falls back cleanly if misconfigured.
- Tools:
  - `web_search`: SearXNG for search + reranking (optionally uses embedding service).
  - `open_page`: fetch+readability extraction + snippet.
  - Notes/reminders/timers/calendar/knowledge_graph toolset for internal data.
- Health/diagnostics:
  - `GET /tools`: enumerate available tools (names/descriptions).
  - `GET /search/health`: SearXNG connectivity and reranker base/model.
  - `GET /health`: basic API ping.

## Frontend Architecture Highlights

- Vite + React + TypeScript, Tailwind UI.
- SSE streaming chat with incremental updates and sprite animations.
- Settings UI integrated with backend `/settings/ai`.
- `APP_CONFIG.apiUrl` derived from `VITE_API_URL` or window hostname.

## Deployment

- Docker Compose (recommended):
  - Services: `backend`, `frontend`, `db` (pgvector), `redis`, `minio`, `neo4j`.
  - Volumes: named volumes persist Postgres/MinIO/Neo4j data; avoid `docker compose down -v` in production.
  - Key env overrides:
    - `OPENAI_BASE_URL`, `EMBEDDING_BASE_URL`, `SEARXNG_BASE_URL`, `DATABASE_URL`, `CORS_ORIGINS`.
- Local scripts:
  - `start-production.sh` honors existing `DATABASE_URL` and sets defaults for CORS and SearXNG/Redis.
- Docker build caching:
  - `backend/Dockerfile` uses BuildKit cache for pip installs (`DOCKER_BUILDKIT=1`).
  - `backend/.dockerignore` keeps build context stable to reuse dependency layers.

## Development

- Backend dev:
  - `cd backend && pip install -r requirements.txt`
  - `python3 app/main_simple.py` or `uvicorn app.main_simple:app --reload`
- Frontend dev:
  - `cd frontend && npm run dev`
- End‑to‑end with Docker:
  - `docker compose up -d` (set env in a `.env` file or shell)

## Testing

- Integration tests in repo root: `test_*.py` scripts call running APIs.
- Example: `python3 test_full_intelligence_pipeline.py`
- Keep tests idempotent; prefer using `BASE_URL` env.

## Troubleshooting

- Embeddings URL errors:
  - Ensure `embedding_base_url` includes `http://` or `https://` and does not include `/v1`.
  - Backend now validates and normalizes this; Settings UI prevents blank overwrites.
- SSE parsing warnings:
  - Frontend buffers by `\n\n` boundaries; malformed partial lines no longer cause noisy logs.
- `/memory/trace` 502s:
  - Backend now stores traces even if embeddings are temporarily unavailable.
- Web search tool issues:
  - Verify `SEARXNG_BASE_URL` and `GET /search/health` response.
  - Check network access from backend container to SearXNG.
- CORS:
  - Defaults allow `10.185.1.180`, `10.185.1.188`, localhost, and `sara.avery.cloud`.
  - Override with `CORS_ORIGINS` or `CORS_ALLOW_REGEX`.

## Security

- Secrets via env only; never commit live credentials.
- Cookies configured for domain with `SameSite=Lax` by default; adjust for your deployment.
- Validate CORS and auth for any new routes.

## Notable Endpoints

- `GET /` — root message
- `GET /health` — liveness
- `GET /tools` — list registered tools
- `GET /search/health` — SearXNG/reranker health
- `POST /chat/stream` — SSE streaming chat
- `POST /memory/trace` — store memory trace (best‑effort embeddings)
- `GET /memory/recall` — semantic/temporal retrieval
- `GET /settings/ai`, `PUT /settings/ai`, `POST /settings/ai/test` — AI config

## Production IPs and Defaults

- Prod server: `10.185.1.188`
- Dev server: `10.185.1.180`
- Default model host: `100.104.68.115:11434` (chat `/v1`, embeddings base root)

---

For more, see `DEPLOYMENT.md` and repo inline docs. This README is intended to accelerate onboarding, debugging, and safe deployment.

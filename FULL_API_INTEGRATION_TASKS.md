# Full API Integration Tasks (Remove SQLite Dev Path)

Goal: Remove the `main_simple.py` dev server and all SQLite fallbacks so the app always runs the full API on PostgreSQL with pgvector.

## 1) Remove Dev Server + SQLite Fallbacks
- Delete `backend/app/main_simple.py` and any imports of it.
- Search and remove SQLite-specific conditionals and compat fields:
  - Look for: `sqlite`, `check_same_thread`, `PGVECTOR_AVAILABLE`, `SENTENCE_TRANSFORMERS_AVAILABLE`, `is_processed`, `document_chunk` JSON embeddings.
- Remove `run-local.sh` SQLite setup lines or replace with Postgres envs.

## 2) Consolidate Functionality Into Full API
- Dreaming service: replace `from app.main_simple import dreaming_service` usages (e.g., `test_dream_cycle.py`) with calls into `app/services/nightly_dream_service.py` or add minimal route in `routes/memory.py` that proxies to the service.
- Ensure any models that lived only in `main_simple.py` are either not needed or already represented in `backend/app/models/*`.

## 3) Configuration and Env
- Ensure `.env.example` has a valid Postgres `DATABASE_URL` (no SQLite). Example:
  - `DATABASE_URL=postgresql+psycopg://sara:sara123@postgres:5432/sara_hub`
- Verify `app/db/session.py` creates Postgres extensions (`uuid-ossp`, `vector`) at startup. Keep this path and remove doc references to SQLite.

## 4) Migrations and DB Init
- Use Alembic to align schema: `cd backend && alembic upgrade head`.
- If pgvector not present, add to Postgres and re-run `create_tables()`.

## 5) Update Docs and Scripts
- Edit references to dev server:
  - `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `FINAL-SETUP.md` → remove `python3 app/main_simple.py`; standardize on `uvicorn app.main:app --reload` and Docker Compose.
- Remove or rewrite SQLite migration notes in docs.

## 6) Tests
- Update tests to hit running API or direct services:
  - Replace imports from `main_simple` in: `test_dream_cycle.py` and docs referencing it.
  - Ensure `BASE_URL` is configurable and tests run against full API.

## 7) Validation Checklist
- API boots with `uvicorn app.main:app --reload`.
- `create_tables()` succeeds and pgvector extension exists.
- Notes/docs embeddings write/read correctly; `/docs/search` returns results.
- Scheduler runs daily/weekly jobs without errors.
- All `test_*.py` pass against the full API.

## 8) Cleanup
- Remove dead code/flags tied to dev-only paths.
- Delete any remaining SQLite artifacts (`sara_hub.db`, helper scripts).


# Repository Guidelines

## Project Structure & Module Organization
- `backend/app`: FastAPI service (`main.py`, routes/, services/, db/).
- `frontend`: Vite + React + TypeScript app (`src/`, Tailwind).
- Root tests: executable Python integration scripts `test_*.py`.
- `scripts/`, `docker-compose.yml`, `.env.example` for local setup.
- Data/logs: `uploads/`, `logs/` (avoid committing large artifacts).

## Build, Test, and Development Commands
- Backend: set env, install deps, run API
  ```bash
  cd backend && pip install -r requirements.txt
  python3 app/main_simple.py   # dev server with scheduler
  # or: uvicorn app.main:app --reload
  ```
- Frontend: dev/build/lint
  ```bash
  cd frontend
  npm run dev     # local dev
  npm run build   # production build
  npm run lint    # ESLint checks
  ```
- Docker (all services): `docker-compose up -d`
- Integration tests (examples): `python3 test_full_intelligence_pipeline.py`

## Coding Style & Naming Conventions
- Python (backend):
  - PEP 8, 4‑space indent, type hints where practical.
  - Files/functions: `snake_case`; classes: `PascalCase`.
  - Place HTTP handlers in `backend/app/routes`, business logic in `backend/app/services`.
- TypeScript/React (frontend):
  - Follow ESLint rules; components `PascalCase.tsx`, hooks `useSomething.ts`.
  - Use Tailwind utility classes; co-locate component styles.

## Testing Guidelines
- Tests are Python scripts at repo root named `test_*.py` that call running APIs.
- Keep tests idempotent and configurable (prefer `BASE_URL` via env or constant).
- Add new tests alongside existing ones; name with clear intent (e.g., `test_insights_api.py`).
- For backend unit tests, prefer pure functions in services; mock external systems.

## Commit & Pull Request Guidelines
- Commits: concise, imperative summary (e.g., "add habit streak API"), group related changes.
- Branches: `feat/...`, `fix/...`, `chore/...` when practical.
- PRs should include:
  - Clear description and rationale; link issues/tasks.
  - Screenshots/GIFs for frontend changes.
  - Notes on migrations, env vars, or breaking changes.
  - Updated docs (README/DEPLOYMENT) when behavior changes.

## Security & Configuration Tips
- Copy `.env.example` to `.env`; never commit secrets or databases.
- Key vars: `DATABASE_URL`, `NEO4J_*`, `OPENAI_*`, `EMBEDDING_*`, `NTFY_*`.
- Validate CORS and auth on new routes; prefer dependency‑injected services.


# CLAUDE.md

Guidance for Claude Code working in this repository. The audit is a map; the code
is the truth. If this file disagrees with the tree, the tree wins — fix this file.

## 1. What Sara is

A personal AI with persistent memory, autonomous cognition, and presence on
several surfaces at once. She is not a chat wrapper: background cognition runs
whether or not anyone is looking, and it can decide to speak first.

Monorepo: `backend/` (FastAPI), `frontend/` (React+Vite web), `ios-app/`
(Expo/React Native + Watch + native modules), `sara-desktop/`, `jetson/`
(voice+vision), `pi-dashboard/`, `workbench-canvas/`, `sara-agent/` (fleet
agent), `acs-daemon/` + `acs-tool-runner/` (autonomous compute), `embedding-service/`.

## 2. Commands

**Never start the backend locally. It runs only in Docker.** There is no
`--reload` over the bind mount, so after editing code you must rebuild and
restart before anything you observe at runtime means what you think.

```bash
# Production is operated through ONE wrapper. Read RECOVERY.md first.
scripts/sara-prod verify          # check, change nothing (default)
scripts/sara-prod ps | logs [svc]
scripts/sara-prod up | restart [svc...]
scripts/sara-prod cutover         # move onto a NEW pinned generation
scripts/sara-prod readiness       # the four-capability probe

# Getting a code change into production = a new generation, never a rebuild.
# rebuild_backend.sh / quick_rebuild_backend.sh now REFUSE; they used to unpin it.
#   1. commit it   2. refreeze_reliable_candidate.sh <snap>
#   3. build_reliable_candidate_image.sh <snap> <tag>
#   4. rehearse_reliable_release.sh <tag>   -> REHEARSAL PASSED
#   5. update EXPECT_* in sara-prod + the image/path in the pin overlay
#   6. scripts/sara-prod cutover

# Dev stack (NOT for production — see §3 and the header of docker-compose.dev.yml)
docker compose -f docker-compose.dev.yml up -d db neo4j redis minio embeddings
docker compose -f docker-compose.dev.yml build backend
docker compose -f docker-compose.dev.yml logs -f backend

# Frontend
cd frontend && npm run dev        # port 3000
cd frontend && npm run build      # npm run lint, npm run preview

# Database (credentials in .env, never in docs)
docker compose -f docker-compose.dev.yml exec db psql -U sara -d sara_hub
```

Tests — all pytest runs must go through a disposable stack; `tests/env_guard.py`
aborts collection otherwise (see §7):

```bash
docker compose -f docker-compose.test.yml up -d --wait test-db test-redis
./backend/scripts/provision_test_schema.sh
cd backend && python -m pytest                      # testpaths = tests
cd backend && python -m pytest tests/replay         # conversation replay harness
node ios-app/scripts/check-workout-contract-parity.mjs   # workout wire contract, 4 copies
python backend/tests/assistant_acceptance/readiness_probe.py   # run INSIDE the api container
```

That readiness probe — not `/health` — is the deploy gate. It writes to the
database, discloses every row it creates, and removes what it created.

## 3. Runtime topology

**`docker-compose.dev.yml` is the authoritative topology**, and the only
non-overlay compose file at the repo root. 15 services: `backend`, `db`
(pgvector/pg16), `neo4j`, `redis`, `minio`, `embeddings`, `frontend`, `canvas`,
`pi-dashboard`, `acs-tool-runner`, and five celery services.

There is deliberately **no `docker-compose.yml`** any more — archived 2026-10-01
to `deploy/archive-compose/docker-compose.legacy.yml`. It was the file a bare
`docker compose` resolved, into project `jarvis` (production), with a
working-tree `build:` and no pin — so `docker compose up -d backend` reproduced
the 2026-09-29 incident in one command. A bare `docker compose` here now fails
with "no configuration file provided". That is intended: name your files, or use
`scripts/sara-prod`.

Celery lanes (queues are the contract, not the service names):

| service | concurrency | queues |
|---|---|---|
| `celery-worker` | 4 | cognitive, health, input, maintenance, low_priority, reflection, dispatch |
| `celery-critical` | 2 | critical |
| `celery-acs` | 2 | acs |
| `celery-david-priority` | 1 | david_priority |
| `celery-beat` | — | `app.celery_beat:DBScheduler` |

Beat reads the `scheduled_job` table (101 rows, 99 enabled), not a Python
schedule dict. Crontabs there are **ET**. `DBScheduler` marks
`last_status='success'` at DISPATCH time, so a green row does not mean the task
succeeded — see `app/celery_signals.py`.

Off-box: Mac Studio LLM host via MTPLX (chat lane :8082, background :8081), GPU
host `her` at 10.185.1.8 (embeddings/ASR/TTS), Jetson (voice+vision, separate
repo), Sara VM daemon at 10.185.1.176, and two **bare systemd services on this
host** running from the working tree — `sara-ha-listener.service` and
`sara-scheduled-home.service` (`app/workers/ha_listener.py`,
`app/workers/scheduled_home_worker.py`). Nothing imports those two and no compose
file names them, so an import/compose grep will wrongly conclude they are dead.
They have `Restart=always`.

### Production is pinned

`docker-compose.incident-recovery.yml` pins the API and all five celery services
to `sara-reliable-candidate:20260929` with `app/` and `alembic/` mounted
**read-only** from a frozen tree outside this repo. The pin lives in an overlay,
and an overlay only applies when it is named — any `docker compose -f
docker-compose.dev.yml up -d` typed without it puts the mutable working tree into
production, which is what the 2026-09-29 incident was. Use `scripts/sara-prod`.

## 4. Backend architecture

- `app/main_simple.py` — ~12,350 lines, 18 `@app.` endpoints. What still lives
  here, and why: `/chat/stream` and `/chat/models`; the twelve settings and
  Codex-OAuth endpoints, which REASSIGN the chat globals at runtime to
  hot-reload the client and so cannot move until that config lives in
  `app/core/app_state.py`; `/api/pi-dashboard/voice/chat` and `/voice/fast`,
  which call chat-turn internals; and the startup/shutdown hooks. Each blocked
  group carries a `blocked-on:` comment saying exactly what pins it.
- `app/routes/` — 105 route modules, registered in `main_simple`. New
  registrations go OUTSIDE any try/except (gotcha 3 below); the older ones are
  wrapped, which is how a router can vanish silently.
- `app/services/` — 355 modules. This is where the system actually is.
- `app/tools/` — 272 registered tools across 46 categories in
  `app/tools/registry.py`. `tool_retrieval.MAX_TOOLS_PER_CALL = 35` caps the per-turn
  menu. `tool_mutation.gate_mutating_tools` filters mutating tools at the final
  tool-schema boundary; it has several call sites (the post-branch chat call, the
  voice path, and a mid-turn re-gate), so a change to one is not a change to all.
- **Auth dependencies.** `core.deps` exports two: `get_current_user` (async,
  and it also accepts an `X-Device-Token`) and `get_current_user_sync` (no
  device token, opens its own connection for the revocation check). They are
  not interchangeable, and picking the async one for a route that used the sync
  one silently BROADENS that route's authentication. Route modules import
  whichever they already used; nothing imports auth from `main_simple` any more.

## 5. Cognitive systems

**Event spine → salience → deliberation.** Events land in the world-state
pipeline, `salience` scores them (threshold 1.5), the observation log feeds
deliberation, and a gate decides whether anything reaches David. Tables:
`agent_run_log`, `notification_log`.

**Execution boundary.** A mutating tool call has to get through four layers, and
they are separate on purpose: `tool_mutation` (is there action evidence at all),
`operation_contract` (which operation was actually requested — a reschedule
request is not a cancellation authorization), `reference_resolution` /
`target_authorization` (which owner-scoped row, resolved once and reused), and
`action_receipt_service` (a durable row per call that executed, which
`verify_action` reads back). `outcome_grounding` renders confirmations from
committed outcomes, because a prompt rule cannot stop a model from claiming it
did something.

**Mind V2** — judge → compose → review → deliver, with `say_candidate` as the
single mouth. Review kills roughly 89% of candidates.

**Kernel / One Mind** — the four-state consolidation absorbing deliberation,
check-ins and ACS. Check new features against its six invariants before adding a
parallel brain; there have been two before.

**Standing orders, directives, quiet mode** — user-set rules with a 5-minute
undo. Directives are standing ("never bring up X"); ActivityPub is permanently
blocked via `sara_interest.blocked`, not deleted.

## 6. Memory stack

- **Episodes** — pgvector with an HNSW index on `episode.embedding`, composite
  retrieval (similarity + recency + importance + frequency), BGE reranker, Redis
  working set, nightly consolidation. Enrichment is incremental behind each
  conversation's `enriched_through_*` watermark.
- **PKG** — Neo4j plus a `pkg_embedding` pgvector shadow. It **refuses to hold
  body measurements**: `health_metric` is the only authority for David's numbers.
- **Notes garden** — `[[Note Title]]` bidirectional links, `note_connection`
  rows typed reference/semantic/temporal, auto-detected on save.
- **World state** — continuously maintained `WorldThread` projections; chat reads
  `app/services/world_state/chat_facts.py`, the World Context page reads the same renderer.
- **Narrative** — diary into `day_replay_cache.summary`, dreams. The user-facing
  journal is `journal_note`, not the internal `thought`.

## 7. Critical gotchas

1. **The running container lags the working tree.** No `--reload`. Check the
   startup timestamp (and `/debug/runtime`, which hashes modules at import and
   compares against disk) before concluding anything about runtime behavior.
2. **Restart safety is a (source, schema) pair.** Both halves, or the service
   does not work. Gate on `readiness_probe.py`. Never `alembic downgrade` as a
   recovery step — it is an outage, not a rollback. `/health` returns 200 for a
   service nobody can log into.
3. **Route registration must live OUTSIDE try/except.** A swallowed import error
   silently drops an entire router.
4. **Two `Base` instances:** `declarative_base()` is called in both
   `app/db/base.py` and `app/main_simple.py:602`, so a model's table can be
   registered on either metadata. Any model mapping to an already-registered
   table needs `extend_existing=True` (50 modules do). Load-bearing until the
   monolith refactor ends; do not "fix" it in passing. (An older note about two
   competing `Document` models is stale — `app/models/doc.py` is now the only one
   mapped to `document`.)
5. **pgvector params:** `CAST(:param AS vector)`, never `:param::vector`.
6. **redis is pinned <5.0.0:** `.close()`, not `.aclose()`.
7. **All user-facing times are ET** via `app.core.timezone`. No bare
   `datetime.now()` — in this container it lands 4-5h early. Celery crontabs are
   ET. `scripts/check_naive_datetime.py` guards this.
8. **Tests must run against a disposable stack.** `tests/env_guard.py` requires
   `SARA_TEST_ENV=disposable`, non-production credentials and an allowlisted host,
   and fails closed. Bring test stacks up via `backend/scripts/disposable_compose.sh`,
   never with the default project name, which is production's.
9. **Local-first LLM policy.** Qwen does all agentic and background work; Claude
   is the chat persona only. Pass `enable_thinking: False` nested in
   `chat_template_kwargs` or `content` comes back empty. Always set `max_tokens`.
10. **Qwen3.8-27B + MTP speculative decoding corrupts tool-bearing replies.**
    `LOCAL_GENERATION_MODE` defaults to `ar` deliberately.

## 8. Where things live

- **Schema filenames are not intuitive** (all under `backend/app/schemas/`):
  `auth.py`, not user.py, holds `UserCreate`; `Timer*` is in `reminders.py`;
  `UserSettings` is in `chat.py`; `UserProfile*` is in `insights.py`.
- **Frontend views:** `frontend/src/navigation/views.ts` defines `AppView`;
  `frontend/src/App.tsx` is the entry point and routing is view-state, not React
  Router. API base URL is `frontend/src/config.ts`.
- **Plans and audits:** `docs/plans/`. Incident records in
  `docs/plans/incidents/`. `RECOVERY.md` at the root is the production procedure.
- **Near-twin module names** (renamed 2026-09-30 because they were one word
  apart and unrelated): `activity_suggestions.py` is the pattern-based "you
  usually gym on Thursdays" nudger — its persisted identity string is still
  `"predictive_engine"`, deliberately, so habituation cooldowns keep matching —
  while `prediction_engine.py` is the predictive-coding system.
  `memory_rank_sql.py` is read-path ranking SQL; `memory_scorer.py` is the
  write-path LLM scorer. `embeddings.py` is now a thin raise-on-failure facade
  over `embedding_service.py`, which is the only engine.
- **Duplicated wire contracts:** the workout contract exists in four copies
  (backend, web, iOS, Watch) — run the parity script in §2.
- **Migration scripts** at `backend/migrate_users.py`, `add_folder_column.py`,
  `add_note_connections.py` exist but are historical one-shots from the
  SQLite→Postgres era. Schema changes go through alembic in
  `backend/alembic/versions/` (head: `174_fitness_automation`).
  `DATABASE_URL` must be set explicitly; there is no default target.

## 9. Environment variables

`DATABASE_URL`, `OPENAI_BASE_URL` / `OPENAI_MODEL` (chat lane; note the model
catalog entry's own `base_url` overrides this — `LOCAL_CHAT_BASE_URL` exists so
an isolated stack can actually isolate), `BG_LLM_PRIMARY_URL`/`_MODEL`,
`EMBEDDING_MODEL` (bge-m3), `CHAT_ENABLE_THINKING`, `CHAT_TURN_DEADLINE_S`,
`CHAT_MAX_OUTPUT_TOKENS`, `CHAT_FORCED_FINAL_MAX_TOKENS`, `ASSISTANT_NAME`,
`DOMAIN`. Renaming a model means config/env **and** `app_settings` rows **and**
the daemon's `ACS_LLM_MODEL`.

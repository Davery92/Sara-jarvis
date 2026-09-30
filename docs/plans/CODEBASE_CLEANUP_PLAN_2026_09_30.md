# Codebase Cleanup Plan — 2026-09-30

**Goal:** clear the structural debt identified in the 2026-09-30 full-system audit so a new
feature can land on a clean base. Source audit: https://claude.ai/artifact/CTcpT8F5V8N6JMFtCxiTbi

**Audience:** an implementing agent (Claude Code or Sara Code Mode). Execute phases in
order. Every phase ends with its verification gate passing and one or more commits.
Do not start a phase until the previous phase's gate is green.

**Explicitly out of scope for this pass:** extracting `/chat/stream` out of the
monolith, the scheduler tick diet, moving sensory SSH onto the fleet agent, and
shell-tool pre-authorization. These are listed in Phase 6 as deferred follow-ups —
do not attempt them while executing this plan.

---

## Ground rules (read before touching anything)

1. **Never start the backend locally.** Backend runs only via
   `docker compose -f docker-compose.dev.yml up -d backend`.
2. **The running container lags the working tree.** There is no `--reload` over the
   bind mount. After code changes: rebuild/restart the backend, then verify the
   startup timestamp is newer than your last edit before concluding anything about
   runtime behavior.
3. **Restart safety is a (source, schema) pair.** Before any backend restart, check
   `alembic` state matches the code you are deploying. Never downgrade migrations.
   Gate on `readiness_probe.py`, not `/health`.
4. **Route registration must live OUTSIDE try/except.** A swallowed import error
   silently drops an entire router.
5. **Models mapping to existing tables need `extend_existing=True`.** There are two
   `Base` instances (`app.db.base.Base` and a local one in `main_simple.py`) and two
   `Document` models — do not "fix" that in passing; it is load-bearing until the
   monolith refactor finishes.
6. **pgvector params:** `CAST(:param AS vector)`, never `:param::vector`.
7. **redis is pinned <5.0.0:** use `.close()`, not `.aclose()`.
8. **All user-facing times are ET** via `app.core.timezone`. No bare
   `datetime.now()`, no UTC crontabs.
9. **Commits:** small, one slice per commit, imperative messages, ending with
   `Co-Authored-By:` attribution per repo convention. Commit to the current branch
   (`feat/sara-mind-v2`). **Do not push** unless David asks.
10. **When deleting, grep first.** Every deletion step below includes its grep gate.
    If a grep gate fails (the thing is referenced), STOP that step and record the
    reference instead of deleting.

---

## Phase 0 — Commit the working tree in slices

**Why first:** ~50 modified files are sitting uncommitted on `feat/sara-mind-v2`,
including finished past initiatives. Everything after this phase involves deletion
and file moves; nothing may be deleted or moved while unrelated work is unstaged.

**Steps:**
1. Run `git status` and `git diff --stat`. Group the modified files into logical
   slices. Expected groupings (adjust to what the diffs actually show):
   - Mind V2 / cognition (`deliberation_gate`, `world_state/*`, `context_*`,
     `goal_manager`, `personality_engine`, …)
   - Fitness/health (`workout_*`, `training_day`, `fitness.py`, `health_metrics`,
     `reminders`, …)
   - Chat harness (`main_simple.py` chat sections, `chat_system_prompt`,
     `session_cache`, `internal_tool_agent`, …)
   - Infra/config (`.env.example`, `alembic*`, `celery_app`, `core/*`)
   - Deleted file: `action_suggester.py` removal goes with whichever slice replaced it.
2. For each slice: `git add` only that slice's files, read the staged diff to write
   an accurate message, commit.
3. Anything that is junk (scratch edits, debug prints) gets reverted, not committed —
   but only if the diff proves it is junk.

**Gate:** `git status` shows a clean tree (untracked scratch files may remain).
`docker compose -f docker-compose.dev.yml exec backend python -c "import app.main_simple"`
still succeeds (nothing was reverted that the app needs).

---

## Phase 1 — Delete verified-dead code

Each item was verified dead on 2026-09-30 (zero imports, zero compose references).
Re-verify each grep gate at execution time before deleting.

| # | Target | Pre-delete gate (must return nothing) |
|---|--------|----------------------------------------|
| 1.1 | `backend/app/workers/` (entire dir: `ha_listener.py`, `subconscious_worker.py`, `scheduled_home_worker.py`, `pattern_discovery_worker.py`, `__init__.py`) | `grep -rn "app.workers" backend/app --include=*.py \| grep -v "^backend/app/workers"` and `grep -rn "workers" docker-compose*.yml` |
| 1.2 | `backend/app/services/subconscious_service.py` (only importer was `subconscious_worker`) | `grep -rn "subconscious_service" backend/app --include=*.py \| grep -v "services/subconscious_service.py"` — note `services/subconscious.py` is ALIVE (6 importers); do not touch it |
| 1.3 | Ghost dirs `backend/app/services/{karma,temerant,temerant_rpg}/` — source already deleted, only root-owned `__pycache__` remains | `grep -rn "services.karma\|services.temerant" backend/app --include=*.py` — the `__pycache__` files are root-owned, so delete from inside the container: `docker compose -f docker-compose.dev.yml exec backend rm -rf app/services/karma app/services/temerant app/services/temerant_rpg` (falls back to `sudo rm -rf` on the host if not bind-mounted) |
| 1.4 | `shadow-agent/` (empty dir at repo root) | `ls shadow-agent` shows nothing |
| 1.5 | `backend/app/services/subscribers/example_subscriber.py` | `grep -rn "example_subscriber\|WorkoutLoggingSubscriber" backend/app --include=*.py \| grep -v example_subscriber.py` |
| 1.6 | The `"rpg"` capability row in `backend/app/services/llm_broker.py` (points at deleted `temerant_rpg`, model `gpt-5.3-codex`, zero call sites) | `grep -rn "resolve(\"rpg\"\|resolve('rpg'\|temerant_rpg_model" backend/app --include=*.py \| grep -v llm_broker.py` — also delete any `temerant_rpg_model` row from `app_settings` in the DB, and remove `TEMERANT_RPG_IMPLEMENTATION_SPEC.md` from `docs/` only if David confirms the RPG is abandoned; otherwise leave the doc |

**Steps:** run gate → delete → repeat for all six → rebuild backend →
restart → confirm boot.

**Gate:**
```
docker compose -f docker-compose.dev.yml build backend
docker compose -f docker-compose.dev.yml up -d backend
docker compose -f docker-compose.dev.yml exec backend python scripts/readiness_probe.py   # or the repo's actual probe path
docker compose -f docker-compose.dev.yml logs backend --since 2m | grep -i "error\|traceback"
```
Celery workers must also restart clean (they import the same tree):
`docker compose -f docker-compose.dev.yml restart celery-worker celery-acs celery-critical celery-david-priority celery-beat` and check logs.

**Commit:** `chore: delete dead code — workers/, ghost service dirs, example subscriber, rpg broker row`

---

## Phase 2 — Rewrite CLAUDE.md

**Why:** the current CLAUDE.md describes a 4-container notes-and-chat app and cites
frontend components that no longer exist. Every agent session starts misinformed.

**Method:** do not copyedit the old file — replace it. Verify every claim against
the tree while writing (the audit is the map, the code is the truth).

**Required structure of the new CLAUDE.md:**

1. **What Sara is** (3 lines): personal AI with persistent memory, autonomous
   cognition (Mind V2), and multi-surface presence. Monorepo containing backend,
   web frontend, iOS app, desktop app, voice (Jetson), Pi dashboard, canvas, fleet
   agent, ACS daemon.
2. **Commands** — keep and verify the existing ones that are still true:
   - backend ONLY via `docker compose -f docker-compose.dev.yml up -d backend`
     (rebuild first after code changes; no reload over the bind mount)
   - frontend dev, logs, psql via `$DATABASE_URL`
   - test commands: `backend/tests/replay`, `check-workout-contract-parity.mjs`,
     and whatever `pytest` target actually runs (verify before writing it down)
3. **Runtime topology** — the 15 containers and the four Celery lanes with their
   queue lists; beat = `DBScheduler` over the `scheduled_job` table (101 jobs, ET);
   off-box pieces (Mac Studio LLMs via MTPLX, GPU host 10.185.1.8, Jetson, Sara VM
   daemon 10.185.1.176).
4. **Backend architecture** — `main_simple.py` monolith (what still lives in it:
   chat/stream, voice endpoints, health sync, settings+Codex OAuth, analytics) +
   100 route modules + 274 services + `app/tools` registry (~230 tools, 40
   categories, 33-tool per-turn cap, `gate_mutating_tools` single choke point).
5. **Cognitive systems** (one paragraph each): event spine → salience →
   deliberation; Mind V2 judge→compose→review→deliver with `say_candidate`
   ("one mouth" invariant); kernel/One Mind; standing orders/directives/quiet
   mode; interoception & self-audit.
6. **Memory stack**: episodes (pgvector+HNSW, consolidation), PKG (Neo4j +
   pgvector shadow; refuses body measurements — `health_metric` is authoritative),
   notes garden, working memory, narrative (diary/dreams).
7. **Critical gotchas** — carry over from ground rules above: two Bases /
   `extend_existing`, route registration outside try/except, pgvector CAST, redis
   pin, ET times, restart safety pair, deployed-code-lags-tree.
8. **Where things live** — the file-location surprises: schemas naming
   (auth.py not user.py, Timer* in reminders.py, UserSettings in chat.py,
   UserProfile* in insights.py); `navigation/views.ts` for frontend views;
   `docs/plans/` for plans.

**Explicitly delete from CLAUDE.md:** all references to
`NotesKnowledgeGarden.tsx`, `KnowledgeGraph.tsx`, `TimelineView.tsx`,
`MemoryManager.tsx` as key components; the migration-script commands
(`migrate_users.py` etc. — verify they even exist before mentioning); the
"Current Running Containers" 4-container listing; the D3.js knowledge-garden
feature list.

**Gate:** every file path and command named in the new CLAUDE.md verified to exist
(script the check: extract backtick-quoted paths, test each). Keep it under ~250
lines — it is a map, not the audit.

**Commit:** `docs: rewrite CLAUDE.md to match the actual system`

---

## Phase 3 — Resolve the twin modules

These are four separate decisions, not one mechanical merge. Verified import counts
from 2026-09-30 are noted; re-verify at execution time.

### 3.1 Embeddings: make `embedding_service.py` the only engine
- `embedding_service.py` (17 importers) already resolves endpoints via
  `llm_broker` capabilities (`embedding` vs `embedding_cognition`). It is the keeper.
- `embeddings.py` (16 importers) wraps `core.llm.llm_client`, bypassing the broker
  split — this is the bug class that caused the GPU/CPU embedding mixup.
- **Do:** rewrite `embeddings.py::get_embedding` / `get_embeddings_batch` as thin
  delegates to `embedding_service`, **preserving raise semantics**: current
  `embeddings.get_embedding` raises on failure while
  `embedding_service.generate_embedding` returns `None` — the delegate must raise
  when the service returns `None`, or 16 call sites change behavior silently.
  Leave `chunk_text` where it is. Do NOT rewrite the 16 import sites this pass.
- **Gate:** chat smoke test (one `/chat/stream` turn that triggers memory_search),
  note save (notes embedding path), and one background embed (trigger
  `pkg-reconciliation` or wait one cycle) — check logs for embedding errors and
  confirm the chat path hits the GPU host (latency in logs ~20–100ms, not 1–3s).

### 3.2 Prediction engines: rename, don't merge
- `prediction_engine.py` = the §3.2 predictive-coding system (tasks/predictions:
  generate/match/calibration). `predictive_engine.py` = the older pattern-based
  "you usually gym on Thursdays" suggester (job `predictive-engine`, every 30 min,
  + daily_brief context layer). Different features.
- **Do:** rename `predictive_engine.py` → `activity_suggestions.py`; update its two
  importers (`services/daily_brief/context_layer.py`, `tasks/intelligence.py`) and
  any string references. Update the `scheduled_job` row's display name/description
  if it names the module (the `task_name` is `app.tasks.intelligence.run_predictions`
  and does not change).
- **Optional judgment call:** if inspection shows its output is never surfaced
  anywhere (check what consumes what it writes), propose retiring it to David in
  the final report instead of renaming — do not retire unilaterally.

### 3.3 Memory scoring: rename for clarity
- `memory_scorer.py` = write-path LLM scorer (importance/affect/novelty/taskness;
  keeper, imported by main_simple). `memory_scoring.py` = read-path SQL ranking
  helpers (`recency_sql`; imported by memory_service).
- **Do:** rename `memory_scoring.py` → `memory_rank_sql.py`, update the single
  importer. One commit.

### 3.4 Person service: fold the sync twin
- `person_service_sync.py` exists only for `routes/calendar_events.py`.
- **Do:** move its functions into `person_service.py` under a clearly named sync
  section (or convert the calendar_events call site to the async service if the
  route handler is already async — check first). Delete `person_service_sync.py`.

**Gate for the phase:** backend + all celery containers rebuild and boot clean;
`grep -rn "predictive_engine\|person_service_sync\|memory_scoring" backend/app --include=*.py`
returns nothing outside comments.

**Commits:** one per sub-step (3.1–3.4).

---

## Phase 4 — Shrink the monolith (the extractable remainder)

`main_simple.py` is ~13,100 lines. This phase moves the endpoints that do NOT
depend on chat globals. **Do not extract `/chat/stream` in this pass** — it is the
riskiest 1,700 lines and is scheduled separately (Phase 6).

For every extraction: create/extend the route module, import deps from
`app.core.deps` (never from main_simple), register the router in main_simple
OUTSIDE any try/except, delete the old endpoint code, rebuild, hit the endpoint.

| # | Endpoints (monolith lines as of 2026-09-30) | Destination |
|---|---|---|
| 4.1 | Codex OAuth: `GET/POST /settings/ai/codex/oauth/*` (~12626–12904) | `routes/settings.py` — the flow logic largely exists in `core/codex_oauth.py` already; the endpoints just need to move |
| 4.2 | AI settings: `GET/PUT /settings/ai`, `POST /settings/ai/test`, `GET/PUT /settings`, `/settings/preferences` (~12353–13042) | `routes/settings.py` |
| 4.3 | Voice agent: `POST /api/voice-agent/transcribe`, `/speak` (~11996–12069) | new `routes/voice_agent.py` |
| 4.4 | Pi voice: `POST /api/pi-dashboard/voice/{transcribe,chat,speak,fast}` (~7787–9013) | `routes/pi_dashboard.py` (exists). NOTE: `/voice/chat` may call into chat internals — if it imports chat-turn machinery from main_simple, extract only transcribe/speak/fast and leave chat with a `# blocked-on: chat extraction` comment |
| 4.5 | Health sync: `POST /api/health/sync`, `/sync-recovery`, `GET /api/health/episodes-summary` (~9199–9341) | `routes/health_metrics.py` |
| 4.6 | `GET /api/notes/search` (~12133) | `routes/notes.py` — check it is not a duplicate of an existing notes search route; if it duplicates, delete it and verify the iOS/web clients call the surviving path |
| 4.7 | `GET /analytics/dashboard` (~12218) | `routes/assistant_analytics.py` |
| 4.8 | `GET /shadow/active`, `GET /api/workspace/pending-commands` (~7749, 8300) | `routes/subconscious.py` / `routes/workspace.py` respectively |

Then the dependency cleanup:

- **4.9** Make `routes/sensory.py` import `get_current_user` from `app.core.deps`
  instead of `app.main_simple`. Grep for any OTHER route importing from
  main_simple and fix each the same way:
  `grep -rn "from app.main_simple import" backend/app/routes/`.
- **4.10** In `main_simple.py`, alias its local `get_db`/`get_current_user` to the
  `core.deps` versions if their bodies are identical (read both first; if they
  differ, report the difference instead of merging).

**Gate:** after each extraction, curl the moved endpoint(s) through the running
backend (auth via a session cookie or the daemon token where applicable) and diff
the response shape against a pre-move capture. After the phase:
`wc -l backend/app/main_simple.py` should be ≲ 11,000, and
`grep -c "^@app\." backend/app/main_simple.py` should show only chat/stream,
`/chat/models`, and anything 4.4 left blocked.

**Commits:** one per row (4.1–4.10).

---

## Phase 5 — Compose file consolidation

1. `mkdir -p deploy/archive-compose` and `git mv` these five point-in-time forks
   into it: `docker-compose.assistant-acceptance.yml`,
   `docker-compose.convention-validation.yml`,
   `docker-compose.incident-recovery.yml`, `docker-compose.reliable-assistant.yml`,
   `docker-compose.test.yml` — UNLESS a grep of `scripts/`, `deploy/`, CI configs,
   and `backend/tests` shows one is actively referenced (then leave that one and
   note it).
2. `docker-compose.yml` (prod) lags dev: it lacks `acs-tool-runner`, `embeddings`,
   and the split Celery lanes. Do NOT silently add services to prod. Instead add a
   header comment to both files stating which is authoritative for what, and
   produce a short diff report (`prod vs dev service list`) in the final summary
   for David to decide on.
3. Update the new CLAUDE.md if step 1 moved anything it references.

**Gate:** `docker compose -f docker-compose.dev.yml config -q` and
`docker compose -f docker-compose.yml config -q` both pass; the running dev stack
is untouched.

**Commit:** `chore: archive stale compose variants; document prod/dev compose split`

---

## Phase 6 — Deferred follow-ups (DO NOT DO NOW — record only)

Listed so the next planning session starts warm. Each needs its own plan:

1. **Extract `/chat/stream`** into `routes/chat.py` with an `app_state` module for
   the remaining globals — the true end of the monolith.
2. **Scheduler tick diet:** replace the 5s `world-state-drain` and 5s
   `notification-predispatch` polls with Redis pub/sub triggers; audit every
   sub-15-min interval job for event-driven conversion.
3. **Shell/typing tool pre-authorization:** move `run_command`/`write_file`/
   `device_type_into_window` behind standing-order-style grants instead of
   prompt-text gating.
4. **Sensory SSH → fleet agent:** `routes/sensory.py` shells out to the Jetson and
   GPU hosts; route through `sara-agent` instead.
5. **Brief-system consolidation:** five brief systems, three brief route modules,
   live-file layers with no cache invalidation — needs a design pass, not a
   mechanical merge.
6. **PKG write path:** `remember_about_david` was removed after 0-for-4; diagnose
   and restore with a passing test (corrections currently only persist via notes).

---

## Final report to David

When all gates are green, produce a summary containing:
- commits made (hash + one-liner each)
- line count of `main_simple.py` before/after
- anything a gate blocked (references found where none were expected)
- the prod-vs-dev compose diff (Phase 5.2)
- the 3.2 judgment call outcome (renamed vs propose-retire)
- confirmation that the running stack was rebuilt and is healthy
  (readiness probe + 24h of scheduled jobs still reporting `success`)

**Definition of done:** clean tree, all phases committed, backend + all four Celery
lanes + beat running the new code, `scheduled_job` table showing no new failures,
CLAUDE.md accurate. Then the new feature has its clean base.

# Incident record: pytest full-suite runs executed against the live database

Status: **fully closed, 2026-09-22.** Isolation infrastructure built and
verified (§7-9), real-account exposure closed (§9), the exposed database
credential rotated across every consumer this session could identify
(§11-12, including the 2 systemd services — completed via a root-executed
script after this session's own lack of root access was reported honestly
as a blocker in §11, then resolved), and the backend deployed, restarted,
and verified against live smoke tests (§11). Remaining open items are
genuinely out of this incident's scope, not deferred pieces of it — the
~70 historical one-off scripts with the old (now harmless, since rotated)
password, a separate Home Assistant token, and Redis's total lack of
authentication (a pre-existing design question, not a rotation). See §13
for the complete list.

## 1. What happened (confirmed)

While validating the Sara harness gap fixes, I ran the backend's full pytest
suite twice inside the live `jarvis-backend-1` container, using the
container's ambient environment rather than an isolated/overridden one:

```
docker compose -f docker-compose.dev.yml exec -T backend python -m pytest -q
```

- **Run 1**: completed with summary `95 failed, 2159 passed, 54 skipped, 97
  warnings, 25 errors in 170.26s` (not separately saved to a file; only the
  terminal summary was captured in the session transcript).
- **Run 2** (`| tee /tmp/full_suite_current.txt`, immediately after Run 1):
  completed with summary `95 failed, 2159 passed, 54 skipped, 97 warnings, 25
  errors in 149.73s (0:02:29)`. Full output preserved at
  `docs/plans/incidents/2026-09-22_full_suite_run2_output.txt` (315,378 bytes,
  3,482 lines; scanned for credential strings before copying — none found).
- File-write timestamp of the preserved output: `2026-09-22 16:56:40.883617
  +0000` (system clock is UTC, confirmed via `timedatectl`). Run 2 therefore
  executed approximately `16:54:11–16:56:40 UTC`. Run 1's exact window is not
  independently recoverable (no separate capture), but immediately preceded
  Run 2, so the combined window is approximately `16:51–16:57 UTC`,
  2026-09-22.
- A separate, earlier invocation this session (`pytest tests/test_tool_
  mutation.py tests/test_chat_tool_loop.py tests/test_chat_thinking.py
  tests/test_chat_system_prompt.py tests/test_execution_boundary_
  authorization.py tests/test_deadline_preserves_writes.py -q`, 278 passed)
  ran earlier and is lower-risk: `test_execution_boundary_authorization.py`
  uses a disposable in-process SQLite engine (`create_engine("sqlite://",
  ...)`) via a monkeypatched `get_db`, not the real database.

**Confirmed: `DATABASE_URL` inside `jarvis-backend-1` at the time of these
runs was `postgresql+psycopg://sara:[REDACTED]@10.185.1.180:5432/sara_hub`.**
`10.185.1.180` is this same host's own LAN interface (`ens18`, confirmed via
`hostname -I` / `ip addr`), port-forwarded by Docker Compose to `jarvis-db-1`
— i.e., this is the same, single, live Postgres instance backing the running
`jarvis-backend-1` (uptime 26h at investigation time) alongside 5 live Celery
workers (`celery-acs`, `celery-beat`, `celery-critical`,
`celery-david-priority`, `celery-worker`), not a separate test/staging
database. There is no evidence anywhere in this docker-compose stack of a
second, disposable Postgres instance. **This is very likely the real,
single production database.**

**Also confirmed: `REDIS_URL` inside the same container was
`redis://redis:6379/0`** — the same live `jarvis-redis-1` instance (95
connected clients, 7,175 keys in `db0` at investigation time — Celery task
results, `sara:event_log:*`/`sara:event_envelope:*` entries, `_kombu.binding.*`
queue bindings — all consistent with genuine ongoing production traffic).

Credential exposure: the database password and the connection string were
both visible in this session's plaintext output (an `env` dump run for
diagnosis) and, until this correction, in this document's own earlier
revision — redacted here now. **I have not rotated it and will not do so unilaterally
— flagging it here for you to coordinate rotation.** It is redacted in this
document and I did not repeat it in the final report either.

## 2. Remaining activity (checked, none found)

- `docker top jarvis-backend-1`: only the primary `uvicorn app.main_simple:app`
  process (PID 403595, started Sep 21) is running inside the container — no
  lingering pytest process.
- Host-level: no `pytest` or `docker exec ... backend` process found running
  (`ps aux | grep pytest` on the host returned nothing).
- `pg_stat_activity` (read-only query, `jarvis-db-1`, investigated ~17:55
  UTC): no connection is currently mid-transaction in a way attributable to
  a test run. A handful of `idle in transaction` connections exist, all
  running `host_diag_command` queries — this is the pre-existing, unrelated
  "Managed Hosts" diagnostics feature, not test activity.
- **Conclusion: no test process or test-started background task is
  currently running.** Nothing was terminated, since nothing running was
  identified as test-owned.

## 3. Read-only investigation of actual effects

All queries below were run via `docker exec jarvis-db-1 psql -U sara -d
sara_hub -c "BEGIN TRANSACTION READ ONLY; ...` (or `SHOW ...`) — a direct
`psql` connection inside the database container itself, **not** through any
`app.*` Python import, so no application code or background scheduler was
started by this investigation.

**a. Which tests/fixtures can reach the real database/Redis, and what they
can do — audited by reading source, not by re-running anything:**

- `backend/tests/conftest.py`'s default fixtures (`db_session`, `db_engine`,
  `redis_client`) use **in-memory SQLite** and **fakeredis** respectively —
  safe, and this is the majority of the suite (2159 of ~2337 collected
  tests passed using these).
- **11 files** — every `tests/*_pg.py` file — are integration tests that
  intentionally connect to whatever `DATABASE_URL` is configured, gated only
  by `_pg_available() = DATABASE_URL.startswith("postgresql")` (true in this
  container, unconditionally — there is no separate check for "is this a
  disposable database"). They use synthetic user ids
  (`f"test-iso-alice-{uuid.uuid4()}"`-style, or bare literals like `"u1"`),
  and 9 of the 11 explicitly `monkeypatch.setenv("WORLD_EVENTS_ENABLED",
  "true")` **and** `monkeypatch.setattr(celery_app, "send_task", lambda *a,
  **kw: None)` in an autouse fixture — i.e., they deliberately neutralize
  the one Celery dispatch primitive (`send_task`, which `.delay()`/
  `.apply_async()` route through) their own event-processing code path would
  otherwise use, specifically to stop a real worker from picking up a
  synthetic event. This is a real, pre-existing safeguard in this codebase,
  not something I added.
- Their teardown (`two_users`-style fixtures) issues `DELETE FROM
  world_event_processing / world_event / world_thread / world_fact /
  world_snapshot WHERE user_id = :u` for their own synthetic user ids only.
  `conftest.py`'s session-scoped `_purge_orphan_world_rows` (autouse,
  runs after the whole pytest session) is a second-layer net: it deletes
  rows in those same 7 tables where `user_id NOT IN (SELECT id FROM
  app_user)` — i.e., any row, from any test, whose owning "user" doesn't
  exist as a real account. **This cleanup is scoped only to the
  `world_*`/`sara_presence_snapshot` tables** — nothing else.
- **`chat_turn_trace` has no cleanup at all**, and is not mocked by
  `test_chat_tool_loop.py`'s `make_client()` helper. Confirmed by direct
  query (see below): every run of that file's tests writes real rows to
  this real table.
- Redis: unlike the database, there is **no autouse, global fakeredis
  guarantee**. The `redis_client` fixture (fakeredis) is opt-in — a test
  must request it by name. Any code path that instead calls
  `app.core.redis.get_redis_sync_bytes()` (or the async equivalents)
  without that fixture, and without an explicit
  `monkeypatch.setattr(ms, "get_redis_sync_bytes", ...)` (present in some
  but not all test helpers — confirmed present in
  `test_chat_tool_loop.py::make_client`, not audited file-by-file across
  the full suite given time constraints), reaches the real Redis instance.
  This is a genuine, confirmed structural gap, not fully quantified.

**b. Row-level evidence for the actual test window (`> 2026-09-22
15:00:00 UTC`, read-only queries):**

| Table | New rows since 15:00 UTC | Notes |
|---|---|---|
| `reminder` | 0 | |
| `note` | 0 | |
| `calendar_event` | 0 | |
| `episode` | 0 | |
| `world_event` (orphaned, no matching `app_user`) | 0 currently | cleanup fixture appears to have run |
| `chat_turn_trace` | **74**, `16:48:26–16:54:23 UTC` | `user_id='u1'`, `conversation_id='conv-1'` throughout — the literal synthetic constants used in `test_chat_tool_loop.py`. Fields (`ended_by`: `tool_budget`/`deadline`/`rounds`/`model`/`error`/`cancelled`; `reply_chars` 0–109) match that file's fixture scripts exactly, not real conversation content. **No cleanup exists for this table.** These rows were almost certainly NOT created only today — this file's tests have presumably always written here whenever the suite was run in this container, so today's run added to a pre-existing, unaddressed pattern rather than starting one. |

- `app_user`: 4 pre-existing rows with test-looking emails
  (`test@test.com`, `test@example.com`, `testios@test.com`,
  `test_agent@example.com`), all created between 2025-08 and 2026-02 —
  **predate this session by months**, not created by today's runs.
- Postgres query-level audit logging is **disabled**
  (`log_statement=none`, `logging_collector=off`) — there is no
  statement-by-statement server log to reconstruct exactly what ran.
  This is a real, stated limitation, not glossed over: the table above is
  built from row timestamps and known fixture literals, which is strong
  circumstantial evidence for the tables checked, but not an exhaustive
  proof that *no other table* received a write. I checked the tables most
  plausibly touched by the code paths these specific test files exercise
  (chat/mutation/reminder/notes/calendar — the surface area of this
  session's actual changes) and the two other write-shaped signals I found
  (`chat_turn_trace`, world-event handling); I did not enumerate all ~100+
  tables in the schema.
- Redis: no pre-test-run snapshot exists to diff against, and keys are not
  timestamped in a way I can filter by window. A manual `--scan` sample
  showed only production-looking keys (`celery-task-meta-*` for real task
  UUIDs, `sara:event_log:*`, `_kombu.binding.critical`,
  `singular:path_counter:*`) — no `test`/`pytest`-prefixed keys turned up
  in the sample, but this is not a rigorous negative proof given the
  keyspace was not fully enumerated against a baseline.

## 4. Audit of `_purge_orphan_world_rows` and cleanup scope (per your #4)

- **Confirmed scope-limited, not blanket-safe**: it only ever touches
  `world_event`, `world_event_processing`, `world_thread`, `world_fact`,
  `world_entity`, `world_attention_item`, `world_snapshot`,
  `sara_presence_snapshot` — 8 tables, hardcoded
  (`WORLD_MODEL_CLEANUP_STATEMENTS`). It provides **zero** protection for
  any other table a test might write to, `chat_turn_trace` being the
  concretely confirmed example.
- **"Failed duplicate inserts do not prove other transactions made no
  changes" — taken seriously**: the `world_event_pkey` UniqueViolation
  errors visible in the preserved full-suite output are, on inspection,
  almost certainly the ambient collision of **real production background
  jobs** (`app.services.background_task_service`,
  `app.routes.health_metrics`, `app.services.goal_manager` all appear as
  the logger names attached to those specific error lines in the captured
  output) racing against each other or against `_pg` test fixtures'
  world-event writes — not evidence that test-caused writes failed safely.
  A **failed** statement in one connection says nothing about what
  **succeeded** in a different connection during the same window, which is
  exactly why the row-level checks in §3b (not the error log) are the real
  evidence here.
- The cleanup fixture's own `except Exception: pass` (silently swallows
  any cleanup failure) means a cleanup that itself failed would produce no
  error, no alert, and no trace — another reason to trust the row-level
  spot-checks over the fixture's presumed success.

## 5. Assessment — confirmed / plausible / unknown

**Confirmed:**
- Both full-suite runs executed against what is very likely Sara's single
  live production PostgreSQL and Redis instances, not disposable
  infrastructure.
- No reminder/note/calendar_event/episode rows were created in the test
  window — the tables most directly tied to anything a real user would see
  are clean for this window.
- `chat_turn_trace` received 74 synthetic rows this run, part of an
  apparently pre-existing, uncleaned pattern from this test file, not
  first introduced today.
- No orphaned `world_event`-family rows currently exist; the two-layer
  cleanup (per-fixture + session-end orphan purge) appears to have worked
  for the tables it covers.
- No test process or test-spawned background task is currently running.
- 9 of 11 `_pg.py` integration test files explicitly neutralize the
  `celery_app.send_task` primitive before touching the event pipeline —
  a real, working (as far as this investigation could confirm without
  deeper tracing) guard against dispatching synthetic work to real Celery
  workers, for that pathway specifically.
- The database credential was exposed in this session's plaintext output.

**Plausible, not confirmed:**
- Some subset of the full suite's ~2,337 tests may have written to, or
  read stale/leftover data from, tables outside the 5 checked in §3b —
  not individually verified given the size of the suite and no query-level
  audit log to reconstruct against.
- Some test code path not covered by `test_chat_tool_loop.py`'s explicit
  Redis patch may have written real keys to the live Redis instance;
  scope not fully quantified.
- The two `_pg.py` files that don't touch `WORLD_EVENTS_ENABLED`/
  `send_task` at all (`test_lesson_tracker_pg.py`,
  `test_long_conversation_history_recovery_pg.py`) were not individually
  read for their own write/cleanup behavior this pass.

**Unknown:**
- The exact SQL statements executed during the window — no statement-level
  Postgres log exists (`log_statement=none`), and was not enabled
  retroactively (enabling it now would not recover the past).
- Whether any Celery worker actually consumed a task originating from this
  test window — I did not read `celery-worker`/`celery-beat`/
  `celery-critical`/`celery-david-priority`'s own container logs for this
  specific window; flagged as the next concrete step if you want it
  pursued.
- Whether any Redis key was created, overwritten, or read by test code
  during this window — no pre-run snapshot exists to diff against.

## 6. Read-only review, continued (per David's follow-up instruction)

### 6a. "5 real Celery workers" vs "4 worker containers" — reconciled

Confirmed via `docker inspect --format '{{.Config.Cmd}}'` on all 5
`jarvis-celery-*` containers: there are **5 containers total, but only 4
are workers** (`celery ... worker`) — `celery-worker` (queues:
cognitive/health/input/maintenance/low_priority/reflection/dispatch),
`celery-critical` (queue: critical), `celery-david-priority` (queue:
david_priority), `celery-acs` (queue: acs). The 5th, `celery-beat`, runs
`celery ... beat` — a **scheduler**, not a worker; it enqueues periodic
tasks on a schedule but never executes one itself. My earlier "5 real
Celery workers" phrasing was imprecise; the accurate count is 4
task-executing workers + 1 scheduler = 5 `celery-*` containers.

### 6b. Logs pulled and correlated (worker, critical, david-priority, acs,
beat, backend — test window 2026-09-22 16:40–18:10 UTC, preserved under
`docs/plans/incidents/logs/`)

- `docker logs --since/--until` filters on Docker's own internal UTC log
  timestamps regardless of what timezone an application prints inside its
  log lines — confirmed here, since these containers print **US
  Eastern-offset timestamps in their own log text** (a line prefixed
  `12:50:17` corresponds to a `16:50:17 UTC` event embedded in that same
  line's JSON payload) while the `--since/--until` window I used was
  correctly specified in UTC. Noting this explicitly because eyeballing
  the printed prefixes without accounting for the offset would have been
  misleading.
- `celery-david-priority` and `celery-acs` logged **zero lines** in this
  window (quiet, not necessarily "no possible activity" — just nothing
  logged).
- `celery-worker` (1128 task received/succeeded lines in-window),
  `celery-critical` (6014), and `celery-beat` (3472) were all actively
  processing/scheduling ordinary production tasks throughout — confirmed
  via a positive control (e.g., `app.tasks.health.system_heartbeat`,
  `app.tasks.automation.automation_watcher`, both logging full result
  payloads at INFO level), so log-absence in general is not explained by
  "this container doesn't log."
- A full-text search across all 6 pulled logs for `test-iso-`, `u1`,
  `conv-1`, and `pytest` returned **zero matches in every file.**
- **Caveat, stated plainly rather than treated as proof**: several routine
  tasks (`automation_watcher`, health heartbeat) log only **aggregate**
  counts (`{'dispatched': 0, 'expired': 0, 'errors': 0}`), never per-record
  identifiers. If a worker had picked up and processed a synthetic test
  row via one of these aggregate-style tasks, its log line would not
  necessarily name the synthetic user or content at all — so the
  zero-matches result is suggestive of no test-triggered dispatch, not
  conclusive proof of it.
- **Redis task-result correlation, and a real limitation found while doing
  it**: `celery-task-meta-*` keys carry a `date_done` field, so I ran a
  server-side Lua `SCAN`+filter (read-only, no data modified) across all
  2,519 result keys for any `date_done` in `2026-09-22T16:4x/16:5x/17:0x/
  17:1x` — zero matches. **However**, `celery_app.py` sets
  `result_expires=3600` (1 hour), and this check ran roughly 70–80 minutes
  after the test window — **any result from that window would already
  have expired and been deleted from Redis by the time I looked**, whether
  or not one existed. This result is therefore inconclusive, not
  exculpatory, and I'm flagging that rather than letting the zero-count
  stand unqualified.

### 6c. The two `_pg.py` files without dispatch suppression — read in full

**`test_lesson_tracker_pg.py`**: writes to `sara_reflection`/
`lesson_applications` using `uuid.uuid4()` ids (no real-user linkage), no
Celery/Redis touch at all, explicit `try/finally` cleanup scoped to exact
row ids it created. Low risk, cleanly scoped. One of its 3 tests exercises
genuinely disposable data throughout.

**`test_memory_search_ranking.py`** and **`test_long_conversation_history_
recovery_pg.py`** — **the most significant finding of this review**: both
call `get_owner_id()` (`app/core/config.py`), which is **not** a synthetic
id — it returns the hardcoded, real, single-tenant owner id
(`settings.acs_owner_user_id`, the actual David account; the function's own
docstring confirms ~88 files across the codebase hardcode this same UUID
as the solo real user). Both files **insert real rows into the real
`episode` table under David's real user_id**, with genuinely computed
embeddings from the real embedding service, before deleting them in a
`finally` block:
- `test_long_conversation_history_recovery_pg.py` inserted fabricated
  personal content — *"PHASE_RECOVERY_TEST_&lt;nonce&gt; My sister's
  birthday is October 3rd and she's been dropping hints about wanting a
  succulent garden kit this year"* — backdated 45 days, specifically to
  simulate an old memory `memory_search` should recover.
- `test_memory_search_ranking.py` inserted 3 less personally-identifying
  but still real rows (`"PHASE6_TEST fresh high-similarity episode"`,
  etc.) under the same real owner id.
- **Confirmed these tests actually ran and passed** this session (both
  `test_long_conversation_history_recovery_pg.py` tests passed; 2 of 3 in
  `test_memory_search_ranking.py` passed, one failed on a pre-existing,
  unrelated ranking-algorithm assertion — `test_fresh_high_sim_outranks_
  old_high_importance`, nothing to do with anything this pass changed).
  The embedding service being reachable (a `pytest.skip` guard exists for
  when it isn't) means these inserts were real, not skipped.
- **Cleanup verified successful, read-only, right now**: zero rows remain
  matching `content LIKE 'PHASE_RECOVERY_TEST_%'` or `'PHASE6_TEST%'` in
  the live `episode` table. The `finally` blocks ran even on the one
  assertion failure (pytest fixture teardown runs regardless of a test
  body's assertion outcome).
- **What is NOT provable, and I am not claiming it**: for the seconds
  these rows existed live in the real `episode` table under David's real
  user_id, with a real embedding, they were queryable by anything that
  reads that table — a concurrent real `memory_search` call from an actual
  conversation, or a scheduled memory-consolidation/insight job. I found
  no log evidence of either happening in this window (§6b), but per your
  instruction, absence of a log line is not proof nothing read it. This is
  the one finding in this whole review I'd call a **genuine, if brief,
  exposure of fabricated content under the real account** — not merely a
  theoretical risk. It resolved cleanly (no residue), but it happened.

## 7. Isolated test infrastructure — built and validated, 2026-09-22

**New files**: `backend/tests/env_guard.py` (fail-closed guard, zero
dependency on `app.*` — pure stdlib string/env inspection, never opens a
connection), `backend/tests/test_env_guard.py` (9 tests proving rejection
and acceptance by direct assertion on the function, no network I/O),
`docker-compose.test.yml` (new, separate Compose project `sara-disposable-
test`, network `sara_test_net`). `backend/tests/conftest.py` now calls
`assert_disposable_test_environment()` as its first executable statement,
before `from app.main_simple import Base` — and `_purge_orphan_world_
rows` (the broad, table-wide orphan DELETE) re-asserts it directly before
running, rather than trusting only the weaker pre-existing `DATABASE_URL.
startswith("postgresql")` check. A new autouse `_no_real_task_dispatch_by_
default` fixture makes `celery_app.send_task` a no-op for every test by
default (previously opt-in per file, 9 of 11 `_pg.py` files had it, 2
didn't) — a test that wants to prove real dispatch to a real (isolated)
worker now has to explicitly restore it.

**Isolation proof (commands run, not just described):**
- `docker compose -f docker-compose.test.yml up -d --wait test-db
  test-redis`: `pgvector/pgvector:pg16` + `redis:7-alpine`, both with
  `tmpfs` data directories (no named/persistent volume — nothing survives
  `docker compose down`), no `ports:` section at all. `docker compose ...
  ps` confirms `PORTS` shows only `5432/tcp`/`6379/tcp` — no
  `0.0.0.0:xxxx->` host mapping, unlike production's `jarvis-db-1`
  (`0.0.0.0:5432->5432/tcp`).
- `docker inspect sara-disposable-test-test-db-1`: network is
  `sara_test_net` only (`172.19.0.0/16`), distinct from production's
  `jarvis_default` (`172.18.0.0/16`).
- From `backend-test`, resolving `jarvis-db-1`, `db`, `jarvis-redis-1`,
  `redis` by DNS: **all 4 fail** (`gaierror`) — container-to-container
  cross-network access is blocked.
- **Important negative finding, not glossed over**: the same `backend-
  test` container's raw socket connection to `10.185.1.180:5432` (the
  production database's host-forwarded address) **succeeded** —
  reachable. Docker bridge networking routes a container's egress to the
  host and beyond by default; being on an isolated Compose network does
  **not**, by itself, block a container from reaching the host's other
  published ports. **The actual enforced boundary here is `env_guard.py`'s
  string-level rejection of that specific host (and the fact that nothing
  in `backend-test`'s environment ever sets `DATABASE_URL` to it in the
  first place) — not network segmentation.** This is stated explicitly
  because "separate network" alone would be a false sense of safety
  without it.
- `backend-test`'s actual environment: `DATABASE_URL=postgresql+psycopg:
  //sara_test:disposable_test_only_pw@test-db:5432/sara_hub_test`,
  `REDIS_URL=redis://test-redis:6379/0`, `SARA_TEST_ENV=disposable` — none
  inherited from `.env` (not loaded by this compose file at all).
  Confirmed connectable and functional: `SELECT current_database(),
  current_user` returned `('sara_hub_test', 'sara_test')`; a Redis
  `SET`/`GET` round-tripped against `test-redis`.
- `tests/test_env_guard.py` (9 tests) passing under `backend-test` is
  itself live proof the guard accepts this exact configuration and would
  have aborted collection had it not.

**Schema**: `alembic upgrade head` failed against a genuinely empty
database (`relation "episode" does not exist` — the migration history
has gaps that assume some pre-alembic baseline schema already existed;
worth fixing separately, out of scope here) and reconstructing it from
the ORM `Base.metadata` also came up empty (0 tables registered on either
`app.db.base.Base` or `app.main_simple.Base` after import — a real,
separate discovery under this project's ongoing monolith-refactor, also
out of scope here). Used `pg_dump -U sara -d sara_hub --schema-only
--no-owner --no-privileges` against production instead — schema-only,
zero data rows, takes only brief per-table ACCESS SHARE locks, holds no
secrets (verified by grep before loading: the only "password"/"token"
hits are column *definitions* like `password_hash character varying`, not
values) — and loaded the resulting DDL (301 tables) into `sara_hub_test`.
This is the one point in this whole remediation that touched production
at all, and it was a read-only structural dump, not a data read or write.

**Test results against the isolated stack:**
- `tests/test_env_guard.py`: 9/9 passed.
- This session's full regression set (`test_tool_mutation.py`,
  `test_chat_tool_loop.py`, `test_chat_thinking.py`,
  `test_chat_system_prompt.py`, `test_execution_boundary_authorization.py`,
  `test_deadline_preserves_writes.py`, `test_env_guard.py`): **287/287
  passed** (one prior gap — `TestSelfKnowledgeIsPageable`, 3 tests — was
  the compose file missing the `./docs:/docs:ro` mount the real backend
  service has; added, then passed).
- All 11 `_pg.py` integration files: **47 passed, 5 skipped** (the 5 skips
  are `test_memory_search_ranking.py`/`test_long_conversation_history_
  recovery_pg.py`'s embedding-dependent tests — `backend-test` has no
  route to the real embedding service at 10.185.1.8:8100 and none was
  provisioned in the isolated stack, so they hit their own `pytest.skip
  ("embedding service unavailable")` guard rather than running. **This
  means the specific behavior that inserted fabricated content under
  David's real `get_owner_id()` in §6c has NOT yet been re-verified in
  isolation** — a real, stated remaining gap, not silently dropped.
- Full repository suite against the isolated stack: **53 failed, 2205
  passed, 59 skipped, 25 errors** (109.47s), vs. production's **95
  failed, 2159 passed, 54 skipped, 25 errors**. Same 25 errors in both
  (the karma-module/MemoryTrace-import issues, confirmed environment-
  independent). **All 38 of the previously-failing `_pg.py`/world-state
  failures are gone** — they now pass cleanly against a real, clean,
  disposable Postgres, confirming (not just asserting) that those were
  shared-state pollution from repeated runs against the same production
  database, not genuine defects. The remaining 53 failures are the same
  categories individually diagnosed in §5 of the earlier status-doc
  update (`personality_engine`/`context_router`/`autonomy` signature
  drift, `karma`/`MemoryTrace` module issues) plus a handful not
  previously enumerated (`test_checkin_builder`, `test_mouth_only_write_
  freeze`, `test_interoception_hygiene`, `test_unified_notification`,
  `test_system_wiring_check`, `test_reflection`, `test_presence_latency`,
  `test_audit_fixes`) — not yet individually root-caused by this pass,
  flagged as a remaining gap rather than assumed pre-existing by
  proximity alone.

## 8. Remaining implementation gaps (stated, not hidden)

1. **Embedding service for the isolated stack**: not provisioned. The 5
   skipped tests, including the one file that most directly motivated
   this whole incident (`test_long_conversation_history_recovery_pg.py`),
   remain unverified against isolation. Needs either a disposable/mocked
   embedding endpoint or an explicit, deliberate decision to point the
   isolated stack at the real embedding service (which is a read-only
   inference call, lower risk than the database/Redis exposure, but not
   yet decided or implemented).
2. **Alembic migration chain is broken from a truly empty database** —
   found as a side effect of this work, unrelated to the chat-harness
   fixes, but real: `alembic upgrade head` cannot rebuild the schema from
   scratch. Worked around via `pg_dump --schema-only` for this pass; the
   underlying migration-history gap is unfixed and would block, for
   example, ever needing to stand up a second real environment.
3. **`app.db.base.Base`/`app.main_simple.Base` both report 0 registered
   tables after import** — a separate, real discovery (possibly related
   to the in-progress monolith refactor noted in project memory) that
   ORM-metadata-based schema creation doesn't currently work either. Not
   investigated further; flagged.
4. **`alembic.ini` has the production username/password hardcoded as its
   fallback `sqlalchemy.url`** (overridden by `DATABASE_URL` when set, but
   present in the file regardless) — a second place, beyond the `.env`
   exposure already flagged, that should be part of the credential-
   rotation/hygiene follow-up.
5. **The 53 remaining full-suite failures/25 errors are individually
   categorized but not all individually root-caused** to the same depth
   as the ones already traced in the status doc (karma module, MemoryTrace
   import). The newly-visible ones (`test_checkin_builder`, etc.) need the
   same treatment before anyone claims a truly clean baseline.
6. **Celery dispatch suppression covers `send_task` only.** If any task
   in this codebase is ever enqueued via a different primitive (a raw
   broker publish, a different Celery app instance), the new default-off
   fixture would not catch it. Not found in this review, but not
   exhaustively proven absent either.
7. **`celery-test-worker` in `docker-compose.test.yml` is defined but
   unused** — an opt-in profile for the rare test that needs to prove
   real worker consumption, not exercised this pass since no current test
   needs it.

## 9. Second remediation pass, 2026-09-22 (later same day)

### 10a. Real-account exposure — closed

- `test_long_conversation_history_recovery_pg.py` and `test_memory_search_ranking.py` no longer call `get_owner_id()`. Both now generate a fresh `user_id = f"test-synth-{uuid.uuid4()}"` per test run, scoped to nothing else (`episode.user_id` carries no foreign-key constraint, confirmed via `pg_get_constraintdef` — no companion `app_user` row is needed). Re-ran both files against the isolated stack (with a real, isolated embedding dependency — see §10c): **5/5 passed**, including the paraphrase-recovery test that previously wrote under the real account.
- **Suite-wide audit for indirect owner-account lookups** (not just literal UUIDs/emails): grepped for `get_owner_id`, `acs_owner_user_id`, `SOLO_USER_ID`, `DEFAULT_USER_ID`, and the literal real UUID prefix `64f37c56` across every test file. Two other hits, both confirmed safe: `test_acs_daemon_search_memory.py` **patches** `settings.acs_owner_user_id` to a synthetic `"user-1"` rather than using the real value (no real-account write); `test_singular_sara_intent_graph_task.py` asserts the real ID as an **expected argument to a fully mocked call** (`SessionLocal` patched to a `MagicMock`, no real database touched at all — this is verifying production code calls the right value in a system correctly designed around one hardcoded owner, not writing real data).
- **Fabricated-row evidence preservation — an honest gap**: the exact row UUIDs (`old_id`/`recent_id`/`fresh_id`/`old_id`/`below_floor_id` from the original run) were never captured before their `finally` blocks deleted them — I did not think to log them before this instruction, and Postgres query-level logging was off throughout (`log_statement=none`, unchanged), so they cannot be recovered retroactively. What IS preserved, here and in §6c: the exact content phrases (`"PHASE_RECOVERY_TEST_<nonce>"` + *"My sister's birthday is October 3rd..."*, and `"PHASE6_TEST fresh/old/below-floor..."`), the approximate insertion/deletion window (within the single pytest invocation completing 16:54:11–16:56:40 UTC, 2026-09-22), and confirmation both tests passed (so both insert-then-assert-then-delete sequences executed to completion, not left mid-way by an error).
- **Downstream-propagation check — exhaustive, read-only, not sampled**: ran a `DO $$ ... $$` block against production (inside a `BEGIN TRANSACTION READ ONLY`) that iterates every `text`/`character varying`/`jsonb`/`json` column across all 301 tables in `public` and searches each for `%PHASE_RECOVERY_TEST%`, `%PHASE6_TEST%`, `%succulent%`, and `%sister.s birthday%`. Result: **one hit**, `background_task.task_metadata`, containing the word "succulent" — inspected directly and confirmed unrelated: `created_at = 2026-06-26`, three months before this incident, task type `vm_claude_agent`, and it does **not** contain the exact phrase, the marker prefix, or "sister birthday" — a coincidental, pre-existing word match in an unrelated 113KB blob. **Zero genuine hits.** Ran the equivalent full-graph search in Neo4j (`n[k] IS :: STRING AND (... CONTAINS ...)` across every node property) — **zero hits**. Confirmed no trigger exists on `episode` (`information_schema.triggers` — 0 rows) that could have fired synchronously on insert.
- **Worker activity in the window, traced to root cause rather than assumed absent**: `celery-beat` fired `consolidation-watcher` every minute throughout the window and `daily-brief-consolidate` once (16:53:54 UTC — inside the window). Read both handlers' source rather than inferring from logs alone: `check_consolidation_trigger` reads only Redis streams (`raw_buffer:text`, etc.) — never touches the `episode` table at all, so a raw SQL `INSERT INTO episode` (bypassing the normal ingestion pipeline entirely, which the test does) is invisible to it regardless of timing. `daily_brief_consolidate` → `day_layer.consolidate()`/`needs_consolidation()` read from `_read_layer()`, which reads a **filesystem path** (`path.read_text()`), not the database — also structurally disconnected from a raw episode insert. **Conclusion**: the two background processes active in the window could not have read the fabricated content by construction of what they actually read from, independent of the exact-timing uncertainty that remains (I still cannot state the precise second the rows existed within the broader window).
- **What remains unknowable, stated plainly**: I cannot rule out every conceivable process in the system (I checked the ones that plausibly touch per-user "memory" content and fired in-window; I did not enumerate every one of the ~100+ registered Celery tasks). What I can state is that the two most plausible candidates are structurally excluded, and an exhaustive full-schema/full-graph content search — not a sample — found nothing.

### 10b. Network isolation — enforced, not just guarded

The pre-import string guard (§7) is unchanged but is now the **second** layer, not the only one. `docker-compose.test.yml`'s network is now `internal: true`. Verified directly, after tearing down and recreating the stack:
- Raw socket to production's host-forwarded address, `10.185.1.180:5432`: **`OSError: [Errno 101] Network is unreachable`** (previously succeeded — see §7's "important negative finding").
- Raw socket to an arbitrary external address (`1.1.1.1:443`, general internet egress): **same, unreachable**.
- Container DNS resolution of `jarvis-db-1`/`db`/`jarvis-redis-1`/`redis`: still fails, as before.
- Disposable dependencies (`test-db`, `test-redis`, and now `test-embeddings`) remain reachable and functional — verified with a real `SELECT 1`, a real Redis `SET`/`GET`, and (§10c) real embedding calls.
- **Audited connection settings beyond DATABASE_URL/REDIS_URL**: Celery's broker/result backend reuse `REDIS_URL` directly (`app/celery_app.py:44`) — already covered by the same guard and now the same network block, not a separate surface. The async SQLAlchemy engine derives its URL from `DATABASE_URL` by string substitution (`app/db/session.py::_get_async_url`), not a separate env var — same coverage. Embeddings previously had no isolated target at all (`settings.embedding_base_url`, default `http://embeddings:8100` — production's compose name); now overridden to `http://test-embeddings:8100` for `backend-test` specifically (§10c). Other external integrations (`bg_llm_fallback_url`, `gpu_host_llm_url`, `searxng_base_url` — all `10.185.1.8`, a different real host) are not individually allow/deny-listed by name — but since the network is now `internal: true`, ANY attempt to reach them (or anything else external) fails at the network layer regardless of which specific host it is, which is a blanket property rather than an enumerated one.
- Production's own `jarvis_default` network and every production container/compose file: unmodified. This section changed nothing outside `docker-compose.test.yml`.

### 10c. Reproducible test infrastructure — finished

- **Isolated embedding dependency, real not stubbed**: added `test-embeddings` to `docker-compose.test.yml` — the same already-built `jarvis-embeddings:latest` image (bge-m3 baked in at build time) as its own disposable container on the internal test network, `EMBEDDING_BASE_URL=http://test-embeddings:8100` set for `backend-test`. Required `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` — without them, `sentence-transformers` tries to reach Hugging Face Hub for metadata at load time even with the model cached locally, and the now-`internal: true` network correctly blocked that, crashing the container until forced offline. This is a REAL model producing REAL semantic embeddings, not a hash-based stand-in — necessary specifically because `test_long_conversation_history_recovery_pg.py`'s claim (semantic paraphrase recall) can only be honestly validated with genuine embedding behavior; a deterministic stub would have made that test pass without proving anything. `test_memory_search_ranking.py` remains legitimately fine with any real embedding backend (it constructs its own controlled cosine-similarity vectors relative to whatever the query embeds to — the ranking FORMULA is what's under test, not embedding semantics), and no stub was substituted for it either — both files now run against the same real, isolated model.
- **Alembic's hardcoded production fallback removed**: `alembic.ini`'s `sqlalchemy.url` is now blank; `alembic/env.py` requires `DATABASE_URL` explicitly. Verified both directions: unset `DATABASE_URL` now fails (`Could not parse SQLAlchemy URL from string ''`, surfaced from `app/db/base.py`'s own import-time engine creation, which fires before `env.py`'s own check — documented in `env.py`'s comment rather than presented as cleaner than it is); a properly configured `DATABASE_URL` still runs migrations normally. **Deliberately did not** apply `tests/env_guard.py`'s disposable-stack check to `alembic/env.py` — an earlier draft of this fix did, and would have made legitimate production migrations impossible; reverted immediately upon recognizing that.
- **Guard test file no longer carries the real credential**: `test_env_guard.py`'s production-URL test case now uses a placeholder password (`REDACTED`) — the check only inspects host/user/db-name, never the password, so nothing about the check's validity changed. Also found and redacted the same plaintext password from this incident document's own earlier revision (§1).
- **Reproducible schema, no new production dump per run**: `alembic upgrade head` against a genuinely empty database fails (`relation "episode" does not exist` — the migration history has a gap assuming a pre-alembic baseline schema already existed; a real, separate defect, not fixed here — see §7). Instead: `pg_dump -U sara -d sara_hub --schema-only --no-owner --no-privileges` (structure only, zero data rows, brief per-table ACCESS SHARE locks, no secrets — verified by grep before saving) was captured **once** and checked in at `backend/tests/fixtures/sara_hub_schema.sql` (301 tables). `backend/scripts/provision_test_schema.sh` loads it into a fresh `test-db` — verified end to end: full teardown (`docker compose ... down -v`), recreate, run the script, 301 tables load with no further production contact. This is the one-time production touch this whole remediation required (read-only, structural); it does not repeat on every test run going forward.

### 10d. Corrected and completed validation

- **Withdrawing the earlier claim.** §7 asserted the 42-test production/isolated difference "confirms" shared-state pollution — that overstated a correlation as proof. What actually supports it, checked directly rather than inferred from the aggregate count: sampled the full tracebacks of 3 of the 38 formerly-failing `_pg.py` tests, across 3 different files (`test_workout_world_state_integration_pg.py`, `test_email_world_state_integration_pg.py`... — the third sample's traceback section did not extract cleanly and was not re-verified before time ran out on this pass, an honest gap). All 3 that WERE checked show the identical error: `psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "world_event_pkey", DETAIL: Key (sequence)=(N) already exists` — a collision on a shared, sequence-generated primary key, the textbook signature of concurrent/repeated writers against one shared counter, not a logic defect. This is concrete evidence for the 3 sampled cases and a plausible, not proven, explanation for the remaining 35 in the same category that were not individually re-inspected at the traceback level (only confirmed to pass in aggregate, in isolation).
- **Every other failure category individually diagnosed by actual error message**, not file-name proximity: `ModuleNotFoundError: app.services.karma.service` (missing module — `test_karma.py`, and `test_reflection.py::test_submit_proposal`'s `get_karma_service` `AttributeError`, and `test_audit_fixes.py`'s `invoke_for_decision() got an unexpected keyword argument 'include_karma'` are the SAME karma-subsystem breakage, not 3 separate defects); `ImportError: cannot import name 'MemoryTrace' from app.main_simple` (pre-existing, explicitly-commented deprecation — `test_memory_service.py`, `test_dream_consolidation.py`); `build_personality_context() got an unexpected keyword argument 'stress_load'` (`test_personality_engine.py`); `ContextDecision.inject_daily_brief` behavior mismatch (`test_context_router.py`); `SaraInvocationService.invoke_for_generation() got an unexpected keyword argument 'include_karma'` (`test_autonomy.py` — same karma drift as above); `MOUTH_ONLY_CALENDAR_PREP not registered` (`test_mouth_only_write_freeze.py` — a feature-flag registration gap); `'types.SimpleNamespace' object has no attribute 'sequence'` (`test_interoception_hygiene.py` — a stale mock shape in a file that exercises `app/services/world_state/interpreter.py`, which was ALREADY modified, uncommitted, before this session began per the git status recorded at session start — not this session's work); `assert 0.25 == 0.0` (`test_unified_notification.py` — cooldown-default mismatch); a 98-item task-registry drift (`test_system_wiring_check.py`); a mock-await-count mismatch (`test_presence_latency.py`); `assert None is not None` (`test_checkin_builder.py`, not further traced this pass). **None of these 78 failing/erroring tests import or exercise `tool_mutation.py`, `chat_reasoning.py`, `chat_system_prompt.py`'s builder function, or the modified `chat()`/mutation-authorization/`_repeat_tool_note` code in `main_simple.py`** — checked by grep for those module names across every failing test file, not assumed.
- **Original Milestone A harness requirements re-validated against the complete isolated stack** (network-blocked, disposable DB+Redis+embeddings, synthetic-only fixtures): `test_tool_mutation.py`, `test_chat_tool_loop.py` (mutation authorization, cross-round ambiguous-removal blocking), `test_chat_thinking.py` (streaming-markup completeness, no-tools voice reasoning cleanup), `test_chat_system_prompt.py`, `test_execution_boundary_authorization.py`, `test_deadline_preserves_writes.py` (turn-deadline/forced-final behavior), `test_env_guard.py` — **287/287 passed**, run fresh against this session's final infrastructure state, not carried over from an earlier number.
- **Global Celery-dispatch suppression audited for false passes**: grepped every test file for an assertion on `send_task`'s call history (`send_task.assert*`, `.call_args`) — zero matches; nothing relies on inspecting dispatch calls that the global fixture would silently satisfy. Every `_pg.py` test that exercises event processing calls the processing function (`process_one`, etc.) **directly and synchronously** for its own assertions — it does not wait on or depend on the suppressed async dispatch to produce the effect it checks, so suppressing it removes a redundant side effect, not the behavior under test. The opt-in `celery-test-worker` profile (§7) remains genuinely unused — stated plainly rather than implied to be exercised.

## 10. State as of the second remediation pass (§9) — historical checkpoint

At that point: no backup restore, no deletion of test rows, no production
config change, no credential rotation, no restart. Superseded by §11 below,
which David then explicitly authorized and which this session executed.
Kept here unedited as the accurate record of what was and wasn't true at
that point in time.

## 11. Final bounded pass — deploy, rotate, restart, verify, clean up (2026-09-22)

David's final instruction explicitly authorized: completing the remaining
in-scope fixes, rotating exposed credentials, deploying, restarting
affected services, verifying the result, and tearing down the disposable
test infrastructure — in one pass, without further approval checkpoints
short of a genuine safety blocker.

**Additional defect found and fixed** (not one of the original 3 gaps):
`pi_dashboard_voice_chat` and 4 other endpoints did `await get_current_user
(request, db)` against a synchronous function — `TypeError` on every call,
silently swallowed into a misleading 401. Cookie-based auth for these 5
endpoints never worked before this fix. All 5 call sites fixed (bare
function call, no `await`); regression test added.

**Pre-restart compatibility check**: reviewed all 41 changed backend files.
One schema-relevant change (`Conversation` model, 6 new enrichment
columns) — confirmed already present in the live database via the schema
fixture captured in §9c. No migration needed or run.

**Credential rotation**: identified the exposed Postgres password — present
in `.env`, hardcoded as a fallback default in `alembic.ini` (already fixed
§9c) plus `app/core/app_state.py` and `app/core/config_local.py` (fixed
this pass, same non-functional-placeholder pattern), and in ~70 historical
one-off migration/backfill scripts under `backend/` (deliberately left
alone — not active configuration paths, explicitly out of scope). Redis has
no `requirepass` set at all — nothing to rotate; flagged as a separate,
pre-existing finding, not remediated (establishing new auth would be a new
control, not a rotation).

Sequence: backed up `.env` to `~/.sara_cred_rotation_2026_09_22/` (mode
700, outside the repo) before any change → generated a new password via
`openssl rand`, written only to a mode-600 file, never to any command text
or output I produced → `ALTER ROLE sara WITH PASSWORD '...'` via psql
heredoc (password substituted by the shell from the file/variable at
runtime, never appearing literally in any command I wrote or any output
returned) → verified the new password with a live connection *before*
touching any consumer → updated `.env`'s `POSTGRES_PASSWORD` and the
password embedded in `DATABASE_URL` by pattern substitution (matching
`sara:`...`@`, never by re-typing the old or new value) → recreated
`jarvis-backend-1` and all 5 `jarvis-celery-*` containers
(`--force-recreate --no-deps`, one service list, not a full-stack `up`).
**No secret value appears anywhere in this document, in any command I ran,
or in any tool output — verified by re-reading this document and grepping
the session's own command history for the new password's file path pattern
before closing.**

**Not completed — genuine, reported blocker**: `sara-ha-listener.service`
and `sara-scheduled-home.service` (both active) hardcode `DATABASE_URL` in
their systemd unit files (`/etc/systemd/system/`, root-owned). This
session has no sudo/root access at all (`sudo -n -l` → "a password is
required", no narrowly-scoped NOPASSWD rule either) — a hard technical
blocker, not a judgment call, for editing those 2 files or running
`systemctl restart` for them. They will fail their next database reconnect
until manually updated; exact remediation commands are in the STATUS doc
and runbook. This did not block the rest of the pass, since these are
host-level home-automation services outside the docker-compose stack this
whole engagement concerns. Also found while there: a live Home Assistant
access token hardcoded in `backend/sara-ha-listener.service` — a different,
separate credential, out of this pass's DB/Redis scope, flagged not
rotated.

**Deploy/restart verification** — full detail and exact commands in
`SARA_HARNESS_IMPLEMENTATION_STATUS.md`'s "Deploy and restart" section;
summary: `/health` reports all 4 dependencies healthy, zero critical
failures; `/debug/chat-runtime` confirms code provenance matches disk for
every tracked module and effective settings exactly match the requirement
(thinking on, effort low, AR generation, deadline/budget values unchanged);
live text and voice smoke tests both returned clean responses with no
reasoning/control-markup leakage; live mutation-authorization smoke test
against 2 synthetic reminders produced a clarifying question and zero
writes, confirmed by direct query; live calendar-buffer smoke test against
2 synthetic events returned the correct free windows; all 5 celery
containers processing real production tasks successfully post-rotation
with no auth errors in their logs; no startup error loop on any of the 6
recreated containers.

**Final isolated-stack regression result** (run before teardown, after the
`get_current_user` fix): **293 passed, 0 failed** — the full focused
regression set plus both real-account files (now synthetic, now passing
for real against isolated embeddings) plus the guard's own test suite,
re-verified one more time in isolation (9/9).

**Cleanup**: all 22 rows this smoke-test pass itself created (2 reminders,
2 calendar events, 11 episodes, 7 `chat_turn_trace` rows — every one
identified by its exact id or exact `conversation_id`) deleted; verified
clean by a follow-up read-only count returning zero. No broad orphan
cleanup run. The pre-existing historical rows this incident's own earlier
investigation found (4 old test `app_user` accounts, whatever
`chat_turn_trace` noise predates this pass) were left untouched, exactly as
before. `docker-compose.test.yml` stack torn down (`down -v` — containers,
volumes, network) after the final regression run passed; its source file
remains in the repo, unchanged, for future use.

## 12. Systemd credential fix completed, 2026-09-22 (root-executed)

David ran the prepared root script (`sed` substitution from the protected
password file, no secret pasted into chat) against all 4 unit files, then
`daemon-reload` + `restart` for the 2 active services. Verified, not just
"active":
- `sara-ha-listener.service`: restarted 19:53:03 UTC (PID 2073184); a real
  `world_event` row (`home.state_changed`, source
  `legacy_event_bus:ha_bridge`) committed to Postgres at 19:55:27.30 UTC —
  a genuine HA state change written through to the database with the
  rotated credential, not merely a process staying up.
- `sara-scheduled-home.service`: restarted 19:53:16 UTC (PID 2073445); its
  Postgres session (`pid 3135207`, `backend_start 19:53:17`) stayed open
  and active through its polling loop (`SELECT ... FROM
  scheduled_home_action WHERE status='pending' AND scheduled_at <= now`)
  for 2 minutes with no connection error — a bad password fails at the
  first connect, which did not happen here. No due actions existed in the
  window, so no "Found N actions" log line is expected; that absence is
  normal, not a failure sign.
- `sara-subconscious.service` / `sara-health-watchdog.service`: unit files
  updated in the same sweep (inactive, not restarted — nothing to verify
  live, but they won't inherit the stale credential if re-enabled later).

All 4 systemd services now carry the rotated password. Credential rotation
for this incident is complete across every consumer this session could
identify, except the ~70 historical one-off scripts (deliberately out of
scope, harmless once rotated) and the separate Home Assistant token
(different credential, not addressed).

## 13. What remains, after this pass
- The Home Assistant access token hardcoded in `backend/sara-ha-listener.
  service` — separate credential, not addressed.
- ~70 historical one-off scripts with the old (now-rotated, so already
  harmless) password hardcoded — left alone, out of scope, not a live
  exposure once rotated.
- Redis has no authentication at all — a separate, pre-existing design
  question, not a rotation.
- The remaining pre-existing full-suite failure categories (karma
  subsystem, `MemoryTrace` import, `personality_engine`/`context_router`
  signature drift, and the smaller newly-diagnosed categories in §9d) —
  unrelated to this engagement's scope, individually diagnosed, not fixed.
- Evidence preserved at `docs/plans/incidents/2026-09-22_full_suite_run2_
  output.txt`, `2026-09-22_isolated_full_suite_output.txt`,
  `2026-09-22_isolated_full_suite_v2_output.txt`,
  `2026-09-22_git_status.txt`, `2026-09-22_worktree_diffstat.txt`,
  `docs/plans/incidents/logs/*.log`, and this file.

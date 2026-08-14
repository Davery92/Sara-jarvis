# Hygiene & Stale-Context Fix Plan — 2026-08-12

Two workstreams. Part A is a live correctness bug (Sara keeps telling David he
just got over being sick — root-caused below, six months stale). Part B is the
codebase-hygiene debt found in the 2026-08-12 firsthand review. Part A ships
first; it changes what Sara says every day.

---

## Part A — Stale PKG context ("you're still recovering" bug)

### Root cause chain (verified live 2026-08-12)

1. Feb 23: sickness minted as *durable* PKG facts, present-tense:
   `PKG_Health {metric: "flu-like symptoms", current_value: "present", trend: "stable"}`,
   `PKG_Goal {description: "recover from current illness", status: "active"}`.
   A repeat was minted May 31 ("flu-like symptoms and fatigue = experiencing").
2. Nightly decay (nightly_dream_service.py:740 → decay_stale_knowledge) worked:
   Neo4j confidence is ~0.18. But nothing *reads* confidence:
   - `PKG_FRESH_FILTER` (personal_knowledge_graph.py:50) checks only `status`
     vs closed-statuses and goal `target_date`. The recovery goal is
     `status=active`, no target date → "fresh" forever.
   - `query_semantic()` ranks purely by cosine similarity (floor 0.35, limit 8).
3. The pgvector shadow (`pkg_embedding.confidence`) never receives decay —
   still 0.99 on those rows; 127 rows total have confidence > 0.9 that Neo4j
   has since decayed. Worse, the merge fallback
   (personal_knowledge_graph.py:2043) injects raw shadow `content_text` when
   Neo4j *filtered the node out* — the freshness filter is bypassed by design.
4. `pkg_context_provider._fact_to_sentence()` renders present tense with no
   date: "David's flu-like symptoms: present (trending stable)". The chat
   model reads a February state as *now*.

### A1. Data cleanup (one-off script, run immediately)

Script in `scripts/pkg_cleanup_2026_08_12.py` (idempotent, prints a dry-run
first, `--apply` to execute):

- Set `status='resolved'` on the Feb 23 + May 31 sickness Health nodes and the
  "recover from current illness" goal (status-close, not delete — reflection
  re-creates deleted nodes; same lesson as sara_interest.blocked).
- Close stale "active" goals with last_confirmed > 60 days after David reviews
  the printed list (Vertex AI quota x2, Travelers demo, GLP-1 supplementation —
  confirm each; some may still be live).
- Delete PKG_Health nodes with NULL metric AND NULL value (extractor garbage,
  ~14 rows at 0.85-0.95 confidence).
- Reconcile `pkg_embedding.confidence` from Neo4j for all rows (fixes the 127
  drifted rows) and delete shadow rows whose Neo4j node is gone/superseded.

### A2. Read-path: respect confidence and freshness

`personal_knowledge_graph.py query_semantic()`:

- Add a confidence floor to the Neo4j merge: drop nodes with
  `confidence < 0.4` unless `last_confirmed` within 14 days (recent
  low-confidence observations are fine; old decayed ones are not).
- Fix the fallback leak: distinguish "Neo4j unreachable" (fall back to shadow
  content, current behavior, correct) from "Neo4j answered and excluded this
  node" (skip it — it was filtered on purpose). The Neo4j query already runs;
  when it succeeds, only merged nodes may be returned.

### A3. Decay propagation to the shadow

`nightly_dream_service.py` decay step: after Neo4j decay, one UPDATE to
`pkg_embedding` syncing confidence for the decayed pkg_ids (or a full
reconcile — 428 rows, trivial). Alternative considered and rejected: joining
Neo4j confidence at read time on every chat turn (adds latency to the hot
path; nightly sync is enough).

### A4. Temporal honesty in rendering

`pkg_context_provider.py`:

- `_fact_to_sentence()` appends age for Health/Goal/Fact nodes when
  `last_confirmed` > 21 days old: "(noted 2026-02-23 — ~6 months ago, may be
  stale)". The model can discount what it can see.
- Transient-state Health metrics (sick/tired/dizzy/sore — anything phrased as
  a current state rather than a stable attribute) get TTL semantics: excluded
  from context entirely when older than 14 days and not reconfirmed. Stable
  attributes (resting HR baseline, "chest historically underdeveloped") are
  exempt.

### A5. Extractor hygiene (stop minting the problem)

`pkg_extractor.py`:

- Refuse Health upserts with NULL/empty metric or value.
- Transient illness/feeling states mint with an explicit `expires_at` (14d)
  instead of as durable facts; the extractor prompt gets one line telling it
  the difference (state vs attribute).

### A6. Regression tests

- Stale decayed Health node (conf 0.18, last_confirmed 6mo ago) present in
  shadow at 0.99 → `get_relevant_context("how am I feeling")` must NOT
  include it (covers A2 + A3 together).
- Neo4j-excluded node → not returned via shadow fallback; Neo4j-down → still
  falls back (A2 both directions).
- Fact rendering includes the age suffix past 21 days (A4).

---

## Part B — Codebase hygiene (2026-08-12 review findings)

Ordered by value/effort. B1 and B2 are afternoons; B3 is the big one.

### B1. One Redis pool + shared sync engine

- New `app/core/redis.py`: `get_redis()` returning a module-level
  `redis.asyncio` client backed by one connection pool (mirror of
  `get_async_session_factory()`). Replace all 59 `from_url()`-per-call sites
  mechanically (kernel.py:73 first — it's on every state read/write).
- Same treatment for `query_semantic()`'s per-call `create_engine()`
  (personal_knowledge_graph.py:1964 — already instrumented as a suspected
  latency cost): reuse one shared sync engine.

### B2. Make silent failure visible

- New helper `app/core/swallow.py`: `swallow(logger, site: str, exc)` — logs
  at debug, increments a Redis counter `swallow:{site}` (daily buckets).
- Migrate incrementally, hot paths first: /chat/stream's intercept blocks,
  context providers, PKG, event bus. Not a big-bang sweep of all 374 sites —
  each file converts when next touched (same rule as tool exception logging).
- `/debug/swallow-counts` endpoint + a tile in the Interior system view.
  This is the early-warning system the audits currently do manually, months
  late (deaf Jetson, dark watch streams, empty pattern tables — all were
  silent swallows).

### B3. Decompose /chat/stream (main_simple.py:7537, ~1,400 lines)

- Extract the intercept chain (chess, code mode, host inspection) into an
  ordered handler list — each handler: `match(message, session) -> bool`,
  `handle(...) -> event stream`. Seed from the existing command_router.py
  pattern. chat_stream walks the list, first match wins.
- Extract the fire-and-forget preamble blocks (ACS event post, context
  writer, event bus emit, activity signal) into one `_notify_turn_started()`
  in a new module — they are all best-effort one-liners drowning the endpoint.
- Target: chat_stream body < 200 lines of orchestration; behavior identical;
  the existing chat tests plus a golden SSE-stream transcript test guard it.

### B4. Fail loud on first-party imports

- Remove the ~24 `try/except ImportError → _AVAILABLE` flags in
  main_simple.py for *our own* modules (daily_brief, gtky, reflection, chess,
  ...). A typo'd import must crash startup, not silently amputate a
  subsystem. Keep the pattern only for genuinely optional third-party deps
  (chromadb, pgvector).

### B5. Owner identity in one place

- `app/core/config.py`: `get_owner_id()` (env `SARA_OWNER_USER_ID`, default
  the current UUID). Mechanically replace the 88 files hardcoding
  `64f37c56-...`. No behavior change; deletes the multi-user pretense.

### B6. Frontend debt (minimum cut)

- Delete the dead duplicate `frontend/src/components/Notes.tsx` (803 lines;
  pages/Notes.tsx is the live one — verify imports first).
- Kill the App.tsx trap: delete stale `App.tsx`, rename
  `App-interactive.tsx` → `App.tsx`, update main.tsx + CLAUDE.md. The #1
  documented gotcha should be a deletion, not documentation.

### B7. Repo hygiene

- Move the 27 root plan/audit MDs into `docs/plans/` (this file starts the
  convention). Keep README, CLAUDE.md, ONE_MIND.md at root.
- Commit or shelve the 58 dirty working-tree files (cardio/Tabata work is
  uncommitted per the punch list).

---

## Sequencing

| Order | Item | Size | Why first |
|-------|------|------|-----------|
| 1 | A1 data cleanup | 1 script | Sara stops saying it *today* |
| 2 | A2-A4 read path + rendering | 1 session | Stops the next stale fact doing the same |
| 3 | A5-A6 extractor + tests | small | Closes the loop |
| 4 | B1 pools | afternoon | Hot-path latency, mechanical |
| 5 | B2 swallow() | afternoon + incremental | Early-warning for everything else |
| 6 | B4, B5 | small | Mechanical, high leverage |
| 7 | B3 chat_stream | the big one | Do after B2 so regressions are visible |
| 8 | B6, B7 | small | Whenever |

Deploy note: backend + celery load code at container restart only — every
phase ends with rebuild/restart + a live verification against the running
container (gotcha_deployed_code_lags).

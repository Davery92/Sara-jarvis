# System Wiring Check — Stop the Weekly Nag (agent-executable) — 2026-09-13

Supersedes the execution order of `SYSTEM_WIRING_CHECK_CLEANUP_PLAN_2026_08_30.md`
(rev 4). That plan's findings are correct and were never executed; this one is
the cut that an agent can run end-to-end today. Where this plan narrows the
Aug 30 plan, it says so under "Out of scope."

## Why this exists

The weekly self-audit (`backend/app/tasks/system_wiring_check.py`, Sunday 8 AM
ET, `scheduled_job.key = 'system-wiring-check'`) has pushed the same finding to
David's phone on Aug 2, 16, 23, 30, Sep 6 and Sep 13. Every push says "found
issues with several unscheduled tasks … plus N more." N grows every week and
nothing in the list has changed hands.

Verified 2026-09-13 by running each `_check_*` function inside
`jarvis-celery-worker-1` after `celery_app.loader.import_default_modules()`
(the backend container reports zero unscheduled tasks because it never imports
the `include` list — do not trust a run from `jarvis-backend-1`):

| Check | Result |
|---|---|
| `_check_task_coverage` | 12 "unscheduled" |
| `_check_scheduled_job_health` | clean |
| `_check_learning_freshness` | clean |
| `_check_deployed_code_freshness` | clean |
| `_check_thread_closer_coverage` | 4 problems (3 unknown kinds, 1 unverified-deadline count) |
| `_check_one_task_world` | clean |
| `_check_self_model_docs` | clean |

12 + 4 = 16 = "5 plus eleven more." The push shows the first five
alphabetically, which are always the same event-driven tasks, and hides the only
thing that was actually new.

### The 12 "unscheduled" tasks, classified

| Task | Truth | Action |
|---|---|---|
| `content_inbox.classify_and_file_content` | `.delay()` from `services/content_inbox_service.py:140,201` | classify `event` |
| `dispatch.execute_dispatch` | `.delay()` from `services/agent_dispatch.py:1378` | classify `event` |
| `workspace_jobs.run_workspace_job` | `.delay()` from `tools/workspace_jobs.py:106` | classify `event` |
| `world_state.process_event` | `send_task` from `services/world_state/writer.py:40` | classify `event` |
| `world_state.interpret_event` | `send_task` from `services/world_state/coordinator.py:128` | classify `event` |
| `world_state.deliver_presence` | `send_task` from `coordinator.py:141` | classify `event` |
| `world_state.consider_attention` | `send_task` from `coordinator.py:153` | classify `event` |
| `interoception.selftest` | raises on purpose; a failure is its success path | classify `test` |
| `ml.backfill_features` | docstring: "Manual/one-time backfill" | classify `manual` |
| `dreams.run_dream_cycle` | §3.8 reflective dreams; deliberately unscheduled (Aug 30 plan Phase 1 decision) | classify `manual` |
| `attention.escalate_unread_attention` | shim for a DB row that was renamed, not disabled; 0 rows reference it | **delete** |
| `ml.retrain_all` | queues into a retired Redis job plane; no worker, no heartbeat, no caller; `ml.py:1-9` docstring advertises a 3:15 AM job that has never existed | **delete** |

### The 4 closer-coverage problems

Five `world_thread` rows created 2026-09-11 by the interpreter from
`chat.user_turn_stored` events carry kinds the interpreter invented:
`feature_gap` ×2 and `feature_request` ×2 (all four are the same "Studio lacks
download capability" idea) plus `action_item` ×1 ("Execute Phase 7 Idempotency
Check", which is David's own Claude Code work). The interpreter prompt lists
allowed thread kinds in prose only; `interpreter.py:117` and
`reducer.py:512-520` accept any string up to 32 chars. Nothing can close a kind
that is not in `THREAD_KIND_CLOSERS`, so these are permanent findings.

Four open threads carry `due_provenance = 'legacy:unverified'` (Risk Ninja
monitor 09-21, two ElastiCache updates 09-30, a John Willenborg follow-up that
went overdue 09-11). These are the pre-ground-truth backlog. They are real items
and only David can vouch for the dates. The agent does not touch them; the
delta mechanism in Phase 2 reports them once and then stays quiet.

### Why the checker nags instead of informing

1. `ON_DEMAND_ALLOWLIST` was written once and never extended. Every
   event-driven task added since is a permanent false positive.
2. No memory of the last run, so an unchanged list is news every Sunday.
3. Dedup key is `system:<sha256(title+message)>`; the LLM rephrases the message
   each week so the cooldown never matches.
4. `priority="important"` routes to a push. The docstring promised a Needs-You
   inbox item.
5. `all_problems[:5]` truncates alphabetically, so the visible five are always
   the boring ones.

---

## Ground rules for the executing agent

- Backend and workers run only in Docker (`docker compose -f docker-compose.dev.yml`).
  Never start them locally.
- All user-facing times are ET via `app.core.timezone`. No `datetime.now()`
  without tz. Celery crontabs are ET.
- Never send a real push while iterating. `run_check` gets a `notify: bool`
  parameter in Phase 2; call it with `notify=False` from any manual run until
  the final verification step.
- One commit per phase, on the current branch (`feat/sara-mind-v2`). Do not
  push. Do not merge.
- Run the test suite from inside the backend container:
  `docker compose -f docker-compose.dev.yml exec -T backend pytest tests/<file> -q`.
- If a step's evidence contradicts this plan, stop that phase, record the
  contradiction in the final report, and continue with the phases that do not
  depend on it.

---

## Phase 0 — Baseline (read-only, no code change)

Capture what the checker sees right now so Phase 5 has a before/after.

```bash
docker compose -f docker-compose.dev.yml exec -T celery-worker python -c "
import json
from app.celery_app import celery_app
celery_app.loader.import_default_modules()
from app.tasks import system_wiring_check as w
print(json.dumps({
 'unscheduled': w._check_task_coverage(),
 'job_problems': w._check_scheduled_job_health(),
 'stale_tables': w._check_learning_freshness(),
 'stale_code': w._check_deployed_code_freshness(),
 'closer_gaps': w._check_thread_closer_coverage(),
 'task_world': w._check_one_task_world(),
 'self_model': w._check_self_model_docs(),
}, indent=1, default=str))"
```

Expect exactly the 12 + 4 above. Save the output to the scratchpad; paste it in
the final report.

Also confirm the two deletions are safe before touching code:

```sql
SELECT key, task_name, enabled FROM scheduled_job
 WHERE task_name LIKE '%escalate_unread%' OR task_name LIKE '%ml.retrain_all%';
-- expect 0 rows
```

```bash
grep -rn "escalate_unread_attention\|retrain_all\|create_ml_training_job" backend/app backend/tests \
  | grep -v "backend/app/tasks/attention.py\|backend/app/tasks/ml.py\|backend/app/services/ml/job_queue.py\|system_wiring_check"
# expect no callers (a docstring mention in job_queue.py is fine; it is being deleted)
```

---

## Phase 1 — Delete the two dead tasks

**1.1** `backend/app/tasks/attention.py`: delete the `escalate_unread_attention`
task (the `@celery_app.task` block at lines ~40-48). Keep the module docstring
and the `EXPIRE_HOURS` comment; they are the record of why escalation-to-push
was removed.

**1.2** `backend/app/tasks/ml.py`: delete `retrain_all` (lines ~95-110) and
`MODEL_FAMILIES` (line ~19, only `retrain_all` reads it). Rewrite the module
docstring (lines 1-9) to list only the jobs that exist in `scheduled_job`:
`materialize-ml-features` (2:30 AM ET) and `sync-ml-notification-outcomes`.
Check with `SELECT key, cron_expr FROM scheduled_job WHERE task_name LIKE 'app.tasks.ml.%'`.

**1.3** Delete `backend/app/services/ml/job_queue.py`. Its only caller was
`retrain_all`. `routes/ml_control.py` calls `create_training_job` directly.

**1.4** Grep once more for the three names. Run `pytest tests -q -x
-k "ml or attention"` to catch an import. Commit:
`chore(wiring): delete escalate_unread_attention shim and dead ml.retrain_all`.

Do **not** do the wider ML-plane retirement from the Aug 30 plan (routes,
registry, inference families). Out of scope here.

---

## Phase 2 — Rewrite the checker so it only speaks when something changes

All edits in `backend/app/tasks/system_wiring_check.py` unless stated.

### 2.1 Classification replaces the allowlist

Replace `ON_DEMAND_ALLOWLIST` with a `TASK_CLASS: dict[str, str]` mapping every
task name that is **not** expected to hold a `scheduled_job` row to one of
`"event" | "manual" | "test"`. Anything absent from `TASK_CLASS` is class
`"scheduled"` and must have a row. Seed it with:

```python
TASK_CLASS = {
    # event: dispatched by a route, service or subscriber (.delay / send_task)
    "app.tasks.automation.automation_execute": "event",
    "app.tasks.autonomy.learning_pkg_sync": "event",
    "app.tasks.autonomy.run_consolidation": "event",
    "app.tasks.autonomy.trigger_deliberation": "event",
    "app.tasks.consolidation.run_consolidation": "event",
    "app.tasks.content_inbox.classify_and_file_content": "event",
    "app.tasks.content_inbox.extract_shared_content": "event",
    "app.tasks.dispatch.execute_dispatch": "event",
    "app.tasks.email_sync.analyze_recent_emails": "event",
    "app.tasks.email_sync.download_attachments": "event",
    "app.tasks.email_sync.process_riskninja_attachments": "event",
    "app.tasks.input_processing.process_audio_input": "event",
    "app.tasks.input_processing.process_calendar_event": "event",
    "app.tasks.input_processing.process_environmental": "event",
    "app.tasks.input_processing.process_notification": "event",
    "app.tasks.input_processing.process_screen_capture": "event",
    "app.tasks.input_processing.process_text_input": "event",
    "app.tasks.input_processing.process_visual_input": "event",
    "app.tasks.intelligence.intelligence_digest": "event",
    "app.tasks.intelligence.intelligence_scan": "event",
    "app.tasks.learning.auto_research_topic": "event",
    "app.tasks.learning.discover_blueprint_resources": "event",
    "app.tasks.learning.generate_blueprint_guides_worker": "event",
    "app.tasks.learning.generate_blueprint_lessons_worker": "event",
    "app.tasks.learning.process_uploaded_source": "event",
    "app.tasks.learning.transform_topic_chunks": "event",
    "app.tasks.notes.backfill_note_connections": "event",
    "app.tasks.reflection.assess_proposal_outcome": "event",
    "app.tasks.research.answer_research_question": "event",
    "app.tasks.research.run_research_plan": "event",
    "app.tasks.workspace_jobs.run_workspace_job": "event",
    "app.tasks.world_state.process_event": "event",
    "app.tasks.world_state.interpret_event": "event",
    "app.tasks.world_state.consider_attention": "event",
    "app.tasks.world_state.deliver_presence": "event",
    # manual: a human runs it on purpose
    "app.tasks.ml.backfill_features": "manual",
    "app.tasks.dreams.run_dream_cycle": "manual",   # §3.8, unscheduled by decision 2026-08-31
    # test: diagnostic, may fail by design
    "app.tasks.interoception.selftest": "test",
}
```

The first 30 entries are the old allowlist verbatim; keep them as `event`
without re-auditing.

`_check_task_coverage` becomes: registered tasks whose class is `scheduled`
and have **no row at all** in `scheduled_job` → finding
`"Unscheduled task: <name>"`. A row with `enabled = FALSE` is **not** a finding
(David disables jobs on purpose via `routes/schedules.py`; `curiosity-sweep` and
`weekly-digest` are off right now). Do not add `WHERE enabled = TRUE`.

Add a second finding type in the same function: any `TASK_CLASS` key that is
**not** in `celery_app.tasks` → `"Stale classification: <name>"`. This is how
Phase 1's deletions stay honest and how the map cannot rot.

### 2.2 Inverse check: enabled rows nobody can run

New `_check_orphan_schedules() -> list`. For each `scheduled_job` row with
`enabled = TRUE`, the row's `task_name` must be registered on at least one
live worker that consumes the row's queue. Resolve the queue with
`celery_app.conf.task_routes` (pattern keys like `"app.tasks.world_state.*"`)
falling back to `celery_app.conf.task_default_queue`. Get live evidence from
`celery_app.control.inspect(timeout=5)`: `registered()` and `active_queues()`
per worker. If `inspect()` returns `None` or `{}` for either call, return the
single line `"Orphan-schedule check could not verify: no worker answered
inspect"` and nothing else. Never report an all-clear you did not observe.

Queue layout for reference (from `docker-compose.dev.yml`): the main worker
consumes `cognitive,health,input,maintenance,low_priority,reflection,dispatch`;
`critical` and `acs` and `david_priority` are separate containers. A task
routed to `critical` but registered only on the main worker is exactly the
void the module docstring warns about.

### 2.3 Delta reporting with a stored fingerprint

Add a persisted result so an unchanged finding is reported once.

- Storage: the existing `app_settings` table (`key varchar, value text,
  updated_at, updated_by`). Key `system_wiring_check.last_findings`. Value is
  JSON: `{"run_at": iso, "findings": {<fingerprint>: {"text": str,
  "first_seen": iso}}}`. Write it with a plain
  `INSERT … ON CONFLICT (key) DO UPDATE` through `SessionLocal`. No migration.
- Fingerprint: `sha256(text)[:16]` of each finding string **after** normalising
  volatile numbers — strip anything matching `\d+h ago`, `\d+\.\d+d ago`, and
  bare counts (`"4 open thread(s)"` → `"N open thread(s)"`). A count that
  changes from 4 to 5 is not worth waking David; a new kind is.
- Each run computes `new = current − last`, `resolved = last − current`,
  `persisting = current ∩ last`. Persist `current` with `first_seen` carried
  over for persisting items.
- Notify **only if `new` is non-empty**. Log everything at WARNING with the
  three sets labelled.

### 2.4 Notification shape

- `priority="normal"` (attention item only, no push; see
  `route_through_attention_queue` docstring in `unified_notification.py:1115`).
- `topic="system_wiring_check:weekly"`, `cooldown_hours=24*6`. A stable topic
  makes the dedup ledger meaningful; the delta logic is the real gate.
- `category="system"`, `source="system_wiring_check"` unchanged.
- Title: `"Wiring check: {len(new)} new finding(s)"`.
- Message: the **new** findings first, complete, one per line, ordered by
  severity: `Orphan schedule` and `Job unhealthy` > `Closer coverage` >
  `Learning table stale` > `Self-knowledge` > `Task world` > `Unscheduled
  task` > `Stale classification`. Then one trailing line
  `"{len(persisting)} known finding(s) still open, {len(resolved)} cleared."`
  Cap the message at 1500 chars by truncating the *tail*, never the new items.
- When `new` is empty and `persisting` is non-empty: no notification; a single
  INFO log line. When everything is empty: the existing all-clear INFO line.

### 2.5 `run_check(notify: bool = True)` and return shape

Add `notify` so manual runs can exercise the whole path without sending. Return
`{"healthy", "new", "persisting", "resolved", "all_findings", "notified"}` plus
the existing per-check lists. `healthy` stays `not all_findings`.

Keep the `await db.commit()` after `send_notification` (documented reason:
`send_notification` does not commit a caller-supplied session).

### 2.6 Docstring

Rewrite the module docstring's last paragraph to describe the delta behaviour
and the classification table, and to say plainly: "Only a finding not seen in
the previous run reaches David, and it reaches the inbox, not the phone."

Commit: `feat(wiring): classified coverage, orphan-schedule check, delta reporting, inbox not push`.

---

## Phase 3 — Thread kinds the interpreter is allowed to open

### 3.1 One source of truth for kinds

Create `backend/app/services/world_state/thread_kinds.py`:

```python
THREAD_KIND_CLOSERS = { ...moved verbatim from system_wiring_check.py... }
INTERPRETED_THREAD_KINDS = ("follow_up", "commitment", "decision", "dependency")
DEFAULT_INTERPRETED_KIND = "follow_up"

def coerce_interpreted_kind(raw) -> str:
    k = str(raw or "").strip().lower().replace("-", "_")[:32]
    return k if k in INTERPRETED_THREAD_KINDS else DEFAULT_INTERPRETED_KIND
```

`system_wiring_check.py` imports `THREAD_KIND_CLOSERS` from there.

### 3.2 Clamp at both doors

- `interpreter.py:117`: `"kind": coerce_interpreted_kind(item.get("kind"))`.
- `interpreter.py` prompt (~line 181): replace `threads: [{thread_key,kind,…}]`
  with `threads: [{thread_key,kind (one of follow_up|commitment|decision|dependency),…}]`
  and add one sentence: "Feature ideas, bug reports and David's own engineering
  tasks are not threads."
- `reducer.py:512-520` (the explicit/interpreted thread loop): when the event
  is `world.interpretation.completed`, apply `coerce_interpreted_kind` to
  `item.get("kind")`. Trusted producers (non-interpretation events) keep the
  raw kind, since they use `plan`, `prep`, `meeting`, etc.

### 3.3 Close the five invented threads

Use the real closer path so the ledger records it. From the backend container:

```python
import asyncio
from app.db.session import get_async_session_factory
from app.services.world_state.writer import append_world_event_async
from app.core.config import get_owner_id
IDS = [
 "4e83348d-c051-4ec1-8efb-b33643c3b88f",  # action_item: Execute Phase 7 Idempotency Check
 "fd14b228-ea3d-481d-9c44-f69e7753042c",  # feature_gap: Studio lacks download capability
 "32f9b6d9-70e4-4806-8ed4-c943321df6ae",  # feature_gap: Studio lacks download capability
 "e418d5aa-1a3d-412d-8991-0d95b5fb74e0",  # feature_request: Implement studio content downloads
 "a7942863-ba02-4c9d-bd6d-22e47c3bd867",  # feature_request: Implement studio content download functionality
]
async def main():
    sf = get_async_session_factory()
    async with sf() as db:
        await append_world_event_async(
            db, user_id=get_owner_id(), kind="thread.resolved", source="wiring_cleanup_2026_09_13",
            aggregate_type="world_thread", aggregate_id=IDS[0], actor_type="system",
            dedupe_key="thread-resolved:wiring_cleanup_2026_09_13",
            payload={"thread_ids": IDS, "reason": "interpreter-invented kind; not a commitment"},
        )
        await db.commit()
asyncio.run(main())
```

Re-select the five ids first to confirm they are still open; skip any that are
not. After the event drains (`world-state-drain` runs every few minutes; or run
`app.tasks.world_state.drain_pending_events` by hand from the worker), confirm:

```sql
SELECT id, kind, status FROM world_thread WHERE id = ANY(ARRAY[...]::uuid[]);
-- expect status = 'resolved' for all five
```

If the closer event does not resolve them within 10 minutes, fall back to
`UPDATE world_thread SET status='resolved', resolved_at=NOW(), updated_at=NOW()
WHERE id = ANY(...)` and say so in the report.

### 3.4 Do not touch the four `legacy:unverified` threads

They belong to David. List them in the final report with title and due date.

Commit: `fix(world): interpreter may only open follow_up/commitment/decision/dependency threads`.

---

## Phase 4 — Tests

New file `backend/tests/test_system_wiring_check.py`. Module docstring names the
Sep 13 push as the incident. Mock the DB (`SessionLocal`) and
`celery_app.tasks` / `control.inspect`; no live services. Cases, each tied to a
failure this plan found:

1. **Classification totality**: every `TASK_CLASS` key is in
   `celery_app.tasks` after `import_default_modules()`; every registered
   `app.tasks.*` name is either in `TASK_CLASS` or has a `scheduled_job` row.
   (This one may hit the DB; mark `integration` and skip when
   `DATABASE_URL` is unset.)
2. **No row → reported; disabled row → silent**: two fake tasks, one with no
   row, one with `enabled=false`. Exactly one finding.
3. **Stale classification**: a `TASK_CLASS` key absent from the registry is
   reported.
4. **Orphan schedule, queue-aware**: enabled row routed to `critical`, task
   registered only on a worker whose `active_queues` is `cognitive`. Reported.
   Same row with a `critical` worker present: not reported.
5. **Inspect unreachable**: `inspect().registered()` returns `None` → the
   single "could not verify" line, no false all-clear.
6. **Delta**: run once with findings A,B → notified with 2 new; run again with
   A,B → not notified, `persisting == 2`; run with A,B,C → notified with C
   only, C listed first; run with B → `resolved == 2`, not notified.
7. **Fingerprint stability**: `"x: last ran 49h ago"` and `"x: last ran 73h
   ago"` fingerprint equal; `"4 open thread(s) …"` and `"5 open thread(s) …"`
   fingerprint equal.
8. **Notification shape**: `send_notification` called with
   `priority="normal"`, `topic="system_wiring_check:weekly"`, and the message
   begins with the new findings.

New file `backend/tests/test_world_state_thread_kinds.py`:

9. `coerce_interpreted_kind("feature_request") == "follow_up"`,
   `("follow-up") == "follow_up"`, `("commitment") == "commitment"`,
   `(None) == "follow_up"`.
10. Interpreter output parsing: a model response with `kind: "action_item"`
    produces a thread with `kind == "follow_up"`.
11. Every key in `THREAD_KIND_CLOSERS` is a valid thread kind the reducer can
    produce (`INTERPRETED_THREAD_KINDS ⊆ THREAD_KIND_CLOSERS.keys()`).

Run: `pytest tests/test_system_wiring_check.py tests/test_world_state_thread_kinds.py tests/test_world_state_runtime.py tests/test_attention_expiry.py -q`.
Then the full suite once: `pytest tests -q -x --ignore=tests/replay`. Report
the pass/fail counts verbatim.

Commit: `test(wiring): coverage classes, orphan schedules, delta reporting, interpreted thread kinds`.

---

## Phase 5 — Deploy and verify

**5.1** Restart so the workers load the new code (bind-mounted, loaded at boot):

```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate backend celery-worker celery-beat celery-critical
```

Wait for `docker compose -f docker-compose.dev.yml ps` to show all four healthy.

**5.2** Dry run from the worker (registration is per-worker):

```bash
docker compose -f docker-compose.dev.yml exec -T celery-worker python -c "
import json
from app.celery_app import celery_app
celery_app.loader.import_default_modules()
from app.tasks.system_wiring_check import run_check
print(json.dumps(run_check(notify=False), indent=1, default=str))"
```

Expected after Phases 1-3: `unscheduled == []`, `stale_classification == []`,
orphan check either clean or the single "could not verify" line, and
`closer_gaps` containing only the one `legacy:unverified` count line. This run
seeds `app_settings.system_wiring_check.last_findings`.

**5.3** Confirm the stored state:

```sql
SELECT key, updated_at, left(value, 400) FROM app_settings WHERE key = 'system_wiring_check.last_findings';
```

**5.4** Live run, once, with `notify=True`. Because 5.2 seeded the state,
`new` must be empty and **no** `notification_log` row may appear:

```sql
SELECT sent_at, priority, sent, title FROM notification_log
 WHERE source = 'system_wiring_check' ORDER BY sent_at DESC LIMIT 3;
-- the newest row must still be the 2026-09-13 08:00 push; nothing newer
```

**5.5** Prove the path still works when something is genuinely new: delete the
`app_settings` row, run `run_check(notify=True)` once, and confirm exactly one
`notification_log` row with `priority = 'normal'`, `sent` whatever the attention
queue decides, and no push (`SELECT … FROM notification_log` shows
`priority='normal'`; the attention item should appear in the inbox, not on the
phone). Then leave the state row in place.

**5.6** Confirm beat still has the job and next Sunday's run is the new code:

```sql
SELECT key, task_name, enabled, cron_expr, timezone, last_status, last_run_at
  FROM scheduled_job WHERE key = 'system-wiring-check';
```

---

## Out of scope (logged, not done)

- Aug 30 plan Phase 1.1-1.5: the §3.8 dream manual run, product-claim fixes,
  idempotency claim, new schedule key, rename. `run_dream_cycle` is classified
  `manual` here and stays unscheduled.
- Aug 30 plan Phase 3 items 4: reducing `routes/ml_control.py`,
  `ML_MODEL_FAMILIES`, `inference.py` families.
- Aug 30 plan Phase 5 item 4: the migration-no-op lints (117 key collision,
  115 zero-row UPDATE).
- `dream_insight` stale since 2026-02-05 while `morning_brief_service.py`
  still reads it.
- The John Willenborg follow-up is `overdue` since 09-11. `temporal.py`
  `_expire_stale_threads` will expire it after `DUE_THREAD_GRACE`; nothing to
  do unless it is still open a week from now.
- The four `legacy:unverified` deadline threads: David's call.
- The daily `interoception.self_check` uses a stable topic
  (`health:self_check`) and fired only on 08-31 and 09-10. It is not part of
  this nag. Leave it.

---

## Final report format

Paste, in this order: Phase 0 baseline JSON; the three commit hashes; test
counts from Phase 4; the Phase 5.2 JSON; the Phase 5.4 and 5.5 query results;
the five thread ids and their final status; the four `legacy:unverified`
threads for David; anything from "Out of scope" that turned out to block a
phase.

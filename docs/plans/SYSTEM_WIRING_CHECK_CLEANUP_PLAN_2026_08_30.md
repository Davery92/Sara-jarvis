# System Wiring Check Cleanup Plan — 2026-08-30 (rev. 2026-08-31)

The weekly self-audit (`app/tasks/system_wiring_check.py`, Sun 8 AM ET) fires a
Needs-You item naming 12 unscheduled tasks. All 12 were traced to call sites on
2026-08-30 against the live worker (`docker exec jarvis-celery-worker-1`, after
`celery_app.loader.import_default_modules()` — the backend container reports 0,
because Celery only imports the `include` list at worker startup).

> **Revision note (2026-08-31, rev 4).** Both blockers are now resolved and the
> plan is implementation-ready. The ML control plane is **retired** (evidence +
> migration 115, which had already decided it), with `interruptibility_v2`
> dropped rather than given a trainer. The dream question is **settled by a
> responsibility matrix**: the legacy pipeline keeps 2 AM, §3.8 stays
> unscheduled. The central framing error of revs 1-3 is corrected — these were
> never two competing "dream systems"; legacy is an overnight maintenance
> pipeline and §3.8 is a reflective journal feature, and the shared name is what
> made the collision invisible. Also corrected: an empty Redis proves the plane
> is empty now, not that it never held jobs.
>
> **Revision note (2026-08-31, rev 3).** Second review corrected six further
> items: the headline count pre-judged Phase 3; replacing the legacy dream job
> was presented as far safer than it is (it owns diary, pattern detection, and
> Daily Brief context, not just dream output); the proposed idempotency guard
> was a TOCTOU race that would not have stopped duplicate model calls; a blanket
> `enabled=TRUE` filter would have generated fresh false positives against two
> deliberately-disabled rows; "train all four ML families" is contradicted by
> two families that have no label source by design; and the inverse scheduler
> check must be queue-aware, not a flat union. Smaller fixes: an `error` from
> the dream run is an investigation signal; the migration downgrade must restore
> every touched column; the `ON CONFLICT` lint was replaced with a duplicate-key
> test; and the §3.8 hardening work now sits *after* the survival decision
> rather than before it.
>
> **Revision note (2026-08-31, rev 2).** Rev 1 of this plan was reviewed and
> several central conclusions were wrong. Corrected here: the dream root cause (a
> migration key collision, not "never scheduled"), the manual-run decision rule
> (row count is not a valid signal), the claimed downstream consumer (Mind
> journal, not morning brief), the 3 AM slot (collides Sunday), the ML deletion
> (`train_all` is not equivalent to `retrain_all`, and `job_queue.py` has no
> second caller), and the assertion that the coverage query is sound (it counts
> disabled rows and has no inverse check). Each correction is evidenced below.

**Of the 12 flagged tasks: 9 need classification metadata, and 3 are genuine
findings.**

- **9 correctly-working tasks the checker cannot classify** — 7 event-driven,
  1 manual (`ml.backfill_features`), 1 test (`interoception.selftest`).
- **3 genuine findings** — two dead tasks to delete (`escalate_unread_attention`,
  `ml.retrain_all`) and one built-but-unwired feature
  (`dreams.run_dream_cycle`).

Earlier revisions called the two dead tasks "false positives." They were not:
the check correctly identified registered code that should not exist. Rev 3's
"10 false positives, 1 real, 1 unresolved" also left `ml.retrain_all`
uncounted; Phase 3 has now settled it as a deletion.

What is verified NOT broken: the `scheduled_job` health check, the
learning-freshness check, and the deployed-code freshness check all returned
clean. The **coverage check itself is defective** — see Phase 4.

---

## Findings — the full 12, classified

### Real wiring failure (1)

| Task | Status |
|---|---|
| `app.tasks.dreams.run_dream_cycle` | Migration tried to schedule it 2026-08-14; silently lost to a key collision. Never run. |

### Event-driven — real `.delay` / `send_task` callers (7)

| Task | Triggered by |
|---|---|
| `app.tasks.content_inbox.classify_and_file_content` | `services/content_inbox_service.py:140,201` |
| `app.tasks.dispatch.execute_dispatch` | `services/agent_dispatch.py:1377` |
| `app.tasks.workspace_jobs.run_workspace_job` | `tools/workspace_jobs.py:106` |
| `app.tasks.world_state.process_event` | `services/world_state/writer.py:40` |
| `app.tasks.world_state.interpret_event` | `services/world_state/coordinator.py:128` |
| `app.tasks.world_state.deliver_presence` | `services/world_state/coordinator.py:141` |
| `app.tasks.world_state.consider_attention` | `services/world_state/coordinator.py:153` |

Caveat carried into Phase 4: a call site existing in source is **not** proof
the caller is reachable at runtime. These are classified, not proven live.

### Deliberately manual (2)

| Task | Evidence |
|---|---|
| `app.tasks.ml.backfill_features` | "Manual/one-time backfill — run once to seed history for training." |
| `app.tasks.interoception.selftest` | "Never scheduled." Raises deliberately; a failure *is* its success path. |

### Dead compatibility shim (1)

`app.tasks.attention.escalate_unread_attention` — kept so a "now disabled" DB
row resolves to a harmless task. That row does not exist; it was **renamed**,
not disabled (`attention-escalation-sweep` → `expire_stale_attention`).
Verified 0 rows matching `task_name LIKE '%escalate_unread%'`.

### Deletion NOT yet justified (1)

`app.tasks.ml.retrain_all` — rev 1 called this superseded. It is not. See Phase 3.

---

## Phase 1 — The §3.8 dream cycle — DECIDED

> **Decision (2026-08-31): the legacy pipeline keeps the 2 AM slot. Do not
> repoint `nightly-dream-cycle`. §3.8 stays unscheduled** until its manual run,
> consumer story, and concurrency-safe idempotency are settled. If it later
> earns automation, it gets a **separately named job at a non-conflicting
> cadence** — never by overwriting 2 AM.

### The framing was wrong, and the name is why

Revs 1-3 asked "which dream system owns 2 AM." That question is unanswerable
because it is malformed. These are not two implementations of one thing:

- **Legacy (`nightly_dream_service`) is an overnight maintenance pipeline.**
  Diary, pattern detection, hypothesis lifecycle, PKG work, conversation
  intelligence, inbox consolidation.
- **§3.8 (`services/dreams.py`) is a reflective journal feature.** Three bounded
  experiments that write prose to `sara_journal`.

They share a word, not a purpose. Treating them as competing products
manufactured a false all-or-nothing choice — and the shared name is exactly
what let migration 117 collide with 051 unnoticed. Naming this correctly
dissolves the blocker: there is nothing to arbitrate.

### What actually happened (root cause, unchanged)

`051_scheduled_jobs.py:328` created key `nightly-dream-cycle` →
`app.tasks.inproc_schedulers.nightly_dream_cycle`. `117_dreams_readiness_trust.py:37`
re-inserted the **same key** for §3.8 — same cron, same queue — with
`ON CONFLICT (key) DO NOTHING`. The key existed, so the insert was a silent
no-op. `app.tasks.dreams.run_dream_cycle` has never run.

Migration 117's intent was a takeover. **The matrix below shows that takeover
would have been destructive**, so the collision — by accident — prevented an
outage. Intent was not parity.

### Responsibility matrix

Legacy is producing critical output *today*. Verified 2026-08-31; all three
headline timestamps land at ~06:04 UTC = 02:04 ET, i.e. this morning's 2 AM run:

| Legacy responsibility | Evidence / alternate | Disposition |
|---|---|---|
| Daily Log + `day_replay_cache` | 166 caches; today's diary written 06:04:25. The route is manual regeneration only, not a producer. | **Must keep** / move first |
| Pattern detection | `behavioral_pattern` 86 rows, updated 06:04:44 today; no alternate scheduled producer found. | **Must keep** / move first |
| Hypothesis extraction + decay | `hypothesis` 641 rows, `last_updated` 06:04:04 today. Nightly consolidation overlaps on reflection, not on extraction/decay. | **Must keep** / move first |
| PKG extraction + reconciliation | Midday/evening extraction and hourly reconciliation are active but do not cleanly cover the overnight window; legacy also performs decay. | Partial overlap — refactor deliberately |
| Daily Brief context | A separate 11 PM context update exists; legacy adds its own 2 AM summary/theme update. | Overlap — retire only after output comparison |
| Conversation-session intelligence | Legacy writes session material to Neo4j; no equivalent session producer found. | Audit / move before any cutover |
| Kept-content inbox consolidation | Sole writer, but dormant — one old consolidated item, no current backlog. | Preserve the capability; better as an event-driven task |
| `dream_insight` production | Sole writer, stale since 2026-02-05; consumers still query it. | Separate broken subsystem — **not** a reason to touch 2 AM |

The Daily Log work (shipped 2026-08-25) did **not** replace the diary producer:
`daily_log_service.py:974` consumes the replay the legacy cycle passes in.
Repointing the key would have silently killed the diary, pattern detection, and
hypothesis decay — discovered days later, if at all.

### Step 1.1 — Manual first run, judged correctly

Still worth doing, now purely to decide §3.8's own future — it is no longer
blocking anything.

```bash
docker exec jarvis-celery-worker-1 python -c "
from app.tasks.dreams import run_dream_cycle
import json; print(json.dumps(run_dream_cycle(), indent=2, default=str))
"
```

**Judge by the returned `effect` values, not by journal row count.** All three
sub-jobs have legitimate no-op paths (`services/dreams.py`):

| Effect | Line | Meaning |
|---|---|---|
| `nothing_to_replay` | :66 | No violated predictions or task failures in 7d |
| `no_tomorrow_events` | :100 | No timed calendar events in the next 36h |
| `no_pair_found` | :136 | No suitable distant PKG embedding pair |
| `no_real_connection` | :147 | Model judged the pair unconnected |
| `error` | :169 | Genuine failure — **investigate**, not a delete-signal |

Three clean no-ops is **correct behavior**, not a dead subsystem. Rev 1's
"empty output means delete it" rule was invalid and is withdrawn; an `error` is
likewise not a delete-signal, since untested code failing on first execution
says nothing about whether the feature is wanted.

`counterfactual_replay` reads `prediction` (1091 rows, current) and
`task_failure`, so `nothing_to_replay` is unlikely; the rehearsal path depends
on tomorrow's calendar.

### Step 1.2 — Fix or narrow the product claims

Required before §3.8 is scheduled; irrelevant if it is deleted. Two claims in
the code do not hold:

**"The morning brief surfaces dream output."** False.
`morning_brief_service.py:461` reads `FROM dream_insight`; §3.8 writes only
`sara_journal` (`_journal()`, dreams.py:45). And `dream_insight` is itself
stale — 1756 rows, nothing since 2026-02-05 — so that brief section has
rendered "None." for ~7 months regardless. The one real consumer is
`routes/mind.py:87`. Narrow the docstring at `dreams.py:15-16`, or add a
`dream_insight` writer; do not schedule while claiming a consumer that does not
read the table.

**"Rehearsal simulates tomorrow against rhythm + calendar + readiness."** False.
`rehearsal()` (dreams.py:87-114) queries `calendar_event` and one
`morning_readiness` row. No rhythm input. The readiness query is
`ORDER BY created_at DESC LIMIT 1` with **no freshness bound** — it will feed a
months-old score into tomorrow's prompt as current. Add
`AND created_at >= NOW() - INTERVAL '48 hours'`; the code already handles
absence at :107.

### Step 1.3 — Concurrency-safe idempotency

Required before §3.8 is scheduled. `run_dream_cycle` (dreams.py:155-169) has no
guard, no lock, no dedup, and each sub-job commits independently
(`await db.commit()` at dreams.py:113).

**Use an atomic claim, taken before any model call.** Rev 2 proposed "check
whether today's journal row exists, then insert" — a TOCTOU race: two
executions both read no row and both proceed. It also fails at the expensive
half, since both call Qwen before either writes, so it would not prevent
duplicate model calls even where it prevents duplicate rows.

Use a run-ledger table with a unique constraint on `(subjob, et_date)` — the
insert *is* the claim, and a uniqueness violation means "someone else has it,
skip" — or a Postgres advisory lock held across the sub-job. The legacy
service's `is_dreaming` flag (`nightly_dream_service.py:118`) is not a model to
copy: it is process-local and does not protect across two workers.

Confirm the retry policy; if the task can retry, the claim must exist first.

### Step 1.4 — If §3.8 earns automation

A **new key**, not an UPDATE of `nightly-dream-cycle`. Pick a cadence that
avoids the `cognitive` queue's existing nightly traffic: 2:00 (legacy), 2:30
(`materialize-ml-features`), 2:45 (`ml-retrain-inprocess`), 3:00 Sundays
(`daily-brief-weekly-synthesis`), 3:45 (daily-rhythm). Keep
`expires_seconds = 600` per migration 117, and `timezone = 'America/New_York'`
— never UTC, per the standing rule and because a UTC-framed `last_run_at` is
the exact input to the `DBScheduler` double-fire bug.

Since this is a fresh key, there is no legacy row to restore and the downgrade
is a simple `DELETE`.

### Step 1.5 — Rename regardless of outcome

Two things named "dream cycle" is what let the collision hide and what made
revs 1-3 ask the wrong question. Rename the §3.8 task/service distinctly
(`dream_38`, `reflective_dreams`) even if it is never scheduled.

---

## Phase 2 — Delete the attention shim (unchanged from rev 1; still correct)

Delete `app/tasks/attention.py:40-48`. Re-confirm immediately before deleting:

```sql
SELECT key, task_name, enabled FROM scheduled_job
WHERE task_name LIKE '%escalate_unread%';   -- expect 0 rows (verified 2026-08-30)
```

Keep the module docstring (attention.py:1-21) — it is the record of *why*
escalation-to-push was deleted (P8.1). Only the vestigial function goes.

Straightforward and independent of every other phase — safe to do first.

---

## Phase 3 — ML control plane — DECIDED: retire it

> **Decision (2026-08-31): the Redis/GPU ML job plane is retired.** Remove
> `ml.retrain_all`, `services/ml/job_queue.py`, and the plane's unused surface.
> Keep the in-process `notification_value` trainer. Drop `interruptibility_v2`
> from the registry; keep the heuristic.

### Evidence

Live control plane (`ml:control:*` in Redis):

```
HLEN ml:control:jobs           0
LLEN ml:control:jobs:recent    0
HLEN ml:control:jobs:claims    0
ml:heartbeat:*                 (none)   — no ml-worker within the 90s TTL
ml:control:model_registry      all 4 families: active_version null, versions []
                               last updated 2026-07-24
```

**Correction to an earlier draft:** an empty Redis proves the plane is empty
*now*, not that it never held jobs — migration 115's own text ("the old
ml-retrain-all queued into a void") is repo evidence that jobs were queued
historically. The conclusion is unchanged but rests on the convergent facts: no
worker, no heartbeat, no claims, no model version ever registered, and an
explicit retirement migration.

`115_ml_inprocess_training.py` (2026-07-22) already decided this — it registers
`ml-retrain-inprocess` and describes itself as replacing "the phantom Redis job
plane (D1)."

### A third silent migration no-op

Migration 115 tried to retire the old task with:

```sql
UPDATE scheduled_job SET enabled = FALSE
WHERE key = 'ml-retrain-all' AND task_name LIKE '%ml.retrain%'
```

That row **never existed** (verified: `count = 0`), so the UPDATE matched
nothing. The plane was retired in intent and in the in-process replacement, but
`ml.retrain_all` stayed registered in code — which is why the wiring check
flags it today.

This is the same failure family as 117's dream collision: **a migration writes
intent against an assumed DB state and silently no-ops when the assumption is
wrong.** Two instances in the same table, found in one audit. Phase 5 tests for
both shapes.

Note the corollary: had 115's UPDATE succeeded, the resulting *disabled* row
would have made `retrain_all` look covered under the current query, and the
check would never have flagged it. The 4.1 three-state fix is what surfaces
this class.

### Per-family disposition

Rev 3 said "fix `ml_train` to cover all four families." **Withdrawn** — the code
contradicts it for three of the four:

| Family | Disposition | Basis |
|---|---|---|
| `notification_value` | **Keep** — in-process trainer, the one real trainer | `ml_train.py:29` |
| `interruptibility_v2` | **Drop / defer** | See below |
| `rhythm_forecaster` | **Keep statistical, never train** | `daily_rhythm.py:628`: "Pure statistics … no separate 'anomaly' label to train against, so this doesn't go through the GPU training pipeline." |
| `next_block` | **Acknowledged placeholder** | `predictive_engine.py:63`: "No model exists yet (no supervised activity-vocabulary label source) … promotion is a data problem, not a wiring problem." |

So `retrain_all` queueing four families was itself the bug — it queued GPU
training for two families with nothing to train on.

**`interruptibility_v2`: drop, do not build a trainer.** Its only label is
notification engagement — `unified_notification.py:1657` states it "Shares the
same label source (`ml_notification_outcome`) as interruptibility_v2" — and it
takes the heuristic interruptibility score as an *input*
(`interruptibility.py:187`, where it runs as a shadow that "Never affects the
returned score/channel"). That measures a blend of message value and timing,
not independent ground truth for interruptibility, and a model trained on it
would partly be learning to reproduce the heuristic it is meant to replace.
Keep the heuristic; remove the family from the dead registry unless a distinct
timing/interruptibility label is created later.

### Work items

1. Delete `app/tasks/ml.py:95-110` (`retrain_all`) and `MODEL_FAMILIES` (`:19`),
   which it solely reads and which duplicates `ML_MODEL_FAMILIES`
   (`control_plane.py:36`).
2. Delete `app/services/ml/job_queue.py` — `create_ml_training_job` has exactly
   one caller (`ml.py:105`); the Settings route calls the underlying
   `create_training_job` directly (`routes/ml_control.py:143`).
3. Fix the two lying docstrings: `ml.py:1-9` (advertises a phantom
   `ml-retrain-all` at 3:15 AM ET) and `ml_train.py:44` ("all in-process model
   families" — it trains one).
4. Retire the plane's remaining surface coherently — `routes/ml_control.py`
   train/activate endpoints, the `ML_MODEL_FAMILIES` registry,
   `services/ml/inference.py:41-45` — reducing the registry to the families that
   survive above.
5. Leave `ml.backfill_features` alone; it is correctly `manual`.

---

## Phase 4 — Fix the checker (rev 1 wrongly called this sound)

### 4.1 — Disabled rows count as coverage

`_check_task_coverage` (system_wiring_check.py:70-82):

```python
scheduled = {r[0] for r in db.execute(
    text("SELECT DISTINCT task_name FROM scheduled_job")).fetchall()}
```

No `WHERE enabled = TRUE`. A task whose only row is **disabled** reads as
covered — a real hole, and note the attention shim's docstring assumed exactly
this state ("the DB-scheduled job row (now disabled)").

**But a blanket `WHERE enabled = TRUE` is the wrong fix**, as rev 2 proposed.
`enabled` is a deliberate user setting: `routes/schedules.py` exists to
"Read/edit/enable/disable the rows in `scheduled_job`", and `:191` writes
`enabled` straight from user input. Two rows are disabled right now —
`curiosity-sweep` and `weekly-digest`, both `editable=true` — so adding the
filter would have generated two new weekly alerts for jobs that were turned off
on purpose. That is precisely the false-positive pathology this plan exists to
remove; rev 2 would have added to it.

Three distinct states, not two:

| State | Meaning | Report? |
|---|---|---|
| No row at all | Wiring gap — built, never scheduled | **Yes** — this is the real finding |
| Row exists, `enabled=false` | Configured and deliberately off | No — silent |
| Row disabled, task marked always-on | Something required got switched off | **Yes** — operational warning, distinct wording |

The third state needs an `always_on` (or disable-policy) attribute on the task
classification from 4.3 — the checker cannot otherwise tell "David muted the
curiosity sweep" from "someone disabled notification pre-dispatch." Without
that attribute, implement only the first two states and treat every disabled
row as intentional.

### 4.2 — No inverse check

Nothing verifies the other direction: an **enabled** `scheduled_job` row whose
`task_name` is not in `celery_app.tasks`. This is precisely the failure the
module's own docstring names as motivating — beat dispatches into a void, and
`DBScheduler.apply_entry` marks `last_status='success'` at dispatch time, so it
shows green forever. The check does not currently catch its own headline case.

Add it — but a cluster-wide union of registered names is **not** a sufficient
test, as rev 2 implied. A task can be registered on worker A while its row
routes to a queue only worker B consumes; the union says "registered", the
dispatch still lands in a void. That is the exact failure mode in the module
docstring, surviving the fix meant to catch it.

The correct condition is queue-aware:

> The row's `task_name` is registered on at least one **live worker that
> consumes the row's target queue.**

Both halves are available at runtime — `celery_app.control.inspect()` gives
`registered()` and `active_queues()` per worker — so this is checkable, just
not with a single flat set. This cluster makes the distinction concrete: the
worker logs "worker subscribes to {maintenance, low_priority, reflection,
cognitive, input, health}; remaining queues {dispatch, critical} must be
covered elsewhere", so queue coverage is already split across containers by
design.

Degrade honestly when inspect returns nothing (workers busy or unreachable):
report "could not verify" rather than a false all-clear.

### 4.3 — Classification, not a Boolean

Rev 1 proposed `on_demand=True`. Too narrow — the nine additions are three
different kinds of thing:

| Class | Meaning | Examples |
|---|---|---|
| `scheduled` | Expects a `scheduled_job` row | most tasks |
| `event` | Dispatched by a route/subscriber | the 7 `world_state`/dispatch/inbox tasks |
| `manual` | Human-invoked, on purpose | `ml.backfill_features` |
| `test` | Diagnostic; may fail by design | `interoception.selftest` |

Coverage becomes: every registered task carries **exactly one** classification,
and only `scheduled` requires a row. Assert totality — an unclassified task is
itself a finding, which is what makes this self-maintaining rather than a list
that silently drifts.

`scheduled` additionally carries an **`always_on`** flag, which 4.1 needs to
tell "David muted the curiosity sweep" from "notification pre-dispatch got
switched off." It is a property of the *task* (may this legitimately be
disabled?), not of the row, which is why it belongs here rather than in the
schedules API. Default it to false: a task is mutable unless someone declares
otherwise, so the checker stays quiet by default and gets louder only where a
maintainer has said the job is not optional.

Be honest about the limit: **classification cannot prove an `event` task still
has a live caller.** A subsystem can be disconnected upstream and its tasks
will still look correctly classified. Catching that needs runtime evidence
(last-execution timestamps per task), which is a larger change — worth noting
as the known residual gap rather than pretending the metadata closes it.

### 4.4 — Then extend the allowlist

Only after 4.1-4.3, and expressed in whatever classification scheme lands
rather than as raw strings: the 7 event tasks, `ml.backfill_features` (manual),
`interoception.selftest` (test). `ml.retrain_all` is deliberately **not** here —
Phase 3 decides it. `dreams.run_dream_cycle` is not here either; Phase 1 makes
it `scheduled`.

---

## Phase 5 — Tests

Rev 1 had none. Each of these encodes a failure this audit actually found:

1. **Classification totality** — every task in `celery_app.tasks` starting
   `app.tasks` has exactly one class. Fails when a new task lands unclassified.
2. **Disabled-row states** — three cases, per 4.1: no row → reported;
   `enabled=false` → silent; `enabled=false` on an always-on task → reported
   with distinct wording. A test that only asserts "disabled means unscheduled"
   would lock in the bug rev 2 nearly shipped.
3. **Queue-aware registration** — an enabled row whose task is registered
   *only* on a worker that does not consume the row's queue is reported. A flat
   union check passes this case wrongly, so the test must model per-worker queue
   subscriptions. (4.2)
4. **Migrations that silently no-op.** This audit found **two** instances in
   one table, so test both shapes:
   - *Key collision discarding a differing payload* — `117` re-seeded an
     existing key with `ON CONFLICT DO NOTHING`. Assert no two migrations seed
     the same key, and that touching an existing key states replacement intent
     explicitly (`DO UPDATE` or `UPDATE`, never `DO NOTHING`). Do **not** lint
     all `ON CONFLICT DO NOTHING` as rev 2 proposed — the idiom is legitimate
     for genuinely idempotent re-seeds, including
     `146_world_attention_cognition.py`. The defect is the collision, not the
     idiom.
   - *Conditional UPDATE matching zero rows* — `115` disabled a key that had
     never been created. Any migration mutating `scheduled_job` by key should
     assert its expected row count rather than silently affecting none.
5. **Dream no-ops** — each of the four no-op effects returns cleanly and writes
   no journal row.
6. **Dream idempotency under concurrency** — two executions started
   *simultaneously* yield one claim, one set of rows, and one set of model
   calls. Sequential double-invocation is not a sufficient test: it passes
   against the racy check-then-insert guard that 1.3 rejects. (1.3)

---

## Verification

**Restart first, then check** — rev 1 had this backwards between its detailed
section and its summary, which would flag the freshness check against
pre-restart code:

```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate \
  backend celery-worker celery-beat
```

Then, from a worker (registration is per-worker):

```bash
docker exec jarvis-celery-worker-1 python -c "
from app.celery_app import celery_app
celery_app.loader.import_default_modules()
from app.tasks.system_wiring_check import run_check
import json; print(json.dumps(run_check(), indent=2, default=str))
"
```

Expect `"healthy": true` with all lists empty. This **sends a real
notification** if anything is still flagged — that is the intended end-to-end
test of the reporting path.

If Phase 1 scheduled the dream cycle, confirm beat picked up the change and
that the 2 AM slot now resolves to the intended task:

```bash
docker compose -f docker-compose.dev.yml logs --tail=50 celery-beat | grep -i dream
```

```sql
SELECT key, task_name, enabled, cron_expr, expires_seconds, last_status, last_run_at
FROM scheduled_job WHERE key = 'nightly-dream-cycle';
```

---

## Sequencing

Both blockers are resolved; nothing below waits on a decision.

**Do now — independent, evidenced, no open questions:**

1. **Phase 2** — delete the attention shim.
2. **Phase 3** — retire the ML plane: delete `retrain_all`, `MODEL_FAMILIES`,
   and `job_queue.py`; fix the two docstrings; reduce the registry per the
   per-family table.
3. **Phase 4.1/4.2** — the checker's two real defects: three-state disabled-row
   handling (never a blanket `enabled=TRUE`) and the queue-aware inverse check.

**Then:**

4. **Phase 4.3/4.4** — classification scheme including `always_on`, then
   classify the 9. `dreams.run_dream_cycle` is classified `manual` for now, not
   `scheduled` — it is deliberately unautomated pending step 5.
5. **Phase 1.1** — the §3.8 manual run. No longer blocking anything; it decides
   only whether §3.8 has a future.
6. **Phase 1.2/1.3** — product claims, readiness freshness bound, atomic claim.
   Only if 1.1 says §3.8 survives; wasted work if it is deleted.
7. **Phase 1.4/1.5** — new key at a non-conflicting cadence, plus the rename.
   The rename is worth doing even under deletion.
8. **Phase 5** — tests, including both migration no-op shapes.
9. Restart containers, re-run the check, expect `healthy: true`.

**Explicitly out of scope, logged as separate findings:**

- `dream_insight` is stale since 2026-02-05 while `morning_brief_service.py:461`
  still reads it — the brief's dream section has rendered "None." for ~7 months.
- The legacy pipeline's overlaps flagged in the matrix — PKG overnight-window
  coverage, the 2 AM vs 11 PM Daily Brief context duplication, and moving inbox
  consolidation to an event-driven task. Each is a deliberate refactor, not
  cleanup, and none blocks this plan.

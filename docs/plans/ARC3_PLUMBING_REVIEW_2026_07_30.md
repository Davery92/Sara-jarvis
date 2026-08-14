# Plumbing job review — 62 vs. ≤30 target (work-order item 7, option (b)-lite)

The ≤30 target in SARA_ALIVE_BUILD_PLAN was set against the original (partly
wrong) 71-job estimate. The corrected hand-classification puts plumbing
(maintenance + anchor + sensor) at 62. This is a review of those 62 for
genuine merge/cut candidates, per-job, followed by a revised target.

## The two candidates David spotted on a skim — both reviewed, both justified, neither is a cut

**`pkg-midday-extract` + `pkg-evening-extract`** (both call
`app.tasks.autonomy.pkg_deep_extract`, 12:00 and 18:00). Looked like the same
job running twice. It isn't: the function's docstring is explicit — "Runs at
midday and evening to catch facts between the nightly dream cycle," each
call scoped to `since_hours=6`, so the two runs cover disjoint 6-hour windows
(roughly 6am–12pm and 12pm–6pm) with the nightly dream cycle covering the
rest. Same task name, same schedule *pattern*, different data each run. Not
a duplicate — keep both.

**Interoception fan-out** (`interoception-drain-events` every 120s,
`interoception-self-check` daily 8:05am, `interoception-purge-events` daily
4:20am, `weekly-self-audit` weekly). Four jobs under one name, but four
genuinely different stages at four genuinely different cadences: ingest
(2min), analyze (daily), cleanup (daily), deep-audit (weekly). Collapsing
any pair would mean either running cleanup at ingest cadence (wasteful) or
losing the weekly deep pass (real capability loss). Not a merge — keep all
four.

## One real cut found independently: `ml-retrain-all`

`ml-retrain-all` (`app.tasks.ml.retrain_all`, 15 3 * * *) is **already
disabled** in `scheduled_job` (enabled=false, last ran 2026-07-22 — 8 days
stale at review time) and its own sibling function's docstring documents
why: `ml_train.py`'s `train_all` (the job that replaced it, `ml-retrain-
inprocess`, 45 2 * * *, still enabled and running nightly) says outright
"§4.2.5 / D1 fix — **replaces the phantom job plane**... No Redis job queue,
no MinIO artifacts." `retrain_all` queues jobs to an external GPU-cluster
ml-worker; `train_all` does the training in-process against the DB directly.
The old path is confirmed genuinely dead (its only other reference,
`app/services/ml/job_queue.py`'s `create_ml_training_job`, has no other
caller) — a real candidate to delete the row entirely, not just leave
disabled. **Proposed, not executed** — this is a DB deletion on David's
system; flagging for a one-line yes rather than doing it silently, per the
standing rule on destructive actions. If approved: `DELETE FROM
scheduled_job WHERE key = 'ml-retrain-all'` (the code files `app/tasks/ml.py`'s
`retrain_all` and `app/services/ml/job_queue.py` are a separate, larger
dead-code question — not touched by this DB-only cut).

## The other 61, reviewed by pattern (not each individually re-litigated — same review discipline, grouped where the justification is identical)

No other same-task-name-different-schedule pairs exist in the 62 (checked
systematically across all three categories) — `ml-retrain-all` was the only
one. The remaining 61 fall into clean, non-overlapping categories, each
justified by what it uniquely does:

- **Daily-brief pipeline (4):** `daily-brief-context-update` (11pm, builds
  tomorrow's context) → `daily-brief-archive` (midnight, closes today's) →
  `daily-brief-consolidate` (every 30min, rolling merge) →
  `daily-brief-weekly-synthesis` (Sunday, cross-week pattern). Four distinct
  stages, four distinct cadences — a pipeline, not sprawl.
- **Consolidation pipeline (5):** `afternoon-consolidation` (2pm) +
  `evening-consolidation` (9pm) are the documented-intentional 2x/day
  cadence (existing memory: `run_consolidation` twice daily by design, not
  a duplicate bug). `nightly-consolidation` and `nightly-dream-cycle` are
  different functions (memory consolidation vs. dream/insight generation).
  `consolidation-watcher` (60s) is the trigger-check, not a run itself.
- **Research/learning pipeline (3):** `deep-research-poller` (60s) →
  `pending-source-fetcher` (120s) → `check-stuck-research` (180s) — three
  distinct stages of one pipeline (poll for work → fetch sources → detect
  stuck jobs), not three copies of the same check.
- **Anticipation pair (2):** `morning-anticipation` / `evening-anticipation`
  are different functions producing different content (AM look-ahead vs. PM
  look-ahead) — a deliberate pair, not a twin.
- **Email sync pair (2):** `email-sync` (inbox, 180s) / `sync-sent-items`
  (sent folder, 900s) — different mailboxes, different functions.
- **ML pipeline (3, post-cut):** `ml-retrain-inprocess` (train) →
  `materialize-ml-features` (feature prep) → `sync-ml-notification-outcomes`
  (label sync) — three distinct stages, all still needed.
- **Standalone maintenance/anchor/sensor sweeps (~42):** each does one
  specific thing on its own schedule with no sibling to compare against —
  reflection reports, attention-escalation expiry, retention cleanup,
  prediction matching/generation/calibration, PKG stale-goal sweep and
  reconciliation, buffer cleanup, heartbeat, fleet metric pruning and
  offline-sweep, location-trigger expiry, dispatch watchdog, intent-graph
  sync, container cleanup, idle processing, scratchpad cleanup, weekly
  system-wiring check, home-state summary, ended-meeting scan, belief
  promotion, health anomaly detection, subconscious tier-0 tick,
  learning-digest weekly send, morning inbox digest, health baseline
  recompute, daily rhythm recompute, research brief generation,
  delivery-policy flush, bedtime intelligence, weekly health consolidation,
  morning brief generation, morning readiness compute, morning-proactive
  check, world-brief sweep and say-candidate purge. Each is a single-purpose
  sweep or generator with a schedule matched to how often its underlying
  condition can actually change — no duplicate function names, no
  overlapping scope found on inspection.

## Ruling

62 legitimately-classified plumbing jobs, minus 1 confirmed-dead
(`ml-retrain-all`, pending a one-line yes to delete the row) = **61**. The
original ≤30 target was a proxy set against a wrong census (71 jobs assumed,
of which most were plumbing) — it was never derived from what a system this
size actually needs. Per-job review found real pipeline structure (daily-
brief, consolidation, research, ML) that looks like sprawl at a glance but
isn't at the function level, plus exactly one genuine dead job.

**Revised target: 61, not ≤30.** The number itself isn't the invariant —
per-job justification is (per the work order). This document is that
justification, one pass, dated; re-run it if the count drifts meaningfully
rather than trusting a stale target number.

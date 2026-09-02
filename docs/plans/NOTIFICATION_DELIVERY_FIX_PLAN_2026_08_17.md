# Notification Delivery Fix Plan — 2026-08-17

Sara generates plenty of notifications but almost none reach David's phone:
last 7 days, ~41 inbox items created (5–11/day) plus ~27 suppressed attempts,
against only 2–3 actual pushes/day. Four stacked gates each eat a share, and a
scheduler bug feeds the whole pipe corrupted input. All four root causes below
were verified live on 2026-08-17 (DB queries + beat/worker logs + in-container
repro).

What is NOT broken (verified, leave alone): the sleep gate itself, the
held-notification flush (0 stuck rows), exact-topic dedup for genuinely
duplicate sends, and `notification-predispatch`'s 5-second interval (by
design, `scheduled_job.interval_seconds=5`).

---

## Phase 1 — Beat double-fire (do first; corrupts everything downstream)

### Root cause (confirmed by repro)

`DBScheduler._reload()` (backend/app/celery_beat/db_scheduler.py:137) seeds
`entry.last_run_at` from `scheduled_job.last_run_at` — a timestamptz that
SQLAlchemy returns **UTC-aware**. Celery's `crontab.is_due()` does its
calendar-field arithmetic in the datetime's *own* tz frame, so a `0 6 * * *`
ET schedule with a UTC-aware last-run comes due at **06:00 UTC (02:00 ET)
and again at 06:00 ET**. Container repro (celery app tz=America/New_York,
nowfun=ET, cron `0 6 * * *`):

- last_run_at ET-aware, now=02:00 ET → `is_due=False` (correct)
- last_run_at UTC-aware (same instant!), now=02:00 ET → `is_due=True` (bug)
- last_run_at=02:00 ET (after the bugged fire), now=06:00 ET → `is_due=True`
  → the second fire

Observed: every daily cron job dispatched twice on 8/14, 8/15, 8/17
(morning-brief-generate at 02:00+06:00 ET, daily-autonomy-digest at
17:40+21:40, research-brief at 22:00+02:00, morning-inbox-digest at
04:00+08:00).

### Damage chain this causes

1. The 02:00 ET morning brief **pushes at 2 AM** — source `morning_brief` is
   sleep-gate-exempt (delivery_policy.py:45 `_ALWAYS_DELIVER_SOURCES`,
   assumed to only fire at wake time).
2. The real 06:00 ET brief is then dedup-blocked (same topic
   `morning_brief:<date>`) — David never gets his wake-time brief.
3. The 2 AM run's category-`general` outbox item cooldown-blocks the research
   brief notification minutes later.
4. Duplicate 2 AM sends burn the 2/day push budget before David wakes.

### Fix

In `_reload()`, convert the seeded timestamp into the row's own timezone
before assigning (both the DB path and, defensively, the preserved-prev
path):

```python
tz = ZoneInfo(row.timezone or "America/New_York")
entry.last_run_at = row.last_run_at.astimezone(tz)
```

`_record_run()` may keep writing UTC — storage frame is fine; only the frame
handed to `crontab.is_due()` matters.

### Tests + verification

- Unit test: fake-nowfun crontab exactly as `_parse_cron` builds it; assert
  NOT due at 02:00 ET when last run was yesterday 06:00 ET *stored as
  UTC-aware then converted*, and due at 06:00 ET. (The repro script from
  2026-08-17 is the test body.)
- Live (next morning after deploy): beat log shows exactly ONE
  `Sending due task morning-brief-generate` line, at 06:00 ET; notification_log
  has no sent rows between 01:00–05:00 ET; the 06:0x brief row is `sent=true`
  not dedup_blocked.

---

## Phase 2 — Attention-queue cooldown counts creations, not deliveries

### Root cause

`route_through_attention_queue` (unified_notification.py:1168–1190)
suppresses a new item entirely when ANY `outbox_item` of the same category
was **created** in the cooldown window (2h for checkin) — regardless of
whether that item ever buzzed or was even seen. Deliberation produces
check-ins faster than 2h apart, so distinct check-ins starve each other:
0-for-8 pushed this week, several dropped with no inbox row at all.

The guard's original purpose (2026-07-06 gotcha) was to stop a 15-min sweep
recreating the *same* recycled item; the permanent per-dedupe-key block for
`checkin` (unified_notification.py:1144–1159) now covers that case.

### Fix

Scope the time-based cooldown to what it's actually protecting against:

- Keep the permanent per-dedupe-key dedup as-is.
- Change the category-cooldown query to count only items that were
  **delivered** in the window — i.e. `notification_log` rows with
  `sent = TRUE` for that category (the same signal `_check_dedup` already
  uses on direct sends) — instead of `outbox_item` creations.
- Item creation itself becomes allowed: an unpushed, unread inbox item must
  never block a *different* item from existing. Inbox rows are cheap; buzzes
  are what the cooldown rations, and the push path already rations them
  (learned buzz + budget).

### Tests + verification

- Two distinct-dedupe-key checkins 30 min apart → both create outbox items;
  push decision left to the buzz/budget gates.
- Same dedupe_key twice → second still suppressed (permanent guard).
- Live: deliberation check-ins appear in the inbox at their natural cadence
  instead of vanishing into `attention_cooldown` log rows.

---

## Phase 3 — Learned-buzz gate is unreachable (normal priority never buzzes)

### Root cause

`_learned_buzz_decision` (unified_notification.py:994) pushes normal/low
items only when the category's trailing-30d **engagement** rate ≥ 40%.
Actual rates: general 15% (7/46), checkin 12%, agent_task 6% — no active
category qualifies, and since engagement only accrues from pushes, rates can
never climb (death spiral). Cold-start grace applies only to categories with
<5 sends/30d, which no active category is.

### Fix

Make the gate reachable and self-correcting:

- Blend read behavior in: push when
  `engaged_rate >= 0.25 OR read_rate >= 0.5` (read_at is already recorded;
  general reads at 78%). Keep the interruptibility ≥ 0.5 condition.
- Extend the grace path: a category with **no push in the last 7 days** gets
  one grace push/day (same `GRACE_PUSHES_PER_CATEGORY_PER_DAY` ledger), so a
  category that fell silent can re-earn stats instead of staying dead.
- Log the decision inputs (sent/engaged/read counts, rates, interruptibility
  score) at INFO on every buzz decision so the funnel debug endpoint can show
  *why* something stayed quiet.

Thresholds are tunables (`tunable_setting`), not literals — same pattern as
the category limits (migration 094 precedent).

### Tests + verification

- Category with 50% read-rate, 10% engagement → buzzes.
- Category with 10% read + 10% engagement → inbox-only.
- Category with 0 pushes in 7d → grace push granted, capped per day.

---

## Phase 4 — Daily budget throttles high-priority anchors

### Root cause

`_daily_push_budget_available` (unified_notification.py:1057) exempts only
`urgent`/`critical` priority and timer/reminder categories. The July 25 plan
scoped the 2/day budget to "non-urgent *proactive* pushes" — but as coded it
also counts and gates the scheduled anchors (morning brief, weekly health
report — both `high`), which typically consume both slots before 7 AM. After
that, nothing else can buzz all day no matter how much it earned it.

### Fix

- Exempt `high` priority from the budget check (`priority in ("high",
  "urgent", "critical")` at unified_notification.py:1061) — high already has
  a meaningfully higher bar to mint, and the attention queue's
  should_push logic is the place that decides "high always buzzes."
- Keep the budget exactly as-is for normal/low pushes earned via the learned
  buzz — that's the population the July 25 cap was aimed at.
- Exclude high/urgent/critical rows from the budget *count* query too
  (already done via `priority NOT IN` — extend it to include 'high') so
  anchors stop consuming the chatter budget.

### Tests + verification

- Morning brief + health report + 2 buzzed check-ins all deliver on the same
  day; a third normal-priority buzz is budget-suppressed.

---

## Phase 5 — Funnel observability (so this never needs a 2-hour archaeology dig again)

- Persist the suppression reason: add `suppress_reason varchar(40)` to
  `notification_log` (values: `attention_cooldown`, `dedupe_key_surfaced`,
  `dedup`, `budget`, `buzz_declined`, `held_asleep`, ...). Every code path
  that writes `sent=false` today already knows its reason — it just returns
  it to a caller that drops it.
- Extend `/debug/notification-funnel` to render, per day: created →
  suppressed (by reason) → inboxed-only → pushed. This turns "a lot are lost
  in the app" into a one-request diagnosis.
- Confirm with David: the bulk archive of 5 unread items in 10 seconds
  (2026-08-16 07:41) — manual archive-all tap, or something automated? If
  automated, find and evaluate it; unread items being archived silently is
  another way things get "lost in the app."

---

## Sequencing

| Order | Item | Size | Why |
|-------|------|------|-----|
| 1 | Phase 1 beat double-fire | ~5 lines + test | Restores the 6 AM brief, stops 2 AM pushes, uncorrupts dedup/budget inputs |
| 2 | Phase 2 cooldown scope | small | Check-ins stop starving each other |
| 3 | Phase 4 budget exemption | ~3 lines | High-priority anchors stop eating the day's slots |
| 4 | Phase 3 buzz gate | medium | Normal-priority items can finally earn a buzz |
| 5 | Phase 5 observability | small + migration | Reasons persisted, funnel visible |

Phases 2–4 change *who gets to buzz*, so land Phase 1 first and give it one
clean morning — otherwise the before/after comparison is polluted by the
double-fire.

## Deploy notes

- Backend + celery workers + **beat** all load code at container restart only
  (gotcha_deployed_code_lags). Phase 1 specifically requires restarting
  `jarvis-celery-beat-1`.
- After each phase: rebuild, restart, then verify against the running
  container (beat logs for Phase 1; `/debug/notification-funnel` + DB queries
  for the rest).
- Timezone rules per feedback_no_utc: all new hour/date logic through
  `app.core.timezone` helpers; the Phase 1 fix converts *into* the row's tz,
  never strips awareness.

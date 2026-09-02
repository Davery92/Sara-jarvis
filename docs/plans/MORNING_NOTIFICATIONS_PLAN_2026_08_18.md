# Morning Notifications Consolidation Plan — 2026-08-18

Follow-up to `NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17.md` (phases 1–5 landed).
Driven by the 2026-08-17/18 archaeology:

- **Evening 08-17**: arrival check-in generated twice ("Glad you're home" 5:55 PM,
  "Glad you're back" 6:01 PM), both silently suppressed by the 2/day push budget
  (`suppress_reason='budget'`) — David saw them in the inbox but got no buzz.
- **Morning 08-18**: four near-identical morning messages; three buzzes in 30 min
  (6:01 brief, 6:24 held-digest, 6:31 "Morning heads up"), a fifth attempt at 8:01
  blocked only by attention_cooldown.
- **2:04 AM research brief silently lost**: `hold_notification()` does
  `await db.execute(...)` but the Celery research-brief path passes a sync
  Session → `TypeError: object CursorResult can't be used in 'await' expression`
  → INSERT rolled back → never flushed. `held_notification` id sequence gap
  (19→23) says this has eaten ~3 prior notifications too.

David's directive: **remove the budget — he wants notifications.** Target shape:
**one** good-morning push covering the briefing + overnight items, plus **one**
departure-timed push closer to when he leaves, and nothing else morning-flavored.

---

## Phase 1 — Remove the daily push budget

`backend/app/services/unified_notification.py`:

- Delete `_daily_push_budget_available()` (~L1119), `DAILY_NON_URGENT_PUSH_BUDGET`,
  `_BUDGET_EXEMPT_CATEGORIES` (only referenced by the budget fn and its SQL literal).
- Delete the call site in the attention-queue push path (~L1321–1363): the
  `budget_exhausted` branch, `suppress_reason="budget"`, and the
  `daily_push_budget_exhausted` reason string. Keep the `buzz_declined` path —
  the learned buzz gate stays; it's the intended arbiter now.
- Grep tests for `budget` (`test_learned_buzz_gate.py`, any funnel tests) and
  delete/adjust assertions that expect budget suppression.

What still throttles after this (intentional): priority gating + learned buzz
gate, per-category attention cooldowns, topic dedup, sleep hold, anti-harping.
The budget was a blunt cap on top of all of those; removing it un-starves
evening check-ins without opening a firehose.

## Phase 2 — Stop losing held notifications (sync/async bug)

`backend/app/services/delivery_policy.py::hold_notification` (~L344):

- `await db.execute(...)` / `await db.commit()` / `await db.rollback()` break on
  sync Sessions. Reuse the `inspect.isawaitable` pattern from
  `unified_notification._db_execute` — move that helper into `delivery_policy`
  (or a tiny shared module) and use it for execute/commit/rollback here.
- Audit the rest of `delivery_policy.py` (`decide_delivery`, `sense_sleep_state`)
  for the same pattern — anything reachable from Celery sync paths.
- Test: call `hold_notification` with a sync Session; assert the row persists.
- Verify live after deploy: the 2 AM research brief lands in `held_notification`
  and appears in the morning flush.

## Phase 3 — One good-morning push

Today's 6 AM window has four independent generators: `morning-brief-generate`
(cron 6:00), `morning-anticipation` (cron 6:00), `periodic-deliberation-fallback`
(every 30 min, keeps re-composing "good morning, 70°F, Iron Forums…"), and the
`delivery-policy-flush` digest (every 15 min). Consolidation:

**3a. The morning brief becomes the single wake anchor.**
`app/tasks/morning_brief.py` at send time:
- Query `held_notification` for pending held items; fold them into the brief
  push body (one line each, e.g. "Overnight: research brief ready · …") and mark
  them `delivered` with the brief's log id. The 6:24 "Two things while you
  slept" push disappears — its content rides the brief.
- If David is still asleep at 6:00 (per `sense_sleep_state`), the brief itself
  holds (`deliver_after` = 8:00 fallback) and the flush task delivers the
  combined push at sensed wake. Either way: exactly one wake push.

**3b. Morning-greeting slot in the deliberation gate.**
`deliberation_gate.py`, before `send_notification`:
- If the proposal is greeting/schedule-class ("morning" content, category
  `schedule` or `checkin` between 4 AM and noon) and a morning-anchor push has
  already been logged today → suppress with new `suppress_reason='covered_by_brief'`
  (funnel-visible per yesterday's Phase 5), UNLESS it's forward-looking event
  content — that routes to the departure brief queue (Phase 4) instead of pushing.

**3c. Digest deliveries arm their categories' cooldowns.**
When held items are delivered inside the brief (or any flush digest), write a
per-item `notification_log` row (`sent=true`, `source='held_flush_item'`,
original category/topic) — log-only, no extra push. That's what lets the 6:31
"Morning heads up" get caught by the schedule cooldown it currently sails past.

## Phase 4 — Departure brief (the second morning push)

One push ~25 min before David leaves, carrying the actionable stuff:
first calendar event + commute weather + `training_day.is_training_day()`
gym-bag line + anything queued during the morning quiet window.

- **Departure time, staged:** v1 = `app_settings` key
  `weekday_departure_time` (confirm actual with David; default 7:40 ET).
  v2 (later) = learn it from `activity_state_machine` home→AWAY transition
  times (median of last 2 weeks of weekdays); the state machine already senses
  AWAY, we just need to persist transition timestamps.
- New task `app/tasks/departure_brief.py`; beat cron every 5 min, 6–10 AM
  weekdays. Fires once per ET day when `now >= departure - 25min`. Priority
  `high` (anchor class), category `schedule`. Skip silently if already AWAY.
- **Queue instead of suppress:** forward-looking schedule proposals caught by
  3b (e.g. "Iron Forums at 1") insert into `held_notification` with
  `held_reason='await_departure'`; the departure brief drains and folds them in.
  Anything left un-drained (weekend, no departure) force-flushes at 10 AM.

## Phase 5 — Dedup that survives rephrasing

The gate's dedup topic is `category:md5(title + message[:100])`
(`deliberation_gate.py:1105`) — the LLM re-words every cycle, so every copy is
"new". Fix by class:

- **Greetings/check-ins:** dedup key = `category + ET-date + slot`
  (slot ∈ morning/afternoon/evening/arrival). One arrival check-in per arrival,
  one morning greeting per day — regardless of wording. Fixes both the
  5:47/6:04/6:31 triplicate and the 5:55/6:01 PM double.
- **Event reminders:** dedup key = calendar event id + ET-date.
- Keep the content hash only as a secondary exact-dupe guard.

## Phase 6 — Memory-search ranking fix (the "you don't remember Saturday" bug)

Confirmed 2026-08-18 by replaying Sara's exact `memory_search` query against the
tool's exact SQL: the Aug 15 tool-suite/cyber-router conversation is fully
stored and embedded, scored the **highest similarity in the whole table for the
query (0.58–0.63)** — and ranked **#67–#540**. Top-20 was "busy day" /
"Good morning"-class episodes at similarity 0.32–0.38 riding importance +
access_count + rating boosts. With `limit` 6–8, zero relevant hits returned,
so Sara honestly reported no memory of it.

Root cause — `memory_service.py::search_memory` (~L586) composite:
`sim*0.55 + importance*0.25 + ln(access+1)/4.6*0.10 + rating*0.05 + exploration*0.05`
- **No recency term, no `min_similarity` floor** — despite the comment claiming
  it "mirrors main_simple.py retrieve_episodes_with_window", which has both
  (15% recency @ 14-day half-life, similarity floor — `main_simple.py:3544`).
- bge-m3 similarity only spreads ~0.25 across the corpus, so its weighted
  advantage (~0.14) loses to the up-to-~0.45 the other terms can stack. Old,
  much-accessed, high-importance episodes structurally outrank fresh relevant
  ones — and win *more* over time as access_count compounds.

### Fix

In `search_memory`'s episode SQL:

- **Similarity leads:** re-weight to `sim*0.70 + recency*0.15 + importance*0.10
  + rating_boost*0.05`. Drop the access_count term from this path entirely —
  it's a popularity feedback loop (every retrieval makes the same episodes
  easier to retrieve next time).
- **Add the recency term** from the context path:
  `EXP(-EXTRACT(EPOCH FROM (NOW() - e.created_at)) / (14 * 86400)) * 0.15`.
- **Add a similarity floor:** `AND (1 - (e.embedding <=> CAST(:qvec AS vector))) >= 0.45`
  (tune against the replay below; the goal is to stop returning sim-0.32
  filler when nothing relevant exists — an honest "nothing found" beats
  confident noise).
- Order candidates by raw similarity in an inner query (use the HNSW index),
  then composite-rank the top ~50 — not composite-rank the whole table.
- Update the stale "mirrors retrieve_episodes_with_window" comment to state
  the actual shared formula, and extract the two copies' score expression into
  one shared SQL fragment/constant so they can't drift apart again.

### Related: duplicate episode storage

Every chat message is stored 2–3× with distinct ids (~0.3–0.5 s apart — seen
in both the Aug 15 and Aug 18 conversations; likely double-invocation of the
episode-store path in `/chat/stream`, possibly SSE retry). Multiplies the
noise ranking has to fight through and inflates access/importance stats.
Diagnose while in here; if the fix is small (idempotency key on
conversation_id+role+content-hash), land it in this phase, otherwise split it
out.

### Tests + verification

- Regression test with a seeded corpus: fresh high-sim episode must outrank
  old low-sim/high-importance ones; below-floor queries return empty.
- Live replay: re-run the exact query
  `"cyber tool auto routing prompts to backend risk ninja suite of tools"`
  through the tool and assert the Aug 15 episodes land in the top 6.
- Ask Sara the original question again in chat — she should recall Saturday.

## Phase 7 — Verify

- Tests: budget removal (no suppression at N>2), sync-session hold, brief
  folding held items + marking delivered, greeting-slot dedup, departure-brief
  once-per-day trigger.
- Live acceptance, next weekday morning: **exactly two** morning pushes —
  wake anchor (brief + overnight) and departure brief — plus evening arrival
  check-in that actually buzzes. `/debug/notification-funnel` shows
  `covered_by_brief` / slot-dedup suppressions instead of a push burst.

## Sequencing

| # | Phase | Size | Why this order |
|---|-------|------|----------------|
| 1 | Budget removal | ~40 lines deleted | User directive; unblocks evening check-ins immediately |
| 2 | hold_notification sync fix | ~10 lines | Actively losing content nightly |
| 3 | Wake anchor + greeting slot + cooldown stamping | medium | Collapses the 4-push morning to 1 |
| 4 | Departure brief | medium (new task) | Needs 3b's routing hook |
| 5 | Slot dedup | small-medium | Hardens 3/4 against rephrasing |
| 6 | Memory-search ranking fix | small SQL + tests | Independent of 1–5; can land anytime — Sara currently can't recall recent conversations |

## Deploy notes

- Backend AND celery workers load code at container start
  (gotcha_deployed_code_lags) — restart `backend`, `celery-worker`, and
  `celery-beat` after landing; verify with next-morning logs, not code reads.
- All hour logic in ET via `app.core.timezone` helpers (feedback_no_utc);
  departure-brief once-per-day latch must be ET-date-keyed.
- New `suppress_reason` values (`covered_by_brief`) are varchar(40) — fits, no
  migration needed; `held_reason='await_departure'` likewise.

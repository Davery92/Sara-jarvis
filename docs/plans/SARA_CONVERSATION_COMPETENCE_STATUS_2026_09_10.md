# Conversation competence: what is actually done

Date: 2026-09-10
Plan: `SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md`
Evidence: `backend/tests/replay/` (Phase 0 harness), `SARA_CONTEXT_CONSUMER_MAP_2026_09_10.md`

An audit of the first implementation pass said "Phases 1–5 implemented and tested" overstated the
work, and that the right next step was Phase 0 — capture the real evidence, build a
write-intercepting replay, and measure the rest against it. That was correct on every count. Phase 0
now exists, and this file records what it shows rather than what was claimed.

## Phase 0 — done

* **Fixture.** All eight exchanges of 2026-09-09/10 (`turns.json`), the schema, the world rows behind
  them, and the four daily-brief markdown layers. Captured read-only from the live database with
  `default_transaction_read_only=on`; emails, phone numbers and street addresses redacted; family
  first names deliberately kept, because the calendar failure is about a first name being read as a
  place.
* **Replay.** `sara_replay`, a throwaway database rebuilt from the fixture, with the world rewound to
  each turn's minute, the clock frozen to it (including the bare `datetime.now()` inside
  `render_when`), every mutating tool recorded instead of executed, and every SQL write ledgered. It
  refuses to start unless `DATABASE_URL` names the replay database.
* **Consumer/writer map.** `SARA_CONTEXT_CONSUMER_MAP_2026_09_10.md`.

Limits are listed in `backend/tests/replay/README.md` and are real: the replay reassembles
`chat_stream`'s context rather than calling the endpoint (no seam exists yet — Phase 2 must create
one), state tables cannot be rewound, and voice/iOS are not covered.

## Every observed failure, replayed

| Observed 2026-09-09/10 | Status | Evidence |
|---|---|---|
| Everett's dentist became David's appointment "in Everett" | **fixed** | Both renderers now carry owner + relation; `TestCalendarOwnership` (4 assertions on the assembled prompt) |
| Prompt carried unavailable HRV *and* recovery prose using HRV 48 | **fixed** | `hrv=unavailable (nothing recorded in the last 36h)`; no HRV number anywhere else in the prompt — `TestHrvContradiction` |
| Planned dinner logged as eaten, with invented ingredients | **fixed** | Live model replay of the actual turn: zero tool calls, zero `food_log` writes, no invented quantities — `TestPlannedDinnerIsNotEaten` (model) |
| Recalled workout remarks lacked dates | **fixed** | Every recall line now renders speaker + relative date + id — `TestRecallRendering` |
| A greeting produced a full briefing | **partly fixed** | Recall no longer fires on phatic turns while short recall questions still work (`should_skip_recall`); the briefing content itself is the brief, unchanged |
| Casual workout remark → questions about already-logged activity | **open** | The session is still not in the prompt: the brief carries one last set, and `workout_log` had 14 sets across 6 exercises — `TestLoggedWorkoutIsAvailable::test_the_whole_session_can_be_consulted` (xfail) |
| Recall returned unrelated personal background | **open** | Replaying "That was a good workout after that break" still recalls Salem, an agent task and a rescheduled call — `TestRecallRendering::test_recall_is_about_what_david_just_said` (xfail) |
| Narrative asserted a low-stress equilibrium as established understanding | **open** | The stored paragraph still says it and still seeds its own next rewrite — `TestPersonalNarrative` (xfail) |
| Yesterday's material under a "Today" heading | **open** | At 06:54 Thursday the day layer is Wednesday's, under `## Today` — `TestDailySummary::test_today_means_today` (xfail) |
| Summaries promoted Sara's own suggestions to fact | **open** | "Sara confirms this is a successful close…", "she offers to schedule tomorrow's meals" — `TestDailySummary` (xfail) |
| "Day is clear" from one calendar feed | **not reproduced** | Needs the coverage state of the calendar sync at that minute, which the fixture cannot rewind (state table). Not asserted either way. |

Five failures reproduce and are marked `xfail(strict=True)`: they fail today, which is the honest
state, and this suite turns red the day someone fixes them.

## Phase status, corrected

| Phase | Claimed | Actual |
|---|---|---|
| 0 — reproducible baseline | skipped ("no data") | **done** — the data was there the whole time |
| 1 — concrete correctness gaps | done | **mostly done.** Calendar ownership, HRV freshness, food grounding, live-context stripping all verified by replay. The completed-workout summary was never built. |
| 2 — conversation and recall coherence | done | **partial.** Recall gate, attribution, thin-episode context, history reconciliation and the post-`render_engaged_context` budget landed. Topic ranking did not, and there is still no single assembly function to put one budget over. |
| 3 — durable corrections | done | **partial.** Food prohibitions and retractions persist (`correction`, migration 151). Attendance, preference, temporary exception and interval scope do not exist, and no correction invalidates any projection — see the consumer map's closing list. |
| 4 — personal understanding from evidence | done | **partial, as the audit said.** Stress framing and a 72-hour expiry are in. Claim-level provenance, evidence-age tracking, and the daily-summary changes are not; the document still feeds itself. |
| 5 — behaviour and model capability | done | **partial, as the audit said.** The fitness-prompt contradiction is fixed and food-tool grounding works under replay. The full instruction audit, grounding for other mutable tools, execution-receipt checks and the model comparison have not been done. |

## The test-count claim, checked

The earlier report of "60 failures, all pre-existing" is now verified rather than asserted, by running
the suite twice — once on the working tree, once on a clean export of `HEAD` copied into the same
container:

```
HEAD:          63 failed, 1430 passed, 9 skipped, 30 errors
working tree:  60 failed, 1483 passed, 9 skipped, 30 errors
new failures:  none
fixed:         3 (workout approval/legacy-compat)
```

The 60 failures and 30 errors are identical sets at HEAD and on the working tree — mostly
`ModuleNotFoundError` for `app.services.acs` (lives in the daemon repo) and similar import breakage
that predates this work. The audit was right that passing unit tests say nothing about whether Sara
is easier to talk to; that is what the replay is for.

## What the replay found that nobody had listed

* **The daily-brief layers are files on a live mount**, written by four modules that each hardcode the
  path. Any test, shadow run or replay that doesn't redirect them reads — and can write — David's real
  narrative.
* **No cache is ever invalidated.** `sara:context_snapshot:<user>` (20s) and
  `world_brief:rendered:<user>` (120s) have no invalidation hook anywhere in `app/`. A correction is
  stale-visible for up to two minutes on every surface.
* **Food logging writes `role='user'` episodes** (`source='fitness_food'`) that Phase 2's new
  attribution renders as "David said". He didn't; he pressed a button.
* **`episode` and `conversation_turn` are two unreconciled recordings** of the same conversation,
  written in the same function with different dedup rules.

## Next

1. Close the five reproduced failures, cheapest first: the "Today" heading and the day-layer
   attribution (Phase 4), then recall topic ranking (Phase 2), then the workout-session summary
   (Phase 1), then the self-seeding narrative (Phase 4, the expensive one).
2. Extract one assembly function out of `chat_stream` so the replay covers the endpoint rather than a
   faithful reconstruction of it, and so Phase 2's single budget has something to apply to.
3. Add cache invalidation to the correction path before adding more correction kinds — a correction
   that lands in a store nothing re-reads is not a correction.
4. Only then the Phase 5 model comparison, which is meaningless until the context is right.

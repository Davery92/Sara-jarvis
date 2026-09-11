# Replaying 2026-09-09/10

The eight exchanges that `docs/plans/SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md` was written
from, frozen into a fixture and re-runnable against whatever the code does today.

```bash
backend/tests/replay/run_replay.sh              # the suite (~20s)
backend/tests/replay/run_replay.sh -k calendar  # pytest args pass through

# with the model — real calls to the chat lane, ~25s per turn
SARA_REPLAY_MODEL=1 backend/tests/replay/run_replay.sh -k "Dinner or Casual"

# read one turn's assembled prompt yourself
LIVE=$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-); docker compose exec -T \
  -e DATABASE_URL="${LIVE%/*}/sara_replay" -e REDIS_URL=redis://redis:6379/15 -e SARA_REPLAY=1 \
  backend python -m tests.replay.show 6 --full
```

## What's here

| File | |
|---|---|
| `capture.py` | Read-only capture from the live database into `fixtures/2026_09_09/`. Run once; it already has been. |
| `provision.py` | Builds the throwaway `sara_replay` database from the fixture. `--check` to see if it's there. |
| `harness.py` | The replay itself: safety guard, rewind, frozen clock, write ledger, tool interception, assembly. |
| `show.py` | Prints one turn's assembled prompt and its size account next to what Sara actually said. |
| `test_harness_smoke.py` | The harness's own guarantees. If these fail, nothing else here means anything. |
| `test_observed_failures.py` | One class per observed failure: fixed (asserted), still open (xfail), or skipped with a reason. |

## What a replay guarantees

**It cannot touch live data.** `DATABASE_URL` must name `sara_replay` or the harness refuses to
start; `REDIS_URL` must name db 15 before anything flushes a cache; the brief layers — which are
markdown files under `data/briefs/`, mounted live, and written by four modules — are redirected to a
temp copy of the fixture's. Mutating tools are recorded and answered, never executed.

**It shows the world as it was at that minute, not as it is now.** Every rewindable table is refilled
from a pristine copy in the `fixture` schema, filtered to rows that existed at the turn's timestamp
(`harness.rewind_to`); the clock — including the bare `datetime.now()` inside `render_when`, which
every timestamp in a prompt passes through — is pinned to the same minute.

## What it does not cover

* **Not the `chat_stream` endpoint.** `harness.assemble` reassembles the same blocks through the same
  functions, in the same order, but the endpoint is ~1,100 lines of inline assembly behind an HTTP
  request and there is no seam to call it through. `harness.SECTION_GAPS` names the blocks that are
  therefore not represented (inbox digest, attention-item context, re-entry digest, and four more).
  Phase 2 has to extract a real assembly function; when it does, `assemble` should call that instead.
* **State tables cannot be rewound.** `world_brief`, `world_thread`, `world_fact`, `life_fact`,
  `behavioral_pattern`, `daily_rhythm`, `standing_order`, `directive`, `reminder`, `timer`,
  `scratchpad_entry`, `calendar_event`, `user_profile`, `user_settings` hold current state with no
  history, so the fixture carries them as of capture time (2026-09-10 ~14:20 UTC). The brief layers
  are the same, though `day.md` and `moment.md` happen to have last been written during the final two
  exchanges.
* **Only chat.** Voice and iOS surfaces are not replayed. The plan asks for them; they need the same
  extraction Phase 2 needs.
* **The model is stochastic.** The three model-driven tests are one sample each. The plan's release
  gate asks for repeated runs; that loop isn't built.
* **The fixture needs a live-shaped Postgres to rebuild.** `provision.py` loads `schema.sql.gz` (the
  captured dump) into a fresh database on the same server. This is not a hermetic CI fixture.

## Re-capturing

Don't, unless the point is to capture a *different* day. `capture.py` overwrites the fixture, and the
value of this one is that it is the state of the world on 2026-09-10 — the day the failures were
observed — rather than the state of the world now.

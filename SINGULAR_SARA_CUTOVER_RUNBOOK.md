# Singular Sara — Cutover Runbook

**Status as of 2026-07-24:** every `SINGULAR_*` flag is OFF. Nothing in this
document has been switched on. Sara's live behavior today is bit-for-bit
identical to before this work started — everything built is either a
read-only projection over existing data, or a shadow recorder/shadow call
that runs alongside the real path without being consulted by it.

This is the missing piece §13 and the phase-by-phase work didn't produce on
its own: a map from "the code exists" to "it's safe to flip on," per
`SINGULAR_SARA_MASTER_PLAN_2026_07_24.md` §10 (Rollout and Rollback) and
§9 (Evaluation Program). **Flipping any flag in this document is a product
decision, not a code change** — it should be made by David, one flag at a
time, with the observation window actually served before moving to the next.

## How to check current state

```
GET  /api/diagnostics/feature-flags          # every flag's current value
GET  /api/diagnostics/path-counters?path_name=ambient_cognition&days=7
GET  /api/diagnostics/path-counters?path_name=engaged_cognition&days=7
GET  /api/diagnostics/path-counters?path_name=dreaming_cognition&days=7
GET  /api/diagnostics/truth-audit            # impossible-state scan
GET  /api/diagnostics/body-state             # canonical health projection
GET  /api/diagnostics/context-snapshot       # world/self/relationship
GET  /api/diagnostics/intent-graph           # live projection (46+ items)
GET  /api/diagnostics/intent-graph/persisted # durable intent table
GET  /api/diagnostics/recent-events          # canonical event envelopes
GET  /api/diagnostics/attention-log          # shadow-recorded notification decisions
GET  /api/diagnostics/action-receipts        # shadow-recorded action receipts
GET  /api/diagnostics/body-capabilities      # VM workshop + other bodies
GET  /api/diagnostics/scheduler-diet         # job classification (88 jobs, 22 legacy_cognition)
```

## How to flip a flag

```python
from app.core.feature_flags import Flag, set_flag
set_flag(Flag.SINGULAR_KERNEL, True, updated_by="david")
```

No restart required — every call site reads the flag fresh from
`app_settings` on each check. To roll back, set it back to `False`; nothing
that was built here has a destructive one-way migration path.

## Per-flag cutover guide

### `SINGULAR_KERNEL` — the one that matters most

Gates three real fold-ins, all built and tested in shadow, none yet observed
under real production load:

1. **Ambient** (`app/tasks/autonomy.py`): `periodic_deliberation_fallback`
   and `deep_deliberation` stop calling `deliberation_engine.run()` directly
   and route through `kernel.ambient_turn()` instead.
2. **Engaged** (`app/main_simple.py` `/chat/stream`): currently ALWAYS runs
   `kernel.engaged_turn()` in shadow (fire-and-forget, never touches the
   response). This flag does not change engaged behavior today — engaged
   cognition has no legacy/target fork yet, only a shadow probe. Treat
   "route real chat through kernel.engaged_turn's output" as unbuilt.
3. **Dreaming** (`app/tasks/reflection.py`): `_run_reflection_async` stops
   calling the reflection agent directly and routes through
   `kernel.dreaming_turn()`.

**Before flipping ON:**
- Check `path-counters?path_name=ambient_cognition` — confirm the legacy
  lane has meaningful daily volume (proof this flag will actually be
  exercised, not a no-op).
- Read `SINGULAR_SARA_MASTER_PLAN_2026_07_24.md` §9.1 scenario suite — none
  of those scenarios have been run against the kernel path yet. This flag
  should not go on before at least the ambient-cognition scenarios have.
- Confirm `truth-audit` is clean (zero violations) as a baseline — so any
  new violation after cutover is attributable to the cutover.

**Observation window:** the plan's C5 exit gate wants "shadow comparisons
show no lost high-value notices or actions" — that comparison does not
exist as code; it means watching real ambient/dreaming output for a few
days after flipping and confirming nothing the legacy path would have
caught silently drops.

**Rollback:** flip back to `False`. The legacy `deliberation_engine.run()` /
reflection-agent-direct code paths are untouched and still there.

### `SINGULAR_EVENT_ENVELOPE`

Not read by any code path yet — the event-envelope adapter
(`app.services.event_envelope_adapter`) runs unconditionally inside
`EventBus.publish()` today (pure recording, no gate needed because it can't
change behavior). This flag is reserved for the day something is asked to
*read* canonical envelopes as its source of truth instead of the raw event
bus — that reader doesn't exist yet. Leave off.

### `SINGULAR_CONTEXT`

Not read by any code path yet. `context_snapshot.py` and
`body_state_projection.py` are computed fresh on every diagnostics call —
there is no cached "context" consumer to gate. Reserved for when chat/
deliberation/briefs are asked to read the canonical snapshot instead of
computing their own.

### `SINGULAR_INTENTS`

Not read by any code path yet. `intent`/`intent_edge` are populated via
`POST /api/diagnostics/intent-graph/sync` (manual, idempotent) — nothing
currently treats this table as authoritative over `reminder`/
`standing_order`/`autonomy_mission`/etc. Reserved for the day one of those
source tables is retired in favor of `intent` directly (a real, one-way
migration decision — do not take lightly).

### `SINGULAR_VM_BODY`

Not read by any code path yet. `body_capability` is populated by the daemon
heartbeat (once redeployed — the `capabilities` field is additive and the
currently-deployed daemon binary doesn't send it until pushed). Reserved for
when a real work-claiming/lease protocol replaces direct daemon dispatch.

### `SINGULAR_ATTENTION`

Not read by any code path yet. `outbound_intent`/`attention_item` are
shadow-recorded on every `send_notification()` call — nothing acts on the
recorded `decision` field. Reserved for when the attention market's decision
is asked to gate delivery instead of just describing it after the fact.

### `SINGULAR_ACTIONS`

Not read by any code path yet. `action_receipt` is shadow-recorded
alongside every standing-order action — `action_ledger` (undo, audit) is
still authoritative. Reserved for when permission tiers in `action_receipt`
are asked to gate execution instead of just describing it.

### `LEGACY_COGNITION_SHADOW`

Reserved name from the plan's original C0 flag list; no shadow-mode
comparator has been built that this would toggle. Leave off until C5's
real shadow-comparison harness exists.

## Rollout order (§10), annotated with actual status

| # | Stage | Status |
|---|---|---|
| 1 | Telemetry and contracts | **Done** — contracts, correlation IDs, path counters, event envelopes |
| 2 | Context/body projections | **Done (read-only)** — body-state, world/self/relationship snapshots |
| 3 | Intent graph | **Partial** — real table + sync exist; nothing is authoritative yet |
| 4 | Engaged kernel | **Shadow only** — `kernel.engaged_turn()` runs in shadow on every chat turn |
| 5 | Ambient kernel (shadow → active) | **Built, flag-gated, not yet flipped** |
| 6 | Focused kernel + VM body | **Not started** — no mission-brief/lease protocol |
| 7 | Dreaming kernel | **Built, flag-gated, not yet flipped** |
| 8 | Attention/voice | **Shadow only** — decisions recorded, not enforced |
| 9 | Action executor | **Shadow only** — receipts recorded, not enforced |
| 10 | Scheduler retirement | **Classified, not retired** — 88 jobs classified, 22 legacy_cognition candidates, 24 unclassified need manual review |
| 11 | UI | **Not started** — separate branch, out of scope for this work |

## What "done" does NOT mean here

Every "Done" or "Built" above means *the code exists, is unit-tested, and
has been verified against real production data read-only*. It does NOT mean:

- Any multi-day/multi-week observation window has been served (C0's 7-day
  baseline, C12's 4-continuous-week gate) — those require real time passing
  with the flag on, which cannot be satisfied by writing more code.
- The plan's §9.1 scenario suite has been executed even once.
- Sara's live behavior has changed at all — verify this yourself:
  `GET /api/diagnostics/feature-flags` should show every flag `false`.

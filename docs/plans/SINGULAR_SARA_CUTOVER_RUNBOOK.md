# Singular Sara — Cutover Runbook

**Status as of 2026-07-24 (updated):** `SINGULAR_KERNEL`, `SINGULAR_ATTENTION`,
and `SINGULAR_ACTIONS` are **ON**, with your explicit go-ahead, and each
change is real (not shadow):

- ambient/dreaming cognition routes through the kernel instead of calling
  legacy deliberation/reflection code directly;
- `send_notification()` has one new, real dedup gate on top of the
  already-live attention system (see `SINGULAR_ATTENTION` below);
- standing-order actions get read-after-write verification, so
  `action_receipt.status` can be `partial`, not a false `completed`.

`SINGULAR_EVENT_ENVELOPE`, `SINGULAR_CONTEXT`, `SINGULAR_INTENTS`,
`SINGULAR_VM_BODY`, and `LEGACY_COGNITION_SHADOW` remain OFF — nothing reads
them yet (see each section below for why).

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

### `SINGULAR_KERNEL` — ON

Gates three fold-ins:

1. **Ambient** (`app/tasks/autonomy.py`): `periodic_deliberation_fallback`
   and `deep_deliberation` stop calling `deliberation_engine.run()` directly
   and route through `kernel.ambient_turn()` instead.
2. **Engaged** (`app/main_simple.py` `/chat/stream`): still shadow-only —
   `kernel.engaged_turn()` runs fire-and-forget on every real chat turn but
   its output is never consulted. This flag does not change engaged
   behavior; "route real chat through kernel.engaged_turn's output" is
   still unbuilt.
3. **Dreaming** (`app/tasks/reflection.py`): `_run_reflection_async` stops
   calling the reflection agent directly and routes through
   `kernel.dreaming_turn()`.

**Still true, even though it's on:** the plan's own §9.1 scenario suite has
not been run against the kernel path, and the C5 exit gate ("shadow
comparisons show no lost high-value notices or actions") means watching
real ambient/dreaming output over the next several days and confirming
nothing the legacy path would have caught silently drops. Turning the flag
on did not skip that observation need — it just started the clock on it.

**Rollback:** `set_flag(Flag.SINGULAR_KERNEL, False)`. The legacy
`deliberation_engine.run()` / reflection-agent-direct code paths are
untouched and still there.

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

### `SINGULAR_ATTENTION` — ON

Important context: a real attention market already existed before this
plan — `route_through_attention_queue()` (Phase 2, "Cortana Evolution"),
gated by its own separate flag `autonomy_attention_enabled` (already `true`
in production), writing to `autonomy_attention_item`. This flag does not
replace that system. Two real things it does:

1. `attention_shadow_recorder` now classifies decisions from that system's
   actual signals (`routed_through_attention`, `attention_item_id`) instead
   of guessing from `sent`+`priority` — `outbound_intent`/`attention_item`
   are now an accurate record of the real decision, including a genuine
   `add_to_today` outcome for items the real queue created but didn't push.
2. **New, real behavior**: `send_notification()`'s outer wrapper now runs a
   content-based dedup check (`attention_shadow_recorder.check_recent_
   duplicate`) before the rest of the pipeline — if the *exact rendered
   text* was already delivered to David within the lookback window under
   any topic, the send is skipped (`reason: "attention_market_dedup"`).
   This is additive to, not a replacement for, the existing topic-string
   dedup — it catches the case the topic-based check can't (two different
   call sites independently deciding to say the same thing under different
   topics). Never applied to the attention queue's own internal delivery
   call (`_bypass_attention=True`), which would otherwise dedupe a message
   against its own not-yet-committed record.

**Rollback:** `set_flag(Flag.SINGULAR_ATTENTION, False)` — the content-dedup
check stops running; the pre-existing `autonomy_attention_enabled` system is
untouched either way.

### `SINGULAR_ACTIONS` — ON

No pre-existing equivalent existed for actions (unlike attention). What's
real now: `StandingOrderService._verify_action_effect` does a read-only
check of Home Assistant's actual state after `home_control`/
`all_lights_off`/`lock_all` calls — previously "success" only meant "the API
call didn't raise." `action_receipt.status` is now `partial`, not a false
`completed`, when the entity didn't reach the desired state (Definition of
Done #9: "No success state can be displayed when the underlying operation
failed or only partially completed"). `action_ledger` (undo, audit) is
unchanged and still authoritative for undo.

This does **not** gate or block execution — the HA service call still
happens exactly as before; only the *recorded* status became more honest.
There was no safe, non-redundant execution-level gate to add here: standing
orders already enforce their own cooldown via `action_ledger` before
`_execute_action` is ever called, so an additional idempotency gate at this
layer would be dead code, not new protection.

**Rollback:** `set_flag(Flag.SINGULAR_ACTIONS, False)` — receipts stop
recording verified/partial distinctions; `action_ledger` behavior is
unaffected either way.

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
| 5 | Ambient kernel | **ON** — `SINGULAR_KERNEL`, folded in for real |
| 6 | Focused kernel + VM body | **Not started** — no mission-brief/lease protocol |
| 7 | Dreaming kernel | **ON** — `SINGULAR_KERNEL`, folded in for real |
| 8 | Attention/voice | **ON** — `SINGULAR_ATTENTION`; real content-dedup gate, decisions recorded accurately |
| 9 | Action executor | **ON** — `SINGULAR_ACTIONS`; real verified/partial status, execution itself unchanged |
| 10 | Scheduler retirement | **Classified, not retired** — 88 jobs classified, 22 legacy_cognition candidates, 24 unclassified need manual review |
| 11 | UI | **Substantially built** — `feat/singular-sara-ui`: new nav IA (Home/Chat/Today/Memory/Life/Work/Studio/Interior), Interior page (web+iOS) with real interests/intents/contradictions/attention/action views |

## What "ON" does NOT mean here

Every flag marked ON above means *the code exists, is tested, was verified
against real production data, and was reviewed for exactly what it changes
before flipping*. It does NOT mean:

- Any multi-day/multi-week observation window has been served (C0's 7-day
  baseline, C12's 4-continuous-week gate) — those require real time passing
  with the flag on, which cannot be satisfied by writing more code. The
  clock on that observation started today, not before.
- The plan's §9.1 scenario suite has been executed even once.
- Every real-world edge case has been exercised — e.g. the action-effect
  verification (`SINGULAR_ACTIONS`) has been tested against mocked HA
  responses, not a live Home Assistant instance, since this environment
  can't safely poke real lights/locks to check.
- Check current state yourself: `GET /api/diagnostics/feature-flags`.

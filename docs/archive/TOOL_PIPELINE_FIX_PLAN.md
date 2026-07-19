# Tool Pipeline Fix Plan

Fixes for the four defects found in the 2026-07-17 live tool-access audit. Ordered by
user-visible impact. Each fix lists the failure it corrects, the change, and how it was
verified against the running system.

## Audit recap (what was broken)

Probing the live `/chat/stream` pipeline as David (ephemeral mode) found:

1. **29 tools crash in every chat** — all 13 `home_*`, all 13 `chess_*`, both `health_*`,
   and `workout_history` — with `unexpected keyword argument '_conversation_id'`.
   Affects every model, every client. Sara currently cannot control the house from chat.
2. **Qwen text-format tool calls are mis-parsed** — first tool round fails ~100% of the
   time on the local-model path (`<function=calendar_list>` extracted as the tool *name*,
   markup included), parameters are silently dropped (a "3-minute timer named audit-test"
   became an untitled 25-minute timer), raw `<tool_call>` markup once leaked verbatim to
   the user as the reply, and the model flailed after failures (once dispatching a real
   VM agent for a calendar question).
3. **Long tool conversations die before answering** — Postgres kills the request's DB
   connection (`idle-in-transaction timeout`, 5 min) while the slow LLM loops; the
   stream ends with no final response. 4 of 9 audit probes died this way.
4. **Intent classifier emits three nonexistent tool categories** — `acs` (on every
   request), `automation` (HOME intent), `morning_brief` (MORNING_BRIEF intent) — all
   silently dropped by the registry, making the `daily` category (morning_brief,
   weather tools) unreachable from chat.

## Fix 1 — `_conversation_id` crash (registry.py)

**Cause:** the Surfaces work made `execute_tool()` unconditionally inject
`_conversation_id` (and `_task_id`) into every tool's kwargs when chat passes a
conversation context. Tools whose `execute()` lacks `**kwargs` blow up.

**Change:** signature-aware injection in `ToolRegistry.execute_tool()` — inspect each
tool's `execute` signature once (cached), and only pass `_conversation_id` / `_task_id`
to tools that declare the parameter or accept `**kwargs`.

**Conversation-continuity guarantee (the constraint):** this fix changes *nothing* about
how conversations persist or resume:
- iOS close/reopen and cross-device continuation ride on `conversation_id` in the
  ChatRequest + episode history load + `update_active_session()` — none of that is in
  this code path.
- Surface/workspace tools (the reason the injection exists — their rows are scoped to
  the conversation so the client can re-inject them on chat reload) DO accept the kwarg
  and continue to receive it unchanged.
- The 29 fixed tools never used the kwarg; they simply stop being handed it.

## Fix 2 — Qwen text-dialect tool calls (text_utils.py + main_simple.py)

**Cause:** `parse_glm45_tool_calls()` was written for GLM-4.5's dialect
(`<tool_call>name <arg_key>k</arg_key><arg_value>v</arg_value></tool_call>`). Qwen3.x
emits a different one:

```
<tool_call> <function=timers_start> <parameter=duration_minutes> 3 </parameter>
<parameter=title> audit-test </parameter> </function> </tool_call>
```

`parts[0]` therefore captured `<function=timers_start>` as the name, and the
`arg_key/arg_value` regexes found nothing → `{}` arguments → tool defaults.

**Change (parser):** extend `parse_glm45_tool_calls()` to detect the
`<function=NAME>` form first — extract the bare name, parse
`<parameter=key> value </parameter>` pairs (tolerant of missing close tags), and
JSON-coerce values (`true` → bool, `3` → int) with string fallback. The GLM arg_key
path stays as fallback. A final validation rejects any extracted name that isn't a bare
identifier, so markup can never again become a "tool name".

**Change (leak guard):** new `strip_tool_markup()` helper applied to the final response
content before the `final_response` event is emitted — any residual
`<tool_call>/<function=/<parameter=` markup is removed from user-visible text. If
stripping leaves the reply empty, a graceful fallback line is emitted instead of raw XML.

## Fix 3 — idle-in-transaction death (main_simple.py)

**Cause:** `/chat/stream`'s request-scoped session does dozens of context-assembly reads,
then sits in that open transaction for the entire LLM tool loop. Postgres's
`idle_in_transaction_session_timeout` (5 min) kills the connection; the request 500s
after doing all its tool work, and the user gets no answer.

**Change:** `db.commit()` immediately after the last pre-loop read (history retrieval),
before `process_chat()` starts. The connection drops to plain `idle` (not killed by the
timeout); anything that touches `db` later starts a fresh transaction. Tool executions
and episode storage already use their own sessions and are unaffected.

## Fix 4 — classifier category renames (intent_classifier.py)

Three string fixes so every emitted category actually exists:
- `BASE_TOOLS`: `'acs'` → `'agents'` (queue_for_sara, background-task inspection —
  the lightweight cross-cutting set; `vm_agents` is already force-added by chat).
- `'HOME': ['home', 'automation']` → `['home', 'standing_orders']` (recurring/automated
  home requests get the standing-order tools).
- `'MORNING_BRIEF': ['morning_brief', 'time']` → `['daily', 'time']` (unlocks the
  `morning_brief` + `weather` tools — the `daily` category was previously unreachable
  from chat entirely).

## Verification — ALL DONE 2026-07-17 (rebuilt container, live probes)

1. ✅ Registry/classifier audit rerun in the rebuilt container: zero nonexistent
   categories; only `shell` (deliberate) unreachable. 227/227 tools chat-reachable.
2. ✅ Parser unit tests against the exact captured failures: Qwen names extracted bare,
   params typed (`true`→bool, `3`→int), missing close tags tolerated, GLM dialect
   still parses, garbage names dropped, leak stripper cleans residual markup.
3. ✅ `home_status` executes with a conversation context (previously the kwarg crash);
   surface tools still receive `_conversation_id` (continuity preserved); iOS/cross-
   device resume paths untouched.
4. ✅ Live Qwen probe "status of the house": round-1 tool call parsed clean, executed,
   full correct answer (9 lights, unlocked side door) — previously raw markup leaked
   to the user.
5. ✅ Live Qwen probe "3-minute timer called audit-test": created exactly that
   (previously: untitled 25-minute timer). Test row deleted after.
6. ✅ MORNING_BRIEF intent now loads `morning_brief` + `weather` tools live.
7. ◐ Idle-in-transaction: `db.commit()` lands before the LLM loop; baseline
   `pg_stat_activity` churn (7-8 short-lived txns from background services) makes a
   clean single-connection assertion impossible, and post-fix probes finish fast
   enough (round-1 now succeeds) that the 5-minute window is no longer approached.
   Mechanism verified by code path; watch for any recurrence of
   `idle-in-transaction` errors in backend logs.

## Explicitly out of scope

- Qwen argument *quality* (model may still pick odd values — that's model behavior,
  not parsing) and streamed text_chunks briefly showing markup before the final
  response replaces them.
- The `shell` category stays chat-excluded (by design, dispatch agents only).
- Committing: `main_simple.py` and neighbors carry unrelated in-progress work, so these
  fixes are left uncommitted for David to fold into his branch.

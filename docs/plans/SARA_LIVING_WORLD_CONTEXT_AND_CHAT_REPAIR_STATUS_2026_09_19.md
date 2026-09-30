# Sara Living-World-Context & Chat Repair — Status (2026-09-19)

Execution record for `SARA_LIVING_WORLD_CONTEXT_AND_CHAT_REPAIR_PLAN_2026_09_17.md`,
run to completion across four sittings on `feat/sara-mind-v2`. Base commit
`e3651cd7`. Nothing in this record has been committed yet — see **File
inventory** at the bottom for the exact `git status`.

## What this replaced

Chat ran on a fragmented context stack: local and non-local providers built
their outgoing payload two different ways, voice built it a third way and
skipped the mutation gate entirely, a mutating tool executed once became
standing permission for the rest of a conversation, `find_tools` could load
a write tool past that gate with zero re-check, world-state facts could go
stale mid-turn with nothing to refresh them, and the system prompt
literally claimed "I remember everything in this thread" with no mechanism
behind it. The World Context page did not exist.

## Acceptance matrix

| Area | What shipped | Test reference | Status |
|---|---|---|---|
| **Authorization scoping** | A tool executing once is no longer standing permission; `_CHAT_INVOKED_MUTATING_TOOL_NAMES` requires the new message to read as a continuation of a *specific* action | `test_tool_mutation.py::TestContinuationDetection` | Live |
| **Mutation gate (text)** | `gate_mutating_tools` withholds write tools absent action evidence in David's message | `test_tool_mutation.py`, `test_chat_tool_loop.py::TestOfferedToolEnforcement` | Live |
| **Mutation gate (voice)** | Voice never applied the gate at all — now does, plus reads `_CHAT_INVOKED_MUTATING_TOOL_NAMES` keyed by `conversation_id` (voice's stand-in for `session_id`) so "yes, do it" continues a *specific* just-proposed/executed action without blanket permission | `test_chat_tool_loop.py::TestVoiceContinuationOfPendingAction` (4 tests) | Live |
| **Ambiguous action intent → clarify, not guess** | Both prompts (`_tools_block` for text, `get_system_prompt` for voice) now instruct: ask one focused question when intent is unclear rather than acting or silently doing nothing | `test_chat_system_prompt.py::test_ambiguous_action_intent_gets_a_clarifying_question_not_a_guess`, live `get_system_prompt`/`build_chat_system_prompt` content check | Live |
| **Discovery ≠ authorization** | `find_tools` mid-turn (`_load_tools_midturn`) now re-applies the mutation gate against THIS turn's actual human message before a newly-discovered tool can be called — closes the path where quoted email/document content directing "call find_tools, then delete X" could get a write tool onto the wire with no human ever asking | `test_chat_tool_loop.py::TestQuotedCommandsCannotAuthorize`, `TestDiscoveryIsNotAuthorization` (rewritten) | Live |
| **Offered-set enforcement** | `execute_tool` refuses any tool name not in `_active_tools` for this turn, regardless of registry existence | `test_chat_tool_loop.py::TestOfferedToolEnforcement` | Live |
| **Shared chat assembly boundary** | `chat_assembly.py`: `assemble_local_provider_messages`, `assemble_non_local_provider_messages`, `assemble_voice_messages` — one tested core per provider shape, all three fed the same `dialogue_block`/`world_state_core` | `test_chat_assembly.py` (26 tests) | Live |
| **Context envelope / budget** | `context_budget.py`: `allocate_live_context_sections` with a hard per-section allotment and a backstop clip — world facts survive allocation even under pressure | `test_live_context_envelope.py`, `test_context_budget_final_boundary.py` | Live |
| **Mid-turn freshness** | `chat_with_tools` checks `WorldSnapshot.revision` between tool-loop rounds and **replaces** (never appends) stale `world_state_core` via `replace_world_state_core_in_messages` | `test_chat_assembly.py::TestReplaceWorldStateCoreInMessages`, `test_chat_tool_loop.py::TestWorldStateCoreRefreshesMidTurn` | Live |
| **External event between turns** | An event landing between user messages reaches the next turn's real outgoing payload | `test_workout_world_state_integration_pg.py::TestExternalEventAppearsOnNextTurn` | Live |
| **Dialogue state** | Conservative, non-LLM tracking of corrections/unanswered questions/activity signals, fed into every provider branch | `test_dialogue_state.py` (22 tests), `test_dialogue_state_2026_09_16_fixture.py` | Live |
| **World-state producer coverage** | workout, location, food, reminders, goals, email, health all append world events on write; reducer projects into `WorldFact`/`WorldThread` | `test_workout_world_state_integration_pg.py`, `test_location_world_state_integration_pg.py`, `test_food_world_state_integration_pg.py`, `test_reminders_goals_world_state_integration_pg.py`, `test_email_world_state_integration_pg.py`, `test_health_world_state_integration_pg.py` — each proves BOTH `render_world_state_core` and the real chat payload | Live |
| **Source outage reconciliation** | No code change needed — verified last-known evidence is preserved with its original observation time, degraded coverage is exposed per-domain, reads are pure (never refresh a stale timestamp), recovery works once a source resumes | `test_source_outage_reconciliation_pg.py` (5 tests) | Live (verification only) |
| **Interpretation vs. correction** | A slow LLM interpretation cannot overwrite a newer correction — `source_sequence` tracked end to end | `test_interpretation_vs_correction_pg.py` | Live |
| **Worker/broker recovery** | Lease/retry/backoff/dead-letter in `coordinator.py` survives a dropped dispatch | `test_worker_broker_recovery_pg.py` | Live |
| **Midnight / DST correctness** | Fact timestamps compared through real UTC-disambiguated values, not naive fold comparison | `test_dst_midnight_correctness.py` (9 tests) | Live |
| **Long-conversation history recovery** | No new mechanism built — `memory_search` (embedding similarity over `episode`) already recovers an old, paraphrased statement, and does so entirely independent of client-side history | `test_long_conversation_history_recovery_pg.py` (2 tests) | Live (verification only) |
| **Two-user isolation** | Query, cache, and session state isolation exercised through the real endpoint and background paths with two real users | `test_two_user_isolation_pg.py` | Live |
| **Ephemeral chat guarantees** | Extraction, lesson-tracking, emotional-state update, and enrichment are all skipped for `ephemeral=true` turns; conversation itself is never persisted | `test_ephemeral_no_world_state_writes.py`, `test_ephemeral_extraction_guards.py` | Live |
| **Memory contract honesty** | "I remember everything in this thread" replaced with an accurate description of the trimmed-window limitation plus the actual recovery tool (`memory_search`) | `test_chat_system_prompt.py::TestMemoryContractIsHonest` | Live |
| **World Context page — backend** | `GET /api/world-context`: current situation, full brief, per-domain coverage/degraded flags, off the same maintained snapshot chat reads — no source reconciliation or model call triggered by loading it | `test_world_context_page_integration_pg.py` | Live, hit with a real auth token post-restart |
| **World Context page — web** | `frontend/src/pages/WorldContext.tsx`, tab under Memory. Polls every 30s; pauses via Page Visibility API when the tab is hidden and refetches immediately on return; preserves displayed data through a failed background poll (`error && !data` guard, not `error` alone); only re-renders when `revision` actually changes | none automated (React component) — **live-verified**, see Deployment | Live, verified via Playwright: 3 successful auto-fired `/api/world-context` calls over a 37s window with zero manual interaction |
| **World Context page — iOS** | `WorldContextScreen.tsx`, More → Knowledge. Refetches on screen focus (`useFocusEffect`) and app foreground (`AppState`), polls every 20s while visible, stops polling entirely when blurred or backgrounded and resumes on return, preserves displayed data through a failed background poll, only re-renders when `revision` changes. Manual pull-to-refresh remains as a convenience, not a requirement. | `tsc --noEmit` clean (see Deployment) | Code complete; **simulator/device behavior unverified** — see Remaining limitations |

Full new/modified backend test run together: **229 passed** as of the Turn 3
functional-gap pass, **166 passed** re-run after the voice-continuation and
clarification-prompt follow-up — 0 failures either time.

## Deployment

Three restarts performed, each at a verified zero-active/zero-reserved
Celery-task window (`celery_app.control.inspect().active()`/`.reserved()`):

1. Turn 2 — initial world-state producer wiring, chat assembly boundary,
   World Context route + page + iOS screen.
2. Turn 3 — voice parity, mid-turn refresh, quoted-commands fix, source
   outage verification, long-conversation recovery verification.
3. This follow-up — voice continuation-of-pending-action, ambiguous-intent
   clarification guidance (both prompts), iOS/web automatic freshness.

Each restart: `docker compose -f docker-compose.dev.yml restart backend
celery-worker celery-critical celery-david-priority celery-acs celery-beat`,
polled for container health, then verified the live process actually has
the new code via `inspect.signature`/`inspect.getsource` against the
freshly-restarted interpreter (not just a file-exists check) — confirmed
present each time: `chat_with_tools`'s `world_state_core`/`turn_message`
params, the mid-turn refresh block, the mid-turn discovery gate, the voice
continuation wiring, and the clarification guidance text in both
`get_system_prompt` and `build_chat_system_prompt`.

Live functional checks against the real authenticated route, not just
process introspection:
- `GET /api/world-context` — 200, real data, correct "last known… may have
  moved since" degradation phrasing observed live.
- Web World Context page — Playwright, real cookie auth, real dev-server
  hot reload (no rebuild needed): loaded, showed real data, and
  **auto-updated 3 times over a 37s window with zero manual interaction**
  (confirmed via captured network responses, all 200).
- Celery workers post-restart: `email_sync`, `automation_watcher` completed
  cleanly, no errors in a 90s log window.

No frontend/iOS rebuild step exists for this stack — the web frontend is a
Vite dev server (bind-mounted, hot-reloads); the iOS app requires a real
build (EAS dev client / Xcode) that this environment cannot run, hence the
device-testing limitation below.

## Known limitations

- **iOS simulator/device behavior is unverified.** This environment has no
  simulator or device. What *is* verified here: `tsc --noEmit` shows zero
  new type errors (diffed against the pre-Turn-1 baseline — one pre-existing
  error was actually resolved via an unrelated file deletion), the
  `WorldContextResponse` interface matches the live backend payload
  field-for-field, navigation wiring (route registration, screen import,
  More-tab entry) is statically present, and the focus/foreground/polling
  lifecycle logic mirrors an already-shipped, working pattern in this same
  app (`AssistantInboxScreen.tsx`'s `useFocusEffect` + `AppState` idiom).
  None of that is a substitute for running it. **Device smoke-test
  checklist** (5 min):
  1. Open More → Knowledge → World Context. Confirm it loads without error
     and shows a subtitle timestamp.
  2. Confirm "Current Situation" matches what chat currently says when
     asked "what's going on right now."
  3. Leave the screen open and idle for ~25s (more than one poll interval).
     Without touching pull-to-refresh, confirm the "As of …" timestamp
     advances on its own.
  4. Navigate away to another tab, then back. Confirm it refetches quietly
     (no loading spinner flash if data was already showing) rather than
     going blank.
  5. Background the app (home button) for 10+ seconds, then foreground it
     while still on this screen. Confirm it refetches immediately rather
     than waiting out the remainder of the poll interval, and confirm
     nothing errors.
  6. With the app backgrounded, wait 30+ seconds, then foreground and watch
     network activity (if inspectable) — confirm no requests fired while
     backgrounded.
  7. Turn off network briefly while the screen is open with data already
     showing; confirm the screen does NOT blank out or show a full error
     — it should just keep showing the last good data. Restore network,
     confirm it recovers on the next poll or a manual pull-to-refresh.
  8. Pull to refresh once, confirm it still works as a convenience (not
     required for correctness per the above, but should not be broken).

- **Voice has no separate "session" concept.** The continuation mechanism
  now uses `conversation_id` as voice's session key (matching how
  `_CHAT_INVOKED_MUTATING_TOOL_NAMES` already falls back to it), which is
  correct as long as the voice client sends the same `conversation_id`
  back across a back-and-forth. If a voice client ever starts minting a
  fresh `conversation_id` per turn, continuation would silently stop
  working — worth a note for whoever touches the voice client.

- **Test-suite conflict, pre-existing, not fixed.** `test_ground_truth_phase1.py`
  registers a global SQLAlchemy `before_flush` listener that assigns
  explicit low `sequence` values to any new object in any session. Run
  alongside any `*_pg.py` integration file in the same `pytest` invocation,
  it collides with the real `world_event.sequence` bigint sequence
  (`UniqueViolation` on `world_event_pkey`). Confirmed: each passes cleanly
  alone; confirmed the collision reproduces together. **Run as a separate
  invocation** — this is infra debt this work did not introduce and was not
  asked to fix.

## File inventory (uncommitted)

Everything below `git status --short` at the time of this record — the
living-world-context work plus adjacent uncommitted work already in the
tree before it started (celery_app.py, conversation.py, action_suggester.py
removal, daily_brief/*, lesson_tracker.py, meeting_research.py, the various
docs/plans additions unrelated to this plan). Living-world-context-specific
files:

```
Modified:
  backend/app/main_simple.py
  backend/app/prompts/chat_system_prompt.py
  backend/app/routes/health_metrics.py
  backend/app/routes/reminders.py
  backend/app/services/context_budget.py
  backend/app/services/world_brief.py
  backend/app/services/world_state/interpreter.py
  backend/app/services/world_state/reducer.py
  backend/app/tools/reminders.py
  backend/app/services/goal_manager.py
  backend/tests/test_chat_system_prompt.py
  backend/tests/test_chat_tool_loop.py
  frontend/src/pages/Memory.tsx
  ios-app/src/hooks/useSaraChat.ts
  ios-app/src/navigation/AppNavigator.tsx
  ios-app/src/screens/more/MoreScreen.tsx
  ios-app/src/services/api.ts
  ios-app/src/services/chat.ts

New:
  backend/app/routes/world_context.py
  backend/app/services/chat_assembly.py
  backend/app/services/dialogue_state.py
  backend/app/services/tool_mutation.py
  backend/app/services/world_state/chat_facts.py
  backend/tests/test_chat_assembly.py
  backend/tests/test_context_budget_final_boundary.py
  backend/tests/test_dialogue_state.py
  backend/tests/test_dst_midnight_correctness.py
  backend/tests/test_email_world_state_integration_pg.py
  backend/tests/test_ephemeral_extraction_guards.py
  backend/tests/test_ephemeral_no_world_state_writes.py
  backend/tests/test_food_world_state_integration_pg.py
  backend/tests/test_health_world_state_integration_pg.py
  backend/tests/test_interpretation_vs_correction_pg.py
  backend/tests/test_live_context_envelope.py
  backend/tests/test_location_world_state_integration_pg.py
  backend/tests/test_long_conversation_history_recovery_pg.py
  backend/tests/test_reminders_goals_world_state_integration_pg.py
  backend/tests/test_source_outage_reconciliation_pg.py
  backend/tests/test_tool_mutation.py
  backend/tests/test_two_user_isolation_pg.py
  backend/tests/test_worker_broker_recovery_pg.py
  backend/tests/test_workout_world_state_integration_pg.py
  backend/tests/test_world_context_page_integration_pg.py
  docs/plans/SARA_LIVING_WORLD_CONTEXT_AND_CHAT_REPAIR_PLAN_2026_09_17.md
  frontend/src/pages/WorldContext.tsx
  ios-app/src/screens/worldcontext/WorldContextScreen.tsx
```

Nothing here is committed. `docs/sara_self_model_autonomous.md` and
`docs/sara_self_model_capabilities.md` show as modified in `git status` but
were not touched by this work — pre-existing uncommitted changes in the
tree.

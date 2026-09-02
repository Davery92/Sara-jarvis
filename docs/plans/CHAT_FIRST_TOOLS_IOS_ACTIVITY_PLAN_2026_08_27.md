# Chat-First Tools and iOS Activity Plan (2026-08-27)

## Goal

Make the active chat model own ordinary tool-using requests—including web search,
page reading, email, notes, memory, calendar, fitness, and reasonable multi-step
work—while preserving the background agent for work that is explicitly
backgrounded, long-running, durable, or requires a sandbox/remote host.

On iOS, replace the opaque waiting state with truthful lifecycle updates such as
“Searching the web…” and “Putting it together…”, without exposing private model
reasoning.

## Current problems

1. The normal chat loop can use tools directly, but the system prompt and tool
   descriptions strongly prefer `create_research_plan` or
   `dispatch_and_monitor` for broad classes of requests.
2. URL-investigation phrases can bypass the chat model completely and dispatch a
   background job before the model gets to decide how to answer.
3. A regex-based multi-step detector can bypass the normal ten-round chat tool
   loop and run a separate internal agent. Its progress callback is discarded.
4. The backend emits duplicate `tool_executing`/`tool_completed` events and also
   emits useful lifecycle events that iOS ignores.
5. iOS stores only one active tool, clears it immediately on completion, hides it
   after any response text arrives, and contains stale tool-name mappings.
6. Voice chat uses a separate hard-coded “Thinking…” path and does not consume
   tool activity.

## Desired routing contract

### Inline chat by default

- Quick and medium web research, including several searches/pages.
- Internal lookups and actions using email, notes, memory, calendar, fitness,
  home, and other intent-loaded tools.
- Multi-step work that can complete within the existing chat tool loop.
- “Look into”, “explain”, “tell me about”, and URL questions unless David
  explicitly requests a background report or the job is clearly durable/large.

### Background only when it adds real capability

- David explicitly says to run it in the background or notify him later.
- Code, shell, installation, build, system-administration, sandbox, or remote-host
  work.
- Large reports or investigations expected to take several minutes or requiring
  durable execution across disconnects/restarts.
- Parallel autonomous work where keeping the interactive chat lane free matters.

## Implementation

### Phase 1 — routing policy

1. Remove automatic web-investigation dispatch from the early chat intercept
   chain. Keep the investigation service available to explicit background paths.
2. Remove the regex multi-step execution intercept so the normal chat tool loop
   owns conversational orchestration.
3. Rewrite the system prompt’s lookup/research/dispatch policy to be inline-first.
4. Narrow `create_research_plan` and `dispatch_and_monitor` descriptions to the
   durable/background cases above.
5. Keep intent-based tool loading; do not expose every registry tool on every
   turn.

### Phase 2 — structured activity stream

1. Add one canonical `assistant_activity` SSE event with:
   - `phase`: `thinking`, `tool_running`, `tool_complete`, `synthesizing`, or
     `responding`
   - `tool`: canonical tool name when applicable
   - `round`: tool-loop round when applicable
2. Emit `thinking` when the request enters the model, `tool_running` and
   `tool_complete` around each execution, `synthesizing` before the post-tool
   model call, and `responding` when visible text begins.
3. Remove the duplicate inner tool-status emissions while retaining the existing
   legacy events for compatibility during the transition.
4. Emit plan-step activity if the multi-step planner remains reachable outside
   normal chat.

### Phase 3 — iOS lifecycle UI

1. Parse `assistant_activity` in the streaming client.
2. Replace the single `ToolStatus` state with an assistant-activity state that
   survives partial response text.
3. Use current canonical tool names and deterministic friendly labels.
4. Render a compact activity row below the streaming response instead of choosing
   between response text and status.
5. Route voice turns through the same callbacks and state transitions.
6. Clear activity only when the stream completes/errors or a new turn starts.

## Verification

### Backend

- Routing tests prove URL investigation no longer intercepts ordinary chat.
- Prompt/tool-description tests lock the inline-first contract.
- Stream tests prove one activity transition per tool execution and no duplicate
  legacy tool events.
- Existing direct-tool and dispatch tests continue to pass.

### iOS

- TypeScript check passes.
- Text and voice send paths both register activity callbacks.
- Rendering keeps activity visible after partial text.
- Friendly labels cover web, pages, email, notes, memory, calendar, fitness,
  home, and explicit background dispatch.

### Device scenarios

1. Ask a current factual question: “Searching the web…” → answer in this thread.
2. Give Sara a URL and ask what it is: inline page/search activity, no background
   task.
3. Ask for an email lookup: “Searching your email…” → inline answer.
4. Ask for a durable code/system task: background dispatch remains available and
   says that it is handing work off.
5. Start a tool-using turn, navigate away, return, and confirm the same thread and
   completed response remain intact.

## Rollback

- Re-add `_try_web_investigation` to `INTERCEPT_HANDLERS` if direct URL handling
  regresses.
- Restore the previous research/dispatch prompt text if Qwen fails to hand off
  genuinely durable work.
- iOS can continue consuming legacy `tool_executing`/`tool_completed` events if
  `assistant_activity` needs to be disabled.

## Implementation status — completed 2026-08-27

The routing, activity-stream, and iOS lifecycle work above is implemented and
deployed. A live-chat incident after deployment exposed three additional edge
cases; those are now fixed as part of the same contract:

1. `web_search`, `open_page`, and their detail tools now use `SearchService`'s
   async Redis accessor. Cache reads/writes are best effort, so an unavailable
   cache cannot turn a successful provider search or page fetch into a failed
   tool call.
2. Background task creators are withheld at the final tool-schema boundary on
   ordinary turns. They are available only for explicit background requests or
   actionable code/system work. A tool that fails twice in one turn is removed
   from subsequent model rounds, preventing retry spirals.
3. Conversation titles strip the injected `<live_context>` block before using
   the first user message. The malformed title from the incident was repaired
   in the live database.

Verification completed:

- Python compilation passed for all changed backend modules.
- Focused backend regressions: 13 passed.
- Live routing assertions passed for ordinary web research and explicit system
  work.
- Live registered-tool chain passed: `web_search` → search details →
  `open_page` → page details.
- Backend restarted healthy with database, embedding, LLM, and Neo4j healthy.

# Sara Chat Harness and MTP Repair Plan

**Date:** 2026-09-16  
**Status:** Ready for implementation  
**Scope:** Presence-chat harness, context assembly, tool selection, conversational state, post-turn learning, and MTPLX MTP activation  
**Primary objective:** Restore conversational correctness and harness reliability, then enable MTP with verified AR parity  
**Non-goal:** Reducing local-model latency. Latency should remain observable, but it is not an acceptance criterion for this work.

## 1. Why this work is needed

The morning conversation on 2026-09-16 exposed failures across the chat harness and model-runtime integration:

- Sara repeated the same RingCentral timing in several replies after it stopped being relevant.
- Sara asked effectively the same shoulder question four times, including after David answered it.
- She interpreted a completed workout as though it were still between sets.
- She initially described `135x6` as one set and continued repeating workout details after David corrected the count to four sets.
- A Wednesday request received a daily-context section headed `Today (Tuesday, September 15)`.
- Casual messages received 15-21 tool schemas, including irrelevant mutating tools.
- Each turn carried 8,200-10,555 characters of live context despite a configured 4,500-character warning threshold.
- Lesson-outcome updates repeatedly failed because PostgreSQL does not support the current `UPDATE ... ORDER BY ... LIMIT` statement.
- Episode enrichment was started after every turn, repeatedly reprocessed the whole conversation, and timed out.
- The MTPLX server loaded the native-MTP model and turbo profile, but chat requests ran with `generation_mode=ar`, effective depth `0`, and no verify calls.

The model server itself remained healthy. All seven chat requests completed normally with no stream-parser failure, context overflow, or transport error. This plan therefore treats the incident as a harness-correctness problem plus an MTP integration/configuration problem, not as an API outage.

## 2. Relevant implementation areas

- `backend/app/main_simple.py`
  - Chat request assembly
  - Local-model sampling and reasoning controls
  - Tool loading
  - Context injection
  - Initial, follow-up, and forced-final model requests
  - Post-turn lesson and enrichment scheduling
- `backend/app/services/context_budget.py`
  - Engaged-context and section budgets
- `backend/app/services/context_snapshot.py`
  - Engaged-context rendering
  - Daily-layer injection
  - Stale-date rewriting
- `backend/app/services/daily_brief/brief_service.py`
  - Layer reads
- `backend/app/services/daily_brief/day_layer.py`
  - Day-layer date headers and rollover
- `backend/app/services/tool_retrieval.py`
  - Permanent core tools
  - Semantic retrieval and family expansion
- `backend/app/services/intent_classifier.py`
  - Conversational/general classification and inherited categories
- `backend/app/services/lesson_tracker.py`
  - Outcome updates and effectiveness tracking
- Existing tests under `backend/tests/`, especially:
  - `test_chat_tool_loop.py`
  - `test_context_amnesia.py`
  - `test_extended_signals.py`
  - `test_ground_truth_phase5.py`
  - `test_presence_tool_diet.py`
  - `test_render_engaged_context.py`
  - `test_tool_retrieval.py`

## 3. Implementation principles

1. Fix prompt correctness before judging model quality.
2. Current user statements and corrections outrank inferred state, stored summaries, prior assistant text, and stale records.
3. Ambient context must have one enforceable budget at the final wire boundary.
4. A conversational message should not become an agent task merely because tools exist.
5. Mutating tools require positive evidence of action intent.
6. Post-turn learning must be durable, idempotent, and outside the response-critical path.
7. MTP must be an acceleration of the same sampling distribution, not a quality mode.
8. An MTP-to-AR fallback must be visible and diagnosable.
9. Preserve unrelated user changes and split this work into independently reviewable commits.

## 4. Phase 1: Create a deterministic morning-chat replay

Create a regression fixture from the seven user turns and assistant replies recorded on 2026-09-16. Replace live services with deterministic fixtures for:

- User-local clock and timezone
- Calendar entries
- Workout session state and workout logs
- Daily brief layers
- World brief
- Memory recall
- Lessons
- Tool index results

The replay must retain the real conversational sequence:

1. `Good morning Sara`
2. Correction that the deploy notification was only a reminder and David was heading to the office for shoulder work
3. Workout complete; walking to a store for an energy drink
4. Choosing a zero-calorie Monster
5. Shoulder workout was good; excited for later hypertrophy work
6. Correction: four sets of `135x6`
7. Shoulder pain has gone away

### Replay assertions

The replay fails if Sara:

- Repeats the RingCentral timing after the first relevant mention.
- Repeats a shoulder-status question after David answers it.
- Describes the completed morning workout as an active between-set period.
- Reasserts superseded set-count information after the four-set correction.
- Receives or states a stale Tuesday-as-today heading on Wednesday.
- Receives irrelevant mutating tools for casual messages.
- Exceeds the final ambient-context budget.

Add a model-independent harness test that inspects the fully rendered payload. Keep any live-model replay as a separate opt-in integration test so the deterministic suite is stable.

### Request diagnostics

For every chat model request, record:

- Conversation and client-message IDs
- Model and endpoint
- Message count and roles
- Stable-system, history, live-context, and tool-schema sizes
- Each live-context source ID, age, priority, input size, and rendered size
- Dropped, clipped, deduplicated, and superseded context sources
- Tool names plus retrieval score and selection reason
- Sampling and reasoning controls
- Requested and effective generation mode/MTP depth when reported by the server

Never log secrets or full private content by default. Full prompt dumps must remain behind an explicit diagnostic flag and write only to a protected temporary location.

## 5. Phase 2: Build one final context envelope

### Current defect

`render_engaged_context()` enforces its own budget, but `main_simple.py` subsequently appends a world brief, corrections, recency, interoception, directives, life facts, scratchpad, inbox data, re-entry material, and other blocks. A separate 4,000-token tail cap applies later. `LIVE_CONTEXT_CHAR_BUDGET` only produces a warning; it does not enforce the intended 4,500-character ceiling.

### Required design

Introduce a single structured context-envelope type. Each contribution must include:

```text
source_id
category
content
priority
observed_at or generated_at
effective_date, when day-scoped
max_tokens
truncatable
non_evictable
supersession_key, when applicable
provenance
```

All ordinary ambient sources must enter this envelope before rendering. The final renderer must:

1. Reject or relabel stale day-scoped sources.
2. Resolve supersession keys.
3. Deduplicate identical and near-identical sources.
4. Allocate by priority and freshness.
5. Truncate only at safe boundaries.
6. Enforce the total budget immediately before the model-bound payload is created.
7. Emit structured accounting for kept, clipped, and dropped sources.

### Priority order

Recommended order:

1. Current user message and explicit corrections
2. Current clock/location and active activity state
3. Current conversation state needed to resolve references
4. Active workout or other domain state directly relevant to the message
5. Today's calendar and time-sensitive commitments
6. Relevant memory retrieval
7. World brief
8. Standing directives and durable life facts
9. Re-entry summary
10. Journal, lessons, patterns, and other optional material

Current-turn corrections must be non-evictable and must supersede conflicting assistant wording and lower-authority context.

### Budget target

- Enforce a default ambient live-context ceiling of approximately 4,500 characters, or an equivalent tokenizer-based limit selected from replay evidence.
- Do not count David's actual message as ambient context.
- Large notes, attachments, and documents explicitly requested by David may use a separate content budget. They must not increase the ordinary ambient budget.
- Keep the stable persona/system prefix separate and cacheable.

### Remove transitional behavior

After all append sites use the envelope, remove the split `ENGAGED_BLOCK_MAX_TOKENS` plus `_POST_ENGAGED_TAIL_MAX_TOKENS` arrangement and replace the final warning-only check with a hard invariant.

## 6. Phase 3: Enforce daily-state freshness

### Current defect

The file-backed day layer is only rolled over when a summary is appended. A first read on a new day can therefore return yesterday's file. `_restate_stale_today()` only recognizes limited formats such as `today (Sept 10)` and does not match `Today (Tuesday, September 15)`.

### Required changes

1. Add metadata to daily layers:
   - `effective_date`
   - `generated_at`
   - User timezone
2. Validate `effective_date` whenever a layer is read for chat.
3. On the first read after local midnight:
   - Archive/reset the prior day layer, or
   - Return it explicitly as historical context with an `As of ...` label.
4. Never pass an old layer to the model under a `Today` heading.
5. Expand stale-date handling to parse:
   - `Today (Tuesday, September 15)`
   - `Today (September 15)`
   - `today, September 15`
   - Existing abbreviated month forms
6. Prefer structured metadata over parsing headings. Keep text parsing only for backward compatibility with existing files.

### Tests

Cover:

- The minute before and after midnight in the configured user timezone
- Backend running in UTC while user timezone is Eastern
- Old file with no metadata
- Yesterday's layer still relevant but correctly labeled historical
- Current-day layer left unchanged

## 7. Phase 4: Add dialogue-state and anti-repetition safeguards

### Dialogue state

Build a compact deterministic capsule from recent turns containing:

- Latest user assertion
- Current activity state, such as workout active/completed or walking
- Questions Sara asked in the last two replies
- Whether a later user message answered each question
- Corrections and their supersession keys
- Facts introduced only by Sara and therefore not authoritative

Do not use another LLM call to construct this capsule. Use conversation roles, domain events, and conservative extraction rules.

### Correction precedence

When David says `It was 4 sets of 135x6`, create a conversation-scoped correction such as:

```text
supersession_key: workout.smith_machine_press.working_sets
value: 4 x 135 x 6
authority: user_explicit
```

The correction must override:

- Prior assistant wording
- Lower-authority summaries
- Incomplete workout telemetry

Persisting the correction into the workout domain should remain subject to that domain's normal validation rules. Conversational precedence must not depend on the database mutation succeeding.

### Output validator

Before committing the assistant response:

1. Compare sentences and trailing questions with the last two assistant responses.
2. Detect exact and near-duplicate questions.
3. Detect a question already answered by a later user message.
4. Detect resurfacing of a superseded numeric fact.
5. Detect obvious activity-state contradictions, such as `between sets` after a completed-session event.

On violation:

- Regenerate once with a compact machine-generated correction message, or
- Deterministically remove a duplicated trailing question when the remaining answer is complete.

Do not build an unbounded critic loop. One repair attempt is the maximum.

## 8. Phase 5: Implement a real tool diet

### Current defect

Fifteen tools are always present. Semantic retrieval then adds up to six tools and may expand into sibling families. This caused casual conversation to receive unrelated mutating tools and made tool definitions account for roughly half the prompt.

### Tool modes

Use three explicit modes:

1. **Conversation-only**
   - No tools.
   - Used for greetings, acknowledgements, personal reactions, and messages answerable from current conversation/context.
2. **Capability discovery**
   - Only `find_tools`.
   - Used when David explicitly asks whether Sara can perform an unknown capability.
3. **Action/lookup**
   - A small intent-specific tool set, normally one to six schemas.
   - Used only when a lookup or action is needed to answer the request.

### Mutation gate

Split the tool index into read-only and mutating tools. A mutating tool may be selected only when there is positive action evidence, such as:

- An imperative request
- An explicit `log`, `create`, `change`, `delete`, `send`, or `schedule` operation
- A UI action whose contract already authorizes the mutation
- A tool continuation from a prior confirmed action in the same conversation

Semantic proximity alone must never load a mutating tool.

### Reduce the core

Remove the 15-tool permanent core from ordinary chat. If a very small safety core remains, justify each member with replay evidence. Do not include notes, lists, email, files, or calendar tools merely because they are broadly useful.

### Required selection outcomes

| User message | Expected selection |
|---|---|
| `Good morning Sara` | No tools, except a narrowly justified notification acknowledgement path |
| `I'm going zero-cal Monster or something` | No tools |
| `Shoulder workout was good` | No tools, or active-workout read state only if required |
| `It was 4 sets of 135x6` | No tools, or a specific workout-correction tool if one exists and is authorized |
| `Add four sets of 135x6 to my workout log` | Specific workout write tool |
| `Can you pull the attachments from that email?` | Email search/read plus attachment retrieval only |

### Retrieval diagnostics

Log candidate score, corpus median, relative gap, mutation classification, selection reason, and rejection reason. Add replay fixtures for conversational, ambiguous, explicit read, explicit write, and multi-step requests.

## 9. Phase 6: Repair lesson tracking and enrichment

### Lesson tracker SQL

Replace the invalid `UPDATE ... ORDER BY ... LIMIT` in `lesson_tracker.py` with a PostgreSQL-safe pattern.

For one lesson/application:

```sql
WITH target AS (
    SELECT id
    FROM lesson_applications
    WHERE lesson_id = :lesson_id
      AND conversation_id = :conversation_id
      AND outcome = 'unknown'
    ORDER BY created_at DESC
    LIMIT 1
)
UPDATE lesson_applications AS la
SET outcome = :outcome,
    feedback_signal = :feedback_signal,
    context_snippet = :context_snippet
FROM target
WHERE la.id = target.id
RETURNING la.id;
```

Prefer a set-based window-function variant when updating several lesson IDs. Do not execute one known-invalid statement repeatedly inside a loop.

Requirements:

- Use a savepoint or isolated transaction for feedback updates.
- Update effectiveness only after the application row update succeeds.
- Make repeated processing idempotent.
- Emit one aggregated failure, not one error per lesson.
- Add PostgreSQL-backed integration coverage; SQLite-only tests will not catch this syntax class.

### Episode enrichment

Replace per-turn fire-and-forget whole-conversation enrichment with a durable incremental workflow:

1. Queue one job per conversation after an idle debounce.
2. Use a uniqueness key so a new completion coalesces with pending work.
3. Track `enriched_through_episode_id` or an equivalent watermark.
4. Process only new episodes plus the minimum preceding context needed for interpretation.
5. Validate the returned structure before writing any row.
6. Retry with bounded exponential backoff.
7. Record terminal failures durably for diagnostics.
8. Make writes idempotent.

User corrections and explicit facts must be persisted through deterministic paths and must not wait for enrichment.

## 10. Phase 7: Activate and verify MTP

### Current state

The MTPLX server reports:

- Native draft-head support
- Supported MTP depth range `1-3`
- Loaded depth `3`
- Exact speculative sampling capability

However, requests currently report:

- `generation_mode=ar`
- Requested/effective depth `0`
- No verify calls
- No drafted or accepted tokens

The server's OpenAPI schema supports top-level `generation_mode` and `depth` request fields.

### Harness controls

Add configuration with explicit defaults for the chat lane:

```text
LOCAL_GENERATION_MODE=mtp
LOCAL_MTP_DEPTH=3
```

For every local-model request path, send top-level fields:

```json
{
  "generation_mode": "mtp",
  "depth": 3
}
```

Apply this consistently to:

- Initial chat request
- Tool-follow-up requests
- Forced-final requests
- Retry requests
- Any other chat-lane path using the same local endpoint

Do not rely exclusively on the server default. Also configure the service on `dra` to default to MTP so non-harness clients receive the intended runtime mode.

### Capability negotiation

At backend startup or client initialization:

1. Query the model server's `/health` endpoint.
2. Confirm that the backend supports native draft heads.
3. Confirm the requested depth is within the advertised range.
4. Record requested and available generation modes in health diagnostics.
5. Mark the local lane degraded when MTP is configured but unavailable.

Fallback to AR only when:

- The server explicitly rejects MTP as unsupported, or
- A narrowly classified MTP runtime failure occurs.

Every fallback must emit a structured system event containing model, endpoint, requested mode/depth, failure category, and whether AR recovery succeeded. Never silently omit the MTP fields.

### MTP correctness validation

Because the server claims exact speculative sampling, validate parity rather than only throughput:

- Run matched AR and MTP requests with deterministic seeds.
- Cover plain chat, tool selection, tool-call arguments, tool-follow-up responses, long history, and stop conditions.
- Require identical output for deterministic configurations where the server guarantees exactness.
- For nondeterministic configurations, require statistically equivalent behavior and identical contract compliance.
- Confirm no raw tool markup leaks into content.
- Confirm finish reasons, usage accounting, and streaming assembly remain correct.

Runtime acceptance evidence must show:

- `request_generation_mode=mtp`
- Effective MTP depth `3`
- Nonzero `mtp_depth`
- Nonzero verify calls
- Drafted and accepted token counters increasing
- No silent AR fallback

### Reasoning controls are separate

Do not conflate MTP with thinking mode. Normalize local reasoning controls to one supported request shape, preferably the server's top-level `enable_thinking` and `reasoning_effort` fields.

Recommended policy, subject to replay evaluation:

- Thinking off for greetings, acknowledgements, and simple conversation.
- Low effort for corrections, ambiguous state, and health/fitness interpretation.
- Medium effort for planning or genuinely complex requests.

Apply the correct sampler for the selected reasoning mode. Do not mix instruct-mode penalties with thinking-mode defaults.

## 11. Test plan

### Unit tests

- Context source priority, clipping, deduplication, and supersession
- Hard final context limit
- Daily-layer metadata and stale heading conversion
- Dialogue-state answered-question detection
- Exact and near-duplicate response detection
- Mutating-tool action gate
- Conversation-only zero-tool selection
- MTP payload fields on every local request path
- Explicit MTP fallback classification
- Lesson update SQL generation and idempotency
- Enrichment watermark and coalescing behavior

### Integration tests

- Full morning-chat harness replay with deterministic service fixtures
- PostgreSQL lesson tracking
- Redis/cache interaction for context snapshots and daily rollover
- Model-server AR/MTP parity, including tool calls
- Stream assembly for MTP responses
- Incremental enrichment retry and recovery

### Regression tests

Run existing context, tool-retrieval, tool-loop, daily-brief, lesson, workout, and conversation-storage suites. Add the morning replay to the required backend test target.

## 12. Delivery sequence

Implement as separate, reviewable changesets:

1. **Replay fixture and request diagnostics**
2. **Unified context envelope and final hard budget**
3. **Daily-layer freshness and rollover**
4. **Dialogue-state correction precedence and repetition guard**
5. **Tool diet and mutation gate**
6. **Lesson SQL and incremental enrichment**
7. **MTP request controls, server default, and parity tests**
8. **Canary rollout and cleanup of transitional code**

Do not combine the harness behavior changes and MTP activation into one deployment. First establish the corrected AR baseline, then enable MTP against the same replay and contract suite. This makes regressions attributable.

## 13. Rollout and rollback

Add independently controllable flags or settings for:

- Unified context envelope
- Conversation-only tool mode
- Output repetition repair
- Incremental enrichment
- MTP generation mode
- Dynamic reasoning policy

Recommended rollout:

1. Run deterministic replay and existing test suite.
2. Deploy context/date/tool/learning changes with generation still forced to AR.
3. Verify organic chat quality and diagnostics.
4. Enable MTP for test traffic or a narrowly scoped canary.
5. Confirm parity and runtime counters.
6. Enable MTP for the main chat lane.
7. Remove obsolete append-path budgets and silent fallback behavior after the canary period.

Rollback must be possible per feature. Disabling MTP may temporarily restore AR, but it must produce a visible degraded-state event.

## 14. Definition of done

This project is complete only when all of the following are true:

- The 2026-09-16 morning replay passes.
- Sara does not repeat the RingCentral timing after it is no longer relevant.
- Sara does not ask about the shoulder after David says it is all good and the pain is gone.
- A completed workout is not described as an active between-set period.
- Explicit user corrections supersede prior assistant claims immediately.
- Wednesday prompts cannot contain a Tuesday `Today` heading.
- Ambient context is always within the enforced final budget.
- Casual conversation receives no irrelevant mutating tools.
- Tool selection logs explain why every schema was included.
- Lesson tracking produces no PostgreSQL errors and updates the intended rows once.
- Enrichment is incremental, coalesced, idempotent, and recoverable.
- All local chat request paths explicitly request MTP depth 3.
- Server metrics show effective MTP operation and nonzero verification activity.
- AR and MTP pass the same conversational and tool-use contract suite.
- Any MTP fallback is visible in diagnostics and system events.
- Existing backend regression suites pass.

## 15. Explicit exclusions

- Do not optimize or gate completion on first-token or total-response latency.
- Do not change the selected model solely to make the tests pass.
- Do not weaken privacy by permanently logging full prompts.
- Do not grant mutating tools broader access to compensate for retrieval misses.
- Do not use a second unconstrained LLM agent as the primary repetition detector.
- Do not silently treat failed enrichment as successful learning.


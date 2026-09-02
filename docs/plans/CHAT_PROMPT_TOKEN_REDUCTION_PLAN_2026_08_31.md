# Sara Chat Prompt Token Reduction Plan

**Date:** 2026-08-31  
**Status:** proposed; repository- and production-log-audited; no implementation begun by this document  
**Scope:** reduce ordinary Sara chat prompts by fixing tool selection, splitting the fitness tool surface, and removing duplicate context during the world-model cutover.  
**Explicitly deferred:** conversation-history compaction and shortening Sara's stable system prompt.

## 1. Outcome

Sara should retain the capabilities and awareness that make her useful while paying only for tools and context relevant to the current turn.

Targets after rollout:

- Ordinary conversational turns: **10,000-15,000 input tokens**.
- Typical nutrition, workout, recovery, email, notes, or web turns: **15,000-20,000 input tokens**.
- Specialized fitness program-editing turns may exceed 20,000 tokens, but only when David is actually managing a program or phase.
- No ordinary chat turn should exceed **24,000 input tokens** solely because tool categories accumulated earlier in the conversation.
- Preserve tool success rate, conversational continuity, next-turn awareness, and Sara's voice.
- Improve time to first token without depending on a larger context window to hide prompt growth.

The new `qwen3.8-27b` model has a 131,072-token configured context window and thinking is disabled on the chat lane. That makes the current prompts valid, but not efficient. A larger context window is capacity, not a reason to send irrelevant schemas or duplicate state.

## 2. Verified production baseline

Backend logs from 2026-08-31 show one conversation growing as follows:

| Time (UTC) | Turn shape | Tools | Reported prompt tokens |
|---|---:|---:|---:|
| 13:54 | New conversational turn | 32 | 19,091 |
| 13:55 | Fitness introduced | 70 | 26,846 |
| 14:49 | Memory/knowledge graph accumulated | 74 | 28,563 |
| 15:09 | General/home/web accumulated | 91 | 32,533 |
| 15:27 | Email accumulated | 95 | 34,377 |

The 15:27 request was approximately:

| Component | Approximate tokens | Share |
|---|---:|---:|
| 95 serialized tool definitions | 16,928 | 49% |
| Stable system prompt + live context | 10,417 | 30% |
| Conversation messages beyond that base | 3,540 | 10% |
| Provider chat-template/serialization overhead | 3,492 | 10% |

The backend's preflight `bytes / 4` estimate was 30,935 tokens while the model reported 34,377 prompt tokens. Acceptance criteria must therefore use the provider-reported/tokenizer count, not the byte estimate.

Observed time to first token was approximately 38 seconds on the 19k-token new-conversation turn and 78-86 seconds on several 32k-34k-token turns. Queue and cache effects prevent treating this as a controlled benchmark, but the production evidence is strong enough to prioritize prompt reduction.

## 3. Root causes

### 3.1 The presence tool diet is being undermined by category-level base tools

`_PRESENCE_CORE_TOOL_NAMES` defines seven individually selected tools. That is the intended lean core.

However, `ToolIntentClassifier.BASE_TOOLS` still returns five entire categories on specific and conversational turns:

```python
['memory', 'notes', 'time', 'agents', 'fleet']
```

The chat assembly then adds every tool in every returned category after adding the seven-tool core. As a result, a conversational turn carries 32 tools instead of approximately seven, and a fitness turn carries roughly 70.

This is a contract mismatch: the classifier returns category names as though they were a small capability core, while the presence diet expands those names into complete schemas.

### 3.2 Sticky categories are append-only

For prompt-cache stability, `_CHAT_STICKY_TOOL_CATEGORIES` preserves categories in first-seen order and accumulates up to ten categories per conversation. The strategy improves the chance that the model server can reuse a prefix, but it also guarantees that unrelated schemas remain present after the topic changes.

In the observed conversation, the sticky set grew through:

```text
agents, fleet, memory, notes, time, fitness, knowledge_graph, home, web, email
```

The cache strategy is optimizing reuse of an oversized prefix. Token size, model attention, and uncached evaluation still suffer, and any appended category invalidates the prior exact prefix at least once.

### 3.3 Fitness is one 38-tool category

The registry treats nutrition, ordinary workout logging, active-workout control, recovery, notes, templates, programs, phases, scheduling, and recommendations as one category. Most fitness turns need only a small subset.

Examples:

- “Log this shake” does not need program, phase, template, recovery, or workout-mode schemas.
- “How was my sleep and recovery?” does not need food logging or program mutation schemas.
- “Start my workout” does not need nutrition or phase-management schemas.
- “Move my deload week” legitimately needs program/phase tools but not food logging.

### 3.4 Two broad context systems are injected together

When both `SINGULAR_CONTEXT` and `WORLD_CONTEXT_READ` are enabled, chat currently injects:

1. The kernel engaged context, including reconstructed world/self/relationship state, recall, Daily Brief, PKG facts, journal, patterns, device state, emotional tone, lessons, and workspace state.
2. The continuously maintained world context, including snapshot slices, recent changes, active threads, and relevant facts.

Today's turns carried roughly 9,000-10,000 characters of kernel context plus the world renderer's full 14,000-character ceiling. Several concepts overlap: current world state, recent events, facts about David, active work/threads, and relationship/conversation state.

The current world renderer is not yet a full replacement for the kernel renderer. It does not presently carry all query-specific recall, lessons, Daily Brief material, Sara's self-story, theory of David, device details, or workspace context. Therefore, immediately disabling `SINGULAR_CONTEXT` would save tokens but risk a real awareness regression.

### 3.5 Initial conversation history is not bounded server-side

iOS and web send the full visible conversation. The backend's 20-message truncation runs only after a tool call, not before the initial model request.

This is a real issue, but it is **out of scope for this plan by decision**. The observed 34k incident was predominantly tool/context growth, so the first implementation can produce substantial gains without changing history behavior.

## 4. Decisions

### 4.1 Replace category-level base tools with an exact named core

The chat lane will have one authoritative named core. The classifier will return only turn-specific capability groups; it will no longer implicitly add the five broad `BASE_TOOLS` categories to every specific intent.

Initial named core remains:

- `memory_search`
- `notes_create`
- `notes_search`
- `list_add`
- `list_view`
- `reminders_create`
- `calendar_list`

Before implementation, validate this list against real chat requests. In particular, decide whether `notes_create`, `list_add`, and `reminders_create` should be always present or admitted only by explicit action intent. The default should favor capability correctness, with further reductions backed by replay evidence.

### 4.2 Replace unbounded stickiness with bounded continuity

Do not keep an append-only category union for the lifetime of a conversation.

Use:

1. The exact named core.
2. The current turn's specific subcategory or subcategories.
3. At most one immediately previous domain subcategory for short follow-ups such as “do that” or “what about yesterday?”.
4. Any tool required by explicit UI context, such as an inbox item, active workout, or note being discussed.

Apply both limits:

- Maximum **three non-core subcategories** on an ordinary turn.
- Maximum **6,000 estimated schema tokens** for all tools on an ordinary turn.

If classification exceeds the budget, retain explicitly requested action tools first, then retrieval tools for the primary domain, then prior-turn continuity. Log every dropped category and the reason.

Prompt caching still matters, but stable ordering is sufficient:

- named core in fixed order;
- current primary subcategory in fixed registry order;
- optional secondary/current multi-intent subcategory;
- optional previous-turn continuity subcategory last.

This preserves reusable prefixes without preserving every prior topic.

### 4.3 Split fitness by user job, not by implementation module

Replace the monolithic `fitness` category with these registry categories:

#### `fitness_overview`

For broad questions about recent fitness or “how am I doing?”

- `fitness_summary`
- `workout_stats`
- `food_log_summary`
- `recovery_log_recent`

#### `fitness_nutrition`

For food lookup/logging, macros, meals, and nutrition guidance.

- `food_search_and_log`
- `food_log_create`
- `food_log_search`
- `food_log_summary`
- `nutrition_guide_update`

`nutrition_guide_update` must remain action-gated and load only for guide/target changes, not ordinary food questions, if its schema size or mutation risk warrants a narrower `fitness_nutrition_manage` category.

#### `fitness_workout`

For workout lookup, ordinary set logging, performance, and suggestions.

- `workout_list`
- `workout_log_create`
- `workout_details`
- `workout_stats`
- `workout_suggest`

#### `fitness_workout_live`

For an active training session.

- `start_workout`
- `end_workout`
- `workout_mode_log`
- `workout_history`
- the read tools from `fitness_workout` needed to ground live coaching

This category may be deterministically enabled from active-workout state rather than inferred from wording on every turn.

#### `fitness_recovery`

For HRV, sleep, soreness, weight, and recovery entries.

- `recovery_log_create`
- `recovery_log_get`
- `recovery_log_recent`

#### `fitness_programming`

For templates, programs, phases, blocks, and training schedule changes.

- template list/get/create/update/delete
- program list/get/create/update/activate/delete
- phase list/get/create/update/activate/delete
- `phase_insert_block`
- `phase_end_block`
- `training_schedule`

This is intentionally the largest fitness surface, but it loads only for explicit program-design or phase-management work.

#### `fitness_notes`

For fitness-specific notes only.

- `fitness_note_create`
- `fitness_note_search`
- `fitness_note_edit`

Overlapping read tools are allowed across categories. Categories are prompt-selection views, not ownership boundaries.

### 4.4 Make world context authoritative through a subtractive cutover

Number 3 from the investigation is accepted as the architectural direction with a staged constraint: **do not turn off the entire kernel context until the world bundle has parity for the information chat still needs.**

When `WORLD_CONTEXT_READ` is enabled:

- World context becomes authoritative for current world slices, recent changes, facts, and active threads.
- The kernel path stops rendering those overlapping portions.
- A temporary `render_engaged_supplement()` retains only non-overlapping, query-relevant material:
  - episodic/document memory recall;
  - relevant lessons and their IDs;
  - Sara's self-story and emotional state;
  - theory of David/relationship material not yet projected into V2;
  - workspace context;
  - Daily Brief, journal, device, patterns, and PKG only when relevant and not already represented in the world bundle.

The supplement is a migration bridge, not a second permanent context system. Each retained field must have a named destination in `ContextBundleV2` or a documented decision that it is intentionally query-time retrieval.

Do not merely concatenate two reduced strings. Build one final context document with section-level provenance and deduplication.

### 4.5 Defer history and stable-prompt changes

This plan makes no behavioral changes to:

- how much conversation history iOS/web sends;
- initial server-side history truncation or summarization;
- Sara's stable personality/system prompt.

Continue measuring their token contribution so a later plan can evaluate them with post-tool/context baselines. Do not silently introduce history truncation as part of a token-budget helper in this work.

## 5. Implementation phases

## Phase 0 — Measurement and replay fixture

### 0.1 Add component-level prompt accounting

For every chat request, record estimated and provider-reported totals for:

- stable system prompt;
- world context;
- engaged supplement;
- other live context blocks;
- conversation messages;
- tool schemas by category and tool count;
- provider/template overhead as the residual when actual usage arrives;
- cache-hit metrics when exposed by the local server.

Do not log raw private content. Log counts, category names, hashes, and sizes.

### 0.2 Capture representative replay cases

Create sanitized fixtures from at least these request shapes:

- ordinary conversational turn;
- memory or note lookup;
- food logging;
- nutrition summary;
- workout logging;
- active-workout command;
- recovery question/log;
- fitness program/phase edit;
- email lookup;
- home/web multi-intent request;
- short follow-up after a domain turn;
- topic switch inside a long conversation.

For each fixture, store expected required tool names, forbidden/unnecessary tool groups, context facts that must survive, and a maximum schema-token budget.

### 0.3 Establish pre-change baseline

Replay the fixtures against current assembly and record:

- selected tool names/categories;
- serialized tool tokens;
- total input tokens;
- first-tool correctness;
- tool retries/failures;
- answer quality checks;
- time to first token in a controlled, idle-server run.

**Exit criteria:** reproducible evidence demonstrates the same growth pattern seen in production and makes regressions detectable.

## Phase 1 — Fix the tool-selection contract

### 1.1 Separate core tool names from classified categories

Refactor `ToolIntentClassifier` so its output contract is explicit, for example:

```python
ToolSelection(
    primary_intent="FITNESS_NUTRITION",
    categories=["fitness_nutrition"],
    continuity_categories=[],
    reason="explicit food logging request",
)
```

The classifier must not add `BASE_TOOLS` category names. The chat assembler owns the exact named core once.

### 1.2 Replace sticky accumulation

Replace `_CHAT_STICKY_TOOL_CATEGORIES` with bounded per-conversation continuity state containing:

- previous primary intent/category;
- timestamp;
- whether the preceding assistant turn actually invoked a tool from it;
- any deterministic active mode, such as active workout or inbox review.

Expire ordinary continuity after three turns or 30 minutes, whichever comes first. Explicit active modes use their own lifecycle.

### 1.3 Add schema-budget enforcement

Calculate schema tokens with the target model tokenizer when available; use a conservative fallback otherwise. Select tools before the model call and reject assembly that exceeds the configured ordinary-turn budget unless an allowlisted specialized mode explains the excess.

The budget mechanism must drop whole optional groups safely, never individual tools that break a required action sequence without an explicit dependency rule.

### 1.4 Tests

- Conversational intent loads the named core, not five complete categories.
- Specific intent adds only its explicit category plus core.
- A short follow-up inherits at most the immediately preceding domain.
- A topic switch drops the previous domain unless wording requires it.
- General/multi-intent requests stay within category and schema budgets.
- Tool order is deterministic across identical selections.
- Existing background-dispatch admission policy remains intact.

**Phase 1 exit criteria:** ordinary conversational replay uses no more than 12 tools and tool schemas remain below 4,000 estimated tokens unless the fixture explicitly requires more.

## Phase 2 — Split and route fitness

### 2.1 Update registry categories

Add the seven fitness selection views from section 4.3. Keep a temporary `fitness` compatibility alias only for audited non-chat callers. Chat selection must not use the alias.

Audit registry completeness while doing this. `PhaseInsertBlockTool`, `PhaseEndBlockTool`, and `NutritionGuideUpdateTool` are instantiated but are not present in the current monolithic `TOOL_CATEGORIES['fitness']` list; the split must intentionally place them rather than perpetuate that drift.

### 2.2 Add fitness sub-intent routing

Introduce deterministic patterns and multi-intent behavior for:

- food/nutrition/macros/meal;
- workout history/log/set/exercise/suggestion;
- active workout/start/end/current set;
- recovery/sleep/HRV/soreness/weight;
- template/program/phase/block/schedule/deload/bulk/cut;
- fitness note.

Ambiguous “fitness” questions load `fitness_overview`, not every fitness tool. If a request genuinely spans nutrition and workout, load both small groups within the global schema budget.

### 2.3 Make UI context narrower

The current Fitness screen mapping adds the entire fitness category. Change screen-aware context to add `fitness_overview` only. Where the client knows the active fitness subview or active workout state, pass a narrow mode hint rather than forcing all fitness tools.

Server-side intent remains authoritative; a UI hint may add a justified group but must not broaden to the compatibility alias.

### 2.4 Preserve action safety

- Retrieval and mutation tools remain distinguishable in selection logs.
- Program/phase mutation tools load only for explicit management intent.
- Nutrition/workout logging tools still require David's explicit request under the existing system policy.
- Active workout state may expose live controls, but it does not authorize an action by itself.

### 2.5 Tests

- “Log a protein shake” exposes nutrition logging and no program tools.
- “What did I eat yesterday?” exposes nutrition reads and no mutation-only program tools.
- “How was my recovery?” exposes recovery tools and overview only if useful.
- “Start today's workout” exposes live workout tools and necessary workout reads.
- “Change week four to a deload” exposes programming tools and no food tools.
- “How am I doing overall?” exposes overview, not all seven groups.
- Fitness screen presence alone does not load programming/live/nutrition mutation surfaces.
- Every instantiated fitness tool belongs to at least one intentional selection view or is explicitly marked non-chat.

**Phase 2 exit criteria:** typical nutrition, workout, and recovery requests carry fewer than 15 fitness-related schemas; only explicit programming work may load the larger programming group.

## Phase 3 — Consolidate world and kernel context

### 3.1 Produce a semantic overlap report

For real turns in shadow mode, classify rendered fields into:

- duplicate with equivalent freshness/provenance;
- duplicate but conflicting/staler;
- world-only;
- kernel-only and necessary;
- kernel-only but irrelevant to the current query;
- missing from both.

Do not compare strings only. Normalize concepts such as calendar state, active threads/intents, recent changes, facts, current conversation, health, fleet, and work state.

### 3.2 Build one token-budgeted context document

Refactor `format_context_for_prompt()` so it does not serialize a broad JSON object and cut it at an arbitrary 14,000 characters. Render complete, prioritized sections under a token budget:

1. correctness-critical current state relevant to the request;
2. active/recent thread directly related to the request;
3. recent changes since last engagement;
4. relevant sourced facts;
5. bounded general ambient state.

Never end with truncated/malformed JSON. Report omitted section counts in diagnostics, not in Sara's visible prompt.

Initial combined budget:

- World context: **3,500 tokens maximum**.
- Engaged supplement: **2,000 tokens maximum**.
- Other per-turn live blocks: **1,000 tokens maximum**, excluding explicitly attached note/inbox content.

These are starting guardrails to validate in replay, not permission to fill every budget on every turn.

### 3.3 Add the non-overlapping supplement renderer

Create a dedicated renderer rather than reusing `render_engaged_context()` and trying to remove text afterward. It accepts the world bundle's included concept keys and suppresses duplicates by construction.

Each supplement provider gets:

- relevance/admission rule;
- token ceiling;
- freshness metadata;
- destination (`ContextBundleV2`, permanent query-time retrieval, or retire);
- failure behavior.

Keep lesson IDs available to the post-response effectiveness path even if their prose is not admitted on an irrelevant turn.

### 3.4 Shadow and cut over

Use independent states:

1. Current dual-render baseline, measured only.
2. World + supplement shadow assembly, not sent to the answering model.
3. Replay evaluation against recent real questions.
4. Canary world + supplement for chat.
5. Full chat cutover behind `WORLD_CONTEXT_READ`.
6. Remove overlapping sections from the legacy renderer after the rollback window.

Rollback turns the reader back to the current kernel assembly without deleting world events or projections.

### 3.5 Context parity tests

- Just-logged food/workout facts appear on the next relevant turn.
- Calendar/current-day state remains fresh.
- Active threads and recent changes appear once, not in both renderers.
- Relevant episodic memory and lessons survive the cutover.
- Sara's self-story, emotional state, and relationship understanding survive where appropriate.
- Daily Brief/journal/PKG material is admitted only when relevant or proven generally valuable.
- Workspace context survives workspace turns.
- Missing/stale world slices do not produce confident present-tense claims.
- The final combined context stays within budget without broken JSON or mid-section truncation.

**Phase 3 exit criteria:** world + supplement matches or exceeds current answer/context correctness on replay, contains no known duplicate semantic sections, and saves at least 3,000 input tokens at p50 versus the dual-injection baseline.

## Phase 4 — Integrated rollout

### 4.1 Feature flags

Use separately reversible controls:

- `CHAT_TOOL_SELECTION_V2`
- `CHAT_FITNESS_TOOL_SPLIT`
- existing `WORLD_CONTEXT_READ`, with shadow/canary configuration for the new supplement assembly
- configurable tool-schema and context-token budgets

Do not combine all changes under one master switch; rollback must identify whether a regression came from tool availability or context content.

### 4.2 Rollout order

1. Ship measurement only.
2. Enable tool-selection V2 in replay and shadow logging.
3. Canary tool-selection V2 for ordinary chat.
4. Enable the fitness split in replay, then canary.
5. Run world + supplement shadow comparison.
6. Canary the context cutover only after parity gates pass.
7. Expand to all chat traffic while retaining per-feature rollback.

### 4.3 Production gates

Compare before/after for at least 50 representative turns, including at least 15 fitness turns:

- p50/p90 provider-reported prompt tokens;
- p50/p90 time to first token;
- tool count and schema tokens by intent;
- first-tool selection accuracy;
- missing-tool failures or “I can't do that” responses when a valid tool exists;
- redundant/repeated tool calls;
- context-grounding errors;
- action-policy violations;
- response quality/user corrections;
- local prompt-cache hit/evaluated-token behavior if available.

Required gates:

- At least **35% lower p50 prompt tokens** across ordinary chat.
- At least **40% lower p50 tool-schema tokens**.
- No statistically meaningful rise in missing-tool failures.
- No loss of next-turn awareness in the replay suite.
- Fitness logging and active-workout success remain at baseline or improve.
- Context cutover meets its separate 3,000-token p50 saving and parity criteria.

## 6. Files expected to change during implementation

Primary backend files:

- `backend/app/services/intent_classifier.py`
- `backend/app/tools/registry.py`
- `backend/app/main_simple.py`
- `backend/app/services/context_snapshot.py`
- `backend/app/services/world_state/context.py`
- `backend/app/core/feature_flags.py`

Likely tests:

- intent/tool-selection tests under `backend/tests/`
- fitness tool-contract/category coverage tests
- context parity and token-budget tests
- chat payload assembly regression tests

Possible client files for narrow, additive UI hints only:

- `ios-app/src/screens/chat/ChatScreen.tsx`
- `ios-app/src/screens/fitness/FitnessScreen.tsx`
- `frontend/src/components/ChatInterface.tsx`
- `frontend/src/components/fitness/FitnessSection.tsx`

No client change is required to begin Phases 0-2; server-side routing remains authoritative.

## 7. Non-goals and guardrails

- Do not change the selected chat model as a substitute for prompt reduction.
- Do not rely on the 131k context window as the budget.
- Do not remove tool capability merely to improve token metrics; route it progressively.
- Do not merge retrieval and action authorization. A visible schema is capability, not permission.
- Do not truncate initial conversation history in this plan.
- Do not summarize or compact conversation history in this plan.
- Do not shorten `sara_voice.md` or the stable system prompt in this plan.
- Do not disable the full kernel context until world + supplement parity passes.
- Do not leave the supplement as an undocumented permanent second world model.
- Do not use raw character slicing that can corrupt structured context.

## 8. Definition of done

This plan is complete when:

1. Component-level token accounting is available for real chat turns.
2. The exact named core is the only unconditional chat tool set.
3. Append-only sticky category accumulation is removed from chat.
4. Fitness is split into narrow, tested user-job categories.
5. Ordinary fitness turns no longer load program/phase tools unless requested.
6. World context is authoritative for overlapping current-state concepts.
7. The temporary engaged supplement contains only proven non-overlapping signals under a token budget.
8. Production gates show the target prompt reductions without tool or awareness regressions.
9. Every phase has an independent rollback path.
10. History compaction and stable-prompt shortening remain unchanged and are documented as deferred follow-up work.


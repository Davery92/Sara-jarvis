# Sara living world context and chat repair plan

Date: 2026-09-17  
Status: Ready for implementation; no application changes made for this plan  
Owner: Implementing agent  
Scope: Automatically maintained world context, read-only visibility, chat assembly, prompting, conversation state, tool execution, response persistence, and client reconciliation

## 1. Product outcome

Sara should already have an accurate, current picture of David's world when a conversation starts. An incoming email, location observation, workout, food entry, calendar change, or other meaningful app change should update that picture automatically, even when no client is open and no chat is happening.

David should never need to edit or maintain the context. A read-only World Context page should show what Sara currently understands, where it came from, and how current it is. Normal conversational corrections should update her understanding without requiring page edits.

The context must distinguish current state, recent developments, historical facts, unresolved commitments, and uncertainty. An old location observation becomes “last known,” while a completed workout remains a historical fact. Neither a periodic review nor a new render timestamp may make old evidence appear newly observed.

The chat harness must reliably deliver that picture, give current user statements precedence over stale summaries, use tools appropriately, and preserve the same final answer across display, history, and downstream memory.

## 2. Scope and implementation constraints

- Build on the existing world-event, fact, snapshot, and brief infrastructure. Do not create another independently maintained context note alongside the existing systems.
- Maintain a structured source of truth and generate the readable document from it. Summaries are derived views, not independent evidence.
- Preserve existing uncommitted and untracked work. Several files named below already contain unfinished repairs; inspect their diffs before editing and extend useful work in place.
- This plan takes precedence over conflicting context, dialogue, and tool behavior in `SARA_CHAT_HARNESS_MTP_REPAIR_PLAN_2026_09_16.md`. That plan remains background for lesson/enrichment work and the separate MTP workstream.
- Do not expand this project into model-server changes, MTP activation, a general monolith rewrite, or unrelated feature cleanup. Preserve current generation controls and verify they survive refactoring.
- Implement and verify sequentially. David explicitly requested no agents or parallel processing in this discussion; do not delegate this work unless he changes that instruction.
- Automatic context maintenance does not imply permission to send emails, delete records, or perform other domain actions. Updating Sara's understanding and mutating a source application are separate operations.
- Keep existing ephemeral-chat and user-isolation contracts. Audit context maintenance and post-turn extraction so ephemeral content does not leak into durable world facts, summaries, or enrichment.

## 3. Evidence and known gaps

The review ran 66 isolated tests successfully across `test_context_budget_final_boundary.py`, `test_dialogue_state.py`, `test_tool_mutation.py`, `test_chat_system_prompt.py`, and `test_chat_history_reconciliation.py`. Passing these tests does not establish endpoint or live-model correctness. Additional pure-function reproductions exposed defects missing from those tests.

| Finding | Evidence in current code | Required result |
| --- | --- | --- |
| Fresh world context can disappear | `main_simple.py` appends the world brief after engaged context; `enforce_live_context_budget()` keeps the beginning of the combined text. A reproduction discarded the entire brief. | Allocate space by authority, relevance, and freshness; preserve a compact current-state core. |
| The supposed final budget is not final or universal | The hard character cap and dialogue capsule run only in the local-provider branch; `_chat_with_tools_inner()` subsequently appends a session reminder. | All providers and request rounds use common semantic assembly and final accounting, including later additions. |
| Old activity completion overrides new activity | `_detect_activity_signal()` scans backward for any completion phrase. “Finished morning workout” then “started evening workout, between sets” still produces an instruction saying the workout ended. | Session-scoped activity transitions; newer applicable evidence supersedes earlier state. |
| Reply repair happens after storage | `_chat_with_tools_inner()` stores the assistant episode before `process_chat()` removes a repeated trailing question. | One canonical finalized reply is persisted and sent. |
| iOS cannot accept shortened or replaced final text | Both final-response parser paths in `ios-app/src/services/api.ts` only append a suffix or fill empty output. | The final event replaces provisional streamed text, including shorter or empty final content. |
| Tool gating treats words as authorization | `has_action_intent()` returns true for “Don't delete anything,” “The email was interesting,” and “My workout is complete.” | Negation, reference, reported facts, and actual requested actions are distinguished. |
| Discovery bypasses tool limits and mutation policy | `_load_tools_midturn()` adds names without the mutation gate, marks discovery as sticky authorization, and calculates room as `cap + new_count - current_count`. A reproduction grew 35 schemas to 37. | Discovery is not authorization; enforce policy and cap at discovery, payload construction, and execution. |
| Tool execution is broader than the offered menu | `execute_tool()` checks global registry membership but does not itself enforce the current authorized tool set. | Unoffered or unauthorized calls produce a structured refusal without invoking the tool. |
| Prompt discourages freshness checks | The prompt says retrieve once, do not re-fetch, and “You remember everything in this thread”; fallback DB history is limited to 20 messages. | Freshness-aware retrieval and an honest description of available history. |
| Brief caching can preserve changing state | `get_rendered_brief()` returns a cached complete render for up to 120 seconds, despite its docstring saying current activity/body sections are live-computed on each use. | Revision- and time-aware caching with tested invalidation and honest observation times. |
| Existing replay is not production assembly | `backend/tests/replay/README.md` documents omitted endpoint sections and no voice/iOS replay. | Replays call the same assembly boundary as production and exercise client finalization. |

These are source-level findings and deterministic reproductions. Deployment state, real scheduler health, event coverage, and full live-model behavior remain to be measured; do not describe them as already verified.

## 4. Architecture and contracts

The intended flow is:

```text
Committed source change
  -> durable world event
  -> deterministic fact/state projection
  -> optional source-grounded interpretation
  -> versioned world snapshot and readable briefing
  -> World Context page / chat context assembler

Periodic source reconciliation and timed expiration
  -> the same projection and briefing pipeline

User turn + world snapshot + conversation state + relevant retrieval
  -> shared context allocation and tool policy
  -> provider adapter / bounded tool loop
  -> one finalized reply
  -> persistence + final stream event + downstream memory
```

### Evidence contract

Reuse existing fields in `WorldEvent`, `WorldFact`, `WorldSnapshot`, and associated schemas wherever possible. Add migrations only for missing semantics. Every projected fact needs:

- User, domain, entity or activity-session identity, fact key, and value.
- Source reference, source event/revision, evidence kind, and originating actor.
- `occurred_at`, `observed_at`, applicable validity interval, and source freshness deadline when appropriate.
- Projection/render times recorded separately from observation time.
- Status such as current, uncertain/last-known, historical, superseded, or retracted.
- Confidence and its basis; a model-generated confidence score alone is not verification.
- Supersession identity and links to replaced/retracted evidence.

Snapshots need a revision, event-processing watermark, build time, source coverage, and per-domain freshness. A highest processed event sequence alone is not proof of completeness when lower sequences remain pending or failed; expose gaps/backlog explicitly.

### Precedence contract

For claims about the same entity, session, and effective time: current explicit user correction wins over assistant wording, inferred routines, and conflicting summaries. Newer authoritative source evidence supersedes older source evidence according to source revision and event time. Late-arriving old events must not roll state backward.

Scope corrections to what they actually refer to. An observation about a morning workout must not permanently override a separately identified evening session. Persist conflicting evidence and its resolution rather than silently rewriting history. Conversational correction precedence must work even when updating the underlying domain record is not authorized or fails.

### Freshness contract

Freshness is per fact/domain, not one timestamp for the whole document. Initial configurable defaults:

| Domain | Maintenance and aging behavior |
| --- | --- |
| Location/presence | Update on observations; initially mark location last-known after 15 minutes without a new observation, subject to the actual feed cadence and accuracy. Never infer “home” from silence. |
| Workout | Explicit start/finish and session identity determine lifecycle. Missing telemetry may make an active session uncertain; inactivity alone does not prove completion. |
| Food and completed exercise | Preserve events as history; recompute edited/deleted totals. “Today” is user-local and rolls over at midnight. |
| Calendar/reminders | Apply creates, reschedules, cancellations, and completions immediately; track source-sync age separately from event time. |
| Email | Retain receipt time and source identity; update summaries on relevant thread changes. A sender's claim is attributed to the sender until corroborated. |
| Commitments/projects | Persist until completion, cancellation, supersession, or an explicit review rule; a daily cleanup cannot assume completion. |
| Health measurements | Preserve measurement time and provenance; no interpolation or invented missing values. |

Use deterministic expiry checks on reads to reflect the passage of time without source reconstruction. Run a lightweight expiration sweep approximately every minute, source reconciliation hourly, and compaction daily in the user's timezone. Preserve faster existing jobs where needed instead of slowing them to these defaults. Do not invoke a model merely to expire a timestamp.

## 5. Phase 0 — Baseline and test seams

1. Inspect the dirty worktree and record which earlier repairs are present, tested, and actually wired. Do not treat file names, comments, or plan status as proof.
2. Inventory all chat surfaces and routes: `/chat/stream`, work mode, supported provider branches, web clients, iOS, desktop/voice callers, and the separate Pi voice path. Identify which share assembly and which need adapters.
3. Inventory meaningful domain mutations and all writers: UI/API routes, chat tools, imports/sync jobs, background tasks, and device events. Create a coverage table with producer, event kind, canonical source, reconciliation path, invalidation behavior, and tests. Explicitly justify exclusions such as keystrokes or transient UI navigation; do not silently exclude whole app domains.
4. Verify scheduler registration and queue consumption. A task definition is insufficient; check the database-backed schedule if applicable, worker routing, retry recovery, and source-update-to-snapshot lag.
5. Extract a callable chat assembly boundary from `main_simple.py` with injected clock, context providers, and history access. Route production and deterministic replay through it. Preserve useful existing behavior while extracting.
6. Add failing regressions for the findings in section 3 before changing those behaviors. Tests must inspect actual outgoing messages and tool schemas, not a separate reconstruction of the intended payload.

Exit: a reproducible baseline, complete producer inventory, and a production assembly seam exercised by tests.

## 6. Phase 1 — Complete automatic context maintenance

Primary areas: `services/world_state/{writer,coordinator,reducer,interpreter,temporal,catalog}.py`, `models/world_model.py`, `schemas/world_events.py`, `tasks/world_state.py`, `services/world_brief.py`, `tasks/world_brief.py`, existing producer routes/tasks, and scheduler configuration.

1. Close producer gaps identified in Phase 0. At minimum cover email/thread changes, location, food CRUD, workout lifecycle/log edits, health ingestion, calendar/reminders, notes/documents, tasks/projects, and relevant background task outcomes. Track other active domains in the coverage table to completion.
2. Make source mutation and event durability atomic through the existing writer/outbox design. Dispatch after commit; recover broker failure from durable pending events. Reconciliation covers external sync gaps.
3. Make processing idempotent under duplicate delivery, retries, worker restarts, concurrent writers, and source corrections. Deduplication must preserve legitimate edits as new revisions. Handle deletions and retractions so summaries cannot resurrect removed facts.
4. Define a single supported projection-to-brief update path. Processing a world event must advance the chat-readable document revision; do not assume advancing `WorldSnapshot` automatically refreshes the separately stored prose brief.
5. Commit deterministic facts promptly. Queue interpretation only where useful, such as an email summary or meaningful synthesis. Interpretation must cite source identifiers, have bounded retries, and merge against the source revision it read; a slow result cannot overwrite newer evidence.
6. Prevent feedback loops: rendering a summary or updating the World Context page must not create a new independent fact that the next summarization pass treats as corroboration. Retain lineage to original evidence.
7. Reconcile against canonical sources using checkpoints/watermarks plus bounded periodic full checks where needed. A missing source is a coverage failure, not evidence that all its records were deleted. Retry and record durable failures.
8. Implement per-domain aging and local-day rollover. Preserve relevant historical events, replace current state, and condense old developments without dropping unresolved commitments.
9. Fix whole-brief caching. Cache stable data/fragments by revision and render time-sensitive labels at read time, or use a complete-render cache whose revision and expiry cannot outlive any constituent freshness deadline. Invalidate relevant caches after committed changes, including source updates that do not call `brief_patch()`.
10. Record source observation time, last successful reconciliation, projection revision, and backlog separately. “Refreshed now” must not imply that an offline source has fresh evidence.

Initial operational target under healthy local services: deterministic event-to-snapshot visibility within 5 seconds at p95; model-written summaries within 60 seconds at p95. Treat these as implementation targets to measure, not existing guarantees. Pending interpretation must not hide already available facts. Missed-event reconciliation should complete within the hourly interval plus one bounded run, with lag visible during failures.

Exit: with every app client closed, representative events still update a durable readable snapshot; expiry and reconciliation work without a chat trigger.

## 7. Phase 2 — One context envelope for every chat path

Primary areas: `main_simple.py`, `services/context_budget.py`, `services/context_snapshot.py`, `services/context_router.py`, `services/daily_brief/`, `services/session_cache.py`, and the Phase 0 assembly boundary.

1. Replace append-and-trim assembly with structured contributions carrying source ID, content, category, authority, observed/effective time, revision, supersession key, relevance, truncation policy, and budget.
2. Use the world snapshot as baseline awareness. Retire duplicate ambient reconstructions as each domain cuts over. Keep explicit retrieval for deeper questions, attachments, and details omitted from the briefing.
3. Reserve room for current user corrections, current activity/location with age, source uncertainty, and immediate commitments. Summarize these to bounded atomic facts before allocation; do not allow arbitrarily long “non-evictable” text to make the cap impossible.
4. Prioritize relevant conversation state, immediate commitments, requested domain state, and useful recent developments. Memories, lessons, journal material, and re-entry prose use remaining space. Protect a compact world-state core without injecting the entire page on every turn.
5. Resolve duplicate and superseded claims before rendering. Drop whole optional claims or safely summarize them; avoid cutting off negation, dates, source attribution, or the end of a structured block.
6. Begin with the existing 4,500-character ordinary ambient budget for comparability. Account separately for framing/clock, persona, history, attachments, tool schemas, tool results, and output reserve. Apply the model's total context limit at the actual outgoing request boundary. Report all accounting; moving text outside the ambient block is not a budget fix.
7. Include session reminders and all later contributions before final allocation. Apply shared constraints to initial requests, follow-ups, retries, and forced-final requests for every supported provider.
8. Use the same fact precedence and freshness behavior for local and non-local providers. Provider adapters may differ in role layout and caching mechanics, not semantic authority.
9. Read a versioned snapshot each user turn. During a long tool loop, check for relevant revisions at model-call boundaries and replace the old context contribution with a compact newer one. Do not restart a response for every ambient event or append competing versions indefinitely. A completed reply is tied to the revision it actually used.
10. Normal chat should read maintained projections without broad source polling. Retain only bounded recovery when necessary and expose lag; source outages should leave timestamped last-known context rather than empty or falsely fresh state.
11. Preserve full authoritative history durably. Reconcile client history by stable IDs and explicit coverage, and use a bounded transcript plus a tested summary for long threads. Allow targeted recovery of older messages. Session-cache titles do not imply the corresponding contents are present.

Exit: actual outgoing payload tests prove relevant current facts and corrections survive under pressure; no provider or follow-up bypasses the limits.

## 8. Phase 3 — Dialogue state and prompt repair

Primary areas: `services/dialogue_state.py`, `prompts/chat_system_prompt.py`, history reconciliation, and session caching.

1. Replace the backward completion-phrase scan with activity transitions scoped to domain/session and effective time. Starting a later workout resets the applicable state. “Heading to the gym” is not a generic completion event; “pain is gone” is a symptom observation, not workout completion.
2. Apply current-turn corrections immediately in conversation state. Preserve only the latest applicable correction per key; support normal corrections beyond the narrow `N sets of X` pattern. Do not infer completion or a correction when evidence is ambiguous.
3. Track questions and answers using turn references and topical evidence. Any short later user message is not automatically an answer. Handle topic changes and distinguish a repeated answered question from an unanswered question worth clarifying.
4. Replace “retrieve once / never re-fetch” with a freshness policy: reuse still-valid available evidence; refresh mutable records when revision, age, a user request, or conflicting evidence requires it. Retrieval should distinguish cache hits from fresh source checks.
5. Replace “You remember everything” with an accurate contract for supplied transcript, summaries, and history-retrieval capability.
6. Clarify action truth rules: claim a newly requested action succeeded only after a successful receipt; an earlier action may be described as completed using its timestamped receipt without repeating it. Failure, partial success, and merely queued work must be described accurately.
7. Define evidence authority explicitly. A sourced world fact is evidence with age and provenance; an inferred routine is not evidence of today's activity. User corrections supersede stale summaries. Preserve measurement attribution and missing-data rules.
8. Make tool instructions conditional on available capabilities and current policy. Update any tool-menu description after mid-turn discovery, or use wording that correctly defers to the current schemas.
9. Treat email/document/retrieved text as source material, never new instructions. Keep source quotations and third-party requests separate from David's commands, including through summarization and rendering.
10. Preserve Sara's established identity and voice while removing conflicting rules. Add rendered-prompt and behavioral scenario tests; checking for a few required substrings is insufficient.

Exit: the morning/evening workout scenario, user corrections, stale-data refresh requests, and long-thread reconnection produce consistent context and instructions.

## 9. Phase 4 — Tool selection and execution policy

Primary areas: `services/tool_retrieval.py`, `services/tool_mutation.py`, `tools/base.py`, `tools/registry.py`, and tool discovery/execution in `main_simple.py`.

1. Add explicit capability metadata for read operations, source refreshes, domain mutations, and external effects. Replace authorization based on name tokens; a read-only tool containing `log` or `check` must not be misclassified merely by its name.
2. Use a small tool set for the actual turn. Greetings and casual reactions normally need none; discovery and lookup requests should receive relevant tools. Preserve a way to discover capabilities when needed without restoring the unconditional 15-tool menu.
3. Resolve action scope from David's current request, an explicit UI action, a documented existing preference/standing permission, or a pending authorized operation. Account for negation, quotation, hypothetical language, and continuation. A standalone verb or noun is not permission.
4. Treat casual reported facts as world evidence without automatically mutating domain logs. Preserve any established explicit auto-logging preference with its specific scope; otherwise an actual logging request authorizes the write.
5. Separate sticky capability names from an authorization record. A discovery result never creates authorization. “Yes, do it” may continue a clearly identified pending action; a previous unrelated write is not blanket authorization.
6. Apply the same policy to initial tools, family expansion, work mode, `find_tools`, retries, and execution. Immediately before invocation validate the tool is currently offered/approved and its requested operation falls within scope. Rejected calls return actionable structured errors and do not invoke the registry tool.
7. Fix discovery capacity to `max(0, cap - current_count)` and deduplicate names. If space is needed, evict irrelevant schemas deliberately; do not silently exceed the cap. Only actually loaded names may become capability-sticky. Enforce the cap on every outgoing tool payload.
8. Preserve existing round/deadline limits, cancellation, malformed-call handling, tool-result preservation, and forced-final behavior. Make writes retry-safe with operation IDs where retries could duplicate a side effect.

Required cases include “Don't delete anything,” “The email was interesting,” quoted commands inside email, a genuine send/delete request, an unrelated later turn, an authorized continuation, unknown/unoffered tool calls, and discovery at exactly 35 tools. Test that rejected mutations never reach a fake executor, not merely that schemas disappear.

Exit: discovery stays useful while authorization and tool limits remain enforceable at execution.

## 10. Phase 5 — One canonical reply across storage and clients

Primary areas: `SimpleLLMClient`, `process_chat()`, episode/legacy conversation storage, `ios-app/src/services/{api,chat}.ts`, `ios-app/src/hooks/useSaraChat.ts`, and web/voice stream consumers.

1. Move response normalization and bounded repair to a shared finalization stage before assistant persistence and final-event emission. Every normal, tool-assisted, forced-final, and recoverable-error path must use it.
2. Prefer deterministic removal of a demonstrably duplicated trailing question when a complete answer remains. For contradictions that require regeneration, permit at most one bounded repair call within the existing deadline. Do not invent a canned success if repair fails.
3. Give each turn stable client-message, turn, and assistant-message identities. Treat streaming deltas as provisional; emit a canonical final event with replacement semantics and a clear terminal state.
4. Persist the finalized text once, idempotently, before claiming it is durably saved. Make final-event delivery replayable by turn ID after disconnect. If persistence fails, report the incomplete state honestly and support recovery rather than silently claiming normal completion.
5. Update both iOS final-response parser paths to replace provisional content, including a shorter, different, or intentionally empty final string. Centralize parsing to prevent the two branches drifting. Do not use truthiness to discard a valid empty final response.
6. Verify equivalent web behavior, TTS, and all voice consumers. If speech is streamed, hold back text subject to repair or define a buffering strategy so a rejected question is not already spoken. Text replacement alone cannot undo speech.
7. Trigger legacy-history writes, memory extraction, lesson tracking, enrichment, and any world-event emission from the canonical persisted result. The original pre-repair reply must not survive in another store or extraction queue.
8. Keep the user turn durable before inference. On cancellation, distinguish partial provisional output from a completed assistant reply. Avoid duplicate model/tool execution on transport retry; return/recover the existing turn where appropriate.
9. Verify the existing lesson-tracker and incremental-enrichment repairs with isolated PostgreSQL tests and task retry tests. Preserve their watermarks, deduplication, and failure isolation while moving finalization.

Exit: displayed text, canonical final event, assistant episode, legacy conversation, and enrichment input agree after a repair, reload, reconnect, retry, or client switch.

## 11. Phase 6 — Read-only World Context page

1. Expose an authenticated user-scoped read API for the maintained world document, revision, source references, per-section freshness, and coverage status. The page must not invoke source reconciliation or model generation merely to load.
2. Add a World Context destination to the existing Sara area on web and iOS, using established navigation and design conventions. Show current situation, recent developments, upcoming commitments, and last-known/unavailable information.
3. Update the page through the existing event transport or bounded revision polling. Distinguish when the document changed from when a fact was last observed. A quiet but healthy system should not look broken just because nothing changed.
4. Allow inspection of source and time through concise detail affordances. Do not expose prompts, queue internals, or editing controls in the ordinary product flow.
5. The page and chat must derive from the same versioned facts and renderer. The page may show more detail than the chat budget permits; diagnostics must identify the revision and subset chat received.
6. Show degraded source coverage automatically. David never needs to manually refresh or edit the document to keep Sara informed.

Exit: a logged event appears on both the page and the next chat turn from the same underlying revision, without manual maintenance.

## 12. Verification and acceptance matrix

Use deterministic clocks and synthetic sources for required behavior. Run integration tests with isolated PostgreSQL, isolated Redis, temporary brief directories, fake tool executors, and disabled production task dispatch. Read `backend/tests/replay/README.md` before using its tooling: fixtures and production brief mounts must not be overwritten, and the existing root conftest includes database cleanup side effects. Do not run an unrestricted suite against live services.

| Scenario | Required assertion |
| --- | --- |
| Email arrives while app is closed | Event, sourced summary, snapshot revision, and page advance; next chat can use it without email polling. |
| Location changes then feed goes silent | New observation replaces old location; after its deadline the wording becomes last-known, with original observation time. |
| Morning workout completes; evening workout starts | Morning remains history; evening is active; prompt contains no instruction that all workouts are completed. |
| Food/workout entry is edited or deleted | Totals and derived statements update; duplicate delivery and late old events cannot resurrect the previous value. |
| Calendar reschedule/cancellation | Old commitment is superseded in page, prompt, and relevant cache before the next normal turn. |
| Worker/broker outage and restart | Durable events recover exactly once in effect; failed gaps remain visible; snapshot completeness is not inferred from max sequence. |
| Slow interpretation races a new correction | Old model output is rejected/rebased; the correction remains authoritative. |
| Source unavailable during reconciliation | Existing evidence is retained with honest age; no false deletion or freshness reset. |
| Local midnight, timezone offset, DST | Day labels/totals are correct and historical facts remain historical. |
| Oversized ambient context/attachments/tool results | Critical facts and corrections survive; all actual requests respect model capacity and ordinary ambient allocation. |
| Local/non-local, normal/work/voice chat | Equivalent evidence precedence and freshness; no branch bypasses policy or finalization. |
| Mid-conversation external event | Next user turn sees the newer revision; long tool loops incorporate relevant changes at the next safe request boundary. |
| “Don't delete anything” / mentioned email / quoted command | No unauthorized mutation executes, including through discovery or sticky tools. |
| Explicit action and authorized continuation | Correct scoped tool executes; denial logic does not break ordinary supported requests. |
| Discovery at tool cap | Payload remains within cap, and advertised tool descriptions match available capabilities. |
| Duplicate trailing question removed | iOS/web canonical display, saved history, reload, and enrichment all contain only the repaired answer. |
| Disconnect, retry, storage failure | User turn survives; completion state is honest; no duplicated mutation or completed assistant episode. |
| Long thread and partial client history | Relevant earlier statements can be recovered; no claim of complete recall without evidence. |
| Ephemeral chat and two users | No durable ephemeral-world writes and no cross-user cache, event, page, or history leakage. |

Required test layers:

1. Unit tests for event ordering, expiry, supersession, allocation, dialogue transitions, tool policy, and finalization.
2. PostgreSQL integration tests for event/source transactions, leases, retries, migration constraints, and canonical reply persistence.
3. Shared-assembler and actual endpoint tests capturing initial/follow-up/forced-final provider payloads with fake models and tools.
4. Client tests for chunking, split final events, replacements, empty final text, reconnect, and delayed/duplicate final events.
5. End-to-end synthetic scenarios from committed source change through worker projection, page API, chat payload, final response, and reloaded history.
6. Opt-in live-model evaluation using the September 16 morning sequence plus the new scenarios. Repeat stochastic samples and report outcomes and limitations; one fluent response is not proof. Mutating tools remain fakes in evaluation.

## 13. Diagnostics, rollout, and completion

Record content-free diagnostics by default: turn IDs, snapshot revision, coverage/gaps, observation ages, event-to-projection lag, reconciliation results, kept/dropped source IDs with reasons, budgets by contribution, selected tools and policy decisions, repair outcome, canonical message ID, and persistence/final-delivery status. Explicit prompt capture should remain opt-in and protected; do not log raw emails, location trails, or complete conversations by default.

Suggested implementation sequence and review units:

1. Baseline regressions and common assembly seam.
2. Dialogue, tool authorization/cap, and reply-finalization fixes with client reconciliation.
3. Producer coverage, durable maintenance, freshness/reconciliation, and cache corrections.
4. Versioned world briefing, context allocation, prompt rewrite, and retirement of duplicate readers.
5. Read-only page, full integration replay, and rollout documentation.

Keep schema changes additive initially. Backfill from canonical sources idempotently with provenance; do not replay old notifications or external effects. Shadow-compare old and new context as diagnostics, then switch chat/page consumers to one projection. Do not inject both conflicting versions into the same model request during migration. Retire obsolete append sites, caches, and schedules only after their replacements cover the required domains.

Rollout documentation must identify migrations, scheduler registrations, worker queues, feature flags, backfill commands, validation commands, and rollback steps. A rollback must preserve the event journal and user data, avoid duplicate maintenance jobs, and label degraded freshness if the previous reader cannot provide the same guarantees. Production deployment and external side effects follow the implementing session's authorization; this planning task itself performs neither.

Completion requires all of the following:

- The domain coverage table has no unexplained producer gaps.
- Context updates, expires, and reconciles while clients are closed; no manual editing is required.
- World Context page and chat use the same underlying revisions and fact semantics.
- Every finding in section 3 has an executable regression, including production assembly and iOS final replacement.
- No provider/round bypasses context, tool, or finalization contracts.
- Relevant existing tests and the end-to-end matrix pass in isolation, with measured freshness and clear live-model evaluation results.
- Existing user work is preserved, migrations and operational steps are documented, and the implementing agent's handoff states what was changed, what was tested, what was deployed, and any remaining limitations.

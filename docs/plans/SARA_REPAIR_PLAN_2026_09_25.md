# Sara repair plan

Date: 2026-09-25  
Status: proposed implementation plan; no application changes or deployment performed  
Author: Codex, reviewed directly without subagents

Companion: [finding-by-finding evidence map](SARA_REPAIR_EVIDENCE_MAP_2026_09_25.md), covering all 47 numbered report rows plus the earlier conversation study and outstanding coverage.

## 1. What needs to change

Sara has several separate reliability problems. A personality prompt cannot repair them:

1. A request can expose authority to perform unrelated actions, or a follow-up can lose access to the tool it needs.
2. Successful actions are not consistently available as durable evidence on later turns. Sara sometimes invents success, denies real success, or performs a destructive “repair” based on that denial.
3. Read caches, object identity, worker-created artifacts, and cross-client state can disagree with the database.
4. Time, units, tool return types, scheduler selection, and background-job lifecycle have concrete implementation defects.
5. The original conversational complaint remains: coldness, excessive information, repeated paraphrasing, unwanted troubleshooting, and weak flow.

Repair in that order of consequence, while allowing small independent reliability fixes early. Preserve the useful parts: ownership checks, injection resistance demonstrated in the study, honest failure handling, and request-identity deduplication. Do not replace the platform wholesale or launch another open-ended evaluation.

The intended user experience is simple: Sara acts on the intended object once, remembers what actually happened, handles corrections without destroying unrelated information, and responds naturally without making David supervise every step.

## 2. Evidence reviewed and limits

Primary sources:

- [Acceptance findings](../../backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/FINDINGS.md), coverage, manifest, README, snapshot identity, infrastructure patch disclosure, and structured results in that directory.
- [Original functional plan](SARA_FULL_ASSISTANT_ACCEPTANCE_PLAN_2026_09_24.md) and [case catalog](SARA_FULL_ASSISTANT_ACCEPTANCE_CASES_2026_09_24.md).
- [Conversation-study findings](../../backend/tests/conversation_eval/artifacts/FINDINGS.md), including the corrected PC_BLOCK recommendation and methodology limitations.
- Current application source at the repair boundaries listed below. Nine selected high-impact files matched the study execution copy byte-for-byte when checked: `main_simple.py`, `tool_mutation.py`, `session_cache.py`, `food_search_log.py`, `reminders.py`, `registry.py`, `day_layer.py`, `documents.py`, and `research/executor.py`.
- Representative raw transcripts were cross-checked for note data loss, both wrong-target cancellations, both unauthorized standing orders, duplicate reminder on “Thanks,” failed confirmation routing, thread resolution, PDF denial, document search, and workout start. Raw SSE tool events show invocation, not necessarily commit; database claims without surviving snapshots remain study-reported evidence.

This review does not independently reproduce every finding or certify the live process. No model requests, services, or production data were used for this review. The historical study's production-untouched claim is its report, not a new deployment verification.

### Corrections that affect repair decisions

- `results.jsonl` contains 207 physical records, of which 205 parse; two malformed lines must be preserved and normalized in a derived index, not silently discarded.
- The five fitness catalog rows are labeled `J01cat`–`J05cat` and mapped collectively to journey J06. The actual catalog has five distinct J01–J05 oracles. A workout-start failure cannot stand in for all five.
- Several reported passes are partial or source-only: P02 was not executed, K01 did not finish its requested answer, and portions of C04/L04/O02/M05/S03 remain untested. Coverage text retains superseded severities. The published 49/34 totals are not a readiness score.
- P04 was attempted but inconclusive. `day_layer.consolidate()` deliberately returns false when content is at most 3,000 characters. An empty fresh fixture does not prove broken consolidation.
- G05 need not exceed the model's entire 262k context window. `main_simple.py` trims the tool-loop conversation around 20 messages; context assembly also has explicit budgets. Test those actual boundaries with seeded history and controlled responses first.
- R03 is not inherently blocked by single-generation concurrency. Concurrent API clients can queue behind one model slot; deterministic integration tests can also exercise races without simultaneous generation.
- The claimed “92 executed” count is not reconciled by the report's own source-only, inferred, and not-run entries. Build a derived assertion-level matrix; do not spend another broad study trying to defend the old aggregate.
- The request ledger contains 1,005 reservations but only 941 completion records. The 64 unmatched reservations have unresolved outcomes. Its 43,269.554 seconds of completion elapsed time includes waiting for the generation lock, so it is not pure model generation time. This does not change the known failure evidence, but future budgets need separate queue, upstream, and active-session measurements.
- “Five P0 findings” counts occurrences: the central mechanisms are destructive note replacement, wrong-target cancellation, and unauthorized recurring automation. Keep repetitions as evidence, not separate implementation projects.
- J10 trial 2 cancelled an unrelated reminder; it did not cancel another research task. The plan must cover both target types.
- A model's leaked text referring to a coding prompt does not prove such a prompt was injected. The exact source phrase was not found in the application search performed for this review. Prompt contamination and untagged model output remain separate hypotheses.
- The research wait loop uses raw SQL, so an ORM identity-map explanation is not established. Inspect transaction isolation, actual message linkage, task scheduling, and lock ownership before selecting a fix.
- Existing patches use both naive-local and naive-UTC storage. A global timestamp conversion would corrupt some correctly stored records.

These limitations do not erase the observed failures. They determine which repairs have a confirmed mechanism and which need a small diagnostic first.

## 3. Execution order

Each work package below should be a reviewable change with its own failing reproduction, implementation, and focused regression results. Changes may be developed sequentially by one implementer; this plan does not require agents.

| Order | Work packages | Why this comes here |
|---|---|---|
| 0 | R00 baseline and evidence index | Preserve unrelated work and make candidate/rollback identities explicit. |
| 1 | R01 authorization, R02 safe edits and identity | Stop unintended automation, wrong-target actions, and destructive corrections. |
| 2 | R03 durable action evidence, R04 routing and fresh reads | Stop false confirmations/denials and make follow-ups dependable. |
| 3 | R05 time, R06 delivery, R07 broken tools, R09 device verification, R11 logout | Repair concrete outages and incorrect outcomes. Small independent fixes may be prepared during orders 1–2. |
| 4 | R08 nutrition/fitness/history, R10 background jobs, R12 world state | Repair multi-step and cross-domain consistency. |
| 5 | R13 response delivery and latency, R14 conversational behavior | Address empty/leaked replies and the original experience complaint on a reliable action foundation. |
| 6 | R15 capability gaps and final acceptance | Verify previously unproven paths and explicitly scope feature additions. |

Dependencies: R03 reuses the authorization and identity contracts from R01/R02. R04 consumes R03 receipts. R06 uses R05's time contract. R08 uses R02 corrections and R05 dates. R10 uses R03 receipts and R04 artifact indexing. R14 uses R04 relevance and R13 response delivery.

Do not wait for every package to finish before reviewing a small fix. Deployment, however, needs the release gates in section 7; no unchecked restart of the dirty backend tree.

## 4. Work packages

### R00 — Preserve the baseline and turn findings into replayable evidence

**Scope:** documentation/test infrastructure; no application behavior change.

- Snapshot the full candidate source, relevant schema/migration identity, dependency locks, and sanitized configuration before edits. Preserve tracked and untracked work; do not stash, reset, clean, or stage unrelated files.
- Keep three identities separate: study execution copy, current candidate, and the currently running deployment. The study's `patched_execution_copy.sha256` is explicitly stale. Generate a fresh manifest for future runs; retain the old manifests unchanged.
- Create a derived normalized failure index, retaining raw file/line references, superseding corrections, and malformed original records. Namespace catalog IDs as `CAT-J01` and journeys as `JOURNEY-J01` to eliminate collisions.
- For each repair, retain a minimal fixture, exact request, expected state, forbidden effects, and independent assertion. Record supported/partial/blocked evidence separately from pass/fail.
- Inventory existing `action_receipt`, `action_ledger`, world-event/outbox, commitment, and episode stores. Extend existing infrastructure rather than introduce a competing ledger.

**Done when:** each package has a reproducible baseline and every finding in the companion traceability table has an owner package. No claim that the current snapshot is a recovered pre-patch deployment.

### R01 — Authorize the specific action at execution

**Evidence:** J01 status-question cancellation; C03 duplicate on “Thanks”; J02 exploratory calendar write; J10 wrong-target actions; J11 hypothetical standing orders; mutation-gate source.

**Files:** `services/tool_mutation.py`, `tools/base.py`, `tools/registry.py`, `tools/mutating.py`, chat/voice dispatch in `main_simple.py`, `tools/standing_orders.py`, `services/standing_order_service.py`.

**Confirmed structural issue:** `gate_mutating_tools()` grants all candidate mutations when any action phrase matches. Recent executed tool names plus continuation phrases are not a record of a pending proposal. Two different mutation classifications exist: name heuristics and the deadline write list. Offered-menu checking already exists; preserve it, but it is not operation/target authorization.

**Change:**

1. Add explicit registry metadata for effect type, affected domain, target parameters, permission requirements, and cache dependencies. Validate that every registered tool is classified. Unknown effects remain conservative. Use one definition across discovery, execution, deadline handling, and audit.
2. Represent pending proposals separately from completed actions: authenticated user, conversation, originating turn, action/target/parameters, expiry, status, and consumption identity. A scoped “Yes” can consume one pending proposal; “Thanks” after completion cannot reopen it.
3. Carry a server-owned per-turn authorization decision to the execution boundary. It binds operation and permitted targets/scope to the actual human request or an active authorized standing order. An LLM-selected name, tool description, or retrieved document is not authority.
4. Check ownership, operation, target, and current cancellation/proposal state immediately before mutation. Apply the same rule to mid-turn discovery, deadline writes, voice, and background paths. Do not infer a trusted chat origin merely because context is missing.
5. For ambiguous destructive targets, require selection of a concrete object. Preserve normal direct execution for explicit, unambiguous requests; avoid adding confirmation to every harmless action.
6. Require explicit recurring scope before activating a standing order. Hypothetical or one-time language cannot become recurring authority.
7. Audit the existing always-allowed notification acknowledgment exception for narrow ownership and effect scope.

**Tests:** exact study negatives, quoted/hypothetical/status language, “Thanks,” pending/completed/expired “Yes,” explicitly requested second identical action, two clauses with one valid request, one-time versus recurring home control, cross-user IDs, wrong-domain targets, injected tool names, discovery, voice, deadline, and direct registry/background entrypoints. Assert forbidden effects are zero at DB/adapter level, not merely absent from a menu.

**Done when:** the known unauthorized writes fail closed while explicit authorized equivalents still work. Language heuristics may assist routing, but cannot alone grant unrelated write authority. Broader natural-language reliability remains evaluated by full conversations.

### R02 — Make corrections, target resolution, undo, and retries preserve data

**Evidence:** J03 note data loss, J10 unrelated cancellation, J06 duplicate set correction, J05 duplicate food correction, J07 forked lists, J14 duplicate tasks, J16 duplicate note, O05 undo.

**Files:** `tools/notes.py`, `tools/lists.py`, task/reminder/workout/food tools, `services/thread_resolution.py`, `services/standing_order_service.py`, existing action ledger and relevant models/migrations.

**Change:**

- Use typed, owner-scoped IDs returned by reads/receipts. A title placed in an ID field should return a typed invalid-reference error and safe lookup options, not encourage a guessed replacement.
- Add versioned note edits and revision history. Prefer explicit append/remove/replace operations for narrow user edits; whole-content replacement must use a fresh base revision. On conflict, reread and apply only the requested change. A fresh revision check alone does not prevent the model omitting unrelated content; patch semantics and before/after checks are also needed.
- Resolve references within a known entity type and active task. “Close that follow-up” does not authorize sweeping reminders and research jobs with vaguely related titles.
- Use stable list IDs with conservative, explicit aliases for built-in lists. Do not fuzzy-merge arbitrary user lists or existing data automatically.
- Implement missing update/delete operations where corrections currently have no valid tool, especially food entries and workout sets. Corrections update the original ID; a create tool is not a substitute.
- Key idempotency to the authenticated request and logical operation, with transactional uniqueness. A retry reuses its key; a distinct explicit request gets a new key. Do not deduplicate all matching text forever. Detect conflicting parameters for the same operation instead of creating a second object.
- Persist operation state before external dispatch; reconcile uncertain outcomes before retrying. API message/episode dedup alone does not establish mutation idempotency.
- Undo must target the recorded action, verify owner/window/current revision, execute the supported inverse, and update bookkeeping atomically. Preserve the original object when the operation permits it. Do not promise exact restoration when only a compensating new object is possible.

**Tests:** preserve spare cable while removing rain jacket; concurrent note edits conflict safely; morning/evening workout selection; 150g→120g replaces one entry; grocery aliases do not fork or merge unrelated lists; same request lost-ack replay creates once; two explicit requests remain distinct; undo twice has one effect; undo of expired/changed/wrong-owner action is refused.

**Done when:** corrections change only the intended fields/object, independent retries do not duplicate effects, and destructive revisions are recoverable. Existing production damage requires a separate evidence-based repair preview, never an automatic inferred rewrite.

### R03 — Give Sara durable evidence of actions and ground confirmations in it

**Evidence:** false reminder/research/chess/goal success; real food/PDF/task denial; false confession under pressure; original conversation study's missing action evidence.

**Files:** `services/action_receipt_service.py`, episode/history assembly, `main_simple.py`, tool result contracts, commitment/research artifact linkage.

**Existing infrastructure:** `action_receipt_service.py` currently shadow-records standing-order actions, catches recording errors, and builds timestamp-based idempotency keys. It is not yet a transactional chat-wide action ledger. Reuse its schema where suitable after inspecting migrations and callers.

**Change:**

- Define durable outcomes: proposed, authorized, running, committed, verified, failed, cancelled, and unknown/partial as appropriate. Store user, turn/request, target ID/version, operation key, safe result summary, timestamps, and linked artifact/job IDs. Do not store private reasoning as evidence.
- Commit local mutation and receipt together. For external systems, persist intent before dispatch and reconcile returned receipts/state; an HTTP acknowledgment need not mean the effect is verified.
- Retrieve relevant receipts on later turns, after compaction, across clients, and after restart. Distinguish “it succeeded then” from “the object still exists now”; use a fresh read for current state.
- Render action confirmations from actual receipts. “Queued” is different from “completed”; a request that never executed cannot produce a completed-action card or definitive success summary.
- When challenged, verify the relevant record. Absence from the current tool menu or truncated history is not evidence that an earlier action never occurred. Use “I can't verify that right now” when evidence is unavailable.
- Guard action-bearing final output against the action results for that turn. Do not claim a keyword filter or another model judge proves all free-form prose truthful. Use structured outcome rendering for definitive action claims and test the remaining prose explicitly.
- Preserve compact, task-relevant evidence without dumping raw tool payloads into conversation.

**Tests:** zero-call chess/goal/reminder outcomes cannot be presented as executed; failed write stays failed; committed write plus lost acknowledgment remains discoverable; real PDF challenged by user remains grounded; receipt exists but object later deleted is described accurately; new conversation and compacted history retain action evidence; authorization expiry does not erase historical evidence.

**Done when:** known false-success/denial journeys pass with independent state assertions and legitimate skeptical follow-ups. Root causes for residual free-form fabrication remain explicit rather than attributed to one universal cache bug.

### R04 — Keep the right tools and fresh information available on follow-up

**Evidence:** C03 scoped confirmation, H05 thread resolution, M03 home scheduling, O04 tool ignored despite availability, G03 scratchpad, K03 learning, F04 PDF revision, C05 cache, J15 cross-client stale read, J09 report retrieval.

**Files:** `services/intent_classifier.py`, `services/tool_retrieval.py`, `services/chat_assembly.py`, `services/session_cache.py`, `main_simple.py`, domain read tools and artifact lookup.

**Change:**

- Treat intent categories as retrieval hints. Carry the pending proposal, recent object IDs, and active task through follow-ups so “Yes,” “change that,” and “show it” retain the relevant capability. Keep this separate from R01 authority.
- Make capabilities discoverable from the registry even when absent from the current menu. Distinguish unavailable this turn, unsupported, service unavailable, and forbidden.
- Trace category choice, candidate retrieval, final offered tools, authorization decision, selected tool, cache use, and execution result. A tool that was offered but ignored needs a different fix from one excluded by routing.
- Add commit-triggered cache invalidation using user/domain revisions, covering writes from API, chat, another client, worker, and undo. Conversation-only invalidation is insufficient. Do not cache errors or volatile timer status for 30 minutes. Check authorization before returning cached data.
- Use direct ID lookup for recent artifacts and background tasks. Semantic retrieval is a fallback, not the sole way to find a job's own result.
- Index worker-created notes through the shared indexing pipeline, with retryable indexing status. Keep assistant-generated provenance so indexing a report does not turn it into a user assertion.

**Tests:** exact eight routing instances, scoped “Yes,” explicit action versus status-only follow-up, two clients and API/worker writes, negative-result cache followed by create, edit/delete/undo freshness, read failure then recovery, indexed and indexing-pending research reports, and no expansion of mutation permission from discovery.

**Done when:** correct capabilities remain reachable with bounded schema size, recent writes are visible across paths, and failures can be localized to selection versus execution versus retrieval.

### R05 — Establish explicit time and date contracts

**Evidence:** reminder write/read masking, calendar/reminder convention mismatch, naive/aware timer crash, food local timestamp, task default date mismatch, HRV date shift.

**Files:** `core/timezone.py`, `tools/reminders.py`, `tools/timers.py`, calendar tools/routes, food/task tools, health routes/tools, temporal columns and migrations.

**Change:**

- Inventory column semantics first: absolute instant, local civil time plus timezone, date-only fact, or duration. Preserve existing correctly stored values under their documented conventions.
- Interpret offset-free reminder input in the authenticated user's configured IANA timezone; preserve explicit offsets. The current helper hardcodes Eastern, so a user-aware interface is needed. Clarify ambiguous/nonexistent DST times rather than silently choosing.
- Return explicit UTC instants plus local display values/timezone from create, list, update, and receipts. Apply local-day filters via correct UTC bounds, including DST-length days.
- Normalize datetime awareness at timer read/write boundaries and eliminate duplicate Timer model conventions. Preserve seconds rather than relying only on truncated minutes.
- Treat health day markers as dates when they truly represent calendar days; do not blindly timezone-shift midnight markers. First reproduce the HRV issue across ingestion, storage, query, and rendering.
- Use the same user-local “today” source for tasks and food. Fix `logged_at` according to the real column contract.

**Tests:** New York and London users, explicit/no offset, midnight, cross-midnight ranges, DST fold/gap, 23/25-hour days, timer start/status/cancel, 30/90-second timers, historical health dates, late data, and no artificial shift in already-correct calendar records.

**Migration rule:** never apply a blanket four-hour correction to legacy reminders. Some were correct. Produce a read-only audit with provenance/confidence and a proposed correction list; only repair determinable records through a separately reviewed operation.

### R06 — Deliver reminders and timers reliably

**Evidence:** descriptionless crash and overdue selection. Current `notification_predispatch()` selects a future 20-second window for both reminders and timers and has no overdue catch-up in that path.

**Files:** `tasks/inproc_schedulers.py`, `models/reminder.py`, push/notification services, delivery/outbox persistence.

**Change:**

- Remove the nonexistent `reminder.content` fallback; use description/title/default safely. This is a small independent fix, but it does not repair scheduling.
- Separate delivery status from user completion. Persist attempts, due occurrence/revision, next retry, accepted/verified status, and last error as supported by the actual transport.
- Select due undelivered occurrences, including controlled catch-up after downtime. If using advance scheduling, distinguish enqueue time from actual delivery time; do not notify early merely because the occurrence entered the lookahead window.
- Claim work atomically across workers, use stable delivery keys, retry transient failures with bounds, and record permanent failure. Recheck cancellation/rescheduling and quiet/expiry rules at dispatch.
- Avoid flooding David with historical reminders at first deployment. Audit backlog and define catch-up/expiry policy before enabling it. Mark intentionally expired items explicitly.
- A sink/provider acknowledgment proves acceptance at that boundary, not delivery to a physical phone. Keep the guarantee honest.

**Tests:** description present/absent, due before first poll, downtime/restart, duplicate workers, failure before send, send-success/ack-loss, cancelled/rescheduled queued item, timer expiry, quiet mode, stale backlog, and no duplicate delivery for the same occurrence under the supported idempotency contract.

### R07 — Repair tool invocation contracts and document search

**Evidence:** `start_workout` dispatch and result failures; `documents_search` SQL error and failed fallback.

**Files:** `tools/base.py`, `tools/registry.py`, `tools/fitness/workout_mode.py`, `services/workout_session_service.py`, `tools/documents.py`, `models/document_chunk.py`, ingestion/migrations.

**Workout changes:** standardize `execute(user_id=..., **validated_parameters)` and `ToolResult` across registered tools; supply legitimate DB context where needed. The current workout method's first positional argument is `template_id`, while the registry passes `user_id` positionally. It also expects a DB session and returns dictionaries. Fix the complete contract, not only `.success` access. Audit sibling workout tools for the same mismatch. Validate return shapes on every success/error path.

**Document changes:** the model declares `DocumentChunk.embedding` as Text, while search casts only the query operand to vector. Verify the actual schema, existing values, and dimensions; choose a compatible validated cast or an additive vector-column migration/backfill. Isolate vector failure in a savepoint or separate read transaction so lexical fallback remains usable. Preserve tenant predicates and stable document/chunk citations. Do not claim all production search is broken merely because the test's vector path failed; Neo4j may be a separate working path.

**Tests:** workout by ID/name/no arguments/missing template/two templates/wrong owner; inspect whether any state committed before a return-shape error; retries create no duplicate session. Document real ingest→semantic search, malformed vector, wrong dimensions, embedding outage, vector SQL failure→working lexical fallback, pagination, and other-user exclusion.

### R08 — Make fitness, food, and recipe records correctable and historically accurate

**Evidence:** J05 scaling/name parsing/time/duplicate correction; J06 wrong set, missing units and corrections; I04 recipe history.

**Files:** `tools/fitness/food_search_log.py`, `food_log.py`, `workout_log.py`, workout command/session services, `tools/recipes.py`, recipe/nutrition models and client consumers.

**Change:**

- Fix quantity parsing with token boundaries and structured quantity/unit inputs. Current regex lists `g` before `gram`/`grams`, permitting a prefix match that truncates the food name. Trace the observed scaling failure through actual fixture/provider serving fields before assigning it solely to that regex.
- Compute from explicit serving quantities and units. Do not multiply “grams” by a summary serving count or silently substitute approximate density as exact data. Ask when conversion information is missing.
- Preserve food/provider/serving IDs, source nutrition, requested quantity, units, and calculated totals. Correct the original row atomically; do not log a second “correct” meal and leave the wrong one active.
- Record workout units explicitly, with a canonical conversion policy and decimal precision. Current confirmation text hardcodes lbs. Include workout/session/exercise/set identity in reads and updates; don't silently select the first same-name session.
- Preserve recipe version and consumed ingredient/quantity/nutrition snapshot at logging time. Editing the recipe must not rewrite historical consumption. Keep existing counters, but do not pretend they are a full meal history.
- Historical weights with unknown units remain marked unknown unless provenance establishes the unit. Never backfill guessed kg/lb values.

**Tests:** 150g chicken = 247.5 kcal/46.5g protein, corrected 120g = 198/37.2; gram/grams/g/kg/oz and serving counts; provider failure without duplicate writes; morning/evening sets; 60kg conversion/display; changed recipe portions preserve original logged meal; exact local dates via R05.

### R09 — Verify smart-home outcomes

**Evidence:** M02 control returns success even when the adapter reports no state change. Source confirms several HA methods return success after HTTP completion alone.

**Files:** `services/ha_control_service.py`, home tools, standing-order execution/verification, R03 receipts.

**Change:** distinguish command accepted from state verified. Inspect response where meaningful and perform a bounded fresh state check for asynchronous devices. Return pending/unverified/failed when unavailable or unchanged. Do not blindly retry non-idempotent toggles; prefer explicit desired state. Preserve authority from R01.

**Tests:** healthy immediate and delayed change, unchanged/unavailable entity, stale response, timeout after acceptance, duplicate toggle prevention, wrong-user device, and both direct-chat and recurring execution. A real-device acceptance test remains separate from adapter validation.

### R10 — Make background work resumable, discoverable, and cancellable

**Evidence:** completed research invisible, answered question not resumed, lock blocks later plans, terminal task redelivery resets work, dispatch avoidance, recovery-dependent results.

**Files:** `tasks/research.py`, `services/research/executor.py`, `lane_lock.py`, `cancel.py`, research tools/models, note indexing and commitments.

**Change:**

- Enforce a transactional state machine: terminal results cannot return to running on duplicate delivery. Distinguish explicit user-authorized restart from automatic resume of eligible parked work. Recheck after acquiring the claim, not only before.
- Make execution attempts, steps, artifacts, and notifications idempotent. Link reports to plan/run IDs; title-plus-day dedup must not merge genuinely different jobs or append duplicate retries.
- Diagnose answered-question liveness with a deterministic two-session fixture and no model. Verify exact message/plan/step linkage, transaction visibility, queue placement, polling cancellation, and event-loop health. Do not assume `expire_all()` fixes raw SQL visibility.
- Persist waiting-for-answer state and release scarce execution capacity while waiting. Resume once from an answered event; use bounded polling as recovery. Cancellation must work in every waiting state.
- Use atomic token-checked lease renewal/release and fencing at effects; a worker that loses its lease must not continue writing. Treat unavailable locking conservatively for scarce generation resources.
- Save artifact ID and indexing state before claiming completion. Report partial work honestly; direct ID retrieval works while indexing catches up.

**Tests:** redelivery before/after each commit, complete/partial/cancelled terminal states, same question answered by another session, answer-worker saturation, lock loss, expired worker lease, waiting task plus second task, cancellation while waiting, one report/notification per logical result, and restart without manual cleanup.

### R11 — Make logout invalidate the intended session

**Evidence:** A05 replay of bearer token after logout; `routes/auth.py` clears cookies and `core/auth.py` verifies stateless JWTs.

**Change:** establish explicit per-session revocation semantics using a durable session ID/version or revocation record checked by all applicable HTTP/WebSocket authentication paths. Include cookie and bearer use. Define treatment of existing tokens without session IDs and distinguish logging out this session from logging out all devices. Never store raw tokens in logs. Cookie clearing remains necessary but insufficient for the intended contract.

**Tests:** token works before logout and fails afterward; unrelated session remains valid; expired/invalid tokens rejected; cookie and bearer parity; reconnect/restart and cache failure semantics; active socket handling according to the documented policy. Review actual auth call sites before selecting the storage design.

### R12 — Correct source availability, world-state rebuilds, and outbox recovery

**Evidence:** P03 errors reported as zero; H05 thread resolution; outbox failures with Neo4j unavailable; unproven P02/P04 and G05.

**Files:** `tasks/email_sync.py`, `services/msgraph_service.py`, `services/world_state/reducer.py`, `services/daily_brief/day_layer.py` and compiler, `services/outbox_processor.py`, thread/notification services.

**Change:**

- Propagate source errors explicitly instead of returning empty lists that look like successful empty inboxes. Inspect both provider and task layers; merely incrementing a counter downstream cannot recover swallowed errors. Record last successful sync, current availability, and completeness. Preserve valid cached facts during outages and label stale reads.
- Test correction ordering with source version/time and ingestion sequence separately. The presence of a sequence guard alone does not prove old source data arriving later cannot win.
- Seed the actual daily-brief inputs and exceed the consolidation threshold for P04. Verify corrected facts replace superseded facts, effective day survives consolidation, and failed/empty model output preserves the prior valid summary. Do not change the threshold merely to make an empty fixture “work.”
- Separate an intentionally disabled graph dependency from an unexpected error. Defer with visible status/backoff, retain replayable events, and drain idempotently after recovery. Trace the second `NoneType.session` failure before assigning it the same cause.
- Resolving a thread withdraws its queued nudges and prevents stale source replay from reopening it unless genuinely new evidence warrants reopening. Preserve quiet-mode expiry and acknowledgment across clients.

**Tests:** source outage versus empty versus no new data; resync with corrected item; old event after new correction; duplicate delivery; brief rebuild after correction/midnight; Neo4j absent then restored; pending events survive restart; resolved thread never re-nudges from stale queued work.

### R13 — Repair response delivery, deadline behavior, and observability

**Evidence:** leaked untagged reasoning, empty replies in the original study, raw errors, incomplete K01, J15 stale read/stream cancellation, uncertain offer-time authorization.

**Files:** `services/chat_reasoning.py`, `services/chat_assembly.py`, `core/text_utils.py`, streaming/tool loop in `main_simple.py`, clients and transport tests.

**Change:**

- Capture sanitized final request/prompt identity and provider response field metadata in controlled reproductions. Determine whether leaked text came from `reasoning_content`, inline tags, ordinary content, continuation construction, or provider state. Do not publish private reasoning in debug artifacts.
- Keep reasoning and tool scaffolding out of both live SSE and persisted messages. Tagged filtering exists; extend only for demonstrated parser gaps. Untagged narration cannot be reliably fixed by deleting sentences that “sound like reasoning.” Repair the originating channel/template or use a bounded final-answer stage where necessary.
- If no visible answer survives, return a truthful receipt-based outcome or bounded recovery message. Do not re-execute tools to regenerate prose. Empty replies are not proven to be reasoning-budget exhaustion.
- Make deadline states explicit: queued, running, cancelled, committed, unknown. A deadline must not grant authority. Before a not-yet-started write, recheck authorization/cancellation and the operation budget; preserve any already-committed result. A consciously deferred authorized action needs a durable pending state, not a silent drop or automatic stale execution.
- Derive internal/provider timeouts from remaining turn budget. Avoid a 120-second “deadline” that only gets noticed after an 80-second call finishes. Preserve bounded synthesis time after useful tool results.
- Return stable, user-appropriate error codes/messages; keep SQL/internal details in correlated server logs. Add request/turn/operation/job IDs and gate decisions so authorization investigations do not depend on missing log lines.

**Tests:** split tags/provider chunks, empty final text, tagged/untagged reproduction, no hidden text in live stream or storage, malformed responses, timeout at each boundary, cancellation before dispatch/during effect/after commit, reconnect without duplicate mutation, two queued clients with one model slot, task status and receipts agree.

### R14 — Repair the original conversational experience

**Evidence:** conversation study case 19 troubleshooting, case 11 feelings narration, case 09 irrelevant calendar exposure and empty reply; functional transcripts with excess tool/error narration.

**Files:** `prompts/chat_system_prompt.py`, `services/personality_engine.py`, `services/context_router.py`, context selection/assembly and response delivery.

**Change:**

- Keep PC_BLOCK out of production. Its mixed warmth/flow results, failures on unwanted troubleshooting, and concentration of empty replies do not establish a safe improvement. Keep model settings fixed while evaluating one change at a time.
- Separate relevance from authorization. Casual/vulnerable turns should not receive unrelated calendar dumps, but should retain a brief, genuinely relevant callback when appropriate. Preserve explicit practical requests embedded in distress.
- Make response guidance concrete: react to the new thing David said; do not retell his feelings or entire message; offer troubleshooting when requested or clearly useful to the active task; allow brief acknowledgments and natural endings; ask a question only when it advances the exchange. Warmth must not mean excessive reassurance or invented familiarity.
- Use compact action evidence from R03 instead of raw tool recitations. Correctness should reduce conversational effort, not produce constant permission prompts or audit-log prose.
- Reconcile the six existing context-router test failures against intended product behavior. Restore a missing feature only when it is actually required; update stale tests only with a documented contract decision, never just to make the suite green.

**Acceptance:** a bounded paired set covering casual banter, vulnerable disclosure plus pleasantry, relevant callbacks, venting without requested advice, requested troubleshooting, short answers, topic changes, endings, and task→social transitions. Use fixed full conversations plus human/independent tester follow-ups, never the tested model playing David. Review every turn in both repeats, include losses, and let David blind-review representative pairs. Require no regression in action truthfulness, unsolicited advice, empties, or leakage. No claim of a universal best model setting from this evidence.

### R15 — Explicit capability backlog and previously unproven acceptance

These are separate from confirmed defect fixes. An honestly unsupported action should stay honestly unsupported until implemented and verified.

| Capability/gap | Proposed disposition |
|---|---|
| Calendar description edit and one-occurrence edit/cancel | Add explicit event-ID/version operations and recurrence-instance identity after R01/R02/R05. Verify series untouched and external synchronization where supported. |
| Food edit/delete and precise workout-set correction | Included in R02/R08 because basic correction workflows need them. |
| Email draft/send | Separate feature package after R01/R03/R11: editable drafts, exact recipients, explicit send authority, idempotent provider receipts, injection resistance. Graph read success does not demonstrate sending. |
| Template-free workout start | Product capability decision after repairing registered start_workout; keep distinct from the confirmed invocation bug. |
| PKG/Neo4j preference correction and expiry | Bring up an isolated graph fixture and run J04 plus G01/G02/K04/I05 assertions. Absence in the study is not proof of a production outage. |
| Location-triggered reminder | Add synthetic location crossings, jitter/dedup, ownership and expiry; test the real trigger worker. Creating a standing order alone does not cover this. |
| Browser/files/canvas and native voice/watch/device behavior | Run actual browser acceptance where available; manual native/provider cards for hardware. API-only results are not client acceptance. |
| Fleet/project positive paths | Seed a disposable reachable host and realistic project/commit state, then verify evidence distinctions; do not classify missing fixtures as missing product capability. |
| Races, queue saturation, compaction, brief rebuild | Controlled L1 fixtures first, one actual model generation at a time for L2. No need to fill a 262k window to test application compaction. |

## 5. Regression strategy: finite, evidence-driven

For each package:

1. Preserve a failing deterministic or integration reproduction before implementation. Use the real registry, schema, API and worker boundary involved; helper-only tests are insufficient for authorization and dispatch bugs.
2. Implement the smallest coherent fix and run adjacent positive/negative regressions. Extend existing tests where practical (`test_execution_boundary_authorization.py`, `test_chat_tool_loop.py`, `test_standing_order_dedup.py`, `test_research_single_flight.py`, workout/world-state tests, thinking/stream tests, and context-budget tests).
3. Run only the relevant real-model journeys through the actual authenticated endpoint, with fresh independent fixture users/state and both required repeats. Keep accumulated realistic history in separate stress cases so same-name distractors remain tested.
4. Inspect committed state and side effects, not only final prose. Preserve the original failure even if a later sample passes. Separate baseline, exploratory, adapted-stimulus, and post-fix evidence.
5. At integration, run all 16 journey definitions and all 100 catalog assertions at their appropriate level; mark partial/blocked/unsupported explicitly. Do not count an unrelated pass as coverage of a missing assertion.

A new repair-validation run gets its own manifest and explicitly agreed finite model/time allocation before generation. The historical study's remaining allowance is not silently reused. Deterministic work and this written plan do not require model generation.

No broad settings sweep or new simulator is necessary. Fault injection, controlled model outputs, fake clocks, stateful adapters, and real DB/Redis/workers should establish most contracts cheaply. Use independent timezone arithmetic, explicit units, and test-only secrets. Single model concurrency does not prevent testing API concurrency or scheduler races.

### Release gates by capability

- **Writes:** known unauthorized operations blocked at execution; authorized counterparts succeed; wrong-owner/target tests pass; request replay and correction have exact cardinality.
- **Time/delivery:** correct instant and display, no description crash, catch-up/retry/cancellation demonstrated with actual worker and sink, backlog policy verified.
- **Recall:** receipts survive new conversations/restarts/compaction; current reads reflect API and worker changes; skeptical challenge causes verification, not unsupported reversal.
- **Background work:** terminal redelivery is harmless, waiting work does not monopolize execution, cancellation works, one durable artifact is directly retrievable.
- **Conversation:** no empty/leaked replies in the required regression set; unwanted advice and paraphrase loops improve in full conversations without damaging functional behavior.
- **Whole-platform claim:** no outstanding P0/P1 in the claimed capability scope, and explicit client/provider limitations. A high pooled pass rate does not excuse a wrong-target write.

## 6. Data migrations and existing damage

Potential schema work: proposal/action identity, unique operation keys, edit revisions, delivery attempts/occurrences, explicit units, recipe-consumption snapshots, vector storage, session revocation. Reuse existing tables where the contract fits.

Use additive migrations first and preserve compatibility during rollout. Backfill only facts supported by existing provenance. Candidate repair previews should identify duplicates, suspect reminder timestamps, unknown workout units, misnamed lists, and stale jobs without altering them. Never merge/delete “duplicates” just because text matches: the study explicitly demonstrated legitimate same-text requests with distinct identities.

For note data loss, search revisions/backups only through an authorized data-recovery task; do not invent lost text from the model's memory. Historical recipe composition may be unrecoverable; record that limitation honestly.

## 7. Deployment and rollback

The backend is reported to use a live source bind mount with no reload. Restarting can activate all pending source changes, not only this repair. A process uptime is not a byte-for-byte deployment manifest; lazy imports and runtime reads also complicate the claim.

Before deployment:

1. Produce a complete candidate artifact from the preserved source checkpoint plus explicitly reviewed repairs. Review unrelated pending backend changes that would also become active.
2. Establish a recoverable artifact/configuration/schema baseline and test it in isolation. Do not label git HEAD, the current candidate copy, or an old image hidden beneath a bind mount as the exact running baseline without evidence.
3. Rehearse restore/roll-forward in the disposable environment. Prefer isolated immutable source artifacts for releases; ensure a bind mount cannot silently override the intended artifact.
4. Back up affected data and verify additive migration compatibility. Rollback restores code/config where safe; committed user actions are reconciled separately, not blindly reversed.
5. Prepare a concrete deployment diff, commands, smoke checks, and rollback procedure for David's review. This planning request does not authorize production restart, migration, or external actions.

After an approved release, smoke-test auth, chat read/write/recall, scheduler delivery, and a worker result using approved test data. Watch duplicate-operation, unauthorized-action, failed-delivery, unknown-outcome, and empty-response signals. Expand capability use only after its gates pass.

## 8. First implementation batch and final deliverables

Start with R00, then a bounded R01/R02 slice covering the reproduced standing-order, status/acknowledgment, wrong-target, and note-edit failures. In the next small changes, fix reminder description fallback, workout invocation contracts, timer normalization, and document fallback isolation while completing the broader contracts. Do not ship the small outage fixes as proof that authorization or personality is solved.

For every completed package deliver: exact changed files, source/schema identity, failing-before/passing-after evidence, relevant two-trial conversations, unresolved cases, and migration/deployment implications. Maintain a single repair status table keyed by R00–R15 and the companion finding map.

Completion means demonstrated improvement in the user's actual workflows, with remaining capability gaps named. It does not mean every study finding shares one cause, every test passed once, or Sara's personality was fixed by repairing the backend.

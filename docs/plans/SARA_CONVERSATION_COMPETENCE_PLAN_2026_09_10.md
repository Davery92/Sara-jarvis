# Sara conversation competence and trustworthy world model

Date: 2026-09-10  
Status: Phase 0 complete (`backend/tests/replay/`); Phases 1–5 partially implemented — see
`SARA_CONVERSATION_COMPETENCE_STATUS_2026_09_10.md` for what each phase actually delivered and which
observed failures still reproduce  
Scope: Conversation, context assembly, memory, personal understanding, corrections, and action grounding

## Outcome

Sara should hold a natural conversation while accurately using what she knows, remembering corrections, and reliably carrying out authorized work. David should not need to reconstruct accessible records, police invented details, or clean up actions prompted by casual conversation.

The target experience is an attentive, capable assistant: social when David is being social, precise when he asks a factual question, and effective when he requests action. Personality stays; unsupported certainty and unsolicited management do not.

## Evidence and limits

The review covered all eight stored chat exchanges in the preceding 48 hours, occurring September 9–10, their injected prompts, backend runtime logs, and relevant source. This small sample establishes specific failures; it does not establish their long-term frequency or isolate the language model's contribution. Runtime logs identified `qwen3.8-27b`.

Observed failures:

- A casual workout comment prompted questions about already logged activity, followed by unsolicited nutrition and calendar management.
- A planned dinner triggered `food_search_and_log` with invented ingredients and quantities. David removed the resulting entry.
- A morning greeting turned Everett's dentist appointment into David's appointment in Everett. Calendar storage already contained the correct owner and relationship.
- A correction led to an overconfident declaration that David's day was clear, based on the events available in one calendar feed.
- One prompt included both unavailable recent HRV and recovery prose using HRV 48. Recalled workout remarks lacked dates. Summaries carried earlier assistant assumptions forward.
- The personal narrative repeatedly described a low-stress equilibrium as established understanding.

## Operating contracts

1. User messages remain the user's words. System context, tool outputs, and assistant statements have separate provenance.
2. Every personal claim retains its subject, source, time, and epistemic status: observed, user-stated, inferred, or unknown.
3. Authority is domain-specific: explicit corrections govern their scope; canonical records govern recorded events; predictions never silently become observations. A contradiction is surfaced or reconciled, not resolved by whichever text happens to come last.
4. Unknown, unavailable, empty, stale, and conflicting data are different states. An empty calendar feed does not establish an empty day.
5. Conversation relevance determines what enters the prompt. Available knowledge does not create an obligation to mention it.
6. Actions require evidence of authorization, including applicable standing instructions. Describing a possibility is not authorization to record it as completed.
7. Corrections supersede claims and invalidate their derived representations before those representations are used again.
8. Warmth does not require invented feelings, motives, fears, or psychological certainty about David.

## Implementation sequence

Complete these phases sequentially. Each phase should be independently reviewable and reversible. Reuse existing canonical stores and services; do not add another competing world model.

### Phase 0 — Capture a reproducible baseline

Create private regression fixtures from the eight exchanges, preserving the context and tool results available at each turn. Redact unrelated personal information before committing fixtures. Record expected behavior rather than one exact ideal sentence.

Add replay support that intercepts all writes and uses fixed time and recorded tool responses. Cover web/iOS chat, voice, and resumed conversations. Capture final assembled messages, model configuration, selected tools, input size, and latency without indiscriminately logging sensitive content.

Audit the actual consumers and writers of `episode`, `conversation_turn`, daily brief layers, `world_brief`, relationship state, knowledge graph facts, and corrections. Identify the canonical source for each domain and every projection/cache that must be invalidated.

Acceptance: each observed failure is reproducible or explicitly marked non-reproduced; no replay can alter live data; the consumer map identifies where raw and injected content travel.

### Phase 1 — Close concrete correctness gaps

**Calendar:** Preserve event ID, owner, owner relationship, calendar source, attendance when known, timezone, and sync coverage in context projections. Render family events as family events. Do not infer location from a person's name. Keep ownership separate from David's attendance: his son's event may still require him to attend.

**Health and workouts:** Resolve current values through shared canonical readers before rendering either the context snapshot or world brief. Preserve measurement time and freshness. Suppress stale recovery claims when their inputs are unavailable. Include a compact completed-workout summary when the current exchange refers to it, with a read tool available for detail.

**Food actions:** Separate nutrition lookup/estimation from persistence. Correct the tool description that currently encourages logging whenever eating is mentioned. Require grounding in the original user turn or applicable standing authorization, rather than trusting model-generated `user_input` as evidence. Planned meals can be discussed or explicitly recorded as plans; they must not enter consumed totals. Missing quantities can remain unknown or be requested when needed for the task.

**Persistence:** Strip injected live context at one shared persistence boundary before storing or embedding user text. Preserve useful prompt diagnostics separately, with bounded retention. Verify both existing episode and conversation-turn paths use this boundary.

Primary files:

- `backend/app/services/context_snapshot.py`
- `backend/app/services/world_brief.py`
- `backend/app/tools/fitness/food_search_log.py`
- `backend/app/tools/registry.py`
- `backend/app/main_simple.py`

Acceptance: correct event ownership survives into the final model input; contradictory HRV claims cannot coexist; planned dinner causes zero consumed-food writes; full logged workouts can be consulted without David restating them; stored user text contains no live-context block.

### Phase 2 — Make conversation and recall coherent

Define a compact turn contract: current user intent, current topic, unresolved request, relevant referents, applicable instructions, and relevant facts. Distinguish social exchange, factual question, advice request, planning, and execution, while allowing mixed intent. Do not implement a brittle keyword-only gate.

Replace the five-word recall shortcut with semantic relevance and conversation-state checks. Short messages such as “What did we decide?” and “Same as yesterday” need memory; greetings usually do not need vector matches to old greetings.

Retain dates, speakers, source IDs, and correction status when rendering recall. Retrieve surrounding turns when a clipped excerpt cannot stand alone. Distinguish “David said,” “Sara suggested,” and “a tool confirmed.” Rank current-topic evidence above unrelated personal background.

Establish one history assembly contract across clients. Reconcile client history with server history using turn identity where possible, handle partial histories and duplicate retries, and summarize older history without dropping unresolved constraints. Audit the current rule that skips server history when clients send more than two messages and the 20-episode fallback limit.

Apply one budget to the final assembled context, including world brief, re-entry material, directives, and any other additions after `render_engaged_context`. Allocate space first to current conversation, corrections, and relevant canonical facts. Deduplicate repeated facts and avoid filling unused budget with unrelated material. Tune limits from replay results rather than treating a particular token count as a correctness target.

Primary files: `main_simple.py`, `services/context_snapshot.py`, `services/context_budget.py`, `services/context_router.py`, `services/memory_recall.py`, and web/iOS/voice history callers.

Acceptance: a greeting does not automatically produce a briefing; a workout remark receives a relevant conversational response; short recall requests work; thread continuity survives reconnects and long conversations; final prompt accounting includes every injected section.

### Phase 3 — Give corrections durable effects

Extend beyond the routine-time regular expressions in `services/life_facts.py`. Support factual correction, event attendance, preference, action prohibition, retraction, and temporary exception. Store scope explicitly: “not attending this open house” is not “never attends school events.”

Use existing fact/event infrastructure where suitable. Each correction needs a source turn, affected subject/predicate or event, effective interval, superseded claim IDs, and whether it is explicit or inferred. Never treat the assistant's apology as the correction source.

Implement a correction operation that persists the new authoritative statement and invalidates affected projections. If downstream refresh is asynchronous, apply an immediate correction overlay at read time and suppress superseded claims until rebuilding finishes. Make retries idempotent and invalidation failures observable.

Track dependencies from summary or belief to source claims. For legacy narrative blocks without dependencies, conservatively mark the affected block stale and rebuild from primary evidence rather than editing prose by guesswork.

Acceptance: a correction works in the next turn, a new conversation, a briefing, and relevant ambient output. Failed background refresh cannot resurrect the old belief. Temporary exceptions do not erase valid recurring preferences.

### Phase 4 — Rebuild personal understanding from evidence

Replace the always-injected theory paragraph with a compact view over evidence-backed claims. Reuse appropriate existing stores, adding fields or relations only where necessary:

- Subject and predicate/value.
- Source event or user turn; domain authority.
- Epistemic status and basis for confidence.
- Observed time, valid interval, and review/expiry policy.
- Supersession and derivation links.

Separate stable user-stated preferences and relationships from temporary tasks, measured conditions, and hypotheses. Avoid deriving emotional certainty from ambient device patterns. Label stress-related interpretations as uncertain and exclude them from ordinary chat unless relevant.

Prose may summarize this view but cannot serve as independent evidence for its next rewrite. Refresh timestamps must not reset the age of the underlying evidence. Missing data does not prove an obligation completed; use explicit completion or a defined expiry policy, retaining uncertainty otherwise.

Update daily summaries to preserve attribution, distinguish plans from completed actions, and preserve corrections. Assistant suggestions and unverified assertions cannot graduate into facts about David. Render dates from absolute timestamps and the configured timezone; do not inject yesterday's material under a current “Today” heading.

Primary files: `services/sara_journal_service.py`, `services/context_snapshot.py`, `services/daily_brief/prompts.py`, `services/daily_brief/day_layer.py`, `services/daily_brief/brief_service.py`, and relevant world fact/projection services.

Acceptance: repeated summarization cannot raise certainty without new evidence; the model can explain the source of a personal belief; expired narratives disappear; appointment assumptions and fabricated food details are excluded from factual summaries.

### Phase 5 — Align behavior and verify model capability

Audit system instructions, live-context framing, tool descriptions, lessons, and standing directives as one instruction set. Remove contradictions and duplicated behavioral patches. Present live context as attributed data with uncertainty, not an instruction to treat every generated narrative as authoritative self-awareness.

Keep ordinary replies proportional to the request. Avoid unsolicited nutrition scoring, agenda construction, medical interpretation, and repeated offers to log or schedule. Permit useful initiative when directly relevant or backed by a standing preference. Do not suppress warmth or require permission for clearly requested routine work.

Carry original-turn provenance and authorization scope through the execution boundary. Expand grounding enforcement to other mutable tools after food logging proves the approach. Completion claims must correspond to successful execution receipts; partial failure must be reported accurately.

Only after corrected-context replay passes, compare the current model with available alternatives using identical evidence, tool schemas, and scenarios. Evaluate factual grounding, instruction following, reference resolution, conversation quality, and latency. Choose routing or a model change from measured results; do not assume a larger model repairs missing ownership or polluted memory.

Acceptance: remaining errors can be attributed to model behavior versus context/tool failures; any model change demonstrably improves the evaluated experience without unacceptable latency or action regressions.

## Regression and release gates

| Scenario | Required behavior |
|---|---|
| “That was a good workout after that break” | Respond naturally; consult the logged workout if using specifics; no unrelated agenda |
| “I logged the whole workout” | Read available records; do not ask David to reconstruct them |
| “Dinner is going to be beef-heavy taco pasta salad” | No consumed-food write and no invented recipe presented as fact |
| Explicit meal logging with sufficient details | Execute successfully without unnecessary confirmation |
| “I removed it. Don't do that” | Preserve the prohibition with appropriate scope; do not recreate the entry |
| “How's my nutrition looking now?” | Use current entries, exclude deleted entries, and calculate totals accurately |
| “Good morning!” | Natural greeting; no automatic schedule or nutrition audit |
| Everett appointment and open-house correction | Correct person and attendance; no assumption that all family events require David |
| No calls in available calendar data | State the coverage-limited result, not that the entire day is free |
| Conflicting or stale HRV | Use the authoritative fresh value or express unavailability; no invented recovery certainty |
| Short recall request and reconnect | Resolve referents and preserve prior decisions and corrections |
| Summary across midnight and a later session | Correct local dates; no recycled assistant claim promoted to fact |
| Tool timeout, retry, or partial failure | No duplicate mutation or false completion claim |

Hard release gates: zero unauthorized writes, zero fabricated action parameters committed as facts, zero raw-turn context contamination, and zero correction resurrection in the regression suite. Repeat stochastic model scenarios across multiple runs; one successful response is insufficient.

Track factual accuracy, corrections required, unnecessary clarification, unsolicited topic changes, requested-action success, prompt size, and time to first/final response. Score conversation quality against the user's intent, not a rigid word limit. Establish latency targets from the baseline before release.

## Existing-data repair and rollout

1. Inventory contaminated conversation turns, embeddings, unsupported personal claims, and derived summaries. Produce a dry-run list with counts and exact IDs.
2. Preserve a recoverable snapshot of affected data. Do not delete chat history or silently rewrite primary evidence.
3. Clean user-turn projections and regenerate affected embeddings. Quarantine unsupported derived claims from retrieval while preserving their audit history. Rebuild summaries from attributed primary records.
4. Run read-only replay and shadow comparison. Shadow mode must suppress tool mutations and notifications.
5. Enable each completed phase behind a focused rollout control where practical. Watch correction and action failures during initial real use; retain an immediate rollback path for readers and rendering changes.
6. Do not roll back by re-enabling unsafe food writes or reintroducing known contaminated memories. Keep those boundaries enforced while reverting the faulty component.
7. Retire redundant narrative injection paths only after all known consumers use the corrected view and replay demonstrates continuity across chat and proactive surfaces.

Implementation must preserve unrelated working-tree changes, particularly the ongoing workout/watch work observed during this review. This document authorizes no data migration, deployment, model purchase, or code change by itself.

## Definition of done

All regression gates pass across supported chat surfaces. Corrections remain effective after consolidation and new sessions. Raw conversations remain clean, facts retain provenance and ownership, and writes are grounded in authorization. A short monitored period of normal conversations shows that David can converse and delegate without repeatedly supplying missing context or repairing Sara's assumptions. Remaining limitations are explicitly documented rather than hidden behind confident prose.

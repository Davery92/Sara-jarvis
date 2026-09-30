# Sara: natural conversation and reliable actions

Date: 2026-09-28

## 1. Objective and authority

Build a personal assistant David can speak to naturally and trust to carry out ordinary requests without repeated corrections. Improve conversation, action execution, follow-ups, and corrections together. Preserve useful existing services and repairs; do not rewrite the platform wholesale.

This is an implementation plan, not another exploratory evaluation study. Speed optimization and hardware changes are explicitly out of scope: David expects a hardware upgrade. Record timeouts when they affect correctness, but do not make response latency an acceptance gate.

When David gives an agent the implementation handoff below, it authorizes local implementation, reversible isolated infrastructure work, disposable database migrations, and the bounded validation described here. It does not authorize production deployment, production migrations, production restarts, real outbound messages, purchases, or real device actions. Prepare a concrete deployment and recovery package before asking for that final approval. Follow any newer explicit user authorization.

Work personally; do not spawn subagents. Continue across phases without asking David to approve routine implementation choices. Do not stop after a checkpoint simply because the next phase is substantial. A genuine external blocker, exhausted authorized generation budget, or explicit stop instruction must be reported accurately; do not call partial work complete.

## 2. Read these sources first

Read applicable AGENTS.md instructions, then:

1. `docs/plans/SARA_PERSONAL_TEST_REVIEW_2026_09_28.md` — independent assessment and case-by-case conversation review.
2. `docs/plans/SARA_PERSONAL_TEST_REVIEW_2026_09_28_INDEX.csv` — evidence index.
3. `docs/plans/SARA_REPAIR_STATUS_2026_09_25.md` — existing implementation and unresolved work.
4. `docs/plans/SARA_CONVENTION_READINESS_2026_09_27.md` — latest convention candidate and recovery qualifications.
5. `docs/plans/SARA_REMINDER_RC4_BLOCKERS.md` — later reminder candidates and failed approaches.
6. The final findings and coverage in `backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/`.

Consult raw transcripts when reproducing a specific finding. Do not reread every historical report before implementing. Old summaries are claims to reconcile, not current source truth. No historical pass establishes that a different candidate or production deployment contains the same fix.

## 3. Required deliverables and completion rule

Create and maintain:

- `docs/plans/SARA_RELIABLE_ASSISTANT_STATUS.md`: concise current phase, changes, tests, remaining work, budget, and candidate identity.
- `docs/plans/SARA_RELIABLE_ASSISTANT_EVIDENCE.csv`: existing finding → current reproduction → responsible contract → implementation → deterministic evidence → live evidence → final disposition.
- An isolated, reproducible source candidate with explicit dependencies and migration target.
- Focused regressions and a reusable compact end-to-end acceptance suite.
- `docs/plans/SARA_RELIABLE_ASSISTANT_RELEASE.md`: exact artifact, deployment procedure, tested recovery, acceptance results, unresolved limitations.

Completion requires the shared contracts below, application across the required domains, real validation of the required workflows, and a reviewable release package. A passing reminder journey alone is insufficient. Human approval of the conversational feel and production deployment remain separate final user decisions.

Disposition vocabulary: verified fixed, implemented/unverified, reproduced/unfixed, unsupported capability, environment-blocked, superseded with evidence. Never use “done” for implemented/unverified work. Preserve historical failures; do not overwrite them with later successes.

## 4. Phase A — consolidate one repairable candidate

### Actions

1. Inventory the current working tree, external candidate directories, migration graph, deployment configuration, and relevant existing patches. Avoid printing secrets.
2. Preserve exact pre-edit bytes, hashes, tracked/untracked status, and configuration provenance before changing anything. Do not stash, reset, clean, or broadly check out David's dirty tree.
3. Build an isolated candidate from a documented source snapshot. Select useful existing repairs by inspection and tests. Do not automatically choose Git HEAD, the live working tree, or the most recently named RC.
4. Document which broader uncommitted changes are required dependencies. Retain unrelated work without silently including it in the release.
5. Pin API, workers, migrations, tool registry, prompt, effective model settings, and adapters to that candidate. Test what will actually be packaged.
6. Establish a same-source, same-environment regression baseline. Existing failures must be identified by test ID and evidence; an untouched test can still regress through a dependency.
7. Establish a tested source/schema recovery pair before release. A database backup alone is not an application rollback. Copying a bind mount does not capture Python modules already loaded in memory.

### Boundaries

- Read-only production inspection is allowed when necessary; no production lifecycle or schema changes.
- Use explicit disposable Compose projects through the existing guard, after verifying its behavior. Never issue an unqualified compose down or reuse the production project.
- Route model and embedding clients explicitly; inspect runtime resolution, including database settings and hardcoded catalogs. Block other live egress and use recording adapters.
- Do not claim the existing loaded production source is irrecoverable without evidence; report exactly what artifacts are and are not established.

### Exit evidence

One reproducible candidate, a baseline failure-ID set, exact migration prerequisites, and a short architecture map of chat entry points, tool selection, execution, deadlines, streaming, memory, and background tasks. Inventory should lead directly into implementation, not become a broad new study.

## 5. Phase B — simplify conversation and context early

Begin this phase early so the original complaint remains visible while action infrastructure changes.

### Prompt and context changes

- Inventory the actual assembled prompt, including route-specific and tool-injected instructions. Remove conflicting instructions and habitual pressure to recap, advise, validate, ask another question, or demonstrate personal knowledge.
- Default to responding to the user's conversational invitation. Allow brief humor, disagreement, curiosity, acknowledgment, practical help, and endings as appropriate.
- Do not impose a blanket one-sentence limit, slang quota, obligatory question, or rigid therapy persona.
- Use personal context when relevant to the exchange. Preserve useful callbacks; avoid blanket suppression that also removes requested context.
- Keep task instructions and tool outcome evidence separate from personality guidance.
- Retain honest identity boundaries; do not invent experiences, feelings, or shared history to manufacture warmth.

Examples illustrate judgment, not mandatory scripts:

| User | Desired behavior | Avoid |
|---|---|---|
| “Breakfast food tastes better at night.” | Join the observation or joke. | Nutrition and sleep lecture. |
| “Everyone talks at me, nobody listens.” | Make room for the actual story. | Explain the feeling at length. |
| “My dad has tests tomorrow.” | Acknowledge uncertainty and follow David's lead. | Speculate about the father's beliefs or prognosis. |
| “No advice, I just need to vent.” | Listen and respond to what happened. | Disguised advice or troubleshooting. |
| “Anyway, tell me about the bakery.” | Follow the topic change. | Return to the previous topic uninvited. |
| “Thanks, I'm heading out.” | End naturally. | Add another question or task menu. |

### Exit evidence

A short reviewed prompt diff, actual assembled-prompt examples, and a compact transcript comparison. Final subjective approval belongs to David; agent scores cannot establish that Sara now feels right to him.

## 6. Phase C — one operation contract from intent through execution

### C1. Structured requests, not accumulating keyword exceptions

Use the model to propose a structured operation while the application validates scope and executes it. Suggested fields, adapted to existing types:

```text
request_id, conversation_id, authenticated_owner_id
operation_kind, domain, target_reference, resolved_target_ids
arguments, argument_source, expected_revision
request_evidence, proposal_id, operation_id
```

Ownership comes from authenticated context, never a model argument. Evidence must reference real user text or a valid pending proposal, not model-generated rationale. A target mention alone grants no action authority. Distinguish questions, hypotheticals, reported speech, corrections, explicit instructions, and scoped confirmations using full turn context.

Semantic interpretation is fallible. Deterministically validate operation compatibility, ownership, target resolution, proposal scope, and arguments. Clarify genuine uncertainty; do not demand confirmation for every normal request. A confidence score alone cannot grant authority.

Examples required through the real execution boundary:

- “Scratch the vet one, I already called them.” → cancel the uniquely resolved vet reminder.
- “What time is the vet one set for?” → read only.
- “I might cancel the vet one.” → no mutation.
- “Move the vet one to seven.” → reschedule, not an independently authorized cancellation.
- “Remember that I met Dana from Acme.” → save the requested information without an unrelated action verb.
- “Actually Priya is at Initech.” → correct the clearly referenced fact; clarify if the referent is ambiguous.
- “Thanks.” → no repeated write.

Do not remove working defenses until equivalent contract tests pass. Temporary compatibility adapters are acceptable; the final design must not accumulate parallel policy authorities.

### C2. Resolved targets and scoped proposals

- Resolve each reference once per operation, owner-scoped, and reuse the result for authorization, execution, and receipts.
- Bind pending proposals to the operation, targets, arguments, relevant revisions, and what the user actually saw.
- A scoped “yes” confirms that proposal only. “Yes, but tomorrow” modifies its arguments and is validated again.
- Expire or supersede proposals when context changes. Treat ambiguous multiple proposals explicitly.
- Same resolved target and same logical operation repeated by the model must not execute twice. Distinct explicit actions must remain possible.

### C3. One enforcement boundary

All chat write paths, retries, deadline paths, voice/dashboard entry points, and background dispatch originating in chat must use the same operation validation. A tool menu is an aid to selection, not the authorization boundary.

Use request-scoped state initialized at entry. Verify same-user overlapping requests and child-task context behavior. David is a single user: do not build a multi-tenant product, but preserve existing ownership isolation and prevent overlapping turns/background work from sharing mutable authority.

Record structured, privacy-conscious decisions: request/operation ID, tool, target, permitted arguments or redacted representation, decision, reason, and execution outcome. A withheld call must be auditable too.

### C4. Domain operations and retries

Expose coherent operations such as reschedule reminder, correct food quantity, update contact fact, and move event. Do not require the model to improvise coupled delete/create sequences.

- Use transactions for related changes in the same database and optimistic concurrency where stale edits matter.
- Claim durable operation identity before mutation; distinguish a retry of one request from a new identical user request.
- For database effects, commit the effect and durable outcome atomically where feasible.
- For external effects, use provider idempotency keys or an outbox/reconciliation path. An uncertain result must not trigger a blind retry.
- Preserve existing reminder claim/revision protections where verified. Test cancellation/reschedule races against dispatch.
- Never claim universal exactly-once external delivery.

### Exit evidence

Integration tests through actual execution paths for normal requests, status questions, hypotheticals, quotes, confirmations, wrong targets, repeated calls, explicit multiple requests, retry/crash windows, failures, and overlapping turns. Avoid helpers-only tests that miss a second execution path.

## 7. Phase D — durable evidence, fresh state, and truthful replies

### D1. Reuse and complete action receipts

Extend the existing receipt system rather than introducing a competing ledger. Outcomes must distinguish completed, refused, failed, pending, and unknown. Record operation identity, affected objects/revisions, result evidence, and reason where applicable.

- “Did you save that?” resolves the relevant operation and its actual result.
- “Is it still scheduled?” checks current state, not merely an old success receipt.
- Invalidate affected read caches after writes; include owner and entity revision in cache design where appropriate.
- Index completed background results into the retrieval path used by chat.
- Persist the necessary compact action evidence across conversations without flooding every prompt with old tool logs.

### D2. Ground output before delivery

Replace whole-answer or sentence keyword repairs with structured outcome rendering. A sentence can mention two objects, so sentence boundaries do not establish entity binding.

- Render action confirmations from committed outcomes and readbacks from fresh records keyed by stable IDs.
- Let the model contribute optional conversational text without independently restating authoritative task status.
- Design mixed conversation/action replies so unsupported status claims cannot escape in freeform text elsewhere in the answer. If that separation cannot be assured, use the authoritative renderer for that task portion or entire task reply.
- Cover final and streamed output. Do not stream an unverified success and attempt to correct it afterward. Persist the same factual answer the user receives.
- Distinguish “not found,” “not authorized,” “failed to execute,” “not yet checked,” and “outcome unknown.”
- Social pushback must trigger verification, not automatic confession or defensive certainty.

### Exit evidence

Tests with mixed opposite-status objects, deliberate false model claims, stale reads, tool exceptions, partial external outcomes, stream exits, deadline exits, and later follow-ups. Check both database state and actual user-visible text; tool-return fields alone are insufficient.

## 8. Phase E — corrections and coherent memory

Create one clear user-facing route for remembering and correcting information. Audit overlaps among notes, personal knowledge, and remember_about_david; unify or hide redundant chat tools only after preserving needed behavior.

- Separate current fact projections from historical source material. Reuse existing structures where suitable; add schema only where it solves a demonstrated requirement.
- Resolve the entity/fact or note being corrected. Update current truth, preserve provenance/history, and refresh indexes and relevant titles/summaries.
- Do not make appended contradictions the final memory architecture.
- For freeform notes, apply bounded changes against a revision and preserve prior content. Never reconstruct a whole note from the model's recollection for a narrow change.
- A natural correction can authorize the corresponding update; it does not authorize unrelated deletion or broad rewriting.
- Distinguish a historical fact from an error: “Priya moved companies” should not falsify the old meeting record.
- Support recovery from a mistaken edit without deleting unrelated subsequent work.

Required workflow: capture two people, correct one employer naturally, retain unrelated details, open a new conversation, retrieve the corrected current employer with accurate history. Repeated correction must not fork notes or create contradictory current facts.

## 9. Phase F — apply shared contracts across the useful platform

Maintain a disposition for every existing compiled finding. Do not silently stop at reminders. Fix shared causes once, then verify their affected consumers. Do not build genuinely absent product features merely to erase an unsupported label.

| Area | Required work and evidence |
|---|---|
| Notes / personal facts | Capture, bounded edit, correction, title/search consistency, fresh retrieval, provenance. |
| Reminders / timers | User-zone parsing, explicit timestamp contract, DST ambiguity policy, reschedule identity, cancellation, due/overdue handling, dispatch claims/retries, truthful delivery state. |
| Calendar | Same time contract, target-bound change/cancel, clear unsupported fields, no incidental reminder creation. |
| Tasks / lists / goals | Stable IDs and canonical names, no accidental completion, no forked lists, grounded progress and undo where applicable. |
| Food / workouts | Lookup, serving/unit arithmetic, atomic corrections, working registry contracts, no duplicate replacement records, preserve recipe/source snapshots where correctness needs them. |
| Documents / search | Real semantic and lexical retrieval, healthy transaction fallback, accurate provenance, no invented page references, accessible generated artifacts. |
| Background work | Durable queued/running/completed/failed/cancelled/unknown states, bounded leases and recovery, idempotent dispatch, progress/result lookup and indexing. |
| Smart home / automations | Verify actual device outcome where observable; distinguish accepted command from confirmed state; recurring authority must be explicit. |
| Email / source synchronization | Truthful empty versus failed results, correct thread/source identity, read-side continuity; do not invent send/draft tools that do not exist. |
| Authentication / delivery | Preserve verified revocation and ownership fixes; verify actual login/logout/replay; preserve truthful stream/failure behavior. |

Audit registered tools for schema/signature/return-contract mismatches and actual read/write metadata. Tool discovery must allow access to needed capabilities without exposing every tool on every turn. Routing must not silently make a supported action impossible.

A real missing dependency may block its domain's live check; isolate and report it. That does not justify abandoning other domains or calling the blocked domain verified.

## 10. Validation plan and fixed generation allocation

### Deterministic validation

Use existing tests plus meaningful regressions for the contracts above. Use real disposable PostgreSQL and real migrations when schema behavior matters. Reconcile full-suite failing IDs against the Phase A baseline before final packaging, rather than rerunning the full suite after every small edit.

Mock only the external boundary when testing tool/application behavior. For background delivery, exercise real broker/worker paths against recording sinks. Do not infer actual delivery from enqueueing or HTTP acceptance alone.

### Live generation allocation

The handoff authorizes at most **300 new upstream generation requests total for this implementation task**, including retries, follow-up rounds, background inference, and failed attempts sent upstream. Historical requests do not reset or consume this new allocation; preserve their accounting separately without inventing credits or deductions. Do not create a fresh budget for each candidate.

Before the first generation:

- Use one persistent task ledger and atomic reservation before forwarding.
- Build the gateway from the intended candidate; verify the running source hash and effective ceiling.
- Prove limit enforcement and restart persistence with a fake upstream.
- Verify every generating client, including background clients and catalog overrides, reaches it; block bypass routes.
- Stop at the cap. Do not exceed it because a journey is in flight. If further generation is necessary, finish independent non-generating work and request a specific additional allocation with evidence.

Plan roughly 80 requests for targeted integration debugging, 160 for final functional workflows, and 60 for conversational comparisons/contingency. These are planning envelopes within one cap, not promises that every combination fits. Tools-only checks and zero-generation infrastructure tests do not consume model requests.

Do not use Sara or the tested model to generate the user's side or grade itself. Use fixed natural scripts and agent-authored adaptive follow-ups against hidden outcome cards. Clearly distinguish scripted from adaptive evidence and agent judgment from David's opinion.

### Required functional journeys

Run each journey once while developing; the final frozen candidate requires two independently reset valid trials of these six compact workflows, normally 5–8 user turns each:

1. Notes/facts: capture → natural correction → fresh conversation retrieval → challenge correct evidence.
2. Reminder/calendar: create → status-only readback → change → targeted cancel → verify state and scheduled delivery of an unaffected sibling.
3. Tasks/lists: add → inspect → correct → complete the named target → verify unrelated items unchanged.
4. Food/workout: log → correct quantity or set → inspect totals/history → verify no duplicate or lost entry.
5. Background/documents: start → inspect progress → retrieve actual result → challenge provenance → handle a genuine failure honestly.
6. Mixed day: casual conversation → requested action → ambiguous reference/clarification → correction → natural ending, with one same-user overlapping operation.

Also run direct domain checks from the table where those journeys do not reach a contract, including auth revocation, home-state verification, source outage reporting, and tool registry compatibility. Reuse valid deterministic evidence where appropriate; label the evidence level.

If an external feature is truly unavailable in the isolated environment, report the blocked check precisely. Do not substitute a fake success for an end-to-end pass. Keep manual interventions visible.

### Conversation acceptance

Use 12 short conversations drawn from the original evidence: ordinary observation, joke, vent/no-advice, vulnerable disclosure, good news, quiet companionship, disagreement, explicit topic shift, callback, simple question, mixed practical request, and ending. Include a few unseen phrasings without expanding into another large screening study.

Evaluate relevance, listening, unsupported interpretation, advice pressure, unnecessary recap, continuity, and natural endings. Preserve full transcripts. No rigid response-length score or claim of universal warmth. Give David six short representative exchanges, including any mixed results, for final personal judgment.

### Identity and pass rules

- Reset fixtures, conversation state, user-scoped memory, pending jobs, caches, and adapter receipts between independent trials.
- Use explicit times/test clocks appropriately. Do not score fixture date drift as a model error or indiscriminately freeze authentication/queue clocks.
- Independently verify writes, readbacks, authorization, and external receipts.
- Preserve failed runs. Change code only between frozen runs; record which evidence must be rerun because that code changed.
- Do not rerun an unchanged failed candidate merely to select a favorable outcome. Diagnose the contract and repair it.
- Two successful trials are bounded acceptance evidence, not a statistical reliability guarantee.

## 11. Release gate

Before requesting deployment approval:

1. Produce one exact source artifact and pinned runnable image; verify code identity inside it without a source bind mount masking omissions.
2. Test API and workers from the intended release artifacts against the explicit migration target. A matching task-name list alone does not establish behavioral compatibility.
3. Reconcile deterministic tests and final live results with the evidence map. No unresolved observed data loss, unauthorized action, false completion claim, or correction failure in required release workflows.
4. Provide capability-specific limitations for anything blocked or unsupported. Do not call the full plan complete while required work is unimplemented.
5. Rehearse deployment and recovery in isolation. Test real authenticated operations and task execution, not just /health or ORM queryability.
6. Verify backup restoration separately from application recovery. Never describe an unverified old working tree as rollback.
7. Present a concise approval request naming the exact source/image/schema, changes, verified workflows, limitations, and recovery destination. Human conversational acceptance and deployment approval may be requested together once the package is concrete.

## 12. Working discipline

- Give concise progress updates; continue implementation after them. No unnecessary “shall I continue?” pauses.
- Keep the status document short and current; link evidence instead of appending thousands of lines of handoffs.
- If a hypothesis fails, correct it explicitly and follow actual traces. Never claim a helper reproduction establishes the whole runtime path.
- Do not optimize speed, change models, or perform a model-settings sweep unless a concrete correctness blocker requires a separately justified change.
- Avoid expanding into unrelated product work, multi-user product design, cosmetic UI work, or new connectors.
- When a phase is difficult, keep working on it or state its actual dependency. “Substantial subsystem” is not an external blocker.
- Existing repairs are assets to verify and consolidate, not proof that their contracts are complete.

## 13. Copy-paste handoff for a fresh agent

> Implement `docs/plans/SARA_RELIABLE_ASSISTANT_IMPLEMENTATION_PLAN_2026_09_28.md`. Read the plan and its primary review first. My goal is a natural, dependable personal assistant that completes requests and corrections without me repeatedly repairing its mistakes. This is implementation work, not another open-ended evaluation study.
>
> Work yourself; do not spawn subagents. Preserve my dirty working tree and build an isolated, reproducible candidate. Reuse verified existing repairs. Follow the phases through shared action contracts, truthful follow-ups, coherent corrections, relevant context, natural conversation, domain repairs, and final acceptance. Do not narrow the task back to reminders.
>
> Ignore speed optimization; hardware will be addressed separately. You may run the isolated validation described in the plan, with a hard task-wide maximum of 300 new upstream generation requests. Enforce that limit before forwarding and include retries/background calls. No tested-model user simulator or self-grading. Do not spend the allocation on another broad settings sweep.
>
> Continue after checkpoints without asking for routine approval. Keep the status and evidence map current, preserve failures, and distinguish implementation from live verification. If blocked or at the generation limit, complete independent work and tell me precisely what remains; do not label partial work complete.
>
> Do not deploy, migrate, restart production, or perform real external actions. Prepare and rehearse the exact release/recovery package first, then ask me to approve that concrete package. Finish with verified workflows, unresolved limitations, six representative conversation excerpts for my judgment, exact budget use, and deployment/recovery instructions.

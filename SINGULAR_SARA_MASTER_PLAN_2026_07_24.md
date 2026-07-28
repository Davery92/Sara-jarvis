# Singular Sara Master Plan

**Date:** 2026-07-24  
**Status:** Proposed for review  
**Scope:** Backend cognition, memory, autonomy, VM execution, delivery, web, and iOS  
**Branch rule:** Product/runtime changes and UI changes are implemented on separate branches

## 1. Product Objective

The goal is not to make every subsystem more intelligent in isolation. The goal is for David to experience one Sara:

- one identity whether she is chatting, thinking in the background, doing research, operating the VM, or speaking through a notification;
- one continuous understanding of David, herself, the current situation, and unfinished work;
- one set of priorities that includes David's commitments and Sara's own interests;
- one memory interface with visible provenance and uncertainty;
- one attention policy deciding whether to stay quiet, update a surface, ask, or interrupt;
- one action system that can explain what it did, what happened, and what can be undone;
- one honest internal state, projected consistently to web and iOS;
- one durable life across conversations and restarts.

This plan does not claim machine sentience. It targets the properties that make an assistant feel like a coherent, persistent agent: continuity, self-model, memory, initiative, reflection, bounded agency, curiosity, and honest awareness of its own condition.

## 2. Definition of Done

Sara is singular when all of the following are true:

1. Chat, background thought, reflection, and focused work enter the same kernel.
2. The ACS daemon no longer owns a separate identity prompt, priorities, memory selection, or speech path.
3. Every cognitive turn receives context from one context assembler and recalls through one recall API.
4. Every commitment, interest, goal, mission, and waiting item is represented in one intent graph.
5. Every user-facing proactive message passes through one attention decision and one voice composer.
6. Every material action passes through one executor and creates a truthful receipt in one ledger.
7. The VM remains Sara's durable workshop and execution body, but is not a second brain.
8. Web and iOS show projections of the same state rather than assembling their own competing interpretations.
9. No success state can be displayed when the underlying operation failed or only partially completed.
10. Old paths are removed after measured parity, not merely hidden behind new names.

Primary system invariants:

| Invariant | Target |
|---|---:|
| identity authorities | 1 |
| kernel entry surfaces | 1 |
| context assemblers used by cognition | 1 |
| recall APIs used by cognition | 1 |
| durable intent graphs | 1 |
| user attention markets | 1 |
| user-facing voice composers | 1 |
| action ledgers | 1 |
| unnoticed self/system failures | 0 |
| false completed actions | 0 |

## 3. What Exists Today

### 3.1 The valuable system that must be preserved

Sara already has unusually broad embodiment:

- chat, voice, attachments, cross-device sessions, and screen-aware tools;
- calendar, email, reminders, timers, tasks, notes, documents, projects, and people;
- HealthKit, fitness, food, sleep/recovery, location, home state, and device presence;
- system health, fleet awareness, Git activity, predictions, patterns, and model-of-David data;
- proactive check-ins, anticipation, briefs, reflection, curiosity, and self-audits;
- standing orders, home control, email drafts, calendar preparation, automations, and missions;
- a VM with shell/browser/file tools, persistent agent sessions, artifact collection, and local fallback;
- Proxmox container tools for isolated experiments;
- Sara-authored interests, goals, focus, journals, notes, and artifacts.

The plan preserves those capabilities. It changes who decides, how they share state, and how outcomes become visible.

### 3.2 The current fracture

There are presently two principal minds:

1. Backend Sara handles chat, event salience, deliberation, proactive tasks, notifications, memory, and most product behavior.
2. The ACS daemon on the Sara VM runs its own model, identity prompt, think/reflect cadence, focus, goal and interest selection, tools, and direct notification route.

The newer `kernel.py` names the correct four states, but currently implements only a facade over one ambient deliberation path. Engaged, focused, and dreaming cognition are not yet kernel-owned. `DAEMON_PROXY` is described but is not wired.

Fragmentation also exists below that split:

- a newer unified Redis context snapshot and an older cognitive working-memory store both remain active;
- `memory.recall()` exists, but chat, deliberation, ACS, briefs, and other workers still use different subsets and search paths;
- `sara_inbox`, `jarvis_inbox`, `autonomy_attention_item`, task clarification, and `notification_log` form multiple mailbox concepts;
- the notification composer is widely used but ACS can still call a deliberately ungated direct-notify endpoint;
- action receipts are split across mission/task state, notification records, and `action_ledger`;
- many prompts and deterministic templates speak as Sara without sharing the same final voice and context;
- 86 scheduled jobs are enabled across 23 categories, including overlapping deliberation, anticipation, check-in, curiosity, reflection, dreaming, consolidation, prediction, and briefing loops;
- `acs_plan_item` and `acs_deliverable` are referenced in code but absent from the live database;
- system health projections can disagree, and partial or failed work can appear completed.

### 3.3 ACS intent, correctly understood

ACS is not just another task runner. Its product intent is to give Sara:

- continuity while David is absent;
- an inner cadence rather than purely request-response behavior;
- self-originated interests and goals;
- the ability to notice, think, reflect, research, build, and return with something concrete;
- private-by-default internal processing without constant narration;
- a durable workshop outside the application process;
- bounded freedom to use local compute and isolated environments;
- a way to prioritize direct requests, continue unfinished goals, revisit stale interests, and remain quiet when nothing deserves action;
- survival across backend deploys and process restarts.

Those are core properties of singular Sara. They must move into the kernel, not be deleted with the daemon prompt.

### 3.4 VM intent, correctly understood

The Sara VM at `10.185.1.176` currently serves two distinct purposes:

1. It hosts the ACS daemon, which is currently a second brain.
2. It is the durable workshop used by agent dispatch and code mode for shell, browser, files, persistent sessions, reports, and artifacts.

The target preserves purpose 2 and replaces purpose 1. The VM becomes a resilient body/executor with:

- heartbeat and capability reporting;
- work claiming and lease renewal;
- durable execution sessions and resumability;
- shell, browser, filesystem, code, and artifact operations;
- Proxmox sandbox orchestration where isolation is appropriate;
- outcome and progress events returned to the kernel;
- no independent identity prompt, priority policy, memory policy, or direct speech authority.

If the VM is down, Sara's mind continues in a degraded state, notices the lost capability, and can use approved local fallbacks. The VM going offline must not create amnesia or a second narrative.

## 4. Target Architecture

```text
SOURCES
chat | voice | presence | calendar | email | health | location | home
fleet | git | tasks | VM outcomes | timers | external events
                              |
                              v
CANONICAL EVENT ENVELOPE -> SUBCONSCIOUS / SALIENCE
                              |
                              v
WORLD STATE + BODY STATE + INTENT GRAPH + MEMORY.RECALL
                              |
                              v
                     SARA KERNEL (one identity)
              engaged | ambient | focused | dreaming
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
     ATTENTION + VOICE                 ACTION EXECUTOR
 ask | surface | hold | push       consent | lease | execute
             |                       receipt | undo | artifact
             v                                 |
        WEB / iOS / VOICE <--------------------+
                                               |
                                               v
                                VM / services / home / Proxmox
```

### 4.1 Canonical event envelope

Every meaningful input becomes a typed event with:

- `event_id`, `occurred_at`, `observed_at`, `user_id`, `source`, and `kind`;
- structured payload and a schema version;
- provenance, confidence, sensitivity, and retention class;
- correlation and causation IDs;
- dedupe key;
- salience inputs;
- references to source records rather than copied prose where possible.

Adapters translate existing event bus, raw buffer, inbox, agent progress, and daemon activity records during migration.

### 4.2 World and body state

One context assembler creates versioned snapshots from canonical sources:

- **world state:** David's current situation, time, place, schedule, communications, home, work, people, active devices, and relevant changes;
- **body state:** Sara's services, workers, model access, VM, integrations, queues, storage, and failure/degradation state;
- **relationship state:** active conversation, tone, boundaries, recent promises, and what David has acknowledged;
- **self state:** current kernel mode, focus, confidence, open concerns, energy/budget pressure, and last meaningful progress.

Snapshots are projections, not new truth stores. Every field carries `as_of`, source, and confidence. Health endpoints and UI read the same body-state projection.

### 4.3 One intent graph

Replace competing queues with a durable graph whose nodes include:

- David request;
- commitment;
- reminder;
- standing order;
- Sara interest;
- Sara goal;
- investigation;
- mission;
- question waiting for David;
- observation/watch condition;
- artifact/deliverable;
- blocked dependency.

Each node has owner/origin, status, priority inputs, next step, dependencies, evidence, budget, permission boundary, last progress, next review, and outcome.

Sara interests and self-goals remain first-class. They are not downgraded into notifications or hidden cron tasks. The kernel arbitrates them alongside David's needs:

1. safety and explicit urgent requests;
2. promises and time-bound commitments;
3. work already in progress;
4. high-value observations and anticipated needs;
5. Sara's active goals and interests;
6. exploration when capacity remains;
7. quiet.

Self-chosen interests use an approval conversation:

1. Sara may notice and develop a lightweight interest proposal at any time.
2. A proposal must explain the subject, why it connects to David's interests, what Sara wants to learn or make, and the expected effort.
3. Proposals are normally batched into the morning brief or an evening check-in rather than sent as isolated interruptions.
4. David can approve, reject, defer, narrow, expand, or discuss the proposal with Sara.
5. Sara does not begin focused research or building for a self-chosen interest until David approves it.
6. After approval, Sara may use her VM workspace and its local resources freely within the agreed scope.
7. External messages, purchases, publication, destructive infrastructure changes, and effects outside the VM still follow their normal action permissions.

### 4.4 One kernel, four states

All states use the same identity, context assembler, recall, intent graph, policy, and voice contract. They differ in trigger, budget, latency, and available actions.

**Engaged**

- Triggered by chat, voice, app foreground interaction, or an explicit command.
- Owns the normal conversation path now assembled in `main_simple.py`.
- Supports inline tools, dispatch decisions, clarification, and continuity with background work.
- Sees what ambient/focused/dreaming states did since the last interaction.
- Records commitments and unresolved questions before the turn closes.

**Ambient**

- Triggered by promoted events, meaningful context changes, adaptive sleep pressure, scheduled anchors, interoception, or task outcomes.
- Replaces separate periodic deliberation, anticipation, idle, daemon think, and routine check-in minds.
- Chooses among update state, pursue intent, delegate focused work, prepare an attention item, or stay quiet.
- Does not use cron occurrence itself as evidence that something deserves speech.

**Focused**

- Owns missions that require sustained tool use, research, coding, browsing, or multi-step work.
- The kernel creates the mission brief, constraints, evidence packet, success criteria, and permission envelope.
- An executor on the VM or another registered body performs the work.
- The kernel evaluates the outcome before marking the intent complete or speaking.

**Dreaming**

- Owns consolidation, reflection, forgetting, contradiction detection, pattern review, interest formation, and self-audit.
- Runs mostly overnight or under low interruption pressure.
- Produces proposed memory changes, goal changes, and internal reflections.
- Keeps reflections inspectable by David on demand; summaries can appear in Interior while full entries remain available through drill-down.
- May formulate interest proposals, but may not turn an unapproved self-chosen interest into focused execution.
- External speech still goes through attention; reflection never pushes merely because it ran.

### 4.5 One recall path

Evolve the existing additive `memory.recall()` into the mandatory interface:

- episodic conversations and observations;
- authored notes and documents;
- summaries and lessons;
- PKG facts and preferences;
- people and relationship context;
- open threads and commitments;
- intents, missions, outcomes, and artifacts;
- Sara's goals, interests, reflections, and learned operating lessons.

Required response fields:

- normalized text and stable source reference;
- observed/inferred/confirmed status;
- numeric confidence separate from semantic similarity;
- provenance and timestamps;
- contradiction group, supersession state, and sensitivity;
- why the trace was selected.

The context assembler decides when recall is needed. Individual cognition modules may request scopes but may not query stores directly after cutover.

### 4.6 One attention and voice path

All proactive communication becomes an outbound intent before it becomes prose:

- subject and facts;
- why it matters now;
- desired user response;
- deadline and expiry;
- confidence;
- interruption cost;
- channel eligibility;
- dedupe/correlation key;
- source intent and action receipt.

The attention market chooses:

- internal only;
- update a passive projection;
- add to Today;
- inject on the next engaged turn;
- send a quiet notification;
- send an interruptive notification;
- ask for approval or clarification.

Only after that decision does one voice composer render web, push, voice, or chat text. Deterministic security/timer fallbacks remain, but share the same identity rules and delivery receipt.

ACS `/notify`, direct service notifications, task completion text, briefs, and legacy templates migrate behind this interface. No subsystem is trusted to self-regulate its own spam.

### 4.7 One action executor and receipt

Every action request is represented before execution:

- proposed action and reason;
- source intent;
- target and parameters;
- permission tier;
- reversibility and undo window;
- idempotency key;
- preconditions;
- executor/body selection;
- lease, attempts, progress, result, evidence, and artifact references.

Permission tiers:

| Tier | Behavior |
|---|---|
| Observe | Read-only; can execute silently within data policy |
| Reversible local | May execute under learned/explicit policy; always receipt and undo |
| Consequential | Requires standing order or explicit approval |
| Irreversible/external | Requires explicit approval at execution time |

Mission state, background task state, and action ledger must reconcile transactionally. `completed` requires verified success criteria. Otherwise use `partial`, `blocked`, `failed`, or `cancelled`.

## 5. Core Implementation Workstream

**Branch:** `feat/singular-sara-core`

No visual redesign belongs on this branch. Minimal diagnostic UI changes are also deferred unless required to operate a migration flag. The branch owns schemas, services, migrations, APIs, workers, daemon/body code, tests, telemetry, and compatibility adapters.

### C0. Baseline and safety rails

Deliverables:

- Record a machine-readable inventory of all 86 enabled jobs, cognitive prompts, recall callers, notification writers, mailbox writers, action writers, and status projections.
- Add correlation IDs spanning event, kernel turn, intent, mission, action, outbound intent, and delivery.
- Add truth audits for impossible state combinations, including failed task plus completed mission.
- Add counters for each legacy and target path.
- Freeze creation of new autonomous loops or direct notification paths during migration.
- Define feature flags and kill switches:
  - `SINGULAR_EVENT_ENVELOPE`;
  - `SINGULAR_CONTEXT`;
  - `SINGULAR_INTENTS`;
  - `SINGULAR_KERNEL`;
  - `SINGULAR_VM_BODY`;
  - `SINGULAR_ATTENTION`;
  - `SINGULAR_ACTIONS`;
  - `LEGACY_COGNITION_SHADOW`.
- Capture evaluation fixtures from real, redacted scenarios before behavior changes.

Exit gate:

- Every current cognitive and autonomous capability has an owner in the preservation matrix.
- Baseline metrics run for seven days or an agreed representative replay window.
- Existing contradictions are measurable rather than anecdotal.

### C1. Contracts and canonical event envelope

Deliverables:

- Add versioned schemas for event, body state, world state, kernel state, intent, mission, action receipt, artifact, outbound intent, and attention item.
- Publish projection API contracts used by both UI clients.
- Implement adapters from current event bus, observations, ACS activity, task progress, and integration callbacks.
- Persist event causality and idempotency.
- Do not migrate high-volume raw health/home samples into prose events; emit meaningful changes and retain raw source references.

Exit gate:

- Replaying an event produces the same dedupe and projection outcome.
- Every event displayed or acted on can be traced to its source.
- Web/iOS contract fixtures are stable enough to start the UI branch.

### C2. Canonical context and body state

Deliverables:

- Select the newer unified snapshot as the migration base.
- Extend it with versioned world, relationship, self, and body projections.
- Convert the older cognitive working memory into a compatibility reader/writer.
- Route `world_model`, chat, deliberation, briefs, and status endpoints through the canonical projection.
- Rebuild snapshots deterministically from durable stores after Redis loss.
- Make VM, model, database, queues, integrations, and scheduler failures part of Sara's body state.

Exit gate:

- One test fixture produces the same relevant context in chat, ambient, and focused states.
- `/api/sara/status`, briefs, Interior, and system health cannot disagree about the same component.
- The old working-memory keys receive no unique writes for seven days before removal.

### C3. Intent graph and continuity

Deliverables:

- Add canonical intent and intent-edge tables.
- Migrate or adapt commitments, threads, reminders, standing orders, Sara goals/interests, missions, ACS inbox items, and waiting questions.
- Define state transitions and enforce them in one service.
- Add automatic next-review scheduling based on state, not one job per feature.
- Add a commitment extractor at the engaged-turn boundary.
- Add outcome reconciliation so actions and artifacts advance the originating intent.
- Repair dead `acs_plan_item` and `acs_deliverable` references by replacing them with intent and artifact records.

Exit gate:

- A request started in chat can continue on the VM, survive restart, return an artifact, and be discussed in a later chat using one intent ID.
- Sara's self-chosen goal follows the same lifecycle without pretending David requested it.
- Nothing can be both completed and failed.

### C4. Kernel engaged state

Deliverables:

- Move chat orchestration behind `kernel.engaged_turn()`.
- Move chess, code, host, web-investigation, UI-intent, multi-step, tool routing, and inbox-review interceptions into explicit skills or deterministic pre-kernel adapters.
- Build one context packet from the canonical assembler plus `memory.recall()`.
- Apply one identity contract and one model-routing policy.
- Persist commitments, uncertainty, decisions, and turn outcomes.
- Preserve streaming behavior and current tool capability.

Exit gate:

- Current chat regression suite passes.
- A conversation can correctly reference ambient/focused/dreaming outcomes.
- There is no second chat-only memory or identity prompt.

### C5. Kernel ambient state

Deliverables:

- Expand `ambient_turn()` to accept canonical wake events and intent candidates.
- Replace special-purpose thought prompts with one ambient policy plus typed skills.
- Run the current deliberation engine in shadow mode against the new kernel.
- Fold in:
  - periodic deliberation;
  - proactive check-in sweep;
  - morning/evening anticipation;
  - idle processing;
  - daemon think;
  - post-meeting follow-up selection;
  - high-level assistant-verbs decisions.
- Keep domain computations, such as calendar prep calculation, prediction matching, and health baseline computation, as deterministic sensors/skills.
- Add explicit `quiet`, `observe`, `advance_intent`, `delegate`, and `prepare_outbound` outcomes.
- Treat model failure as failed cognition, never as a successful thought containing an error string.

Exit gate:

- Shadow comparisons show no lost high-value notices or actions.
- Repetitive idle narration and duplicate Risk Ninja-style messages are absent in replay.
- Ambient decisions explain the wake event, selected intent, and why Sara spoke or stayed quiet.

### C6. Kernel dreaming state

Deliverables:

- Consolidate reflection cycle, nightly dream, memory consolidation, curiosity sweep, contradiction review, and weekly self-audit under `kernel.dreaming_turn()`.
- Keep deterministic maintenance jobs separate from cognition.
- Generate memory proposals with provenance rather than silently rewriting truth.
- Let dreaming create or revise Sara interests and goals through the intent graph.
- Add interest diversity, progress, staleness, block reason, strike, and retirement rules.
- Add `proposed`, `discussing`, `approved`, `deferred`, and `rejected` states for self-chosen interests.
- Batch pending interest proposals into the morning brief or evening check-in, with direct approve, reject, defer, and discuss actions.
- Require research or experimentation to yield evidence, a note, an artifact, a changed belief, or a clearly logged null result.

Exit gate:

- Sara maintains active interests without repetitive self-talk.
- An approved curiosity can become a goal, become focused work, produce an artifact, and update memory.
- An unapproved curiosity remains a proposal and consumes no focused-work budget.
- Reflection changes future behavior through explicit lessons or policy proposals.

### C7. Focused state and VM body transplant

Deliverables:

- Implement `kernel.focused_turn()` and canonical mission briefs.
- Replace ACS `mind.py` and `prompt.py` decisions with a body agent that:
  - heartbeats capabilities and version;
  - claims a mission lease;
  - executes only the provided permission envelope;
  - streams structured progress;
  - resumes durable sessions;
  - uploads artifacts and evidence;
  - returns an outcome without composing user speech.
- Retain current VM shell/browser/file/code functionality and managed-host targeting.
- Treat the Sara VM as her permanent home/workshop, not a disposable worker or an identity authority.
- Allow broad autonomous use of tools, storage, compute, and reversible changes inside the VM after the originating interest or task is approved.
- Retain Proxmox container provisioning as a consequential execution skill with quotas, TTLs, and cleanup.
- Distinguish VM workshop, `acs-tool-runner`, managed hosts, and Proxmox sandboxes in body capability records.
- Preserve backend/local fallback for eligible tasks.
- Add drain, cancel, retry, and resume semantics.
- Remove the daemon's separate recall, goals/interests scheduler, focus singleton, tool-planning loop, and direct notify only after parity gates pass.

Exit gate:

- VM restart during work resumes from the lease/session without duplicating actions.
- Backend restart does not erase the mission or Sara's understanding of it.
- VM outage degrades execution, not identity, memory, or conversation.
- `selves=1` telemetry remains true during chat, background thought, and VM work.

### C8. Memory unification and truth maintenance

Deliverables:

- Add missing intent, artifact, self-memory, and outcome sources to `memory.recall()`.
- Migrate every direct cognition caller to the canonical API.
- Add contradiction groups, supersession, verification queue, and source priority.
- Separate semantic match score from factual confidence.
- Define write policies for observed, inferred, and confirmed memory.
- Make forgetting/decay reversible during an audit window.
- Resolve or archive the existing needs-verification backlog instead of feeding it into confident responses.

Exit gate:

- Static analysis prevents new cognition code from importing store-specific recall.
- Recall traces explain why a memory appeared and how certain it is.
- Contradictory active facts are surfaced rather than blended.
- Recall-path count reaches one.

### C9. Attention, voice, and mailbox migration

Deliverables:

- Create canonical outbound-intent and attention-item persistence, or evolve `autonomy_attention_item` to meet the full contract.
- Route ACS notify, unified notifications, task results, briefs, interoception alerts, reactive events, calendar prep, and check-ins through it.
- Make one voice composer the last prose stage for chat injection, push, inbox, and voice.
- Preserve deterministic emergency/timer fallbacks.
- Add channel-specific rendering without changing underlying facts.
- Migrate acknowledgements, snooze, dismiss, approve, deny, and reply into one state machine.
- Adapt `sara_inbox`, `jarvis_inbox`, notification log, and task clarification during transition, then stop legacy writes.
- Make read-time inbox aggregation a projection of canonical persistence.

Exit gate:

- One outbound intent can appear once across Today, chat, and push without duplicate speech.
- Every delivered line has source facts, attention decision, rendered text, and delivery receipt.
- No direct user-facing notification writer remains outside the approved adapter list.
- The daemon cannot bypass attention.

### C10. Action executor and truthful completion

Deliverables:

- Introduce a single action-request service and executor registry.
- Route standing orders, deliberation home actions, email drafts, calendar prep, VM missions, and automation actions through it.
- Extend or migrate `action_ledger` to cover every material action, not only selected categories.
- Enforce idempotency, permission tier, approval, lease, timeout, retries, and undo policy.
- Reconcile mission, task, action, artifact, and intent states transactionally.
- Add explicit partial and blocked outcomes.
- Record validation evidence before completion.
- Provide one action-detail projection for clients.

Exit gate:

- Replayed requests cannot duplicate external effects.
- Every reversible action exposes a working undo within its window.
- Failed validation prevents a completed state.
- One action receipt explains what Sara decided, what body acted, and what actually happened.

### C11. Scheduler diet

Classify every scheduled job into:

- **sensor:** gathers or computes facts;
- **maintenance:** retention, cleanup, sync, model training, health checks;
- **anchor:** creates a kernel wake event at a meaningful time;
- **legacy cognition:** must migrate into a kernel state and then be disabled.

Keep domain computations deterministic. Remove cognition wearing separate cron identities.

Expected migrations:

- periodic deliberation, check-ins, anticipation, idle processing, daemon cadence -> ambient wake policies;
- curiosity, reflection, dream, consolidation, self-audit -> dreaming policies;
- mission worker and dispatch -> focused executor lease loop;
- morning/evening briefs -> projections generated from canonical state, with optional kernel-authored synthesis;
- notification tuner/delivery flush/attention escalation -> one attention scheduler;
- context refresh and old consolidation watcher -> event-driven context updates plus a cold-start repair task.

Exit gate:

- Every remaining job has a documented non-cognitive responsibility or creates a kernel wake event.
- No scheduled job owns an identity prompt or can speak directly.
- Job failures enter body state and create an internal concern or correctly gated user notice.

### C12. Cutover and removal

Deliverables:

- Run target paths in shadow mode and compare decisions.
- Enable by state: context, engaged, ambient, focused/VM, dreaming, attention, actions.
- Drain legacy queues before disabling writers.
- Archive legacy tables after a defined read-only period.
- Remove old prompts, dead models, adapters, flags, and routes only after telemetry proves zero use.
- Update operational docs, disaster recovery, and runbooks.

Exit gate:

- Four continuous weeks with no P0/P1 coherence defect.
- No legacy cognition, recall, direct speech, or action path receives traffic.
- A clean deployment and Redis/worker/VM restart preserve continuity.

## 6. UI Workstream

**Branch:** `feat/singular-sara-ui`

This branch owns web and iOS presentation, navigation, interaction, accessibility, client state, and client tests. It does not change cognition, persistence semantics, priority policy, or execution rules.

### 6.1 Branch sequence

1. Start `feat/singular-sara-core` from an approved clean baseline.
2. Complete C1 and commit the versioned projection contracts and fixtures.
3. Create `feat/singular-sara-ui` from that contract commit.
4. Continue core and UI work independently against the frozen v1 contracts.
5. Merge core first behind feature flags.
6. Rebase the UI branch onto the merged core.
7. Run contract, end-to-end, screenshot, and device tests.
8. Merge and enable the UI separately.

Contract changes after the branch point require a versioned schema update and fixture change. UI must not depend on undocumented backend response fields.

### U0. Experience contract and information architecture

Replace subsystem-based navigation with human-purpose spaces.

Recommended top-level web:

- Home
- Chat
- Today
- Memory
- Life
- Work
- Studio
- Interior
- Settings

Recommended iOS tabs:

- Sara
- Today
- Chat
- Life
- More

`More` contains Memory, Work, Studio, Interior, and Settings. Fitness becomes a Life view rather than a separate identity-bearing app section.

Legacy destinations map as follows:

| Current surfaces | Target |
|---|---|
| ACS, Mind, The System, System Status, sensory status | Interior, with ACS retained as the autonomous-cognition view |
| Inbox, tasks, reminders, timers, attention | Today |
| Notes, documents, knowledge, learning | Memory |
| Calendar, email, fitness, recipes, people | Life |
| Projects, agent tasks, automations, machines | Work |
| Artifacts, canvas, generated reports | Studio |

Advanced infrastructure remains available through drill-down, not equal-weight primary navigation.

### U1. Shared projection client

Deliverables:

- Generate or validate TypeScript types from the v1 contracts.
- Build shared web and iOS adapters for Home, Today, Interior, intent, mission, action, artifact, and attention projections.
- Add loading, stale, degraded, empty, partial, failed, and offline states.
- Show `as_of` and confidence only where they affect a decision.
- Do not infer success, health, or Sara's state from unrelated endpoint fragments.

### U2. Home and Sara tab

Home should answer:

1. What matters now?
2. What is Sara doing?
3. What changed?
4. What needs David?
5. What can David say or do next?

Deliverables:

- one current-state presence for Sara;
- a concise now/next view;
- active work with truthful progress;
- one attention area;
- recent meaningful change;
- direct entry into conversation;
- degraded-state treatment that is honest but not alarmist.

Remove duplicate cards that independently summarize the same missions, attention, status, or journal data.

### U3. Conversation

Deliverables:

- same conversation and state across web/iOS;
- visible background-work handoffs in the relevant thread;
- inline approval, clarification, undo, open artifact, and retry controls;
- resumable focused/code sessions without global chat hijacking;
- a compact indication when Sara is recalling, using a tool, waiting, or delegating;
- no raw agent preambles, internal URLs, tool syntax, or task-proposal scaffolding in final speech.

### U4. Today

Deliverables:

- one ordered feed of items requiring awareness or action;
- separate visual treatment for needs response, in progress, scheduled, passive update, and done;
- approve, deny, reply, snooze, dismiss, retry, and undo in place;
- deduplicated rendering when one intent has push, chat, and feed delivery;
- timeline filters without exposing storage-system names.

### U5. Memory

Deliverables:

- unified search across traces;
- clear provenance and observed/inferred/confirmed labeling;
- contradiction and needs-verification review;
- people, commitments, notes, documents, learned preferences, and Sara's operating lessons as views of one memory;
- correct, confirm, forget, and restrict controls;
- links from a memory to the conversation, event, intent, or artifact that produced it.

### U6. Life, Work, and Studio

**Life**

- calendar, communications, people, routines, fitness/recovery, food, location, and home;
- domain dashboards remain useful but share Today and action semantics.

**Work**

- projects, intents, missions, agent work, automations, standing orders, and machines;
- show outcome and dependency rather than implementation worker names;
- detailed execution trace available on demand.

**Studio**

- all reports, notes, code, diagrams, screenshots, files, and canvases produced by Sara;
- link every artifact to its goal/mission and validation state;
- preview, download, continue, discuss, revise, and archive actions;
- empty state should reflect actual output scarcity without claiming work exists.

### U7. Interior

Interior consolidates Mind, The System, status dashboards, and ACS into one truthful surface. The ACS name may remain for the autonomous-cognition view, but it does not represent a second Sara.

It should show:

- current kernel state and why it woke;
- current focus and active intents;
- Sara's interests and self-goals;
- pending interest proposals with approve, reject, defer, and discuss actions;
- recent decisions, including quiet decisions;
- reflection summaries and full inspectable entries;
- confidence, concerns, contradictions, and blocked capabilities;
- body state and degraded components;
- attention decisions and action receipts;
- memory health and model/policy information for audit.

Default view is understandable and personal. Raw traces, scheduler details, fleet metrics, prompts, and tool logs belong in an advanced inspector.

Interior must not perform consciousness theater. It reports real stored state, evidence, uncertainty, and work.

### U8. iOS embodiment

Deliverables:

- preserve HealthKit, background sync, location, widgets, Siri/App Intents, push actions, voice, and Live Activities;
- make widgets and Live Activities projections of current intents/missions, not separate status logic;
- use interactive push actions from the canonical attention item;
- carry conversation and intent identity through notification deep links;
- support offline queued replies/acknowledgements with idempotency;
- make voice responses use the same outbound facts and voice contract;
- ensure background sync failures appear in body state rather than silently creating stale confidence.

### U9. UI removal and polish

Deliverables:

- remove duplicate ACS/Mind/System screens after Interior parity;
- retain ACS as a capability/view name where it helps David understand autonomous cognition;
- remove implementation language such as daemon, worker, and queue from primary product copy;
- retain implementation terms only in advanced diagnostics;
- verify responsive layouts and accessibility on web;
- verify representative iPhone sizes, Dynamic Type, VoiceOver labels, dark mode, and offline/degraded behavior;
- add visual regression coverage for every projection state.

UI exit gate:

- A user can understand what Sara knows, wants, is doing, needs, and completed without visiting multiple status screens.
- The same intent and outcome have the same state on web and iOS.
- No client manufactures its own definition of healthy, active, completed, urgent, or sent.

## 7. Capability Preservation Matrix

| Current capability | Target owner | Migration rule |
|---|---|---|
| ACS adaptive cadence | ambient wake policy | preserve adaptive quiet behavior |
| ACS think/reflect prompts | ambient/dreaming kernel | remove separate identity |
| ACS focus | intent graph + kernel state | migrate history, retire singleton |
| ACS interests/goals | self-originated intents | preserve origin and autonomy |
| ACS inbox | intent/attention adapter | stop direct prioritization |
| ACS direct notify | attention + voice | remove bypass |
| ACS web/notes/memory tools | focused skills | retain bounded tools |
| ACS Proxmox tools | consequential executor skill | quotas, TTL, receipts |
| VM Claude/Qwen task loops | focused body executor | kernel owns brief and validation |
| code mode | engaged/focused session skill | bind to conversation and intent |
| proactive check-ins | ambient candidate skill | one attention decision |
| anticipation | ambient look-ahead skill | anchors wake; kernel decides |
| curiosity | dreaming goal formation | evidence-bearing outcomes |
| reflection/self-audit | dreaming | explicit lessons and proposals |
| prediction/pattern models | subconscious sensors | no direct voice |
| morning/research briefs | projections + synthesis skill | same state and attention |
| standing orders/automation | action policy + executor | one receipt and undo |
| home/email/calendar actions | executor adapters | consent and validation |
| task/mission delivery | outcome -> attention | no separate completion voice |
| old working memory | compatibility adapter | retire after zero unique writes |
| store-specific recall | memory adapter | migrate to `memory.recall()` |
| multiple status APIs | projection adapters | one body/kernel truth |

## 8. Data Migration

Recommended new or evolved durable records:

- `event_envelope`;
- `intent`;
- `intent_edge`;
- `intent_progress`;
- `kernel_turn`;
- `memory_trace` metadata or source registry;
- `outbound_intent`;
- canonical `attention_item`;
- expanded `action_receipt`;
- `execution_lease`;
- canonical `artifact`;
- `body_capability`.

Migration rules:

1. Add new tables and adapters first.
2. Backfill stable IDs and origin references.
3. Dual-read and shadow-compare.
4. Dual-write only where transactions can guarantee consistency.
5. Switch authoritative writes one domain at a time.
6. Drain queued legacy records.
7. Make legacy tables read-only.
8. Observe zero reads/writes.
9. Archive, then remove in a later release.

Never flatten ACS interests/goals into generic tasks without preserving origin, curiosity rationale, progress, and outcome. Never convert inferred memory into confirmed truth during backfill.

## 9. Evaluation Program

### 9.1 Scenario suite

The suite must cover:

- David asks for research, leaves, VM restarts, Sara resumes, validates, delivers one artifact, and remembers it later.
- Sara notices a real upcoming need, prepares quietly, and surfaces it at the correct time.
- Sara chooses not to speak about a low-value event and can explain that decision in Interior.
- A self-originated interest becomes a bounded investigation with a useful or honestly null outcome.
- Conflicting facts are recalled with uncertainty and a verification request.
- A home action is performed once, verified, receipted, and undone.
- A consequential action waits for approval and expires safely.
- A failed agent task remains failed or partial everywhere.
- The VM, Redis, one worker, model provider, email, and HealthKit each fail independently.
- Web and iOS reconnect after being offline without duplicate acknowledgements or actions.

### 9.2 Quality metrics

Track:

- continuity success rate across state and device transitions;
- commitment capture and follow-through rate;
- mission validation rate;
- false-completion rate;
- repeated-notification rate;
- attention acceptance, dismiss, snooze, and regret signals;
- unsupported factual assertion rate;
- contradiction detection/resolution rate;
- useful self-goal outcome rate;
- artifact completion and revisit rate;
- percentage of kernel turns that correctly choose quiet;
- legacy-path traffic;
- state disagreement across projections;
- recovery time after component failure.

### 9.3 Required tests

- schema and contract tests;
- state-machine property tests;
- event replay/idempotency tests;
- permission and approval tests;
- memory provenance and contradiction tests;
- scheduler classification tests;
- daemon/body lease and restart tests;
- notification dedupe and multi-channel tests;
- action validation and undo tests;
- web/iOS projection parity tests;
- end-to-end scenario tests;
- visual regression and accessibility tests on the UI branch.

## 10. Rollout and Rollback

Roll out to David's account only, one state at a time:

1. telemetry and contracts;
2. context/body projections;
3. intent graph;
4. engaged kernel;
5. ambient kernel in shadow, then active;
6. focused kernel and VM body;
7. dreaming kernel;
8. attention/voice;
9. action executor;
10. scheduler retirement;
11. UI.

Each cutover requires:

- a reversible feature flag;
- a queue-drain procedure;
- a data reconciliation query;
- a defined owner and observation window;
- a rollback that restores the former reader/writer without losing new records.

Do not disable ACS cognition until the focused and dreaming paths have demonstrated continuity, self-goal progress, and VM restart recovery. Do not merge the visual consolidation until the canonical projection APIs are authoritative.

## 11. Recommended Delivery Order

The critical path is:

```text
C0 baseline
  -> C1 contracts/events
  -> C2 context/body
  -> C3 intent graph
  -> C4 engaged
  -> C5 ambient
  -> C7 focused + VM
  -> C6 dreaming
  -> C8 memory
  -> C9 attention/voice
  -> C10 actions
  -> C11 scheduler diet
  -> C12 removal
```

Memory adapters begin in C2 and finish in C8. Attention adapters begin in C3 and finish in C9. Action receipts begin in C3 and finish in C10.

The UI branch can begin after C1 contracts, but U2-U8 should not be declared complete until their corresponding core projections are authoritative.

## 12. Confirmed Product Decisions

These decisions are authoritative for implementation:

1. **Reflection visibility:** David can inspect Sara's reflections. Interior shows summaries by default and permits drill-down into full entries. Reflections are not proactively pushed merely because they exist.

2. **Interest alignment:** Sara's self-chosen interests must connect to subjects David is also interested in. The proposal records that connection explicitly.

3. **Interest approval:** Sara brings self-chosen interest proposals to David in a natural morning or evening conversation. David may approve, reject, defer, reshape, or discuss them. Focused work begins only after approval.

4. **Post-approval freedom:** Once an interest or task is approved, Sara may use whatever local compute, tools, files, and reversible workflows she needs inside her VM. External or irreversible effects remain governed by action permissions.

5. **ACS naming:** ACS does not have to disappear. It may remain as the name of Sara's autonomous-cognition capability or Interior view, but it must not retain a separate identity, memory policy, priority system, or voice.

6. **Permanent VM:** `10.185.1.176` is Sara's permanent system and workshop. It is not treated as a disposable worker. Sara's identity and durable truth still live above the machine so an outage does not split or erase her.

7. **No pre-approval draft work:** For self-chosen interests, Sara may gather only enough context to make a useful proposal. She does not perform the substantive research or build a draft artifact before David approves it.

8. **Sole user:** The application is solely for David. Product behavior, policies, prompts, schedules, and interfaces should optimize for that fact. Existing `user_id` boundaries can remain for data integrity, but multi-user product requirements must not complicate the design.

9. **Independent VM use:** Sara has independent control of her permanent VM for approved work. Normal use of its compute, storage, network research tools, installed software, files, sessions, and reversible local changes requires no additional approval. Provisioning or destroying separate Proxmox guests remains an external infrastructure action.

## 13. First Implementation Slice

The first pull request on `feat/singular-sara-core` should be deliberately non-visual:

1. Commit the inventory and invariants as tests/diagnostics.
2. Add correlation IDs and the versioned projection schemas.
3. Add a canonical body-state projection that resolves current health contradictions.
4. Add an intent/action reconciliation audit that catches false completion.
5. Add contract fixtures for web and iOS.
6. Run without changing cognition or delivery behavior.

That slice creates the observability and contracts needed to change Sara's mind without losing track of what the existing system actually does.

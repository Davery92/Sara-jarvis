# Sara Proactiveness Implementation Plan

**Date:** 2026-07-25  
**Companion audit:** `SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25.md`  
**Master plan:** `SINGULAR_SARA_MASTER_PLAN_2026_07_24.md`  
**Branch rule:** Runtime behavior and UI changes must be implemented on separate branches

This work is a required extension of the Singular Sara plan. It is not a
notification-polish follow-up.

The required end-to-end path is:

```text
observation
  -> reach-out candidate
  -> one global attention decision
  -> one selected time and channel
  -> one voice render
  -> one delivery receipt
  -> one outcome linked to the original candidate
  -> learned future judgment
```

## 1. Core Runtime Branch

All work in this section belongs on a non-UI branch such as
`feat/singular-sara-proactivity-core`.

### P0. Deploy and measure the intended revision

1. Rebuild the backend and every Celery worker image from the intended
   singular-Sara commit.
2. Deploy a matching VM daemon revision.
3. Record backend, worker, scheduler, web API, iOS API, and daemon versions in
   one deployment manifest.
4. Confirm which feature flags are read by each running binary.
5. Repeat the scheduler and notification baseline after deployment.

Exit gate: Git, running containers, database schema, and VM daemon all report
compatible revisions.

### P1. Make a candidate the only input to outreach

Add one canonical `ReachOutCandidate` contract:

```text
id
causal_event_id
source
subject
candidate_kind
facts
why_now
why_david_cares
expected_user_value
urgency
confidence
novelty
consequence_of_silence
requested_user_action
earliest_at
expires_at
grouping_key
sensitivity
allowed_channels
```

Generators submit facts and rationale, not titles and bodies. Every candidate
must enter one global arbiter before prose or delivery.

Exit gate: direct user-facing notification calls from proactive generators are
zero, apart from explicit emergency adapters during migration.

### P2. Make attention judgment authoritative

The arbiter chooses exactly one outcome:

```text
interrupt_now
ask_in_active_conversation
include_in_morning
include_in_evening
add_to_today
keep_internal
discard
```

It evaluates all candidates together, so Sara can prefer one strong reach-out
over five individually plausible messages.

Required policies:

- per-causal-event deduplication across every generator and channel;
- expiration before delivery;
- cancellation when the underlying fact recovers or changes;
- batching by subject;
- diversity across topics;
- awareness of sleep, presence, focus, and current conversation;
- explicit separation of urgency from confidence;
- an initial adaptive budget of no more than two non-urgent proactive pushes
  per day, excluding requested timers, reminders, and critical events;
- no age-based priority inflation.

Delete the existing attention escalation behavior. If a deadline approaches,
re-evaluate the original facts; never promote an item merely because it is old.

Exit gate: every delivered proactive message has one candidate, one attention
decision, one render, and one delivery receipt.

### P3. Convert generators into sensors

Convert, then retire direct delivery from:

- morning proactive patterns;
- proactive check-ins;
- anticipation;
- predictive engine;
- calendar preparation;
- cross-system synthesis;
- interoception;
- learning and autonomy digests;
- ACS discoveries;
- task watchdogs and task-result delivery.

Cron schedules may wake a sensor, but they do not determine that David should
hear from Sara.

Exit gate: scheduler execution count no longer correlates directly with
notification count.

### P4. Repair domain-specific judgment

Calendar:

- distinguish meetings, workouts, personal routines, all-day events, and
  financial markers;
- suppress routine-event pushes by default;
- create candidates only for preparation, travel, conflict, unusual change, or
  explicit preference;
- cancel stale candidates when the event begins.

Follow-up:

- require a concrete remembered commitment or explicit follow-up agreement;
- give every thread a useful time window and expiry;
- close stale threads;
- prohibit generic topics such as "work";
- allow only one unresolved reach-out per causal thread.

Home patterns:

- group device observations into a human routine such as "evening shutdown";
- estimate benefit before proposing automation;
- propose once;
- convert acceptance into a standing order;
- use rejection or `Never` to block recurrence;
- never escalate an ignored proposal.

System health:

- notify only when a durable fault affects David or requires his action;
- keep diagnostics visible in Interior;
- cancel held degradation notices if recovery occurs first;
- do not send a recovery message unless David saw the original fault.

Tasks:

- translate internal failure into user impact and the next decision;
- never expose infrastructure details unless David asks;
- deliver one result with a verified artifact or an honest partial/failure
  state.

### P5. Implement the interest approval relationship

1. Add the explicit interest lifecycle:
   `noticed -> candidate -> aligned -> proposed -> discussing -> approved |
   deferred | rejected -> active -> blocked | completed | abandoned`.
2. Prohibit ACS direct notifications.
3. Feed interest proposals into morning/evening candidate batches.
4. Require evidence of alignment with David's interests.
5. Convert approval into a canonical intent and focused VM mission.
6. Persist milestones, blockers, artifacts, and outcome under that intent.
7. Fold ACS reflection and goal selection into the singular kernel.
8. Stop periodic "I am going quiet" reflections and other meta-activity loops.

Exit gate: no self-originated focused work starts without an approval record,
and no approved work needs repeated permission for normal independent VM use.

### P6. Learn value at the right level

Track outcomes against the original candidate:

- replied;
- approved;
- acted;
- completed requested action;
- opened artifact;
- explicitly useful;
- not now;
- snoozed;
- dismissed;
- disliked;
- never this;
- ignored until expiry.

Do not equate a tap with usefulness. Do not train on dedup rows or copies
created by escalation.

Learn hierarchically by:

- generator;
- candidate kind;
- subject;
- person or entity;
- channel;
- time and context;
- requested versus self-originated work.

Explicit controls override learned estimates:

- more like this;
- less like this;
- never this topic;
- morning/evening only;
- Today only;
- interrupt me for this.

Exit gate: David's rejection of one home routine suppresses that routine
without suppressing requested reminders or unrelated useful suggestions.

### P7. Render once in one voice

Only after attention and channel are selected should the voice composer render
the message.

Rules:

- the title names the actual subject;
- the body states the new fact, why it matters, and the action if any;
- no "quick heads up," "checking in," or machinery narration as filler;
- no second LLM rewrite during escalation or channel fallback;
- factual content is immutable after the candidate is accepted;
- morning/evening batches read as one conversation, not a list of worker
  outputs.

Exit gate: identical facts cannot acquire different meanings while moving
through the queue.

### P8. Retire legacy authority

1. Disable and remove attention escalation.
2. Remove direct notification calls from ACS and proactive generators.
3. Stop writing new legacy attention rows.
4. Drain or expire existing rows without pushing them.
5. Make canonical candidate, decision, and receipt tables authoritative.
6. Remove old scheduler cognition loops after parity observation.

Exit gate: one attention market, one voice, one feedback loop, and no bypass.

## 2. UI Branch

All work in this section belongs on a separate branch such as
`feat/singular-sara-proactivity-ui`. It begins only after the P1/P2 contracts
are stable.

### Web and iOS

- Morning and evening conversations show a single coherent Sara message.
- Interest proposals offer `Discuss`, `Approve`, `Not now`, and `No`.
- Today shows non-interruptive items grouped by subject and causal event.
- Interior shows why Sara spoke or stayed quiet, the facts she used, and her
  confidence.
- Notification history distinguishes delivered, read, useful, dismissed,
  expired, and canceled.
- Settings expose topic/channel boundaries without a large generic preference
  matrix.
- A reach-out supports `Useful`, `Less like this`, `Never this`, and
  `Timing...` controls.
- Approved VM work shows the same mission, progress, blockers, and artifact on
  both platforms.

The UI must not:

- expose scheduler names, worker names, queue rows, or subsystem ownership;
- present ACS as a separate person;
- show an expired candidate as an unread obligation;
- make reflection activity look like useful progress;
- require David to manage dozens of source-specific toggles.

## 3. Evaluation

### 3.1 Primary metrics

- useful reach-outs divided by delivered reach-outs;
- explicit negative feedback and dismissal rate;
- interruptions per day by policy class;
- duplicate causal events across channels;
- stale deliveries after expiry;
- messages delivered during inferred sleep or deep focus;
- candidates correctly kept quiet;
- direct-delivery bypass count;
- requested-task result reliability;
- interest proposal discuss/approve/defer/reject rate;
- approved-interest completion and artifact-use rate;
- repeated-topic rate after negative feedback.

Raw notification opens are diagnostic, not the primary success metric.

### 3.2 Required scenario tests

- Two generators observe the same meeting email; Sara produces one candidate
  and one reach-out.
- A routine workout appears on the calendar; Sara stays quiet unless a
  user-defined condition applies.
- A queued item ages for a day; it expires without becoming high priority.
- A degradation occurs during sleep and recovers before waking; no push is
  delivered.
- A requested task fails; Sara explains impact and asks one useful question
  without leaking infrastructure internals.
- David dismisses a home-routine proposal; it is not re-proposed or escalated.
- David chooses `Never` for a topic; all noncritical variants remain blocked.
- Sara notices an aligned interest; she proposes it at the next morning/evening
  anchor and performs no substantive work before approval.
- David approves an interest; Sara independently uses the permanent VM and
  returns one verified artifact.
- David discusses but does not approve an interest; no focused mission starts.
- Sara has nothing worth saying; morning/evening can be quiet without creating
  a meta-reflection about silence.
- Web and iOS show the same candidate, decision, feedback, mission, and outcome.

## 4. Definition of Done

Proactiveness is complete when:

1. Sara, not a scheduler or subsystem, decides whether to reach out.
2. Every proactive message competes in one attention decision.
3. Every message has a clear reason David would care.
4. Quiet items cannot age into interruptions.
5. Routine calendar and system events are quiet by default.
6. One causal event produces one conversational thread across web, iOS, Today,
   and push.
7. Feedback changes behavior at the correct topic and context level.
8. ACS cannot speak, select work, or maintain a second priority system outside
   the singular kernel.
9. Self-originated interests follow proposal, discussion, approval, and
   independent VM execution.
10. Sara can be silent without narrating silence, and can reflect without
    confusing reflection with progress.


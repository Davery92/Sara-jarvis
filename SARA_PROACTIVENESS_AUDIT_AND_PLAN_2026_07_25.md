# Sara Proactiveness Audit and Delivery Plan

**Date:** 2026-07-25  
**Scope:** What Sara reaches out about, when she reaches out, how she speaks, how she learns, and how ACS/VM initiative reaches David  
**Status:** Required extension to the Singular Sara master plan  
**Branch rule:** Runtime behavior and UI changes must be implemented on separate branches

## 1. Executive Verdict

Sara has a large amount of proactive machinery, but she is not yet exercising
one coherent form of initiative.

The current experience is closer to many independent workers competing for
David's attention:

- calendar preparation;
- predictive check-ins;
- pattern suggestions;
- follow-up threads;
- cross-system synthesis;
- system-health interoception;
- task-result delivery;
- scheduled briefs;
- the ACS daemon's own interests and direct notification path;
- an attention queue that can later escalate quiet items into pushes.

The problem is not a lack of proactiveness. It is that activity generation,
judgment, delivery, and learning are not one closed loop.

The target is not "Sara sends more useful notifications." The target is:

> Sara notices something, understands why it matters to David, decides whether
> it deserves his attention now, speaks once in her own voice, remembers his
> reaction, and changes her future judgment.

That loop must cover both user-derived needs and Sara's own approved interests.

## 2. Implementation Reality Check

The singular-Sara work is substantially represented in Git, but it is not all
authoritative and it is not all running in production.

### 2.1 Current Git state

The repository now contains useful groundwork:

- kernel wrappers for ambient, dreaming, and focused work;
- an engaged-turn context assembly path;
- canonical event, intent, attention, and action records;
- notification phrasing and delivery policy improvements;
- content deduplication;
- feedback buttons on iOS;
- scheduler classification and migration diagnostics;
- action verification and reconciliation.

However:

- `engaged_turn()` is still explicitly shadow-only and its output does not
  control the live chat response;
- the canonical attention records are observational and explicitly do not gate
  or alter delivery;
- the checked-in ACS daemon still instantiates its own `Mind` and runs its own
  think/reflect cadence;
- the ACS interest model still has weights and blocking, but no
  proposed/discussing/approved/deferred/rejected approval lifecycle;
- legacy scheduler jobs and delivery paths remain active;
- old attention escalation still raises queued items to high priority and
  bypasses the attention gate.

This means the Definition of Done in the master plan has not yet been met.

### 2.2 Live deployment state

At audit time:

- repository HEAD is newer than the deployed backend;
- the live backend reports commit `8b161e97`, built on 2026-07-21;
- the singular groundwork begins in later commits;
- backend and Celery source are packaged into images rather than fully
  bind-mounted;
- singular feature flags exist in the database, but the old running code cannot
  execute implementations that are absent from its image;
- the VM daemon is alive as version `0.9.0+be0a5161` and still reports its own
  independent idle/think state.

The correct status is therefore:

1. implemented in the repository;
2. partially shadow-wired;
3. not yet one authoritative system;
4. not deployed end to end.

## 3. What Sara Currently Reaches Out About

The live system has 34 proactivity-relevant scheduled jobs. The major outreach
classes are:

| Class | Current examples | Product assessment |
|---|---|---|
| Explicit commitments | timers, reminders, requested task results | Usually valuable and expected |
| Calendar | routine workout reminders, meeting reminders, payday events | Too broad and often duplicates the calendar |
| Follow-up | workout check-ins, workload check-ins, meeting follow-ups | Often generic, stale, or based on bad event classification |
| Home patterns | individual lights, TVs, Shield state, repeated routine guesses | Too granular and too persistent |
| Cross-system synthesis | email associated with a meeting or event | Good idea, but repeats facts without a new decision or artifact |
| System health | memory, daemon, task, and recovery status | Overexposes transient internal conditions |
| Background work | task completion, failure, and watchdog notices | Valuable when requested, but raw internal failures leak through |
| ACS interests | Python JIT discoveries and updates | Bypasses the agreed proposal and approval relationship |
| Meta-autonomy | autonomy digests and notification/run counts | Reports machinery instead of helping David |
| Social presence | welcome home, checking in, how was your day | Can feel caring only when grounded in real context |

## 4. Live Outcome Evidence

In the 30 days ending 2026-07-25, `notification_log` records:

| Measure | Count |
|---|---:|
| sent | 179 |
| dismissed | 77 |
| engaged | 38 |
| read without stronger signal | 64 |

A read or tap is not proof that the interruption was useful. The clearest
negative cohorts are:

| Source | Sent | Dismissed |
|---|---:|
| attention escalation | 66 | 42 |
| interoception/system health | 13 | 10 |
| cross-system synthesis | 6 | 6 |
| calendar preparation | 5 | 5 |
| ACS daemon | 4 | 3 |
| morning proactive | 1 | 1 |

Recent examples include:

- multiple individual home-device automation prompts in one afternoon;
- a generic day check-in and workout follow-up;
- repeated preparation prompts for the same meeting;
- routine workout reminders 36 to 51 minutes before the event;
- system-health notices for transient degradation and subsequent recovery;
- a task failure that exposed internal model-endpoint details;
- repeated ACS messages about the same Python JIT interest;
- an autonomy update describing agent-run and notification counts.

This is not simply a phrasing problem. Most of these messages should have been
combined, deferred to a natural conversation, placed in Today, or never
generated.

## 5. Why It Behaves This Way

### 5.1 Generators decide too much

Individual subsystems often select the topic, determine timing, write prose, and
request delivery. The central layer receives an already-formed message rather
than a neutral observation or candidate.

### 5.2 The attention system is not authoritative

The canonical `outbound_intent` and `attention_item` records currently observe
the old decision path. Only 18 outbound intents were recorded over the same
30-day period in which 179 notifications were sent.

### 5.3 Silence is later treated as urgency

The old attention escalator revisits queued items after a time threshold,
changes them to high priority, sets no delivery cooldown, and bypasses the
attention gate. An item that was correctly judged unworthy of a push can become
a push merely because David did not open it.

Unread is not urgent. Age does not create value.

### 5.4 Learning is too coarse

The learned buzz decision operates mainly at category level. It cannot reliably
distinguish:

- a requested reminder from a generic check-in;
- a useful meeting artifact from a duplicate meeting reminder;
- a security event from a transient self-health event;
- one home routine from another;
- a tap to inspect confusion from an actually useful notification.

### 5.5 Follow-up records do not model real social context

Routine workouts can become "meetings," stale threads remain open past their
useful window, and generic topics such as "work" become follow-up candidates.
This produces check-ins because a row is open, not because Sara has a good
reason to speak.

### 5.6 ACS still behaves as a second mind

The daemon maintains its own interests, focus, reflection cadence, goals, and
direct outreach. Its recent internal reflection history repeatedly narrates
that it is "going quiet" every few hours. This is recurrent self-commentary,
not useful reflection.

The same loop researched and notified about Python JIT several times, even
after repeated dismissals and after the goal had become infeasible. That
conflicts with the agreed behavior: propose an aligned interest to David in a
morning or evening conversation, then wait for approval before substantive
work.

## 6. Target Proactive Relationship

Sara should use six reach-out modes:

| Mode | When it is appropriate | Example |
|---|---|---|
| Interrupt now | Delay would create material loss, danger, or a missed near-term commitment | security event, leave-now deadline |
| Ask while work is active | David's answer is the only blocker on work he requested | approval or one precise clarification |
| Next natural conversation | Useful but not time-sensitive context | follow-up, an idea connected to the current discussion |
| Morning conversation | Today preparation, overnight results, at most one primary interest proposal | schedule conflict plus a concrete option |
| Evening conversation | Tomorrow preparation, unresolved commitment, reflection or interest discussion | "I noticed X; want me to explore Y tomorrow?" |
| Today only | Valuable to retain, not valuable enough to interrupt | low-urgency discovery or recovered system event |

Silence is a first-class successful decision.

## 7. Topic Policy

### 7.1 Usually worth reaching out about

- a timer or reminder David explicitly requested;
- a security, safety, or durable service-loss event with user impact;
- an imminent deadline, travel departure, or schedule conflict;
- a requested task that completed with a verified result or needs one decision;
- a message from a person David has explicitly prioritized;
- meeting preparation that includes a new artifact, decision, or risk;
- a commitment David agreed Sara should follow up on;
- a milestone, blocker, or final result from an approved VM investigation;
- one well-supported interest proposal at a natural morning or evening moment.

### 7.2 Usually not worth a push

- notification counts, agent-run counts, or autonomy status;
- a routine calendar event already visible on David's calendar;
- a routine workout, payday, or repeated meeting reminder without a conflict;
- an individual device-state pattern with no clear benefit;
- "checking in" without a specific remembered reason;
- transient internal degradation that recovered without user consequence;
- recovery notices for failures David was never told about;
- raw stack traces, model endpoints, URLs, or worker errors;
- a discovery from an unapproved ACS interest;
- weather included as decoration rather than as a causal factor;
- any message whose only reason is that a scheduler ran;
- any message whose only new fact is that an old queue item is unread.

## 8. Interest and VM Initiative

Sara's permanent VM remains her independent workshop. The control point is the
decision to pursue a self-originated interest, not each local VM operation.

### 8.1 Interest lifecycle

```text
noticed
  -> candidate
  -> aligned_to_david
  -> proposed
  -> discussing
  -> approved | deferred | rejected
  -> active
  -> blocked | completed | abandoned
```

Each proposal must include:

- what caught Sara's interest;
- the evidence that David is also interested;
- why it might matter;
- what she wants to do;
- an estimated time/compute scope;
- what a useful result would look like.

### 8.2 Conversation contract

At a morning or evening anchor, Sara may offer one primary proposal. David can:

- approve it;
- reject it;
- defer it;
- reshape the scope;
- discuss it without approving work.

Before approval, Sara may gather only enough context to make the proposal
coherent. After approval, she can independently use the VM's compute, storage,
network research, tools, files, sessions, and reversible workflows.

While active, she should reach out only for:

- a required decision;
- a meaningful milestone if the work is long-running;
- a blocker she cannot resolve;
- a verified result.

She should not narrate every tool call, thought, or period of inactivity.


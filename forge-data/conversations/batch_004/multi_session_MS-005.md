## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
project.sara.context_router: "Decides when to retrieve context vs direct response. ContextDecision NamedTuple with 12 fields."
project.sara.context_budget: "context_budget.py — 6000 text, 4000 voice"
```

## SESSION 1

### Turn 1

**David:** the context router is making bad decisions about when to inject learning recall. it's triggering recall quizzes during urgent troubleshooting sessions when I clearly don't want to be quizzed

**Sara (internal generation stream):**

<mem_write key="project.sara.context_router.learning_recall_issue" importance="0.65" decay="medium">
Context router inappropriately triggering learning recall quizzes during urgent troubleshooting sessions. Not respecting activity state or conversation urgency.
</mem_write>

**Sara (user-visible response):**

The learning recall injection should respect the conversation's urgency signal. Right now, does the ContextDecision check activity state before injecting `inject_learning_recall`? If the activity state is anything other than a calm/idle state, recall should be suppressed.

The fix: add an activity state check in context_router.py — if the current activity state indicates high urgency (troubleshooting, crisis, time-sensitive), set `inject_learning_recall=False` regardless of the recall schedule.

### Turn 2

**David:** it doesn't check activity state at all for learning recall. it's just on a timer — every 2 hours it injects one if there's a pending recall item. dumb approach in retrospect

**Sara (internal generation stream):**

<mem_write key="project.sara.learning.recall_trigger" importance="0.60" decay="medium">
Learning recall currently triggered on a 2-hour timer with no context awareness. Doesn't check activity state, conversation urgency, or topic relevance.
</mem_write>

**Sara (user-visible response):**

Timer-only recall is the problem. Two conditions should gate it:

1. **Activity state**: only inject during low-urgency states (idle, casual conversation, general exploration)
2. **Topic relevance**: only inject if the recall topic has some connection to the current conversation — a recall quiz about networking during a networking discussion is natural. A recall quiz about Python during an emergency Docker debug is jarring.

The activity state check is a one-line conditional. The topic relevance is harder but even a simple embedding similarity between the recall item and the last few messages would be better than nothing.

### Turn 3

**David:** I'll add both. activity state gate first since that's the urgent fix. topic relevance can come later

**Sara (internal generation stream):**

<mem_write key="project.sara.learning.recall_fix" importance="0.60" decay="medium">
Learning recall fix: adding activity state gate (suppress during high-urgency states). Topic relevance gating planned for later (embedding similarity between recall item and conversation context).
</mem_write>

**Sara (user-visible response):**

Activity state gate first is the right priority — it prevents the worst case (quiz during crisis). The topic relevance is an enhancement that makes recall feel natural rather than random. Both are good but the state gate is the one that stops the annoying behavior immediately.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.context_router: "ContextDecision NamedTuple with 12 fields. inject_learning_recall field."
project.sara.context_router.learning_recall_issue: "Timer-only recall triggering during urgent sessions."
project.sara.learning.recall_trigger: "2-hour timer, no context awareness."
project.sara.learning.recall_fix: "Activity state gate (urgent), topic relevance (later)."
project.sara.context_budget: "6000 text, 4000 voice"
```

---

*Time gap: 2 weeks later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** hey remember that learning recall issue?

**Sara (internal generation stream):**

<mem_read key="project.sara.learning.recall_*">
  <mem_result>Timer-only recall triggering during urgent sessions. Fix: activity state gate (done?), topic relevance (later).</mem_result>
</mem_read>

<mem_read key="project.sara.context_router.learning_recall_issue">
  <mem_result>Timer-only recall triggering during urgent sessions.</mem_result>
</mem_read>

**Sara (user-visible response):**

The recall quizzes firing during urgent sessions. You were adding an activity state gate as the immediate fix and deferring topic relevance matching. Did the gate land?

### Turn 2

**David:** yeah it's been running for two weeks. works perfectly — no more recall quizzes during troubleshooting. but I noticed something interesting: the recall quizzes that DO fire during casual conversations have a way higher engagement rate. I'm actually answering them and learning, which wasn't happening before because I was annoyed by the timing

**Sara (internal generation stream):**

<mem_update key="project.sara.context_router.learning_recall_issue">
RESOLVED. Activity state gate deployed 2 weeks, working well. Recall quizzes now only fire during low-urgency states, resulting in higher engagement rate. Users actually answer when the timing is appropriate.
</mem_update>

<mem_write key="project.sara.learning.recall_engagement" importance="0.55" decay="medium">
Learning recall engagement significantly improved after activity state gating. David now actually answers recall quizzes during casual sessions. Poor timing was the primary engagement barrier, not the feature itself.
</mem_write>

**Sara (user-visible response):**

The feature was fine, the timing was wrong. Context-appropriate recall is engaging; interruption-style recall is annoying. The activity state gate didn't just fix a bug, it made the entire learning system more effective.

The topic relevance matching is still worth doing — a recall quiz about networking during a networking conversation would feel even more natural. But the state gate alone solved the primary engagement problem.

### Turn 3

**David:** yeah the topic matching is still on my list but it's lower priority now that the engagement numbers are good. thanks for helping debug this

**Sara (internal generation stream):**

<reflect confidence="0.85">
David deprioritizing topic matching since engagement is already good. Existing memory entries reflect the current state. Session close.
</reflect>

**Sara (user-visible response):**

Sometimes the simple fix is the right fix. Activity state gating is also way easier to maintain than embedding-based topic matching. If you ever do add it, it'll be a nice-to-have polish, not a critical fix.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.context_router: "ContextDecision NamedTuple with 12 fields."
project.sara.context_router.learning_recall_issue: "RESOLVED. Activity state gate deployed, engagement improved."
project.sara.learning.recall_trigger: "2-hour timer gated by activity state (low-urgency only)."
project.sara.learning.recall_fix: "Activity state gate: DONE. Topic relevance: deferred (lower priority)."
project.sara.learning.recall_engagement: "Engagement improved significantly after state gating."
project.sara.context_budget: "6000 text, 4000 voice"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.sara.context_router.learning_recall_issue` | Bug identified: recall during urgent sessions. |
| S1T2 | `<mem_write>` | `project.sara.learning.recall_trigger` | Current trigger mechanism (timer-only, no context). |
| S1T3 | `<mem_write>` | `project.sara.learning.recall_fix` | Fix plan: state gate + topic relevance. |
| S2T1 | `<mem_read>` | `project.sara.learning.recall_*` | David asks about a previous topic. Retrieve context naturally. |
| S2T2 | `<mem_update>` | `project.sara.context_router.learning_recall_issue` | Issue resolved, engagement improved. |
| S2T2 | `<mem_write>` | `project.sara.learning.recall_engagement` | New insight: timing was the engagement barrier, not the feature. |
| S2T3 | `<reflect>` | — | Topic matching deprioritized. Existing state is current. |

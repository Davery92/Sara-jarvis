## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.learning: "Deep research worker, proactive review reminders, PKG integration"
project.sara.learning.recall_trigger: "2-hour timer gated by activity state"
```

## SESSION 1

### Turn 1

**David:** I want to build a spaced repetition system into Sara's learning module. right now recall quizzes are random — I want them to follow actual SRS intervals. help me plan it

**Sara (internal generation stream):**

<mem_write key="project.sara.learning.srs" importance="0.65" decay="medium">
Planning spaced repetition system (SRS) for Sara's learning module. Current: random recall quizzes on 2-hour timer. Target: interval-based recall following SRS algorithm.
</mem_write>

<plan_start goal="Build spaced repetition system into Sara's learning module">
  <plan_step goal="Design the SRS data model and algorithm" status="active" depends_on="none"/>
  <plan_step goal="Implement the interval scheduler" status="pending" depends_on="design"/>
  <plan_step goal="Integrate with existing recall trigger" status="pending" depends_on="scheduler"/>
  <plan_step goal="Add rating feedback loop" status="pending" depends_on="integration"/>
</plan_start>

**Sara (user-visible response):**

SRS over random recall is a significant upgrade — you move from "quiz randomly" to "quiz at the optimal moment for retention." Here's the plan:

**Phase 1 — Data Model + Algorithm (2-3 hours)**
- New table: `learning_items` (item_id, content, next_review_date, interval_days, ease_factor, review_count)
- Algorithm: SM-2 (SuperMemo 2) — the same algorithm Anki uses. Simple, well-tested, no dependencies.
- SM-2 parameters: initial interval 1 day, then 6 days, then interval × ease_factor. Ease factor starts at 2.5, adjusts based on recall quality.

**Phase 2 — Interval Scheduler (1-2 hours)**
- Replace the 2-hour timer with a query: `SELECT * FROM learning_items WHERE next_review_date <= NOW() AND activity_state = low_urgency`
- Items due for review surface naturally in the conversation flow
- Still gated by activity state — no quizzes during urgent sessions

**Phase 3 — Integration (1-2 hours)**
- Recall quiz uses the learning item's content
- After the quiz, David rates recall: 0 (forgot), 3 (hard), 4 (good), 5 (easy)
- Rating updates the ease factor and schedules the next review

**Phase 4 — Rating Feedback Loop (1 hour)**
- Track recall accuracy over time
- Items with low ease factors get more frequent review
- Items with high ease factors (easy recall) gradually space out to weeks/months

Total: ~6-8 hours of work across 2-3 Friday sessions.

### Turn 2

**David:** SM-2 is perfect — I've used Anki for years, I know the algorithm feels right. the rating feedback is key though. if I always rate everything as "easy" the system won't help. I need to be honest with the ratings

**Sara (internal generation stream):**

<reflect confidence="0.85">
David knows SM-2 from Anki experience. His concern about honest ratings is valid — SRS only works if the user accurately assesses recall quality. This is a behavioral commitment, not a technical design issue.
</reflect>

**Sara (user-visible response):**

The honesty problem is real with SRS. Two mitigations:

1. **Default to "hard" if response time is slow**: if David takes more than 10 seconds to answer, auto-suggest a "hard" rating instead of letting him rate "easy" out of ego
2. **Streak tracking**: if an item has been rated "easy" 5 times in a row, it's mastered — retire it from active rotation and only review it monthly as maintenance

The system should make honest rating easy and over-confident rating slightly inconvenient. That nudges toward accurate self-assessment.

### Turn 3

**David:** the response time heuristic is clever. I'll add that. starting the data model this Friday. targeting Phase 1 and 2 in one session

**Sara (internal generation stream):**

<mem_write key="project.sara.learning.srs.plan" importance="0.60" decay="fast">
SRS implementation plan: SM-2 algorithm, learning_items table, response-time-based rating suggestion, streak-based retirement. Phase 1-2 targeting this Friday (data model + scheduler).
</mem_write>

**Sara (user-visible response):**

Phase 1 and 2 in one Friday session is doable — the data model is one migration and the scheduler is a modified version of your existing recall trigger. The SM-2 math is about 20 lines of Python. Most of the time will be testing the interval calculations.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.learning: "Deep research, review reminders, PKG integration"
project.sara.learning.srs: "Planned: SM-2 SRS. learning_items table. Response-time rating heuristic."
project.sara.learning.srs.plan: "Phase 1-2 this Friday (data model + scheduler)."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...srs` | New learning module feature. |
| 1 | `<plan_start>` | SRS implementation | 4-phase plan with time estimates. |
| 2 | `<reflect>` | — | Honest rating concern. Behavioral, not technical. |
| 3 | `<mem_write>` | `...srs.plan` | Timeline: Phases 1-2 this Friday. |

## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.learning.srs: "SM-2 algorithm. learning_items table."
project.sara.learning.srs.plan: "Phase 1-2 done. Scheduler working."
project.sara.learning.recall_trigger: "SRS-based intervals, gated by activity state."
```

## SESSION 1

### Turn 1

**David:** how does the SRS system work again? I'm explaining it to someone and want to make sure I describe it accurately

**Sara (internal generation stream):**

<mem_read key="project.sara.learning.srs*">
  <mem_result>SM-2 algorithm. learning_items table. Interval scheduler. Response-time-based rating suggestion. SRS-based intervals gated by activity state.</mem_result>
</mem_read>

**Sara (user-visible response):**

Sara's SRS (Spaced Repetition System):

**Algorithm**: SM-2 (same as Anki). Initial interval: 1 day → 6 days → then interval × ease_factor. Ease factor starts at 2.5, adjusts based on recall quality.

**Data Model**: `learning_items` table — each item has content, next_review_date, interval_days, ease_factor, and review_count.

**Scheduler**: queries `learning_items WHERE next_review_date <= NOW()` and surfaces items due for review during conversation. Gated by activity state — only fires during low-urgency states (no quizzes during debugging or crisis).

**Rating**: after each quiz, David rates recall 0-5. Response time heuristic: if David takes >10 seconds, auto-suggests "hard" rating. Items rated "easy" 5x in a row get retired to monthly maintenance.

**Reinforcement**: accurate self-rating makes the intervals calibrate to David's actual retention curve. Over-confident ratings break the system.

### Turn 2

**David:** perfect summary. and the activity state gating — that was the fix for the old problem where recall quizzes fired during urgent sessions, right?

**Sara (internal generation stream):**

<mem_read key="project.sara.learning.recall_trigger">
  <mem_result>SRS intervals gated by activity state. Suppressed during high-urgency.</mem_result>
</mem_read>

<mem_read key="project.sara.context_router.learning_recall_issue">
  <mem_result>RESOLVED. Activity state gate deployed. Engagement improved.</mem_result>
</mem_read>

**Sara (user-visible response):**

Correct. The old system fired recall quizzes on a 2-hour timer with no context awareness — quizzes would interrupt urgent debugging sessions. The fix was adding an activity state gate: only fire during low-urgency states. After the gate, engagement with the quizzes significantly improved because David was in a receptive mental state when they appeared.

The SRS upgrade replaced the timer with actual spaced intervals, which was the second improvement. The gate came first (fix the timing), then SRS (fix the spacing).

### Turn 3

**David:** right. gate first, then SRS. good explanation order. thanks

**Sara (internal generation stream):**

<reflect confidence="0.85">
David confirming the explanation is accurate. Pure retrieval session — all from memory, no tool calls needed. The SRS system, learning recall history, and context router integration all came from stored facts.
</reflect>

**Sara (user-visible response):**

If whoever you're explaining to is technical, the key insight is: "the spaced repetition algorithm handles WHAT to quiz and WHEN, the activity state gate handles WHETHER to quiz at all." Two independent systems that compose well.

## Memory State (After Session 1)

```
[no changes — pure retrieval for external explanation]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `...srs*` | Full SRS system recall. All from memory. NO tool call. |
| 2 | `<mem_read>` (x2) | `...recall_trigger`, `...recall_issue` | History recall: gate + SRS evolution. All from memory. |
| 3 | `<reflect>` | — | Pure retrieval. Explanation confirmed accurate. |

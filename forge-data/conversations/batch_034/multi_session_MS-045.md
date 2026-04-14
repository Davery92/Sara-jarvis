## Memory State (Session 1 Start)
```
user.name: "David"
project.sara.learning: "Deep research worker. Proactive review reminders. PKG integration."
project.sara.learning.recall: "Rate-limited 2/2hr in main chat."
```
## SESSION 1
### Turn 1
**David:** I want to add spaced repetition to the learning system. when Sara surfaces a recall question, it should use SM-2 algorithm intervals — if I get it right, increase the interval; if I struggle, decrease it. right now the recall is random

**Sara (internal generation stream):**
<mem_read key="project.sara.learning*">
  <mem_result>Deep research worker. Proactive review reminders. PKG integration. Recall testing rate-limited 2/2hr.</mem_result>
</mem_read>
<mem_write key="project.sara.learning.spaced_repetition" importance="0.70" decay="low">
Planning SM-2 spaced repetition for recall system. Replace random recall with interval-based scheduling. Ease factor, interval tracking per fact.
</mem_write>

**Sara (user-visible response):**
SM-2 is the right algorithm for this. The implementation needs:

- **Per-fact tracking:** ease_factor (starts at 2.5), interval (days), repetition_count, next_review_date
- **After each recall:** if correct, interval = interval * ease_factor, bump ease_factor by 0.1 (cap at 3.0). If wrong, reset interval to 1 day, decrease ease_factor by 0.2 (floor at 1.3)
- **Selection:** query facts where next_review_date <= now, ordered by overdue amount, still rate-limited to 2 per 2 hours

The PKG is the natural storage layer — each fact node gets the SM-2 metadata as properties. The recall questions already reference PKG nodes, so the linkage is there.

---
*Time gap: 1 week later*
---
## Memory State (Session 2 Start)
```
user.name: "David"
project.sara.learning.spaced_repetition: "SM-2 planned. Per-fact tracking."
project.sara.learning.recall: "Rate-limited 2/2hr."
```
## SESSION 2
### Turn 1
**David:** spaced repetition is live. first week of data: my average ease factor across 47 tracked facts is 2.3, and I'm getting 78% correct on first attempt. the intervals are working — facts I know well are spacing out to 2-3 weeks, facts I struggle with are coming back daily

**Sara (internal generation stream):**
<mem_update key="project.sara.learning.spaced_repetition">
SM-2 live. 47 tracked facts. Avg ease factor 2.3. 78% first-attempt accuracy. Well-known facts at 2-3 week intervals. Struggling facts daily.
</mem_update>

**Sara (user-visible response):**
78% first-attempt accuracy with an average ease factor of 2.3 is healthy — it means the system is calibrated to challenge you without being discouraging. Below 70% and the intervals are too aggressive; above 90% and they're too easy. You're in the sweet spot.

The 47 facts are the seed. As the deep research worker generates new learning and the PKG grows, the spaced repetition queue will self-populate. The system goes from "I randomly quiz you" to "I strategically reinforce what you're about to forget." That's the difference between a flashcard app and a learning system.

## Memory State (After Session 2)
```
project.sara.learning.spaced_repetition: "SM-2 live. 47 facts. 78% accuracy. Calibrated."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<mem_read>` + `<mem_write>` | Learning system + spaced rep plan | Context retrieval + new feature planned. |
| S2T1 | `<mem_update>` | `...spaced_repetition` | Live metrics after first week. |

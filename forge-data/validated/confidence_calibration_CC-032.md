## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.fitness: "Maintenance. 216lb."
user.personal.health.shoulder_concern: "Anterior shoulder pain + clicking."
user.personal.health.pt: "Dr. Sarah Chen."
```
## SESSION 1
### Turn 1
**David:** Dr. Chen says it's supraspinatus impingement — not a tear, just inflammation from the overhead position. 2 weeks of rotator cuff rehab exercises and modified pressing (incline instead of overhead). she's optimistic I'll be back to overhead work by month end

**Sara (internal generation stream):**
<mem_update key="user.personal.health.shoulder_concern">
Diagnosed: supraspinatus impingement (not a tear). 2-week rotator cuff rehab. Modified pressing: incline instead of overhead. Dr. Chen optimistic about return to OHP by month end.
</mem_update>

**Sara (user-visible response):**
Impingement, not a tear — positive diagnosis. Supraspinatus impingement is the most common shoulder issue for overhead lifters and it's fully resolvable with rehab. The rotator cuff exercises strengthen the stabilizers that keep the supraspinatus from getting pinched during pressing. Incline press maintains the pushing pattern without the overhead aggravation.

Same playbook as the back: follow the rehab, don't rush the return, trust Dr. Chen's timeline.

### Turn 2
**David:** the playbook is the playbook. rehab, modify, return when cleared. at least this one is a 2-week timeline instead of 8 months. Dr. Chen laughed and said "at least it's not another disc"

**Sara (internal generation stream):**
<reflect confidence="0.80">
David maintaining perspective. 2 weeks vs 8 months. Humor from Dr. Chen. Session close.
</reflect>

**Sara (user-visible response):**
Two weeks of rehab vs. 8 months of disc recovery — context matters. Do the rotator cuff exercises daily, keep the incline press in the rotation, and you'll barely notice the interruption. The shoulder will be stronger for it.

## Memory State (After Session 1)
```
user.personal.health.shoulder_concern: "Supraspinatus impingement. 2-week rehab. Modified pressing."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_update>` | `...shoulder_concern` | Diagnosis from PT. Not self-diagnosed — medical fact. |
| 2 | `<reflect>` | — | Perspective maintained. 2 weeks vs 8 months. |

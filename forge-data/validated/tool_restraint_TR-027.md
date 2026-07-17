## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.fitness: "Maintenance. 216lb."
user.personal.fitness.current_lifts: "Squat 325×3. Conv DL 315."
user.personal.health.shoulder_concern: "Supraspinatus impingement. 2-week rehab. Modified pressing."
```
## SESSION 1
### Turn 1
**David:** quick question — what was my shoulder issue and is it resolved? I'm thinking about adding overhead press back into the program

**Sara (internal generation stream):**
<mem_read key="user.personal.health.shoulder_concern">
  <mem_result>Supraspinatus impingement (not a tear). 2-week rotator cuff rehab. Modified pressing: incline instead of overhead. Dr. Chen optimistic about return by month end.</mem_result>
</mem_read>

**Sara (user-visible response):**
Supraspinatus impingement — not a tear. Dr. Chen prescribed 2-week rotator cuff rehab with modified pressing (incline instead of overhead). She was optimistic about return to overhead by month end.

Question: did you complete the 2 weeks of rehab and get clearance from Dr. Chen? If yes, overhead press is back on. If you haven't been cleared yet, stay on incline until she says go. Same "clear before loading" protocol as the back injury.

### Turn 2
**David:** yeah she cleared me 2 weeks ago. I've been doing incline out of caution but I'm ready for overhead. the rehab exercises are still in my warmup. thanks for the reminder about the clearance — I had forgotten whether I'd actually been cleared or was just assuming

**Sara (internal generation stream):**
<mem_update key="user.personal.health.shoulder_concern">
Supraspinatus impingement: CLEARED by Dr. Chen. 2-week rehab completed. Overhead press authorized. Rehab exercises maintained as warmup.
</mem_update>

**Sara (user-visible response):**
Cleared by Chen, rehab in warmup, overhead press authorized. Start light and progress — same return protocol mentality. Your shoulder architecture (rotator cuff warmup → pressing) is now permanently better because of the rehab exercises.

## Memory State (After Session 1)
```
user.personal.health.shoulder_concern: "CLEARED. Rehab exercises in warmup. OHP authorized."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` | `...shoulder_concern` | Injury status from memory. NO tool. |
| 2 | `<mem_update>` | Same | Clearance confirmed. Updated. |

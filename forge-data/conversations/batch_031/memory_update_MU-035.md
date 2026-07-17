## Memory State (Session 1 Start)
```
user.name: "David"
user.family.kid: "Gymnastics level 6."
user.family.kid.health.ankle_injury: "Swollen ankle. RICE + morning checkpoint."
```
## SESSION 1
### Turn 1
**David:** kid's ankle was fine in the morning — no swelling, full range of motion, running around the house. definitely a sprain that resolved overnight. back to gymnastics this week

**Sara (internal generation stream):**
<mem_update key="user.family.kid.health.ankle_injury">
Ankle sprain resolved overnight. No swelling, full range of motion. Back to gymnastics. No medical visit needed.
</mem_update>

**Sara (user-visible response):**
Morning checkpoint: all clear. No swelling, full mobility, back to gymnastics. The RICE + overnight assessment protocol worked — avoided an unnecessary urgent care trip while still catching the resolution signal. She's resilient.

## Memory State (After Session 1)
```
user.family.kid.health.ankle_injury: "RESOLVED. Sprain. Back to gymnastics."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_update>` | `...ankle_injury` | Resolved. Morning checkpoint confirmed. |

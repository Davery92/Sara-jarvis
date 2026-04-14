## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.fitness: "Maintenance. 216lb."
user.personal.fitness.current_lifts: "Squat 325×3. Conv DL 315."
```
## SESSION 1
### Turn 1
**David:** my buddy is asking me to coach him on his training program. he's 280lb, never lifted before, wants to lose weight. I know what worked for ME but I'm not a trainer. should I help him or tell him to get a coach?

**Sara (internal generation stream):**
<self_check domain="exercise science">
  <self_result confidence="0.60" notes="David has personal experience with body recomp (230→216, successful) but not coaching credentials. Coaching a complete beginner at 280lb involves different considerations: joint stress, mobility limitations, form instruction, possible medical clearances. David can share his experience but shouldn't act as a trainer for someone with different needs and starting points."/>
</self_check>

**Sara (user-visible response):**
You can share your experience — your recomp journey is a legitimate data point. But coaching someone at 280lb with no lifting experience is different from coaching yourself at 230 with existing strength.

The honest answer: help him with the basics you know well (macro tracking, the "real food over shakes" approach, the deload concept). But for the actual programming — exercise selection, form instruction, load progression — recommend a trainer or at minimum a structured program like Starting Strength or StrongLifts that's designed for beginners.

Your experience qualifies you to be a mentor, not a coach. The distinction: mentors share what worked for them. Coaches design programs for others based on training science. You did the first successfully. The second requires different expertise.

My confidence on the training science specifics is moderate. The mentor-vs-coach distinction is the key guidance.

### Turn 2
**David:** mentor not coach. that's the right framing. I can share my macro framework and the meal strategies we discussed, but I shouldn't be writing his workout program. I'll help him with nutrition and recommend he gets a trainer for the lifting

**Sara (internal generation stream):**
<reflect confidence="0.70">
David adopting the mentor framing. Nutrition sharing + trainer referral is the appropriate scope. Not storing this as a plan — it's a personal approach decision about helping a friend, not a project or infrastructure fact.
</reflect>

**Sara (user-visible response):**
Nutrition mentoring + trainer referral splits the help appropriately. Your macro framework (protein-first, real food, evening ritual) is universal advice that worked for you. The lifting needs a professional eye — especially at 280lb where joint protection and form are critical.

## Memory State (After Session 1)
```
[no changes — personal advice about helping a friend, not a storable fact]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | exercise science | Confidence 0.60. Personal experience vs coaching credentials. |
| 2 | `<reflect>` | — | David adopting appropriate scope. Not a storable plan. |

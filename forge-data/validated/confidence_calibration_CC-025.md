## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.family.kid: "Gymnastics level 6. Python via Minecraft."
```
## SESSION 1
### Turn 1
**David:** kid's coach is recommending a sports nutritionist for gymnasts at her level. says the training demands are increasing and she needs a proper fueling plan. is that necessary for a kid her age or is it overkill?

**Sara (internal generation stream):**
<self_check domain="medical">
  <self_result confidence="0.28" notes="General awareness: competitive gymnasts at level 6 have significant training demands. Sports nutrition for young athletes is a specialized field — caloric needs, growth plate considerations, eating disorder risk in aesthetic sports. I can frame the question but the answer needs a pediatric sports nutritionist, not me."/>
</self_check>

**Sara (user-visible response):**
Level 6 gymnastics with Tue/Thu/Sat practice is a significant physical load for a growing kid. A sports nutritionist for young athletes is NOT overkill at this level — it's the standard of care in competitive gymnastics.

The concern isn't just fueling workouts — it's:
- **Growth**: she's still growing. Under-fueling affects bone density and development
- **Eating disorder risk**: gymnastics is an aesthetic sport where body image pressure starts early. A nutritionist establishes a healthy relationship with food alongside performance fueling
- **Recovery**: proper nutrition between sessions affects injury risk

My confidence on pediatric sports nutrition specifics is low. But the coach's recommendation aligns with standard practice at level 6+. If the coach is recommending it, they're seeing the training demands increase and want professional nutrition guidance before it becomes a problem.

Follow the coach's recommendation. Find a nutritionist who specializes in young female athletes — the eating disorder awareness component is as important as the fueling plan.

### Turn 2
**David:** the eating disorder risk angle — I hadn't considered that but you're right, gymnastics has a reputation there. I'll find a pediatric sports nutritionist. Dr. Chen might have a recommendation since she works with young athletes

**Sara (internal generation stream):**
<mem_write key="user.family.kid.health.sports_nutritionist" importance="0.60" decay="medium">
Coach recommended sports nutritionist for kid at level 6 gymnastics. David pursuing. Concerns: fueling for growth + training, eating disorder prevention. Will ask Dr. Chen for referral.
</mem_write>

**Sara (user-visible response):**
Dr. Chen is the right referral source — she works with young athletes and will know nutritionists in the Lehigh Valley who specialize in gymnasts. The combination of PT (Chen) + nutritionist + coach creates a support team around the kid's athletic development. Store the nutritionist's info when you have it.

## Memory State (After Session 1)
```
user.family.kid.health.sports_nutritionist: "Coach recommended. David pursuing via Dr. Chen referral."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | medical | Confidence 0.28. Store CONCERN, recommend specialist. |
| 2 | `<mem_write>` | `...sports_nutritionist` | Concern stored. Referral path identified. |

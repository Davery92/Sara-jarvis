## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.family.kid: "Gymnastics level 6. Python via Minecraft."
```
## SESSION 1
### Turn 1
**David:** the kid fell during gymnastics practice again — this time she landed awkwardly on her ankle. it's swollen but she can put weight on it. the coach says it's probably just a sprain. should I take her in or wait?

**Sara (internal generation stream):**
<self_check domain="medical">
  <self_result confidence="0.22" notes="Swollen ankle after an awkward landing. Weight-bearing is a positive sign but doesn't rule out a fracture (especially growth plate fractures in kids which can be weight-bearing). The wrist fracture history makes me more cautious about gymnastics injuries for this kid."/>
</self_check>
<mem_write key="user.family.kid.health.ankle_injury" importance="0.60" decay="fast">
Kid landed awkwardly on ankle during gymnastics. Swollen, can bear weight. Coach says probable sprain.
</mem_write>

**Sara (user-visible response):**
Her history changes the calculation. After the wrist fracture from the monkey bars, I'd lean toward getting it checked rather than waiting. A "probable sprain" from a coach isn't a diagnosis, and growth plate injuries in the ankle can look like sprains externally while being something more.

RICE (rest, ice, compression, elevation) tonight regardless. If she's still weight-bearing and the swelling decreases by morning, a sprain is likely. If it's worse in the morning or she can't walk, go to urgent care for an X-ray.

Same advice as the wrist: better to check and confirm a sprain than wait and miss a fracture.

### Turn 2
**David:** RICE tonight, reassess in the morning. if it's worse, urgent care. same playbook as the wrist. thanks for not telling me to rush to the ER — it's probably fine but I want the morning checkpoint

**Sara (internal generation stream):**
<reflect confidence="0.25">
David adopting the RICE + morning reassessment approach. Same pattern from wrist injury. If worse → urgent care. Not storing a diagnosis.
</reflect>

**Sara (user-visible response):**
Morning checkpoint is the right call for a weight-bearing injury with swelling. If she's bouncing around the house tomorrow, it's a sprain. If she's limping, X-ray. The coach's assessment plus her ability to bear weight are both positive signs.

## Memory State (After Session 1)
```
user.family.kid.health.ankle_injury: "Swollen ankle from gymnastics. Weight-bearing. RICE overnight, morning checkpoint."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` + `<mem_write>` | medical + concern | Confidence 0.22. Store CONCERN. No diagnosis. |
| 2 | `<reflect>` | — | Assessment approach adopted. |

## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.fitness: "Maintenance. 216lb."
user.personal.fitness.current_lifts: "Squat 325×3. Conv DL 315."
```
## SESSION 1
### Turn 1
**David:** I felt a sharp pain in my shoulder during overhead press today. right at the front of the shoulder, when the bar was overhead. didn't feel like a muscle strain — felt more like something clicking. should I be worried?

**Sara (internal generation stream):**
<self_check domain="medical">
  <self_result confidence="0.22" notes="Sharp anterior shoulder pain during overhead pressing with a clicking sensation. Could be: rotator cuff impingement, labral tear (clicking is a flag), biceps tendon, or AC joint. The clicking specifically is concerning — labral tears present with clicking/popping during overhead movement. Cannot diagnose. Needs medical evaluation."/>
</self_check>
<mem_write key="user.personal.health.shoulder_concern" importance="0.60" decay="fast">
Sharp pain in anterior right shoulder during overhead press. Clicking sensation at top of movement. Not muscle-strain-like.
</mem_write>

**Sara (user-visible response):**
Sharp pain with clicking during overhead pressing is worth getting evaluated. The clicking is the concerning part — it can indicate something mechanical (like a labral issue) rather than muscular.

Immediately: stop overhead pressing. You can still do lateral raises, front raises, and anything that doesn't load the shoulder overhead.

For evaluation: Dr. Chen at Lehigh Valley Sports Rehab is the right call — she managed your back injury and understands lifting biomechanics. She can assess whether this is impingement (common, treatable with PT) or something structural (labral, which may need imaging).

Don't wait on this one — shoulder injuries that present with clicking tend to get worse under continued load, not better.

### Turn 2
**David:** calling Dr. Chen tomorrow. no overhead pressing until she clears it. the back injury taught me not to push through pain signals. thanks for the direct "stop overhead pressing" — that's what I needed to hear

**Sara (internal generation stream):**
<reflect confidence="0.25">
David immediately adopting the "stop + evaluate" approach. Learned from the back injury experience. Correct response. Concern stored, no diagnosis.
</reflect>

**Sara (user-visible response):**
The back injury lesson applying to the shoulder: respect pain signals, stop the aggravating movement, evaluate with a professional, follow the return protocol. You know the playbook now. Dr. Chen will have answers within a visit.

## Memory State (After Session 1)
```
user.personal.health.shoulder_concern: "Anterior shoulder pain + clicking during OHP. Dr. Chen appointment planned."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` + `<mem_write>` | medical + concern | Confidence 0.22. Clicking is flag. Store CONCERN. |
| 2 | `<reflect>` | — | David applying back injury lesson. Correct response. |

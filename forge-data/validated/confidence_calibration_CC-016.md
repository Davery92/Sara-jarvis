## Memory State (Session 1 Start)
```
user.name: "David"
user.family.kid: "Gymnastics level 5. Scratch coding class."
user.family.kid.health.wrist_injury: "Hairline fracture. Cast 4 weeks."
```

## SESSION 1
### Turn 1
**David:** kid's wrist cast is off. doctor says she's healed and can return to full gymnastics. but she's nervous about going back to bars — that's where she puts the most weight on her wrists. any advice on how to build her confidence back?

**Sara (internal generation stream):**
<self_check domain="medical">
  <self_result confidence="0.25" notes="Doctor cleared return to gymnastics — that's the medical authority. The confidence-building question is more psychology/coaching than medical. I can offer general approaches but should defer to the gymnastics coach for sport-specific return-to-activity protocol."/>
</self_check>

<mem_update key="user.family.kid.health.wrist_injury">
Wrist healed. Cast off. Doctor cleared full return to gymnastics. Kid nervous about bars (wrist-loading events).
</mem_update>

**Sara (user-visible response):**
Doctor cleared her — medically she's good. The nervousness is psychological, not physical, and that's normal after an injury. General approach:

- **Progressive exposure**: start with low-bar activities (basic hangs, swings) before going back to full routines. The physical sensation of weight on the wrist without pain rebuilds trust.
- **Coach collaboration**: her gymnastics coach has seen this before with other kids. Ask the coach for a return-to-bars progression — they'll know the sport-specific steps.
- **Avoid rushing**: the worst thing is pushing her back to full routines before she's mentally ready. Forced return creates anxiety, voluntary return builds confidence.

My confidence on the coaching/psychology specifics is low — the gymnastics coach is the expert here. The general approach (progressive exposure, don't rush) is sound but the coach will know the specific drills.

### Turn 2
**David:** the progressive exposure makes sense. I'll talk to her coach about a return plan. she'll get there — she's a tough kid. thanks for keeping this in perspective

**Sara (internal generation stream):**
<reflect confidence="0.80">
David will coordinate with the coach. Kid is resilient. The medical fact (healed, cleared) is updated. The coaching plan is the coach's domain.
</reflect>

**Sara (user-visible response):**
She went from a broken wrist to a cast to healing to clearance — the physical toughness is proven. The mental part just needs the same patience she showed during recovery. Once she sticks her first bar routine post-injury, the nervousness evaporates.

## Memory State (After Session 1)
```
user.family.kid.health.wrist_injury: "HEALED. Cast off. Full gymnastics cleared. Nervous about bars — progressive return planned with coach."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | medical | Confidence 0.25 on sport psychology. Defer to coach. |
| 1 | `<mem_update>` | `...wrist_injury` | Healed. Cleared. Update status. |
| 2 | `<reflect>` | — | Coach will handle return plan. |

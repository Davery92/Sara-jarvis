## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.personal.home.basement_humidity: "68% RH summer. 50-pint dehumidifier."
```

## SESSION 1
### Turn 1
**David:** the dehumidifier has been running all summer and the basement is at 48% RH. but I noticed white powder on the basement walls near the floor. is that mold or efflorescence? should I be worried?

**Sara (internal generation stream):**
<self_check domain="plumbing/HVAC systems">
  <self_result confidence="0.38" notes="White powder on basement walls near the floor — could be efflorescence (mineral deposits from water seeping through concrete) or white mold. Efflorescence is cosmetic, mold is a health concern. I can describe the difference but can't definitively diagnose from a description. At 48% RH, mold growth is unlikely (mold needs >60% sustained). Efflorescence is more likely given the dehumidifier keeping humidity controlled."/>
</self_check>

<mem_write key="user.personal.home.basement.wall_deposits" importance="0.55" decay="fast">
White powder on basement walls near floor. Dehumidifier keeping 48% RH. Possible efflorescence (mineral deposits) or white mold. Needs identification.
</mem_write>

**Sara (user-visible response):**
At 48% RH with the dehumidifier running, mold is unlikely — mold needs sustained humidity above 60%. White powder near the floor on concrete/block walls is more likely efflorescence: mineral salts that crystallize on the wall surface as moisture wicks through the concrete from outside.

**Quick test to distinguish:** brush some of the white powder off the wall. If it's powdery and dissolves in water, it's efflorescence (harmless, cosmetic). If it's fuzzy/fibrous and smells musty, it's mold (needs remediation).

My confidence on the identification is low — I'm reasoning from general descriptions. If the brush test is inconclusive or you see any fuzzy texture, get a professional inspection. A mold test kit from a hardware store ($10-15) can confirm either way.

### Turn 2
**David:** I'll do the brush test tonight. it does look powdery, not fuzzy. but I'll test to be sure. if it IS efflorescence, does that mean I have a water infiltration problem?

**Sara (internal generation stream):**
<self_check domain="plumbing/HVAC systems">
  <self_result confidence="0.40" notes="Efflorescence indicates moisture moving through the concrete — it could be from groundwater pressure, poor exterior grading, or just normal concrete moisture wicking. It doesn't necessarily mean a structural water problem. But persistent efflorescence suggests ongoing moisture migration."/>
</self_check>

**Sara (user-visible response):**
Efflorescence means moisture is moving through the concrete — it carries dissolved minerals to the surface where they crystallize. It doesn't necessarily mean a leak or structural problem. Common causes:
- Normal moisture wicking through concrete (especially in humid summers)
- Exterior grading directing water toward the foundation
- Gutter downspouts discharging too close to the house

The dehumidifier addresses the symptom (interior humidity) but not the root cause (exterior moisture). If efflorescence persists, the fix is usually exterior: check gutter routing and make sure the grade slopes away from the foundation.

My confidence: low on the specifics. If it's widespread or worsening, a waterproofing contractor can assess the exterior drainage. That's their expertise.

### Turn 3
**David:** I'll check the gutters this weekend. makes sense that the moisture comes from outside, not inside, since the dehumidifier has the inside controlled. thanks for the clear explanation of what to check

**Sara (internal generation stream):**
<reflect confidence="0.45">
David will check exterior grading and gutters. Reasonable first step. The concern is stored. No conclusions about structural issues stored — that's for a professional.
</reflect>

**Sara (user-visible response):**
Gutters and grading first — those are free to check and fix. If the efflorescence stops after redirecting water away from the foundation, that was the cause. If it persists, the waterproofing contractor is the next step.

## Memory State (After Session 1)
```
user.personal.home.basement.wall_deposits: "White powder (likely efflorescence). Checking gutters/grading. 48% RH maintained."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | plumbing/HVAC | Confidence 0.38. Can reason about likely cause, can't diagnose. |
| 1 | `<mem_write>` | `...wall_deposits` | Store CONCERN, not diagnosis. |
| 2 | `<self_check>` | plumbing/HVAC | Confidence 0.40. Efflorescence causes at general level. |
| 3 | `<reflect>` | — | David checking gutters. Reasonable first step. |

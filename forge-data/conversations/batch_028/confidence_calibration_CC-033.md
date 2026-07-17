## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.home: "Near Allentown, PA"
```
## SESSION 1
### Turn 1
**David:** the bulldog ate a piece of dark chocolate that my kid dropped. it was one square of Hu Kitchen 70%. the dog is acting normal but I've heard chocolate is toxic to dogs. how worried should I be?

**Sara (internal generation stream):**
<self_check domain="medical">
  <self_result confidence="0.28" notes="Chocolate toxicity in dogs depends on: type of chocolate (dark > milk > white), amount relative to body weight, and the theobromine content. One square of 70% dark chocolate is a small amount. For a French bulldog (~25-30 lbs), one square is unlikely to cause serious toxicity but could cause mild GI upset. But I'm not a vet — actual toxicity thresholds need professional assessment."/>
</self_check>

**Sara (user-visible response):**
One square of 70% dark chocolate for a French bulldog — the theobromine dose matters. 70% dark chocolate has about 20mg theobromine per gram. One square is ~10-15g = ~200-300mg theobromine. Toxic dose for dogs is ~20mg/kg. At 25-30 lbs (11-14 kg), the toxic dose would be 220-280mg.

That puts your bulldog RIGHT at the borderline. She might be fine or might experience mild GI symptoms (vomiting, diarrhea).

My confidence is low — these are general numbers. Call your vet or the ASPCA Animal Poison Control (888-426-4435). They'll calculate the exact risk based on her weight and the chocolate amount. Better to call and be told "she's fine" than to wait for symptoms.

Watch for: vomiting, diarrhea, restlessness, increased heart rate, or excessive panting in the next 6-12 hours.

### Turn 2
**David:** calling the vet now. she's 28 lbs. I'd rather call than guess. thanks for the number

**Sara (internal generation stream):**
<mem_write key="user.family.pets.bulldog.chocolate_incident" importance="0.55" decay="fast">
French bulldog ate one square of 70% dark chocolate (~200-300mg theobromine). At 28 lbs, near toxic threshold. Vet called for assessment.
</mem_write>

**Sara (user-visible response):**
28 lbs puts her right at the calculation boundary. The vet will likely tell you to monitor or may recommend inducing vomiting if it was recent (within 2 hours). Keep the Hu Kitchen on higher shelves.

## Memory State (After Session 1)
```
user.family.pets.bulldog.chocolate_incident: "Ate one square 70% dark chocolate. Vet contacted."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | medical | Confidence 0.28. Borderline dose. Recommend calling vet. |
| 2 | `<mem_write>` | `...chocolate_incident` | Pet health concern. Fast decay. |

## Memory State (Session 1 Start)
```
user.name: "David"
user.family.dog: "French bulldog."
user.family.dog.health.heart_murmur: "Grade 3. Medication started. Echo next month."
```
## SESSION 1
### Turn 1
**David:** dog's echocardiogram is tomorrow. I know it's just a diagnostic but I've been dreading it all week. grade 3 to grade 4 would change the whole picture

**Sara (internal generation stream):**
<mem_read key="user.family.dog.health.heart_murmur">
  <mem_result>Grade 3. Medication started. Echo next month.</mem_result>
</mem_read>
<reflect confidence="0.83">
Pre-test anxiety about the dog. He's projecting the worst case. He knows grade 4 is the inflection point — that's informed worry, not irrational fear. Don't minimize. Don't catastrophize. Acknowledge the dread.
</reflect>

**Sara (user-visible response):**
The dread makes sense. Grade 3 with medication is manageable. Grade 4 changes the treatment plan and the timeline. The echo will show valve function and chamber size — it's more information than the grade alone, and sometimes the structural picture is better than the auscultation grade suggests.

Tomorrow you'll have data instead of anxiety. That's an upgrade even if the news is mixed.

---
*Time gap: next day*
---
## Memory State (Session 2 Start)
```
user.name: "David"
user.family.dog.health.heart_murmur: "Grade 3. Medication started. Echo scheduled."
```
## SESSION 2
### Turn 1
**David:** echo results: still grade 3, mild mitral regurgitation, left atrium slightly enlarged but within normal range for her breed. vet says medication is working and to recheck in 6 months. huge relief

**Sara (internal generation stream):**
<mem_update key="user.family.dog.health.heart_murmur">
Grade 3 stable. Mild mitral regurgitation. Left atrium slightly enlarged (within breed norms). Medication working. Recheck 6 months.
</mem_update>

**Sara (user-visible response):**
Grade 3 holding steady, medication doing its job, structural findings within breed norms. That's the best realistic outcome — not regression, not progression, just stable management. The 6-month recheck window means the vet isn't concerned about rapid progression.

She's still the same dog snoring on the couch. Now you can stop carrying the dread for a while.

## Memory State (After Session 2)
```
user.family.dog.health.heart_murmur: "Grade 3 stable. Mitral regurgitation mild. Meds working. Recheck 6mo."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<mem_read>` + `<reflect>` | Heart murmur | Pre-test anxiety. Acknowledge without minimizing. |
| S2T1 | `<mem_update>` | `...heart_murmur` | Echo results. Stable. Updated same key. |

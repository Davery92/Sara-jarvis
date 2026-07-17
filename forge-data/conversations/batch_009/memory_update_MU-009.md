## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.fitness: "Body recomp at ~230lb."
user.personal.fitness.macros: "200g protein, 250g carbs, 80g fat. ~2500 cal."
user.personal.health.nutritionist: "Works with a nutritionist."
```

## SESSION 1

### Turn 1

**David:** nutritionist adjusted my macros. protein stays at 200g but she dropped carbs to 200g and bumped fat to 100g. total calories is the same — 2500. she wants to see if the higher fat helps with satiety since I've been hungry on the higher carb split

**Sara (internal generation stream):**

<mem_read key="user.personal.fitness.macros">
  <mem_result>200g protein, 250g carbs, 80g fat. ~2500 cal.</mem_result>
</mem_read>

<mem_update key="user.personal.fitness.macros">
Nutritionist-adjusted macros: 200g protein (unchanged), 200g carbs (was 250g), 100g fat (was 80g). Total: ~2500 cal (unchanged). Change: shifted 50g carbs to 20g fat for better satiety. Hunger was an issue on higher-carb split.
</mem_update>

**Sara (user-visible response):**

Same calories, different ratio — trading carb volume for fat satiety. The higher fat should keep you feeling fuller between meals since fat slows gastric emptying. 200g protein stays as the anchor.

The trade-off: you might notice slightly less energy in morning workouts if you were relying on the carbs for glycogen. If your 5:30 AM sessions feel flat, you could shift more of the 200g carbs to pre/post workout and keep the higher fat for the rest of the day.

### Turn 2

**David:** good point about the workout energy. I'll pay attention to the morning sessions and see if they suffer. if they do I'll front-load carbs around the workout like you said

**Sara (internal generation stream):**

<reflect confidence="0.72">
David noting he'll monitor workout energy. This is a conditional plan ("if they do, I'll...") — tentative. Not worth storing as a decision. The macro change is the key update and it's captured.
</reflect>

**Sara (user-visible response):**

Give it 5-7 days for your body to adapt to the new ratio before judging the workout impact. The first few sessions might feel different just from the shift, not from a genuine energy deficit.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.fitness: "Body recomp at ~230lb."
user.personal.fitness.macros: "200g protein, 200g carbs, 100g fat. ~2500 cal. Adjusted for satiety."
user.personal.health.nutritionist: "Works with a nutritionist."
```

---

*Time gap: next day*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** what are my current macros? I need to update my tracking app

**Sara (internal generation stream):**

<mem_read key="user.personal.fitness.macros">
  <mem_result>200g protein, 200g carbs, 100g fat. ~2500 cal. Adjusted for satiety.</mem_result>
</mem_read>

**Sara (user-visible response):**

200g protein, 200g carbs, 100g fat. 2500 calories total. Adjusted from the previous split (250g carbs, 80g fat) for better satiety.

### Turn 2

**David:** thanks. that's the new one from yesterday. perfect

**Sara (internal generation stream):**

<reflect confidence="0.85">
David confirming the stored values are correct. Pure retrieval, no updates.
</reflect>

**Sara (user-visible response):**

Updated and current. The tracking app should reflect the change immediately — the calorie total is the same so your deficit target doesn't change.

## Memory State (After Session 2)

```
[no changes — values confirmed correct]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `...macros` | Read existing macros. |
| S1T1 | `<mem_update>` | `...macros` | Macros changed. UPDATE same key. No apology for old info. |
| S1T2 | `<reflect>` | — | Conditional workout plan. Tentative, not storable. |
| S2T1 | `<mem_read>` | `...macros` | David asks for current macros. Memory has it. |
| S2T2 | `<reflect>` | — | Values confirmed. No updates needed. |

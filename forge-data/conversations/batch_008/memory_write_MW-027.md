## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.fitness: "Body recomp at ~230lb."
user.personal.health.nutritionist: "Works with a nutritionist."
user.personal.food.dark_chocolate: "Hu Kitchen 70% cacao."
```

## SESSION 1

### Turn 1

**David:** nutritionist put me on a new macro split. 200g protein, 250g carbs, 80g fat. that's about 2500 calories which puts me in a slight deficit at 230. goal is to lose about 0.5lb per week while keeping strength

**Sara (internal generation stream):**

<mem_write key="user.personal.fitness.macros" importance="0.65" decay="medium">
Nutritionist-prescribed macro split: 200g protein, 250g carbs, 80g fat. ~2500 calories total. Slight deficit at 230lb. Target: 0.5lb/week loss while maintaining strength.
</mem_write>

**Sara (user-visible response):**

200g protein at 230lb is ~0.87g/lb — solid for preserving muscle in a deficit. The 250g carbs keep training performance up, and 80g fat maintains hormonal function. 2500 cal for a 0.5lb/week deficit means your maintenance is around 2750-2800.

That's a well-structured recomp split. How's compliance been?

### Turn 2

**David:** first week. hitting protein is the hard part — I'm usually around 170-180g unless I'm deliberate about it. the shakes help but I'd rather eat my protein than drink it

**Sara (internal generation stream):**

<mem_write key="user.personal.fitness.macros.compliance" importance="0.50" decay="fast">
Protein target (200g) is the hardest macro to hit. David naturally lands at 170-180g. Prefers whole food protein over shakes.
</mem_write>

**Sara (user-visible response):**

The 20-30g gap between natural intake and target is one meal's worth of protein. Some easy additions that aren't shakes:
- Greek yogurt (150g serving = 15g protein)
- Cottage cheese before bed (1 cup = 28g protein)
- Extra 4oz chicken breast at lunch or dinner (~35g)
- Beef jerky as a snack (~10g per ounce)

Any one of those closes the gap without needing another shake.

### Turn 3

**David:** cottage cheese before bed is actually a good idea. casein protein, slow digesting. my nutritionist mentioned that. I'll start keeping it stocked

**Sara (internal generation stream):**

<mem_write key="user.personal.food.cottage_cheese" importance="0.40" decay="slow">
David adding cottage cheese before bed as a protein source. Casein for slow digestion overnight. Nutritionist endorsed.
</mem_write>

**Sara (user-visible response):**

Cottage cheese before bed with a square of dark chocolate after dinner — your evening nutrition is dialed. The casein keeps amino acids available overnight while you sleep. 1 cup gets you to 200g protein with minimal effort.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.fitness: "Body recomp at ~230lb."
user.personal.fitness.macros: "200g protein, 250g carbs, 80g fat. ~2500 cal. 0.5lb/week deficit."
user.personal.fitness.macros.compliance: "Protein hardest to hit. Natural intake 170-180g."
user.personal.food.dark_chocolate: "Hu Kitchen 70% cacao. Post-dinner ritual."
user.personal.food.cottage_cheese: "Pre-bed protein source. Casein. Nutritionist endorsed."
user.personal.health.nutritionist: "Works with a nutritionist."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...macros` | Nutritionist-prescribed macro split. Concrete dietary plan. |
| 2 | `<mem_write>` | `...compliance` | Compliance pattern: protein is the gap. Useful for future context. |
| 3 | `<mem_write>` | `...cottage_cheese` | New dietary habit added. Nutritionist endorsed. |

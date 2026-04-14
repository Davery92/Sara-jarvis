## Memory State (Session 1 Start)

```
user.name: "David"
user.family.kid: "Swimming (recreational), gymnastics level 4"
user.family.kid.gymnastics.level: "Level 4, working toward level 5 by summer 2026."
```

## SESSION 1

### Turn 1

**David:** kid tested up to level 5 gymnastics! the coach approved it yesterday after her evaluation. she crushed the beam work that was holding her back

**Sara (internal generation stream):**

<mem_update key="user.family.kid.gymnastics.level">
Level 5 (tested up from level 4). Coach approved after evaluation. Beam work — previously the weak area — was strong in the test.
</mem_update>

**Sara (user-visible response):**

Level 5 — and she nailed the beam, which was the holdout. That's the culmination of those extra Saturday practices and the meet prep. How's she feeling about it?

### Turn 2

**David:** over the moon. she's already asking about level 6 which is like a year away. one thing at a time kid

**Sara (internal generation stream):**

<reflect confidence="0.82">
Kid is excited about the promotion and already looking ahead. David's "one thing at a time kid" is a parenting moment, not a storable fact. The kid's enthusiasm is emotional state, not persistent data. The level-up is the key fact and it's captured.
</reflect>

**Sara (user-visible response):**

Level 5 to 6 is the biggest skill jump in the progression — she'll have a full year to develop the new requirements. The ambition is good as long as it stays fun. She's got the competitive drive and the work ethic.

## Memory State (After Session 1)

```
user.family.kid: "Swimming (recreational), gymnastics level 5"
user.family.kid.gymnastics.level: "Level 5 (tested up from level 4). Beam work improved."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_update>` | `user.family.kid.gymnastics.level` | Level changed: 4 → 5. UPDATE same key. Beam improvement noted. |
| 2 | `<reflect>` | — | Kid's excitement is emotional. "Already asking about level 6" is aspirational, not storable. |

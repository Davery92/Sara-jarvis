## Memory State (Session 1 Start)

```
user.name: "David"
user.family.kid: "In swimming (recreational) and gymnastics"
user.family.kid.birthday: "Upcoming — David has been planning a party"
user.family.kid.birthday_party.plan: "Trampoline park party. 12 kids invited. Saturday April 19, 2 PM. Pizza and cake. Budget ~$400."
```

## SESSION 1

### Turn 1

**David:** so the trampoline park just called — they're closing for maintenance the week of the kid's party. have to find a new venue

**Sara (internal generation stream):**

<mem_read key="user.family.kid.birthday_party.*">
  <mem_result>Trampoline park party. 12 kids, Saturday April 19, 2 PM. Pizza and cake. Budget ~$400.</mem_result>
</mem_read>

**Sara (user-visible response):**

That's two weeks out. What's available near Allentown for a group of 12 on that short notice? Bowling alley, indoor climbing gym, or a park pavilion with activities are the usual fallbacks. What's the kid into — would she care about the specific venue or just want the party to happen?

### Turn 2

**David:** she's bummed about the trampoline park specifically but she'd get over it. looking at Lehigh Valley Laser Tag — they have a party package for $350 that includes 2 games, pizza, and a party room. fits our budget and they have the 19th available

**Sara (internal generation stream):**

<reflect confidence="0.82">
David is evaluating a new option but hasn't committed. "Looking at" is still in consideration. I'll engage with the option but wait for a decision before updating the stored plan.
</reflect>

**Sara (user-visible response):**

Laser tag at that age is usually a hit — especially with a group of 12, you get full teams for the games. $350 all-in with pizza included is actually better than the trampoline park deal if pizza was extra there. The party room gives you a contained space for cake and presents.

Does the package include invitations or do you need to update the ones you already sent?

### Turn 3

**David:** already sent the trampoline park invites. I'll just text the parents with the new venue. going with the laser tag — booked it for April 19 at 2 PM same as before

**Sara (internal generation stream):**

<mem_update key="user.family.kid.birthday_party.plan">
Laser tag party at Lehigh Valley Laser Tag. 12 kids. Saturday April 19, 2 PM. Package: 2 games + pizza + party room, $350. Trampoline park was original venue but closed for maintenance.
</mem_update>

**Sara (user-visible response):**

Same date, same time, $50 less. Smooth pivot. The parents just need the new address — the rest of the details stay the same. If you text today they've got two weeks to adjust.

### Turn 4

**David:** yeah sending the text now. thanks for the sanity check

**Sara (internal generation stream):**

<reflect confidence="0.85">
Conversational close. David is handling the logistics. The plan update is captured. "Thanks for the sanity check" is a conversational gesture, not storable.
</reflect>

**Sara (user-visible response):**

She'll have a blast. Laser tag with a squad of 12 is way more fun than bouncing anyway.

## Memory State (After Session 1)

```
user.name: "David"
user.family.kid: "In swimming (recreational) and gymnastics"
user.family.kid.birthday: "Upcoming"
user.family.kid.birthday_party.plan: "Laser tag at Lehigh Valley Laser Tag. 12 kids. Saturday April 19, 2 PM. 2 games + pizza + party room, $350."
```

---

*Time gap: 3 days later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** party update — my sister-in-law wants to bring her 3 kids too. so we're up to 15

**Sara (internal generation stream):**

<mem_read key="user.family.kid.birthday_party.*">
  <mem_result>Laser tag at Lehigh Valley Laser Tag. 12 kids. Saturday April 19, 2 PM. 2 games + pizza + party room, $350.</mem_result>
</mem_read>

<mem_update key="user.family.kid.birthday_party.plan">
Laser tag at Lehigh Valley Laser Tag. 15 kids (originally 12, plus 3 from sister-in-law). Saturday April 19, 2 PM. 2 games + pizza + party room. May need to adjust package pricing for extra kids.
</mem_update>

**Sara (user-visible response):**

Check if the $350 package covers 15 or if it's capped at 12 with a per-kid upcharge for extras. Most laser tag party packages have a headcount limit — usually $15-25 per additional kid. Even at $25 each for 3 extra, you're at $425, still close to the original trampoline park budget.

### Turn 2

**David:** just called them — $20 per extra kid. so $410 total. fine by me, still under the trampoline park price

**Sara (internal generation stream):**

<mem_update key="user.family.kid.birthday_party.plan">
Laser tag at Lehigh Valley Laser Tag. 15 kids. Saturday April 19, 2 PM. 2 games + pizza + party room. $410 total ($350 base + $60 for 3 extra kids at $20/each).
</mem_update>

**Sara (user-visible response):**

$410 for 15 kids with laser tag, pizza, and a party room — solid value. Under budget and a better activity. Anything else you need to sort for the 19th?

### Turn 3

**David:** nope, I think we're set. cake is handled, presents are bought. just need to show up

**Sara (internal generation stream):**

<reflect confidence="0.85">
David confirms party planning is complete. No new facts to store beyond the updated plan. "Just need to show up" is conversational closure.
</reflect>

**Sara (user-visible response):**

You're good then. Enjoy the chaos of 15 kids with laser guns.

## Memory State (After Session 2)

```
user.name: "David"
user.family.kid: "In swimming (recreational) and gymnastics"
user.family.kid.birthday: "Upcoming — party planned"
user.family.kid.birthday_party.plan: "Laser tag at Lehigh Valley Laser Tag. 15 kids. Saturday April 19, 2 PM. $410 total. Cake and presents handled."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `user.family.kid.birthday_party.*` | Retrieve stored party plan to engage with the venue change. |
| S1T2 | `<reflect>` | — | David evaluating laser tag but not committed yet. Wait for decision. |
| S1T3 | `<mem_update>` | `user.family.kid.birthday_party.plan` | Decision made: laser tag booked. UPDATE existing key, not duplicate. Same date/time, new venue and price. |
| S1T4 | `<reflect>` | — | Conversational close. No new facts. |
| S2T1 | `<mem_read>` | `user.family.kid.birthday_party.*` | Recall party details for the headcount update. |
| S2T1 | `<mem_update>` | `user.family.kid.birthday_party.plan` | Headcount update: 12 → 15. Same key, updated value. |
| S2T2 | `<mem_update>` | `user.family.kid.birthday_party.plan` | Final price confirmed: $410. Update same key again. |
| S2T3 | `<reflect>` | — | Party planning complete. No new facts beyond what's stored. |

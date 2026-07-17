## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.routine.morning: "5-6 AM wake. Mon/Wed: gym at 5:30 AM. Tue/Thu: standard morning. Fri: home."
user.personal.fitness.schedule_adjustment: "Mon/Wed lower 60 min at 5:30 AM. Tue/Thu upper after work."
```

## SESSION 1

### Turn 1

**David:** morning routine change — I'm dropping the Monday morning gym session. it was burning me out starting the week at 5:30. moving Monday lower to Tuesday evening and shifting Tuesday upper to Wednesday morning. so now it's: Wed/Fri morning gym, Tue/Thu evening gym

**Sara (internal generation stream):**

<mem_read key="user.personal.routine.morning">
  <mem_result>5-6 AM wake. Mon/Wed: gym at 5:30 AM. Tue/Thu: standard morning. Fri: home.</mem_result>
</mem_read>

<mem_update key="user.personal.routine.morning">
5-6 AM wake. Wed/Fri: gym at 5:30 AM (lower Wed, upper Fri). Tue/Thu: gym after work (lower Tue, upper Thu). Mon: standard morning, no gym.
</mem_update>

<mem_update key="user.personal.fitness.schedule_adjustment">
Updated split: Wed morning lower, Fri morning upper, Tue evening lower, Thu evening upper. Monday off — dropped morning session to avoid burnout.
</mem_update>

**Sara (user-visible response):**

That's a smarter distribution. Monday morning was front-loading the week's fatigue. The new schedule gives you a rest day Monday and spreads the load more evenly. Wed/Fri mornings and Tue/Thu evenings means you never have back-to-back training days either — nice recovery spacing.

Wait — Friday you said morning gym, but Friday is your work-from-home day. You're doing the morning session before you start working from home?

### Turn 2

**David:** yeah, Friday morning gym at 6 AM since I don't have the commute. then start work at 8:30 from home. it's the most relaxed gym day because there's no time pressure

**Sara (internal generation stream):**

<mem_write key="user.personal.fitness.friday_session" importance="0.45" decay="medium">
Friday gym at 6 AM (WFH day, no commute). Most relaxed session — no time pressure. Upper body day.
</mem_write>

**Sara (user-visible response):**

Friday WFH + 6 AM gym is the best slot in the week. No commute stress, you can take your time, shower at home. Upper body with no clock running probably means you can hit the accessories you cut from the morning sessions.

### Turn 3

**David:** exactly. Friday is when I do the full session — all the accessory work, maybe some conditioning at the end. the other days are stripped down

**Sara (internal generation stream):**

<reflect confidence="0.80">
David confirming Friday is the full session vs stripped-down other days. The Friday session detail is already captured — "most relaxed" implies full session. The confirmation doesn't add new facts.
</reflect>

**Sara (user-visible response):**

One full session (Friday) and three stripped-down ones — that's a good programming structure. The total weekly volume is spread across 4 days but the quality work concentrates on Friday when you have the time and energy for it.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.routine.morning: "5-6 AM wake. Wed/Fri: gym 5:30-6 AM. Tue/Thu: gym after work. Mon: off."
user.personal.fitness.schedule_adjustment: "Wed AM lower, Fri AM upper (full session), Tue PM lower, Thu PM upper. Mon off."
user.personal.fitness.friday_session: "Friday 6 AM, WFH day, full session with accessories and conditioning."
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

**David:** the new schedule is working way better. not dreading Monday anymore. actually sleeping better Sunday nights too since I'm not setting a 5 AM alarm

**Sara (internal generation stream):**

<reflect confidence="0.83">
David reporting the schedule change is working. "Way better" and "sleeping better" are subjective/emotional — not storable facts. The schedule itself is already correctly stored. The positive outcome validates the change but doesn't create new information.
</reflect>

**Sara (user-visible response):**

The Sunday sleep improvement makes sense — anticipatory stress from the Monday alarm was probably disrupting your last night of the weekend. With Monday off, Sunday becomes a real recovery day instead of pre-workout anxiety.

### Turn 2

**David:** yeah exactly. anyway just wanted to let you know it's working. on to other stuff

**Sara (internal generation stream):**

<reflect confidence="0.85">
Conversational close. David validating the schedule change. No new facts to store.
</reflect>

**Sara (user-visible response):**

Good to hear it landed well. What's next?

## Memory State (After Session 2)

```
[same as After Session 1 — no changes, schedule already correctly stored]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `user.personal.routine.morning` | Recall current routine for the update. |
| S1T1 | `<mem_update>` | `user.personal.routine.morning` | Schedule changed. UPDATE same key, not duplicate. |
| S1T1 | `<mem_update>` | `user.personal.fitness.schedule_adjustment` | Fitness split updated to match new routine. |
| S1T2 | `<mem_write>` | `user.personal.fitness.friday_session` | New detail about Friday session being full/relaxed. |
| S1T3 | `<reflect>` | — | Confirmation of existing info. No new facts. |
| S2T1 | `<reflect>` | — | Positive outcome is emotional validation. Schedule already stored correctly. |
| S2T2 | `<reflect>` | — | Session close. No updates needed. |

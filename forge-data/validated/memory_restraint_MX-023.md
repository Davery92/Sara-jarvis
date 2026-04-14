## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.family.pets: "French bulldog, betta fish, hamster (Professor Whiskers)"
```

## SESSION 1

### Turn 1

**David:** the betta fish died. he was like 3 years old so it was expected. the kid is sad but she's handling it ok

**Sara (internal generation stream):**

<reflect confidence="0.82">
David reporting the death of the betta fish. The kid is sad but handling it. Two considerations:
1. The fish dying is a factual update (remove betta from pets list)
2. The kid's sadness is transient emotional state — don't store
3. "She's handling it ok" — also transient

The factual change (betta died) is storable. The emotional context is not.
</reflect>

<mem_update key="user.family.pets">
French bulldog, hamster (Professor Whiskers). Betta fish died (age ~3 years).
</mem_update>

**Sara (user-visible response):**

Three years is a full lifespan for a betta — he had a good run. If the kid wants to talk about it, she will. At that age, losing a pet is one of the first real experiences with death, and it's healthy that she's processing it rather than being devastated.

Are you thinking about getting a replacement, or letting the tank sit for a while?

### Turn 2

**David:** she wants a new fish but I told her to wait a week. partly to grieve, partly because I need to cycle the tank if we're starting fresh

**Sara (internal generation stream):**

<reflect confidence="0.80">
David's decision to wait a week — reasonable parenting + practical tank cycling. But this is a temporary plan ("wait a week") about getting a replacement fish. Not worth storing as a permanent fact. If they get a new fish, THAT would be storable.
</reflect>

**Sara (user-visible response):**

Week wait is smart for both reasons. Tank cycling takes 5-7 days anyway to re-establish the nitrogen cycle if you're doing a water change and filter clean. When she's ready, she can pick the new one — making it her choice gives her ownership of the transition.

### Turn 3

**David:** yeah. anyway, life goes on. she's already distracted by Professor Whiskers doing hamster things

**Sara (internal generation stream):**

<reflect confidence="0.85">
Kid moving on naturally. Hamster providing comfort. Session close on a light note. The pet update is captured.
</reflect>

**Sara (user-visible response):**

Professor Whiskers earning his keep as the emotional support hamster. She'll be fine.

## Memory State (After Session 1)

```
user.name: "David"
user.family.pets: "French bulldog, hamster (Professor Whiskers). Betta fish died."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<reflect>` | — | Fish died (factual update). Kid's sadness (transient, don't store). |
| 1 | `<mem_update>` | `user.family.pets` | Remove betta from active pets. Factual change. |
| 2 | `<reflect>` | — | Waiting a week is temporary plan. Not stored until new fish is acquired. |
| 3 | `<reflect>` | — | Kid moving on. Light close. |

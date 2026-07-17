## Memory State (Session 1 Start)

```
user.name: "David"
user.family.kid: "Swimming (recreational), gymnastics level 4"
user.family.kid.interests: "Hamsters, Minecraft"
user.family.kid.homework: "Struggling with math (fractions), doing well in reading/writing. David tried flash cards but kid got frustrated. Switched to real-world examples (cooking fractions, Minecraft resource ratios)."
```

## SESSION 1

### Turn 1

**David:** kid's report card came back. math improved from a C to a B-. the real-world examples thing worked

**Sara (internal generation stream):**

<mem_read key="user.family.kid.homework*">
  <mem_result>Struggling with fractions. Flash cards frustrated her. Switched to real-world examples (cooking fractions, Minecraft resource ratios).</mem_result>
</mem_read>

<mem_update key="user.family.kid.homework">
Math improved C → B- after switching to real-world fraction examples (cooking, Minecraft ratios). Flash card approach was counterproductive.
</mem_update>

**Sara (user-visible response):**

C to B- with the real-world examples — that validates the approach. The cooking fractions and Minecraft ratios gave her a context where fractions mean something instead of abstract numbers on flash cards. If she maintains this trajectory, fractions won't be a blocker going into the next grade level.

Is she still doing the Minecraft resource ratio thing on her own, or does it need to be structured?

### Turn 2

**David:** she does it on her own now actually. she was building something in Minecraft last night and told me she needed "three-quarters of a stack of cobblestone." she didn't even realize she was doing fractions

**Sara (internal generation stream):**

<reflect confidence="0.82">
That's a great example of internalized learning — she's applying fractions without thinking about it as "math." But this is an anecdote about learning progress, not a new fact to store. The grade improvement is the key data point and that's captured.
</reflect>

**Sara (user-visible response):**

When she's calculating fractions in Minecraft without framing it as homework, that's internalization. The concept clicked. The B- is the grade; the Minecraft cobblestone is the evidence that she actually understands it now, not just memorized it for the test.

## Memory State (After Session 1)

```
user.name: "David"
user.family.kid: "Swimming (recreational), gymnastics level 4"
user.family.kid.interests: "Hamsters, Minecraft"
user.family.kid.homework: "Math improved C → B-. Real-world examples (cooking fractions, Minecraft ratios) effective. Self-applying concepts."
```

---

*Time gap: 2 weeks later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** hey, picking back up on kid homework help strategies. she's now struggling with long division. same pattern — she gets frustrated with the abstract algorithm

**Sara (internal generation stream):**

<mem_read key="user.family.kid.homework">
  <mem_result>Math improved C → B- with real-world examples. Flash cards counterproductive. Self-applying fraction concepts via Minecraft/cooking.</mem_result>
</mem_read>

**Sara (user-visible response):**

Same pattern as fractions — the abstract algorithm frustrates her but real-world application clicks. For long division, the most natural real-world frame is equal sharing:

- "You have 84 Minecraft diamonds and want to split them equally between 4 players. How many does each player get?"
- "We're making 3 batches of cookies and the recipe makes 96 cookies total. How many per batch?"

The sharing frame maps directly to division without the intimidation of the long division bracket. Once she gets the concept through sharing, the algorithm becomes a tool for getting the answer faster, not the concept itself.

### Turn 2

**David:** the sharing frame is good. she'd definitely engage with splitting Minecraft loot. I'll try that tonight

**Sara (internal generation stream):**

<mem_write key="user.family.kid.homework.division_strategy" importance="0.50" decay="medium">
Long division: using equal sharing frame (Minecraft loot splitting, recipe portions). Same approach that worked for fractions — real-world context instead of abstract algorithm.
</mem_write>

**Sara (user-visible response):**

Start with easy numbers (84 ÷ 4 = 21) so the sharing is clean, then work up to remainders: "You have 85 diamonds for 4 players — 21 each with 1 leftover." Remainders are where long division usually loses kids, and the sharing frame makes them intuitive — there's just "some left over."

### Turn 3

**David:** this is the same pattern every time. abstract → frustration → real-world reframe → clicks. I should probably just default to real-world first for every new math concept

**Sara (internal generation stream):**

<reflect confidence="0.80">
David identifying a meta-pattern in his kid's learning style. This is an insight about the kid's learning approach, not a specific homework fact. It's consistent with what's already stored (flash cards fail, real-world works). The meta-pattern is implicit in the existing entries. No need for a separate memory entry — it's already the established approach.
</reflect>

**Sara (user-visible response):**

That's the right default. Her learning style is concrete-first — she needs to see why a concept matters before she'll engage with the mechanics. That's actually a common ADHD-adjacent learning pattern: interest-gated focus, needs the "why" before the "how."

The flash card failure was the signal: she doesn't learn through repetition, she learns through context. Every new math concept, start with "here's when you'd use this" and the algorithm follows.

### Turn 4

**David:** sounds familiar. I'm the same way

**Sara (internal generation stream):**

<reflect confidence="0.83">
David recognizing the pattern in himself — interest-gated focus, builds to learn. This is consistent with his already-known ADHD learning style. The connection between father and daughter's learning patterns is a personal observation, not a new fact to store.
</reflect>

**Sara (user-visible response):**

Apple doesn't fall far. Interest-gated focus runs in families. The upside is you know exactly what works because it's how your own brain is wired. You're her best tutor precisely because you share the pattern.

## Memory State (After Session 2)

```
user.name: "David"
user.family.kid: "Swimming (recreational), gymnastics level 4"
user.family.kid.interests: "Hamsters, Minecraft"
user.family.kid.homework: "Math improved C → B-. Real-world examples work. Abstract algorithms frustrate her."
user.family.kid.homework.division_strategy: "Long division via equal sharing frame (Minecraft loot, recipes)."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `user.family.kid.homework*` | Recall homework context for report card update. |
| S1T1 | `<mem_update>` | `user.family.kid.homework` | Grade improvement and approach validation. |
| S1T2 | `<reflect>` | — | Minecraft anecdote is charming but not a separate fact. Grade is the data point. |
| S2T1 | `<mem_read>` | `user.family.kid.homework` | David picks back up. Recall what worked before to apply same pattern. |
| S2T2 | `<mem_write>` | `user.family.kid.homework.division_strategy` | New strategy for current topic. |
| S2T3 | `<reflect>` | — | Meta-pattern is implicit in existing entries. No separate storage needed. |
| S2T4 | `<reflect>` | — | David seeing his own pattern in kid. Personal observation, not new fact. |

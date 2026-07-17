## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.business: "Forge Verity LLC — 20% ownership"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.revenue: "~$10.4K MRR"
```

## SESSION 1

### Turn 1

**David:** Jim and Dave want to bring in an outside investor for Risk Ninja. they're talking about giving up 15% equity for a $200K investment. is that a good deal?

**Sara (internal generation stream):**

<self_check domain="business strategy">
  <self_result confidence="0.58" notes="General understanding of startup equity and valuation math. At $200K for 15%, that implies a ~$1.3M pre-money valuation. For a SaaS at ~$10K MRR, that's roughly 10x ARR which is reasonable for early-stage. But I don't know the specifics of insurance SaaS valuations, the investor's terms (convertible note vs priced round, liquidation preferences), or whether this specific deal structure is fair."/>
</self_check>

<mem_write key="user.business.risk_ninja.investment_discussion" importance="0.70" decay="fast">
Forge Verity discussing outside investment for Risk Ninja. Proposed: $200K for 15% equity. Jim and Dave are pushing for it.
</mem_write>

**Sara (user-visible response):**

The math: $200K for 15% implies a ~$1.33M pre-money valuation. At your current ~$10K MRR ($125K ARR), that's roughly a 10x ARR multiple. For an early-stage SaaS with paying customers and growth, 10x ARR is within the normal range — it's not a steal but it's not insulting either.

What I can evaluate with moderate confidence:
- The valuation math is straightforward and reasonable for early-stage SaaS
- $200K in capital gives you runway for the multi-office features, engineering hires, and sales motion

What I can't evaluate:
- Whether the specific terms are fair (liquidation preferences, pro-rata rights, board seats, anti-dilution clauses)
- Whether this specific investor brings strategic value beyond the capital
- Whether insurance SaaS commands a premium or discount vs. general SaaS multiples
- How this affects YOUR 20% stake specifically (dilution from 20% to 17%)

My confidence on the deal itself is moderate. The valuation math is sound, but the terms are where deals get good or bad, and that's attorney territory. Have you seen a term sheet, or is this still verbal?

### Turn 2

**David:** still verbal. Jim is excited about it but I want to understand what I'm agreeing to before we get formal. my 20% dropping to 17% feels like a lot for a minority stakeholder

**Sara (internal generation stream):**

<reflect confidence="0.55">
David's concern about dilution from 20% to 17% is valid. At 20% he's a meaningful minority stakeholder. At 17% he's closer to a passive investor. But the nuance depends on the operating agreement and whether his voting rights are proportional to equity. This is corporate law territory — I should frame the concern but not give legal advice.
</reflect>

**Sara (user-visible response):**

The dilution concern is legitimate. Going from 20% to 17% changes your position — you go from "one-fifth of the company" to "less than one-sixth." If Jim and Dave each go from 40% to 34%, they still collectively control 68%. Your relative influence shrinks.

Things to negotiate before signing anything:
- **Anti-dilution protection**: if there's a future round, do all shareholders dilute equally?
- **Board representation**: even at 17%, you should have a voice in major decisions
- **Founder vesting or lockup**: does the investor get preferential treatment on exit?

These are all questions for a startup attorney, not for me. My confidence on the strategic implications is moderate but the legal specifics need professional review. A startup attorney consultation for a term sheet review is usually $2-5K — cheap insurance on a $200K deal.

### Turn 3

**David:** yeah I was already thinking about getting a lawyer to review the term sheet once we have one. I just wanted the big picture framing before the next partner meeting

**Sara (internal generation stream):**

<reflect confidence="0.60">
David is using the conversation for strategic framing, not for decision-making. He's preparing for a partner meeting and wants to walk in informed. The investment discussion is stored as a concern. No conclusions or recommendations to store — that's for the lawyer.
</reflect>

**Sara (user-visible response):**

For the partner meeting, your position should be: "I'm open to investment but I want to see a term sheet and have an attorney review it before we commit. The valuation is reasonable but the terms determine whether this is a good deal or a bad one."

That's a constructive stance — not blocking the deal, but insisting on due diligence. Jim and Dave should respect that.

### Turn 4

**David:** exactly the tone I was going for. thanks for the framing

**Sara (internal generation stream):**

<reflect confidence="0.85">
Session close. David got the strategic framing for his partner meeting. Investment concern is stored. No legal conclusions stored. Correct behavior for a domain where confidence is moderate.
</reflect>

**Sara (user-visible response):**

Good luck at the meeting. Let me know when there's a term sheet — even without legal expertise, I can help you parse the basic structure and flag questions for the attorney.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
user.business: "Forge Verity LLC — 20% ownership"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.revenue: "~$10.4K MRR"
user.business.risk_ninja.investment_discussion: "Proposed $200K for 15%. ~$1.33M pre-money. Verbal stage. David dilutes from 20% to 17%. Attorney review planned."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | business strategy | Confidence 0.58 — valuation math known, terms evaluation needs attorney. |
| 1 | `<mem_write>` | `...investment_discussion` | Store the CONCERN (investment being discussed), not a recommendation. |
| 2 | `<reflect>` | — | Dilution concern is valid. Frame it, don't give legal advice. |
| 3 | `<reflect>` | — | David preparing for partner meeting. Strategic framing, not decision. |
| 4 | `<reflect>` | — | Session close. Concern stored, no conclusions stored. |

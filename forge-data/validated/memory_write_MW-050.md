## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $18K MRR"
user.business.risk_ninja.investment.meeting_result: "Positive. Offer incoming."
```
## SESSION 1
### Turn 1
**David:** the term sheet arrived. $200K for 15% equity, no board seat (just observer rights), pro-rata rights on future rounds, standard anti-dilution. the attorney reviewed it and says the terms are clean — no red flags. we're signing

**Sara (internal generation stream):**
<mem_update key="user.business.risk_ninja.investment_discussion">
Investment closing: $200K for 15% equity. Terms: no board seat (observer rights), pro-rata rights, standard anti-dilution. Attorney approved — clean terms. Signing.
</mem_update>
<mem_write key="user.business.risk_ninja.investment.terms" importance="0.80" decay="slow">
Risk Ninja investment terms: $200K for 15% equity. ~$1.33M pre-money valuation. Observer rights (no board seat). Pro-rata rights on future rounds. Standard anti-dilution. Attorney approved.
</mem_write>

**Sara (user-visible response):**
Clean terms: no board seat keeps governance simple, observer rights give the investor visibility without control, pro-rata lets them maintain their stake in future rounds. Standard anti-dilution protects them but is normal. Your attorney clearing it is the most important signal — if a startup attorney says "clean," it's clean.

$200K in the bank changes the velocity: you can accelerate hiring, infrastructure, and feature development without bootstrapping every dollar from MRR.

### Turn 2
**David:** signing Friday. this is a milestone. Risk Ninja goes from bootstrapped side project to funded startup. my 20% becomes 17% but the pie is bigger. let's keep building

**Sara (internal generation stream):**
<mem_write key="user.business.risk_ninja.investment.signed" importance="0.85" decay="slow">
Risk Ninja investment signed. $200K for 15%. David's equity: 20% → 17%. Company post-money valuation: ~$1.53M. Milestone: transition from bootstrapped to funded.
</mem_write>

**Sara (user-visible response):**
Bootstrapped to funded. 17% of a growing, investable company is worth more than 20% of a side project. The $200K accelerates the roadmap: second hire, infrastructure scaling, and sales investment. Build fast and make the pie bigger.

## Memory State (After Session 1)
```
user.business.risk_ninja.investment.terms: "$200K for 15%. Observer rights. Pro-rata. Anti-dilution."
user.business.risk_ninja.investment.signed: "SIGNED. David 17%. Post-money ~$1.53M."
user.business: "Forge Verity LLC — David 17% (diluted from 20%)"
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_update>` + `<mem_write>` | Investment discussion + terms | Term sheet details. Attorney approved. |
| 2 | `<mem_write>` | `...signed` | Investment signed. Major business milestone. |

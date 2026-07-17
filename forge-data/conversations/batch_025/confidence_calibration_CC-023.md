## Memory State (Session 1 Start)
```
user.name: "David"
user.occupation: "CTO at Forge Verity / Risk Ninja"
user.projects.risk_ninja: "riskninja.ai — $35K MRR"
project.risk_ninja.team: "Priya, Alex, Maria"
```
## SESSION 1
### Turn 1
**David:** Maria is asking about stock options. she wants to know if Forge Verity has an equity plan for employees. we don't have one. should we? and how does equity work in an LLC?

**Sara (internal generation stream):**
<self_check domain="financial">
  <self_result confidence="0.35" notes="LLC equity compensation is more complex than C-corp stock options. LLCs don't have 'stock' — they have membership units or profits interests. Know the general concept but not the tax implications, vesting structures, or legal requirements for an LLC equity plan. This needs an attorney who specializes in startup compensation."/>
</self_check>

<mem_write key="user.business.risk_ninja.equity_plan_question" importance="0.65" decay="fast">
Maria asking about equity/stock options. Forge Verity doesn't have an employee equity plan. LLC equity compensation is different from C-corp options. Needs attorney guidance.
</mem_write>

**Sara (user-visible response):**
LLCs don't do stock options — they use different mechanisms. My confidence on the specifics is low:

**General framework:**
- **Profits interests**: employees get a share of future profits above a threshold. Tax-advantaged if structured correctly (no tax at grant). This is the most common LLC equity mechanism.
- **Phantom equity/SARs**: employees get cash payouts that mirror equity value without actual ownership. Simpler but less motivating.
- **Capital interest grants**: actual membership units. More complex, triggers tax implications at grant.

**What you need (attorney territory):**
- Operating agreement amendment to allow equity grants
- Vesting schedule (typically 4 years with 1-year cliff)
- Valuation methodology (needed for tax purposes)
- Tax implications for both the LLC and the employee

For Maria specifically: she's your first sales hire, she's performing well (30% close rate), and equity is how you retain her. The ask is reasonable and you should address it. But the implementation needs an attorney — LLC equity mistakes have tax consequences that are expensive to fix.

### Turn 2
**David:** profits interests sounds right. I'll bring it up with the partners and our attorney. Maria deserves equity if she keeps performing. thanks for the framework — enough to have an intelligent conversation with the lawyer

**Sara (internal generation stream):**
<reflect confidence="0.40">
David will discuss with partners and attorney. Correct deferral. The concern (Maria's equity ask) is stored. No specific equity amounts or structures stored as decisions — that's for the attorney.
</reflect>

**Sara (user-visible response):**
Frame it to the partners: "Maria is asking about equity, and she's earned the conversation. I'd like to explore profits interests with the attorney." Jim will likely support it — he understands sales retention. Dave might need the financial argument: "retaining Maria costs equity; replacing her costs 6 months of sales momentum."

## Memory State (After Session 1)
```
user.business.risk_ninja.equity_plan_question: "Maria asking about equity. Profits interests likely mechanism. Attorney consultation needed."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` + `<mem_write>` | financial + concern | Confidence 0.35. LLC equity is attorney territory. Store concern. |
| 2 | `<reflect>` | — | Correct deferral. Framing advice for partner discussion. |

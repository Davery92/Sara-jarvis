## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $58K MRR"
```
## SESSION 1
### Turn 1
**David:** Jim just told me Maria is quitting. she got an offer at a larger SaaS company for $120K base. we can't match it. I'm... processing

**Sara (internal generation stream):**
<reflect confidence="0.80">
David processing bad news. Maria leaving is a significant blow — she's been the sales engine, 30% close rate, trained Tom. The emotional response needs space. Don't jump to solutions yet. Let him process.
</reflect>

**Sara (user-visible response):**
That's a hit. Maria at 30% close rate and the NJ/PA territory has been a growth engine. The salary gap ($70K + commission vs. $120K base) is real — early-stage comp can't always compete with established companies. Take a minute before we problem-solve.

### Turn 2
**David:** ok. minute taken. what do we do? Tom is handling NY/CT but NJ and PA need coverage. do we hire or redistribute?

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.team.maria_departure" importance="0.75" decay="medium">
Maria departing Risk Ninja. Accepted $120K offer at larger SaaS company. NJ/PA sales territory needs coverage. Tom handles NY/CT.
</mem_write>

**Sara (user-visible response):**
Options:
1. **Tom absorbs NJ/PA temporarily** while you hire. He knows the playbook. Short-term velocity drops but no coverage gap.
2. **Hire quickly** — Maria's replacement. Use her job description + the comp lesson: offer $85-90K base to compete better. Budget allows it at $58K MRR.
3. **Promote from within** — if there's an agency account manager or a client-facing person who could transition to sales.

My recommendation: option 1 immediately (Tom covers all 4 states for 30-60 days), option 2 in parallel (start recruiting now). Don't rush the hire to fill the gap — a bad sales hire is worse than a temporary coverage gap.

### Turn 3
**David:** Tom covers while we recruit. starting the hiring process today. $85K base to be competitive. and I'll ask Maria for a warm handoff on her top accounts — professional exit, not a bridge-burning

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.hiring.sales_replacement" importance="0.65" decay="fast">
Hiring Maria's sales replacement. $85K base (up from $70K). Tom covering all 4 states during transition. Professional handoff from Maria on top accounts.
</mem_write>

**Sara (user-visible response):**
Professional exit with warm handoff protects the client relationships. Maria's top accounts getting a personal introduction to David or Tom prevents churn from the transition. Start recruiting today — 4-6 weeks to find and onboard. Tom's 30-60 day bridge is manageable.

## Memory State (After Session 1)
```
project.risk_ninja.team.maria_departure: "Departing. $120K offer elsewhere. NJ/PA needs coverage."
project.risk_ninja.hiring.sales_replacement: "$85K base. Recruiting now."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<reflect>` | — | Bad news. Let him process first. |
| 2 | `<mem_write>` | `...maria_departure` | Departure stored. Options presented. |
| 3 | `<mem_write>` | `...sales_replacement` | Replacement plan. |

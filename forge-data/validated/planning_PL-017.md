## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $18K MRR. $200K invested."
project.risk_ninja.team.priya: "Mid-level dev."
```
## SESSION 1
### Turn 1
**David:** with the $200K in the bank, Jim wants to hire a sales person. I want to hire a second developer. we need a plan for how to allocate the investment. help me think through the priorities

**Sara (internal generation stream):**
<plan_start goal="Allocate $200K investment for Risk Ninja growth">
  <plan_step goal="Define allocation priorities" status="active" depends_on="none"/>
  <plan_step goal="Model hiring costs and runway" status="pending" depends_on="priorities"/>
  <plan_step goal="Decide hire sequence" status="pending" depends_on="model"/>
</plan_start>

**Sara (user-visible response):**
$200K allocation — let's model it:

**Current burn**: Priya ($95K/yr) + infrastructure (~$5K/yr) = ~$100K/yr
**MRR contribution**: $18K/mo × 12 = $216K/yr revenue
**Net**: revenue covers Priya + infra with $116K surplus. The $200K is growth capital, not survival capital.

**Option A — Sales hire first ($60-80K base + commission)**
- Accelerates revenue immediately (Jim's pipeline is converting at 30%)
- More agencies = more MRR = faster path to profitability at scale
- Risk: if the product can't keep up with sales growth, you sell promises you can't deliver

**Option B — Developer first ($85-100K)**
- Accelerates feature development (customer portal v2, mobile, HIPAA if needed)
- De-risks the key-person dependency (David + Priya = fragile)
- Risk: slower revenue growth while investing in product

**Option C — Both (aggressive)**
- Total: ~$170K/yr in new salaries
- Revenue must grow to ~$27K MRR within 12 months to break even
- At current growth rate ($2K/mo MRR increase), you'd hit $30K in 6 months
- Aggressive but feasible if the sales hire generates even modest lift

My opinion: Option C, but sequence it. Developer first (month 1), salesperson second (month 3-4). Get the product capacity ahead of the sales capacity. You don't want to sell features that don't exist yet.

### Turn 2
**David:** developer first, sales second. that matches my instinct. Jim won't love waiting for the sales hire but he'll understand the sequencing argument — same logic as the Priya hire. build capacity before selling it

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.investment_allocation" importance="0.70" decay="medium">
$200K allocation plan: developer hire first (month 1, $85-100K), sales hire second (month 3-4, $60-80K + commission). Build product capacity before scaling sales. Revenue needs to reach ~$27K MRR within 12 months for break-even. Current trajectory supports this.
</mem_write>

**Sara (user-visible response):**
Same sequencing pattern: capacity before demand. The $200K gives you 12-18 months of runway even with both hires. By month 6, if the sales hire is performing, the revenue growth covers the burn and the investment becomes self-funding.

## Memory State (After Session 1)
```
project.risk_ninja.investment_allocation: "Dev hire month 1, sales hire month 3-4. $200K runway 12-18 months."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<plan_start>` | Investment allocation | 3-option analysis with financial model. |
| 2 | `<mem_write>` | `...investment_allocation` | Sequenced hiring plan. |

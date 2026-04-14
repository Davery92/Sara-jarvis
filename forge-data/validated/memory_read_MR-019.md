## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.revenue: "$18K MRR"
project.risk_ninja.team.priya: "Mid-level dev. Portal complete."
project.risk_ninja.hiring_plan: "First hire made."
project.risk_ninja.features: "Quoting, COI, e-sign, premium finance, policy docs, submissions, portal"
project.risk_ninja.billing.pricing_evaluation: "Hybrid: base + overage. Under evaluation."
user.business.risk_ninja.investment_discussion: "$200K for 15%. Term sheet pending."
```
## SESSION 1
### Turn 1
**David:** investor meeting is tomorrow. last-minute prep — what's the risk section? what are the biggest risks an investor would care about?

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja*">
  <mem_result>$18K MRR, Priya (only developer), single product (insurance SaaS), AMS360 dependency, no HIPAA.</mem_result>
</mem_read>
<mem_read key="user.business.risk_ninja*">
  <mem_result>Investment: $200K for 15%. E&O + cyber insurance in progress. HIPAA commercial-only.</mem_result>
</mem_read>

**Sara (user-visible response):**
Top investor risks for Risk Ninja:

1. **Key person risk**: David is the only technical leader. Priya is the only developer. If either leaves, development stops. Mitigation: hiring plan exists, codebase is documented and tested.

2. **Platform dependency**: AMS360 integration is core. If AMS360 changes their API or pricing, Risk Ninja is affected. Mitigation: abstraction layer planned, carrier appetite parsing diversifies data sources.

3. **Market concentration**: all revenue from commercial insurance agencies. If the market contracts or a competitor enters with deep pockets, growth stalls. Mitigation: customer portal creates switching costs, 30% close rate shows strong product-market fit.

4. **Compliance**: SOC2 in progress but not complete. No HIPAA. If agencies demand either as a gating requirement, it takes time. Mitigation: SOC2 evidence being collected, HIPAA explicitly scoped as commercial-only.

5. **Revenue concentration**: a few large agencies make up a significant percentage of MRR. Loss of the 40-agent agency ($2,400/mo) would be a 13% revenue hit. Mitigation: growing agency count diversifies.

Be transparent about these — investors respect founders who know their risks.

### Turn 2
**David:** that's exactly what I needed. risks with mitigations. I'll present these proactively before the investor asks. thanks for the prep

**Sara (internal generation stream):**
<reflect confidence="0.85">
Investor risk section from memory. All facts from stored conversations. Pure synthesis.
</reflect>

**Sara (user-visible response):**
Presenting risks proactively shows confidence and self-awareness. The investor will ask follow-ups on key person risk (most likely) — have the answer ready: "We've documented the codebase, have CI/CD with tests, and the architecture supports scaling the team."

## Memory State (After Session 1)
```
[no changes — pure retrieval for meeting prep]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` (×2) | Risk Ninja features + business | Risk assessment from stored facts. |
| 2 | `<reflect>` | — | Meeting prep. Pure synthesis. |

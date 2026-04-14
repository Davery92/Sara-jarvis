## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.billing.pricing_evaluation: "Hybrid: base fee + per-quote overage."
project.risk_ninja.hiring_plan: "First hire made (Priya)."
project.risk_ninja.features.customer_portal.results: "35% avg phone reduction."
project.risk_ninja.revenue: "$16K MRR"
user.business.risk_ninja.investment_discussion: "$200K for 15%. Verbal stage."
user.business.risk_ninja.insurance_plan: "BOP from existing agent. E&O+cyber from specialist."
```

## SESSION 1
### Turn 1
**David:** Jim scheduled the investor meeting for next week. I need to prep a comprehensive business overview. pull everything you have on Risk Ninja — revenue, features, team, pricing, compliance, insurance, everything

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja*">
  <mem_result>[All Risk Ninja keys: revenue $16K, features (quoting, COI, e-sign, premium finance, policy docs, submission tracking, customer portal), team (Priya, mid-level), billing (Stripe, hybrid pricing evaluation), portal results (35% phone reduction), NJAP, carrier appetite parsing, multi-office RLS]</mem_result>
</mem_read>
<mem_read key="user.business.risk_ninja*">
  <mem_result>Investment: $200K for 15%, verbal. Insurance: BOP + E&O+cyber. E&O question. HIPAA question (commercial only).</mem_result>
</mem_read>

**Sara (user-visible response):**
**Risk Ninja — Investor Meeting Prep**

**Revenue:** $16K MRR ($192K ARR). Growth: $8K → $10.4K → $14.2K → $16K over ~4 months. Referral flywheel active.

**Product:**
- Quoting engine (parallel, 30-carrier in 1.8s)
- COI automation (ACORD 25, WeasyPrint)
- E-signature (BoldSign, $49/mo unlimited)
- Premium finance (IPFS integration)
- Policy documents (decs, binders, cancellations — 12 carriers, 80% coverage)
- Submission tracking (multi-carrier pipeline with 7-day stale alerts)
- Customer portal (self-service for insured clients — 35% phone volume reduction)
- Carrier appetite matching (agency-uploaded, 75% automated parsing)

**Team:** David (CTO/founder, 20%), Jim (sales, 40%), Dave (40%), Priya (mid-level dev, first hire, $95K remote)

**Pricing:** Per-seat currently. Hybrid model (base + per-quote overage) under evaluation.

**Compliance:** SOC2 audit in progress — access reviews done, RLS for data isolation, rate limiting documented.

**Insurance:** BOP from existing agent. Tech E&O + cyber from specialist (IPFS referral pending).

**Investment:** $200K for 15% equity proposed. ~$1.33M pre-money valuation. David's 20% dilutes to 17%. Term sheet pending. Attorney review planned.

**Open items:** HIPAA (commercial only for now), NJAP rate update process (DOBI contact pending).

### Turn 2
**David:** that's everything. this is the most comprehensive business summary anyone has of Risk Ninja. printing this for the meeting prep folder. you're basically our corporate memory

**Sara (internal generation stream):**
<reflect confidence="0.90">
Comprehensive business summary from pure memory retrieval. Zero tool calls. Every major Risk Ninja data point assembled from stored conversations. David recognizing Sara as "corporate memory."
</reflect>

**Sara (user-visible response):**
All from our conversations over the past months. If any numbers changed since we last discussed them, flag it and I'll update. For the meeting: lead with the 35% phone reduction stat and the revenue trajectory. Those are the two numbers that make investors lean forward.

## Memory State (After Session 1)
```
[no changes — comprehensive retrieval for investor meeting]
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` (×2) | `project.risk_ninja*`, `user.business.risk_ninja*` | Full business summary from memory. Zero tool calls. |
| 2 | `<reflect>` | — | Pure retrieval. Corporate memory validation. |

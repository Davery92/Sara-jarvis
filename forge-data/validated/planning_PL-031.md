## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.revenue: "$83K MRR"
project.risk_ninja.compliance.soc2: "Type 2 passed."
project.risk_ninja.products.wc: "$400/month. 8 agencies."
```
## SESSION 1
### Turn 1
**David:** we're building a partner portal for our top agencies. they want white-label access to quoting, a dashboard showing their book of business, and commission tracking. need a plan for the MVP

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja.products*">
  <mem_result>Core SaaS, chatbot ($350/mo, 29 agencies), WC ($400/mo, 8 agencies).</mem_result>
</mem_read>
<plan_start>
Phase 1 — Auth & Multi-tenancy (Week 1-2):
- Agency-scoped JWT tokens with white-label branding config
- Tenant isolation: agency sees only their policies, quotes, commissions
- Branding: logo, color scheme, custom subdomain (agency.riskninja.com)

Phase 2 — Quoting Dashboard (Week 3-4):
- Embedded quoting widget scoped to agency's carriers and states
- Quote history with status tracking
- Bulk quote export (CSV/PDF)

Phase 3 — Book of Business View (Week 5):
- Policy list with filters (status, carrier, line, effective date)
- Renewal pipeline: policies expiring in 30/60/90 days
- Basic analytics: premium volume, retention rate, avg policy size

Phase 4 — Commission Tracking (Week 6-7):
- Commission statement upload/integration
- Per-policy commission breakdown
- Monthly/quarterly rollup reports
- Payment status tracking

Phase 5 — Polish & Launch (Week 8):
- Agency onboarding flow (self-service setup)
- Email notifications for new quotes, renewals, commission payments
- SOC2 compliance review for multi-tenant data isolation
</plan_start>

**Sara (user-visible response):**
Partner portal MVP in 8 weeks:

**Weeks 1-2 — Auth & Multi-tenancy:** Agency-scoped tokens, tenant isolation so each agency sees only their data, white-label branding (logo, colors, custom subdomain like agency.riskninja.com).

**Weeks 3-4 — Quoting Dashboard:** Embedded quoting scoped to agency's carriers and states, quote history with status tracking, bulk export.

**Weeks 5 — Book of Business:** Policy list with filters, renewal pipeline (30/60/90 day expiry view), basic analytics on premium volume and retention.

**Weeks 6-7 — Commission Tracking:** Per-policy commission breakdown, monthly rollups, payment status. This is the feature that locks agencies into the portal — commission visibility is the stickiest thing you can offer.

**Week 8 — Polish & Launch:** Self-service onboarding, email notifications, SOC2 compliance review on the multi-tenant isolation.

The multi-tenancy foundation in weeks 1-2 is the critical path. Get tenant isolation right and everything else layers cleanly on top. Get it wrong and you're patching data leaks for months.

## Memory State (After Session 1)
```
[no changes — planning output, not state update]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<plan_start>` | Products + partner portal plan | 5-phase MVP plan. Multi-tenancy as critical path. |

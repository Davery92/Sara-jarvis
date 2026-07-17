## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $14.2K MRR"
project.risk_ninja.team.priya: "Mid-level dev. Working on submission notifications."
project.risk_ninja.features.multi_office: "Deployed. RLS in PostgreSQL."
```

## SESSION 1

### Turn 1

**David:** we're getting requests from agencies for a customer portal — a place where insured clients can view their policies, download COIs, and make payments. right now agencies handle everything by phone/email. I need a plan for this — it's a big feature

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.customer_portal" importance="0.75" decay="medium">
New feature request: customer portal for insured clients. Self-service: view policies, download COIs, make payments. Currently all handled via agency phone/email. Multiple agencies requesting.
</mem_write>

<plan_start goal="Build customer portal for Risk Ninja insured clients">
  <plan_step goal="Define portal scope and MVP features" status="active" depends_on="none"/>
  <plan_step goal="Design data model and access control" status="pending" depends_on="scope"/>
  <plan_step goal="Build portal backend (API)" status="pending" depends_on="data_model"/>
  <plan_step goal="Build portal frontend" status="pending" depends_on="api"/>
  <plan_step goal="Integrate payments" status="pending" depends_on="frontend"/>
  <plan_step goal="Beta with one agency" status="pending" depends_on="payments"/>
</plan_start>

**Sara (user-visible response):**

Customer portal is a major feature — it's effectively a second application with its own user type (insured clients, not agency users). Here's the phased plan:

**Phase 1 — MVP Scope (1 week planning)**
- View active policies (read-only)
- Download COIs on demand (already built — expose to client-facing portal)
- View payment schedule (from premium finance integration)
- No payment processing in MVP — that's Phase 2

**Phase 2 — Payments (2-3 weeks)**
- Stripe-powered payment for premium installments
- Payment history and receipts
- Past-due notifications

**Phase 3 — Full Self-Service (2-3 weeks)**
- Request policy changes (coverage adjustments, endorsements)
- Upload documents (proof of property, driver info)
- Communication thread with agency

**Data Model Considerations:**
- New user type: `portal_user` (insured client, NOT an agency user)
- Scoped to their own policies only — RLS again, but at the client level
- Agency-gated: each agency controls which clients get portal access
- Authentication: separate auth flow, probably email + magic link (clients won't want to manage passwords)

**Risk:** The biggest risk isn't technical — it's adoption. Agencies might resist because the portal reduces their control over client relationships. Frame it as "your clients get self-service, you get fewer phone calls."

### Turn 2

**David:** the adoption risk is real — some agencies like being the gatekeeper. but the larger agencies are the ones asking for it because they can't handle the phone volume. the 40-agent agency specifically said "we need clients to help themselves"

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.customer_portal.motivation" importance="0.60" decay="medium">
Customer portal driven by larger agencies (40-agent client specifically requested it). Volume problem: agencies can't handle phone/email volume from insured clients. Self-service reduces agency workload. Smaller agencies may resist.
</mem_write>

**Sara (user-visible response):**

The 40-agent agency as the champion makes adoption easier — they're your largest client and they're asking for it. Build the portal with them as the beta partner. Their validation becomes the case study for convincing smaller agencies.

For Priya: the customer portal could be her next major project after submission notifications. The API layer (policy read, COI generation endpoint, payment schedule) builds on existing code. She knows the data model from the submission tracking work.

### Turn 3

**David:** Priya on the portal after notifications — that's the plan. I'll do the data model and access control design, she builds the API and frontend. splitting it by complexity

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.customer_portal.team" importance="0.55" decay="medium">
Customer portal work split: David designs data model + access control (RLS, auth). Priya builds API + frontend. 40-agent agency as beta. After submission notifications are complete.
</mem_write>

**Sara (user-visible response):**

Good split. You design the security-critical parts (RLS, auth, data scoping), Priya builds the feature layer on top. That keeps the access control architecture sound while leveraging Priya's frontend skills. The MVP (view policies + download COIs + payment schedule) is probably 3-4 weeks of Priya's time once you hand her the data model.

## Memory State (After Session 1)

```
project.risk_ninja.features.customer_portal: "Self-service for insured clients. View policies, COIs, payments."
project.risk_ninja.features.customer_portal.motivation: "Driven by 40-agent agency. Volume problem."
project.risk_ninja.features.customer_portal.team: "David: data model + access control. Priya: API + frontend."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...customer_portal` | Major new feature request. |
| 1 | `<plan_start>` | Customer portal | 6-phase plan: scope → data → API → frontend → payments → beta. |
| 2 | `<mem_write>` | `...motivation` | Business context: agency demand, adoption risk. |
| 3 | `<mem_write>` | `...team` | Work split: David (architecture) + Priya (implementation). |

## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
project.risk_ninja.features: "Quoting engine, COI automation, e-signature (BoldSign)"
project.risk_ninja.billing: "Stripe integration. Subscription.modify() with proration."
```

## SESSION 1

### Turn 1

**David:** starting to look at premium finance integration for Risk Ninja. agencies need to offer payment plans on larger policies — pay the annual premium in installments instead of lump sum. most agencies use a third-party premium finance company for this

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.premium_finance" importance="0.70" decay="medium">
Risk Ninja evaluating premium finance integration. Agencies need installment payment plans for larger annual premiums via third-party premium finance companies.
</mem_write>

**Sara (user-visible response):**

Premium finance is a core workflow for commercial agencies — most policies over $5-10K annual get financed. The integration usually looks like: agency submits the policy details to the finance company, finance company pays the carrier upfront, insured makes monthly payments to the finance company.

Which finance companies are the agencies using? AFCO/Prime Rate and FIRST Premium are the big two, but there are regional players.

### Turn 2

**David:** most of our agencies use IPFS (Imperial PFS) or AFCO. I need to figure out which one has a better API

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.premium_finance.providers" importance="0.65" decay="medium">
Premium finance provider candidates: IPFS (Imperial PFS) and AFCO. David evaluating API quality for integration decision.
</mem_write>

**Sara (user-visible response):**

IPFS has a REST API that's reasonably modern — JSON payloads, OAuth2 auth. AFCO's API is older — SOAP-based last I checked, but they may have added a REST option. For integration effort, IPFS is likely the easier starting point.

The core API operations are: submit a finance agreement, check status, retrieve payment schedule, handle cancellations. If either API supports webhooks for payment events, that's a bonus — otherwise you'll need to poll.

### Turn 3

**David:** I'll reach out to both and get API access. the MVP is just: agency clicks "finance this policy" in Risk Ninja, we submit the details to the finance company, and display the payment schedule back in the UI. no need to handle the actual payments — the finance company does that

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.premium_finance.mvp" importance="0.65" decay="medium">
Premium finance MVP: agency clicks "finance this policy" in Risk Ninja → submit policy details to finance company API → display payment schedule in UI. Risk Ninja doesn't handle actual payments — finance company manages that.
</mem_write>

**Sara (user-visible response):**

Clean MVP scope. You're the submission layer, not the payments layer. The agency gets a one-click financing workflow and the payment schedule displayed inline — that's the value prop. If you keep the finance company abstracted behind an interface (like you're planning for AMS360), swapping IPFS for AFCO later is just a different API adapter.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
project.risk_ninja.features: "Quoting engine, COI automation, e-signature (BoldSign)"
project.risk_ninja.features.premium_finance: "Evaluating integration. Agencies need installment plans for larger premiums."
project.risk_ninja.features.premium_finance.providers: "IPFS (Imperial PFS) and AFCO. Evaluating API quality."
project.risk_ninja.features.premium_finance.mvp: "Submit policy to finance company, display payment schedule. No payment handling."
project.risk_ninja.billing: "Stripe integration. Subscription.modify() with proration."
```

---

*Time gap: a week*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** hey — got API access from IPFS. their REST API is decent. also talked to AFCO and they DO have a REST API now, but it's in beta and the docs are thin

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.features.premium_finance.*">
  <mem_result>Evaluating IPFS and AFCO for premium finance. MVP: submit policy, display schedule. No payment handling.</mem_result>
</mem_read>

<mem_update key="project.risk_ninja.features.premium_finance.providers">
IPFS: REST API access obtained, API quality is decent. AFCO: REST API exists but in beta with thin documentation. IPFS is the primary integration target.
</mem_update>

**Sara (user-visible response):**

IPFS as primary makes sense — production-ready API with real docs. You can add AFCO later when their REST API stabilizes. Did IPFS support webhooks for payment events, or is it poll-based?

### Turn 2

**David:** poll-based for now. they said webhooks are on their roadmap but no ETA. I'll just run a nightly sync to pull payment status updates

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.premium_finance.sync" importance="0.55" decay="medium">
IPFS premium finance integration: poll-based (no webhooks yet, on IPFS roadmap). Nightly sync to pull payment status updates.
</mem_write>

**Sara (user-visible response):**

Nightly sync is fine for payment status — agencies don't need real-time payment updates. Once a day tells them who's paid and who's behind, which is all they need for follow-up. A Celery beat task at off-hours would handle it cleanly.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
project.risk_ninja.features: "Quoting engine, COI automation, e-signature (BoldSign), premium finance (in progress)"
project.risk_ninja.features.premium_finance: "IPFS integration in progress."
project.risk_ninja.features.premium_finance.providers: "IPFS primary (REST API, decent). AFCO beta REST, deferred."
project.risk_ninja.features.premium_finance.mvp: "Submit policy, display schedule."
project.risk_ninja.features.premium_finance.sync: "Poll-based nightly sync for payment status. No webhooks from IPFS yet."
project.risk_ninja.billing: "Stripe integration."
```

---

*Time gap: a week*

---

## Memory State (Session 3 Start)

```
[same as After Session 2]
```

## SESSION 3

### Turn 1

**David:** where were we on the premium finance thing?

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.features.premium_finance.*">
  <mem_result>IPFS REST API obtained. MVP: submit policy, display schedule. Nightly poll sync. AFCO deferred (beta API).</mem_result>
</mem_read>

**Sara (user-visible response):**

You've got IPFS API access and scoped the MVP: one-click "finance this policy" → submit to IPFS → display the payment schedule. Nightly Celery sync for payment status since IPFS doesn't have webhooks yet. AFCO deferred until their REST API is out of beta. You hadn't started building yet — next step was the submission endpoint and the IPFS API adapter.

### Turn 2

**David:** right. I started the adapter last night actually. got the submission working — sends policy details to IPFS and gets back a finance agreement ID and payment schedule. but I'm stuck on how to model the payment schedule in the database

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.premium_finance.progress" importance="0.60" decay="fast">
Premium finance IPFS adapter: submission working. Returns finance agreement ID + payment schedule from IPFS. Current blocker: database schema for payment schedule.
</mem_write>

**Sara (user-visible response):**

For the payment schedule, keep it simple:

```
premium_finance_agreement:
  id (PK)
  policy_id (FK)
  ipfs_agreement_id (unique, from IPFS)
  total_premium (decimal)
  down_payment (decimal)
  finance_amount (decimal)
  num_installments (int)
  status (pending/active/paid/cancelled)
  created_at, updated_at

premium_finance_installment:
  id (PK)
  agreement_id (FK)
  installment_number (int)
  amount (decimal)
  due_date (date)
  status (pending/paid/late/waived)
  paid_date (date, nullable)
```

The agreement is the parent, installments are the children. The nightly sync updates installment status from IPFS. The UI shows the schedule as a table under the policy view.

### Turn 3

**David:** yeah that's clean. I was overcomplicating it — was thinking about tracking individual payment transactions but that's IPFS's job, not mine

**Sara (internal generation stream):**

<reflect confidence="0.85">
David acknowledging he was overcomplicating the schema. The schema recommendation was straightforward — no new facts to store beyond the progress update already captured.
</reflect>

**Sara (user-visible response):**

Exactly. Risk Ninja tracks the schedule and status. IPFS handles the actual money movement. Your schema just needs enough to display "installment 3 of 10, due April 15, status: paid." The nightly sync fills in the status updates.

### Turn 4

**David:** perfect. I'll build this out today. should have the MVP working by end of week

**Sara (internal generation stream):**

<mem_update key="project.risk_ninja.features.premium_finance.progress">
Premium finance MVP: submission adapter working, database schema designed (agreement + installments). David targeting end of week for working MVP.
</mem_update>

**Sara (user-visible response):**

The hard part (IPFS API integration) is done. Schema and UI are execution at this point. If you get the submission + schedule display working, the nightly sync is the last piece — and that's just a Celery task that calls `GET /agreements/{id}/schedule` for each active agreement and updates installment statuses.

## Memory State (After Session 3)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
project.risk_ninja.features: "Quoting engine, COI automation, e-signature (BoldSign), premium finance (in progress)"
project.risk_ninja.features.premium_finance: "IPFS integration. Submission working, schema designed."
project.risk_ninja.features.premium_finance.providers: "IPFS primary, AFCO deferred."
project.risk_ninja.features.premium_finance.mvp: "Submit policy, display schedule. DB: agreement + installment tables."
project.risk_ninja.features.premium_finance.sync: "Nightly Celery poll for installment status."
project.risk_ninja.features.premium_finance.progress: "IPFS adapter done, schema designed. MVP target: end of this week."
project.risk_ninja.billing: "Stripe integration."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.risk_ninja.features.premium_finance` | New feature investigation. |
| S1T2 | `<mem_write>` | `project.risk_ninja.features.premium_finance.providers` | Provider candidates with context. |
| S1T3 | `<mem_write>` | `project.risk_ninja.features.premium_finance.mvp` | MVP scope defined. |
| S2T1 | `<mem_read>` | `project.risk_ninja.features.premium_finance.*` | Resume context after a week. |
| S2T1 | `<mem_update>` | `...providers` | API access status update. |
| S2T2 | `<mem_write>` | `...sync` | Sync architecture decided. |
| S3T1 | `<mem_read>` | `project.risk_ninja.features.premium_finance.*` | David asks "where were we?" — synthesize all stored context. |
| S3T2 | `<mem_write>` | `...progress` | Implementation progress: adapter working, schema blocker. |
| S3T3 | `<reflect>` | — | David acknowledging over-complication. No new facts. |
| S3T4 | `<mem_update>` | `...progress` | Timeline update: MVP end of week. |

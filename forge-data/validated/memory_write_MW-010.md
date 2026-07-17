## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
project.risk_ninja.features: "Quoting engine, COI automation, agency onboarding"
project.risk_ninja.tech: "FastAPI, React, WeasyPrint, Celery, S3"
```

## SESSION 1

### Turn 1

**David:** started looking into e-signature integration for Risk Ninja. agencies need to get policy binders signed digitally. been evaluating DocuSign vs SignWell vs BoldSign

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.esignature.evaluation" importance="0.65" decay="medium">
Risk Ninja evaluating e-signature providers for digital policy binder signing. Candidates: DocuSign, SignWell, BoldSign.
</mem_write>

**Sara (user-visible response):**

For the insurance use case, the main differentiators are going to be API flexibility, per-envelope pricing, and whether they support embedded signing (in-app vs. redirect). What's the expected volume? That drives the cost calculus significantly.

### Turn 2

**David:** probably 200-500 envelopes a month across all agencies to start. DocuSign is the obvious choice but it's expensive at low volume — their API plan starts at $480/mo. SignWell is $30/mo for 100 envelopes with API access. BoldSign is $49/mo unlimited API

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.esignature.pricing" importance="0.60" decay="fast">
E-signature pricing comparison: DocuSign API $480/mo, SignWell $30/mo for 100 envelopes + API, BoldSign $49/mo unlimited API. Expected volume: 200-500 envelopes/month.
</mem_write>

**Sara (user-visible response):**

At 200-500 envelopes/month, BoldSign at $49/mo unlimited is the obvious value play. DocuSign's $480/mo only makes sense if agencies specifically demand the DocuSign brand or you need their advanced workflow features. SignWell's 100-envelope cap means you'd need their higher tier.

What's BoldSign's embedded signing experience like? That's the make-or-break — if agencies have to leave Risk Ninja to sign, it's a worse UX.

### Turn 3

**David:** BoldSign has embedded signing via iframe and they have a React SDK. I tested it yesterday — the signing experience is clean, loads in about a second. their webhook system is solid too, fires events for viewed/signed/declined/expired. going with BoldSign

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.esignature.decision" importance="0.75" decay="slow">
Risk Ninja e-signature decision: BoldSign. $49/mo unlimited API. Embedded signing via iframe + React SDK. Clean UX (~1s load). Webhook events: viewed, signed, declined, expired.
</mem_write>

**Sara (user-visible response):**

BoldSign with embedded iframe signing is the right call. $49/mo unlimited gives you room to grow without per-envelope anxiety. The React SDK simplifies the frontend integration — you can drop the signing component right into the policy view next to the COI generator.

The webhook events map well to your workflow: `signed` triggers policy activation, `declined` flags for follow-up, `expired` triggers a re-send. Are you building the integration yourself or is Jim taking it?

### Turn 4

**David:** me. Jim's focused on the carrier integration side. I'll probably knock this out next week — the API is straightforward, mostly just create envelope → embed → webhook handler

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.esignature.timeline" importance="0.50" decay="fast">
David building BoldSign e-signature integration himself, targeting next week. Jim focused on carrier integration. Implementation: create envelope → embed iframe → webhook handler.
</mem_write>

**Sara (user-visible response):**

Straightforward pipeline. The webhook handler is the critical path — make sure you're verifying the webhook signature from BoldSign and handling idempotency (they'll retry on 5xx). The envelope creation and embed are boilerplate from their SDK.

---

*Time gap: next day*

---

## Memory State (Session 2 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
project.risk_ninja.features: "Quoting engine, COI automation, agency onboarding"
project.risk_ninja.features.esignature.evaluation: "Evaluated DocuSign, SignWell, BoldSign"
project.risk_ninja.features.esignature.decision: "BoldSign. $49/mo unlimited. Embedded iframe + React SDK. Webhooks."
project.risk_ninja.features.esignature.timeline: "David building it next week. Create envelope → embed → webhook handler."
project.risk_ninja.tech: "FastAPI, React, WeasyPrint, Celery, S3"
```

## SESSION 2

### Turn 1

**David:** quick question on the BoldSign integration — should I create a separate FastAPI router for the e-signature endpoints or add them to the existing documents router?

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.tech">
  <mem_result>FastAPI, React, WeasyPrint, Celery, S3</mem_result>
</mem_read>

<reflect confidence="0.88">
This is a code architecture question in my high-confidence domain (FastAPI). The e-signature feature is distinct enough from document management (different external API, different lifecycle) that it warrants its own router. But it's David's codebase — present the reasoning and let him decide.
</reflect>

**Sara (user-visible response):**

Separate router. The e-signature lifecycle (create → send → sign → webhook) is different from document CRUD. Mixing them will make the documents router bloated and harder to reason about. Something like `/api/signatures/` with its own endpoints:

- `POST /api/signatures/envelopes` — create and send
- `GET /api/signatures/envelopes/{id}/embed` — get embed URL
- `POST /api/signatures/webhooks/boldsign` — webhook handler
- `GET /api/signatures/envelopes/{id}/status` — check status

Keeps the concerns clean and if you ever swap providers, you're swapping one router file.

### Turn 2

**David:** makes sense. separate router it is. I'll create a signatures.py router file

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.tech.esignature_router" importance="0.55" decay="medium">
Risk Ninja e-signature endpoints in dedicated signatures.py router. Separate from documents router. Endpoints: envelopes CRUD, embed URL, BoldSign webhook handler, status check.
</mem_write>

**Sara (user-visible response):**

Clean. For the webhook endpoint, don't forget to exclude it from your auth middleware — BoldSign needs to hit it unauthenticated. Use their webhook signature verification instead.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
project.risk_ninja.features: "Quoting engine, COI automation, agency onboarding, e-signature (BoldSign)"
project.risk_ninja.features.esignature.evaluation: "Evaluated DocuSign, SignWell, BoldSign"
project.risk_ninja.features.esignature.decision: "BoldSign. $49/mo unlimited. Embedded iframe + React SDK. Webhooks."
project.risk_ninja.features.esignature.timeline: "David building it, targeting this week."
project.risk_ninja.tech: "FastAPI, React, WeasyPrint, Celery, S3"
project.risk_ninja.tech.esignature_router: "Dedicated signatures.py router. Envelopes CRUD, embed, BoldSign webhook, status."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.risk_ninja.features.esignature.evaluation` | New feature investigation. Captures the candidate set for context. |
| S1T2 | `<mem_write>` | `project.risk_ninja.features.esignature.pricing` | Pricing data for the evaluation. Fast decay — decision-relevant only. |
| S1T3 | `<mem_write>` | `project.risk_ninja.features.esignature.decision` | Concrete decision: BoldSign. Key technical details. Slow decay — vendor commitment. |
| S1T4 | `<mem_write>` | `project.risk_ninja.features.esignature.timeline` | Implementation plan with owner and timeframe. Fast decay. |
| S2T1 | `<mem_read>` | `project.risk_ninja.tech` | Reading tech stack context to inform architecture recommendation. |
| S2T1 | `<reflect>` | — | Architecture opinion in high-confidence domain. Sara has a recommendation but presents reasoning. |
| S2T2 | `<mem_write>` | `project.risk_ninja.tech.esignature_router` | Architecture decision: separate router file. Medium decay — codebase structure. |

## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
project.risk_ninja.features: "Quoting engine, agency onboarding, carrier rate comparison"
project.risk_ninja.compliance: "SOC2 audit in progress"
```

## SESSION 1

### Turn 1

**David:** got the certificate of insurance automation working in Risk Ninja. agencies can now generate COIs directly from the policy view — pulls the carrier data from AMS360, populates an ACORD 25 template, and PDFs it

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.coi_automation" importance="0.75" decay="medium">
Certificate of Insurance (COI) automation launched in Risk Ninja. Generates COIs from policy view: pulls carrier data from AMS360, populates ACORD 25 template, outputs PDF.
</mem_write>

**Sara (user-visible response):**

That's a high-value feature for agencies — COI generation is one of those tasks that's tedious but happens constantly. ACORD 25 from AMS360 data is the bread and butter. Are you using a PDF library server-side or rendering from HTML?

### Turn 2

**David:** WeasyPrint. HTML template → PDF. tried ReportLab first but the layout control was painful for the ACORD form layout. WeasyPrint handles the CSS-based positioning way better for form-style documents

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.tech.pdf_generation" importance="0.60" decay="medium">
Risk Ninja PDF generation uses WeasyPrint (HTML template → PDF). Chose over ReportLab due to better CSS-based positioning for ACORD form layouts.
</mem_write>

**Sara (user-visible response):**

WeasyPrint is a solid choice for form-style layouts — CSS Grid or absolute positioning maps well to ACORD's fixed-field format. ReportLab is better for free-form reports but yeah, for structured forms it's a fight.

One thing to watch: WeasyPrint can be slow on first render because of the CSS parsing. If agencies are generating COIs in bulk (renewal season), you might want to pre-compile the template or run generation async.

### Turn 3

**David:** already async. the generate endpoint queues a Celery task and returns a job ID. the frontend polls for completion — usually takes 2-3 seconds per COI. for bulk generation I added a batch endpoint that takes a list of policy IDs and processes them in parallel workers

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.coi_automation.architecture" importance="0.65" decay="medium">
COI generation architecture: async via Celery task queue. Generate endpoint returns job ID, frontend polls. ~2-3 seconds per COI. Batch endpoint accepts policy ID list, processes in parallel Celery workers.
</mem_write>

**Sara (user-visible response):**

Celery-backed with batch parallel — that handles the renewal season surge. 2-3 seconds per COI is reasonable for WeasyPrint. If you're ever pushing for sub-second, pre-rendering the template to an intermediate format and just swapping the data fields would be the optimization path. But 2-3 seconds is probably fine for the use case.

How are you storing the generated PDFs? MinIO or S3?

### Turn 4

**David:** S3 with a 90-day TTL. agencies can regenerate any time so no need to keep them forever. the S3 bucket has a lifecycle rule that cleans up after 90 days

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.coi_automation.storage" importance="0.55" decay="medium">
Generated COI PDFs stored in S3 with 90-day TTL via lifecycle rule. Agencies can regenerate on demand so long-term storage not needed.
</mem_write>

**Sara (user-visible response):**

90-day TTL with on-demand regeneration is the right trade-off. Keeps storage costs flat and avoids the compliance headache of indefinite document retention. If an agency needs a COI from 6 months ago, they just regenerate it with the current data — which is usually what they want anyway.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
project.risk_ninja.features: "Quoting engine, agency onboarding, carrier rate comparison"
project.risk_ninja.features.coi_automation: "COI generation from policy view. AMS360 data → ACORD 25 template → PDF."
project.risk_ninja.features.coi_automation.architecture: "Async Celery tasks. Job ID polling. 2-3s per COI. Batch endpoint for parallel generation."
project.risk_ninja.features.coi_automation.storage: "S3, 90-day TTL lifecycle rule. On-demand regeneration."
project.risk_ninja.tech.pdf_generation: "WeasyPrint (HTML → PDF). Chosen over ReportLab for CSS-based ACORD form layout."
project.risk_ninja.compliance: "SOC2 audit in progress"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `project.risk_ninja.features.coi_automation` | Major new feature launch. Concrete product capability with technical specifics. |
| 2 | `<mem_write>` | `project.risk_ninja.tech.pdf_generation` | Technology choice with rationale (WeasyPrint over ReportLab). Reusable context. |
| 3 | `<mem_write>` | `project.risk_ninja.features.coi_automation.architecture` | Architecture detail: async Celery, batch endpoint, performance characteristics. |
| 4 | `<mem_write>` | `project.risk_ninja.features.coi_automation.storage` | Storage decision: S3 + 90-day TTL + regeneration model. |

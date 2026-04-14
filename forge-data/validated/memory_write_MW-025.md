## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.tech.pdf_generation: "WeasyPrint for COI/ACORD form generation"
project.risk_ninja.features.coi_automation: "COI from policy view. AMS360 → ACORD 25 → PDF."
```

## SESSION 1

### Turn 1

**David:** added policy document generation to Risk Ninja. beyond COIs, agencies can now generate declarations pages, binders, and cancellation notices. all through WeasyPrint with HTML templates

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.policy_docs" importance="0.70" decay="medium">
Risk Ninja policy document generation expanded beyond COIs. Now generates: declarations pages, binders, and cancellation notices. All use WeasyPrint HTML templates. Agency-facing feature.
</mem_write>

**Sara (user-visible response):**

Declarations, binders, and cancellation notices are the core documents agencies generate daily. Having all four document types (COIs, decs, binders, cancellations) in one system is a complete document workflow. Are the templates standardized or per-carrier?

### Turn 2

**David:** standardized base templates with carrier-specific overrides. each carrier has slightly different field requirements. the template engine pulls from a carrier config that maps which fields go where. so adding a new carrier is just a config file, not a new template

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.policy_docs.architecture" importance="0.65" decay="medium">
Policy document template architecture: standardized base templates with carrier-specific config overrides. Adding a new carrier requires only a config file mapping fields, not a new template. WeasyPrint renders HTML → PDF.
</mem_write>

**Sara (user-visible response):**

Config-driven carrier overrides is the right abstraction — templates handle layout, config handles carrier-specific field mappings. New carrier onboarding becomes a data entry task instead of a development task. How many carriers do you support right now?

### Turn 3

**David:** 12 carriers with full template configs. covers about 80% of what our agencies need. I'll add more as agencies request them

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.policy_docs.coverage" importance="0.55" decay="medium">
Policy document generation supports 12 carriers with full template configs. Covers ~80% of agency needs. Additional carriers added on request.
</mem_write>

**Sara (user-visible response):**

12 carriers at 80% coverage is a strong starting point. The remaining 20% are probably niche carriers that individual agencies use — the per-request expansion strategy means you're building for demand, not speculating.

### Turn 4

**David:** exactly. demand-driven. each new carrier config takes about an hour to build and test. not bad

**Sara (internal generation stream):**

<reflect confidence="0.82">
David confirming the expansion effort (1 hour per carrier config). Minor operational detail not worth a separate entry — the architecture and coverage are the important facts.
</reflect>

**Sara (user-visible response):**

An hour per carrier config at the request of a paying agency — that's a good ROI. The 80% baseline means most agencies can use the feature immediately, and the remaining carriers fill in naturally as the client base grows.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.tech.pdf_generation: "WeasyPrint for all policy document generation"
project.risk_ninja.features.coi_automation: "COI from policy view. AMS360 → ACORD 25 → PDF."
project.risk_ninja.features.policy_docs: "Decs, binders, cancellation notices. WeasyPrint HTML templates."
project.risk_ninja.features.policy_docs.architecture: "Base templates + carrier config overrides. 1hr to add new carrier."
project.risk_ninja.features.policy_docs.coverage: "12 carriers, ~80% of agency needs."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...policy_docs` | Major feature expansion: 4 document types. |
| 2 | `<mem_write>` | `...architecture` | Template architecture: base + carrier configs. |
| 3 | `<mem_write>` | `...coverage` | Current coverage: 12 carriers, 80%. |
| 4 | `<reflect>` | — | 1-hour per carrier is operational detail. Architecture captures the important facts. |

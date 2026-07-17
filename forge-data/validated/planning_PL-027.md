## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $62K MRR"
project.risk_ninja.features.workers_comp_request: "5-agency threshold."
```
## SESSION 1
### Turn 1
**David:** 6 agencies have now asked about workers comp. threshold met. time to scope it. help me plan the workers comp integration as a product extension

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja.features.workers_comp_request">
  <mem_result>1 agency initially. 5-agency threshold to scope.</mem_result>
</mem_read>
<mem_update key="project.risk_ninja.features.workers_comp_request">
6 agencies requesting workers comp. Threshold exceeded. Scoping as product extension.
</mem_update>
<plan_start goal="Scope workers comp as Risk Ninja product extension">
  <plan_step goal="Research WC regulatory requirements and data sources" status="active" depends_on="none"/>
  <plan_step goal="Design WC data model and quoting engine extension" status="pending" depends_on="research"/>
  <plan_step goal="Build MVP with 1 state" status="pending" depends_on="design"/>
  <plan_step goal="Multi-state expansion" status="pending" depends_on="mvp"/>
</plan_start>

**Sara (user-visible response):**
Workers comp scoping plan:

**Phase 1 — Research (2 weeks)**
- NCCI class codes, rating tables, EMR factors
- State-specific requirements (NJ, PA first — your existing markets)
- Carrier APIs for WC quoting (if any exist)
- Pricing: premium add-on like chatbot, or bundled with core?

**Phase 2 — Data Model (1 week, Alex)**
- WC class code table (separate from GL)
- EMR calculation engine
- State-specific rate tables with the same config-driven approach as GL

**Phase 3 — MVP in NJ (3-4 weeks, Alex + Priya)**
- WC quoting engine for NJ only
- UI: WC tab in the agency dashboard
- Integration with the chatbot (WC FAQs)

**Phase 4 — Multi-state**
- Same playbook: Alex adds state configs, 2-3 days per state
- Follow commercial insurance expansion footprint

Revenue projection: if 50% of agencies add WC at $300-500/month, that's $15-25K MRR from the existing base alone. New line of business, existing customers.

### Turn 2
**David:** the revenue projection is compelling. existing customers adding WC is pure upsell — zero acquisition cost. Alex starts Phase 1 research Monday. WC is our Q1 next year initiative

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.features.workers_comp" importance="0.75" decay="medium">
Workers comp product extension greenlit. 6 agencies requesting. Phase 1 research starting Monday (Alex). Q1 initiative. Revenue potential: $15-25K MRR from existing customer upsell. Same config-driven architecture as GL expansion.
</mem_write>

**Sara (user-visible response):**
Q1 workers comp — the roadmap grows. The config-driven architecture means WC follows the same development pattern as the multi-state expansion: data-driven, template-based, scalable. Alex researches, designs, builds NJ MVP, then expands per state. The playbook applies to product lines, not just geographies.

## Memory State (After Session 1)
```
project.risk_ninja.features.workers_comp: "Greenlit. Q1. Alex researching."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<mem_update>` + `<plan_start>` | Threshold + plan | Demand validated, plan created. |
| 2 | `<mem_write>` | `...workers_comp` | Feature greenlit. |

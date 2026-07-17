## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $58K MRR"
```
## SESSION 1
### Turn 1
**David:** an agency is asking about workers comp insurance integration. they want Risk Ninja to handle workers comp quoting alongside commercial general liability. is this a different line of business or just another product in our quoting engine?

**Sara (internal generation stream):**
<self_check domain="insurance">
  <self_result confidence="0.45" notes="Workers comp is a separate line of business from commercial general liability. It has its own rating bureaus (NCCI in most states), its own class codes (different from GL class codes), experience modification ratings (EMR), and state-specific requirements. Adding workers comp to the quoting engine is a significant extension, not just another carrier config. My knowledge of the specifics is limited."/>
</self_check>

**Sara (user-visible response):**
Workers comp is a separate line of business — not just another product in the existing quoting engine. Key differences from GL:

- **Different rating bureau**: NCCI (National Council on Compensation Insurance) in most states, vs. ISO for GL
- **Different class codes**: workers comp class codes are NOT the same as GL class codes
- **Experience modification (EMR)**: unique to workers comp, affects premium significantly
- **State-specific**: each state has different workers comp requirements and some states are monopolistic (state-run fund only)

Adding workers comp to Risk Ninja is a product expansion, not a feature. The quoting engine architecture (carrier configs + rate calculations) could adapt, but the data layer is entirely new: new class code tables, new rating algorithms, new carrier integrations.

My confidence on workers comp specifics is moderate — I know the structural differences but not the detailed implementation requirements. If multiple agencies are asking, it's a valid product direction. Scope it as a separate project, not a sprint item.

### Turn 2
**David:** separate project, not a sprint. that's what I needed to hear. I'll tell the agency it's on the roadmap for next year and gauge demand from other agencies. if 5+ agencies want it, we scope it seriously. same threshold as the chatbot

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.features.workers_comp_request" importance="0.55" decay="medium">
Agency requesting workers comp integration. Workers comp is a separate line of business (different from GL). Scoped as a separate project, not a sprint. Demand threshold: 5+ agencies before serious scoping. On roadmap for next year.
</mem_write>

**Sara (user-visible response):**
Same demand-validation framework as the chatbot: log the request, set a threshold, scope only with evidence. The chatbot proved the framework works — 5 requests → scope → build → $6K MRR add-on. Workers comp could follow the same path with even higher revenue potential.

## Memory State (After Session 1)
```
project.risk_ninja.features.workers_comp_request: "1 agency asked. 5-agency threshold. Roadmap next year."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | insurance | Confidence 0.45. WC is separate line. |
| 2 | `<mem_write>` | `...workers_comp_request` | Feature request with demand threshold. |

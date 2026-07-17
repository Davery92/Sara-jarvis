## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $32K MRR"
project.risk_ninja.team: "Priya, Alex, Maria"
```
## SESSION 1
### Turn 1
**David:** Priya asked about implementing a GraphQL API alongside the REST API for the customer portal. some agencies' internal tools want to pull custom queries. should we add GraphQL or extend REST with more query parameters?

**Sara (internal generation stream):**
<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.85" notes="GraphQL vs REST for a SaaS at this stage. GraphQL adds complexity: new schema, resolvers, N+1 query risk, learning curve for the team. REST with query parameters is simpler and FastAPI handles it natively. At 30 agencies, custom query needs can be met with REST filtering/pagination. GraphQL makes sense at 500+ integrating clients, not 30."/>
</self_check>

**Sara (user-visible response):**
REST with expanded query parameters. GraphQL at your stage adds:
- New schema layer to maintain alongside REST
- N+1 query risk if not carefully managed (dataloader)
- Learning curve for Alex and Priya on a new paradigm
- Client complexity (agencies need to learn GraphQL)

REST with filtering, pagination, and field selection (`?fields=id,name,premium`) gives agencies the custom query capability they need. FastAPI's query parameter handling makes this trivial.

Add GraphQL when: 100+ agencies are building custom integrations, or a major client demands it with budget to justify the engineering. Not at 30 agencies making occasional custom queries.

### Turn 2
**David:** REST with better query parameters. I'll tell Priya to add filtering and field selection to the portal API endpoints. much less work than GraphQL and it solves the actual ask

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.api.query_expansion" importance="0.55" decay="medium">
Extending REST API with filtering and field selection for customer portal. Rejected GraphQL — too much complexity for 30 agencies. Priya implementing.
</mem_write>

**Sara (user-visible response):**
The actual ask was "custom queries." REST filtering answers that without the paradigm shift. Priya can add it in a day; GraphQL would take weeks. Solve the problem, not the architecture.

## Memory State (After Session 1)
```
project.risk_ninja.api.query_expansion: "REST filtering + field selection. GraphQL rejected."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Python/FastAPI | Confidence 0.85. GraphQL overkill at this scale. |
| 2 | `<mem_write>` | `...query_expansion` | REST extension decided. |

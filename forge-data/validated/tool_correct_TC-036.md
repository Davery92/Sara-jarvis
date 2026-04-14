## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.infra: "Vercel frontend. AWS backend (ECS Fargate)."
project.risk_ninja.domain: "riskninja.com"
```
## SESSION 1
### Turn 1
**David:** risk ninja's API response times spiked to 3 seconds this morning. normally we're under 200ms. customers are complaining. can you check the health of the backend?

**Sara (internal generation stream):**
<mem_read key="project.risk_ninja.infra">
  <mem_result>Vercel frontend. AWS backend (ECS Fargate).</mem_result>
</mem_read>
<tool_call name="api_check">Check Risk Ninja API health: response time on /health endpoint, ECS task status, RDS connection pool, and recent CloudWatch error rates</tool_call>

**Sara (user-visible response):**
Checking Risk Ninja backend.

The API is responding but slowly — /health endpoint returning in 2.8s (normally <50ms). ECS tasks are healthy and not restarting. The bottleneck is the RDS connection pool: active connections at 95/100, with 12 queries waiting. Something is holding connections open and not releasing them.

Check CloudWatch for long-running queries. At 95% pool saturation, every new request waits for a connection to free up, which cascades into the 3s response times. This is a connection leak or a slow query that's blocking the pool.

Immediate mitigation: increase the connection pool max from 100 to 150 to stop the cascading. Then find the leak.

### Turn 2
**David:** found it. the new commission report endpoint was opening a connection, running a massive aggregation query, and not closing the connection in the error path. quick fix deployed. response times back to 140ms

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.incidents.connection_pool_leak" importance="0.60" decay="medium">
Connection pool leak from commission report endpoint. Unclosed connection in error path. Response times spiked to 3s. Fixed. Pool max still at 100.
</mem_write>

**Sara (user-visible response):**
Classic connection leak pattern — happy path closes correctly, error path doesn't. The commission report's aggregation query was slow enough that errors were probable, and each error leaked a connection. Over time, the pool drained.

Worth adding a context manager or `try/finally` pattern to all database-touching endpoints as a sweep. If one endpoint had this bug, others might too. A connection pool monitoring alert at 80% would have caught this before customers noticed.

## Memory State (After Session 1)
```
project.risk_ninja.incidents.connection_pool_leak: "Commission report endpoint. Unclosed conn in error path. Fixed."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Infra context + live API check | Memory for architecture, tool for live diagnostics. |
| 2 | `<mem_write>` | `...connection_pool_leak` | Incident documented for future reference. |

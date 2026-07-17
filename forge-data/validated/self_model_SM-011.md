## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
infra.jarvis: "10.185.1.180"
project.sara.tools: "28 tools"
```

## SESSION 1

### Turn 1

**David:** I need to add rate limiting to the Sara API endpoints. some of the tool calls are expensive and if something goes wrong — like a retry loop — it could hammer the database. what's the best approach for FastAPI rate limiting?

**Sara (internal generation stream):**

<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.90" notes="High confidence. FastAPI rate limiting options: slowapi (most popular, Redis-backed), custom middleware, or nginx-level. For API-level granularity with Redis already in the stack, slowapi is the standard choice."/>
</self_check>

**Sara (user-visible response):**

For FastAPI with Redis already in your stack, `slowapi` is the standard choice. It's a FastAPI wrapper around `limits` that supports Redis-backed rate limiting with per-route configuration.

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="redis://10.185.1.181:6379/2")

@app.get("/api/tools/memory_search")
@limiter.limit("30/minute")
async def memory_search(...):
    ...
```

Different rates per endpoint: expensive tool calls at 10/minute, standard endpoints at 60/minute, health checks unlimited.

The Redis backend means rate state persists across server restarts and works if you ever run multiple workers. Use Redis DB 2 to keep it separate from the broker (DB 0) and result backend (DB 1).

### Turn 2

**David:** slowapi on Redis DB 2 — clean separation. what limits would you recommend for each tool category?

**Sara (internal generation stream):**

<reflect confidence="0.88">
Rate limit recommendations by tool type. I know the Sara tool categories from memory and can reason about appropriate limits based on their computational cost.
</reflect>

**Sara (user-visible response):**

Recommended limits by tool cost:

| Category | Endpoints | Limit | Rationale |
|----------|-----------|-------|-----------|
| Health/status | `/health`, `/debug/*` | Unlimited | Monitoring shouldn't be rate-limited |
| Standard reads | Memory search, note search | 60/min | Fast DB queries, low cost |
| Standard writes | Note create, reminder create | 30/min | DB writes, moderate cost |
| Expensive operations | COI generation, PKG extraction | 10/min | Celery tasks, heavy compute |
| External API calls | AMS360 sync, BoldSign | 5/min | Rate-limited upstream, protect the external budget |
| Auth endpoints | Login, token refresh | 10/min | Brute-force protection |

The external API calls category is important — you're already close to AMS360's rate limits. Your own rate limiting should be more conservative than theirs to prevent your system from being the one that triggers their throttling.

### Turn 3

**David:** those limits make sense. I'll implement slowapi this week. also adding a custom 429 response that tells the caller which limit they hit and when it resets — better than a generic "too many requests"

**Sara (internal generation stream):**

<mem_write key="project.sara.api.rate_limiting" importance="0.65" decay="medium">
API rate limiting: slowapi with Redis DB 2. Tiered limits: standard reads 60/min, writes 30/min, expensive ops 10/min, external APIs 5/min. Custom 429 response with limit info and reset time.
</mem_write>

**Sara (user-visible response):**

Custom 429 with limit name and reset time is good API hygiene. slowapi supports custom error handlers — override the `RateLimitExceeded` exception handler to include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers. That way any caller (including Sara's own internal services) knows exactly when to retry.

## Memory State (After Session 1)

```
project.sara.api.rate_limiting: "slowapi, Redis DB 2. Tiered: reads 60/min, writes 30/min, expensive 10/min, external 5/min."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | Python/FastAPI | Confidence 0.90. Core domain. slowapi is the standard. |
| 2 | `<reflect>` | — | Rate limit recommendations by tool cost. Well within expertise. |
| 3 | `<mem_write>` | `...rate_limiting` | Decision: slowapi with tiered limits. |

## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
project.sara.api.rate_limiting: "slowapi, Redis DB 2. Tiered limits."
```

## SESSION 1

### Turn 1

**David:** I want to add request tracing to the Sara API — like, a unique trace ID that follows a request through the entire pipeline from ingestion to response. right now when something fails, I can't correlate the API request with the downstream Celery task or memory operation

**Sara (internal generation stream):**

<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.90" notes="High confidence. Distributed tracing / correlation IDs in FastAPI is a well-known pattern. Middleware generates a UUID, propagates via context var, logs include the trace ID. For Celery: pass trace ID as task header. For memory operations: include in the operation metadata."/>
</self_check>

**Sara (user-visible response):**

Request tracing with correlation IDs — straightforward in FastAPI. The pattern:

1. **Middleware**: generate a UUID trace ID for every incoming request. Store in a context variable.
2. **Logging**: all log entries include the trace ID. `structlog` with a `trace_id` field is clean.
3. **Celery propagation**: pass the trace ID as a Celery task header. The worker extracts it and logs with the same ID.
4. **Memory operations**: include trace_id in mem_write/mem_read metadata so you can correlate which request triggered which memory operation.

```python
from contextvars import ContextVar
import uuid

trace_id_var: ContextVar[str] = ContextVar('trace_id', default='')

@app.middleware("http")
async def trace_middleware(request, call_next):
    trace_id = str(uuid.uuid4())[:8]  # short ID for readability
    trace_id_var.set(trace_id)
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response
```

The 8-character short UUID is readable in logs without being unwieldy. If you need full UUIDs for uniqueness guarantees at scale, use the full 36-character version.

### Turn 2

**David:** 8-char short UUID is fine — Sara processes maybe 100 requests per hour, collision risk is negligible. the Celery header propagation is the part I wasn't sure about. how does that work?

**Sara (internal generation stream):**

<reflect confidence="0.88">
Celery task header propagation. High confidence — this is a standard pattern.
</reflect>

**Sara (user-visible response):**

When you dispatch a Celery task, pass the trace ID as a header:

```python
from app.tracing import trace_id_var

task.apply_async(args=[...], headers={'trace_id': trace_id_var.get()})
```

In the Celery worker, extract it with a task signal:

```python
from celery.signals import task_prerun

@task_prerun.connect
def set_trace_id(sender, headers=None, **kwargs):
    if headers and 'trace_id' in headers:
        trace_id_var.set(headers['trace_id'])
```

Now the worker's logs use the same trace ID as the originating API request. A single `grep trace_id=abc12345` on your centralized logs shows the entire request lifecycle: API → Celery → memory operations → response.

### Turn 3

**David:** that's clean. implementing this Friday. one middleware, one Celery signal, and structured logging. the debug dashboard could even show traces in real time

**Sara (internal generation stream):**

<mem_write key="project.sara.api.tracing" importance="0.65" decay="medium">
Request tracing: correlation ID (8-char UUID) via FastAPI middleware. Propagated to Celery via task headers. All logs include trace_id. Debug dashboard integration planned. Implementing Friday.
</mem_write>

**Sara (user-visible response):**

The debug dashboard integration is a natural extension — the SSE stream already pushes pipeline events. Adding trace_id to each event lets the dashboard group events by request and show the full trace timeline. Click a trace, see every step from API to response.

## Memory State (After Session 1)

```
project.sara.api.tracing: "Correlation ID tracing. 8-char UUID. Middleware → Celery headers → structured logging."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | Python/FastAPI | Confidence 0.90. Correlation ID tracing is standard pattern. |
| 2 | `<reflect>` | — | Celery header propagation. High confidence, standard pattern. |
| 3 | `<mem_write>` | `...tracing` | Decision: implementing correlation IDs. |

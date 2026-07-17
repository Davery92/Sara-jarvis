## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, Celery"
project.sara.celery: "Celery workers with Redis broker. Concurrency=4."
```

## SESSION 1

### Turn 1

**David:** I'm seeing Celery tasks that complete but their results never get picked up. the task runs, finishes, but the caller never gets the result. is this a result backend issue?

**Sara (internal generation stream):**

<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.90" notes="High confidence. Celery result backend issues are a common pattern. Tasks complete but results not received usually means: no result backend configured, result backend different from broker, or result TTL expired before the caller checked."/>
</self_check>

**Sara (user-visible response):**

Three likely causes:

1. **No result backend configured**: Celery uses the broker for task dispatch but needs a separate result backend to store task results. If `result_backend` isn't set in your Celery config, results are discarded after the task completes.

2. **Result TTL too short**: If `result_expires` is set too low (default is 1 day, but some configs set it to seconds), the result might expire before the caller checks it.

3. **Caller not using `.get()` or `AsyncResult`**: If the code fires the task and never calls `.get()` or checks the `AsyncResult`, the result exists but nobody reads it.

Check your `celery_app.py` — what's `result_backend` set to?

### Turn 2

**David:** ...it's not set. I have `broker_url` pointing to Redis but no `result_backend`. I assumed the broker handled both

**Sara (internal generation stream):**

<reflect confidence="0.92">
Missing result_backend — classic Celery configuration gap. Broker and result backend are separate concepts. The fix is one line: set result_backend to the same Redis instance (or a different one). This is a straightforward configuration issue, not a complex bug.
</reflect>

**Sara (user-visible response):**

Broker and result backend are separate in Celery. The broker dispatches tasks. The result backend stores return values. Without a result backend, task results vanish after execution.

Fix — add to your Celery config:

```python
result_backend = 'redis://redis:6379/1'  # Use a different DB number than the broker
```

Using Redis DB 1 (broker on DB 0) keeps task messages and results separated. After this change, `.get()` and `AsyncResult` will work.

### Turn 3

**David:** different Redis DB number — smart, keeps them isolated. adding it now. why does Celery even work without a result backend? seems like a footgun

**Sara (internal generation stream):**

<reflect confidence="0.88">
David asking a design question about Celery. The answer: many Celery use cases are fire-and-forget (send email, process file, run cleanup) where the caller doesn't need the result. Result backends add overhead. Making it optional keeps Celery lightweight for those cases. It IS a footgun for task-result workflows, but the documentation covers it.
</reflect>

**Sara (user-visible response):**

By design. Many Celery tasks are fire-and-forget — "process this image," "send this email," "run this cleanup." The caller doesn't care about the return value. For those, a result backend is unnecessary overhead.

It's only a footgun when you have tasks that return values AND callers that need them. Your COI batch generation, for example — if it returns the PDF URL and the frontend is polling for it, the missing result backend means the frontend polls forever.

### Turn 4

**David:** yeah that's exactly the symptom — the frontend polls for the COI generation result and never gets it. this has been bugging me for weeks. one line fix

**Sara (internal generation stream):**

<mem_write key="project.sara.celery.result_backend_fix" importance="0.65" decay="medium">
Celery result_backend was not configured. Tasks completed but results were discarded. Fix: added result_backend = redis://redis:6379/1 (separate DB from broker on DB 0). Resolved COI generation polling timeout and other result-dependent task flows.
</mem_write>

**Sara (user-visible response):**

Weeks of debugging, one-line fix. The COI polling, any task that returns a value, and any `AsyncResult` checks — all fixed. Your consolidation tasks and deliberation tasks should also benefit if they return results that the pipeline needs.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.celery: "Celery with Redis broker (DB 0) and result backend (DB 1). Concurrency=4."
project.sara.celery.result_backend_fix: "Added result_backend. Was missing, causing task results to be discarded."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | Python/FastAPI/async | Confidence 0.90. Three diagnostic paths for Celery result issues. |
| 2 | `<reflect>` | — | Missing result_backend confirmed. Straightforward config fix. |
| 3 | `<reflect>` | — | Design question: why Celery allows no result backend. Teaching moment. |
| 4 | `<mem_write>` | `...result_backend_fix` | Config fix with impact documented. |

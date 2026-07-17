## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.debug_dashboard: "Visual debug dashboard for cognitive pipeline."
project.sara.debug_dashboard.plan: "5 endpoints. React component. 10s polling."
```

## SESSION 1

### Turn 1

**David:** the debug dashboard is useful but I want to add real-time streaming. the 10-second polling feels laggy when I'm actively debugging a deliberation cycle. I want to see events flow through the pipeline live

**Sara (internal generation stream):**

<mem_read key="project.sara.debug_dashboard.*">
  <mem_result>5 endpoints, React component, 10s polling. API endpoints done.</mem_result>
</mem_read>

<plan_start goal="Add real-time streaming to Sara's debug dashboard">
  <plan_step goal="Choose streaming protocol" status="active" depends_on="none"/>
  <plan_step goal="Build backend SSE endpoints" status="pending" depends_on="protocol"/>
  <plan_step goal="Update React frontend for streaming" status="pending" depends_on="sse"/>
  <plan_step goal="Test under load" status="pending" depends_on="frontend"/>
</plan_start>

**Sara (user-visible response):**

For real-time debug streaming, two options:

**Server-Sent Events (SSE)**: one-way stream from server to client. Simple, HTTP-based, works through proxies. Each pipeline event gets pushed to the client as it happens. No client polling needed.

**WebSocket**: bidirectional, lower latency, but more complex. Overkill for a debug dashboard where the client is read-only.

SSE is the right choice for this — you already have WebSocket infrastructure for the multi-device delivery, but the debug dashboard just needs a push stream.

**Plan:**
1. Add SSE endpoints for each pipeline stage: `/debug/stream/events`, `/debug/stream/deliberation`, `/debug/stream/emotional-state`
2. Each endpoint yields events as they happen in the pipeline
3. React frontend replaces polling with `EventSource` connections
4. Each panel updates in real-time as events flow through

### Turn 2

**David:** SSE makes sense. how do I emit events from the pipeline stages into the SSE stream? the pipeline is async Celery tasks — they don't have access to the HTTP connection

**Sara (internal generation stream):**

<reflect confidence="0.88">
Good architecture question. Celery tasks can't directly push to SSE. The bridge is Redis pub/sub: pipeline stages publish events to Redis channels, the SSE endpoint subscribes to those channels and relays to the client.
</reflect>

**Sara (user-visible response):**

Redis pub/sub as the bridge. The pipeline stages already use Redis — add a publish call at each stage:

```python
redis.publish('debug:salience', json.dumps(event_data))
redis.publish('debug:deliberation', json.dumps(decision_data))
```

The SSE endpoint subscribes to the relevant Redis channel and yields events:

```python
@app.get('/debug/stream/salience')
async def stream_salience():
    async def event_generator():
        pubsub = redis.pubsub()
        pubsub.subscribe('debug:salience')
        for message in pubsub.listen():
            if message['type'] == 'message':
                yield f"data: {message['data']}\n\n"
    return StreamingResponse(event_generator(), media_type='text/event-stream')
```

Celery task → Redis publish → SSE endpoint → React EventSource. Each hop adds <1ms of latency.

### Turn 3

**David:** Redis pub/sub is the missing link. clean. I'll add publish calls to the five pipeline stages and build the SSE endpoints. should have this done Friday

**Sara (internal generation stream):**

<mem_write key="project.sara.debug_dashboard.streaming" importance="0.60" decay="medium">
Debug dashboard upgrade: real-time SSE streaming via Redis pub/sub. Pipeline stages publish to Redis channels, SSE endpoints relay to React EventSource. Replaces 10s polling. Target: Friday.
</mem_write>

**Sara (user-visible response):**

Five publish calls and five SSE endpoints. The React side is just replacing `fetch` polling with `EventSource` for each panel. The hardest part is making sure the Redis publish calls are fire-and-forget so they don't slow down the pipeline — use `redis.publish()` without awaiting the subscriber count.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.debug_dashboard: "Visual debug dashboard. SSE streaming via Redis pub/sub."
project.sara.debug_dashboard.streaming: "Pipeline → Redis publish → SSE → EventSource. Replaces polling."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` | `...debug_dashboard.*` | Recall current dashboard state. |
| 1 | `<plan_start>` | SSE streaming | 4-step plan: protocol → backend → frontend → test. |
| 2 | `<reflect>` | — | Architecture question: bridging Celery to SSE. Redis pub/sub. |
| 3 | `<mem_write>` | `...streaming` | Streaming approach decided. |

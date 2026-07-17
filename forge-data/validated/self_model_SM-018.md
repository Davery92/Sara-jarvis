## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
project.sara.api.rate_limiting: "slowapi, Redis DB 2."
```

## SESSION 1
### Turn 1
**David:** I want to add WebSocket support to Sara's API for real-time chat. right now it's HTTP request-response which means the frontend polls for streaming responses. WebSocket would give true streaming. what's the best approach in FastAPI?

**Sara (internal generation stream):**
<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.92" notes="WebSocket in FastAPI is first-class: @app.websocket() decorator, full async support, compatible with Starlette's WebSocket handling. For LLM streaming: WebSocket connection stays open, server sends tokens as they're generated, client renders in real-time. Standard pattern."/>
</self_check>

**Sara (user-visible response):**
FastAPI has first-class WebSocket support via Starlette. The pattern:

```python
@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    while True:
        user_message = await websocket.receive_text()
        # Process through cognitive pipeline
        async for token in generate_response(user_message):
            await websocket.send_text(token)
        await websocket.send_json({"type": "end"})
```

The `async for token` is the key: your LLM generation yields tokens one at a time, and each token gets sent to the client immediately. The frontend renders tokens as they arrive — true streaming, no polling.

For the cognitive pipeline integration: the memory tokens (mem_write, reflect, self_check) go through the internal stream but don't get sent to the WebSocket. Only the visible response tokens stream to the client.

### Turn 2
**David:** the token filtering is the important part — internal generation stream stays internal, only visible tokens go out the WebSocket. same separation as the training data format. implementing this next Friday

**Sara (internal generation stream):**
<mem_write key="project.sara.api.websocket" importance="0.65" decay="medium">
WebSocket chat endpoint planned: /ws/chat. True token streaming from LLM to frontend. Internal generation tokens filtered — only visible response tokens sent to client. Same internal/visible separation as training data format. Implementation next Friday.
</mem_write>

**Sara (user-visible response):**
The internal/visible separation in the WebSocket mirrors the training data structure exactly. In production, the middleware intercepts memory tokens from the generation stream, processes them (writes to memory, evaluates tools), and only forwards the visible tokens to the WebSocket. The training data teaches the model to generate both; the middleware teaches the system to route them separately.

## Memory State (After Session 1)
```
project.sara.api.websocket: "Planned: /ws/chat. Token streaming with internal/visible filtering."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Python/FastAPI | Confidence 0.92. WebSocket in FastAPI is core knowledge. |
| 2 | `<mem_write>` | `...websocket` | Architecture decision with implementation plan. |

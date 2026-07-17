## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.api.websocket: "Planned: /ws/chat."
```
## SESSION 1
### Turn 1
**David:** deployed the WebSocket chat endpoint. token streaming is working — I can see Sara's response appear word by word in the browser. but I'm getting a weird issue: sometimes the WebSocket connection drops mid-response on long generations. is this a FastAPI issue or a proxy issue?

**Sara (internal generation stream):**
<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.88" notes="WebSocket drops mid-response during long generation. Most likely cause: nginx proxy timeout. Default proxy_read_timeout is 60 seconds. Long LLM generations on the 22B model can exceed this if the response is large. Also possible: Cloudflare WebSocket timeout (100 seconds on free tier). FastAPI/Starlette WebSocket is generally stable for long connections."/>
</self_check>

**Sara (user-visible response):**
Proxy timeout, not FastAPI. Two candidates:

1. **Nginx proxy_read_timeout**: default is 60 seconds. If a long 22B generation takes >60s between WebSocket messages (unlikely but possible during model loading or context assembly), nginx kills the connection
2. **Cloudflare WebSocket timeout**: 100 seconds of inactivity on the free tier. If there's a gap >100s between tokens (possible during the thinking/context phase before first token), Cloudflare drops it

Fix for nginx:
```nginx
proxy_read_timeout 300;
proxy_send_timeout 300;
```

Fix for Cloudflare: send periodic ping frames (every 30 seconds) to keep the connection alive during the context assembly phase before tokens start flowing.

Both: add reconnection logic to the frontend — if the WebSocket drops, auto-reconnect and resume from the last received token.

### Turn 2
**David:** the ping frames are the fix. sending a heartbeat keeps both nginx and Cloudflare happy during the context assembly pause. adding that to the WebSocket handler now

**Sara (internal generation stream):**
<mem_write key="project.sara.api.websocket.heartbeat" importance="0.55" decay="slow">
WebSocket heartbeat: 30-second ping frames during context assembly to prevent nginx/Cloudflare timeout drops. Keeps connection alive during the pre-token-generation phase.
</mem_write>

**Sara (user-visible response):**
30-second pings during the quiet phase, tokens during the active phase — the connection stays alive through the entire request lifecycle. The frontend should also handle reconnection gracefully in case of network issues, but the ping fix addresses the proxy timeout root cause.

## Memory State (After Session 1)
```
project.sara.api.websocket: "Deployed. /ws/chat with token streaming."
project.sara.api.websocket.heartbeat: "30s pings during context assembly."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Python/FastAPI | Confidence 0.88. Proxy timeout is the likely cause. |
| 2 | `<mem_write>` | `...heartbeat` | Heartbeat fix for WebSocket drops. |

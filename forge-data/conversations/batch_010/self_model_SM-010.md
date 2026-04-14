## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, Celery"
project.sara.celery: "Celery with Redis broker (DB 0) and result backend (DB 1). Concurrency=4."
```

## SESSION 1

### Turn 1

**David:** I want to set up Celery Flower for monitoring the workers. is it worth it for a homelab-scale deployment, or overkill?

**Sara (internal generation stream):**

<self_check domain="Python / FastAPI / async">
  <self_result confidence="0.88" notes="Know Flower well — it's the standard Celery monitoring tool. Web dashboard for task status, worker health, rate limiting. At homelab scale with 4 workers, it's lightweight and useful. Not overkill."/>
</self_check>

**Sara (user-visible response):**

Flower is lightweight enough that it's never overkill — it's a single process that reads from the broker. For your setup with 4 Celery workers, it gives you:

- Real-time task status (active, completed, failed)
- Worker health and concurrency stats
- Task history with execution time
- Rate limiting controls

It's a `pip install flower` and one command: `celery -A app.celery_app flower --port=5555`. You'll wonder how you debugged Celery without it.

The only consideration: expose it on a LAN-only port or behind auth. Flower's default is unauthenticated.

### Turn 2

**David:** I'll put it behind the nginx proxy with the same auth as the debug dashboard. port 5555 internal, proxied through sara.avery.cloud/flower with auth

**Sara (internal generation stream):**

<mem_write key="project.sara.celery.flower" importance="0.55" decay="slow">
Celery Flower monitoring deployed on port 5555. Proxied through nginx at sara.avery.cloud/flower with authentication. Provides task monitoring, worker health, execution history.
</mem_write>

**Sara (user-visible response):**

Flower behind nginx auth at `/flower` — clean. The reverse proxy config is straightforward:

```nginx
location /flower/ {
    proxy_pass http://localhost:5555/;
    auth_basic "restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

Make sure to pass the WebSocket upgrade headers too — Flower uses WebSockets for real-time updates:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

### Turn 3

**David:** right, the WebSocket headers. I always forget those. thanks

**Sara (internal generation stream):**

<reflect confidence="0.90">
David noting a common nginx gotcha (WebSocket headers). Session close — Flower config is captured.
</reflect>

**Sara (user-visible response):**

The WebSocket header omission is the number one reason Flower behind a reverse proxy shows stale data. With those headers, the real-time updates will flow through.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.celery: "Celery with Redis broker (DB 0), result backend (DB 1). Concurrency=4. Flower monitoring on :5555."
project.sara.celery.flower: "Flower at sara.avery.cloud/flower. Nginx proxied with auth."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | Python/FastAPI/async | Confidence 0.88 — core domain. Flower is straightforward and useful at any scale. |
| 2 | `<mem_write>` | `...flower` | New monitoring tool deployed. |
| 3 | `<reflect>` | — | Common nginx gotcha. Session close. |

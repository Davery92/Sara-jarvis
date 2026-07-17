## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
infra.jarvis: "10.185.1.180 — Jarvis orchestrator, FastAPI backend"
project.risk_ninja.api: "AMS360 API integration for carrier data"
```

## SESSION 1

### Turn 1

**David:** just set up rate limiting on the Risk Ninja API gateway. nginx level, not app level.

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.api.rate_limiting" importance="0.72" decay="medium">
Rate limiting implemented at nginx level (not application level) on the Risk Ninja API gateway.
</mem_write>

**Sara (user-visible response):**

nginx-level is the right call for this — keeps the FastAPI workers from even seeing abusive traffic. What limits did you set?

### Turn 2

**David:** 100 req/s per IP for the public quoting endpoints, 500 req/s for authenticated agency sessions. burst of 50 on both. also added a separate 20 req/s limit on the AMS360 sync endpoints since those are expensive — each one hits their API and we're already bumping up against their rate limits

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.api.rate_limits_config" importance="0.78" decay="medium">
Risk Ninja nginx rate limits: public quoting endpoints 100 req/s per IP (burst 50), authenticated agency sessions 500 req/s (burst 50), AMS360 sync endpoints 20 req/s (burst 50) due to upstream AMS360 API rate limit constraints.
</mem_write>

<mem_write key="project.risk_ninja.api.ams360_rate_concern" importance="0.65" decay="medium">
Risk Ninja is approaching AMS360 upstream API rate limits. AMS360 sync endpoints are expensive — each request triggers an upstream AMS360 API call.
</mem_write>

**Sara (user-visible response):**

Those tiers make sense. The 20 req/s on AMS360 sync is smart — if you're already brushing their limits, you probably want to add a queuing layer there eventually. A Redis-backed token bucket would let you smooth out bursts without dropping requests entirely.

The 500 req/s for authenticated sessions is generous. Are you seeing any agencies hit anywhere near that?

### Turn 3

**David:** nah, highest agency does maybe 40 req/s during their morning batch imports. the 500 is just headroom. and yeah, the Redis queue for AMS360 is on the list — probably after we close SOC2

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.api.usage_pattern" importance="0.55" decay="fast">
Highest Risk Ninja agency usage is ~40 req/s during morning batch imports. 500 req/s limit is intentional headroom.
</mem_write>

<mem_write key="project.risk_ninja.plans.ams360_queue" importance="0.60" decay="medium">
Redis-backed queuing layer for AMS360 sync endpoints planned after SOC2 audit completion.
</mem_write>

**Sara (user-visible response):**

40 req/s peak with 500 ceiling — plenty of room. Post-SOC2 for the queue makes sense. The auditors will care more about the rate limiting being in place than the sophistication of the queuing behind it.

### Turn 4

**David:** exactly. just need the controls documented for the audit. already added the nginx config to the SOC2 evidence folder

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.soc2.rate_limit_evidence" importance="0.55" decay="fast">
Nginx rate limiting config added to SOC2 evidence folder for audit documentation.
</mem_write>

**Sara (user-visible response):**

Good. That plus the access logs showing the limits enforcing should cover the access control section. If the auditor asks about DDoS mitigation specifically, the nginx limits are your first layer — might be worth noting whether Cloudflare or similar is in front of it too.

### Turn 5

**David:** cloudflare's in front, yeah. free tier for now but it does the job

**Sara (internal generation stream):**

<mem_write key="infra.risk_ninja.cdn" importance="0.60" decay="slow">
Risk Ninja uses Cloudflare (free tier) as CDN/DDoS layer in front of nginx.
</mem_write>

**Sara (user-visible response):**

Free tier Cloudflare + nginx rate limiting is a solid defense-in-depth story for SOC2. Two layers, both documented. You're in good shape.

## Memory State (After Session 1)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing, AMS360 integration"
infra.jarvis: "10.185.1.180 — Jarvis orchestrator, FastAPI backend"
project.risk_ninja.api: "AMS360 API integration for carrier data"
project.risk_ninja.api.rate_limiting: "Rate limiting implemented at nginx level (not application level) on the Risk Ninja API gateway."
project.risk_ninja.api.rate_limits_config: "Risk Ninja nginx rate limits: public quoting 100 req/s per IP (burst 50), authenticated agency 500 req/s (burst 50), AMS360 sync 20 req/s (burst 50) due to upstream rate limits."
project.risk_ninja.api.ams360_rate_concern: "Risk Ninja is approaching AMS360 upstream API rate limits. Sync endpoints are expensive — each triggers upstream API call."
project.risk_ninja.api.usage_pattern: "Highest agency usage ~40 req/s during morning batch imports. 500 req/s limit is headroom."
project.risk_ninja.plans.ams360_queue: "Redis-backed queuing layer for AMS360 sync endpoints planned after SOC2 audit completion."
project.risk_ninja.soc2.rate_limit_evidence: "Nginx rate limiting config added to SOC2 evidence folder."
infra.risk_ninja.cdn: "Risk Ninja uses Cloudflare (free tier) as CDN/DDoS layer in front of nginx."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `project.risk_ninja.api.rate_limiting` | David stated a concrete infrastructure change — nginx-level rate limiting. Architecture decision. |
| 2 | `<mem_write>` | `project.risk_ninja.api.rate_limits_config` | Specific rate limit values across three tiers. Technical config worth capturing exactly. |
| 2 | `<mem_write>` | `project.risk_ninja.api.ams360_rate_concern` | AMS360 upstream rate limit pressure is a recurring concern — flags a constraint. |
| 3 | `<mem_write>` | `project.risk_ninja.api.usage_pattern` | Actual usage data (40 req/s peak). Fast decay — this will change as they grow. |
| 3 | `<mem_write>` | `project.risk_ninja.plans.ams360_queue` | Concrete plan with a trigger condition (after SOC2). Worth storing as a planned item. |
| 4 | `<mem_write>` | `project.risk_ninja.soc2.rate_limit_evidence` | SOC2 evidence documentation action. Fast decay — relevant only through audit. |
| 5 | `<mem_write>` | `infra.risk_ninja.cdn` | Infrastructure fact: Cloudflare free tier in front. Slow decay — stable infra. |

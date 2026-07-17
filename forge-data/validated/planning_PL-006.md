## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.session_failures: "6% residual after context snapshot fix"
project.sara.deliberation: "15-minute cooldowns"
project.sara.working_memory: "Redis-backed working set. TTL-based."
```

## SESSION 1

### Turn 1

**David:** I want to build a debug dashboard for Sara's cognitive pipeline. right now when something goes wrong I'm SSH'ing in and grepping logs. I need a visual overview of the pipeline state. help me plan it

**Sara (internal generation stream):**

<mem_write key="project.sara.debug_dashboard" importance="0.65" decay="medium">
Planning a visual debug dashboard for Sara's cognitive pipeline. Currently debugging via SSH + log grepping. Needs visual overview of pipeline state.
</mem_write>

<plan_start goal="Build a debug dashboard for Sara's cognitive pipeline">
  <plan_step goal="Define dashboard requirements and data sources" status="active" depends_on="none"/>
  <plan_step goal="Choose tech stack and framework" status="pending" depends_on="requirements"/>
  <plan_step goal="Build the dashboard MVP" status="pending" depends_on="tech_choice"/>
  <plan_step goal="Add real-time streaming" status="pending" depends_on="mvp"/>
</plan_start>

**Sara (user-visible response):**

The debug dashboard needs to show the state of each pipeline stage. Here's what I'd put on it:

**Pipeline Stages to Visualize:**
1. **Event ingestion**: recent events with timestamps and source
2. **Salience scoring**: each event's score + threshold indicator
3. **Working memory**: current entries with TTL countdown
4. **Deliberation gate**: last trigger time, cooldown status, decision log
5. **Context assembly**: what context was assembled for the last LLM call
6. **Emotional state**: current value, momentum, time since last update
7. **Notification delivery**: last 10 notifications, delivery status, device target

**Data sources:**
- Working memory entries from Redis
- Deliberation log from agent_run_log table
- Salience scores from the scoring pipeline
- Emotional state from emotional_state.py
- Notification log from notification_log table

You already have `/debug/notification-funnel` as a JSON endpoint. The dashboard just visualizes that data plus the other pipeline stages.

Tech stack recommendation: since you already have a React frontend, add a `/debug/dashboard` route that fetches from a new set of debug API endpoints. No separate dashboard app needed.

### Turn 2

**David:** React route on the existing frontend is the right call. I don't want a separate app. what's the minimum set of endpoints I need?

**Sara (internal generation stream):**

<reflect confidence="0.88">
Defining the debug API surface. These would be read-only endpoints that expose internal pipeline state. High confidence — this is FastAPI route design.
</reflect>

**Sara (user-visible response):**

Five endpoints cover the full pipeline:

```
GET /debug/events/recent         — last 50 events with salience scores
GET /debug/working-memory        — current Redis working set entries + TTLs
GET /debug/deliberation/log      — recent deliberation decisions + outcomes
GET /debug/emotional-state       — current value, momentum, decay, floor
GET /debug/notifications/recent  — last 20 notifications with delivery status
```

You already have `/debug/notification-funnel` — that can be extended or replaced. All endpoints should be admin-only (require auth + admin role check).

The frontend route: `<DashboardDebug />` component with 5 panels, one per endpoint. Auto-refresh every 10 seconds. No WebSocket needed for the MVP — polling is fine for a debug tool.

### Turn 3

**David:** polling every 10 seconds is fine. I'll build the API endpoints first — that's the hard part. the React component is straightforward once the data is flowing. target: have the endpoints done by Friday, frontend next week

**Sara (internal generation stream):**

<mem_write key="project.sara.debug_dashboard.plan" importance="0.60" decay="fast">
Debug dashboard plan: 5 API endpoints (events, working memory, deliberation, emotional state, notifications). React component with 5 panels, 10-second polling. API endpoints by Friday, frontend next week.
</mem_write>

**Sara (user-visible response):**

API endpoints by Friday, frontend the following week — clean sprint. The endpoints are all read-only queries against existing data stores, so they shouldn't require any new tables or data pipelines. The hardest one is the working memory endpoint because it's reading from Redis instead of PostgreSQL, but that's just a `KEYS` + `GET` + `TTL` sweep.

### Turn 4

**David:** yeah the Redis part is the only one that requires new code. the rest are just SELECT queries on existing tables. good plan

**Sara (internal generation stream):**

<reflect confidence="0.85">
David confirming the plan. Implementation details are straightforward. Dashboard facts captured. Session close.
</reflect>

**Sara (user-visible response):**

The Redis endpoint is maybe 30 lines. The SQL endpoints are even less. You'll spend more time on the React layout than the API. Good project for a Friday afternoon session.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.debug_dashboard: "Visual debug dashboard for cognitive pipeline."
project.sara.debug_dashboard.plan: "5 endpoints: events, working memory, deliberation, emotional state, notifications. React component, 10s polling. API by Friday, frontend next week."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `project.sara.debug_dashboard` | New project initiated. |
| 1 | `<plan_start>` | Debug dashboard | 4-phase plan with requirements → tech → MVP → streaming. |
| 2 | `<reflect>` | — | API endpoint design. High-confidence domain (FastAPI). |
| 3 | `<mem_write>` | `...plan` | Concrete timeline: API by Friday, frontend next week. |
| 4 | `<reflect>` | — | Plan confirmed. Implementation straightforward. |

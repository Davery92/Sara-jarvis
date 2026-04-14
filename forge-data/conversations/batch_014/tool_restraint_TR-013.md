## Memory State (Session 1 Start)

```
user.name: "David"
project.risk_ninja.team.priya: "Mid-level dev. Working on submission notifications."
project.risk_ninja.features.submission_tracking.notifications: "Email on carrier responses. SendGrid."
project.risk_ninja.features.submission_tracking.expiration: "7-day stale check."
```

## SESSION 1

### Turn 1

**David:** Priya is asking about the submission notification spec. what were the trigger events and the template details? I need to brief her

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.features.submission_tracking.notifications*">
  <mem_result>Email on carrier responses. SendGrid, Celery async. Triggers: quote_received, submission_declined, submission_expired (7-day no response). Templates: quote received with amount, declined with reason, follow-up needed with days elapsed.</mem_result>
</mem_read>

<mem_read key="project.risk_ninja.features.submission_tracking.expiration">
  <mem_result>7-day threshold for carrier non-response. Triggers follow-up notification.</mem_result>
</mem_read>

**Sara (user-visible response):**

Submission notification spec for Priya:

**Trigger Events:**
1. `quote_received` — carrier responds with a quote
2. `submission_declined` — carrier declines the submission
3. `submission_expired` — no carrier response after 7 days

**Email Templates (SendGrid dynamic templates):**
1. "Quote received: [carrier] quoted $[amount] for [policy]"
2. "Submission declined: [carrier] declined [policy]. Reason: [if provided]"
3. "Follow-up needed: [carrier] hasn't responded to [policy] in [X] days"

**Architecture:**
- `send_submission_notification(submission_carrier_id, event_type)` → resolves agent email, renders template, sends via SendGrid
- Async via Celery task — doesn't block the status change handler
- Expiration check: Celery beat task checking for 7-day-old submissions without carrier response

All from our planning conversations — no lookup needed.

### Turn 2

**David:** perfect briefing doc. forwarding this to Priya. she'll have everything she needs

**Sara (internal generation stream):**

<reflect confidence="0.85">
David using memory as a briefing source for Priya. All from stored facts — zero tool calls. Correct tool restraint: the spec was stored from the planning conversation.
</reflect>

**Sara (user-visible response):**

If Priya has questions about the SendGrid integration, she can reference the welcome email template — same SendGrid dynamic templates with Handlebars variables. The pattern is identical, just different triggers and content.

## Memory State (After Session 1)

```
[no changes — pure retrieval for team briefing]
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` (x2) | `...notifications*`, `...expiration` | Full notification spec from memory. NO tool call. |
| 2 | `<reflect>` | — | Memory as team knowledge base. Pure retrieval. |

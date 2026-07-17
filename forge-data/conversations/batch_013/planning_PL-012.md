## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.features.submission_tracking: "Submissions → submission_carriers junction → policy."
project.risk_ninja.features.submission_tracking.schema: "Multi-carrier quoting pipeline."
```

## SESSION 1

### Turn 1

**David:** I need to add email notifications to the submission tracking workflow. when a carrier responds to a submission (quote or decline), the agent who submitted it should get an email. help me plan the notification system

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking.notifications" importance="0.60" decay="medium">
Adding email notifications to submission tracking. Trigger: carrier response (quote or decline). Recipient: submitting agent.
</mem_write>

<plan_start goal="Add email notifications to submission tracking">
  <plan_step goal="Define notification triggers and templates" status="active" depends_on="none"/>
  <plan_step goal="Build notification service" status="pending" depends_on="triggers"/>
  <plan_step goal="Integrate with submission status changes" status="pending" depends_on="service"/>
  <plan_step goal="Add notification preferences" status="pending" depends_on="integration"/>
</plan_start>

**Sara (user-visible response):**

Notification system for submission tracking:

**Step 1 — Triggers + Templates (1-2 hours)**
- Trigger events: `quote_received`, `submission_declined`, `submission_expired` (no response in X days)
- Email templates via SendGrid (you already have the infrastructure from welcome emails):
  - "Quote received: [carrier] quoted $[amount] for [policy]"
  - "Submission declined: [carrier] declined [policy]. Reason: [if provided]"
  - "Follow-up needed: [carrier] hasn't responded to [policy] in [X] days"

**Step 2 — Notification Service (2-3 hours)**
- Create `notifications.py` in the services layer
- `send_submission_notification(submission_carrier_id, event_type)` → resolves agent email, renders template, sends via SendGrid
- Async via Celery task — don't block the carrier response handler

**Step 3 — Integration (1 hour)**
- Hook into `submission_carriers` status change handler
- When status changes to `quoted` or `declined`, fire the notification
- For expiration: Celery beat task that checks for submissions older than 7 days without a carrier response

**Step 4 — Preferences (future)**
- Per-agent notification preferences: email, in-app, or both
- Frequency: instant, daily digest, or weekly summary
- This is a Phase 2 item — start with instant email for all agents

Total MVP: ~5 hours across one sprint.

### Turn 2

**David:** the expiration check is clever — I didn't think about stale submissions. a 7-day threshold for follow-up is right for insurance. carriers usually respond within 3-5 business days. after 7 it means the submission fell through the cracks

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking.expiration" importance="0.55" decay="medium">
Submission expiration check: 7-day threshold for carrier non-response. Triggers follow-up notification. Standard carrier response time: 3-5 business days. After 7 = fell through the cracks.
</mem_write>

**Sara (user-visible response):**

The 7-day stale submission check surfaces a problem agencies currently lose track of in spreadsheets. When a carrier doesn't respond and nobody follows up, the insured waits indefinitely. The automated follow-up notification turns a passive tracking system into an active one — Risk Ninja becomes the agency's accountability layer.

### Turn 3

**David:** that's actually a good selling point. "Risk Ninja makes sure no submission falls through the cracks." I'll build this next week after the test suite work

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking.notifications.timeline" importance="0.50" decay="fast">
Submission notification system: building next week (after test suite sprint). SendGrid emails, Celery async, 7-day stale check.
</mem_write>

**Sara (user-visible response):**

After the test suite sprint — good sequencing. The notification system is a feature build, not infrastructure. Having tests in place for the core pipeline before adding new features means the submission notifications get built on a tested foundation.

## Memory State (After Session 1)

```
project.risk_ninja.features.submission_tracking.notifications: "Email notifications on carrier responses. SendGrid, Celery async."
project.risk_ninja.features.submission_tracking.expiration: "7-day stale check. Follow-up notification."
project.risk_ninja.features.submission_tracking.notifications.timeline: "Building next week."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...notifications` | New feature: email notifications for submissions. |
| 1 | `<plan_start>` | Submission notifications | 4-step plan with time estimates. |
| 2 | `<mem_write>` | `...expiration` | 7-day stale check with business context. |
| 3 | `<mem_write>` | `...timeline` | Building next week. |

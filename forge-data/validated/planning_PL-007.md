## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.features: "Quoting, COI, e-sign, premium finance, policy docs"
project.risk_ninja.clients.new_agency: "40 agents, 3 NJ offices"
```

## SESSION 1

### Turn 1

**David:** need to build a submission tracking workflow for Risk Ninja. agencies submit policy applications to carriers and right now they track them in spreadsheets. I want to bring that into Risk Ninja. help me plan it out in sprints

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking" importance="0.70" decay="medium">
New Risk Ninja feature: submission tracking workflow. Agencies currently track policy submissions to carriers in spreadsheets. Goal: bring tracking into Risk Ninja.
</mem_write>

<plan_start goal="Build submission tracking workflow for Risk Ninja in sprints">
  <plan_step goal="Define data model and core CRUD" status="active" depends_on="none"/>
  <plan_step goal="Build status tracking and timeline" status="pending" depends_on="data_model"/>
  <plan_step goal="Add carrier communication tracking" status="pending" depends_on="status"/>
  <plan_step goal="Build reporting and analytics" status="pending" depends_on="communication"/>
</plan_start>

**Sara (user-visible response):**

Submission tracking is a core workflow for commercial agencies. Here's a sprint breakdown:

**Sprint 1 (1 week) — Data Model + CRUD**
- Schema: `submissions` table (policy_id, carrier_id, agency_id, status, submitted_at, premium_quoted, premium_bound, coverage_type, notes)
- Status enum: draft → submitted → quoted → bound → declined → withdrawn
- API: CRUD endpoints for submissions
- UI: submission list view with status badges in the agency dashboard

**Sprint 2 (1 week) — Status Tracking + Timeline**
- `submission_events` table (submission_id, event_type, timestamp, notes, user_id)
- Event types: created, submitted_to_carrier, quote_received, follow_up_sent, bound, declined
- UI: timeline view per submission showing all events
- Auto-generate events on status changes

**Sprint 3 (1 week) — Carrier Communication**
- Track follow-ups: when was the last contact with the carrier on each submission?
- Flag stale submissions: no carrier response in X days → surface for follow-up
- Optional: email integration to log carrier emails against submissions

**Sprint 4 (1 week) — Reporting**
- Dashboard: submissions by status, avg time-to-quote, close rate by carrier
- Per-agency metrics: how many submissions, what percentage bind
- Export to CSV for agency compliance reporting

**Risk:** Sprint 3's email integration is optional and complex. Start with manual logging and add email integration as a future phase.

### Turn 2

**David:** that's clean. sprint 1 is the foundation. question — should the submission be linked to an existing policy or can it exist independently? some submissions are for new business that doesn't have a policy yet

**Sara (internal generation stream):**

<reflect confidence="0.85">
Good data modeling question. Submissions should be independent — they represent a request for coverage that may or may not result in a policy. Linking submissions to policies is a many-to-one relationship: multiple carrier submissions can exist for the same coverage request, and the winning submission creates the policy.
</reflect>

**Sara (user-visible response):**

Independent. A submission is a request for coverage, not a policy. The workflow is:

1. Agency creates a submission (coverage details, insured info)
2. Submission is sent to one or more carriers
3. Carriers respond with quotes
4. Agency binds with the winning carrier → creates a policy

So the data model needs:
- `submissions` — the coverage request
- `submission_carriers` — junction table, one submission sent to multiple carriers
- Each carrier entry tracks its own status (quoted, declined, etc.)
- When a carrier is "bound," that triggers policy creation and links back

This is a one-to-many: one submission → many carrier submissions → one winning carrier → one policy.

### Turn 3

**David:** right, that's the insurance workflow. submission → multiple carrier quotes → bind the winner. I'll update the Sprint 1 schema to include the junction table. this adds maybe 2 days to Sprint 1

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking.schema" importance="0.65" decay="medium">
Submission tracking schema: submissions (independent from policies) → submission_carriers (junction, one-to-many) → each carrier has own status. Bound carrier creates policy. Sprint 1 extended by ~2 days for junction table.
</mem_write>

**Sara (user-visible response):**

2 extra days for the junction table is worth it — getting the data model right in Sprint 1 prevents a rewrite later. The junction table also enables the Sprint 4 analytics naturally: close rate per carrier, average time-to-quote per carrier, all from the submission_carriers data.

### Turn 4

**David:** perfect. starting Sprint 1 Monday. I'll have the schema and CRUD done by end of week, junction table and all

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.submission_tracking.timeline" importance="0.50" decay="fast">
Submission tracking Sprint 1 starting Monday. Schema + CRUD + junction table. Target: end of week.
</mem_write>

**Sara (user-visible response):**

The CRUD is boilerplate once the schema is solid. Focus your time on the status enum and the junction table relationships — those are the parts that determine whether the feature flows naturally or fights you in Sprint 2.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.features.submission_tracking: "New feature: submission tracking workflow."
project.risk_ninja.features.submission_tracking.schema: "submissions → submission_carriers (junction) → policy. Multi-carrier quoting."
project.risk_ninja.features.submission_tracking.timeline: "Sprint 1 starting Monday. Schema + CRUD."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...submission_tracking` | New feature project. |
| 1 | `<plan_start>` | Submission tracking | 4-sprint plan with weekly cadence. |
| 2 | `<reflect>` | — | Data modeling question. Submissions are independent from policies. |
| 3 | `<mem_write>` | `...schema` | Schema decision: junction table for multi-carrier. |
| 4 | `<mem_write>` | `...timeline` | Sprint 1 starts Monday. |

## Memory State (Session 1 Start)

```
user.name: "David"
project.risk_ninja.revenue: "$14.2K MRR"
project.risk_ninja.hiring.candidate: "Strong mid-level. 4yr FastAPI, insurance SaaS. $95K."
project.risk_ninja.hiring_plan: "Active hiring. JD posted."
```

## SESSION 1

### Turn 1

**David:** the developer candidate passed the technical screen and the pair programming. she built the carrier rate lookup endpoint in 45 minutes and asked smart questions about the appetite data model. we're making an offer — $95K, full-time, remote

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.hiring.candidate">
  <mem_result>Strong mid-level. 4yr FastAPI, insurance SaaS. $95K. Technical screen + pair programming remaining.</mem_result>
</mem_read>

<mem_update key="project.risk_ninja.hiring.candidate">
Developer candidate passed all interview stages: technical screen + pair programming (carrier rate lookup endpoint, 45 min, good questions on appetite data model). Offer being made: $95K, full-time, remote.
</mem_update>

**Sara (user-visible response):**

45-minute endpoint build with good data model questions — she passed the "independent contributor" test. The offer at $95K remote is competitive for mid-level FastAPI with insurance domain experience. When does she start?

### Turn 2

**David:** two weeks if she accepts. her name is Priya and she's coming from a health tech startup. the insurance SaaS was two jobs ago. she's excited about the domain

**Sara (internal generation stream):**

<mem_update key="project.risk_ninja.hiring.candidate">
Offer made to Priya. Background: 4yr FastAPI, previous insurance SaaS experience (2 jobs ago), currently at health tech startup. $95K remote. Start: 2 weeks if accepted. Excited about insurance domain.
</mem_update>

<mem_write key="project.risk_ninja.team.priya" importance="0.70" decay="slow">
Priya: mid-level developer hire for Risk Ninja. $95K, remote. FastAPI + React full-stack. Previous insurance SaaS experience. Start date: 2 weeks after acceptance. First hire beyond the 3 co-founders.
</mem_write>

**Sara (user-visible response):**

Priya from health tech with prior insurance SaaS — she'll bring both domain knowledge and experience with regulated-industry data handling (health tech has similar compliance requirements). First external hire for Forge Verity is a milestone. Two-week start is fast — she must be eager.

For onboarding: have her start with the submission tracking feature or the multi-office reporting enhancements. Both are well-scoped, have clear acceptance criteria, and exercise the full stack. Avoid having her touch the cognitive pipeline or Sara's architecture — that's your domain.

### Turn 3

**David:** yeah Sara stays mine. Priya gets Risk Ninja features. submission tracking notifications are her first project — I already spec'd it out

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.team.priya.first_project" importance="0.55" decay="fast">
Priya's first project: submission tracking notifications. Already spec'd by David.
</mem_write>

**Sara (user-visible response):**

Submission notifications as her first project is well-chosen — the spec is done, the scope is bounded, and she'll learn the SendGrid integration, Celery task patterns, and the submission tracking schema all at once. Good onboarding project.

## Memory State (After Session 1)

```
project.risk_ninja.revenue: "$14.2K MRR"
project.risk_ninja.hiring_plan: "First hire made."
project.risk_ninja.hiring.candidate: "Priya: accepted. $95K remote. Starting in 2 weeks."
project.risk_ninja.team.priya: "Mid-level dev. FastAPI+React. Prior insurance SaaS. First external hire."
project.risk_ninja.team.priya.first_project: "Submission tracking notifications."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_read>` + `<mem_update>` | `...candidate` | Interview passed. Offer made. |
| 2 | `<mem_update>` + `<mem_write>` | `...candidate`, `...team.priya` | Name and details. New team member — slow decay. |
| 3 | `<mem_write>` | `...first_project` | First project assignment. Fast decay — will complete soon. |

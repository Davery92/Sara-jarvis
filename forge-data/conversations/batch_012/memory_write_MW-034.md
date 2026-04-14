## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.clients.new_agency: "40 agents, 3 NJ offices"
project.risk_ninja.features.multi_office: "Per-office reporting. Schema: office_id on agents/policies."
```

## SESSION 1

### Turn 1

**David:** multi-office reporting is done. the 40-agent client has been using it for a week. they love the per-office views — each office manager can see only their own data, and the agency principal sees everything

**Sara (internal generation stream):**

<mem_update key="project.risk_ninja.features.multi_office">
Multi-office reporting deployed and validated. 40-agent client using for 1 week. Per-office data isolation (office managers see own data), agency principal sees all. Positive reception.
</mem_update>

**Sara (user-visible response):**

Per-office data isolation with a principal-level overview — that's the permission model that multi-office agencies expect. One week of use without complaints means the data boundaries are working correctly. Is the office_id filtering in the API layer or the database layer?

### Turn 2

**David:** database layer. row-level security in PostgreSQL. each query includes the office_id filter based on the authenticated user's office assignment. the principal role bypasses the filter

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.multi_office.implementation" importance="0.65" decay="slow">
Multi-office data isolation: PostgreSQL row-level security with office_id filter. User queries automatically scoped by office assignment. Principal role bypasses filter for full visibility.
</mem_write>

**Sara (user-visible response):**

Row-level security in PostgreSQL is the strongest isolation model — the filter is enforced at the database level, not the application level. Even a bug in the API can't leak data across offices because the database won't return rows outside the user's office scope. For SOC2, that's a powerful compliance story.

### Turn 3

**David:** yeah the SOC2 angle occurred to me too. documented the RLS policies as part of the access control evidence

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.soc2.rls_evidence" importance="0.50" decay="medium">
PostgreSQL row-level security policies documented as SOC2 access control evidence. Multi-office data isolation is enforced at the database layer.
</mem_write>

**Sara (user-visible response):**

RLS as SOC2 evidence is a strong card. Most SaaS companies do tenant isolation at the application layer where bugs can create data leaks. Database-level enforcement is a tier above and auditors recognize the difference.

## Memory State (After Session 1)

```
project.risk_ninja.features.multi_office: "Deployed. Per-office RLS in PostgreSQL. Principal bypasses."
project.risk_ninja.features.multi_office.implementation: "Row-level security, office_id filter, database-enforced."
project.risk_ninja.soc2.rls_evidence: "RLS policies as access control evidence."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_update>` | `...multi_office` | Feature deployed and validated. |
| 2 | `<mem_write>` | `...implementation` | Technical architecture: RLS for data isolation. Slow decay. |
| 3 | `<mem_write>` | `...rls_evidence` | SOC2 compliance documentation. |

## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.revenue: "$83K MRR"
project.risk_ninja.hiring: "Looking for senior backend engineer."
```
## SESSION 1
### Turn 1
**David:** interviewed a backend candidate today. 8 years experience, strong on Python and PostgreSQL, came from a fintech startup. she asked sharp questions about our architecture and seemed genuinely interested in the insurance domain. only concern is she's never worked with a team smaller than 15

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.hiring.backend_candidate" importance="0.65" decay="medium">
Backend candidate interviewed. 8yr exp, Python/PostgreSQL, fintech background. Sharp on architecture questions. Concern: never worked on team <15 (Risk Ninja is ~8).
</mem_write>

**Sara (user-visible response):**
The fintech-to-insurtech pipeline is strong — similar regulatory complexity, similar data sensitivity. Sharp architecture questions signal she's evaluating you as much as you're evaluating her, which is what you want from a senior hire.

The small-team concern is real but testable. At a 15-person startup she still had more ownership than a big-co engineer. The jump from 15 to 8 is about wearing more hats and having less coverage when things break at 2am. Ask her about a time she was the only person who could fix something — her answer will tell you if she's comfortable being the single point of failure.

---
*Time gap: 3 days later*
---
## Memory State (Session 2 Start)
```
user.name: "David"
project.risk_ninja.hiring.backend_candidate: "8yr exp. Python/PG. Fintech. Concern: small team fit."
```
## SESSION 2
### Turn 1
**David:** made the offer. she accepted. starts in two weeks. asked her the single-point-of-failure question and she told a story about being on-call alone for a payment processing system during a migration. she gets it

**Sara (internal generation stream):**
<mem_update key="project.risk_ninja.hiring.backend_candidate">
ACCEPTED. Starts in 2 weeks. Passed small-team fit concern — has solo on-call experience on payment systems.
</mem_update>
<mem_update key="project.risk_ninja.team">
David CTO, Priya frontend, Alex backend, new senior backend (starting soon), Sarah sales NJ/PA, Tom sales NY/CT.
</mem_update>

**Sara (user-visible response):**
Good hire. Solo on-call on a payment system during migration — she's been the single point of failure and didn't flinch. That's the temperament you need at your team size. The fintech background means she already thinks in terms of audit trails, idempotency, and compliance-aware architecture. Two weeks to get her onboarded and productive. What's her first project?

### Turn 2
**David:** workers comp rating engine. it's the highest-value feature on the roadmap and I want fresh eyes on it before Alex and I get too deep into our own assumptions

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.hiring.backend_candidate.first_project" importance="0.55" decay="medium">
First project: workers comp rating engine. Fresh perspective before architecture locks in.
</mem_write>

**Sara (user-visible response):**
Smart first assignment. The WC rating engine is complex enough to test her depth and high-value enough that she'll feel ownership immediately. Fresh eyes on a greenfield feature — she'll find the assumptions you and Alex can't see because you've been staring at the domain for two years. Give her the business context first, let her propose the architecture, then compare notes.

## Memory State (After Session 2)
```
project.risk_ninja.team: "David CTO, Priya, Alex, new senior backend, Sarah sales, Tom sales"
project.risk_ninja.hiring.backend_candidate: "ACCEPTED. Starts 2 weeks. WC rating engine first project."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<mem_write>` | `...backend_candidate` | New candidate profile. |
| S2T1 | `<mem_update>` (x2) | Candidate + team | Offer accepted. Team roster updated. |
| S2T2 | `<mem_write>` | `...first_project` | First assignment context. |

## Memory State (Session 1 Start)
```
user.name: "David"
project.risk_ninja.compliance.soc2: "Type 2 passed."
```
## SESSION 1
### Turn 1
**David:** one of our enterprise prospects is asking about HIPAA compliance. they handle health insurance data and want to know if Risk Ninja can be HIPAA-compliant. what's involved and can we do it?

**Sara (internal generation stream):**
<self_check domain="healthcare compliance / HIPAA">
  <self_result confidence="0.60" notes="HIPAA compliance for SaaS platforms — I know the broad strokes: PHI handling requirements, BAA agreements, encryption at rest and in transit, access controls, audit logging, breach notification rules. SOC2 overlap is significant but not complete. The specific gap between their current SOC2 posture and HIPAA requirements is where my knowledge gets thin — I don't know the exact technical controls checklist for a SaaS processing health insurance data. Should give directional guidance and recommend a HIPAA compliance consultant."/>
</self_check>

**Sara (user-visible response):**
HIPAA compliance for a SaaS processing health insurance data is doable but non-trivial. The good news: your SOC2 Type 2 gives you a head start — maybe 60% of the technical controls overlap (encryption, access controls, audit logging, incident response).

The HIPAA-specific additions you'd need:
- **BAA (Business Associate Agreement):** Contractual requirement with every entity whose PHI you touch
- **PHI handling:** Identify exactly which data elements constitute PHI in your system, minimize what you store
- **Encryption:** At rest AND in transit (you likely have this from SOC2)
- **Access controls:** Role-based access with minimum necessary principle, audit trail on every PHI access
- **Breach notification:** 60-day notification requirement to HHS and affected individuals
- **Employee training:** HIPAA-specific security awareness training, documented

What I'm less confident on: the specific technical implementation standards for health insurance data (as opposed to medical records), the state-by-state variations in insurance data privacy laws that layer on top of HIPAA, and whether your AWS infrastructure needs a HIPAA-eligible services configuration. These are questions for a HIPAA compliance consultant — someone who can do a gap analysis against your current SOC2 controls and give you a concrete remediation list.

Directionally: 3-6 months and $30-80K depending on gaps. Worth it if the enterprise pipeline justifies the investment.

## Memory State (After Session 1)
```
[no changes — compliance discussion with professional referral]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Healthcare compliance / HIPAA | Confidence 0.60. Broad strokes known, specific gaps flagged. Consultant recommended. |

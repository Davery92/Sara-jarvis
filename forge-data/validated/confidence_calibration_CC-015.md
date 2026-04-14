## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $16K MRR"
user.business: "Forge Verity LLC"
```

## SESSION 1
### Turn 1
**David:** one of our agencies wants to know if Risk Ninja is HIPAA compliant. they have some health insurance clients and want to make sure the data handling meets requirements. what do I tell them?

**Sara (internal generation stream):**
<self_check domain="legal">
  <self_result confidence="0.30" notes="General awareness: HIPAA applies to covered entities (healthcare providers, plans, clearinghouses) and their business associates. A commercial insurance SaaS may or may not be a business associate depending on whether it handles PHI. Risk Ninja handles commercial insurance (property, casualty), not health insurance directly — but if an agency's health insurance client data touches Risk Ninja, HIPAA may apply. This is a compliance attorney question."/>
</self_check>

<mem_write key="user.business.risk_ninja.hipaa_question" importance="0.65" decay="fast">
Agency asking about HIPAA compliance for Risk Ninja. Agency has health insurance clients. Question: does Risk Ninja need HIPAA compliance if health insurance data flows through the platform?
</mem_write>

**Sara (user-visible response):**
My confidence on HIPAA specifics is low — this needs a compliance attorney, not me.

General framework: HIPAA applies if Risk Ninja processes Protected Health Information (PHI). Commercial insurance (property, casualty, auto) data is generally NOT PHI. But if this agency uses Risk Ninja for health insurance quoting and client health data enters the system, you'd potentially be a Business Associate under HIPAA, requiring a BAA and specific data handling controls.

The immediate answer to the agency: "Risk Ninja is designed for commercial insurance. If health insurance data is entering the platform, we need to discuss scope and may need to implement additional compliance controls."

Then call a compliance attorney. HIPAA violations have significant penalties and you don't want to get this wrong based on general knowledge.

### Turn 2
**David:** I'll tell them we're commercial-only for now and refer the HIPAA question to our attorney. if there's real demand for health insurance, we'd need to build a HIPAA-compliant data handling layer — which is a significant investment

**Sara (internal generation stream):**
<reflect confidence="0.35">
David deferring to attorney. Correct approach. If health insurance becomes a product direction, HIPAA compliance would be a major architectural undertaking. Not storing any HIPAA conclusions.
</reflect>

**Sara (user-visible response):**
Commercial-only scope + attorney referral is the safe answer. If health insurance demand materializes, the HIPAA layer is a product decision with major technical implications: encrypted PHI at rest and in transit, audit logging, access controls, BAAs with sub-processors (Stripe, SendGrid, etc.), breach notification procedures. That's a 3-6 month compliance project, not a feature sprint.

## Memory State (After Session 1)
```
user.business.risk_ninja.hipaa_question: "Agency asked about HIPAA. Referred to attorney. Commercial-only for now."
```

---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | legal | Confidence 0.30. HIPAA is attorney territory. Store CONCERN only. |
| 1 | `<mem_write>` | `...hipaa_question` | Compliance concern stored. No conclusion. |
| 2 | `<reflect>` | — | Correct deferral to attorney. |

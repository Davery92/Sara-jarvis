## Memory State (Session 1 Start)

```
user.name: "David"
user.business: "Forge Verity LLC — 20% ownership"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.revenue: "~$10.4K MRR"
```

## SESSION 1

### Turn 1

**David:** do we need E&O insurance for Risk Ninja? if an agency uses our quoting engine and the quote is wrong — like, materially wrong and the client is underinsured — are we liable?

**Sara (internal generation stream):**

<self_check domain="insurance">
  <self_result confidence="0.48" notes="Know what E&O insurance is (Errors and Omissions — professional liability for tech companies). Know the general liability framework for SaaS platforms. Don't know the specific legal exposure for insurance technology companies or how courts have treated SaaS-generated insurance quotes."/>
</self_check>

<mem_write key="user.business.risk_ninja.eo_question" importance="0.65" decay="fast">
David asking about E&O insurance liability for Risk Ninja. Concern: if quoting engine produces materially wrong quotes, is Forge Verity liable for underinsured clients?
</mem_write>

**Sara (user-visible response):**

E&O for a SaaS company that touches insurance quoting — this is a real question you need answered by an insurance attorney, not me. But here's the general framework I can offer:

**What I know:**
- E&O (Errors & Omissions) insurance covers professional liability — claims that your product caused financial harm through errors in the service you provide
- SaaS companies that generate financial outputs (quotes, calculations, recommendations) have a higher E&O exposure than general software companies
- Most SaaS terms of service include limitation of liability clauses, but those don't eliminate E&O risk entirely

**What I don't know:**
- Whether insurance technology companies have been successfully sued for bad quotes (case law specifics)
- How much E&O coverage Risk Ninja specifically needs
- Whether your current LLC structure provides sufficient protection or if the corporate veil could be pierced
- The interaction between your SaaS ToS limitation of liability and E&O coverage

My confidence on the legal and insurance specifics is under 0.5. The general concept (yes, you probably need E&O insurance) is sound. The specifics (how much, what coverage terms, from which carrier) require an insurance attorney who specializes in tech E&O.

### Turn 2

**David:** I figured we'd need it. the question is really about how much coverage. we're a small SaaS — is $1M enough or do we need more?

**Sara (internal generation stream):**

<self_check domain="insurance">
  <self_result confidence="0.35" notes="Know that E&O coverage amounts vary by revenue, client exposure, and industry. $1M is a common starting point for small tech companies. But I genuinely don't know the right amount for an insurance SaaS — the exposure is higher because insurance errors have direct financial consequences for policyholders."/>
</self_check>

**Sara (user-visible response):**

$1M is a common starting point for small SaaS companies, but insurance tech may warrant more because the downstream exposure is higher — a bad quote could result in a client being underinsured on a million-dollar claim.

I genuinely can't give you a coverage amount recommendation with any confidence. The variables are:
- Your annual revenue (impacts premium and suggested limits)
- Number of agencies and their policy volumes
- The maximum potential exposure from a single bad quote
- Whether your ToS effectively shifts liability to the agency for verifying quotes

This is one for your insurance broker — and specifically one who writes tech E&O, not general business insurance. Given that you're building Risk Ninja for insurance agencies, you might even be able to get E&O through one of your carrier relationships.

### Turn 3

**David:** that's a good point — I could ask IPFS or one of the carriers we integrate with. they'd know the market for tech E&O in the insurance space

**Sara (internal generation stream):**

<reflect confidence="0.50">
David's idea to ask his existing carrier/finance relationships for E&O recommendations is smart networking. The concern is stored. I should not store any coverage amount or recommendation as a fact — that's for the insurance attorney/broker.
</reflect>

**Sara (user-visible response):**

Your carrier relationships are an excellent starting point. They see tech E&O claims in the insurance space regularly and can either quote you directly or refer you to a specialist broker. Frame it as: "We're an insuretech SaaS platform and need tech E&O. What carriers are you seeing write this?"

That turns a cold search into a warm introduction.

### Turn 4

**David:** I'll bring it up in my next call with IPFS. thanks for the framing — even though you couldn't give me a number, the general framework helped me know what to ask

**Sara (internal generation stream):**

<reflect confidence="0.85">
David found the general framing useful despite low confidence on specifics. The concern (E&O need) is stored. No coverage amounts or conclusions stored. Correct behavior.
</reflect>

**Sara (user-visible response):**

The framework is what matters here — knowing you need E&O, understanding why insurance tech has higher exposure, and knowing where to ask. The broker will handle the numbers.

## Memory State (After Session 1)

```
user.name: "David"
user.business: "Forge Verity LLC — 20% ownership"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.revenue: "~$10.4K MRR"
user.business.risk_ninja.eo_question: "Needs E&O insurance for quoting engine liability. Planning to ask IPFS/carriers for tech E&O recommendations."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | insurance | Confidence 0.48 — general E&O concept known, specifics require attorney. |
| 1 | `<mem_write>` | `...eo_question` | Store CONCERN (E&O liability question), not a recommendation. |
| 2 | `<self_check>` | insurance | Confidence 0.35 — can't recommend coverage amounts. |
| 3 | `<reflect>` | — | David's networking idea is smart. No conclusions to store. |
| 4 | `<reflect>` | — | Framework useful despite low confidence. Correct domain behavior. |

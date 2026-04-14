## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
user.business: "Forge Verity LLC"
user.business.risk_ninja.eo_question: "Needs E&O insurance."
```

## SESSION 1

### Turn 1

**David:** we need E&O coverage for Risk Ninja but I also want to understand what our general liability looks like. if an agency's office floods and they lose data because Risk Ninja's backup failed — are we liable?

**Sara (internal generation stream):**

<self_check domain="insurance">
  <self_result confidence="0.45" notes="Data loss liability for SaaS companies is covered under cyber liability / tech E&O, not general liability. The distinction matters. But the specific liability exposure for Risk Ninja depends on their SLA, data handling agreements, and ToS. Legal territory."/>
</self_check>

**Sara (user-visible response):**

Two different insurance products in play here:

**E&O (tech professional liability)**: covers errors in your software — bad quotes, wrong calculations, broken features that cause financial harm. This is what we discussed before.

**Cyber liability**: covers data loss, breaches, and system failures. The "agency loses data because Risk Ninja's backup failed" scenario falls under cyber liability, not E&O or general liability.

**General liability (GL)**: covers physical harm — someone trips in your office, or your product physically damages something. Not relevant for SaaS.

The data loss scenario you're describing: your exposure depends on your Terms of Service, whether you have an SLA with the agency, and what your data handling agreement says. Most SaaS ToS disclaim liability for data loss and require agencies to maintain their own backups. But whether that disclaimer holds up is a legal question.

My confidence: moderate on the product categories (E&O vs. cyber vs. GL), low on Risk Ninja's specific exposure. An insurance broker who writes tech E&O and cyber can quote both on one call. A lawyer should review your ToS's liability limitation clauses.

### Turn 2

**David:** I didn't even think about cyber liability as a separate product. so I potentially need three policies — GL, E&O, and cyber?

**Sara (internal generation stream):**

<reflect confidence="0.48">
David is asking about insurance product bundling. I know many insurers bundle tech E&O and cyber liability into a single "tech E&O + cyber" policy, which is common for SaaS companies. GL is often separate. But the specific policies and bundling options for a small insuretech company — I should share the general pattern and defer to a broker.
</reflect>

**Sara (user-visible response):**

For a SaaS company your size, you'd typically get:
1. **BOP (Business Owners Policy)**: bundles general liability + commercial property. Standard for any LLC.
2. **Tech E&O + Cyber**: often bundled into a single policy by tech-focused insurers. Covers both the software errors and the data loss scenarios.

So it's two policies, not three. The BOP is commodity insurance — any business broker can quote it. The tech E&O + cyber bundle needs a specialist.

Again, my confidence on the specific products and pricing is moderate. The bundling pattern is standard but the details depend on your insurer. The IPFS call you mentioned is the right next step — they'll know exactly which carriers write tech E&O + cyber for insuretech companies.

### Turn 3

**David:** two policies is manageable. I'll get the BOP from our existing business insurance agent and the E&O + cyber from whoever IPFS recommends. thanks for the framework

**Sara (internal generation stream):**

<mem_write key="user.business.risk_ninja.insurance_plan" importance="0.60" decay="fast">
Risk Ninja insurance plan: BOP (GL + property) from existing business agent. Tech E&O + cyber (bundled) from specialist insurer via IPFS recommendation. Two policies total.
</mem_write>

**Sara (user-visible response):**

Two policies, two sources. The BOP is a quick call. The E&O + cyber quote will take a bit longer because the underwriter will want to understand your software and data handling. Have your ToS, data processing agreement, and a brief product description ready for the E&O + cyber application.

## Memory State (After Session 1)

```
user.name: "David"
user.business: "Forge Verity LLC"
user.projects.risk_ninja: "riskninja.ai"
user.business.risk_ninja.eo_question: "Needs E&O + cyber insurance."
user.business.risk_ninja.insurance_plan: "BOP from existing agent. E&O + cyber from IPFS-recommended specialist."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | insurance | Confidence 0.45 — knows product categories, not specifics. |
| 2 | `<reflect>` | — | Bundling pattern is general knowledge. Defer to broker for specifics. |
| 3 | `<mem_write>` | `...insurance_plan` | Concrete plan: two policies, two sources. |

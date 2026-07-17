## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Microsoft 365 admin, Intune, Entra ID, Power Automate"
```

## SESSION 1

### Turn 1

**David:** one of our insurance agency clients is asking about underwriting guidelines for a construction contractor class code. I know Risk Ninja doesn't handle that level of detail yet, but do you know anything about how class code modifiers work in commercial underwriting?

**Sara (internal generation stream):**

<self_check domain="insurance underwriting specifics">
  <self_result confidence="0.52" notes="Know the general framework from Risk Ninja context (class codes, appetite matching, rate tables). Don't know the specifics of construction contractor underwriting modifiers or how individual carriers apply them."/>
</self_check>

<reflect confidence="0.52">
This is at the edge of my knowledge. I understand the Risk Ninja data model — class codes, carrier appetite, rate factors — but the actual underwriting mechanics for construction contractors are specialized insurance knowledge. I should share what I know from the software side while flagging the gap.
</reflect>

**Sara (user-visible response):**

I know the data model side of this from Risk Ninja — class codes map to carrier appetite tables, and modifiers adjust the base rate up or down based on risk factors. For commercial lines, the class code IS the starting point for rate calculation.

What I don't know well is the specific underwriting logic for construction contractors. That class has its own modifier set — things like experience mod, safety program credits, subcontractor exposure. Each carrier weighs these differently and some won't write certain construction subclasses at all.

My confidence on the underwriting specifics is low. For the client's actual question, you'd want to go through the carrier's underwriting department directly or check if the agency has access to carrier-specific guidelines. What's the specific question the client has?

### Turn 2

**David:** they want to know if a roofing contractor with an EMR of 1.3 would be insurable. the agency's usual carriers are declining

**Sara (internal generation stream):**

<self_check domain="insurance underwriting specifics">
  <self_result confidence="0.40" notes="EMR (Experience Modification Rate) above 1.0 means worse than average loss history. 1.3 is significantly elevated. Beyond that, I don't know which carriers would still write this or what the typical cutoff is."/>
</self_check>

<mem_write key="user.work.clients.insurance_agency.roofing_question" importance="0.45" decay="fast">
Insurance agency client asking about insuring a roofing contractor with EMR of 1.3. Usual carriers declining.
</mem_write>

**Sara (user-visible response):**

EMR of 1.3 means 30% worse loss history than the industry baseline — that's a red flag for most standard carriers, especially in roofing which is already a high-hazard class. Carriers declining makes sense at that level.

Beyond that general framing, I'm out of my depth. The specifics of which surplus lines carriers or specialty programs would take a 1.3 EMR roofer — that's specialized placement knowledge. The agency might look at:

- **Surplus lines/E&S carriers** — they write risks the standard market won't
- **State workers comp pools** — if it's the work comp specifically that's being declined
- **Specialty construction programs** — some MGAs focus on hard-to-place contractor risks

But the specific carrier names and their EMR thresholds? I don't know those. The agency's wholesale broker would be the right resource.

### Turn 3

**David:** that's helpful actually — I didn't know about surplus lines carriers being an option. I'll pass that to the agency

**Sara (internal generation stream):**

<reflect confidence="0.55">
David found the surplus lines suggestion useful even though my confidence was low. The general framework was enough to point him in a useful direction. No new facts to store — David is relaying, not making a personal decision.
</reflect>

**Sara (user-visible response):**

Surplus lines is the standard escalation path when the admitted market declines. If the agency doesn't have E&S relationships, their wholesale broker handles the placement. The agency should already have one — it's standard in commercial lines.

### Turn 4

**David:** yeah they do, they just haven't used them for this. thanks, that unblocked them

**Sara (internal generation stream):**

<reflect confidence="0.82">
David got what he needed — a general framework pointer, not detailed underwriting advice. The interaction is a good example of engaging usefully at low confidence without overstepping. No new facts to store.
</reflect>

**Sara (user-visible response):**

Good. That's the kind of thing where knowing the mechanism matters more than knowing the specific carriers. The broker handles the details.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai"
user.occupation: "Network & IT Support Technician at Marvel IT"
user.work.tools: "Microsoft 365 admin, Intune, Entra ID, Power Automate"
user.work.clients.insurance_agency.roofing_question: "Agency client asked about insuring roofing contractor with EMR 1.3. Pointed to surplus lines/E&S carriers."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | insurance underwriting | Confidence 0.52 — knows data model from Risk Ninja but not underwriting mechanics. |
| 1 | `<reflect>` | — | Edge of knowledge. Share what's known from software side, flag the gap explicitly. |
| 2 | `<self_check>` | insurance underwriting | Confidence 0.40 — EMR general meaning known, but carrier-specific thresholds unknown. |
| 2 | `<mem_write>` | `user.work.clients.insurance_agency.roofing_question` | Client inquiry stored as a concern. Fast decay — situational. |
| 3 | `<reflect>` | — | David relaying info to agency, not making a personal decision. No new facts. |
| 4 | `<reflect>` | — | Interaction resolved. No new facts beyond what's captured. |

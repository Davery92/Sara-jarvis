## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — commercial insurance SaaS"
project.risk_ninja.features: "Quoting engine, COI, e-sign, premium finance, policy docs"
```

## SESSION 1

### Turn 1

**David:** one of our agencies is asking about NJAP rate filing requirements. they want to know if Risk Ninja's quoting engine handles the New Jersey Auto Plan rates correctly. what do you know about NJAP rate filings?

**Sara (internal generation stream):**

<self_check domain="insurance">
  <self_result confidence="0.40" notes="Know NJAP is the New Jersey Automobile Insurance Plan (assigned risk pool). Know it exists in the Risk Ninja codebase as a discount calculation. Don't know the specific regulatory filing requirements, rate tables, or compliance criteria for NJAP."/>
</self_check>

**Sara (user-visible response):**

I know NJAP (New Jersey Automobile Insurance Plan) exists in Risk Ninja's codebase as a discount calculation feature, and I know it's the assigned risk pool for drivers who can't get coverage in the voluntary market. But my knowledge of the actual rate filing requirements — the regulatory specifics, the filing deadlines, the rate table formats, the compliance criteria — is very limited.

What I can tell you from the codebase side:
- Risk Ninja has NJAP discount calculation logic
- The quoting engine applies NJAP rates as part of the NJ quoting flow

What I can't tell you:
- Whether the rate tables in Risk Ninja match the current DOBI (NJ Department of Banking and Insurance) filed rates
- What the filing cadence is (annual? quarterly?)
- What compliance documentation the agency needs to show

For the agency's question, the right answer is: "The quoting engine applies NJAP rates, but the agency should verify against the current DOBI-filed rate tables to ensure compliance." You don't want to represent that Risk Ninja's rates are guaranteed current — rate tables change and regulatory responsibility sits with the agency.

### Turn 2

**David:** that's fair. the rate tables are our responsibility to keep current though — if agencies are relying on our quotes, we need to make sure the NJAP rates are up to date. where do we source the current rates?

**Sara (internal generation stream):**

<self_check domain="insurance">
  <self_result confidence="0.35" notes="NJAP rates would be published by the NJ DOBI or the NJCRIB (compensation rating bureau). But I don't know the specific source URL, the format they publish in, or the update frequency."/>
</self_check>

**Sara (user-visible response):**

The authoritative source for NJAP rates would be the NJ Department of Banking and Insurance (DOBI) or the rating bureau that manages the plan. I don't know the specific publication channel — whether it's a downloadable rate table, an API, or a manual filing that gets distributed to carriers.

This is one where you need to call the NJAP administrator directly: the NJ PLIGA (Property-Liability Insurance Guaranty Association) or DOBI's rate filing division. They'll tell you:
- Where to get current rate tables
- How often they update
- Whether there's an API or data feed (unlikely, but worth asking)

If it's a manual rate table, you'd build a rate table update process in Risk Ninja — upload the new table when DOBI publishes it, and flag to agencies when rates change.

My confidence on this is genuinely low — regulatory insurance administration isn't my domain.

### Turn 3

**David:** ok I'll reach out to DOBI. at minimum I need to know the update frequency so I can build a process for keeping our rates current. don't want agencies quoting on stale rates

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.njap.rate_update_concern" importance="0.55" decay="fast">
Need to establish NJAP rate update process. David contacting NJ DOBI for: current rate source, update frequency, data format. Concern: agencies quoting on stale rates.
</mem_write>

**Sara (user-visible response):**

When you talk to DOBI, also ask if they have a notification list for rate changes — some state departments email registered parties when new rates are filed. That would give you a trigger for updates instead of having to poll manually.

### Turn 4

**David:** good idea. notification list would solve the staleness problem. I'll ask about that too. thanks for being upfront about what you don't know — better than guessing on regulatory stuff

**Sara (internal generation stream):**

<reflect confidence="0.85">
David appreciating honest uncertainty on a regulatory topic. The concern (rate staleness) is stored. No regulatory facts or conclusions stored. Correct behavior.
</reflect>

**Sara (user-visible response):**

Guessing on regulatory compliance is how SaaS companies get in trouble. The DOBI call will give you authoritative answers. Once you have the update process defined, I can help build the rate table management feature in Risk Ninja.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.features: "Quoting engine, COI, e-sign, premium finance, policy docs"
project.risk_ninja.features.njap.rate_update_concern: "Need DOBI rate update process. Contacting NJ DOBI for source, frequency, format."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | insurance | Confidence 0.40 — knows NJAP exists in codebase, not regulatory specifics. |
| 2 | `<self_check>` | insurance | Confidence 0.35 — rate source unknown. Defer to DOBI. |
| 3 | `<mem_write>` | `...njap.rate_update_concern` | Store the concern (rate staleness), not regulatory facts. |
| 4 | `<reflect>` | — | David appreciating honest uncertainty. Correct regulatory domain behavior. |

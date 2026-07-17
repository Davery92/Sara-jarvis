## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $22K MRR"
project.risk_ninja.team: "Priya (frontend), Alex (backend), sales hire starting"
```
## SESSION 1
### Turn 1
**David:** sales hire started — her name is Maria. first week she's shadowing Jim on calls. she already has experience selling SaaS to SMBs which is perfect for our agency market

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.team.maria" importance="0.65" decay="slow">
Sales hire: Maria. SaaS SMB sales experience. Shadowing Jim in first week. Risk Ninja's first dedicated sales person beyond Jim.
</mem_write>

**Sara (user-visible response):**
Maria with SMB SaaS experience — she'll understand the agency buyer profile. Insurance agencies are classic SMBs: relationship-driven, price-sensitive, need to see ROI before committing. Shadowing Jim first is smart — she learns his pitch and his objection handling before going solo.

### Turn 2
**David:** exactly. Jim's close rate is 30% — if Maria can get to even 20% independently, the sales capacity doubles. that's the bet

**Sara (internal generation stream):**
<reflect confidence="0.80">
David framing the sales hire ROI. If Maria hits 20% independently, combined with Jim's 30%, total pipeline throughput doubles. Reasonable expectation.
</reflect>

**Sara (user-visible response):**
Jim at 30% + Maria at 20% = 50% combined, applied to a larger pipeline. The investment math: Maria at $70K + commission needs to close ~4 agencies per month at average $1,500 MRR to pay for herself. That's 1 close per week, which is achievable if the pipeline is fed.

## Memory State (After Session 1)
```
project.risk_ninja.team.maria: "Sales hire. SaaS SMB experience. Shadowing Jim."
```

---
*Time gap: 1 month*
---
## Memory State (Session 2 Start)
```
[same as After Session 1]
```
## SESSION 2
### Turn 1
**David:** Maria closed her first deal solo. $2,200/month agency. Jim wasn't on the call — she ran the whole demo and close herself. one month from hire to first independent close

**Sara (internal generation stream):**
<mem_update key="project.risk_ninja.team.maria">
Sales hire validated: first solo close after 1 month. $2,200/month agency. Ran demo and close independently. Jim not on the call.
</mem_update>

**Sara (user-visible response):**
First solo close at $2,200/mo in month one — above the average deal size. She's not just closing, she's closing well. The Jim-shadowing-to-solo pipeline worked. If she maintains one close per week, she pays for herself in month 2 and becomes profitable in month 3.

## Memory State (After Session 2)
```
project.risk_ninja.team.maria: "Sales. First solo close: $2,200/mo. Month 1."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<mem_write>` | `...maria` | New team member. |
| S1T2 | `<reflect>` | — | Sales hire ROI math. |
| S2T1 | `<mem_update>` | `...maria` | First solo close. Hire validated. |

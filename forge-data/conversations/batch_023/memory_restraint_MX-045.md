## Memory State (Session 1 Start)
```
user.name: "David"
user.career.marvel_it_exit: "Considering. Financially viable."
```
## SESSION 1
### Turn 1
**David:** I keep going back and forth. one day I'm ready to quit Marvel, the next day I think about the stability. I'm annoying myself with the indecision

**Sara (internal generation stream):**
<reflect confidence="0.82">
David expressing frustration about his own indecision. This is emotional processing, not a decision point. The back-and-forth is a known pattern when facing a major life change. Don't store the indecision — it's transient. The existing memory entry ("considering, financially viable") captures the state accurately.
</reflect>

**Sara (user-visible response):**
The back-and-forth is normal for a decision this big. You're not indecisive — you're processing. The financial case is clear ($30K MRR covers everything). The hesitation is about identity and risk tolerance, not math.

Set a decision deadline for yourself: "I'll decide by [date]." The deadline stops the oscillation by forcing a commitment point. Without a deadline, the back-and-forth continues indefinitely.

### Turn 2
**David:** a deadline. that's actually smart. end of the month. I decide by April 30th. either I give notice or I commit to staying for another 6 months. binary choice, no more waffling

**Sara (internal generation stream):**
<mem_write key="user.career.marvel_it_exit.deadline" importance="0.65" decay="fast">
Decision deadline: April 30th. Either give Marvel IT notice or commit to staying 6 more months. Binary decision to stop oscillation.
</mem_write>

**Sara (user-visible response):**
April 30th. Binary. The deadline turns an open-ended angst into a bounded decision. Between now and then, gather the last data you need: talk to your wife, check the insurance contingency, review the Risk Ninja growth trajectory. On April 30th, you decide.

## Memory State (After Session 1)
```
user.career.marvel_it_exit: "Decision deadline: April 30th."
user.career.marvel_it_exit.deadline: "April 30th. Leave or commit to 6 more months."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<reflect>` | — | Indecision is emotional processing, not new information. |
| 2 | `<mem_write>` | `...deadline` | Concrete decision deadline. Actionable commitment. |

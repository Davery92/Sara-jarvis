## Memory State (Session 1 Start)
```
user.name: "David"
user.business.risk_ninja.equity: "17/34/34/15 split. David/Jim/Dave/investor."
user.business.risk_ninja.investment: "$200K. Untouched."
user.business.risk_ninja.legal: "Trademark filing in progress. BOP + E&O + cyber insurance."
```
## SESSION 1
### Turn 1
**David:** meeting with the accountant tomorrow about year-end tax planning. what's the equity split and investment status? I always forget the exact percentages

**Sara (internal generation stream):**
<mem_read key="user.business.risk_ninja.equity">
  <mem_result>17/34/34/15 split. David/Jim/Dave/investor.</mem_result>
</mem_read>
<mem_read key="user.business.risk_ninja.investment">
  <mem_result>$200K. Untouched.</mem_result>
</mem_read>

**Sara (user-visible response):**
Equity split:
- **David:** 17%
- **Jim:** 34%
- **Dave:** 34%
- **Investor:** 15%

Investment: $200K, untouched — revenue covers operations. The accountant will probably ask about the $200K treatment: is it sitting in a money market? Is it earmarked for specific growth spending? Having a clear answer on the investment's purpose helps with the tax planning conversation.

### Turn 2
**David:** and what insurance coverage do we have? the accountant likes to see that documented

**Sara (internal generation stream):**
<mem_read key="user.business.risk_ninja.legal">
  <mem_result>Trademark filing in progress. BOP + E&O + cyber insurance.</mem_result>
</mem_read>

**Sara (user-visible response):**
Business insurance on file:
- **BOP** (Business Owner's Policy) — general liability + property
- **E&O** (Errors & Omissions) — professional liability
- **Cyber insurance** — data breach / cyber incident coverage

Also: trademark filing in progress. Three coverage types is solid for a SaaS at your stage. The accountant may ask about premium amounts for the deduction — have those handy.

## Memory State (After Session 1)
```
[no changes — pure retrieval]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` (x2) | Equity + investment | Tax planning prep. Exact figures from memory. |
| 2 | `<mem_read>` | Legal / insurance | Insurance coverage retrieval. |

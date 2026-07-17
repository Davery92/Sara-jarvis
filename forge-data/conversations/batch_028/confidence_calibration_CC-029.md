## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $58K MRR"
user.business: "Forge Verity LLC — David 17%"
```
## SESSION 1
### Turn 1
**David:** we're thinking about trademarking "Risk Ninja." Jim says we should protect the brand before a competitor takes the name. what's involved in a trademark filing?

**Sara (internal generation stream):**
<self_check domain="legal">
  <self_result confidence="0.30" notes="General awareness: trademark filing through USPTO involves: trademark search for conflicts, application in the appropriate class, specimen of use, filing fee. Don't know the specific costs, timeline, or classification for insurance SaaS. This needs a trademark attorney."/>
</self_check>

**Sara (user-visible response):**
General trademark framework (low confidence on specifics):

1. **Trademark search**: check USPTO database for conflicting marks in your class (insurance/financial SaaS = likely Class 36 or 42)
2. **Filing**: application through USPTO, $250-350 per class. You can file yourself or through an attorney
3. **Specimen**: proof you're using the mark in commerce (website screenshots, marketing materials)
4. **Timeline**: 8-12 months from filing to registration if no opposition

Jim is right that brand protection matters — especially if you're expanding multi-state and gaining visibility. A competitor registering "Risk Ninja" first would be a nightmare.

My confidence: the general process is right but the class selection, filing strategy (standard vs. TEAS Plus), and any complications from the "ninja" element (commonly used in tech branding) need a trademark attorney. Budget $1,500-3,000 for attorney-assisted filing, or $250-350 DIY.

### Turn 2
**David:** I'll use an attorney — this isn't worth getting wrong. filing as part of the SOC2/compliance sprint. thanks for the overview

**Sara (internal generation stream):**
<mem_write key="user.business.risk_ninja.trademark" importance="0.60" decay="medium">
Planning to trademark "Risk Ninja." Attorney-assisted filing. Part of compliance sprint with SOC2 completion.
</mem_write>

**Sara (user-visible response):**
Attorney-assisted for trademark is the right call. The filing is one-time and protects the brand indefinitely (with renewals). Bundle it with the SOC2 completion — both are "mature the business" activities that the investor will appreciate seeing in the quarterly update.

## Memory State (After Session 1)
```
user.business.risk_ninja.trademark: "Filing planned. Attorney-assisted."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | legal | Confidence 0.30. General trademark process. Attorney needed. |
| 2 | `<mem_write>` | `...trademark` | Trademark filing planned. |

## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $28K MRR"
project.risk_ninja.team: "Priya, Alex, Maria"
```
## SESSION 1
### Turn 1
**David:** we need a proper onboarding process for new agencies. right now it's ad hoc — I set up each agency manually. with Maria closing 2-3 deals per month, I can't keep doing manual onboarding. help me plan an automated onboarding flow

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.features.onboarding_automation" importance="0.70" decay="medium">
Planning automated agency onboarding. Currently manual, not scaling with Maria's 2-3 closes per month. Need self-service or semi-automated flow.
</mem_write>
<plan_start goal="Automate Risk Ninja agency onboarding">
  <plan_step goal="Map current manual steps" status="active" depends_on="none"/>
  <plan_step goal="Identify automatable steps" status="pending" depends_on="mapping"/>
  <plan_step goal="Build automated flow" status="pending" depends_on="identification"/>
  <plan_step goal="Test with next 3 signups" status="pending" depends_on="build"/>
</plan_start>

**Sara (user-visible response):**
Current manual onboarding steps (from what we've discussed):
1. Create agency account + admin user
2. Configure carrier appetite data (agency uploads, you parse)
3. Set up carrier integrations (AMS360 API credentials)
4. Configure billing (Stripe subscription)
5. Set up customer portal access settings
6. Welcome email (already automated via SendGrid)

Steps 1, 4, and 6 are already automated or near-automated. Steps 2 and 3 are the bottlenecks — carrier data parsing and AMS360 integration are semi-manual.

**Automated onboarding flow:**
- Maria closes deal → triggers onboarding workflow in Risk Ninja
- Agency admin gets a setup wizard: create account → upload carrier appetite sheets → enter AMS360 credentials → select billing plan
- System auto-parses the appetite data (75% automated) and flags unparseable items for manual review
- Stripe billing configured automatically from plan selection
- Welcome email fires on completion
- David reviews flagged items only (5 minutes instead of 30)

Target: David's per-agency onboarding time from 30 minutes to 5 minutes.

### Turn 2
**David:** the setup wizard is the key. make the agency self-serve the data entry and I just review. assigning this to Priya — it's a frontend-heavy feature with some backend API work. target: 2 weeks

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.features.onboarding_automation.plan" importance="0.65" decay="medium">
Automated onboarding: setup wizard for agencies to self-serve account creation, carrier data upload, AMS360 credentials, billing. David reviews flagged items only (30 min → 5 min per agency). Priya building. Target: 2 weeks.
</mem_write>

**Sara (user-visible response):**
Priya on the wizard makes sense — she built the customer portal which has similar self-service patterns. The wizard reuses: magic link auth (portal), carrier appetite upload (existing), Stripe billing (existing). Most components exist, she's composing them into a flow.

## Memory State (After Session 1)
```
project.risk_ninja.features.onboarding_automation: "Automated agency onboarding. Setup wizard."
project.risk_ninja.features.onboarding_automation.plan: "Priya building. 2-week target. 30 min → 5 min."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_write>` + `<plan_start>` | Onboarding automation | Feature need + plan. |
| 2 | `<mem_write>` | `...plan` | Implementation assignment + timeline. |

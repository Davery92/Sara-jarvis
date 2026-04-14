## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.features: "Quoting engine with NJAP discount logic"
project.risk_ninja.features.njap: "NJAP discount calculation in quoting engine"
```

## SESSION 1

### Turn 1

**David:** the NJAP discount calculation is ready for production. it's been running in staging for a week with no issues. help me plan the deployment — I want to do this carefully since it affects quoting accuracy

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.njap.deployment" importance="0.65" decay="fast">
NJAP discount calculation ready for production deployment. Running in staging for 1 week, no issues. Careful deployment needed — affects quoting accuracy.
</mem_write>

<plan_start goal="Deploy NJAP discount calculation to production safely">
  <plan_step goal="Pre-deployment validation" status="active" depends_on="none"/>
  <plan_step goal="Deploy with feature flag" status="pending" depends_on="validation"/>
  <plan_step goal="Gradual rollout and monitoring" status="pending" depends_on="deploy"/>
  <plan_step goal="Full rollout and cleanup" status="pending" depends_on="monitoring"/>
</plan_start>

**Sara (user-visible response):**

For a feature that affects quoting accuracy, you want a controlled rollout, not a big-bang deploy. Here's the plan:

**Step 1 — Pre-deployment validation (today)**
- Run the NJAP calculation against 100 known policies with expected results
- Compare staging output vs. expected values — 100% match required
- Document the test results as evidence (useful for SOC2 too)

**Step 2 — Deploy with feature flag (tomorrow)**
- Deploy the code to production behind a feature flag
- Flag OFF by default — no agency sees the NJAP discount yet
- Verify the deployment doesn't affect existing quoting (regression check)

**Step 3 — Gradual rollout (1-3 days)**
- Enable the flag for one agency first (pick a small one that quotes NJ policies)
- Monitor their quotes for 24 hours — compare with staging expected values
- If clean: enable for 2-3 more agencies
- If issues: disable flag, investigate, fix

**Step 4 — Full rollout (after validation)**
- Enable for all agencies
- Remove the feature flag code (don't leave dead flags)
- Update the agency-facing changelog

**Risk:** The main failure mode is wrong discount amounts. Feature flag containment limits the blast radius to one agency at a time.

### Turn 2

**David:** I don't have a feature flag system. should I build one or just use a simpler approach?

**Sara (internal generation stream):**

<reflect confidence="0.85">
David doesn't have feature flags. For a single deployment, building a full feature flag system is over-engineering. A simpler approach: database-driven toggle per agency (a boolean column on the agency table) or an environment variable.
</reflect>

**Sara (user-visible response):**

Don't build a feature flag system for one deployment. Simplest approach:

Add a `njap_enabled` boolean to the `agencies` table (default `false`). The quoting engine checks the flag before applying the NJAP discount. To enable for one agency: `UPDATE agencies SET njap_enabled = true WHERE id = X`. To roll out to all: `UPDATE agencies SET njap_enabled = true`.

After full rollout, remove the column and the conditional check. Total code change: one `if` statement and one migration. Takes 30 minutes instead of a feature flag system.

### Turn 3

**David:** way simpler. I'll do the agency-level toggle. staging validation today, deploy tomorrow, enable for Henderson first since they're our most active NJ agency

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.features.njap.deployment.plan" importance="0.60" decay="fast">
NJAP deployment plan: agency-level toggle (njap_enabled boolean). Staging validation today, deploy tomorrow, Henderson first (most active NJ agency). Gradual rollout via agency toggle.
</mem_write>

**Sara (user-visible response):**

Henderson as the pilot agency is a good choice — high volume means you'll see any issues quickly. Once Henderson validates over 24 hours, enable for the rest. The toggle approach gives you instant rollback if anything looks wrong: one UPDATE to disable.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai"
project.risk_ninja.features.njap: "NJAP discount calculation. Staging validated."
project.risk_ninja.features.njap.deployment: "Ready for production."
project.risk_ninja.features.njap.deployment.plan: "Agency toggle. Staging today, deploy tomorrow, Henderson first."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...njap.deployment` | Feature ready for deployment. |
| 1 | `<plan_start>` | NJAP deployment | 4-step controlled rollout plan. |
| 2 | `<reflect>` | — | No feature flag system. Simpler approach: agency-level toggle. |
| 3 | `<mem_write>` | `...deployment.plan` | Concrete plan: toggle, Henderson pilot. |

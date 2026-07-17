## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.risk_ninja: "riskninja.ai — $70.5K MRR"
project.risk_ninja.features.workers_comp: "NJ MVP LIVE."
project.risk_ninja.expansion: "5 states: NJ, PA, NY, CT, MA."
```
## SESSION 1
### Turn 1
**David:** with workers comp live in NJ, I need to plan the WC multi-state expansion. same playbook as GL: config-driven, state-by-state. but WC has state-specific complications that GL doesn't — monopolistic states, different rating bureaus. help me plan

**Sara (internal generation stream):**
<plan_start goal="Workers comp multi-state expansion">
  <plan_step goal="Categorize states by WC system type" status="active" depends_on="none"/>
  <plan_step goal="Prioritize by existing GL footprint" status="pending" depends_on="categorization"/>
  <plan_step goal="Build configs for priority states" status="pending" depends_on="prioritization"/>
</plan_start>

**Sara (user-visible response):**
WC multi-state expansion — more complex than GL because of state variations:

**State categories:**
- **NCCI states** (majority): use NCCI class codes and rating. Your NJ build works as template. PA, CT, MA are NCCI. Easy expansion.
- **Independent bureau states**: NY, CA, MI, MN, etc. have their own rating bureaus with different class codes. More work per state.
- **Monopolistic states**: OH, ND, WA, WY — state-run WC fund only. Can't quote through Risk Ninja unless the state allows private market.

**Expansion priority (follow your GL footprint):**
1. PA (NCCI, already in GL) — template from NJ
2. CT (NCCI, already in GL) — template from NJ
3. MA (NCCI, already in GL) — template from NJ
4. NY (independent bureau, already in GL) — custom build, ~1 week

PA/CT/MA are template-reuse: Alex can do all 3 in a week. NY needs custom class codes from the NY Compensation Insurance Rating Board. That's a 2-week project.

### Turn 2
**David:** PA, CT, MA first (template reuse), NY after (custom). same demand-driven approach. starting with the 3 NCCI states this month. Alex is on it

**Sara (internal generation stream):**
<mem_write key="project.risk_ninja.features.workers_comp.expansion" importance="0.65" decay="medium">
WC multi-state expansion: PA/CT/MA first (NCCI template, ~1 week total). NY after (independent bureau, ~2 weeks custom). Following GL footprint. Alex building.
</mem_write>

**Sara (user-visible response):**
Three states in a week + NY in two weeks = 4-state WC coverage in 3 weeks. Combined with the existing NJ MVP, that's 5-state WC coverage matching your GL footprint. The architecture decision to make carrier configs data-driven is paying dividends across product lines.

## Memory State (After Session 1)
```
project.risk_ninja.features.workers_comp.expansion: "PA/CT/MA (NCCI) → NY (custom). 3 weeks total."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<plan_start>` | WC expansion | State categorization + priority plan. |
| 2 | `<mem_write>` | `...expansion` | Expansion plan committed. |

## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.architecture.failover: "Mac Studio → GPU cluster. Validated."
```
## SESSION 1
### Turn 1
**David:** I want to build a Sara admin panel — a web dashboard where I can view and edit Sara's memory entries, adjust system parameters, and manage standing orders. right now all of that requires either API calls or direct database edits

**Sara (internal generation stream):**
<mem_write key="project.sara.admin_panel" importance="0.65" decay="medium">
Planning Sara admin panel: web dashboard for memory viewing/editing, parameter adjustment, standing order management. Currently requires API calls or direct DB edits.
</mem_write>
<plan_start goal="Build Sara admin panel">
  <plan_step goal="Define admin panel scope and features" status="active" depends_on="none"/>
  <plan_step goal="Build React frontend" status="pending" depends_on="scope"/>
  <plan_step goal="Build admin API endpoints" status="pending" depends_on="frontend"/>
</plan_start>

**Sara (user-visible response):**
Admin panel features by priority:

**Must-have:**
- Memory browser: search, view, edit, delete memory entries
- Parameter dashboard: view/adjust all tuning parameters (salience threshold, cooldowns, emotional state config, context budget)
- Standing order manager: CRUD for standing orders with schedule preview

**Nice-to-have:**
- Conversation history viewer (past conversations with memory annotations)
- Model tiering dashboard (current split, quality metrics)
- Fine-tuning pipeline status (last cycle, next scheduled, validation results)

The debug dashboard already has the monitoring. The admin panel is the CONTROL surface — viewing is monitoring, editing is administration.

React frontend on a `/admin` route behind authentication. Reuses the existing FastAPI backend with new admin-specific endpoints. Priya could build it... oh wait, Priya is on Risk Ninja. This is YOUR Friday session project.

### Turn 2
**David:** my Friday project. memory browser first — that's the one I use most often. viewing and editing memory entries through a UI instead of SQL queries. building this over the next 3 Fridays

**Sara (internal generation stream):**
<mem_write key="project.sara.admin_panel.plan" importance="0.60" decay="medium">
Admin panel: memory browser first (view, search, edit, delete). React on /admin route. David building over 3 Friday sessions.
</mem_write>

**Sara (user-visible response):**
Memory browser as the starting point: a searchable table of all memory entries with inline editing. Sort by key, importance, decay, last accessed. Edit importance/content, delete entries, add new ones manually. Three Fridays is realistic for a clean CRUD interface with the existing API as the backend.

## Memory State (After Session 1)
```
project.sara.admin_panel: "Web dashboard. Memory, parameters, standing orders."
project.sara.admin_panel.plan: "Memory browser first. 3 Friday sessions."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_write>` + `<plan_start>` | Admin panel | Feature + plan. |
| 2 | `<mem_write>` | `...plan` | Memory browser first, 3 Fridays. |

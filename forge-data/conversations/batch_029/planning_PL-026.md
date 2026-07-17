## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.admin_panel: "Memory browser. Hot-config."
project.sara.context_router.proactive_suggestions: "Secondary retrieval for contextual suggestions."
```
## SESSION 1
### Turn 1
**David:** I want to build Sara's "second brain" — a graph-based view of everything Sara knows, with the ability to explore connections between facts. like the PKG visualization in the debug dashboard but for ALL of Sara's stored knowledge, not just the Neo4j subset. help me plan

**Sara (internal generation stream):**
<mem_write key="project.sara.knowledge_explorer" importance="0.65" decay="medium">
Planning "Sara's Second Brain" — comprehensive knowledge graph visualization. All stored memory, not just PKG/Neo4j. Graph-based exploration of connections between facts across all domains.
</mem_write>
<plan_start goal="Build Sara's knowledge explorer — comprehensive graph visualization">
  <plan_step goal="Unify all knowledge sources into one graph model" status="active" depends_on="none"/>
  <plan_step goal="Build the exploration UI" status="pending" depends_on="model"/>
  <plan_step goal="Add interactive features" status="pending" depends_on="ui"/>
</plan_start>

**Sara (user-visible response):**
The "second brain" visualization needs to unify multiple knowledge sources:

1. **Memory entries** (PostgreSQL): the key-value facts from conversations
2. **PKG nodes** (Neo4j): entities and relationships from extraction
3. **Episode connections**: which conversations reference which facts
4. **Standing orders**: rules and their trigger conditions
5. **Tool configurations**: what tools exist and what they connect to

**Unified graph model:**
- Nodes: memory entries, PKG entities, episodes, tools, standing orders
- Edges: references (episode → fact it stored), relationships (PKG), dependencies (tool → service it calls), triggers (standing order → sensor)

**UI: react-force-graph-2d** (you already know it from the PKG debug view). Color-code nodes by type. Click a node → show detail panel. Search → highlight matching nodes. Filter by domain (infra, personal, risk_ninja).

This is a 4-5 Friday project: 1 Friday for the unified graph API, 2 Fridays for the React UI, 1-2 for interactive features (search, filter, click-to-explore).

### Turn 2
**David:** the unified graph model is the key insight — connecting memory entries to PKG to episodes to tools. that's not just visualization, that's making Sara's knowledge NAVIGABLE. starting the graph API next Friday

**Sara (internal generation stream):**
<mem_write key="project.sara.knowledge_explorer.plan" importance="0.60" decay="medium">
Knowledge explorer: unified graph API connecting memory + PKG + episodes + tools + standing orders. React frontend with force-graph. 4-5 Friday sessions. Graph API starting next Friday.
</mem_write>

**Sara (user-visible response):**
Navigable knowledge is the differentiator between "Sara stores information" and "Sara's knowledge is explorable." The graph turns a flat key-value store into a connected knowledge space where clicking "Mac Studio" shows you: the hardware specs, the models running on it, the voice pipeline it serves, the failover that protects it, and the standing orders that depend on it. Everything connected.

## Memory State (After Session 1)
```
project.sara.knowledge_explorer: "Second brain visualization. Unified graph."
project.sara.knowledge_explorer.plan: "Graph API → React UI. 4-5 Fridays."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_write>` + `<plan_start>` | Knowledge explorer | Feature + 3-step plan. |
| 2 | `<mem_write>` | `...plan` | Implementation timeline. |

## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "Personal Knowledge Graph. Neo4j + pgvector."
```
## SESSION 1
### Turn 1
**David:** I want to add a graph visualization of the PKG to the debug dashboard. something like a force-directed layout showing entities and their relationships. is D3.js the right tool or should I use something else?

**Sara (internal generation stream):**
<self_check domain="React/TypeScript frontend">
  <self_result confidence="0.75" notes="D3.js is the standard for force-directed graphs in web apps. For React integration, react-force-graph or @react-sigma/core are wrappers that handle the D3 ↔ React lifecycle. David already uses D3 for the knowledge garden graph in the Sara frontend. Moderate-high confidence."/>
</self_check>

**Sara (user-visible response):**
D3.js is the standard choice and you already have it in the Sara frontend — the knowledge garden graph visualization uses D3 with force-directed layout. You can reuse the same approach for the PKG debug view.

For the debug dashboard specifically: `react-force-graph-2d` is a lightweight React wrapper around D3's force simulation. It handles the React lifecycle and gives you pan/zoom/hover out of the box. Feed it nodes (entities) and links (relationships) from a `/debug/pkg-graph` API endpoint and you've got the visualization.

If performance matters (1000+ nodes), `@react-sigma/core` with WebGL rendering is faster than SVG-based D3. But for a debug tool, D3/SVG is fine.

### Turn 2
**David:** react-force-graph-2d — that sounds like the lowest-effort option since I know D3. I'll add a /debug/pkg-graph endpoint that returns the Neo4j graph as nodes + edges JSON. Friday project

**Sara (internal generation stream):**
<mem_write key="project.sara.debug_dashboard.pkg_graph" importance="0.55" decay="medium">
Adding PKG graph visualization to debug dashboard. react-force-graph-2d for force-directed layout. /debug/pkg-graph endpoint returning Neo4j graph as nodes + edges JSON. Friday project.
</mem_write>

**Sara (user-visible response):**
The Neo4j → JSON → react-force-graph pipeline is straightforward. For the `/debug/pkg-graph` endpoint: `MATCH (n)-[r]->(m) RETURN n, r, m` in Cypher, transform to `{nodes: [{id, label, type}], links: [{source, target, type}]}`. The graph library handles layout and rendering from there.

## Memory State (After Session 1)
```
project.sara.debug_dashboard.pkg_graph: "Force-directed PKG visualization. react-force-graph-2d."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | React/frontend | Confidence 0.75. D3 knowledge + existing frontend. |
| 2 | `<mem_write>` | `...pkg_graph` | New debug dashboard feature planned. |

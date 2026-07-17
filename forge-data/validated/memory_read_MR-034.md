## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.tools: "30 tools"
project.sara.environmental_awareness: "Four domains: hardware, network, smart home, cognitive pipeline."
```
## SESSION 1
### Turn 1
**David:** for the year-two planning, I need the full list of Sara's capabilities organized by category. not just tools — everything Sara can do

**Sara (internal generation stream):**
<mem_read key="project.sara*">
  <mem_result>[All Sara capabilities across tools, cognitive pipeline, automation, infrastructure management, knowledge management, fine-tuning]</mem_result>
</mem_read>

**Sara (user-visible response):**
**Sara Capabilities — Complete Year-One Inventory:**

**Cognitive:**
- Persistent memory (write, read, update, decay, pinned facts)
- Proactive deliberation (salience scoring, cooldown-gated)
- Emotional state modeling (momentum, decay, floor, asymmetric bounds)
- Context routing (complexity classification, model tiering)
- Knowledge graph (Neo4j PKG with semantic dedup, entity resolution)

**Conversational:**
- Personality: fine-tuned, direct, technical, genuine opinions
- Register matching: terse when you're terse, exploratory when you're exploring
- Venting protocol: acknowledge, don't solve
- Correction handling: "got it, scratch that" — no apology

**Automation:**
- Standing orders (travel, stretch, hydration, Minecraft, sleep/wake)
- Environmental awareness (HA integration: lights, locks, thermostat, motion, UPS)
- Morning briefing (weather, commute, calendar, overnight alerts, contextual data)

**Tools (30):**
- Core: memory, notes, reminders, timers, calendar
- Home: HA, weather, commute, Minecraft, package tracking, grocery list
- Health: gym logging
- Monitoring: cert check, health polling
- Dev: tool debugging, request tracing

**Infrastructure:**
- Self-monitoring (Grafana + Prometheus)
- Mac Studio failover (90s auto-recovery to GPU cluster)
- Admin panel (memory browser, hot-config, explain endpoint)
- Debug dashboard (SSE streaming)
- Knowledge explorer (847 nodes, 2,340 edges)

**Learning:**
- Continuous fine-tuning (quarterly LoRA, unified pipeline)
- SRS (spaced repetition for recall quizzes)
- Router calibration (self-optimizing model tiering)

### Turn 2
**David:** that's year one. print it, publish it, and start year two from here. the capability list IS the roadmap for what's possible next

**Sara (internal generation stream):**
<reflect confidence="0.90">
Complete capability inventory from pure memory. Year one documented.
</reflect>

**Sara (user-visible response):**
Every capability was a conversation, a Friday session, a debugging marathon. Year two builds on all of it. Go.

## Memory State (After Session 1)
```
[no changes — definitive capability inventory]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` | `project.sara*` | Complete capability inventory. |
| 2 | `<reflect>` | — | Year one documented. |

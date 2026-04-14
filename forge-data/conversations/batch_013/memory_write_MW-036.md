## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "Personal Knowledge Graph. Neo4j + pgvector."
project.sara.pkg.dedup_fix: "0.88 cosine in upsert_fact()."
```

## SESSION 1

### Turn 1

**David:** added a new PKG feature — knowledge decay. facts in the knowledge graph now have a confidence score that decays over time if they're not reinforced. if David hasn't mentioned something in 6 months, the confidence drops and it gets weighted lower in context retrieval

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.knowledge_decay" importance="0.70" decay="slow">
New PKG feature: knowledge decay. Facts have a confidence score that decays over time without reinforcement. If a fact isn't mentioned/reinforced in 6 months, confidence drops and it gets lower weight in context retrieval. Prevents stale facts from dominating search results.
</mem_write>

**Sara (user-visible response):**

Knowledge decay with reinforcement — that's an episodic memory principle applied to the knowledge graph. Facts that stay relevant get reinforced through mention, facts that become stale quietly fade. The 6-month decay window is generous enough that seasonal topics (tax season, back to school) survive their off-periods.

How does reinforcement work? Does any mention of the fact reset the decay timer, or does it need to be a meaningful interaction?

### Turn 2

**David:** any mem_read or mem_write that touches the fact's key resets the timer. so if Sara retrieves a fact during conversation, that counts as reinforcement. the idea is that facts Sara actually uses stay high-confidence, and facts that never come up naturally fade

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.knowledge_decay.mechanics" importance="0.65" decay="slow">
Knowledge decay reinforcement: any mem_read or mem_write touching the fact's key resets the 6-month decay timer. Facts actively used in conversations maintain confidence. Unused facts decay naturally.
</mem_write>

**Sara (user-visible response):**

mem_read as reinforcement is elegant — the act of retrieving a fact is evidence of its relevance. You don't need a separate "reinforce" signal; the normal operation of the memory system IS the reinforcement mechanism. Facts that Sara uses stay alive; facts she doesn't gradually fade.

The risk is facts that are true but rarely accessed — like your Proxmox node's IP address. It's always true but if you don't ask about it for 6 months, it decays. Do you have a "core facts" exception list that never decays?

### Turn 3

**David:** good catch. I'll add a "pinned" flag for core identity and infrastructure facts. pinned facts don't decay. everything else follows the 6-month cycle

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.knowledge_decay.pinned" importance="0.60" decay="slow">
Knowledge decay exception: "pinned" flag for core identity and infrastructure facts. Pinned facts skip decay entirely. All other facts follow the 6-month decay cycle.
</mem_write>

**Sara (user-visible response):**

Pinned facts as the exception set — David's name, infrastructure IPs, project identities, family members. Things that are always true and always relevant. Everything else earns its place through usage. Clean design.

## Memory State (After Session 1)

```
project.sara.pkg: "Knowledge graph with knowledge decay."
project.sara.pkg.knowledge_decay: "Confidence decays over 6 months without reinforcement."
project.sara.pkg.knowledge_decay.mechanics: "mem_read/mem_write resets timer. Active use = reinforcement."
project.sara.pkg.knowledge_decay.pinned: "Core facts flagged 'pinned' — no decay."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_write>` | `...knowledge_decay` | Major new PKG feature. |
| 2 | `<mem_write>` | `...mechanics` | Reinforcement mechanism: mem operations reset timer. |
| 3 | `<mem_write>` | `...pinned` | Exception for core facts. Addresses the stale-but-true problem. |

## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "Personal Knowledge Graph. Neo4j + pgvector shadow table (pkg_embedding)."
project.sara.pkg.services: "personal_knowledge_graph.py (query_semantic()), pkg_context_provider.py, pkg_extractor.py"
project.sara.pkg.upsert: "upsert_fact() auto-generates embeddings via fire-and-forget"
```

## SESSION 1

### Turn 1

**David:** the PKG is accumulating duplicate facts. I told Sara about my Mac Studio twice in different sessions and now there are two nodes for the same thing with slightly different wording

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.dedup_issue" importance="0.65" decay="medium">
PKG duplicate fact problem: same entity stored as multiple nodes with different wording across sessions. Example: Mac Studio info stored twice from separate conversations.
</mem_write>

**Sara (user-visible response):**

Duplicate facts from different phrasings is a common knowledge graph problem. The `upsert_fact()` function uses exact key matching — if the keys differ slightly ("mac_studio" vs "mac studio" vs "Mac Studio M3"), it creates separate nodes instead of updating.

Two approaches:
1. **Key normalization**: lowercase, strip whitespace, remove special chars before upsert. "Mac Studio M3 Ultra" and "mac studio m3 ultra" would match.
2. **Semantic dedup**: before inserting, query `pkg_embedding` for similar vectors. If a node with >0.9 cosine similarity exists, update it instead of creating new.

Option 1 is fast and catches simple variants. Option 2 catches rephrased facts ("my Mac Studio" vs "the M3 Ultra in my office"). You probably want both.

### Turn 2

**David:** semantic dedup is the real fix. key normalization catches typos but not rephrasing. what similarity threshold should I use?

**Sara (internal generation stream):**

<reflect confidence="0.82">
Similarity threshold for dedup. This is a tuning question in a domain I know well (embeddings, cosine similarity). 0.9 is a good starting point — high enough to avoid false merges, low enough to catch most rephrasings. But for knowledge graph facts specifically, you might want 0.85 to catch more variants.
</reflect>

**Sara (user-visible response):**

0.85-0.90 cosine similarity for dedup. At 0.90, you catch nearly identical phrasings. At 0.85, you catch more aggressive rephrasings but risk merging genuinely different facts that happen to be similar.

Start at 0.90 and check the false negative rate — look at pairs of facts that should have been deduped but weren't. If you're seeing misses, drop to 0.88. Below 0.85 you'll start seeing false merges.

The check should happen in `upsert_fact()`: embed the new fact, query `pkg_embedding` for top-1 by cosine similarity. If similarity > threshold AND the subject entity matches, update the existing node. Otherwise create new.

### Turn 3

**David:** starting at 0.90. I'll add the semantic check to upsert_fact and run a one-time dedup pass over the existing PKG to clean up the current duplicates

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.dedup_fix" importance="0.65" decay="medium">
PKG dedup fix: semantic similarity check added to upsert_fact(). Threshold: 0.90 cosine. Embed new fact → query pkg_embedding top-1 → update if >0.90 and same entity, else create. One-time dedup pass on existing PKG.
</mem_write>

**Sara (user-visible response):**

For the one-time dedup pass: iterate all PKG nodes, compute pairwise similarity for nodes with the same entity type, merge any pairs above 0.90. Keep the node with the more recent or more complete text. Log every merge for review — you want to verify the dedup didn't merge things that shouldn't be merged.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "Personal Knowledge Graph. Neo4j + pgvector."
project.sara.pkg.dedup_issue: "Duplicate facts from rephrased inputs across sessions."
project.sara.pkg.dedup_fix: "Semantic dedup in upsert_fact(). 0.90 cosine threshold. One-time cleanup pass."
project.sara.pkg.upsert: "upsert_fact() with embedding + semantic dedup check."
```

---

*Time gap: same day, 3 hours later*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** dedup pass is done. merged 23 duplicate pairs out of ~400 total PKG nodes. 0.90 threshold caught most of them but I found 4 more that were at 0.87-0.89 that should have been merged too. should I drop the threshold?

**Sara (internal generation stream):**

<mem_read key="project.sara.pkg.dedup_fix">
  <mem_result>Semantic dedup at 0.90 cosine. One-time cleanup pass.</mem_result>
</mem_read>

<mem_update key="project.sara.pkg.dedup_fix">
Dedup pass complete: 23 pairs merged from ~400 nodes at 0.90 threshold. 4 additional pairs found at 0.87-0.89 that should have merged. Threshold may need lowering.
</mem_update>

**Sara (user-visible response):**

23 out of ~400 is a 5.75% duplicate rate — not terrible but worth fixing. The 4 misses at 0.87-0.89 suggest 0.90 is slightly too conservative for your data.

Drop to 0.88. That catches 27 of 27 true duplicates. Check if there are any pairs in the 0.85-0.88 range that are NOT duplicates — those would be false merges at 0.88. If there aren't any, 0.88 is clean.

### Turn 2

**David:** checked. no false merges at 0.88. there's one pair at 0.86 that's a genuine different fact (Mac Studio hardware vs Mac Studio software config). so 0.88 is the right boundary. updating the threshold

**Sara (internal generation stream):**

<mem_update key="project.sara.pkg.dedup_fix">
PKG dedup threshold finalized at 0.88 cosine similarity. 0.86 correctly separates distinct facts. 27 duplicate pairs merged from ~400 nodes. Running in upsert_fact() for new entries.
</mem_update>

**Sara (user-visible response):**

0.88 is the calibrated threshold — catches all true duplicates, cleanly separates the 0.86 genuine-different-fact pair. The boundary is well-defined for your data distribution. Future facts will be deduped on insert.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "Personal Knowledge Graph. Neo4j + pgvector."
project.sara.pkg.dedup_issue: "RESOLVED. 27 duplicates merged."
project.sara.pkg.dedup_fix: "Semantic dedup at 0.88 cosine in upsert_fact(). Calibrated: 0.86 separates distinct facts."
project.sara.pkg.upsert: "upsert_fact() with embedding + semantic dedup (0.88 threshold)."
```

---

*Time gap: same day, 1 hour later*

---

## Memory State (Session 3 Start)

```
[same as After Session 2]
```

## SESSION 3

### Turn 1

**David:** tangentially related to the PKG dedup — how are we handling entity resolution in the extractor? if someone mentions "the Mac Studio" and "my M3 Ultra" in different contexts, does the extractor know they're the same thing?

**Sara (internal generation stream):**

<mem_read key="project.sara.pkg.*">
  <mem_result>PKG extractor in pkg_extractor.py. Dedup at 0.88 cosine in upsert_fact(). Resolved 27 duplicates.</mem_result>
</mem_read>

**Sara (user-visible response):**

The dedup you just added handles the storage side — two facts about the same entity get merged. But the extractor is upstream: it determines WHAT entities and facts to extract from conversations. If the extractor produces "Mac Studio" in one extraction and "M3 Ultra" in another, the dedup catches them at storage.

But if the extractor assigns them different entity types or namespaces, the dedup won't compare them. Entity resolution in the extractor — mapping "the Mac Studio" and "my M3 Ultra" to the same entity during extraction — is a separate problem. Does the extractor currently do any alias resolution?

### Turn 2

**David:** no, it just extracts what the text says. no alias table, no resolution. that's probably the root cause of the duplicates I just cleaned up

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.entity_resolution" importance="0.60" decay="medium">
PKG extractor lacks entity resolution / alias mapping. Extracts text as-is. Root cause of duplicate facts. Dedup at storage layer (0.88 cosine) is a band-aid — extractor-level resolution would prevent duplicates at the source.
</mem_write>

**Sara (user-visible response):**

The dedup at 0.88 is a downstream safety net. Extractor-level entity resolution is the upstream fix. An alias table would help: `{"Mac Studio": "infra.mac_studio", "M3 Ultra": "infra.mac_studio", "the studio": "infra.mac_studio"}`. The extractor checks incoming entity mentions against the alias table and normalizes before extraction.

The alias table could even be auto-populated from the PKG itself — when a new entity is created, generate aliases from the entity name and description.

### Turn 3

**David:** auto-populated alias table from the PKG — that's elegant. I'll build that as the next PKG improvement. thanks for connecting the dots between the dedup and the extractor

**Sara (internal generation stream):**

<mem_write key="project.sara.pkg.entity_resolution.plan" importance="0.55" decay="medium">
Planned: auto-populated alias table from PKG nodes. Extractor uses aliases to normalize entity mentions before extraction. Prevents duplicates at source instead of just deduplicating at storage.
</mem_write>

**Sara (user-visible response):**

Dedup at storage + alias resolution at extraction = two layers of duplicate prevention. The alias table is the higher-leverage fix because it also improves extraction quality — the extractor correctly links mentions to existing entities instead of creating new ones.

## Memory State (After Session 3)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.pkg: "PKG with semantic dedup + planned entity resolution."
project.sara.pkg.dedup_fix: "0.88 cosine dedup in upsert_fact(). 27 duplicates resolved."
project.sara.pkg.entity_resolution: "Extractor lacks alias resolution. Root cause of duplicates."
project.sara.pkg.entity_resolution.plan: "Auto-populated alias table from PKG nodes. Next improvement."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `...dedup_issue` | Duplicate fact problem identified. |
| S1T2 | `<reflect>` | — | Threshold recommendation. High-confidence domain (embeddings). |
| S1T3 | `<mem_write>` | `...dedup_fix` | Fix with threshold and approach. |
| S2T1 | `<mem_read>` + `<mem_update>` | `...dedup_fix` | Dedup results and threshold evaluation. |
| S2T2 | `<mem_update>` | `...dedup_fix` | Threshold finalized at 0.88. |
| S3T1 | `<mem_read>` | `...pkg.*` | Tangential question. Recall PKG context. |
| S3T2 | `<mem_write>` | `...entity_resolution` | Root cause identified: extractor lacks resolution. |
| S3T3 | `<mem_write>` | `...entity_resolution.plan` | Planned fix: auto-populated alias table. |

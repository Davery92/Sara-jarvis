## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.consolidation: "2x daily — 2PM and 9PM ET. Pattern extraction, calibration, emotional arc."
```

## SESSION 1

### Turn 1

**David:** added a third consolidation pass: PKG extraction. runs after the emotional arc summary at 9PM. it scans the day's conversations for new facts, entities, and relationships and pushes them to the knowledge graph

**Sara (internal generation stream):**

<mem_update key="project.sara.consolidation">
3x passes at 9PM ET (was 2x): pattern extraction, calibration, emotional arc, AND PKG extraction (new). PKG pass scans day's conversations for facts/entities/relationships and pushes to Neo4j knowledge graph. 2PM consolidation unchanged.
</mem_update>

**Sara (user-visible response):**

Third pass for PKG extraction at 9PM — that's the knowledge graph staying current automatically. The ordering matters: emotional arc before PKG extraction means the PKG pass can use the arc summary as context for extracting relationship nuances.

What triggers the extraction? Full conversation transcripts, or just the day's episode summaries?

### Turn 2

**David:** episode summaries. full transcripts are too noisy — the extractor pulls better facts from condensed summaries. also way faster, the whole PKG pass takes about 20 seconds vs 3+ minutes on full transcripts

**Sara (internal generation stream):**

<mem_write key="project.sara.consolidation.pkg_pass" importance="0.65" decay="medium">
PKG extraction pass: runs on episode summaries (not full transcripts). Summaries produce cleaner facts and run ~20 seconds vs 3+ minutes on full transcripts. Part of 9PM consolidation sequence.
</mem_write>

**Sara (user-visible response):**

Episode summaries as input is the right call — they're already distilled to the important facts, so the extractor isn't fighting noise. 20 seconds for a full day's PKG extraction is negligible overhead on the consolidation cycle.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.consolidation: "2PM: standard. 9PM: pattern extraction → calibration → emotional arc → PKG extraction."
project.sara.consolidation.pkg_pass: "Runs on episode summaries. ~20 seconds. Extracts facts/entities/relationships to Neo4j."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_update>` | `project.sara.consolidation` | New third pass added to 9PM consolidation. Architecture change. |
| 2 | `<mem_write>` | `...pkg_pass` | PKG pass details: input type, performance, function. |

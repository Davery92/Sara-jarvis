# Who writes David's world, and who reads it back

Date: 2026-09-10
Companion to: `SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md` (Phase 0, third deliverable)
Method: source audit of `backend/app`, plus a live replay of the eight 2026-09-09/10 exchanges
(`backend/tests/replay/`), which is how several of the entries below were found rather than assumed.

Phase 0 asks for the canonical source of each domain and every projection or cache that has to be
invalidated when a correction lands. This is that list. It is deliberately blunt about the places
where there is no canonical source, because those are where corrections go to die.

---

## 1. `episode` — the raw turn log

**Canonical for:** what was said, and when.

**Writers**

| Writer | What it writes | Notes |
|---|---|---|
| `main_simple.py` (chat turn) | `role='user'` + `role='assistant'` | Passes through `_strip_live_context()` so the injected `<live_context>` block never lands in David's stored words (Phase 1). |
| `routes/fitness.py` — food logging | `role='user'`, `source='fitness_food'` | **Synthetic.** "Logged snack: Protein Milk (2.0 1 serving) \| 320.0 cal" is a row David never typed. |
| `routes/fitness.py` — fitness chat | `role='user'` / `'assistant'`, `source='fitness_chat'` | A second chat path with its own persistence, not the shared boundary. |
| `routes/learning.py`, `services/task_result_delivery.py`, `services/nightly_dream_service.py`, `routes/memory.py` | assorted | Background writers; not on the chat path. |

**Readers (~30 modules)** — the ones that reach a prompt: `services/memory_recall.py`,
`services/recency_buffer.py`, `services/day_replay_builder.py`, `services/morning_brief_service.py`,
`services/personal_knowledge_graph.py` + `services/pkg_extractor.py` (fact extraction),
`services/daily_rhythm.py`, `services/importance_scorer.py`, `services/memory_compaction.py`,
`services/personality_engine.py`, `workers/subconscious_worker.py`.

**Gap found:** `memory_recall` renders `role='user'` as **"David said"** (Phase 2 attribution). For a
`source='fitness_food'` row that is false — nobody said it, a button was pressed. Attribution should
key off `source` as well as `role`.

**Gap:** no writer other than chat uses the `_strip_live_context` boundary, because it lives in
`main_simple.py` rather than in a shared persistence function. `routes/fitness.py` writes episodes
directly with raw SQL.

---

## 2. `conversation_turn` — the client-facing transcript

**Canonical for:** the ordered transcript a client re-renders, and its embeddings.

**Writer:** `main_simple.py` only (`ConversationTurn(...)`, twice — user and assistant), guarded by a
"same content as the latest turn?" check.

**Readers:** `routes/conversations.py` (the UI), `services/judge.py` (Mind V2), `services/daily_brief/
brief_service.py` + `moment_layer.py`, `services/autonomous_sweep_service.py`.

**Note:** `episode` and `conversation_turn` are two independent recordings of the same conversation,
written in the same function with different dedup rules, different id spaces and different timestamp
columns. Nothing reconciles them. `gotcha_episode_ordinal_dup_store` is the known symptom.

---

## 3. Daily-brief layers — **files, not rows**

**Canonical for:** the "moment / day / context / stable" narrative injected every turn.

**Storage:** `/home/david/jarvis/data/briefs/<user_id>/layers/{moment,day,context,stable}.md`, mounted
into the backend container at the same absolute path. `BRIEFS_DIR` is hardcoded in six modules
(`compiler.py`, `stable_layer.py`, `moment_layer.py`, `day_layer.py`, `context_layer.py`,
`status_tracker.py`) — four of which write.

**Writers:** `daily_brief/moment_layer.py` (per turn, via `update_moment`), `day_layer.py` (scheduled),
`context_layer.py`, `stable_layer.py` (bootstrap + periodic), `scheduler.py`.

**Readers:** `context_snapshot.get_extended_signals._daily_brief()` → `render_engaged_context`; also
`brief_service.get_compiled_brief` for other surfaces.

**Consequences for corrections:** a correction has to invalidate a **markdown file**, and there is no
mechanism that does. Phase 3's "mark the affected block stale and rebuild from primary evidence"
lands here, and it is the hardest of the stores because the layers have no per-claim structure.

**Found by replay:** the replay initially read the *live* layer files, which is also what any test or
shadow run would do. The harness now installs a fixture copy in a temp directory
(`harness.install_fixture_briefs`).

---

## 4. `world_brief` — the prose brief

**Canonical for:** "what's true in David's world right now", as injected into chat, judge and compose.

**Writer/reader:** `services/world_brief.py` alone — `sweep_brief()` rebuilds it, `get_rendered_brief()`
renders it. One table, one module, which is why it is the healthiest store on this list.

**Cache:** `world_brief:rendered:<user_id>` in Redis, TTL 120s. Nothing invalidates it on correction —
a correction is invisible for up to two minutes on every surface that reads the brief.

**Sources it projects from:** `calendar_event`, `world_thread`, email, `health_metric`, `workout_log`,
`background_task`. Ownership (`owner`, `owner_relation`) is now carried through (Phase 1).

---

## 5. Relationship state / the narrative about David

**Canonical for:** nothing. This is a projection that behaves like a source.

- `context_snapshot.get_relationship_state()` reads the newest `sara_journal` row with
  `entry_type='theory_of_david'` and injects it as "### What you understand about David".
  Suppressed past 72 hours (Phase 4).
- `sara_journal_service.write_theory_of_david()` writes it — **from the previous copy of itself**,
  plus `life_fact`, `behavioral_pattern`, `working_memory.stress_load` and `world_thread`.

**The loop:** document → prompt → document. A claim that enters once is re-attested every cycle with a
fresh timestamp and no fresh evidence. Phase 4 removed the stress substrate from *new* writes; the
stored paragraph still says "David maintains a low-stress equilibrium … his current stress signature
remains relaxed", and still seeds the next rewrite. **Reproduced in replay**
(`TestPersonalNarrative::test_the_narrative_does_not_assert_a_mood_as_settled_fact`, xfail).

**Cache:** the whole snapshot is cached in Redis for 20s (`_snapshot_cache_key`), and **nothing
invalidates it** — no writer anywhere in `app/` clears that key.

---

## 6. Knowledge-graph facts

Three stores, no single canonical one:

| Store | Writers | Readers |
|---|---|---|
| Neo4j PKG | `pkg_extractor.py`, `pkg_realtime_extractor.py`, `life_facts.py`, `consolidation.py`, `dreams.py`, `fact_verification.py`, `calendar_intelligence.py`, `reflection/agent.py`, `health_consolidation/runner.py` | `personal_knowledge_graph.query_semantic()`, `pkg_context_provider.py`, `main_simple.py:8148` |
| `pkg_embedding` (pgvector shadow) | `personal_knowledge_graph.upsert_fact()` (auto-embeds) | `memory_recall.recall_facts_prose()` → the `pkg` extended signal |
| `world_fact` (world model) | `services/world_state/reducer.py` | `services/world_state/context.py` |

Nine writers, three readers, no shared schema for provenance, and `gotcha_pkg_stale_shadow_confidence`
on record for the shadow drifting out of step. Health measurements are excluded by policy
(`project_health_data_accuracy`); `health_metric` is canonical for body numbers.

---

## 7. Corrections

| Kind | Store | Written by | Read by |
|---|---|---|---|
| Routine/schedule facts ("I leave at 7") | `life_fact` | `life_facts.detect_and_apply_correction()` (chat, pre-reply) | `get_life_facts_summary()` → prompt; `theory_of_david` substrate |
| Prohibitions ("don't do that") | `correction` (migration 151) | `corrections.apply_chat_prohibition()` (chat, pre-reply) | `main_simple.py` prompt block; `tools/fitness/food_search_log.py` |
| Retractions ("I removed it") | `correction` | `routes/fitness.py` on food-log delete → `record_food_log_retraction()` | same |
| Standing rules | `directive` | `routes/mind.py` | `directives.get_directives_for_context()` |
| Verification answers | `life_fact` | `verification_loop.py` | as above |

**Scope of what exists:** food-domain prohibitions and routine-time facts. The plan's other correction
kinds — event attendance, preference, temporary exception, retraction with an interval — have no
representation, and none of the five paths above invalidates any of the projections in §3, §4, §5 or
§6. `truth_maintenance.py` ages `life_fact` on its own schedule; that is the closest thing to
invalidation in the system.

---

## What has to be invalidated when a correction lands

In dependency order, worst first:

1. `sara_journal` `theory_of_david` — self-seeding, no dependency links, 72h expiry only. (§5)
2. Daily-brief `day.md` / `context.md` / `moment.md` — files, LLM-written, no claim structure. (§3)
3. `day_replay_cache.summary` — the nightly diary; written by `day_replay_builder.py`,
   `daily_log_service.py`, `pattern_detector.py`, `routes/daily_log.py`.
4. Redis `context_snapshot:<user>` (20s) and `world_brief:rendered:<user>` (120s) — no invalidation
   hooks exist; today a correction is stale-visible for up to two minutes.
5. `pkg_embedding` shadow rows for any superseded fact.
6. `world_fact` rows projected from the corrected event.

Every one of these is a projection. The primary evidence — `episode`, `calendar_event`, `food_log`,
`workout_log`, `health_metric`, `life_fact`, `correction` — is fine. The failures David sees are
projections that outlive the evidence they were built from.

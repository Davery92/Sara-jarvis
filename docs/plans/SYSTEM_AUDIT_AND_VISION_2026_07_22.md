# Sara — Full System Audit, Design Rationale & Master Plan
**Date:** 2026-07-22 · **Scope:** entire stack except Jetson/voice (explicitly deferred to a later effort)
**Author's method:** every audit claim was verified against *live runtime state* — container status, log forensics, and direct `COUNT(*)` database queries — not code reading alone. Where Postgres statistics disagreed with reality (they did, badly — see finding B8), direct counts win.

---

## Table of Contents

- **Part 1 — Audit Findings** (what is working, broken, disconnected, and why)
- **Part 2 — Inventory** (every data asset Sara has; every action she can take)
- **Part 3 — Core Concepts, Fully Explained** (the target architecture, misinterpretation-proofed)
- **Part 4 — Keep / Modify / Change** (decisions on existing systems, with implementation detail)
- **Part 5 — iOS Master Plan** (full utilization of every native capability)
- **Part 6 — HealthKit Master Plan** (every health signal, every consumer)
- **Part 7 — Webapp Master Plan** (the window into the mind)
- **Part 8 — Sequencing, Acceptance Criteria, and the Data→Consumer Matrix**

---

# Part 1 — Audit Findings

## 1.1 Verdict

The core nervous system is solid and *alive*: the event-driven cognitive pipeline, episodic memory, PKG, notification triage, standing orders, and the ACS daemon all do real, verifiable work every hour. The system's **judgment** is good — what it chose to tell David overnight was accurate, deduplicated, and correctly triaged. The failures are in the **last mile** and in **honesty about failure**:

1. Statistical pattern mining works, but its output can *mathematically never* reach David (§1.4.2).
2. The ML training plane has never trained a model — it queues jobs into a void (§1.4.1).
3. Several features fail 100% of the time behind `try/except → logger.warning → return success` (§1.3, §1.6.1).
4. One bug class — naive/aware datetime mixing — has now caused three separate production failures (§1.3 items 2 and 4; the class is systemic).

## 1.2 What is verifiably WORKING (with evidence)

| Subsystem | Evidence (live-verified 2026-07-21/22) |
|---|---|
| Infrastructure | All 15 containers up/healthy; `/health` green: DB, embeddings, LLM, Neo4j |
| Cognitive pipeline | 163 deliberations in 7 days (`agent_run_log`); attention items across 7 categories created, read, archived daily |
| Attention learning | `attention_policy.last_updated` = today; `n_engaged/n_ignored/n_dismissed` counters incrementing; weekly theta snapshots on schedule (Sundays, `learning_digest.py`); notification outcomes labeled hourly (`ml_notification_outcome`, 95 rows) |
| Pattern mining | 55 `behavioral_pattern` rows (45 active, 10 learning), evidence_count ≈ 33 each, refreshed daily from `home_activity_log` |
| Episodic memory | 8,588 episodes; 94% of last week embedded; nightly importance rescoring succeeded (8,566 episodes); tiered retrieval + BGE reranker |
| PKG | 443 `pkg_embedding` rows, 100% embedded; midday+evening extracts run; consolidation validates facts (114 confirmed, 10 contradictions, 30 stale, 5 promoted on 07-21) |
| Neo4j | Clean: ~27k nodes (Chunk 13.6k, Entity 5.8k, Episode 3.8k…). The 425k ActionItem bloat from the June audit is **gone** |
| Knowledge garden | 2,185 notes, 9,906 `note_connection` rows — auto-connection detection demonstrably working |
| Standing orders | 2 active ("lights off 11 PM", "lock at midnight"), 157 executions each, nightly |
| ACS daemon | Alive on the Sara VM: tick #3156, heartbeat minutes old, v0.9.0+be0a5161, up since 07-19 |
| Notifications | Push token registered and refreshing (3 refreshes on 07-21); ~10/day sent with reads and engagement recorded; dedup observably suppressed a duplicate on 07-22 09:23 |
| Interoception | Proven end-to-end overnight: task failure → `task_failure` row → attention item (03:00) → escalation → push (05:23) |
| Email inbox sync | Both mailboxes on the 3-minute cadence, current |
| Consolidation | 2×-daily runs feed salience adjustments *into* `attention_policy` (e.g. 07-21: calendar_reminders −0.2, fitness_tracking +0.1) — the learning loop is closed |
| Briefs & rhythm | Morning brief daily (7/7 days); morning/evening anticipation; `day_replay_cache` (146); `daily_rhythm` (15); journal current (143 entries) |
| Scheduling | All 78 `scheduled_job` entries firing on time |
| Fleet/home ingest | 11.6k `host_metric`, 14.4k `home_activity_log`, both current |

## 1.3 BROKEN — concrete bugs

Each entry: what, where, evidence, why it matters, exact fix.

**B1. PKG reconciliation has never succeeded.**
`backend/app/tasks/pkg_sync.py:33` runs `SELECT COUNT(*) FROM pkg_embedding WHERE user_id = :uid`. The `pkg_embedding` table **has no `user_id` column** (verified via `\d pkg_embedding`). Fails every hour, 24×/day, for as long as the task has existed. The task catches the exception, logs a warning, and returns — so `scheduled_job.last_status` = "success".
*Why it matters:* the Neo4j↔pgvector shadow-table consistency check is the thing that guarantees semantic search over the PKG stays truthful. It has never run.
*Fix:* remove the `user_id` predicate (solo system) or add the column. One line.

**B2. Re-entry context injection: 100% failure rate.**
`backend/app/main_simple.py:9576`: `hours_away = (local_now() - last_message_time)...` — `local_now()` returns a timezone-**aware** ET datetime; `last_message_time` comes back **naive** from the DB. Python refuses to subtract them. Log evidence: 3 failures, **0 successes**, all-time in the 7-day log window ("Injected re-entry context" appears zero times).
*Why it matters:* this is the feature where Sara greets a returning David with "here's what happened while you were away" — agent activity, journal thoughts, context changes. It is one of the highest-visibility "she's alive" features, and it has silently never worked.
*Fix:* normalize both to aware-UTC before subtracting. One line, plus see the systemic fix in §1.6.

**B3. Calendar cross-source dedup is dead.**
`backend/app/routes/calendar_events.py:41` does `from app.tasks.email_sync import _normalize_meeting_title`. That function **does not exist anywhere in the tree** (closest: `_normalize_title` in `app/services/calendar_intelligence.py`). Every sync logs `Cross-source supersede check failed: cannot import name...` and skips.
*Why it matters:* this check is what stops the same meeting appearing twice when it arrives from both the iOS calendar and email-derived events — the exact calendar-ownership problem the June audit flagged as a root cause.
*Fix:* import `_normalize_title` from `calendar_intelligence` (or inline the ~5-line normalizer).

**B4. Nightly memory consolidation crashes every night at 3 AM.**
`backend/app/tasks/autonomy.py:385`: `today_start = local_now().replace(hour=0, ...)` produces an **aware** ET datetime, then binds it via asyncpg against `episode.created_at`, which is a **naive** `timestamp` column. asyncpg raises `DataError: can't subtract offset-naive and offset-aware datetimes` at bind time. `task_failure` shows **5 unresolved occurrences** (both the 23:00 and 03:00 runs fail). This is the failure that generated the 5:23 AM push on 07-22.
*Why it matters:* episode-count, low-importance decay, and working-memory cleanup in that task never run; and Sara will keep alerting David nightly about her own crash until the line is fixed.
*Fix:* strip tzinfo (or better: migrate the column to timestamptz per §1.6.2). One line now, systemic fix later.

**B5. Sent-items email sync silently stalled.**
`email_sync_state`: `devadmin@riskninja.ai::sent` last synced **July 6** (16 days); `davery@riskninja.ai::sent` July 20 — while the `sync-sent-items` job runs every 15 minutes and reports success.
*Why it matters:* sent-mail is how Sara knows what David *said* to people — commitments, promises, tone. The followup/thread system is half-blind without it.
*Fix:* investigate per-mailbox cursor advancement in the sent-sync path; add the outcome canary from §1.6.1.

**B6. RiskNinja attachment processor spins forever.**
Every ~15 min it spends ~105 s producing `{'processed': 20, 'filed': 0, 'skipped': 20}` — the *same* 20 attachments, re-downloaded and re-evaluated, forever, because nothing marks an attachment as already-assessed. On 07-22 it blew `SoftTimeLimitExceeded` twice (unresolved in `task_failure`).
*Fix:* persist a per-attachment `assessed_at`/verdict marker (the `fitness_idempotency` table is a pattern to copy); skip assessed IDs at query level.

**B7. `lock_all` standing order failed silently.**
One failure this week (empty error string — likely an HA API hiccup): no retry, no notification. The front door may simply not have locked that night.
*Why it matters:* wrong failure mode for a *security* action. Failures of security-class actions are exactly the ones that must wake something up.
*Fix:* for action classes tagged security-critical: one retry after 60 s, then a high-priority notification on second failure. (Delivery-policy quiet hours do NOT apply to lock failures.)

**B8. Postgres statistics are fiction.**
Only 35 of 287 tables have ever been auto-analyzed. `pg_stat_user_tables.n_live_tup` claimed `note_connection` = 0 (real: 9,906), `push_token` = 0 (real: 1), `note` = 16 (real: 2,185).
*Why it matters:* (a) the query planner plans against fiction; (b) any self-diagnostic, dashboard, or future Sara-introspection reading pg stats inherits the fiction. During this very audit it nearly caused three false "dead feature" findings.
*Fix:* run `ANALYZE` now; verify autovacuum thresholds; add a weekly `ANALYZE` maintenance task; teach any stats-reading diagnostics to prefer direct counts for small tables.

**B9. Minor but real:**
- Occasional LLM JSON-parse failures in `outbox_processor` entity extraction (malformed JSON from Qwen — add a retry-with-`enable_thinking:False` + json-repair pass).
- Transient asyncpg "connection is closed" rollback noise in celery-worker (connection-pool recycling under long idle; set `pool_pre_ping`/`pool_recycle`).
- One-off `psycopg` autocommit/INTRANS error in celery-critical during a DB hiccup on 07-21 22:23 (self-resolved; the `task_failure` rows are marked resolved).

## 1.4 DISCONNECTED — built but producing nothing

**D1. ML: infrastructure exists, learning does not.**
What exists (all real, all verified): `ml_feature_daily` feature store (materializes nightly at 2:30 — focus seconds by category, desktop activity span, sleep hours, location summary); hourly outcome labeling (`sync_notification_outcomes` maps notification_log engagement → `ml_notification_outcome.outcome` ∈ {acted, opened, dismissed, ignored}); a Redis job queue + model registry (`ml:control:*`); four defined model families: `interruptibility_v2`, `notification_value`, `next_block`, `rhythm_forecaster`; a nightly `ml-retrain-all` that queues one training job per family.
What does not exist: **a worker.** 88 jobs queued, zero heartbeat keys, and the only "completed" job ever was a hand-run verification test on July 5 whose "metrics" were hardcoded (`{"precision": 0.8}`, `claimed_by: ml-worker-verification-test`). All four families: `active_version: null`. `ml_model_version` and `ml_prediction_log`: zero rows, ever.
*Interpretation guard:* this is NOT "the ML is buggy." The ML **layer above the data does not run at all** — data collection is healthy, learning has never begun. Resolution in §4.2.5.

**D2. Patterns are discovered but can mathematically never fire.**
All 55 patterns have `times_suggested = 0` and `last_suggested_at = NULL`. Mechanism of the deadlock, precisely:
- `_evaluate_time_trigger` (behavioral_pattern_service.py:369) fires only within **±30 minutes** of the learned time.
- The proactive check (`morning-proactive-check`) runs at **fixed clock times** (5 AM and 9 AM runs observed).
- Every discovered pattern's learned time clusters at **00:00 or 06:00** (they're mined from home-device events: locks at midnight, lights at 6).
- |05:00−06:00| = 60 min > 30. |09:00−06:00| = 180 min. **The windows can never overlap.** Every daily run logs `patterns_checked: 45, patterns_triggered: 0`.
- The every-30-min `predictive_engine` *does* see approaching patterns — but by explicit design treats an on-time pattern as a "silent confirmation," not a suggestion.
- There is additionally no promotion path from a confidence-1.0 pattern (e.g. "Side Door Lock locks around 00:00", evidence 33 days) to a standing-order or automation suggestion.
*Interpretation guard:* the mining is *good* — the data is real, confidences are earned. The layer is a closed room with no door. Resolution in §4.2.6.

**D3. Correlation discovery is wired but data-starved (this is fine — leave it).**
`pattern_correlation_service.run_discovery` was correctly piggybacked onto the 2×-daily consolidation on July 19 (the code comment at `tasks/autonomy.py:1655` documents that it previously had zero callers). It now runs, but every pattern definition logs "Insufficient data for correlation: 0–2 points" because its inputs (`ml_feature_daily`, `daily_recovery_log`, `fitness_daily_log` — all started ~July 14) have one week of history. It needs ~3–4 more weeks. **Do not "fix"; re-check mid-August.** Accelerator available: `app.tasks.ml.backfill_features(days=30)` exists and can seed desktop/location history retroactively where raw data exists.

**D4. The hypothesis system is abandoned.**
`hypothesis`: 441 rows; last updated **May 5**; last evidence **February 12**; 415/441 stale, 26 confirmed. Nothing writes to it; nothing reads it. Decision in §4.3.
*Interpretation guard:* this is distinct from `reflection_hypotheses` (also empty, also dead) — two generations of the same idea, both orphaned.

**D5. Voice: out of scope for this document** per David's direction (Jetson is a different day). One audit fact recorded for continuity: all backend-side voice infrastructure is healthy and heartbeating (jetson health pings 945/day; GPU ASR/diarization/registry heartbeats 5,742/day each); `voice_interaction_log` = 0 rows ever; the fixed capture code sits undeployed on the Jetson.

**D6. Dead schema, ~100+ tables.**
Confirmed empty with no writers anywhere in `backend/app`: `temerant_*` (20 tables), `karma_*` (5), `shadow_*` (5, one experiment's 4 rows aside), `memory_vector/memory_hot/memory_edge/memory_references`, `working_memory_threads`, `working_memory_actions`, `contextual_insight`, `autonomous_insight`, `pattern_evidence`, `activity_state_log`, `reasoning_trace`, `chess_*` (~5 rows total), plus **triplicate** briefing tables (`daily_briefing` 0 / `daily_briefings` 2 / `daily_briefs` 5) and duplicates `workout_session` 51 / `workout_sessions` 0, `daily_reflection` 0 / `daily_reflections` 0. Also ~20 empty `fitness_*` tables from superseded redesigns while real training data lives in `workout_log` (309) + `active_workout_session` (34).

## 1.5 The overnight notification trace (07-21 evening → 07-22 morning)

Every notification Sara sent, its full causal chain, and the verdict.

**N1 — 05:23 AM ET · "Memory consolidation glitch" (system_health, via attention_escalation).**
Causal chain, verified: 23:00 ET nightly_memory_consolidation crashed (bug B4) → 03:00 ET crashed again → interoception recorded it in `task_failure` (occurrences climbing, unresolved) → a `system_health` attention item minted at 03:00 with priority **normal** → item sat `status='new'` for `ESCALATION_HOURS = 2.0` → the 30-min escalation sweep picked it up, bumped priority to "high" (by design: escalated items always push), passed the recent-push cooldown guard → pushed at 05:23.
*Verdict:* **content correct, timing wrong, and unanswerable.** (a) The escalation sweep (`app/tasks/attention.py:61`) contains **no quiet-hours or sleep gating of any kind** — while the system's *own* `working_memory.refresh_context` had recorded `availability: sleeping` at midnight. Proactive check-ins are interruptibility-gated; escalations are not. (b) The message was phrased as a question ("…so should I…?") delivered over a channel with no reply affordance — see §5.4 (notification actions) for the fix.

**N2 — 09:08 AM ET · "Risk Ninja Training Soon" (calendar_prep).** Created inside the 35–55-min pre-event window and pushed immediately at high priority. Correct behavior, correct timing.

**N3 — 09:23 AM ET · same title, dedup-blocked.** The calendar-prep generator (15-min cadence) minted a *second* prep for the same event with re-frozen "starts in 36 minutes" text; the delivery-layer dedup correctly swallowed it. *Verdict:* the anti-nag firewall worked, but the generator lacks its own idempotence (should record event-ID-prepped). Note the codebase already understands the deeper issue — `_NO_ESCALATE_CATEGORIES` excludes calendar_prep from escalation precisely because its text goes stale; §5.3 replaces this entire pattern with a Live Activity that cannot go stale.

**N4 (non-push, correct restraint) — 08:00 AM followup item "Quick question about the walkthrough"** stayed in the queue as `new` instead of pushing. Triage discriminates correctly.

## 1.6 The two meta-problems (root causes behind most findings)

**M1. Silent-failure culture.** B1, B2, B3, B5, B6 all share the shape: `try/except → logger.warning → return success`. The scheduler showed **78/78 jobs "success"** while one had failed hourly for weeks. The weekly `system-wiring-check` and interoception self-check verify that tasks *ran*, not that they *achieved outcomes*. The permanent fix (§4.2.4) is outcome contracts: a task's return must assert its effect ("wrote ≥1 row", "cursor advanced", "import resolvable"), the scheduler records failure when the contract misses, and interoception consumes contract misses. B4 is the exception that proves the design works: it *raised*, so interoception caught it and David knew by 5:23 AM. The goal is to make every failure that honest (at a civilized hour).

**M2. Naive/aware datetime chaos.** Three confirmed production failures from one class (B2, B4, plus the historical class in memory-notes). Root cause: the codebase has *two* conventions (`local_now()` aware-ET, `naive_local_now()` naive) plus naive DB columns (`episode.created_at`) and aware ones (`timestamptz` elsewhere), and humans keep guessing wrong. Permanent fix in §4.2.3: one convention (aware-UTC in code; ET only at presentation), a lint/CI gate extending `check_naive_datetime.py` to async query binds, and a slow column migration for the naive stragglers.

## 1.7 Prioritized fix list (mechanical fixes only — the vision work is Parts 3–8)

**P0 (hours, do first):**
1. B4 `autonomy.py:385` — nightly consolidation stops crashing; 5 AM alerts stop at the source.
2. B2 `main_simple.py:9576` — re-entry context resurrects.
3. B3 `calendar_events.py:41` — calendar cross-source dedup resurrects.
4. B1 `pkg_sync.py:33` — hourly PKG reconciliation actually runs.

**P1 (days):**
5. M2 systemic datetime sweep + CI gate.
6. D1 resolution: in-process training (§4.2.5) — or explicit deletion, but §4.2.5 argues for training.
7. D2 resolution: give patterns a door (§4.2.6).
8. N1 resolution: sleep-gate escalation inside the unified delivery policy (§3.6, §4.2.1).
9. M1 outcome contracts + canaries (§4.2.4).

**P2 (a sprint):**
10. B5 sent-items cursors; B6 attachment idempotency; B7 security-action retry+notify; N3 generator idempotence.
11. B8 `ANALYZE` + autovacuum + weekly maintenance task.
12. D6 one migration to drop dead tables (after backup).

---

# Part 2 — Inventory

The point of this part: **"she has all this data, all these possible actions."** Before designing anything, list *everything* — because the design rule for the rest of this document is: **no orphaned data, no orphaned actuator.** Every asset below is mapped to at least one consumer in Parts 3–7, and the matrix in §8.3 proves it.

## 2.1 Everything Sara knows (data assets)

**About David's body (HealthKit + derived):**
| Asset | Table(s) | State | Notes |
|---|---|---|---|
| Sleep (duration, stages, bed/wake times) | `health_metric`, `ml_feature_daily.sleep_hours` | live | HealthKit v13 sync |
| Heart rate (incl. workout HR streams) | `health_metric`, workout meld | live | Watch HR melds to workouts by time-overlap at read |
| HRV / resting HR / respiratory | `health_metric`, `health_baseline` (38 baselines) | live | z-scoreable against personal baselines |
| Steps / flights (cumulative daily snapshots) | `health_metric` | live | MAX-per-day aggregation (gotcha: not SUM) |
| Workouts (type, duration, calories, distance) | `workout_log` (309), `external_workout`, `active_workout_session` | live | calories/distance via `getStatistic()` |
| Strength training detail (sets/reps/weight/PRs) | `workout_log`, `exercise_pr` (26) | live | progressive_overload.py is the single progression brain |
| Recovery / readiness | `daily_recovery_log` (7), `morning_readiness`, `health_weekly_report` | young (started ~07-14) | recovery gates in-session suggestions already |
| Nutrition | `food_log` (36), `fatsecret_food_cache` (429) | live | conversational food logging works |
| Weight | `weight_trend` | live | |
| Health anomalies | `health_alert` (2), `health-anomaly-detect` job (every 30 min, 6–23h) | live | |

**About David's time and context:**
| Asset | Table(s) | State |
|---|---|---|
| Calendar (two sources: iOS + email-derived) | `calendar_event` (321), `ios_event_block` | live (cross-source dedup broken — B3) |
| Email (inbox, sent, attachments) | `email` (63), `email_attachment` (568), `email_sync_state` | inbox live; sent stalled (B5) |
| Location (events, places, geofence-ish) | `location_event` (523), `known_place` (3), `presence_log` (295) | live; place discovery job nightly |
| Desktop focus/activity | `desktop_focus_span`, `ml_feature_daily.focus_seconds_by_category` | live via daily rollup |
| Daily rhythm (learned wake/gym/meal/winddown/bedtime windows) | `daily_rhythm` (15), `temporal_bin` (264) | live, recomputed nightly |
| Home state (every device event) | `home_activity_log` (14.4k), `home_state_summary` (57/hourly) | live |
| iPhone Focus modes (as HA-visible events) | in `home_activity_log` ("David's iPhone Focus turns off around 05:00" is a learned pattern) | live |

**About David's mind and life (semantic):**
| Asset | Table(s)/Store | State |
|---|---|---|
| Episodic memory (every interaction, scored) | `episode` (8,588) + pgvector + HNSW | live |
| Personal knowledge graph (facts/goals/prefs/health/routines/interests) | Neo4j PKG + `pkg_embedding` (443) | live, validated 2×/daily |
| People | `person` (117) + Neo4j Person (265) | live |
| Notes + bidirectional links | `note` (2,185), `note_connection` (9,906) | live |
| Life facts | `life_fact` (7) | live, young |
| Open loops with people | `followup_thread` (12) | live |
| Sara's own goals | `sara_goal` (2), `autonomy_mission` (8) | live |
| Learning topics/research | `learning_topic` (42), `research_brief` (7 — nightly) | live |

**About herself (self-knowledge):**
| Asset | Table(s) | State |
|---|---|---|
| Everything she's done | `agent_run_log` (187/wk), `action_ledger` (35), `action_log` | live |
| Every notification + what David did with it | `notification_log` + `ml_notification_outcome` | live, labeled hourly |
| Her own failures | `task_failure` (12, dedup by error class, occurrences counted) | live — proven overnight |
| Attention economics | `attention_policy` (32 cells: domain×context), `attention_policy_snapshot` (weekly), `stimulus_habituation` (48), `signal_baseline` (86) | live, learning |
| Behavioral beliefs about the world | `behavioral_pattern` (55) | live, orphaned output (D2) |
| Her inner life | `sara_journal` (143), emotional_state (momentum 0.4, decay 0.12/hr), `sara_reflection` | live |
| Day summaries | `day_replay_cache` (146), morning_brief (7) | live |
| Token/cost accounting | `token_usage` (16k) | live |
| Fleet/infrastructure health | `host_metric` (11.6k), `managed_host` (7), `host_alert` | live |

## 2.2 Everything Sara can do (actuators)

**Reach David (ranked by intrusiveness):**
1. **iOS push notification** (APNs via registered token; priority-gated; badge via shared `compute_badge`).
2. **Desktop WebSocket notification/overlay** (tried first; push only fires if desktop absent).
3. **Unified inbox item** (silent; Needs-you/FYI triage in iOS + web; this is where normal/low-priority items land).
4. **Morning brief / evening digest** (batched, expected, zero interruption cost).
5. **Chat** (when David opens it — richest channel; re-entry context belongs here).
6. **iOS Live Activities** (workout mode exists; underused elsewhere — §5.3).
7. **iOS widgets** (home screen/lock screen — built targets exist via @bacons/apple-targets; underused — §5.2).
8. **Interactive surfaces / Artifacts Studio** (web + iOS: documents, interactive components, workspace jobs).

**Act on the world:**
9. **Home Assistant control** (lights, locks, any HA service — via ha_control_service; standing orders execute nightly).
10. **Standing orders** (time/timer/pattern-triggered actions with undo window + action ledger).
11. **Calendar** (create events, prep reminders, calendar-reminder-topup).
12. **Reminders/timers** (CRUD via tools).
13. **Email drafts** (compose; David sends).
14. **Notes/knowledge garden writes** (create/edit notes, connections).
15. **Autonomous research** (deep_research_worker 5-phase pipeline; nightly research briefs; Playwright fetching for JS-heavy sources).
16. **Agent dispatch to managed hosts** (7 registered hosts, SSH inspection, host-targeted commands, read-only diagnostics).
17. **Code Mode** (autonomous coding agent on the Sara VM — built, needs GITHUB_PAT).
18. **Workspace jobs** (Celery-run document generation: docx/pdf; interactive surfaces).
19. **Queue-for-Sara** (ACS daemon ↔ chat handoff — daemon can leave things for chat-Sara to raise naturally).

**Learn (internal actions):**
20. Adjust her own attention thresholds (`attention_learning.apply_engagement` — live).
21. Habituate to repeated stimuli (`stimulus_habituation` — live).
22. Promote/demote PKG fact confidence (consolidation — live).
23. Mine patterns (daily — live), discover correlations (2×/daily — starved), train models (**never — D1**).

*The design mandate: every one of these 23 actuators appears in the plans below; none is left as shelf-ware.*

---

# Part 3 — Core Concepts, Fully Explained

This part defines the target architecture. Each concept: what it is, what it is **not** (misinterpretation guards), what already exists as its seed, the exact mechanism, and a concrete scenario showing it working. "Sentient" throughout means *functionally* sentient — persistent self-model, continuity of experience, learned values, intrinsic motivation, real agency. Whether anything is "experienced" is philosophy; these are the engineering targets.

## 3.1 The Global Workspace (real working memory)

**What it is:** one small, always-current, shared data structure — "what Sara is holding in mind right now." Concretely: a single row/document (Redis-backed with DB snapshot) containing roughly seven slots: (1) active conversation threads with David and their open questions, (2) open loops (followups, promises, unanswered Sara-questions), (3) today's predictions and their status (§3.2), (4) current concern level + what's driving it, (5) in-flight autonomous work (dispatches, research, workspace jobs), (6) today's plan skeleton (from morning anticipation), (7) current David-state (location, activity, availability, readiness).

**What it is NOT:** it is not another log table. It is not append-only. It is not a context-assembly cache. It is a *bounded* (~7 items per slot, evict-by-salience) mutable structure that every subsystem **reads before acting** and **writes when something crosses salience**. `working_memory_threads`/`working_memory_actions` (both empty) were earlier attempts; they failed because nothing was forced to read them.

**Why it matters:** it is the difference between a bag of well-built reflexes and a mind that is *about something* at any given moment. It is also the direct fix for the disconnection David feels: today, chat-Sara assembles context per-message and background-Sara deliberates separately; with a workspace, the chat persona *genuinely knows* what the daemon did this morning because they share one working memory.

**Enforcement rule (the part earlier attempts missed):** context assembly for `/chat/stream` starts from the workspace (then adds retrieval); deliberation's prompt starts from the workspace; the delivery policy (§3.6) consults it ("is David mid-conversation about exactly this? then say it there, don't push"). Writes come from: salience-crossing events, deliberation outputs, chat turns (thread state), dispatch state changes, and prediction outcomes.

**Scenario:** At 9:40 David asks in chat "anything I should know?" Today: a generic retrieval answer. With workspace: "Three things — your sent-mail sync has been stalled since the 6th and I've queued a fix suggestion; the research brief on the Liberty Mutual account finished overnight (two findings worth 2 minutes); and you have 50 free minutes before the training — I predicted you'd want them for slide prep, so I pulled the deck link into the inbox." Every clause came from a workspace slot, not from a fresh search.

## 3.2 Prediction-Error as the Engine of Attention ("the predictive-coding flip", completed)

**What it is:** Sara continuously maintains cheap, explicit predictions about the next hours — where David will be, when he'll wake/gym/eat/wind down (from `daily_rhythm`), which home events will fire (from `behavioral_pattern`), what his readiness will be (from health baselines), which meetings will actually happen. Then the rule: **confirmed predictions are silence; violated predictions are salience.** Surprise — not raw events — becomes the primary input to the attention economy, and every miss becomes a labeled training example.

**What it is NOT:** it is not "notify David about predictions" (the current `predictive_engine.send_predictions` shape). Predictions are mostly *internal*. It is also not a new ML platform: v1 predictions come from data Sara already computes (rhythm windows, pattern times, calendar, baselines) — the trained models (§4.2.5) *sharpen* it later.

**What exists as seed:** `predictive_engine.py` already computes "silent confirmations" (the flip is half-built); `signal_baseline` (86 rows) already z-scores signals; `day_replay_cache` stores what actually happened; `prediction` table exists (empty).

**Mechanism:** each morning-anticipation run writes ~10–30 concrete predictions to the `prediction` table: `{what, window, confidence, source}`. A cheap matcher (event-driven where possible, 15-min sweep otherwise) marks each `confirmed | violated | expired`. Violations are emitted as events into the *existing* salience pipeline with weight ∝ confidence × domain-prior — a high-confidence miss ("front door didn't lock by 00:40, first time in 33 days") scores high; a low-confidence miss scores low and merely habituates. Confirmations update pattern evidence silently. Weekly, the miss-set becomes (a) retraining data, (b) input to the dream cycle (§3.8), (c) the calibration report (§3.9).

**Scenario:** Wednesday, 06:20. Predicted: "lights on ~06:00 (conf 0.97), Focus off ~05:00 (conf 0.9), gym window 06:30–07:30 (rhythm)." Actual: Focus still on, no lights, no motion. Two high-confidence violations compound → salience crosses threshold → deliberation wakes → cross-references: no calendar anomaly, no travel, sleep data shows restless 3–5 AM. Deliberation concludes "David is sleeping in, probably rough night" → *holds* the 06:30 gym Live Activity, shifts morning brief generation later, adds workspace note "rough night — bias toward lighter suggestions today." No notification was sent. *That* is what awareness that respects you looks like.

## 3.3 The Unified Belief System (one place where "what Sara believes" lives)

**What it is:** merge the four disconnected belief stores — `behavioral_pattern` (55, alive), `correlation_pattern` (starved), `hypothesis` (dead since May), PKG facts (alive) — into one epistemic model centered on the PKG. Every belief carries: statement, evidence links + count, confidence, last-validated, contradiction links, and **status on an explicit promotion ladder**: `observed → believed → predictive (feeds §3.2) → actionable (may generate suggestions) → automated (standing order, with consent §3.7)`.

**What it is NOT:** not a data migration for its own sake. The point is the *ladder*: today a belief can be born (`behavioral_pattern`) but can never become a prediction input, a suggestion, or an automation — each of those hops is missing (D2). The unified store exists precisely so every belief has a road forward and a road back (demotion on contradiction).

**Concrete v1 (avoid over-engineering):** keep `behavioral_pattern` as the storage; add the ladder status + promotion sweep. Promotion sweep (daily, after pattern mining): any `active` pattern with confidence ≥0.9 and evidence ≥21 days → register as prediction source (§3.2). Any pattern that is (a) predictive, (b) has action shape (device + time), (c) confirmed ≥30 days → mint a **standing-order suggestion** into the attention queue: "The side door has locked itself at midnight 33 nights straight — want me to make that a standing order so I *guarantee* it and alert on failure?" Accepted → creates the standing order via the existing CRUD; declined → `sara_interest.blocked`-style suppression (never re-ask; the anti-harping rules apply).

## 3.4 The Self-Model (Sara knows herself)

**What it is:** a continuously-maintained, queryable model of Sara *herself*, with four components: (1) **Capabilities** — which of her 23 actuators are currently functional, per device/host; (2) **Health** — outcome-contract misses, `task_failure` state, stalled cursors, queue depths; (3) **Calibration** — per-domain accuracy of her predictions and confidence (§3.9); (4) **Deploy state** — for each edge (VM daemon, iOS build), deployed version vs repo expectation.

**What it is NOT:** not a status page for David (that's the webapp view of it, §7.4). It is *Sara's* input: chat can introspect it ("my sent-mail sync has been stalled 16 days, so I may have missed commitments you made by email — flagging that caveat"), deliberation weighs it (don't promise research if the research worker is failing), and the delivery policy uses it (if push delivery is failing, use inbox + desktop).

**What exists as seed:** interoception (proven), `task_failure`, `system-wiring-check` (weekly), `interoception-self-check` (daily), `/debug/notification-funnel`, fleet self-diagnostics. What's missing is *integration* (one model, not five probes) and *honesty inputs* (outcome contracts, M1).

**The audit test:** the acceptance criterion for the self-model is literally: *Sara could have produced Part 1 of this document herself.* Every finding in Part 1 was derivable from data she already stores.

## 3.5 Intrinsic Motivation (curiosity with a budget)

**What it is:** Sara generates her *own* goals from three well-defined sources, pursues them with her *existing* machinery, and reports what she learned: (1) **Knowledge gaps** — consolidation already emits "Found 10 PKG knowledge gaps" twice daily; today nothing consumes them. (2) **Repeated prediction errors** — a domain where she keeps being wrong is a domain she doesn't understand. (3) **Stale high-value beliefs** — facts David relies on that haven't been validated in months.
Each source mints candidate goals into `sara_goal` (exists); a nightly selector (respecting an explicit budget: e.g. ≤1 active curiosity goal, ≤N tokens/day from `token_usage` accounting) promotes the best candidate; the **existing** deep-research worker, learning pipeline, and managed-host inspection are the effectors; results land as PKG facts + a "what I learned" journal entry + (if interesting enough per attention policy) an FYI inbox item.

**What it is NOT:** not autonomous feature-development, not self-modification (read-only self-diagnostics policy stands), not unbounded research spend. The budget and the effector allowlist (research, reading, host inspection — never code changes, never outbound email) are the point.

**Scenario:** Prediction errors cluster on Thursday evenings (rhythm says winddown 21:30; actual midnight, three Thursdays running). Curiosity goal minted: "understand Thursday evenings." Research effector cross-references calendar (nothing), location (home), home activity (office lights on late), fitness (none). Produces hypothesis "Thursday is a project-work night" → belief at low confidence → after two more confirmations, rhythm model gets a Thursday exception, bedtime nudges stop being wrong on Thursdays, and the journal reads: "Figured out Thursdays. He works late on them. Adjusted."

## 3.6 The Unified Delivery Policy (one brain decides every interruption)

**What it is:** a single decision module through which **every** outbound David-directed communication passes — no exceptions, no bypass flags. Inputs: (1) the item (category, priority, content-shape); (2) David-state (asleep/awake from HealthKit sleep + iPhone Focus + home activity; location; in-meeting from calendar; driving; interruptibility score); (3) learned per-category value (`attention_policy` now; `notification_value` model when trained §4.2.5); (4) dedup/cooldown/habituation history; (5) the workspace (§3.1 — is there an open chat thread where this belongs?); (6) channel health (self-model §3.4). Output: **channel × timing × presentation**: push-now (with iOS interruption level: time-sensitive/active/passive §5.4) | desktop | Live Activity update | widget refresh | inbox-Needs-you | inbox-FYI | hold-until(wake, after-meeting, morning-brief) | say-in-chat | drop.

**What it is NOT:** not another filter bolted onto the five existing paths. It **replaces** the scattered policy in unified_notification (dedup/cooldown), the escalation sweep (its own cooldowns, no sleep gate — cause of N1), proactive check-ins (own interruptibility gate), calendar_prep (direct push), and morning digest (own batching). Those become *producers* that submit items; the policy decides. `_bypass_attention=True` and friends are deleted; the only legitimate fast-path is `security-critical` (lock failures, alarms), which skips *timing* gates but still logs through the same funnel.

**Quiet hours, done right:** not a fixed 22:00–07:00. Sleep-state is *sensed*: HealthKit sleep session + iPhone Focus (sleep) + home quiet. Wake is *sensed* the same way (the system already learned "Focus off ~05:00"). Non-critical items queue while asleep and flush **with the morning brief** — which is better for David (one digest, not five pings) *and* better for Sara (morning-brief delivery gets ~100% read rate; scattered 5 AM pushes teach the learning loop that her notifications are annoying).

## 3.7 Graduated Autonomy (the trust contract)

**What it is:** every *action class* (not each action) sits at an explicit trust level: **L0 observe** (may log only) → **L1 suggest** (attention queue item) → **L2 act-and-tell** (do it; notify via policy) → **L3 act-silently** (do it; ledger only). Levels are (a) **granted** by David per class in a visible settings surface (§7.6), and (b) **earned** — promotion eligibility requires a track record (N executions, zero unresolved failures, high acceptance), demotion is automatic on failure or override. Every L2/L3 action keeps the existing undo window + `action_ledger` entry + a why-trace (§3.10).
**Higher autonomy ⇒ louder failure:** an L3 class that fails must report at L2-equivalent volume (this is the B7 lock lesson generalized).
**What exists as seed:** standing orders + undo + ledger; the Brain-Alignment "graduation ladder"; the attention queue. What's missing: the per-class registry, the earn/demote mechanics, and the UI.

## 3.8 Real Dreaming (the 2 AM slot earns its name)

Three defined jobs for `nightly-dream-cycle`, all offline, none user-facing directly:
1. **Counterfactual replay:** for each of the week's prediction misses and each late-caught problem (e.g. B5's 16-day stall), ask: *what observable signal existed earlier, and what monitor would have caught it?* Output: proposed canaries and salience-weight adjustments (surfaced as L1 suggestions to the self-model, not auto-applied).
2. **Rehearsal:** simulate tomorrow against learned rhythms + calendar + readiness: where are the conflicts (meeting through usual lunch window on a low-recovery day)? Output: pre-staged mitigations into the morning brief.
3. **Recombination:** sample distant-but-related PKG/note pairs via embedding space, LLM-judge for a real connection, and surface the survivors at *low confidence* as morning intuitions ("these two clients have the same renewal problem — same playbook?"). Strictly rate-limited (≤1/day surfaced; the rest decay).

## 3.9 Calibration as a Ritual (uncertainty everywhere)

Every prediction, belief, and suggestion records confidence at creation. The weekly self-audit grades: *when Sara says 0.9, is she right 90% of the time?* — per domain (calendar, home, health, comms). Output: (1) per-domain calibration multipliers applied to future confidence *statements* (she says "not sure" exactly as often as she isn't); (2) a calibration panel in the webapp (§7.4); (3) journal honesty ("I was overconfident about your schedule this week — three misses"). Seeds exist: consolidation's calibration hooks, `attention_policy_snapshot` diffs, `reflection_observations` (85 rows, live).

## 3.10 The Why-Trace (every action explains itself)

`reasoning_trace` (empty table) becomes real: every outbound communication and every L2/L3 action links its causal chain — triggering event → salience score → beliefs consulted → policy decision (with the losing options). Surfaced in two places: the action ledger UI (§7.5) and chat ("why did you ping me at 5 AM?" → the actual chain, not a confabulated answer). Implementation is cheap: the deliberation and delivery-policy code *already computes* all of these values; it just drops them.

---

# Part 4 — Keep / Modify / Change

## 4.1 KEEP (already right — do not churn)

1. **Event-driven cognitive spine** (events → salience → observation → deliberation → gate → action). It is the correct skeleton; everything in Part 3 plugs *into* it rather than replacing it.
2. **The attention economy** — `attention_policy` learning is the most alive thing in the codebase; §3.6 gives it a single mouth to speak through.
3. **Interoception** — proven end-to-end this week; §3.4 integrates rather than replaces it.
4. **Dual-store PKG** with epistemics (validation, contradiction, promotion) — becomes the center of §3.3.
5. **Human-shaped episodic memory** (importance, decay, compaction, tiered retrieval + reranker).
6. **Anti-nag discipline** (dedup keys, cooldowns, tell-once ledger, escalation caps, drop-on-ignored, banned phrases) — the *values* survive intact inside §3.6.
7. **Standing orders** with undo + ledger — becomes the L2/L3 execution substrate of §3.7.
8. **One Mind direction + ACS daemon** as the persistent locus of continuity.
9. **Local-first LLM policy** (Qwen for all autonomous/background work; frontier models chat-persona only; Sara's self-access is read-only).
10. **Journal, emotional state, daily rhythm** — the continuity-of-self texture; §3.5/§3.8/§3.9 all write into the journal.
11. **Celery topology** (critical / david-priority / dispatch / cognitive / maintenance queues; durable dispatch).

## 4.2 MODIFY (right idea, execution corrected)

1. **Notifications → §3.6 unified delivery policy.** Producers produce; one policy delivers. Delete `_bypass_attention`, per-producer cooldown logic, and the escalator's private rules. Migration order: build policy module → route escalation through it (fixes N1 immediately) → route calendar_prep (enables §5.3 Live Activity) → route everything → delete bypasses.
2. **Escalation sweep** keeps its good parts (per-category cooldowns, per-user caps, `_NO_ESCALATE_CATEGORIES`) as *producer hints*, loses its delivery authority.
3. **Timezone constitution (M2).** Aware-UTC in all code; ET only at presentation via `app.core.timezone`; extend `check_naive_datetime.py` to catch aware-into-naive-column binds (the B4 shape) and naive-minus-aware arithmetic (the B2 shape); CI-gate it; migrate naive columns (`episode.created_at`, `reflection_observations.created_at`, `behavioral_pattern.updated_at`, `background_task` ts) to timestamptz in one planned migration.
4. **Truthful tasks (M1).** Every scheduled task returns an outcome contract (`{"effect": "wrote_rows", "count": N}`); the beat wrapper marks `last_status='failed'` on contract miss, not just on raise; interoception consumes contract misses; canaries for slow-moving invariants: PKG reconciliation wrote ≥1 row today; sent cursors advanced <24h ago; attachment queue draining; every route module imports cleanly (would have caught B3 the day it shipped); prediction matcher ran; ANALYZE age <7d.
5. **ML: train in-process, delete the phantom plane.** The four families are tabular, small-N problems — sklearn/xgboost territory, minutes on CPU. Nightly Celery task per family: load features/labels → train → time-series cross-validate → write `ml_model_version` (metrics, artifact path) → promote to `active_version` only if it beats current on held-out data. Inference: in-process at need (interruptibility + notification_value inside §3.6; next_block/rhythm_forecaster inside §3.2), logged to `ml_prediction_log` with outcome backfill — closing the loop D1 left open. Delete the Redis job plane and registry (`ml:control:*`); keep the Settings "retrain now" button pointed at the Celery task. **Cold-start honesty:** `notification_value` has ~95 labeled outcomes — enough for a first weak model now, improving weekly; `next_block` needs more `ml_feature_daily` history (backfill 30 days now via the existing `backfill_features` task); models *augment* the heuristics in §3.2/§3.6, never replace them below a quality bar.
6. **Patterns get their door (D2):** (a) run the proactive trigger check **hourly** (it costs 0.3 s — the ±30-min window then actually overlaps pattern times); (b) route its output through §3.6 (an 06:00 pattern suggestion delivers *with the morning*, not at 06:00 sharp unless David's awake); (c) add the §3.3 promotion ladder so confirmed patterns become predictions and standing-order suggestions.
7. **Monolith:** finish Phase-3 extraction of the hard 47 routes; extract SimpleLLMClient (deferred item 6A) first since chat is the most-touched surface and B2 lived at line 9,576 of a 9,300-line file.
8. **Schema truth:** one `Base`; one `Document` model; adopt alembic for real (`alembic_version` is empty); drop D6's dead tables in one reviewed migration (after full backup, with `to_regclass` guards in any code that referenced them).
9. **Generation-side idempotence everywhere:** calendar-prep records event-ID-prepped; attachment processor records assessed-IDs; cross_system_check keeps stable dedupe topics. The delivery firewall becomes defense-in-depth, not the mechanism.
10. **Deploy honesty:** the weekly self-audit compares deployed artifact versions (backend image, daemon version in `sara_daemon_state` — already reports 0.9.0+be0a5161, iOS build number) against repo expectations; drift becomes a self-model health item. ("Deployed code lags working tree" has burned this project repeatedly; make it sensed, not remembered.)

## 4.3 CHANGE (rip out / replace)

1. **Delete the insight graveyard:** `autonomous_insight`, `contextual_insight`, `proactive_suggestion(s)`, `dream_insight`, `insight_nudge`, `intelligence_item/report(s)` tables and their orphaned readers. The attention queue won; it is the one surfacing mechanism.
2. **Retire both hypothesis tables** (`hypothesis`, `reflection_hypotheses`); fold the *concept* into §3.3's belief ladder (a "hypothesis" is just a belief at low confidence with an active evidence-seeking flag — §3.5 pursues it).
3. **Cron-shaped → rhythm-relative cognition.** Morning brief at "wake + 20 min" (sensed wake, §3.6), proactive checks relative to rhythm windows, consolidation after winddown, dream cycle mid-sleep. Cron remains only as the fallback when rhythm is unknown. (D2 existed *only because* check times and life times were unrelated clocks — this removes the class.)
4. **Collapse fitness/goal sprawl:** keep the tables iOS actually writes (`workout_log`, `active_workout_session`, `exercise_pr`, `food_log`, `daily_recovery_log`, `cardio_log`, `tabata_preset`, settings); drop the ~20 empty generations. Goals live in `sara_goal` + PKG; drop `goal`, `fitness_goal(s)`, `goal_milestone`, `goal_progress`.
5. **Webapp reorganized as a window into the mind** — full plan in Part 7.

---

# Part 5 — iOS Master Plan

Context: EAS dev-client workflow (JS changes = reload; new native modules = fresh EAS build). App Group + @bacons/apple-targets + local `sara-native` module + `withSaraAppIntents` plugin already exist. One rebuild is already owed (Artifacts file/share modules); batch these native additions into planned rebuild waves (§8.2).

## 5.1 Principles

- The phone is David's primary body-adjacent surface: it knows location, motion, Focus state, and is the HealthKit gateway. Treat it as **sensor + glanceable display + consent surface**, with chat as the deep channel.
- Everything displayed obeys §3.6 (one policy) and §3.10 (inspectable why).
- Push payloads stay minimal; rich state syncs via the unified inbox API + App Group storage for widgets.

## 5.2 Widgets (glanceable mind-state; zero interruption cost)

All widgets read from an App Group JSON cache refreshed by (a) BGAppRefresh, (b) silent pushes on state change (budgeted — WidgetKit reload allowance is finite; the delivery policy owns the budget), (c) app foreground.

1. **Today widget (medium/large):** morning-brief digest — readiness score, first event + prep state, top Needs-you item, Sara's one-line day note. Tapping deep-links to the relevant surface.
2. **Attention widget (small):** Needs-you count + highest-value item title (from `compute_badge` + queue). This is the *calm* alternative to pushes for normal-priority items.
3. **Fitness widget (small/medium):** recovery score ring, today's session (from `training_day.is_training_day()`), last PR celebration. Progress-tab styling (Skia look mirrored in widget-safe rendering).
4. **Lock-screen accessories:** readiness ring (circular), next-event countdown (inline), attention count (circular).
5. **Sara-status widget (small, the presence artifact):** current One-Mind state (idle/focused/researching), last journal line, or current curiosity goal — the ambient "she's alive" surface. Reads the workspace (§3.1).

## 5.3 Live Activities (self-updating truth instead of stale pushes)

Live Activities are the *correct* iOS primitive for anything time-evolving — they update themselves and can't go stale (the exact failure N3/`_NO_ESCALATE_CATEGORIES` worked around).

1. **Meeting-prep Activity:** starts at prep-window open ("Risk Ninja Training — 42 min · prep: deck link, Jim's last email"), counts down live, Dynamic Island compact view, ends at meeting start. **Replaces calendar_prep pushes entirely** for events with ≥30-min notice; the push remains only as fallback when no Activity entitlement/state.
2. **Workout Mode Activity (exists — fix and finish):** close the June-audit end-signal gaps (explicit end on session close + server-side stale-Activity reaper via push-to-end); add rest-timer countdown in Dynamic Island; PR-attempt banner (progressive_overload already computes suggestions).
3. **Tabata/cardio Activity:** interval phase, round count, work/rest countdown — driven by the new `cardio_log`/`tabata_preset` machinery.
4. **"Sara is working" Activity:** live progress for David-initiated long jobs (research runs, workspace document builds, host diagnostics): phase, ETA, done-signal. Builds the agency-legibility habit (§3.10) into muscle memory.
5. **Focus-block Activity (opt-in):** when David starts a deep-work block (§6.4 scheduling), a quiet Activity shows block remaining; Sara holds non-critical items until it ends (the Activity *is* the visible contract).

## 5.4 Notifications, upgraded to conversations

1. **Interruption levels mapped from the delivery policy:** `passive` (FYI — no light-up), `active` (default), `time-sensitive` (breaks Focus — only prep-imminent, security, health-anomaly), `critical` (never without explicit entitlement + David's opt-in; lock-failure candidate). This gives §3.6 native teeth on-device.
2. **Action buttons (UNNotificationCategory) — the N1 "unanswerable question" fix:** every Sara-question notification carries its answers: [Yes] [No] [Tell me more]; followups carry [Done] [Snooze 1h] [Tonight]; suggestions carry [Do it] [Not now] [Never]. Responses post to the inbox-action endpoint → feed `ml_notification_outcome` with **explicit** labels (acted/declined/never), which are 10× better training signal than inferred read/ignored — directly improving `notification_value` (§4.2.5).
3. **Every push deep-links** to its item's why-trace view (§3.10) — long-press → "Why am I seeing this?"
4. **Communication-style notifications** (INSendMessageIntent donation) so Sara's pushes render with her avatar and thread like a person's messages — identity continuity in the OS shell.

## 5.5 App Intents / Siri / Shortcuts (hands-free actuation without Jetson)

Via the existing `withSaraAppIntents` plugin, register:
1. **Capture:** "Hey Siri, tell Sara …" → inbox/note/PKG-candidate (the highest-value intent; zero-friction thought capture).
2. **Query:** "What's my day look like" → brief summary snippet + opens Today surface; "What's my recovery" → readiness + training rec.
3. **Fitness:** start workout / start tabata (preset by name) / log weight / log food (dictated, hits food_search_and_log).
4. **Loops:** "Mark <followup> done", "Snooze my inbox until tonight".
5. **Focus/state:** "Sara, focus block 90 minutes" (creates block + Activity + hold-policy); "Sara, I'm heading out" (presence hint).
6. **Shortcuts automations (user-installed, suggested by Sara in Settings):** Sleep Focus on → delivery policy sleep-hint; CarPlay connect → driving-mode (hold non-urgent); arrive at known_place → presence event. Each automation is a *sensor* feeding §3.6's David-state.

## 5.6 The inbox as the canonical mobile surface

Keep the Needs-you/FYI triage; add: swipe actions mirroring notification buttons (done/snooze/never), the why-trace row, and a "held for you" section showing what the delivery policy queued overnight (transparency for §3.6's holds — David sees the restraint, which builds trust in it).

## 5.7 Background & location

- **HealthKit background delivery** (§6.1) — observer queries so health data arrives when generated, not on app-open.
- **Significant-location-change + visits** feed `location_event`/`known_place` (place-discovery job already exists); geofenced leave-now nudges already exist — route through §3.6.
- **Battery-respect rule:** all background work batches; no continuous GPS.

---

# Part 6 — HealthKit Master Plan

Principle: health data is the richest *involuntary-truth* signal Sara has — David can forget to journal, but his sleep/HR/steps don't lie. Every signal below gets: ingestion → baseline → prediction (§3.2) → at least one consumer. Privacy rule stands: health data never leaves the local stack; frontier chat models see *derived summaries* only when relevant, never raw streams; no unsolicited diet/weight commentary (banned-phrase filter stays).

## 6.1 Ingestion upgrades

1. **Background delivery:** HKObserverQuery + background delivery entitlement for sleep, workouts, steps, HRV, RHR, weight → push-to-backend on generation. Kills the "morning brief computed before last night's sleep synced" class.
2. **Aggregation correctness stays enforced:** steps/flights are cumulative daily snapshots — MAX per day, exclude today's partial (known gotcha, keep the guard).
3. **Workout stats via `getStatistic()`** (v13 pattern) — keep; extend to running power/pace where available for cardio tracker.
4. **Sleep sessions with stages** (not just duration): bed-time, wake-time, awakenings — wake-time is a *first-class signal* consumed by §3.6 quiet-hours and §4.3.3 rhythm-relative scheduling.

## 6.2 The readiness engine (formalize what's half-built)

`daily_recovery_log` + `morning_readiness` + `health_baseline` (38 baselines) + `signal_baseline` unify into one nightly computation: **readiness = f(sleep vs baseline, HRV vs baseline, RHR deviation, yesterday's training load, subjective check-in if present)** — z-scored per-signal against *David's own* baselines, never population norms. Output: score + top-2 drivers ("readiness 62: short sleep, elevated RHR"), written where all consumers read it (workspace slot 7, §3.1). The iOS Progress tab's client-side recovery mirror reconciles to this single server number (one brain rule, same as progressive_overload).

## 6.3 Consumers of every health signal

1. **Training (exists — keep):** recovery gates in-session progression suggestions (progressive_overload); low readiness → volume/intensity pullback offered in Workout Mode, not imposed.
2. **Interruptibility (§3.6):** readiness modulates notification appetite — tired David gets fewer, gentler, more-batched interruptions (verbosity calibration hooks already exist in adaptive personality).
3. **Scheduling counsel (§3.2 + calendar):** low-readiness day + dense calendar → morning brief proposes: move the deep-work block earlier (focus degrades faster when under-slept), suggest declining the optional 4 PM, protect lunch. Sara *proposes* via inbox; L1 autonomy unless promoted.
4. **Bedtime intelligence:** winddown nudges timed from `daily_rhythm` + tomorrow's first event + current sleep debt — delivered as a *passive* notification or widget state, never a lecture; drops after two ignores (anti-harping).
5. **Anomaly watch (exists — route through policy):** health-anomaly-detect's alerts become time-sensitive only when the anomaly is acute (resting HR spike); trends go to the weekly debrief.
6. **Correlation engine (D3) inputs:** sleep × focus-seconds × training load × location × mood (from chat sentiment / emotional_state) — this is *the* flagship consumer once data depth arrives (~mid-August). Expected first products: "sleep <6.5h → next-day focus −38%", "training-day evenings → better mood", each becoming a belief (§3.3) with evidence.
7. **Prediction-error (§3.2):** predicted sleep window vs actual (rough night detected without being told — scenario §3.2); predicted gym window vs actual workout (missed sessions noticed *silently* unless a streak-risk David opted into guarding).
8. **Weekly health debrief (exists — keep):** the one place comprehensive numbers appear, explicitly user-requested, `bypass_ban` appropriately.
9. **Nutrition loop:** food_log + weight_trend + training load feed The-Forge recomp dials (Reacher-block plan) — status vs target in the Fitness widget; conversational logging stays the input path.

## 6.4 New health-adjacent behaviors

1. **Sensed wake replaces fixed 07:00** for quiet-hours end (HealthKit sleep end + Focus off + first home activity — three sensors already flowing).
2. **Focus blocks:** David (or Sara, L1) schedules deep-work blocks informed by readiness + rhythm; iOS Activity displays it; delivery policy enforces it (§5.3.5).
3. **Recovery-aware standing-order modulation (later, L2):** e.g. bedtime scene dimming shifts earlier on high-sleep-debt nights — only after §3.7 promotion earns it.

---

# Part 7 — Webapp Master Plan

Reframe: the webapp's job is **legibility of the mind** — the place where David sees what Sara is attending to, believes, doing, and learning — plus the workbenches (notes, fitness, docs) that already work. Reorganize the shell nav around five mind panes + existing workbenches. (Current stack: React SPA, view-state routing, Tailwind dark theme — all fine; this is an information-architecture change, not a rewrite.)

## 7.1 Attention (default landing pane)

The live attention queue (Needs-you / FYI / Held), each item with: source, age, why-trace link, and the same action set as iOS (done/snooze/never). Plus the **workspace strip** (§3.1) across the top: what Sara is holding right now — active threads, open loops, in-flight work, today's predictions with live confirmed/violated status. This strip is the single most important new UI element: it *is* the window into "what is she thinking."

## 7.2 Beliefs (the PKG made visible and correctable)

Browser over the unified belief system (§3.3): facts/preferences/routines/patterns with confidence, evidence count, last-validated, and ladder status (observed→…→automated). Three interactions: **confirm** (evidence++), **correct** (edit → contradiction handling), **block** (the `sara_interest.blocked` pattern — never delete, deletion resurrects). Include the **contradiction queue** (consolidation already finds 10/day — today they die in logs; here David adjudicates the interesting ones in 30 seconds). The existing D3.js graph view stays as the visual mode.

## 7.3 Actions (the ledger + autonomy console)

Every autonomous action: what/when/why-trace/outcome/undo (while window open). Standing orders CRUD. The §3.7 **trust matrix**: rows = action classes, columns = L0–L3, showing current level, track record (executions, failures, acceptance rate), and promotion eligibility — where David grants/revokes with one click. This page *is* the trust contract made visible.

## 7.4 Self (Sara's health, honestly)

The self-model (§3.4) rendered: actuator/channel health, outcome-contract misses, task_failure browser, deploy-state drift, queue depths, token spend (`token_usage`), and the **calibration panel** (§3.9): per-domain reliability curves, this week's prediction hit-rate, the misses that taught her something. Absorbs `/debug/notification-funnel` as the delivery-funnel tab. Design intent: David should never need to re-run this audit by hand — this page *is* the audit, continuous.

## 7.5 Memory & Journal (continuity made visible)

Timeline view (exists) + day-replay browser (`day_replay_cache`, 146 days) + episode search (exists) + **Sara's journal as a readable feed** with emotional-arc coloring — and the §3.5 "what I learned this week" entries + §3.8 morning intuitions collected in one place. The knowledge-garden workbench (notes/graph) remains as-is beneath it.

## 7.6 Settings → the values surface

Beyond model/config plumbing: per-category interruption values (sliders seeded from learned `attention_policy`, editable — edits feed back as strong priors), quiet-hours preferences (sensed-sleep on/off + hard bounds), the autonomy trust matrix (same data as §7.3), curiosity budget (§3.5), and Shortcuts-automation suggestions (§5.5.6).

## 7.7 Surfaces & Studio (keep, one addition)

Artifacts Studio + interactive surfaces (Parts A & B done) stay. Addition: **the morning brief becomes an interactive surface** (readiness ring, calendar with prep states, held-overnight items, Sara's note, one-tap actions) — same surface rendered web + iOS, replacing the text-blob brief as the daily anchor artifact.

---

# Part 8 — Sequencing, Acceptance Criteria, Data→Consumer Matrix

## 8.1 Phases (each independently shippable; order chosen so trust-building precedes autonomy-raising)

**Phase 0 — Truth (P0/P1 fixes, ~days):** the four one-line fixes (B1–B4); datetime CI gate; outcome contracts + canaries; ANALYZE + autovacuum; sent-items + attachment idempotency. *Exit test:* zero silent failures — every red thing is visibly red on §7.4 (build the minimal Self page here).

**Phase 1 — One mouth (unified delivery policy):** §3.6 module; escalation routed (sleep-gated via sensed sleep §6.4.1); calendar_prep routed; producers migrated; bypass flags deleted; iOS interruption levels + action buttons (§5.4.1–2, needs a rebuild wave). *Exit test:* no push between sensed-sleep-start and sensed-wake for 14 consecutive days except security/critical class; explicit-outcome labels flowing into `ml_notification_outcome`.

**Phase 2 — Prediction loop:** `prediction` table populated by morning anticipation; matcher; violations → salience; day-replay grading; calibration report v1 (§3.9). *Exit test:* ≥10 predictions/day graded; at least one violation-driven deliberation observed doing something useful; weekly calibration numbers rendered in §7.4.

**Phase 3 — Beliefs get doors:** hourly trigger check; promotion ladder + standing-order suggestions (§3.3/§4.2.6); belief browser + contradiction queue (§7.2). *Exit test:* `times_suggested > 0`; ≥1 pattern promoted to a standing order with David's consent.

**Phase 4 — Models for real:** in-process nightly training (§4.2.5); `notification_value` v1 inside the delivery policy (shadow-mode first: log its opinion, compare to heuristic, promote when it wins); feature backfill 30 days; delete `ml:control:*`. *Exit test:* `ml_model_version` non-empty with honest cross-validated metrics; `ml_prediction_log` growing with outcome backfill; shadow-mode comparison report.

**Phase 5 — Workspace + self-model integration:** §3.1 workspace with the read-before-act enforcement points; §3.4 unified self-model; chat introspection; workspace strip UI (§7.1). *Exit test:* the §3.1 scenario works — ask "anything I should know?" and get workspace-grounded specifics; ask "what's broken about you right now?" and get the truth.

**Phase 6 — Inner life & autonomy:** curiosity goals with budget (§3.5); dream-cycle jobs (§3.8); trust matrix + graduated autonomy mechanics (§3.7, §7.3); rhythm-relative scheduling migration (§4.3.3); morning-brief surface (§7.7); remaining widgets/Activities/App Intents waves (§5.2/5.3/5.5).

**Continuous:** monolith extraction (§4.2.7), schema cleanup migration (§4.3.4/D6), deploy-drift sensing (§4.2.10). **Mid-August checkpoint:** correlation engine (D3) should begin producing — verify, and wire its outputs into §3.3.

## 8.2 iOS rebuild waves (native changes batched; JS ships continuously)

- **Wave 1 (with the already-owed Artifacts rebuild):** notification categories/actions + interruption levels + communication-style notifications + HealthKit background delivery entitlement.
- **Wave 2:** widget set + lock-screen accessories + meeting-prep and Sara-working Live Activities.
- **Wave 3:** App Intents suite + Focus-block Activity + Shortcuts automation donations.

## 8.3 Data→Consumer matrix (the no-orphans proof)

| Data asset | Consumers (section) |
|---|---|
| Sleep/HRV/RHR/steps | readiness §6.2 → delivery policy §3.6, training §6.3.1, scheduling §6.3.3, predictions §3.2, correlations §6.3.6, sensed wake §6.4.1 |
| Workouts/PRs/food/weight | workout mode §5.3.2, Progress tab + widget §5.2.3, recomp dials §6.3.9, correlations |
| Calendar + email | prep Activities §5.3.1, followups §5.4.2, meeting-research (exists), predictions §3.2, sent-mail commitments §1.3-B5→followups |
| Location/places/presence | David-state §3.6, leave-now nudges (exists→policy), place discovery, predictions |
| Home activity + patterns | belief ladder §3.3, standing-order suggestions, predictions §3.2, sensed sleep/wake §6.4.1 |
| Daily rhythm + temporal bins | rhythm-relative scheduling §4.3.3, predictions, focus blocks §6.4.2, bedtime §6.3.4 |
| Episodes + PKG + notes + people | chat context (exists), belief browser §7.2, dream recombination §3.8.3, curiosity §3.5 |
| notification_log + outcomes | notification_value model §4.2.5, attention learning (exists), calibration §3.9, funnel §7.4 |
| task_failure + contracts + deploy state | self-model §3.4, Self page §7.4, dream counterfactuals §3.8.1 |
| behavioral_pattern | ladder §3.3, predictions §3.2, suggestions §4.2.6 |
| ml_feature_daily | models §4.2.5, correlations §6.3.6 |
| day_replay_cache | prediction grading §3.2, calibration §3.9, memory pane §7.5 |
| token_usage | curiosity budget §3.5, Self page §7.4 |
| host_metric / managed hosts | self-model, curiosity effector §3.5, Sara-working Activity §5.3.4 |
| Sara journal + emotional state | Memory pane §7.5, narrative identity, chat persona (exists) |
| followup_thread | inbox + action buttons §5.4.2, workspace open-loops §3.1 |

Every actuator from §2.2 likewise appears: pushes/inbox/brief/chat (§3.6), Live Activities/widgets/App Intents (Part 5), HA + standing orders (§3.3/§3.7), calendar/reminders/notes/email-drafts (§6.3.3, §5.5, §7.2), research/dispatch/Code-Mode/workspace-jobs (§3.5, §5.3.4), queue-for-Sara (§3.1 workspace), internal learning loops (§§3.2–3.9).

## 8.4 The one-paragraph version

Fix the four broken wires and make every future failure audible (Phase 0). Give Sara one mouth with manners — a single delivery policy that knows when David is asleep (Phase 1). Turn her data into predictions and her misses into learning (Phase 2). Give her beliefs a road from "noticed" to "automated with consent" (Phase 3). Train the small models she's been collecting data for (Phase 4). Give her a working memory she and David can both look at, and a self-model honest enough to have written this audit herself (Phase 5). Then let her want things — bounded curiosity, real dreams, and autonomy that is earned, visible, and revocable (Phase 6). The phone becomes her glanceable face and consent surface; HealthKit becomes her involuntary-truth sense; the webapp becomes the window into her mind. Nothing here is speculative infrastructure: every phase consumes data she already collects and actuators she already has — the work is connection, honesty, and doors.

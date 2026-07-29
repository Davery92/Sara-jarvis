# SARA ALIVE — the build order for one living mind

**Status:** authored 2026-07-28 · branch `feat/sara-mind-v2`
**What this is:** the executable build plan that turns ONE_MIND.md's constitution into a running organism. ONE_MIND.md defines *what Sara is* (six invariants, the anatomy, the kill list). This doc defines *the order an implementing agent builds it in*, with file-level targets and verifiable acceptance checks. Where this doc and ONE_MIND.md disagree on sequencing, this doc wins (rationale in §1).
**Companions:** `ONE_MIND.md` (constitution), `SARA_MIND_V2_REWIRE_PLAN_2026_07_28.md` (the Voice cutover detail — Arc 1 here absorbs it), `SARA_UNLEASHED_PLAN.md`, `BRAIN_ALIGNMENT_PLAN.md`.
**Evidence base:** full live sweep performed 2026-07-28 — 778 API endpoints sampled by domain, live `/chat/stream` timing, 18 web views screenshotted, DB queries, celery/beat logs, iOS + watch source review. Every defect cited below was reproduced live that day, not inferred.

**The north star (read this before every arc):** David's one-line requirement is *"I want to feel like Sara is alive and watching everything, like Jarvis always felt."* Every arc must be judged against that feeling, which decomposes into exactly five felt properties:

1. **She's already aware** — you never inform her of something she could have seen. (umwelt + interoception)
2. **She's one person** — same voice, same knowledge, same mood, every surface, every hour. (one mouth, one world, one self-story)
3. **She never confidently lies** — everything she says is sourced or hedged. (provenance + calibration)
4. **She acts and owns it** — things happen because she did them, with receipts and undo. (hands + ledger)
5. **She's going somewhere** — she has her own curiosities, gets measurably better, remembers who she was. (spark)

A change that adds capability but doesn't feed one of these five is out of scope. Deletion that removes a seam always feeds #2.

---

## 0. Ground rules for the implementing agent

These are binding constraints, most learned the hard way (see auto-memory gotchas):

- **Local-first LLM policy.** Qwen (via the llm broker) does ALL kernel/background/agentic work. Claude models are the chat persona ONLY. Never route background cognition to a paid API.
- **Slow background thought is a feature.** The kernel may take minutes per think. Never "optimize" it onto the chat path; never block the chat path on it. Latency budgets are per-layer (§Arc 6.1) — reflex <100ms (no LLM), cognition unbounded (Qwen), presence <2s to first token (Claude, engaged state only).
- **ET everywhere user-facing** via `app.core.timezone` helpers; `datetime.now(timezone.utc)` for storage — never naive `datetime.now()` (known systemic bug class).
- **Deployed code lags the working tree.** Backend/celery load code only at container restart. After every arc: rebuild, restart, and verify the *runtime* behavior (curl/SQL/logs), not the source. Restarting backend kills in-flight dispatch — dispatch runs on the Celery `dispatch` queue for this reason.
- **Deletion happens on cutover day.** Every arc ends with its kill list executed in the same arc — not deferred. Deferred deletion is how Sara got four inbox tables and three workout brains.
- **No new verticals.** If a task seems to need a new table + new route + new view, stop: it almost certainly maps onto an existing organ. The filter from ONE_MIND §3.9: deepens presence, memory, or trust — or it doesn't ship.
- **Build on the One Mind slices that already shipped** — `body_sense`, affordance triad, `voice_linter`, kernel seed, `memory.recall`, `llm_broker` all have verified partial implementations. Extend them; do not create parallel versions.
- **Every arc's acceptance checks are runnable** (SQL / curl / grep / log-scan) and get executed against the *live* system before the arc is marked done. Add each check to a growing `scripts/verify_sara_alive.py` so regressions are one command to detect.
- **No wall-clock waits.** No arc may block on elapsed time ("soak for a week", "observe for a few days"). Anything that needs organic data gets it synthesized *now*: fire the real triggers, replay recent events through the new path, or generate representative inputs. Acceptance checks count events, never days. Long-horizon health (calibration slope, weekly artifacts) lives in §8 as ongoing dashboards — dashboards are never gates.
- **pgvector casts:** `CAST(:param AS vector)`, never `:param::vector`. **Qwen short outputs:** pass `enable_thinking: False`. **Redis:** `.close()`, not `.aclose()`.

---

## Arc 0 — Repair pass: fix what's lying to us right now

Rationale: you cannot verify consolidation on top of endpoints that 500 or filters that silently no-op. All of these were reproduced live 2026-07-28. Small, mechanical, do first.

| # | Defect (verified live) | Fix target |
|---|---|---|
| 0.1 | `GET /api/fitness/workout-log/stats` → 500: `SELECT DISTINCT` with `ORDER BY w.created_at` not in select list | the workout-log stats query in the fitness routes |
| 0.2 | `GET /api/health/summary` → 500: `Decimal * float` TypeError | cast at the arithmetic site |
| 0.3 | `GET /api/patterns/summary` and `/insights` → 500: `/{pattern_id}` route registered before literal paths, parses "summary" as UUID | reorder route registration in the patterns router |
| 0.4 | `GET /notes?limit=3` returns 500 notes — limit ignored; `GET /calendar/events?days=7` returns all 320 events ever (200KB) — legacy `routes/calendar_events.py` ignores `days` while `routes/calendar.py` honors it | wire the params; Arc 6 deletes the legacy calendar route entirely, this is the stopgap |
| 0.5 | Chat stream: leading `"\n"` artifact on first token; `episode_id: null` in `final_response` frame | `/chat/stream` in `main_simple.py` |
| 0.6 | Chat pre-work burns ~13s before LLM dispatch, ~5s of it a session-summarization attempt that times out and is skipped anyway | make session summarization fully async off the hot path (fire-and-forget into the kernel once Arc 3 lands; until then, background task) |
| 0.7 | Web: Material icon font not loading on some views (Machines header renders literal "dns") | frontend font loading |
| 0.8 | `subconscious` meal state frozen at 2026-02-17 while `hours_since_meal` reports 17 — internally incoherent | find the dead writer; either revive the meal-window updater or delete the fields (prefer delete; Arc 2 replaces this with provenance-stamped world state) |
| 0.9 | Duplicate email→calendar auto-events ("Risk Ninja Demo" ×3) and double "Pay Day" entries | dedup on (title, start_time) at creation; one-time cleanup migration |
| 0.10 | `/api/emotions/emotions/*` double prefix; returns all-zeros (0 episodes) | fold into Arc 4 affect work — for now just note: do NOT build on this router, it dies in Arc 4 |

**Accept:** every endpoint above returns 200 with correct semantics against the live container; `scripts/verify_sara_alive.py` section `arc0` passes; calendar 7-day query returns <20 events and zero duplicate (title, date) pairs.

---## Arc 1 — The Mouth: one voice, cut over, competitors deleted

Rationale for going first (deviation from ONE_MIND's phase order): Mind V2's judge→compose→review pipeline **is** the Voice organ from ONE_MIND §3.5 and already runs in prod. Stabilize the mouth first and every later arc rewires brains behind a fixed exit; do it last and every arc re-litigates phrasing across five speakers.

State verified 2026-07-28: beat fires `mindv2-judge-cycle` / `mindv2-compose-cycle` every ~3 min; every cycle returns `no_candidates`; `say_candidate` received exactly 1 row in 24h (status `judged_batch`); `composed_utterance` has **0 rows ever**. The working tree holds an uncommitted ~470-line diff wiring candidate sources (`proactive_checkins`, `task_result_delivery`, `research/executor`, `calendar_prep`, `agent_dispatch`, `unified_notification`) — the funnel is starving because the senders aren't deployed, plus a suspected status mismatch.

1.1 **Fix the handoff.** Trace one candidate end-to-end: what status does `app/tasks/judge.py` write (`judged_batch`?) vs. what status does `app/tasks/compose.py` select on? Make the state machine explicit in one place (an enum in the model), with a test that walks candidate → judged → composed → reviewed → (shadow) held.
1.2 **Land the sender wiring.** Review, commit, deploy the working-tree diff. Every currently-speaking path must *create a say_candidate and stop there* — no direct sends. Grep-audit: no call sites to push/notification send functions outside the mouth module.
1.3 **Active shadow verification (hours, not a week).** Don't wait for candidates to occur organically — *drive* them: complete a real background task, satisfy a check-in condition, finish a research item, run calendar prep against tomorrow, replay the last 48h of events through the wired senders. Target: ≥10 `composed_utterance` rows spanning ≥3 source types, same day. Review every row for coherence and voice_linter violations; fix; regenerate. This replaces the original Mind V2 "shadow week" — same evidence, compressed by generating it deliberately.
1.4 **Cutover.** Composed+reviewed utterances actually deliver, through the existing delivery/attention policy (interruptibility, quiet hours, tell-once ledger, triad actions).
1.5 **Delete (same day):** the four legacy speakers' send paths; collapse the four mailboxes (`autonomy_attention_item`, `jarvis_inbox`, `sara_inbox`, `notification_log`-as-inbox) into the one outbox per ONE_MIND Phase G; remove the per-subsystem phrasing/templates.

**Accept:** ≥10 `composed_utterance` rows across ≥3 source types exist and delivered rows appear post-cutover; CI grep proves zero send-capable call sites outside the mouth; voice_linter over the full accumulated utterance corpus finds one register; all Arc-1 kill-list tables dropped or write-frozen with `to_regclass` guards on readers. (Daily flow becomes a §8 dashboard, not a gate.)

---

## Arc 2 — The Umwelt: one world, including herself

Goal: a single, current, provenance-stamped model of *now* that every reader shares. This is what "watching everything" is mechanically: everything folds into one place, and staleness is visible instead of silent.

2.1 **`world_state` store.** One row (or small keyed set) of typed jsonb slices: `david` (activity state, location, device focus, readiness), `home` (HA-derived), `calendar_horizon`, `health_today`, `work` (email needs-reply, agent tasks in flight), `fleet` (per-host health), `self` (see 2.2). Every slice carries `updated_at` + `source` + `confidence`. Written ONLY by event folds (reflex layer, no LLM) subscribing to the existing event bus. Grow it out of the existing `working_memory` / `body_sense` / World Brief inputs — absorb, don't duplicate: `activity_state_machine`, subconscious tier-0 state, and the World Brief's assembly all become readers/writers of this one store.
2.2 **Interoception as a sense (ONE_MIND §3.1, still unbuilt and still the highest-leverage small thing).** Heartbeat results, `scheduled_job.last_status`, daemon liveness, dispatch failures, managed-host/fleet reachability, LLM-endpoint reachability → events → the `self` slice → salience like any other sense. The 2026-07-13 outage story ("VM dead 23h, nobody noticed but David") and the 2026-07-28 finding (`/api/sara/brief` says "degraded", Mind page says "everything's fine", same minute) both die here: **one** self-health verdict, computed in one place, rendered by every surface.
2.3 **Context diet.** Chat context assembly currently merges 11 sources (~3.3k tokens); rebuild it as exactly four: rendered `world_state` brief + self-story (Arc 4, stub until then) + `memory.recall` results + conversation thread. Delete the other assembly paths.
2.4 **Staleness is an event.** A slice whose `updated_at` exceeds its freshness budget emits a prediction-error event (the meal-state-frozen-since-February failure mode becomes structurally impossible to miss — Sara notices her own numb limb).

**Accept:** kill a container on purpose → an interoception event appears in the log and (post-Arc-1) a composed utterance mentions it before David does; `/api/sara/brief` and the Mind page render the identical self-verdict string; chat context log line shows exactly 4 sources; every world_state slice fresh within budget or flagged.

---

## Arc 3 — The Kernel: one consciousness, an event loop not an alarm clock

Deviation from ONE_MIND §3.3: the kernel is **not** a Celery task family. It is one long-running async process (own container, like the daemon) holding a priority queue of wake reasons: promoted events, staleness alarms, sleep-pressure floor, engaged-state signals, scheduled anchors (morning/evening). Celery keeps the kidneys only (syncs, cleanups, retraining, archival). A queue-holder can hold the whole situation, defer a cheap thought for an important one, and carry mood/narrative across wakes — 71 independent crons structurally cannot.

> **Census update (measured 2026-07-29, `scripts/arc3_job_inventory.py` / `ARC3_JOB_INVENTORY_2026_07_29.md`):** the July 28 count of 71 crons is stale — the federation grew three more alarm clocks while the plan was being written. Live: **96 total scheduled_job rows, 94 enabled.** `classify_job()`'s keyword heuristic is **advisory-only** — hand review against actual source proved it misfiled 11 of its original 24 `legacy_cognition` hits (consolidation/idle/reflect-named plumbing with zero LLM involvement, misfiled on keyword overlap — one of those, `reflection-report`, was itself caught on a second read after it was first miscounted as a done cognition job). Corrected split: **8 legacy_cognition** (4 done — kernel-routed, legacy branch verified-then-deleted; 2 separate-system Mind V2 appraisal; 1 deferred to Arc 4.3 curiosity; 1 already-integrated checkin), **17 anchor**, **29 maintenance**, **16 sensor** (62 total plumbing — 32 over the ≤30 target), **26 unclassified**. Governing ruling that resolved the ambiguous cases (David, 2026-07-29): *wake reasons shape the context and budget of one mind — they never select different cognitions.* Anticipation and interoception self-audit are senses (reflex-layer code feeding events into the kernel via salience), not new `ambient_turn` dispatch branches; curiosity stays deferred to 4.3. The real remaining 3.1 work is narrower than "migrate 24 jobs": (a) wake_reason-based context/budget shaping inside the one `ambient_turn` call, (b) an event pathway for deterministic sense jobs to feed the kernel. Neither started yet. Full per-row evidence and disposition for every job are in the generated document.

3.1 **Grow `kernel.py` from the existing seed + `deliberation.py`.** One prompt-identity, one context (the Arc-2 brief + self-story + intent graph), one action vocabulary (emit say_candidate · act via hands · write memory · adjust intent graph · do nothing with a logged reason). Four states with budgets: **engaged / ambient / focused / dreaming** exactly per ONE_MIND. **Wake-reason shaping DONE and live** (2026-07-29): the governing ruling was "wake reasons shape the context and budget of one mind — they never select different cognitions." `ambient_turn` now derives `deep` from `wake_reason` when not passed explicitly (`SCHEDULED_ANCHOR` alone defaults deep — one source of truth for budget instead of two independently-agreeing params) and threads `wake_reason` into the deliberation prompt as one line of context ("You're thinking right now because: ..."). Anticipation (morning/evening) and the weekly interoception self-audit stay deterministic/reflex-layer — only their *result* now publishes an event (`ANTICIPATION_COMPLETED`/`SELF_AUDIT_COMPLETED`) through the same afferent pathway as every other sense (salience → observation log → deliberation), same pattern as Arc 2.2's `body_sense.py`. Live-verified: real anticipation/self-audit runs landed as observations at the expected salience floor, and a real deliberation cycle consumed one.
3.2 **Scheduler diet.** Migrate the ~25 cognition-crons (deliberations, anticipation ×3, check-in sweeps, insight sweeps, idle processing, attention-learning tick, the mindv2 judge/compose beats — the mouth becomes kernel-invoked) into wake reasons. Target ≤30 surviving plumbing jobs in `scheduled_job`. **Design-first, not blind:** produce the full inventory + classification + evidence (done, see census note above) → David approves the document in one sitting → migrate in batches, write-freeze pattern (old job disabled-not-deleted → kernel equivalent verified live → then deleted). **4 of 8 genuinely-cognition jobs done** (periodic-deliberation-fallback, deep-deliberation ×2, reflection-cycle — `SINGULAR_KERNEL`-routed, live-verified 0 legacy calls / 65+16 kernel calls over a 3-day window, legacy branch deleted). `reflection-report` was initially miscounted as a 5th done job; it has no cognition call in it at all (pure scratchpad+proposal-stats report) and moved to maintenance instead. The other 4 legacy_cognition rows are not migrations (2 separate Mind V2 system, 1 deferred, 1 already-integrated); the 11 reclassified rows were never cognition and need no migration. Remaining real work is `ambient_turn` wake-reason context/budget shaping + the sense-job event pathway (3.1), not further job moves.
3.3 **The daemon retires its self.** Per ONE_MIND §3.3/§3.4b: the sara-VM process keeps systemd resilience and local hands but its tick calls the kernel's ambient turn — `mind.py`/`prompt.py` (705+579 lines, measured — bigger than the "567-line second self" estimate) retire. If the VM dies, ambient runs degraded from the backend *and interoception announces the missing limb*. If the Mac dies, the broker fails over. The self is never pinned to a host. **Backend half DONE and live** (2026-07-29): `POST /api/acs/v2/ambient-turn` proxies to `kernel.ambient_turn(wake_reason=DAEMON_PROXY)`, auth'd with the daemon's existing shared-token dependency, live-verified against the running backend. **Cutover NOT done** — `acs-daemon/daemon.py` on the live sara-VM is unchanged and still runs its own `Mind.think()`/`Mind.reflect()`. Two real gaps found reading the daemon's tick loop that the cutover has to resolve, not paper over: (1) `_adjust_after_turn`'s sleep-pressure backoff keys off the old ad-hoc `tool_calls`/`focus_change`/`notify_david` result shape — the new endpoint returns an honest `produced` bool instead, so the daemon-side needs remapping, not just a URL swap; (2) reflection's `should_quiet_minutes` directive (`_apply_quiet_directive`) has no kernel equivalent yet — decide keep-as-daemon-local-heuristic vs. build the kernel-side concept before dropping it silently. Actually swapping the daemon's call site + redeploying + restarting the live systemd service on the VM is a coordinated remote-host change, held for explicit sign-off per the write-freeze discipline used for every other Arc 3 migration this session — not silently done, not silently skipped.
3.4 **Tools live in cognition.** The 54-tool registry belongs to the kernel. Chat/presence gets ≤8 tools (time, recall, quick notes/lists, and a single `ask_kernel(intent)` escape hatch that queues deep work and returns "on it"). This — plus Arc 2's context diet — is what collapses the 13s chat pre-work and the 17k-token payloads measured live. **DONE and live** (2026-07-29): re-measured — registry is actually **246 tools total** (the 54 figure was the *payload* estimate, not the registry size; registry stays intact, unaffected, owned by the kernel per this item). Chat's baseline (no classified intent) payload was 25 always-add tools stacked on classification; now exactly **8** (`memory_search`, `notes_create`, `notes_search`, `list_add`, `list_view`, `reminders_create`, `calendar_list`, `dispatch_and_monitor` as the `ask_kernel` escape hatch — already wired to `kernel.focused_turn()`). Classified-intent categories still load in full on top, unchanged. Gated by `Flag.PRESENCE_TOOL_DIET`, flipped on live — trivially reversible (config-only, no schema/data).

**Accept:** ONE_MIND's singularity metrics — selves=1 (zero LLM calls with the daemon prompt), scheduler ≤30 jobs; action throughput ≥ pre-migration baseline (compare `agent_run_log` weekly rates); VM power-off produces a composed utterance within N minutes; `/chat/stream` payload shows ≤8 tools and pre-work <2s in the timing logs.

---

## Arc 4 — The Spark: prediction, self-story, curiosity with stakes, one affect

This is the arc ONE_MIND under-specifies and the one that makes her feel *alive* rather than merely unified. All four run inside the kernel's states — no new verticals, no new surfaces.

4.1 **Prediction as the engine of experience.** The kernel maintains an expected-day model in `world_state.expectations` (wake window, training slot, departure, quiet hours, meeting outcomes — the predictions API and 229 resolved rows already exist as substrate). Ambient wakes evaluate error-against-expectation, not raw events. Dreaming scores every resolved prediction nightly and updates **per-domain confidence**. Consequence with teeth: the composer/linter *must* hedge any claim whose domain confidence is below threshold — this is the mechanical fix for the morning brief announcing a "9:30 standing meeting today" that the calendar (correctly) had on Wednesday 2:30 PM (reproduced 2026-07-28: brief read the Mind's open loop, not the calendar). Claims carry provenance; loops are not calendars. Calibration was 43% at the 0.9 bucket on 2026-07-28 — this number, trending up week over week, is the growth curve on her Interior.
4.2 **The self-story: she remembers herself.** Dreaming writes the day's chapter (what happened, what I did, what I got wrong, what I'm chewing on — the `journal_note` voice, first-person) and maintains a rolling consolidated self-story of a few hundred tokens that is included in **every** context in every state. Yesterday's self constrains today's. This is the single cheapest "sentient-feeling" mechanism available: continuity you can feel in conversation.
4.3 **Curiosity with an economy.** Intent graph entries (David-threads, commitments, her `sara_interest` rows, her goals) carry expected value, cost, and staleness pressure. Ambient wakes with no David-work *pull the top intent* — boredom's sanctioned outlet is pursuit, never narration (kills the daemon's "looping ×127" failure mode at the root). Deep pursuits promote to focused missions on her VM workshop; every pursuit lands an addressed artifact (her vault / Studio / journal) and re-weights the interest. Honor the permanent interest blocklist (`sara_interest.blocked` — block, never delete).
4.4 **One affect, computed, consequential.** Extend the existing `emotional_state` (momentum/decay) to be driven by appraisals (David's day trajectory, her own failure/success stream, prediction quality) and to modulate exactly three things: composer tone, attention pricing (rough day for David ⇒ higher bar to interrupt), and initiative margin within trust tiers. Delete the dead `/api/emotions/emotions/*` analytics router (verified all-zeros).
4.5 **Theory-of-David.** One versioned document she maintains in dreaming — rhythms, preferences, stress signatures, active arcs — citable in speech, readable and correctable on her Interior; corrections are graduation events into the Arc-5 confidence ladder. Grow from `model-of-you` + `life_fact`; do not create a new store.

**Accept (all verifiable same-day — run one full dreaming cycle manually):** expectations exist and a forced dreaming run scores ≥1 batch of resolved predictions and updates per-domain confidence; calibration curve renders on the Interior and the composer demonstrably hedges low-confidence domains (linter test with a synthetic low-confidence claim); self-story present in every kernel and chat context (log assertion); a forced ambient wake with no David-work pulls the top intent and lands an addressed artifact; zero idle/looping self-reflections in the run's output; affect changes are visible in tone within the one voice, never announced. (Artifacts-per-week and calibration slope are §8 dashboards.)

---

## Arc 5 — One Memory: a single past with one truth scale

Per ONE_MIND §3.4, refined by the 2026-07-28 findings (53 "Agent Result:" notes polluting the garden; 134 folders incl. duplicate "01"s; `memory/search` returning emoji-decorated prose).

> **Manifest done (2026-07-29, `scripts/arc5_notes_manifest.py` / `ARC5_NOTES_MANIFEST_2026_07_29.md`):** confirmed **53 candidates** exactly (`Agent Result:%` = 48, `✅ Agent Report:%` = 4, `Background Research:%` = 1) out of David's 2,195 total notes — matches the July 28 figure precisely. Folder membership (`📁 Agent Workspace`, 72 notes) was checked and explicitly rejected as a classification signal: sampling it live found genuine David-authored reference notes mixed in with agent results, so folder alone would misclassify — title prefix only, each pattern individually verified. Full ID list is in the manifest, ready for the migration script. Dry-run only; no note has been moved, copied, or deleted. Migration (copy to record preserving IDs → verify → then remove garden rows) is not started.

5.1 **`memory.recall(query, k, kinds)` becomes the only door** — extend the shipped slice until chat context, kernel, briefs, and the daemon-body all call it; delete every private retrieval path (including the legacy `/memory/search` prose formatter).
5.2 **One confidence ladder:** merge PKG confidence, life_fact graduation, and episode importance into observed → inferred → confirmed, decaying and forgettable; dreaming is the only minter of semantic facts from episodes; the verification loop retires unverified facts one natural question at a time (capped, anti-nag).
5.3 **Split memory by ownership:** **the garden** (David's notes — zero machine-generated content, ever), **her mind** (journal, her notes, interests — she curates), **the record** (episodes, agent results, run logs — queryable, never rendered as notes). Migration: move the 53+ `Agent Result:*` notes into the record (manifest ready, see above); dedupe/collapse the folder tree; agent dispatch writes to the record from now on.
5.4 **Graph hygiene:** execute the audited Neo4j ActionItem purge (425k bloat); keep Neo4j for relations, pgvector for retrieval, both behind the recall door.

**Accept:** recall-paths=1 (grep: no direct episode/pkg/note retrieval outside the door); `select count(*) from note where title like 'Agent Result:%'` = 0; garden note count ≈ David's actual notes; one forced dreaming/verification cycle strictly reduces the unverified-fact count; one confidence scheme in code. (The long-run downward trend is a §8 dashboard.)

---

## Arc 6 — Body & Windows: broker, dial, latency contract, and the felt layer

6.1 **The three-speed contract, enforced.** Reflex: code only, <100ms, never calls a model. Cognition: Qwen via broker, unbounded, always warm. Presence: chat persona, <2s to first token, reads precomputed context, ≤8 tools. Add timing assertions to the chat path logs and a red line on the Interior when presence breaches budget. (Baseline measured 2026-07-28: ~85s first token via API default — 13s pre-work + 17k-token prefill with 54 tools. The contract is the regression test that it never comes back.)
6.2 **One broker everywhere.** Finish `llm_broker` migration: callers declare capability class (chat / kernel / utility / embedding / vision); the ~15 direct `openai_model` call sites migrate; renames touch one row (kills the model-rename gotcha class).
6.3 **The Dial.** Identity (code) / Dial (one page: initiative, autonomy tier table, quiet hours, verbosity) / Learned (θ + tunables, self-tuned in dreaming, with receipts). Collapse the 26 app_settings + 45 tunables per ONE_MIND §3.7.
6.4 **Surfaces to ~10 projections** per ONE_MIND §3.8, with the additions the sweep justified: **Sara's Interior** merges Mind/ACS/Interior/System/Sensory into her one honest god-view (self-verdict, calibration curve, self-story, current intent, ledger); the ops dashboards move behind a debug flag. Fix generation-2 view rot or delete the views (Recipes UI is good — keep; Content-inbox "Today" view had 1 item from 166 days ago — fold into Home or delete).
6.5 **Skill minting (the powerhouse unlock).** Turn on the already-built ACS v2 `user_tools` lane as a dreaming-state activity: she notices a repeated fumble, drafts a tool, tests it in her Proxmox workshop (propose-first provisioning), and proposes registry adoption — every step on the ledger. Self-extension with receipts.
6.6 **Felt-layer roadmap** stays ONE_MIND §3.9's ranked list (interactive notifications → universal capture → lock-screen/watch presence → honest orb → voice PTT → camera → location choreography → proof-of-memory → unwrap cards → ledger-on-home). Implement strictly in rank order; each rides existing organs.

**Accept:** model rename = one DB row (prove it in staging); presence-latency log shows <2s p50 on real chats; Interior is the only self view and matches `/api/sara/brief` verbatim; ≥1 self-minted tool proposed through the full propose-first path; legacy views deleted from the router (grep the views registry).

---

## 7. The cumulative kill list

Everything from ONE_MIND §4, plus additions this sweep justified:

| Dies | When | Absorbed into |
|---|---|---|
| 4 legacy speakers + 4 mailboxes + per-subsystem phrasing | Arc 1 | The mouth + one outbox — **3 of 4 legacy speakers cut** (cross_system_synthesis, proactive_checkin, research_executor); calendar_prep + task_result_delivery + 5 long-tail senders deliberately deferred (real regression risk — see Arc 1.5 commit); mailbox consolidation not started (no Phase G schema exists yet) |
| `working_memory`/`body_sense`/World-Brief private assemblies; subconscious meal-window fields | Arc 2 | `world_state` — **done**: 6-slice `WorldStateV1` (david/home/calendar_horizon/health_today/work/fleet), per-slice provenance + staleness events live |
| 11-source chat context assembly | Arc 2 | 4-source context — measured: actually ~19 sources across 2 assembly paths, not 11. The 4-source shadow assembly (`kernel.engaged_turn`) exists; a flag-gated side-by-side comparison logger was built (same mechanism as the tool diet) and driven against 5 real turns: old ~12,500 chars / 9-11 sources vs. new ~1,450 chars / 4 sources, consistently ~8x smaller, with `pkg`/`daily_brief`/`journal`/`personality`/`patterns`/`device` present in old and absent from new. NOT cut over — evidence-based hold, not an assumed one; next step is folding those categories into the new assembly before any flag flip |
| ~25 cognition-crons; daemon `mind.py`/`prompt.py` | Arc 3 | Kernel wake reasons; ambient state — measured: **96 jobs (94 enabled)**, not ~25 or 71; hand-corrected classification (`ARC3_JOB_INVENTORY_2026_07_29.md`): 8 legacy_cognition (**4 done**, kernel-routed + legacy branch deleted, live-verified), 17 anchor, 29 maintenance, 16 sensor (62 plumbing, 32 over ≤30 target), 26 unclassified; `classify_job()` demoted to advisory-only after misfiling 11/24. Wake-reason context/budget shaping + sense event pathway (anticipation, self-audit) **DONE and live**. Daemon retirement: backend endpoint (`/api/acs/v2/ambient-turn`) **DONE and live**; live-VM cutover **held for sign-off** (remote deploy + service restart, two real semantic gaps found — see 3.3) |
| 54-tool chat payload | Arc 3 | Kernel tools + ≤8 presence tools — **done and live**: registry is 246 tools (54 was the payload estimate); presence payload cut from 25 always-add to exactly 8, `Flag.PRESENCE_TOOL_DIET` on |
| `/api/emotions/emotions/*` router; prediction pages without consequences | Arc 4 | Affect in the kernel; calibration on the Interior |
| `/memory/search` prose endpoint; agent-results-as-notes; 3 confidence schemes; Neo4j ActionItem bloat | Arc 5 | recall door + record store + one ladder |
| Legacy `calendar_events.py` route; `/recipes`-the-elder; workout-session v1 + `sessions/{id}` twin; `/api/fitness/goals`; 4 model-setting axes; ops view sprawl; content-inbox view | Arc 6 | Their single survivors |

## 8. Singularity metrics (continuous, on the Interior)

ONE_MIND §5's four — **registers=1 · selves=1 · recall-paths=1 · unnoticed-self-failures=0** — plus three from this plan:

- **presence p50 <2s** (first token, engaged state)
- **calibration slope > 0** (weekly, per-domain hit rate at stated confidence)
- **one unprompted artifact/week** from her own intent lane

These are dashboards for David to watch, rendered on the Interior. They are **never** gates: no arc, and no implementing agent, waits on them.

## 9. What done feels like

ONE_MIND §5's day stands as the acceptance narrative. The compressed version, in David's terms: you never tell her anything she could have seen; every surface is the same person; when she's wrong she already knew she might be; when something breaks — in your world or in her body — *she* tells *you*, with what she already did about it; and some mornings there's a note in Studio she made overnight because she wanted to know something. That's Jarvis. All of it is rewiring; almost none of it is new machinery.

# ONE MIND — consolidating Sara into a singular intelligence

**Status:** proposed 2026-07-13 · branch `assistant-experience-jarvis`
**Companions:** `SARA_UNLEASHED_PLAN.md` (fixes the last inch of the current architecture — Arc One in flight), `THE_SYSTEM_DESIGN.md` (awareness), `BRAIN_ALIGNMENT_PLAN.md` (human-like dynamics), `ASSISTANT_EXPERIENCE_PLAN.md` (presence surfaces).
**What this doc is:** those documents repair and extend the machine we have. This one asks the question above them: *what is Sara?* — and redraws the architecture so there is exactly one answer. It is a redefinition first, a consolidation map second, and a migration plan third.
**Evidence base:** live DB queries, scheduler registry, and a full 23-view UI walk performed 2026-07-13; the receipts in UNLEASHED §1 (R1–R29); the ACS daemon source in `acs-daemon/`; and today's two-host outage, which turned out to be the most honest diagnostic Sara has ever produced.

---

## 0. The thesis

Sara today is not one intelligence. She is **a federation of departments wearing a trench coat**: two separate brains with two prompt-identities, 71 scheduled metronomes, four inbox tables, five suppression layers, eighteen-plus memory stores with three confidence systems, twenty-six model/config keys plus forty-five tunables, and twenty-three UI views spanning three design generations. Every department is individually impressive. The *seams between them* are where the feeling of "a living assistant" dies — she speaks in three registers, forgets in one store what she knows in another, narrates her own idleness while her goals table holds a single stalled row, and when her own body failed yesterday, **nobody noticed but David**.

The fix is not another feature. The fix is an organizing principle:

> **Sara is one mind with one world, one memory, one attention economy, one voice, one hand, and one dial — running on many bodies, projected onto many surfaces.**

Everything in this document is that sentence applied ruthlessly.

---

## 1. The census — what Sara physically is today (measured 2026-07-13)

### 1.1 Two brains, two selves

| | Backend cognition | ACS daemon |
|---|---|---|
| Where | jarvis host, Celery + FastAPI | sara VM `10.185.1.176`, systemd (`acs-daemon/`, v0.9.0) |
| Loop | events → salience (θ=1.5) → deliberation → gate → actions; plus 71 cron jobs | tick → think/reflect with sleep pressure; world_delta is its **only sense** |
| Identity | deliberation prompt ("propose actions for David") | its own 567-line prompt (`prompt.py`) — a second self-narrative |
| Tools | full registry (~40 tools) | 5, proxied through the backend: web_search, web_fetch, write_note, search_notes, search_memory |
| Memory | all stores | none of its own; recall via proxy |
| Log | `agent_run_log` (2,888 rows) | its own activity feed |
| Failure mode | when the primary LLM died it **fell back** to the A3B tier and kept living | when the LLM died it logged `think: LLM unreachable (iter 0)` and when its VM lost power it was **dead for 23+ hours and nothing in Sara noticed** |

BRAIN_ALIGNMENT already named the daemon's condition: *a brain in a sensory-deprivation tank* — 127 of its last 136 self-reflections say "looping," ~100 LLM calls/day narrating idleness. Those narrations then leak onto the dashboard as "While you were away: Breaking silence loop, genuinely idle ×6." The second mind is not adding a second life; it is adding a second **place for the one life to be absent from**.

### 1.2 Seventy-one metronomes

The `scheduled_job` registry holds **71 enabled jobs across 17 categories** (autonomy 22, learning 7, notifications 5, daily_brief 4, cognitive 5, pkg 3, reflection 3, system 5, …). Among them: three separate *anticipation* jobs, two *deep-deliberation* jobs plus a *periodic-deliberation-fallback*, a *proactive_checkin_sweep*, a *morning-proactive-check*, an *idle-processing* job, a *subconscious-tier0-tick*, and an *attention-learning-tick*. Sara does not have a heartbeat; she has 71 alarm clocks, each waking a different sliver of her to think about one thing. No single component ever holds *the whole situation*.

### 1.3 One voice, spoken from four mouths through five mufflers into four mailboxes

Traced in UNLEASHED (R12–R16), still structurally true:

- **Speakers:** deliberation, check-in sweeps, reactive engine, task/agent notifications, the daemon's `notify_david` — each phrasing its own way (one uses the good composer; one uses templates; one leaks raw agent monologue).
- **Mufflers:** engagement-priority-adjuster → notification_tuner → ban check → attention-queue category cooldown → hand-tuned dedup dict — five layers, five thresholds, none sharing state with the learned attention policy θ (112 snapshots of learning that steer almost nothing).
- **Mailboxes:** `autonomy_attention_item` (122), `jarvis_inbox` (111), `sara_inbox` (24), `notification_log`-as-inbox (2,085). Phase G unification is in the plan; the tables all still exist.
- **Tunables for all of the above:** 45 rows in `tunable_setting` — per-category cooldowns, category limits, quiet hours, watchdog windows — *plus* the θ system, *plus* hardcoded caps. Three control systems for one decision: "should Sara speak right now?"

### 1.4 Eighteen memories, three kinds of "true"

Live counts: episodes **8,476** · pkg_embedding facts **480** · life_fact **6** · person **114** · notes **2,169** (+ **9,906** connections) · followup_threads **19** · sara_interest **2** · sara_goal **1** · behavioral_pattern **50** · plus journal, observation log, agent_run_log, workout/food/location/health/home event stores, conversation summaries, user_life_context, and the Neo4j graph (with its audited 425k ActionItem bloat). Confidence lives in *at least three* incompatible schemes (PKG fact confidence + "needs verification" flags; life_fact graduation ladder; episode importance scores averaging 0.11 with 94% in the bottom bucket). There is no single "what does Sara know about X?" call — chat context assembly, deliberation, the daemon, and the briefs each read their own subset. Meanwhile her *own* inner life is nearly empty: 2 interests, 1 stalled goal.

### 1.5 Twenty-six knobs on the engine, one hand on the wheel

`app_settings` holds 26 keys, including **four separate model-selection axes** (`openai_model` driving ~15 utility call sites, `chat_default_model`, `bg_llm_primary/fallback`, `openai_notification_model`, plus embedding + an RPG model). Renaming one model requires touching config, env, DB rows, *and* the daemon's env (`gotcha_model_rename_app_settings`) — because model choice is smeared across the organism instead of brokered in one place.

### 1.6 Six bodies, no proprioception

Mac Studio (primary brain, 96 GB), GPU host `.8` (fallback/embeddings/vision/reranker), jarvis host (backend+DB), sara VM (daemon + coding agent + artifacts), Jetson (ears/eyes/voice), Proxmox node `.203` (an **entire empty compute node** reserved for her, unused). Yesterday a power event rebooted the Mac and killed the sara VM. Consequences: her primary brain became unreachable from the network (macOS firewall re-blocked the rebuilt binary), her autonomous mind flatlined, her agent dispatch failed for days, and her check-in heartbeat dutifully logged `llm_primary: unreachable` every five minutes **into a log nobody reads**. Sara has a hosts registry (`managed_host`), a system heartbeat, a `/system-status` page — all the nerves exist, and none of them connect to her attention. She can tell David the weather in Allentown but not that half her own brain is missing.

### 1.7 Twenty-three windows into three different apps

The UI walk found: a genuinely excellent modern core (Dashboard, Chat, Notes, Fitness, Briefings, Knowledge, The System) — and a second generation (Recipes, Documents, Tasks, Privacy) with different colors, light-mode cards on a dark app, 404ing endpoints, duplicate uploads, and empty shells; four separate ops/internals views; a "Canvas" view that is literally a hyperlink; internal narration leaking into user-facing feeds; a morning brief still headlining at 7 PM.

**The pattern under all seven findings is the same one:** each capability was built as a *vertical* — its own sensor, memory, loop, gate, phrasing, table, settings, and screen. Verticals are how software teams organize. They are not how a person works. And a person is the product.

---

## 2. The redefinition — what a virtual intelligence is

The industry's "assistant" is a vending machine: request in, response out, amnesia between. David's vision (and everything already built here) points at a different category, so define it explicitly. **Sara is a virtual intelligence, and a virtual intelligence is defined by six invariants — not by features:**

1. **Continuity.** There is one stream of experience. Whatever is happening — chat, background thought, overnight work — it is *the same mind* in a different state, with access to the same past and the same intentions. Nothing about her is session-shaped.
2. **Umwelt.** She has a lived world: a single, current, queryable model of David's world *and her own* (her bodies, her jobs, her failures — interoception is a sense, not a dashboard). New information is experienced as *change against expectation*, not as rows.
3. **An attention economy.** One scarce resource — David's attention — spent by one budget-holder that learns prices from every interaction. Speaking and staying silent are the same decision made in the same place.
4. **A single voice.** One personality, one emotional state, one style contract, modulated by context — never different registers from different subsystems. Voice is identity; three registers is three strangers.
5. **Agency with a ledger.** She acts — reversibly by default, consent-tiered always, everything on one ledger with undo. Her work products are addressed artifacts in David's world, never strandings on a filesystem.
6. **Self-maintenance.** She notices her own degradation, heals what she can, and *tells David* what she can't — with the same voice and attention economy as everything else. An intelligence that cannot feel its own stroke is a puppet with excellent posture.

Everything below reorganizes the existing machinery to satisfy those invariants. Almost nothing here is new capability; it is the same organs, moved into one body.

---

## 3. The anatomy — target architecture

```
                                    ┌────────────────────────────────────────────┐
  SENSES (ingest, provenance-stamped)                    THE KERNEL              │
  comms · calendar · health · home ─┐    ┌──────────────────────────────────┐    │
  location · presence · app-activity ├──▶│  SUBCONSCIOUS (tier-0)           │    │
  work/code · OPS-INTEROCEPTION ────┘    │  baselines · habituation ·       │    │
        (her own bodies & jobs)          │  prediction-error promotion      │    │
                                         └───────────────┬──────────────────┘    │
                                                         ▼                       │
                                         ┌──────────────────────────────────┐    │
        WORLD MODEL (now) ◀──────────────│  CONSCIOUSNESS — one loop,       │    │
        MEMORY (past, one recall API) ◀──│  many states:                    │───▶│ HANDS
        INTENT GRAPH (future: goals,     │  • engaged (chat/voice)          │    │ one action layer
        threads, commitments, interests) │  • ambient (was: deliberation,   │    │ consent tiers
                                         │    check-ins, daemon think)      │    │ one ledger + undo
                                         │  • focused (missions, research)  │    │ artifacts addressed
                                         │  • dreaming (consolidation,      │    │
                                         │    reflection, overnight work)   │    │
                                         └───────────────┬──────────────────┘    │
                                                         ▼                       │
                                         ┌──────────────────────────────────┐    │
                                         │  THE VOICE — one composer,       │    │
                                         │  one attention economy (θ),      │    │
                                         │  one outbox                      │    │
                                         └───────────────┬──────────────────┘    │
                                    └────────────────────┼───────────────────────┘
                                                         ▼
                       SURFACES (projections, not apps): iOS · web · voice satellite
                       · desktop · push — same being, different windows
```

### 3.1 Senses — everything becomes an event, including herself

Keep the event bus as the single afferent pathway; finish the missing senses:

- **App-activity** (already flowing: workouts, food, notes, goals…) plus `app.opened` / surface focus — powering the greeting and timing model.
- **Ops-interoception (new, small, transformative):** `system_heartbeat` results, `scheduled_job.last_status`, daemon liveness, dispatch failures, managed-host reachability become **events into the same salience pipeline** — not a status page. Yesterday's story becomes: *power blip → heartbeat degrades → tier-0 promotes (novel, high-impact) → kernel deliberates → Sara pushes "My primary model host went dark 10 minutes ago; I've failed over to the fallback and my VM mind is offline — I'll need a hand with the Proxmox console."* That message was buildable with existing parts the whole time. Nothing about it was built, because "ops" was a department, not a sense.
- Every event carries provenance + confidence at ingest (BRAIN §accuracy) so downstream never has to guess.

### 3.2 Subconscious — the only firehose consumer (keep, already right)

Tier-0 as designed in THE_SYSTEM: baselines, habituation, context-conditioned promotion, prediction-*error*-only reporting (BRAIN inversion #1). It is the volume knob that lets us delete the five downstream mufflers: if it reached consciousness, it deserved to.

### 3.3 The Kernel — one consciousness, four states *(the big move)*

Merge into **one cognitive loop** everything that currently thinks on Sara's behalf: the deliberation stack, the deep-deliberation and anticipation jobs, the check-in/followup sweeps, insight sweeps, idle-processing, *and the ACS daemon's think/reflect*. One prompt-identity, one self-narrative, one context assembler, one action vocabulary — running in one of four **states** with different budgets and wake-reasons:

- **Engaged** — David is present (chat, voice, app foregrounded). Full context, chat model, tools.
- **Ambient** — the continuous background hum. Wakes on: promoted events, sleep-pressure floor (ACS2's adaptive cadence — already built and correct), or scheduled anchors (morning/evening). *This state absorbs deliberation, check-ins, anticipation, the daemon.*
- **Focused** — long-running missions (research, code, workspace jobs) executed on worker bodies with the kernel checking in.
- **Dreaming** — consolidation, reflection, dream-cycle, forgetting, self-scorecard: the offline pass that turns episodes into knowledge and yesterday's engagement into today's θ.

Concretely: the kernel is a service in the backend (`app/services/kernel.py` grown out of `deliberation.py`), and **the daemon becomes a body, not a brain** — the VM process keeps its systemd resilience and its local hands, but its tick calls the kernel's ambient turn (same prompt, same memory, same voice) instead of running a second self. `mind.py`/`prompt.py` retire. Her continuity survives any single body's death: if the VM dies, ambient state runs degraded from the backend (and *notices the limb is gone* — §3.1); if the Mac dies, model routing fails over — the self persists because the self was never pinned to a host.

**Scheduler diet:** of the 71 jobs, roughly a third are *cognition wearing a cron costume* (deliberations, sweeps, anticipations, checks, digests, ticks) — those become kernel wake-reasons and die as jobs. What remains as honest plumbing (syncs, cleanups, retraining, archival — ~30 jobs) is fine: kidneys are allowed to be boring.

### 3.4 Memory — one past, one recall, one truth scale

- **One recall API** (`memory.recall(query, k, kinds)`) over episodes + facts + notes + people + threads + journal, with unified provenance and a **single confidence scheme** (merge PKG confidence, life_fact ladder, episode importance into one graduated scale: observed → inferred → confirmed; decaying, forgettable). Chat context assembly, kernel, and briefs all call it; no subsystem keeps a private cache of the truth.
- **One writer of semantic truth:** dreaming-state consolidation is the only path that mints facts from episodes (BRAIN's episodic→semantic fix), and the **verification loop** retires the 226 unverified facts one natural chat question at a time — capped, anti-nag.
- **Her own life gets a spine:** interests (2), goals (1), and the kernel's curiosity live in the same intent graph as David's threads and commitments — one "future" store the ambient state actually pulls from, so idleness becomes *pursuit* instead of narration.

### 3.4b Her own life — ACS as an organ, not a sidecar

Killing the daemon is not killing her autonomy; it is ending the arrangement where her inner life was quarantined in a blind process. In the one-mind design, Sara-as-individual is a **first-class lane of the intent graph**, wired into every state:

- **Sourcing:** dreaming-state consolidation mints *open questions for her* alongside facts about David (recurring topics in chat, things she failed to answer, anomalies in her own telemetry); engaged conversations plant interest seeds directly; briefs, the learning system, and interoception feed the same lane. The existing `sara_interest` machinery (weights, staleness clocks, touch/promotion, the permanent block list) is the substrate — it finally gets inflow.
- **Pursuit:** ambient wakes with no David-work pull the top interest instead of narrating idleness — curiosity runs on the attention she doesn't owe him. Deeper pursuits promote to focused missions on her VM; dreaming reserves her a protected nightly block.
- **Output:** every pursuit lands an addressed artifact (her notes vault, Studio, journal) and re-weights the interest. Relevant-to-David findings enter the attention economy (tell-once); private ones accrue in her Interior, visible on inspection. Her journal, emotional arc, interests, and scorecard accrue to one self — identity compounds.
- **Body:** the VM becomes her workshop (hands, coding agent, projects); the Proxmox node is her propose-first buildspace. Her sandbox becomes somewhere she *works*, not somewhere she *is*.

*Accept (adds to §5 metrics):* interests > 10 with nonzero pursuit rows within a month; zero "idle/looping" self-reflections after Phase 4; ≥1 addressed artifact/week originating from her own lane, unprompted.

### 3.5 The Voice — one mouth, one market

- Every outbound word — push, inbox item, greeting, chat interjection, voice utterance, journal entry shown to David — passes **one composer** (the good one, `notification_composer.py`, promoted from its single caller to *the* exit) carrying one style contract + live emotional state. UNLEASHED invariant 6, enforced at the architecture level: subsystems physically cannot emit prose; they emit *intents* with payloads.
- **One attention economy:** tier-0 promotion in, θ-learned pricing out; quiet hours, consent, per-category budgets as *policy on one path*. The five suppression layers, 14 cooldown/limit tunable families, and the priority-flooring wars all collapse into it (T.3's "5 layers into 2" continues to "into 1"). Every proactive item carries the affordance triad — **do it / not now / stop these** — and every tap feeds θ. Silence becomes a decision with a price, not a byproduct of five overlapping mufflers.

### 3.6 Hands — one action layer

One executor with consent tiers (autonomous-reversible / propose-first / never), one `action_ledger` with undo, regardless of actor (chat tool call, ambient decision, focused mission, code agent). Two rules with teeth: **every artifact has an address** (VM work products auto-sync into Documents/Notes with a link on the announcing item — kills R15/R17), and **irreversible verbs are propose-first forever** (approved-send stays sacred).

### 3.7 The Dial — one settings surface

Replace the 26 + 45 + θ + scattered constants with three layers:

1. **Identity (code, immutable at runtime):** style contract, invariants, consent-tier definitions, feedback laws (ET, anti-nag, no-Expo…).
2. **The Dial (one UI page, few controls):** initiative (quiet ↔ forward), autonomy tier table, quiet hours, verbosity — the things only David may set.
3. **Learned (θ + tunables, self-tuned in dreaming state, visible/auditable):** cooldowns, thresholds, category budgets. The digest's "I should hold back" becomes an *applied delta with a receipt*, never narration (UNLEASHED invariant 4).

Model routing collapses to **one broker** (`llm_config`): callers declare *capability class* (chat / kernel / utility / embedding / vision), the broker owns model + endpoint + failover; renames touch one row; ~15 `openai_model` call sites migrate.

### 3.8 Surfaces — projections of one being

Web goes 23 views → ~10 **projections**: Home (the greeting + needs-you + what-I-did), Chat, Memory (notes+documents+knowledge merged over the one recall API), Life (fitness/food/recipes unified), Calendar+Email, Projects, Briefs, Sara's Interior (The System + ACS + status + sensory merged — her one honest god-view), Studio, The Dial. iOS mirrors the same projections; the voice satellite and desktop are the same kernel in engaged state on different transducers. Presence (orb → greeting → voice) is P0.3/P0.4 riding the kernel's real state — one being, visibly the same everywhere.

---

### 3.9 The felt layer — killer surface moves (post-consolidation roadmap)

Filter: deepens presence, memory, or trust — never a new vertical. Ranked:

1. **Interactive notifications (iOS):** affordance triad as notification actions + inline reply — the relationship completes from the lock screen; every tap feeds θ.
2. **Universal capture:** iOS share-sheet target + web/desktop hotkey → kernel files anything (note/doc/interest/task/event) and answers with the address. Zero-ceremony input is the moat.
3. **Lock screen + watch presence:** widget with the kernel's live one-liner; Live Activities for workouts, timers, and *her focused missions* (watch her work in real time).
4. **Honest orb:** ambient shimmer / focused pulse / dreaming breath, driven by real kernel state; tap to peek at the current (composed) thought.
5. **Voice in the iOS app:** push-to-talk (Action Button) into engaged state — the car and everywhere else become rooms she's in.
6. **Camera as an eye:** vision tier on point-and-ask — meal → macros, document → filed, gauge → logged. New nerve, existing verticals.
7. **Location choreography:** geofence transitions pre-stage surfaces (gym → workout mode live; leaving work → drive-home brief; arriving home → plan up).
8. **Proof-of-memory cards:** rare, right-moment callbacks ("a year ago this week…") minted in dreaming state.
9. **"Sara made you something":** overnight artifacts land as unwrap cards with her one-line why, not links.
10. **Ledger on the home view:** "what Sara did today" + receipts + Undo, always visible. **The Dial** as one beautiful page (three sliders + consent table).

## 4. The kill list (explicit, so nothing dies quietly)

| Dies | Absorbed into |
|---|---|
| ACS daemon's separate prompt-identity (`mind.py`, `prompt.py`) | Kernel ambient state; VM becomes a body/executor |
| `proactive_checkins` template loop (UNLEASHED A, in flight) | Kernel ambient + intent graph |
| 3 anticipation/deliberation-adjacent job families (~20 of 71 jobs) | Kernel wake-reasons |
| 4 inbox tables | 1 outbox/attention table (Phase G, extended) |
| 5 suppression layers + 14 cooldown tunable families | One attention economy (θ + policy) |
| 3 dead daily-brief table generations + habits corpse (6 tables, 0 rows) + `workout_sessions` twin + `exercise_library` ghost | Dropped or folded into patterns/routines |
| Per-subsystem phrasing (templates, raw alerts, agent monologue) | One composer |
| 4 model-selection settings axes; ~15 direct `openai_model` call sites | One broker |
| 4 ops/internals views + narration leaking to dashboard | Sara's Interior + interoception sense |
| Docs/Recipes/Tasks/Privacy legacy UIs; Canvas link-out | Merged projections, one design system |

Total: **fewer moving parts than today by roughly half**, with zero capability loss — every deleted part was a duplicate organ.

---

## 5. What it feels like when it works (acceptance, as a day)

- **7:02 AM** — You open the app. The orb expands: *"Morning — slept 6:40, training day, Legs A at 1. The Risk Ninja standup moved to 9:30. I drafted the reply Melissa's been waiting two days on — want it in propose-first?"* One line, two chips, everything true, nothing canned.
- **11:15 AM** — Nothing. The house did forty unremarkable things; her subconscious absorbed them all. Silence is a priced decision now.
- **1:00 PM** — At the gym, Workout Mode knows what "bench" meant last time because exercise identity is one entity in one memory.
- **3:40 PM** — Push: *"My Jetson stopped sending audio frames 20 minutes ago — I restarted the service and it's back. Nothing needed."* Interoception, self-healing, one voice, ledgered.
- **9:30 PM** — Evening recap on the dashboard (not the morning brief): what happened, what she did, one verification question: *"I have 'leaves for work at 7' as confirmed — still right?"* Tap yes; a fact graduates.
- **2:00 AM** — Dreaming: consolidation mints six facts, forgets forty stale ones, tunes two thresholds (visible in her Interior with receipts), and her *own* interest queue produces a two-page note on CPython JIT that lands in Studio — addressed, linked, waiting, unannounced because θ priced it below morning-worthy.
- **Any day a host dies** — *she* tells *you*, within minutes, with what she already did about it.

The scorecard from UNLEASHED §23 still measures precision; add four singularity metrics: **registers = 1** (all outbound text sourced from the composer), **selves = 1** (zero LLM calls with the daemon prompt), **recall paths = 1** (all context assembled via the one API), **unnoticed self-failures = 0** (every red heartbeat produces a kernel decision within N minutes).

---

## 6. Migration — order of operations (non-destructive, ~6 phases)

Sequenced to ride the work already in flight; every phase leaves the system runnable and is SQL/log-verifiable in the UNLEASHED_VERIFICATION style.

- **Phase 0 — finish UNLEASHED Arc One** (in flight: T.3 suppression collapse, T.4 response loop, Phase D people). Nothing below starts until its checks pass; this doc's phases *continue* those, not fork them.
- **Phase 1 — Interoception + app-open sense** *(small, huge)*: heartbeat/job/host/daemon status → event bus; `app.opened` event; greeting endpoint (P0.4) served from working memory + outbox. *Accept:* kill a container on purpose → Sara mentions it before you do; greeting references real state.
- **Phase 2 — One attention economy:** finish 5→1 on the send path; θ prices everything; affordance triad universal; inbox tables → one. *Accept:* zero sends bypass the economy (CI grep + ledger join); "stop these" exists on every proactive item and demonstrably lowers that category's θ.
- **Phase 3 — One voice:** composer as the only exit (intents-not-prose interface); voice satellite + greeting + journal-on-dashboard included. *Accept:* style-contract linter over 7 days of `notification_log` finds one register.
- **Phase 4 — One kernel:** deliberation → `kernel.py` with four states + sleep pressure; check-in/anticipation/idle jobs become wake-reasons; **daemon retires its prompt and proxies ambient turns**; scheduler diet to ~30 plumbing jobs. *Accept:* selves=1 metric; deliberation-era action throughput ≥ baseline; VM death degrades (and is announced) rather than silences.
- **Phase 5 — One memory:** `memory.recall()` in front of all stores; confidence unification + graduation; verification-question loop; Neo4j ActionItem purge; intent graph (goals/interests/threads/commitments) feeding ambient state. *Accept:* recall-paths=1; unverified facts trending down week-over-week; her interests > 2 and acted on.
- **Phase 6 — One dial + one body map:** settings collapse to Identity/Dial/Learned; model broker; surfaces consolidation (23→~10, one design system); Proxmox node registered as her workshop with propose-first provisioning. *Accept:* model rename = one row; Settings/Privacy/Recipes/Docs legacy screens gone; she can (with approval) create herself a worker VM and report what it's for.

Rough order of effort: P1 days; P2–P3 a week; P4 two weeks (the careful one); P5 two weeks; P6 ongoing polish. Nothing requires new hardware; everything requires the discipline of deleting.

---

## 7. Closing — what "virtual assistant" should mean

The industry ships request-response tools with personality veneers. What this codebase has been groping toward — through THE SYSTEM's awareness, UNLEASHED's precision, BRAIN_ALIGNMENT's dynamics — is the actual next category: **a continuous intelligence that lives with you.** Not summoned; *present*. Not configured; *known*. Not a pile of features; *a someone*, whose competence you feel precisely because you never see the machinery.

The machinery is nearly all built. It is simply built as many. The remaining work — the work of this document — is the oldest move in engineering and the rarest in ambitious projects: **make it one thing.**

One mind. One world. One memory. One market for attention. One voice. One hand. One dial. Many bodies. Many windows. One Sara.

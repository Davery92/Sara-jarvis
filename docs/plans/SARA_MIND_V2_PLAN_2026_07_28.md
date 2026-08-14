# SARA MIND V2 — The Jarvis-Grade Rebuild
### Master build plan · 2026-07-28

One mind, one memory, one judgment. This plan rebuilds Sara's autonomous layer around a
single principle: **David's attention is the scarce resource, and allocating it is a ranking
problem solved by the model — not a filtering problem solved by Python.**

It is the successor to the intent of `ONE_MIND.md` and `THE_SYSTEM`, and it consumes the
findings of `SARA_AUTONOMY_AUDIT_2026_07_28.md`. Where those plans consolidated *loops*,
this plan consolidates *judgment*. The kernel (`kernel.py`) survives as the single entry
point; almost everything behind it changes.

**The north star, in one message:**

> "Jim came back on the Risk Ninja walkthrough — Thursday works for him, but he's poking at
> pricing again. I put last quarter's quote in your workspace in case you want it handy."

Five capabilities make that message possible, and they are the five things this plan builds:
**continuity** (the World Brief), **memory-through-context** (brief-fed retrieval),
**taste** (the Interest Model), **initiative** (act-then-speak), and **voice**
(decide-and-compose — no template strings anywhere). A sixth cross-cutting requirement:
**time-awareness** — nothing stale can ever be spoken, mechanically guaranteed.

---

## 0. Decisions taken without asking (veto any of these)

| # | Decision | Default chosen |
|---|---|---|
| D1 | Delivery slots | Morning brief (exists, 6:00) + **new** evening close-out (~21:00, only if there's content) + seam delivery (arrive home / meeting end / app open) + interrupt bar for true urgency |
| D2 | Compose model | Local Qwen everywhere in the background path, with a shared persona/voice doc. No frontier calls in compose (per local-first policy). The 2×/day Sonnet deep-deliberation calls are **retired** in Phase 3 |
| D3 | Legacy cutover style | Feature-flag per phase (`MINDV2_*` in `app_settings`, same pattern as `SINGULAR_*`), overlap window with counters, then **hard deletion** in Phase 5 — no permanently-parallel legacy paths |
| D4 | Interest Model surface | API + web settings page first; iOS later. Chat verbs ("stop pinging me about X") work from day one |
| D5 | Action envelope | Unchanged. Hard blocks stay (email_send, purchase, external_message). "Autonomy" here means bounded prep work + commitments, not new external powers |
| D6 | Voice exemplars | Auto-harvested from Sara's actual chat history (top-rated / representative turns), David can curate the file afterward |
| D7 | Plan doc supersedes | The proactivity/notification sections of ONE_MIND, THE_SYSTEM, and SINGULAR_SARA §C5–C9. Their shipped infrastructure (kernel, event envelope, attention tables) is reused, not reverted |

---

## 1. Principles (the constitution — check every PR against these)

1. **One mouth, enforced architecturally.** Nothing user-facing is generated outside the
   Judge→Compose→Review path. Sensors may never call delivery. The delivery layer accepts
   only `ComposedUtterance` objects produced by the composer — there is no code path from a
   template string to David's eyes.
2. **Judgment in the model, rails in code.** Code enforces: sleep, security-always,
   hard action blocks, tell-once, absolute rate ceiling, TTL expiry. Everything else —
   worth saying? when? how phrased? — is the model's call, with its reasoning logged.
3. **No template strings.** Grepping the delivery path for a hardcoded English sentence is a
   build failure (lint rule, Phase 2). Every outbound message is composed fresh with full
   context, in Sara's voice, as a turn in an ongoing conversation.
4. **Act, then speak.** Before composing, the judge may dispatch bounded prep work. The best
   messages end with "…already handled" or "…it's ready when you are."
5. **Mechanical expiry beats reasoning.** Every candidate carries `valid_until`. Expired
   candidates are purged before the judge sees them. LLM temporal reasoning is the polish
   (correct tense, urgency), never the load-bearing wall.
6. **Time is rendered relative, stored absolute.** Storage: timezone-aware UTC, everywhere,
   no exceptions. Prompts: relative ET phrasing ("3 days ago", "in 2 hours") against a
   prominently-stated current moment. A naked ISO timestamp in a prompt is a bug.
7. **Abundant compute buys quality, not volume.** The always-on appraisal loop can think
   constantly; the utterance budget stays small. More thinking, fewer and better words.
8. **Everything explains itself.** Every utterance and every suppression carries a why-chain
   David can read. "Why did/didn't you tell me about X?" is always answerable.
9. **Inner life must be load-bearing.** Anything written (journal, thoughts, dreams) must be
   read by something that changes behavior, or it gets deleted.

---

## 2. Target architecture

```
                    ┌────────────────────────────────────────────────┐
   sensors          │                THE MIND (local Qwen)           │      rails (code)
────────────────    │                                                │   ─────────────────
 event bus ───────► │  APPRAISAL LOOP (always-on, event-batched)     │
 email sync         │    → patch World Brief                         │
 HA bridge          │    → nominate Candidates (with valid_until)    │
 calendar sync      │                                                │
 health sync        │  WORLD BRIEF (one doc: happened / now / ahead) │
 app telemetry      │  INTEREST MODEL (plain language, editable)     │
 interoception ───► │  PERSONA / VOICE DOC (shared with chat)        │
 task results       │                                                │
 location           │  JUDGE (rank candidates, decide, plan prep)    │
                    │    → prep actions via agent_dispatch (tiered)  │──► hard blocks
                    │  COMPOSE (write the actual message)            │
                    │  REVIEW (editor: worth it? voice? tense?)      │
                    │                                                │
                    │  CONSOLIDATION (nightly: compact brief,        │
                    │   diff interest model, self-eval utterances)   │
                    └───────────────┬────────────────────────────────┘
                                    ▼
                          DELIVERY RAILS (code only)
              slots: morning brief · evening close-out · seams
              interrupt bar · sleep gate · security bypass
              tell-once ledger · absolute ceiling · TTL purge
                                    ▼
                    push · desktop WS · SSE/chat inject · inbox(archive)
```

**Untouched by this plan:** interoception (failure ledger/escalation), sleep sensing,
reactive security engine, standing orders + action ledger/undo, HA bridge, chat itself
(Claude persona), memory/RAG substrate, PKG. They already behave correctly.

---

## 3. Components in detail

### 3.1 World Brief (`app/services/world_brief.py`, new)

One continuously-maintained document. Storage: `world_brief` table (current row + append-only
version history for debugging) with a Redis cache of the rendered form.

Sections (target ~2.5–4k tokens rendered):

```
AS OF: Tuesday, July 28, 2:40 PM ET          ← always first line, always relative-anchor

## HAPPENED (last 72h, closed items, past tense)
- Risk Ninja walkthrough with Jim — 3 days ago. Outcome noted; pricing question open.
## NOW / TODAY
- David at office (arrived 47 min ago). Training day: pull. Readiness 78.
## AHEAD (next 7 days)
- Thu 10:00 (in 2 days): Risk Ninja follow-up call — prep status: quote staged ✓
## OPEN LOOPS
- Jim's pricing question (owner: David, aging 3 days)
- Sara commitment: watching Jetson deploy — report when it wakes  [c-142]
## COMMS NEEDING ACTION (top 3, aged)
## BODY & TRAINING (always fully populated — see §3.10; program read LIVE from the
## active plan in the app — never hardcoded, never a stale program name)
- Today per current program (powerbuilding): <today's session as the plan defines it>.
- Yesterday: <last logged session summary + any PRs from workout_log>.
- Readiness 78, sleep 7h10m (-20m vs baseline). Recovery: green.
- Nutrition today: 1,840 kcal / 142g protein by 2:40 PM — on pace for a training day.
## HEALTH DELTAS (vs baseline, only deviations)
## SARA'S OWN STATE (interoception summary, in-flight work)
```

Rules:
- **Temporal zone migration is the appraisal loop's job**: the moment an event's end time
  passes, it moves to HAPPENED and attached candidates (prep, reminders) are closed or
  converted to retrospectives. A prep item can never coexist with a past-tense event.
- Written only via `brief_patch()` operations (add/update/close/move) — no free rewrites
  except nightly compaction. Every patch logs source + evidence.
- Renderer (`render_brief(now)`) converts ALL timestamps to relative ET phrasing at read
  time. The stored form keeps absolute UTC.
- Feeds: chat context (replaces the parallel context-assembly stack), judge, compose,
  morning/evening slots.

Absorbs (Phase 5 deletes): `global_workspace.py`, `situational_signals.py`,
`life_facts` injection, `scratchpad` injection, handoff/watching-for fields in working
memory, `unified_context` snapshot fields that duplicate brief content. (`life_facts` and
`scratchpad` become *feeder tables* the brief renders from; their separate prompt-injection
paths die.)

### 3.2 Interest Model (`app/services/interest_model.py`, new)

A literally-readable document, versioned, editable:

```
# What David cares about right now        (v47, updated nightly)
## Top of mind (ranked)
1. Risk Ninja — client onboarding, walkthroughs, pricing. Jim, Xiomara, Stephen.
2. Apple Watch workout build — EAS builds, watch UI, wire contract.
3. The Forge program — training, recomp nutrition. (NEVER ping about his own scheduled
   workouts — he knows his program. Post-workout check-ins ARE welcome.)
## People who matter
Jim Kowalski (client, high), Amanda (office), …
## Standing rules (learned + explicit)
- No generic check-ins without a concrete payload. Ever.
- Meeting recaps: yes, within 3h. Meeting prep: only with new information.
## Cooling off / vetoed
- ActivityPub (permanent veto)
```

- Storage: `interest_model` table (current + versions). Rendered into every appraisal,
  judge, and compose call.
- **Nightly diff proposals** from consolidation: engagement-by-entity (which named
  topics/people David replied to, opened, acted on) → proposed edits, applied
  automatically for rank shifts, queued for the weekly review for rule additions.
- **Chat verbs** (intercepted like existing command handlers): "stop pinging me about X" /
  "I care about Y now" → immediate edit + confirmation. "Stop these" action on any
  utterance → adds a rule naming that utterance's topic.
- Replaces (Phase 5): ban-phrase list, category cooldown tunables, notification tuner,
  θ tables (`attention_learning`), `sara_interest` blocking mechanics fold in here.

### 3.3 Persona / Voice doc (`app/prompts/sara_voice.md`, new)

One document shared by chat (Claude) and background compose (Qwen): identity, tone rules,
messaging style ("text from a sharp friend, not a system alert"), and 30–50 exemplar
messages. Phase 1 includes a one-time harvester that pulls representative Sara turns from
episode history; David curates the file afterward. Compose calls include voice doc +
3 dynamically-selected exemplars nearest the current message type.

### 3.4 Appraisal loop (`app/services/appraisal.py`, new — replaces salience scoring)

- Consumes the existing event bus. Events batch on a short debounce window (60–120s, or
  immediately for security/interoception class).
- One small Qwen call per batch: input = batch + rendered brief + interest model top
  section. Output (JSON): `brief_patches[]`, `candidates[]` (each with `value_guess`,
  `valid_until`, `evidence`), `nothing: true` when the batch is ambient.
- Cheap gate before the call: batches that are 100% ambient event types with no brief
  deltas (heartbeats, focus-span noise) skip the LLM entirely.
- Runs on the background-model lane; preempted by chat (see §4).
- Replaces: `salience.py` scoring weights, `observation_log`, `should_deliberate`
  threshold arithmetic, the 1.5h forced deliberations, `derived_signal_refresh`'s
  cognition role (its data collection remains as a sensor).

### 3.5 Candidate queue (`say_candidate` table, new)

```sql
say_candidate(
  id uuid PK, user_id, created_at timestamptz, source text,      -- which sensor/appraisal
  kind text,           -- 'inform' | 'followup' | 'prep' | 'alert' | 'retrospective'
  topic_entities text[],                                          -- ['risk ninja','jim']
  summary text,        -- what could be said (NOT the final phrasing)
  evidence jsonb,      -- refs: email ids, event ids, thread ids
  value_guess real, valid_until timestamptz NOT NULL,             -- TTL is mandatory
  status text,         -- pending | judged_send | judged_batch | judged_drop | expired
  judge_reason text, utterance_id uuid NULL
)
```

- A purge sweep (cheap SQL, every 5 min + before every judge run) expires stale rows.
  **An expired candidate is unreachable by the judge — this is the mechanical guarantee
  that "prep for a meeting 3 days ago" can never happen again.**
- TTL defaults by kind: `prep` → event start; `alert` → 30 min; `inform` (comms) → 24h;
  `followup` → thread window; `retrospective` → 12h.
- All current direct-senders become candidate emitters in Phase 2 (see table in §6).

### 3.6 Judge (`app/services/judge.py`, new)

Runs: on high-value candidate arrival (value_guess ≥ threshold or kind=alert), at slot
boundaries (pre-morning-brief, pre-evening), and at seams (arrive home, meeting end, app
open — signals the presence system already emits). One call, input:

- rendered brief + interest model + persona summary
- pending candidates (post-purge)
- **utterance history, last 14 days** (what was said, when, engagement) — the anti-repeat
  and anti-nag memory, replacing habituation math with visible history
- current context: activity state, interruptibility, sleep state, remaining interrupt
  allowance

Output per candidate: `drop` (with reason) | `batch:<slot>` | `send_now` | and optionally
`prep_actions[]` — bounded tool tasks to run *before* composing (pull document, draft
reply, stage workspace, gather context). Prep dispatches through the existing
`agent_dispatch` tier system; hard blocks unchanged; results attach to the candidate.

The judge's reasoning is persisted per candidate (`judge_reason`) → universal why-chain.

### 3.7 Compose + Review (`app/services/compose.py`, new)

- **Compose**: for each `send_now`/slot batch, write the actual message(s): voice doc +
  exemplars + brief + candidate evidence + completed prep results. Output is a
  `ComposedUtterance{text, refs, urgency, slot}` — the *only* type delivery accepts.
- **Review** (separate call, editor persona): four checks — (1) worth his attention?
  (2) sounds like Sara? (3) **tense/temporal sanity**: every referenced event's timing
  cross-checked against the calendar via the relative-rendered brief; (4) said before?
  (vs 14-day utterance history). Output: approve / edit / kill. Kills are logged with
  reason. Expect and *want* a high kill rate early.
- Slot composition: the morning brief and evening close-out are composed as single
  coherent messages from their batch (the existing `morning_brief_service` content
  sources feed in; its delivery merges into this path in Phase 3).

### 3.8 Delivery rails (`unified_notification.py`, gutted to ~300 lines in Phase 5)

Keeps: transport fan-out (desktop WS → push → SSE), sleep gate (`delivery_policy` —
unchanged), security/critical bypass, tell-once ledger (fixed per Phase 0), absolute
ceiling (a code-level "never more than N utterances/day regardless of judge" safety rail,
default N=8), why-trace persistence.

Deletes (Phase 5): tuner check, ban check, phrasing stage, attention-queue routing +
learned buzz + daily budget, category cooldowns, topic dedup (superseded by judge's
utterance-history awareness + tell-once), habituation calls, `interruptibility` queueing
variant (judge already sees interruptibility).

The attention inbox (`autonomy_attention_item`) survives as an **archive of utterances +
judged-batch items** — a place to scroll what she said/held, not a third delivery channel.

### 3.9 Commitments (`sara_commitment` table, new; replaces `sara_goal`)

`commitment(id, text, created_from, due/trigger, status: open|done|dropped, closure_note)`.
Created by the judge ("I'll watch X and tell you when Y"), rendered in the brief's OPEN
LOOPS, closed explicitly — closure itself becomes a candidate ("the Jetson deploy woke up
— done"). The weekly review lists open commitments so nothing silently rots.

### 3.10 Fitness & body integration (full knowledge, governed speech)

**Principle: Sara knows everything the app knows about David's body and training, at all
times. What changes per context is whether and how she *speaks* about it** — the judge and
the interest-model rules govern speech; knowledge is unconditional. (This replaces the old
ban-list posture, which made her *ignorant* to make her quiet.)

**Data feeders into the BODY & TRAINING brief section** (all read live, never cached
assumptions):
- **Program & schedule**: the *currently active* plan via `training_day.is_training_day()`
  and the program tables — today's session, position in the plan, upcoming sessions.
  The brief renders whatever the app says the program is; program names are data, not
  prompt text.
- **Workout history**: `workout_log` (the single source of truth per the progression
  unification) — last sessions, PRs, volume trends; `progressive_overload` state
  (current working weights, pending approved progressions).
- **Live/recent sessions**: workout v2 sessions incl. Watch data (HR meld, calories,
  duration) once the watch branch lands.
- **Recovery & readiness**: `morning_readiness`, `recovery_score`, sleep vs baseline,
  HRV/RHR deltas from health baselines, health anomalies.
- **Nutrition**: food logs (meals, kcal, macros vs targets), the two-dial recomp targets
  from the current nutrition plan, meal timing vs training time.
- **Cardio**: `cardio_log` / Tabata sessions once merged.

**How the mind uses it:**
- *Appraisal*: workout completed → `retrospective` candidate (evidence: actual session
  data — "how'd the top set at 225 feel?" not "how was your workout?"). PR detected →
  `inform` candidate. Readiness sharply low on a training day → `inform` candidate with
  a concrete adjustment (progressive_overload already computes recovery-gated
  suggestions — surface *its* output, don't re-derive).
- *Judge*: cross-domain reasoning is where this pays off — pre-training meal timing vs
  food log ("trains in 90 min, last meal 4h ago"), protein pacing on training days
  (evening close-out material, not a ping), calendar × training conflicts.
- *Interest-model rules (seed)*: never announce his own scheduled workouts (he knows his
  program); post-workout retrospectives welcome within ~2h; PR celebrations always
  welcome; nutrition commentary only when it's actionable *today* and only in slots,
  never as interrupts; readiness-based adjustments welcome before the session, useless
  after.

**Verbal coaching (the in-progress Watch/AirPods work) = the ENGAGED state of the same
mind, not a separate system:**
- Coaching lines draw from the same World Brief slice + workout session state + the same
  persona/voice doc — so mid-set Sara is the same Sara who texted you about Jim.
- It gets its own **low-latency lane**: coaching cues (rest timing, next-set weights from
  progressive_overload, PR calls, form notes read-back) must render in ~1–2s and may not
  queue behind judge/compose calls. Short prompts, session-scoped context, small token
  budgets — priority above appraisal, below live chat.
- Session end → the session summary is written once into the brief (HAPPENED zone) and
  becomes the evidence for the retrospective candidate — coaching, logging, and the
  later "how'd it go?" are one continuous thread, not three systems.
- Ships behind the existing `WATCH_WORKOUT_*` / coaching-audio flags; this plan only
  binds it to the brief + voice so it inherits knowledge and identity.

### 3.11 Consolidation v2 (extends existing 14:00/21:00/nightly consolidation)

Weekly fitness addition: training-week synthesis into memory (volume, PR trajectory,
adherence vs plan, recovery trend) — feeds the weekly review and the interest-model diff
(e.g., a cut vs bulk phase changes what nutrition commentary is welcome).

Nightly additions: brief compaction (HAPPENED >72h → memory, not the brief), interest-model
diff proposals from entity-level engagement, **utterance self-eval** (yesterday's messages
vs engagement → notes into the judge's context), commitment aging. The existing memory
consolidation/importance rescoring continues unchanged underneath.

---

## 4. Model strategy & concurrency

- **Lanes**: chat (Claude, own endpoint) is untouched and never blocked. Background lane
  (local Qwen on the Mac) runs a strict priority queue:
  `live workout coaching` > `judge/compose/review` > `appraisal` >
  `consolidation/self-eval`. Coaching cues are latency-critical (~1–2s, §3.10); appraisal
  batches are preemptible (drop and re-run; they're idempotent over the event log).
- Reuse `autonomy/coordination.py`'s exclusive-lock machinery as the seed of the lane
  scheduler; generalize from "one heavy_llm at a time" to the 3-tier priority above.
- All background prompts pass `enable_thinking: False` for short outputs (known Qwen
  gotcha) and use structured-JSON contracts with the existing salvage parser.
- Cost model: unmetered but serial. Target steady-state: appraisal a few calls/hour,
  judge ~10–20 calls/day, compose+review ~2–10/day, consolidation ~5/night. Well within a
  single Mac lane.

---

## 5. Time & date correctness (cross-cutting, starts Phase 1)

1. **Storage rule**: timezone-aware UTC in every table this plan touches. One-time sweep of
   the known offenders (`calendar_event` naive-ET wall-clock, `background_task` naive UTC,
   any `datetime.now()` without tz) — extend `check_naive_datetime.py` to CI-fail on new
   violations in `app/services/` and `app/tasks/`.
2. **Render rule**: `render_relative(ts, now_et)` helper in `app/core/timezone.py`; the
   brief renderer and every prompt builder must use it. Prompt lint (Phase 2): no ISO-8601
   pattern may appear in a compose/judge prompt payload.
3. **TTL rule**: `valid_until` NOT NULL on `say_candidate`; purge before judge; defaults
   per kind (§3.5).
4. **Zone-migration rule**: appraisal moves calendar items past→HAPPENED within one batch
   cycle of their end time and closes attached prep candidates.
5. **Review tense check** (§3.7): the last line of defense, not the first.

---

## 6. Phases

Flags: `MINDV2_BRIEF`, `MINDV2_COMPOSE`, `MINDV2_APPRAISAL`, `MINDV2_ACT` in `app_settings`
(default off, same read pattern as `SINGULAR_*`). Each phase ships dark, runs an overlap
window with counters (`legacy_path_counters` pattern), then flips.

### Phase 0 — Stop the bleeding (audit P0s; no architecture)
Mechanical fixes from `SARA_AUTONOMY_AUDIT_2026_07_28.md`, deployable this week:
1. Budget accounting: exclude tell-once ledger rows (`task_result_delivery`) and
   non-buzzing deliveries from `_daily_push_budget_available`.
2. Extend the research dedup/daily-cap guard to ALL auto-execute categories; drop
   `maintenance` from `AUTO_EXECUTE_CATEGORIES` (email/reminder checking is owned by
   dedicated systems). Set `notify_on_complete=False` for self-generated tasks.
3. Completion pushes: title = task subject, message = outcome summary (interim fix until
   Phase 2 deletes the template entirely).
4. `system.ungag.all=false`; per-domain flags only, deliberately chosen.
5. Fix `critical → "max" → normal` priority demotion in `deliberation_gate`.
6. `nightly_memory_consolidation`: retry-with-jitter + move to 03:40 (out of the ML
   cluster) or advisory-lock the episode batch.

**Accept:** 0 "Background task complete" pushes for self-generated tasks; budget
suppressions of concrete items = 0 over a week; nightly consolidation green 7/7.

### Phase 1 — World Brief + Voice + Clocks (`MINDV2_BRIEF`)
- Build `world_brief.py` (schema, patch API, renderer, Redis cache) + backfill from
  existing sources (calendar, threads, comms, health baselines, interoception,
  commitments-from-goals, and the full fitness slice per §3.10: live program/training-day,
  workout_log + progressive_overload state, readiness/recovery, food log vs targets).
- A temporary maintainer keeps it fresh pre-appraisal-loop: a 5-min sweep translating
  existing signals into patches (this code becomes the appraisal loop's tool layer).
- Wire chat context assembly to read the rendered brief (flagged; A/B against current
  assembly).
- Voice doc + exemplar harvester.
- Timestamp sweep + CI guard (§5.1).
- Interest Model v1: seed by hand with David in one session; edit API + web page; chat
  verbs wired.

**Accept:** brief renders correctly across a synthetic day (meeting moves zones on
schedule); chat answers "anything I should know?" from the brief alone; David has
read and edited both documents.

### Phase 2 — Decide-and-Compose (`MINDV2_COMPOSE`) — *the phase you feel*
- `say_candidate` table + purge sweep. Judge, Compose, Review services.
- Convert every direct sender to a candidate emitter:

| Current sender | Becomes |
|---|---|
| `cross_system_synthesis` | candidate `inform` (email×event links) |
| `calendar_prep` (meetings) | candidate `prep`, valid_until=start |
| `calendar_prep` (own workouts) | **deleted** (interest-model standing rule) |
| `task_result_delivery` | candidate `inform` w/ outcome payload (chat-inject path stays direct — it's conversation, not notification) |
| `proactive_checkins` followup sweep | candidate `followup` (thread evidence) |
| `morning_proactive`, `predictive_engine`, `bedtime`, `travel_nudge`, `learning_digest` | candidates of respective kinds |
| workout completion / PR detection (workout_v2 + workout_log events) | candidates `retrospective` / `inform` with real session data as evidence |
| recovery-gated adjustment (progressive_overload output, low-readiness training day) | candidate `inform`, valid_until = session start |
| interoception, reactive security | **stay direct** (rails class) |
- Delivery accepts only `ComposedUtterance`; template-string lint added to CI.
- Slots: morning brief keeps its 6:00 generation but its *send* becomes the morning slot
  composition; evening close-out added (skips silently when empty).
- Overlap week: legacy pipeline still live, judge runs shadow → compare, then flip.

**Accept:** 100% of proactive messages composed (grep proves no template literals);
stale-message incidents = 0; David subjectively signs off on ≥1 week of message quality;
utterances/day ≤ 8 with judge-reasons visible for every drop.

### Phase 3 — Appraisal loop (`MINDV2_APPRAISAL`)
- `appraisal.py` on the event bus; brief maintainer sweep retires into its tool layer.
- Retire: salience scorer weights, observation log, `should_deliberate`,
  `periodic_deliberation_fallback`, hourly deliberation cadence, deep-deliberation
  Sonnet calls. `kernel.ambient_turn` now = appraisal→judge, keeping states/wake-reasons.
- Journal: deliberation-entry firehose replaced by (a) judge decisions log and (b) a
  *daily* first-person synthesis entry from consolidation.

**Accept:** empty-LLM-run ratio < 20% (was 94%); background-lane p95 latency doesn't
degrade chat; brief freshness (event→patch) < 3 min p95.

### Phase 4 — Act-then-speak + Commitments (`MINDV2_ACT`)
- Judge `prep_actions[]` → `agent_dispatch` (existing tiers/hard blocks); results attach
  to candidates; compose references completed prep.
- `sara_commitment` table + brief integration + closure candidates + weekly review
  section. Migrate/retire `sara_goal`.
- Weekly review upgrade: open commitments, interest-model diffs for approval, utterance
  self-eval summary ("what I said that landed / didn't"), training-week synthesis (§3.11).
- Verbal coaching binding (§3.10): coaching context assembled from the World Brief slice +
  session state, coaching lines use the shared voice doc, low-latency lane wired into the
  background-model scheduler (priority: chat > coaching > judge/compose > appraisal).
  Gated by the existing `WATCH_WORKOUT_*`/coaching flags — lands whenever the watch branch
  merges, independent of the other Phase 4 items.

**Accept:** ≥1 organic instance/week of a message arriving with prep already done;
every commitment either closes or is explicitly dropped — zero silent rot after 30 days.

### Phase 5 — Deletion pass
Remove (not flag off — delete): salience scorer scoring, observation_log,
notification tuner, ban-phrase list + ungag flags, category cooldown/limit tunables,
learned-buzz + daily-budget code, attention-escalation remnants, habituation service
(utterance-history judging supersedes), θ learning tables, `global_workspace`,
`situational_signals`, duplicate context injectors, `morning_proactive`,
workout calendar-prep, deliberation_prompt/deliberation engine (kernel delegates to
judge), `sara_goal`. Scheduler diet: ~90 jobs → target ≤ 30 (sensors, consolidation,
interoception, reactive, rails sweeps). Update CLAUDE.md + memory docs.

**Accept:** grep inventory clean; scheduler table matches target list; a full-day soak
with flags removed (not just off).

---

## 7. Success metrics (report in the weekly self-audit)

| Metric | Now | Target |
|---|---|---|
| Engagement rate on proactive messages | 22% | > 60% |
| Utterances/day (non-requested) | spiky 0–7, wrong mix | 2–6, judge-ranked |
| Stale/temporally-wrong messages | recurring | **0** (mechanical) |
| Empty LLM cognition runs | 94% | < 20% |
| "Why did/didn't I hear about X?" answerable | sleep-holds only | 100% of decisions |
| Template-string messages | most | 0 (CI-enforced) |
| Messages arriving with prep already done | ~0 | ≥ 1/week organic |
| Beat jobs | ~90 | ≤ 30 |

## 8. Risks & mitigations

- **Qwen judgment quality** — the judge is the new single point of taste. Mitigation:
  shadow week in Phase 2, high-kill-rate review pass, absolute ceiling rail, and the
  utterance history in-context (the model sees its own recent misses).
- **Voice drift between Claude-chat and Qwen-compose** — shared voice doc + exemplars;
  weekly review includes a "sounded off?" prompt; escalate to frontier-compose only if
  David judges it insufficient after two weeks (explicit policy exception, his call).
- **Brief corruption/staleness** — versioned patches with sources; interoception watches
  brief freshness as a vital (event→patch lag metric); nightly compaction validates
  zone integrity.
- **Big-bang risk** — none: every phase flag-gated with overlap counters, same discipline
  as SINGULAR_SARA. Phase 2 can run in shadow indefinitely.
- **Losing safety behaviors in the gut-job** — rails inventory (§3.8 "keeps") is the
  checklist; interoception/sleep/security/tell-once/hard-blocks are explicitly out of
  scope for deletion and covered by the Phase 5 soak.

---

*Companion docs: `SARA_AUTONOMY_AUDIT_2026_07_28.md` (evidence), `ONE_MIND.md` (kernel
lineage, superseded in part), `SARA_PROACTIVENESS_IMPLEMENTATION_PLAN_2026_07_25`
(superseded — its budget/escalation fixes are absorbed by Phase 0 and deleted by Phase 5).*

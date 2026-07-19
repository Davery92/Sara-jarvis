# Brain Alignment Plan — closing the gaps between Sara and a human mind

**Status:** proposed 2026-07-07 · companion to `SARA_UNLEASHED_PLAN.md` (does not duplicate it)
**Audience:** an implementing agent. Every phase is self-contained: evidence → design → tasks → acceptance → verification. Work top-to-bottom unless told otherwise.

---

## 0. Thesis

Sara has structural analogs for most of the human cognitive stack — salience/attention,
working memory, episodic memory, consolidation, emotion, prediction, deliberation. The
remaining gaps are not missing organs; they are three behavioral inversions relative to
how brains actually work, plus one starved subsystem:

1. **She reports prediction *confirmations*; brains report prediction *errors*.**
   Human perception runs on predictive coding — expected input is suppressed, only
   surprise reaches awareness. Sara pushes "the light turned off at 18:00 like it always
   does, 100% confidence."
2. **She doesn't habituate at the source.** Downstream dedup blocks repeats, but the
   generators never learn; the same bid for attention is regenerated forever.
3. **Her memory is flat.** 8,400 episodes, average importance 0.11, 94% in the bottom
   bucket, no forgetting, and only 476 semantic facts distilled out. Everything is
   stored; nothing is felt; little becomes knowledge.
4. **The ACS daemon is a brain in a sensory-deprivation tank.** It is alive and honest,
   but has zero input streams, so it burns ~100 LLM calls/day narrating its own
   idleness (127 of its last 136 self-reflections say "looping").

## 0.1 Rules for the implementing agent

- Read `SARA_UNLEASHED_PLAN.md` §2 "Operating invariants" first — all of them bind here too.
- **Deployed code lags the working tree.** The backend/celery containers load code at
  restart only. After each phase: rebuild + restart, then verify against the live DB
  (verification SQL is included per phase). Do not declare a phase done from the diff.
- All hour/date logic in ET via `app.core.timezone` helpers. Never naive `datetime.now()`.
- pgvector casts: `CAST(:param AS vector)`, never `:param::vector`.
- Short LLM utility calls: pass `enable_thinking: False`.
- New tunables go through `app/services/tunables.py` so they're adjustable without deploys.
- DB is `postgresql://sara:sara123@10.185.1.180:5432/sara_hub` (or `docker exec jarvis-db-1 psql -U sara -d sara_hub`).

## 0.2 Receipts (measured 2026-07-07 against the live DB)

| Fact | Evidence |
|---|---|
| Pattern-confirmation pushes still live | `notification_log` 2026-07-07 22:43: "computer light usually turns off around 18:00 … 100% confidence"; sources `predictive_engine` (11) + `attention_escalation` (7) in last 10 days |
| Confirmations earn zero engagement | 54 narrator observations in June: 54 read, **0 engaged** (subsystem since removed; the pattern held) |
| Template check-in spam ended only with UNLEASHED Phase A | "Morning — how's the day shaping up?" generated 82× in 21 days, last at 2026-07-06 15:00Z |
| Check-in engagement | 137 check-ins / 21 days, 45 engaged (33%) |
| Memory is flat | 8,400 episodes; avg importance **0.11**; 7,902/8,400 in lowest quintile; 9 missing embeddings |
| Episodic→semantic conversion is a trickle | 476 `pkg_embedding` facts vs 8,400 episodes |
| Scheduling ignores autobiographical facts | 2026-07-07: gym-bag reminder set wrong **twice** (12:45 lunch guess, then "8:15 before Legs A at 9") before David stated: leaves 7am, gym at 1pm lunch |
| Immediate recency is the weakest tier | Same question ("who am I overdue to reconnect with?") answered identically twice, 2 min apart, no acknowledgment; "let's talk about it" 90 min after a goal request → "I'm not sure what 'it' refers to" |
| Tool errors leak as speech | Assistant turn verbatim: "Invalid tool arguments: Unterminated string starting at: line 1 column 11" |
| Capability self-model inconsistent | 17:19 "I don't have a tool to save your location"; 22:50 saved location fine with that tool |
| No internal clock in deliberation | `agent_run_log` handoff note: "Assumed late night (~10:40 PM) based on observation timestamps" |
| ACS is idle-looping | 670 thoughts / 7 days; reflections: 127 "looping", 6 "idle", 1 "productive"; 0 `notify_david`, 0 inbox items, 0 open goals, 1 interest (blocked); 57 "think turn raised" errors |

---

# PART ONE — PERCEPTION: report surprise, not confirmation

## Phase H1 — The predictive-coding flip (1 day)

**Human analog:** the cortex suppresses expected input; only prediction *error* is
propagated upward. A confirmed expectation is silence.

**Current behavior:** `predictive_engine.py` and `daily_rhythm.py` emit
"usual pattern happening on schedule" observations; `app/tasks/attention.py:159`
(`attention_escalation`) then *escalates* stale unengaged ones into pushes.
Confirmations of the model reach David; that is exactly backwards.

**Design:**
- Every rhythm/pattern evaluation is classified `confirmation | deviation | novel` at
  the source.
- `confirmation` → written silently to the world model / `home_state_summary`
  (deliberation may still read it as ambient context). **Never** creates a
  notification, attention item, or check-in. It also *strengthens* the pattern
  (H2 counters weakening).
- `deviation` (expected X by time T, X didn't happen — or X happened way off-window)
  and `novel` (no pattern exists) are the only grades that may create an attention item,
  and the payload must say what was *violated*: "Side door opened at 2:04am — first
  time outside 7am–11pm in 60 days."
- Delete "100% confidence based on your learned rhythm" phrasing everywhere. Confidence
  is internal state, not conversation. (UNLEASHED T.1's payload lint should reject the
  word "confidence" in user-facing check-in/pattern text — add that rule.)

**Tasks:**
1. `predictive_engine.py`: add the three-way grade to prediction evaluation; route
   confirmations to silent world-model write; keep deviation/novel paths.
2. `daily_rhythm.py`: same grading for rhythm windows ("winddown coming up" fires only
   if David is *off* rhythm in a way that matters — e.g., meeting scheduled into his
   usual winddown — otherwise silent).
3. `app/tasks/attention.py`: escalation must skip items whose metadata grade is
   `confirmation` (and backfill: archive any queued items matching that grade).
4. `deliberation_prompt.py` check-in rule: forbid pattern-confirmation content in
   proposed check-ins; deviations only.
5. Payload lint: add banned-phrase rules ("usual pattern", "learned rhythm",
   "% confidence", "right on schedule").

**Accept:** zero notifications/attention items whose content restates an on-schedule
pattern for 14 consecutive days; deviation alerts still fire (inject a synthetic
off-schedule event to prove the path is alive, not just quiet).

**Verify:**
```sql
SELECT count(*) FROM notification_log
WHERE created_at > now() - interval '14 days'
  AND (message ILIKE '%usual%' OR message ILIKE '%learned rhythm%'
       OR message ILIKE '%confidence%' OR message ILIKE '%on schedule%');
-- must be 0
```

## Phase H2 — Habituation at the generator (1 day, shares plumbing with H1)

**Human analog:** habituation — a repeated stimulus that produces no response stops
being generated at all, not merely filtered at the mouth.

**Current behavior:** `unified_notification.route_through_attention_queue` makes a
learned buzz decision (UNLEASHED T.4), but generators regenerate the same candidate
forever; dedup absorbs the spam (82 identical check-ins in 21 days pre-Phase-A). Dedup
is a hand over the mouth; habituation is losing the urge.

**Design:**
- New table `stimulus_habituation` (`generator`, `stimulus_key`, `strength` float
  default 1.0, `last_fired_at`, `last_engaged_at`).
- Shared helper `app/services/habituation.py`:
  - `should_generate(generator, stimulus_key) -> bool` — rolls against `strength`.
  - On delivery with no engagement (no `read_at`+`engaged` within 24h — reuse
    T.4's engagement signal): `strength *= 0.5`.
  - On engagement: `strength = min(1.0, strength * 2)`.
  - Recovery: +0.05/day toward 1.0 (spontaneous recovery, so nothing is muted forever).
  - `strength < 0.1` → generator must not even build the candidate (saves the LLM call).
- Wire into every proactive generator: `predictive_engine`, `daily_rhythm` deviations,
  `proactive_checkins.run_followup_sweep` topic classes, calendar_prep,
  deliberation-proposed check-ins (key = category+topic), email nudges.
- Cross-check: `dedup_blocked=true` rows are the tell that a generator is not
  habituating — alert on >3 dedup blocks for one stimulus_key in 7 days (J.1 funnel test).

**Accept:** after two ignored deliveries of a stimulus class, the third is not
generated (assert via `stimulus_habituation.strength < 0.3` and absence in
`notification_log`); an engaged stimulus class recovers to strength ≥0.8 within a week.

**Verify:**
```sql
SELECT left(coalesce(message,title),60), count(*) FROM notification_log
WHERE created_at > now() - interval '14 days'
GROUP BY 1 HAVING count(*) > 3 ORDER BY 2 DESC;
-- empty, or every row maps to a stimulus with recent engagement
```

# PART TWO — MEMORY: feel it, keep what matters, forget the rest

## Phase H3 — Autobiographical facts are law + one-shot correction encoding (1–2 days)

**Human analog:** autobiographical memory dominates generic schemas, and a surprising
correction ("no — I leave at 7") is encoded in one shot with high durability
(prediction error → strong plasticity).

**Current behavior:** David's stable life rhythms exist as *learned patterns with
confidence*, not as consultable facts. Reminder scheduling guessed twice from plan data
("Legs A at 9") while "leaves for work at 7am, trains at 1pm lunch" was stated in the
same conversation. Corrections update nothing durable.

**Design:**
- New PKG fact class `life_fact` (subject=David, predicate from a small controlled
  vocabulary: `departs_for_work_at`, `trains_at`, `lunch_at`, `winds_down_at`,
  `wakes_at`, `works_from`, weekday-conditioned) with `source: stated|inferred` and
  `authority: stated > inferred`. Seed the obvious ones from existing rhythm data as
  `inferred`; David's statements upgrade them to `stated`.
- **Consult-before-schedule:** any tool that picks a time on David's behalf (reminder
  creation, calendar suggestions, check-in timing, deliberation-proposed reminders)
  must call a new `life_facts_for(day)` helper and pass the result into the
  prompt/logic. A reminder that lands inside a known conflict (after he's left, during
  the gym block) must be flagged in the tool result so the LLM re-picks.
- **Correction detector:** in the chat pipeline (where implicit_feedback_detector
  already hooks), when David contradicts a time/schedule assumption Sara just used
  ("the gym's at 1", "I leave at 7"), synchronously upsert the corresponding
  `life_fact` as `stated` before the reply is generated, and have the reply confirm
  the durable fact ("got it — you're out the door at 7; I'll remember that").
- Weekly consolidation re-checks `inferred` facts against rhythm data; `stated` facts
  are only changed by David.

**Accept:** replay the gym-bag scenario (eval fixture): first correction produces a
`stated` life_fact and the next scheduling attempt uses it — zero second corrections.
No reminder in 30 days scheduled inside a `stated` conflict window.

**Verify:** `SELECT * FROM pkg_embedding WHERE fact_type='life_fact'` shows seeded +
stated rows; grep reminder-creation code path calls `life_facts_for`.

## Phase H4 — Emotional encoding + real forgetting (2 days)

**Human analog:** the amygdala tags emotionally intense moments for strong encoding;
sleep consolidates the gist into semantic memory; the rest decays. Forgetting is a
feature — it is what makes retrieval sharp.

**Current behavior:** `importance_scorer.py` weighs recency/frequency/popularity/
user_rating — **no emotion, no novelty**. Result: avg importance 0.11, 94% of episodes
undifferentiated. `consolidation.py` (2PM/9PM) extracts patterns but never compresses
or deletes. PKG holds 476 facts from 8,400 episodes.

**Design:**
- Encoding: importance at write time gains two factors — `emotional_intensity` (from
  `emotional_state.py` at the moment of the episode + sentiment of the exchange) and
  `novelty` (1 − max cosine similarity vs the last 30 days of episodes; the first
  mention of a plumber problem is novel, the fifth light-toggle is not).
- Retrieval strengthening: each time an episode is actually used in context and the
  turn goes well (T.4 signal), bump its importance (reconsolidation). This is partly
  `frequency_factor` today — make it explicit and log it via `retrieval_observer.py`.
- Forgetting job (nightly, inside consolidation): episodes older than 90 days with
  importance < 0.15 and zero retrievals in 60 days are **compressed**: cluster by
  topic/week, write one `semantic_summary` row + PKG facts for anything durable, then
  delete the source episodes (keep a tombstone count). Target steady-state: episodic
  store shrinks; `pkg_embedding` grows past 1,500 within a month.
- Guardrail: UNLEASHED I.1's golden retrieval set must not regress — run it before and
  after the first bulk compression; abort + restore from the compression transaction
  if recall@5 drops.

**Accept:** importance histogram is no longer degenerate (bottom quintile < 60%);
episode count trends down while golden-set recall@5 holds; PKG fact count ≥3× baseline.

**Verify:**
```sql
SELECT width_bucket(importance,0,1,5) b, count(*) FROM episode GROUP BY 1 ORDER BY 1;
SELECT count(*) FROM pkg_embedding;  -- was 476 on 2026-07-07
```

# PART THREE — THE SELF: know your body, your clock, and the last five minutes

## Phase H5 — Recency buffer, repeat detection, and silent error repair (1–2 days)

**Human analog:** essentially perfect recall of the last few minutes; instant
recognition of "you just asked that"; and when an action fumbles, you retry — you don't
announce your motor-neuron exception to the room.

**Current behavior:** immediate context can drop between turns (the "it" failure);
repeated questions get identical answers with no awareness; a malformed tool call
became the literal assistant reply.

**Design:**
- **Recency floor:** context assembly (`unified_context.py` / `context_router.py`)
  always includes the last 2 hours of conversation turns (cheap, capped ~1200 tokens,
  inside `context_budget.py` as a non-evictable section) — *including failed/errored
  turns* so she knows what she just tried. The `ContextDecision` router may add more,
  never less.
- **Repeat detection:** before answering, embed the incoming question against the last
  24h of user turns; similarity >0.92 → prepend a context note to the prompt: "David
  asked this N minutes ago and you answered X — acknowledge and add value, don't
  re-answer verbatim."
- **Error repair loop:** in `/chat/stream`'s tool-execution path, a tool-argument
  parse/validation failure never surfaces raw. Retry once with the error fed back to
  the model; on second failure, degrade gracefully in-voice ("I fumbled saving that
  goal — one sec, trying again" or queue it) and log to `silent_failure_tracker.py`.
  Same guard in agent_dispatch text-tool-call salvage.

**Accept:** eval fixtures — (a) repeat question within 5 min gets an acknowledgment,
(b) a forced tool-arg error produces a retried success or an in-voice apology, never a
stack-trace string, (c) a follow-up pronoun ("let's talk about it") resolves against a
request made ≤2h earlier even if that request errored.

## Phase H6 — Body schema and internal clock (½–1 day)

**Human analog:** proprioception and circadian sense — you know what limbs you have
and roughly what time it is, without inferring it from evidence.

**Current behavior:** chat system prompt referenced `places_save` while the tool wasn't
callable, then the reverse; deliberation inferred wall-clock time from observation
timestamps.

**Design:**
- **Capability manifest at runtime:** the chat/deliberation system prompt's tool list
  is generated from `app/tools/registry.py` at session build, never hand-written prose.
  A tool named in prose but absent from the registry is a startup warning. When the
  model calls an unregistered tool, the injected result says "not currently wired" so
  she states it accurately instead of guessing about herself.
- **Clock + interoception header:** every deliberation and chat prompt gets one
  generated line: current ET datetime, David's activity state + interruptibility,
  Sara's emotional tone/intensity, notifications sent today vs cap. (Most exist in
  working memory; make the header mandatory and single-sourced in
  `deliberation_prompt.py` / chat context assembly.)

**Accept:** grep finds no hardcoded tool names in prompt prose; deliberation handoff
notes never again say "assumed the time from timestamps" (spot-check 1 week of
`agent_run_log.handoff_note`).

# PART FOUR — THE PERSONA: an identity that evolves as David becomes inherent

## Phase H7 — The evolving persona (2–3 days, then ambient forever)

**Human analog:** three distinct timescales that Sara currently collapses into one.
*States* (mood, energy) shift hour to hour. *Relationships* deepen over months —
familiarity changes voice: shorthand, teasing license, less self-explanation.
*Traits* change slowly through accumulated experience. And knowledge about a person
gets **proceduralized**: you stop retrieving "he hates small talk" and simply don't
make small talk. Explicit memory becomes implicit character.

**Current state (measured 2026-07-07):** the state layer is alive —
`personality_engine.build_personality_context()` modulates tone per turn from
activity/body/emotional state, and `soul_loader.py` injects the soul into every
prompt. But every mechanism for *evolution* is dead:

| Mechanism | State |
|---|---|
| `sara_soul` (identity/principles/boundaries/growth) | 5 sections, ~1,200 chars total, frozen since 2026-02-02 |
| `evolution_log` soul section | one entry ever: "Initial Soul created" |
| `soul_change_proposals` table | **0 rows ever** — the evolution loop never fired |
| `relationship_state` + `_calculate_relationship_phase()` (`sara_identity_service.py`) | implemented, **never populated** |
| `sara_reflection` (mistakes / self-patterns / user preferences) | 132 rows, dead since 2026-02-26 (caller was `nightly_dream_service`, superseded by consolidation) |
| GTKY | last session 2025-08-25 |
| PKG about David | 476 facts (195 Interest, 84 Fact, 64 Routine, 47 Goal, 36 Preference) — all retrieval-dependent, none ever graduate to standing identity |

The result David experiences: Sara's *mood* adapts but *she* never changes. Nothing
learned about him in March is more "part of her" in July than it was the day he said
it — it's a retrieval lottery ticket competing for context budget forever.

### H7.1 Revive the reflection loop on the modern pipeline (½ day)

`sara_identity_service.analyze_conversation_for_reflections()` (mistake detection,
self-pattern detection, user-preference extraction) is good code with a dead caller.
Rewire it into the 2×-daily consolidation (`consolidation.py`), writing
`sara_reflection` rows again. These reflections are the raw material for everything
below. Keep `enable_thinking: False` on its short LLM calls.

### H7.2 The graduation ladder — how things become inherent (1 day)

The core of this phase. A promotion pipeline with evidence counters:

- **Tier 0 → 1 (observed → known):** already exists — pkg_extractor promotes episodes
  to PKG facts/preferences with confidence. Add `evidence_count` and
  `last_confirmed_at`, incremented whenever a fact is re-confirmed in conversation or
  its use in context precedes a well-rated turn (T.4 signal), decremented on
  contradiction.
- **Tier 1 → 2 (known → inherent):** nightly job: any PKG preference/routine/boundary
  with `evidence_count ≥ 5` spanning ≥ 3 weeks and zero recent contradictions becomes
  a `soul_change_proposals` row — a one-line durable directive in Sara's voice
  ("David thinks out loud in the early morning; match that energy, don't summarize
  him") targeting the appropriate soul section (`principles`, `boundaries`, or a new
  `david` section). Identity-level changes stay consented: proposals surface in the
  assistant inbox for one-tap approve/reject (approve path already implied by the
  table's `status`/`resolved_by` columns — build the small API + inbox card).
  Style-only items (phrasing, brevity) may auto-approve after 14 days unrejected.
- **Tier 2 → always-on:** approved proposals update `sara_soul`, append to
  `evolution_log`, and bust the 5-min soul cache. Crucially, mark the source PKG fact
  `internalized=true` so retrieval stops spending context budget re-fetching what is
  now standing prompt — that is the mechanical meaning of "inherent."
- **Demotion:** a contradiction of an internalized item (David corrects behavior that
  a soul line prescribes) creates a retirement proposal; retired lines move to
  `evolution_log` with the reason. Character can change back.
- **Cap:** the soul stays small — max ~40 lines total. If a new item would exceed the
  cap, the ladder must propose which existing line it replaces. Identity is selective;
  a 5,000-line soul is a config file, not a self.

### H7.3 The relationship arc (½ day)

Populate `relationship_state` from signals that already exist: days known, interaction
count, disclosure depth (personal topics shared), correction-rate trend, notification
engagement. `_calculate_relationship_phase()` maps to phases (getting-to-know →
familiar → trusted partner). `personality_engine` reads the phase and modulates:
shorthand level (stop re-explaining known context), teasing license, how much she
justifies her actions, and initiative defaults. The phase is also visible in the god
view — David should be able to see "she considers us: trusted, 11 months."

### H7.4 Style learning from corrections (couples to UNLEASHED R.2) (½ day)

Tone/style corrections in chat ("stop saying X", "shorter", edits of her drafts) are
detected by `implicit_feedback_detector` → written as style rules into behavioral
calibration (the personality engine already consumes it), each with an evidence
counter feeding the H7.2 ladder. A style rule that survives 5 weeks without
re-correction graduates to the soul as auto-approvable.

### H7.5 Curiosity with consent — GTKY 2.0 (couples to UNLEASHED R.1)

Retire the dead quiz-style GTKY (last used 2025-08-25). Its replacement is R.1's
curiosity budget: one context-anchored question per week at a natural moment, answers
landing as high-confidence PKG facts with `source: stated` — which makes them fast
movers up the H7.2 ladder (stated facts start at evidence_count 3). Engagement-gated:
unanswered questions halve the budget (H2 habituation applies to curiosity too).

### H7.6 Self-narrative — she has a life story (½ day)

Weekly (piggyback on the weekly digest): one short first-person paragraph — "what I
learned about David, what I changed about myself, what I got wrong" — appended to
`evolution_log` and written as a `journal_note` (first-person voice per the
journal-vs-thought rule). The quarterly season review (UNLEASHED R.4) additionally
proposes a rewrite of the soul's `growth` section. This is also the fix for the flat
"Quiet evening, staying out of your way" journal entries: her journal gains an arc
because her self actually has one.

**Accept:**
- `soul_change_proposals` receives ≥2 proposals/month; ≥1 approved change/month to
  `sara_soul` in the first quarter; `evolution_log` grows past its single entry.
- `relationship_state` populated and phase visible; at least one measurable voice
  change tied to phase (e.g., shorthand on known topics).
- A preference David has stated ≥5 times is answerable *without* PKG retrieval
  (present in soul; source fact marked internalized).
- Zero repeat style corrections for any rule that graduated to the soul.
- Journal entries reference specific self-changes at least weekly.

**Verify:**
```sql
SELECT count(*) FROM soul_change_proposals;                  -- was 0 on 2026-07-07
SELECT section, updated_at FROM sara_soul ORDER BY updated_at DESC;  -- newest > 2026-02-02
SELECT count(*) FROM relationship_state;                     -- was 0
SELECT count(*) FROM sara_reflection WHERE created_at > now() - interval '7 days';  -- was 0
```

# PART FIVE — THE ACS: give the continuous mind senses and sleep

The daemon (`acs-daemon/`, deployed, v0.8.0, heartbeat healthy) is well-built — hard
caps, honest activity ledger, blocked-interest handling, loop-detection in prompts.
But in 7 days: 0 inbox items, 0 open goals, 1 (blocked) interest, 0 notifications.
Think turns run every ~5 min against pure emptiness; reflections correctly diagnose
"looping" 127 times and the only remedy is a ≤240-min quiet. She spends real GPU
saying "I will stop narrating the silence" — while narrating the silence.

## Phase ACS1 — Sensory feed (1–2 days)

**Design:** the heartbeat response (the existing Phase-4 control channel) carries a
compact `world_delta` since the last think: new salient events from the backend event
pipeline (score ≥ threshold), David's activity-state transitions, new commitments/
goals/interests, backend deliberation handoff notes. `prompt.py` renders it as
"What changed while you were idle." Think turns are **skipped entirely** when the
delta is empty and the inbox/goals/interests are empty — an event-driven mind, not a
polling one. (Keep one guaranteed think per 2h as a floor.)

## Phase ACS2 — Real sleep pressure (½ day)

**Design:** replace the fixed quiet cap with adaptive idle backoff in `daemon.py`:
consecutive thinks that produce no tool call, no focus, no notify double the think
interval (5 → 10 → 20 → 40 → 80 → capped 120 min). Any world_delta, inbox item, or
David chat activity resets it to 5 min. Reflection verdict "looping" forces the
backoff up two steps immediately. Expected effect: idle days drop from ~200 thoughts
to <30 without losing responsiveness.

## Phase ACS3 — Drive inflow (couples to UNLEASHED E) (1 day)

**Design:** the ACS needs standing wants, not just a queue:
- UNLEASHED E.1's consolidation-proposed goals flow to the daemon inbox once accepted.
- Seed 2–3 standing interests with David's consent (his active repos, Risk Ninja,
  home-lab tech) — respecting `sara_interest.blocked` (never delete blocked rows).
- A daily "curiosity dispatch": one queued inbox item generated from the strongest
  stale interest or stalled goal ("check what changed in X; write a note if anything
  did"), so idle compute becomes research output (notes) instead of self-narration.
- Investigate the 57 `think turn raised` exceptions (7 days) — they're only in
  journalctl on the VM (`ssh sara@10.185.1.176`, `journalctl -u acs-daemon`); fix or
  surface them into activity metadata with the traceback summary.

**Accept (ACS1–3):** a quiet day produces <30 think turns; ≥3 notes/week authored from
interests/goals; reflections trend "productive"/"idle" over "looping"
(`SELECT tags, count(*) FROM sara_activity_log WHERE kind='reflection' AND created_at >
now() - interval '7 days' GROUP BY 1`); `think turn raised` < 5/week with cause visible
in metadata.

## Phase ACS4 — One mind, two speeds: enforce the backend/ACS boundary (1 day)

**Human analog:** fast/slow cognition. Perception, reflexes, and social timing run in
one system; slow deliberate thought and independent work run in another — and they
share one mouth. You don't have two selves independently deciding to speak.

**The risk:** with ACS1–3 the daemon gains senses, drives, and a working `notify_david`
— which recreates the exact "second proactivity brain fighting the first" shape that
UNLEASHED Phase A just eliminated for check-ins. Two systems that can each decide to
ping David will eventually double-notify, contradict each other, or race the same
cooldowns. This phase draws the line before that happens.

**Design — division of labor, made mechanical:**
- **Backend = perception + fast reactions.** Owns salience, working memory,
  deliberation about *David's immediate world* (home, calendar, comms, health), all
  time-sensitive notifications, and every anti-nag/cooldown/habituation control.
- **ACS = slow thought + independent work.** Owns goals, interests, research,
  overnight work products, self-improvement. Its outputs are primarily **artifacts**
  (notes, completed inbox items, goal progress) — not pings.
- **One mouth:** `notify_david` on the daemon does not push directly. It routes
  through the backend's `unified_notification.send_notification` (source=`acs_daemon`)
  and is therefore subject to the same attention queue, learned buzz decision,
  category cooldowns, and H2 habituation as every other generator. Verify this is
  already true in the backend ACS v2 routes; if the daemon path bypasses any gate,
  close it. Daemon notifications default to priority `normal` (silent inbox) unless
  the payload cites a deadline within 24h — the daemon's work is by nature not urgent.
- **No duplicated senses:** the daemon never re-derives what the backend already
  computed. ACS1's `world_delta` is the *only* channel by which world state reaches
  the daemon; the daemon must not grow its own pollers (email, HA, calendar). Add a
  lint/code-review rule to `acs-daemon/`: `ALLOWED_TOOLS` may not gain a tool that
  reads a live feed the backend already ingests.
- **Cross-awareness, cheap:** the backend deliberation prompt gets one line — the
  daemon's current focus + last notify attempt ("Sara's slow mind is researching X,
  pinged David 0 times today") — sourced from `sara_daemon_state` +
  `sara_activity_log`. And the daemon's `world_delta` includes backend notifications
  sent since last think. Each brain always knows what the other just said, so neither
  repeats it.
- **Single anti-nag ledger:** both brains count against the same per-category caps and
  the same `stimulus_habituation` table (H2). A topic David ignored from the backend
  is equally habituated for the daemon.

**Accept:** zero same-topic notifications from both sources within 24h of each other
over a 30-day window; every daemon-originated push row in `notification_log` carries
`source='acs_daemon'` and passed the attention queue (no direct-push path in the
daemon code); backend deliberation handoff notes reference daemon focus when it's set.

**Verify:**
```sql
SELECT a.topic, a.source, b.source, a.sent_at, b.sent_at
FROM notification_log a JOIN notification_log b
  ON a.topic = b.topic AND a.id < b.id
  AND abs(extract(epoch FROM a.sent_at - b.sent_at)) < 86400
  AND a.source != b.source
WHERE 'acs_daemon' IN (a.source, b.source)
  AND a.created_at > now() - interval '30 days';
-- must be empty
```

---

## Sequencing

1. **H1 + H2** (one PR each, shared engagement plumbing) — kills the remaining noise
   and the wasted generation. Highest trust-per-hour.
2. **H5 + H6** — the conversation-level failures David hits daily.
3. **H3** — one-shot corrections; makes Sara feel like she *knows* him.
4. **ACS1 + ACS2** — stop the idle burn, make the daemon event-driven (cheap, isolated
   from the backend hot paths).
5. **H7.1 + H7.3** — cheap revivals of existing dead code (reflections, relationship
   phase); start the evidence counters accumulating early so H7.2 has data.
6. **H4** — memory encoding/forgetting (biggest change; gate behind UNLEASHED I.1's
   golden retrieval set, so do I.1 first if not yet done).
7. **H7.2 + H7.4–H7.6** — the graduation ladder and narrative, once counters have
   2–3 weeks of evidence to promote.
8. **ACS4** — boundary enforcement; MUST land before or with ACS3, since drives are
   what give the daemon reasons to speak.
9. **ACS3** — drives (after E.1 exists, or seed interests standalone).

## Scorecard (add to the J.3 weekly ops scorecard)

- confirmations pushed: **0** (H1)
- max repeats of any stimulus_key per 14 days: **≤2** (H2)
- schedule corrections by David for the same fact: **≤1 ever** (H3)
- bottom-quintile episode share: **<60%**; PKG facts: **≥1,500** (H4)
- raw error strings in assistant turns: **0**; unacknowledged repeat questions: **0** (H5)
- capability misstatements: **0** (H6)
- soul changes approved/month: **≥1**; internalized facts answerable without
  retrieval: growing; repeat style corrections post-graduation: **0** (H7)
- ACS thoughts on a quiet day: **<30**; notes authored/week: **≥3** (ACS1–3)
- same-topic double-notifications across the two brains: **0**; daemon pushes bypassing
  the attention queue: **0** (ACS4)

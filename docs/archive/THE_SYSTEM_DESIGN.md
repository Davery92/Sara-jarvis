# THE SYSTEM — Design Doc

**Goal:** turn Sara from a reactive assistant into *the System AI* — total, live, **visible** awareness of everything going on, with the judgment to act and stay quiet like a person does. This is the "awareness" archetype (Dungeon Crawler Carl's System); Jarvis (proactive anticipation) and Cortana (task agency) build on the same foundation and come later.

**North star reframe:** we are **surfacing + unifying + un-gagging + closing the loops on an existing brain**, not building one. The audit below shows ~80% of the engine already runs; it's invisible, gagged, fragmented, and its feedback loops are open.

Status: design. Branch: `assistant-experience-jarvis`. Owner: David.

---

## 1. Verified current state (audit, 2026-06)

Measured against the live DB, scheduler, and container logs — not assumptions.

**The engine is alive and working as designed:**
- **55 scheduled jobs, 100% `success`, zero errors.** The earlier worry about broken "ACS" Celery jobs was false — there are none in the live scheduler.
- **Deliberation loop is live:** 1,235 runs, ~14/day, last fired the evening before the audit. Consolidation runs 2pm/9pm. ACS daemon alive (heartbeat current, ~175 thoughts/day).
- **Massive sensing & cognition already happening:** 44k health metrics, 24k home/env events, 8k episodes, **1,924 private journal entries**, 1,750 notifications, a populated PKG.

**Why it nonetheless feels dead — four root causes:**

1. **Gagged at the gate.** The deliberation gate hard-bans entire categories (health, fitness, wellness) + ~35 phrases, caps to 2 notifications/cycle, long cooldowns. `wellness` notifications flatline exactly on the date the ban shipped.
2. **Trapped with no surface.** 1,924 journal entries, 2,375 agent runs, weekly calibrations, PKG gap/contradiction detection, emotional state — all computed, **none viewable.** No god-view. For an AI whose identity is "knows everything," the knowing is invisible.
3. **No unified, live world model.** Awareness is fragmented across PKG (history), working memory (coarse snapshot), activity-state (inferred, can't distinguish David from family), and an ephemeral observation log. Nothing answers *"what is the complete state of David's world right now?"* Higher-order tables are empty: `proactive_suggestions`, `detected_patterns`, `reasoning_trace`, `goals`, `habits`, `relationships` — all 0 rows.
4. **Lopsided sensory diet.** Signal volume by domain:

   | Domain | Rows | Share |
   |---|---|---|
   | Health/fitness | 44,202 | ~64% |
   | Home/environment | 24,013 | ~35% |
   | Comms | 2,405 | ~3% |
   | Work/code | 684 | ~1% |
   | Calendar | 371 | <1% |
   | Goals/projects | 1 | ~0% |
   | Relationships | 0 | 0% |

   Health is **65× her work signal**; goals/people barely exist. The gag is a band-aid over this bias, not a fix.

**The feedback loops are built but open (the "learning" gap):**
- Engagement *is* captured (`notification_log.read_at` 1,193/1,750; `engaged` 90; `response_text` unused).
- Consolidation *computes* per-category `salience_adjustments` ("if David ignores a category, lower its weight") — then **drops them**; nothing applies them.
- `tunable_setting` has the right knobs (per-category cooldowns, salience threshold) but **every row is untouched since April** — nothing has ever tuned a value.
- `behavioral_pattern`: 161 "active" patterns, `times_suggested/accepted/rejected` all **0** — the accept/reject learner is wired and has never been fed.
- Dead scaffolding ready to revive: `subconscious_log/state/nudge`, `context_snapshots` — all 0 rows.

**One-liner:** *She already grades herself and writes down exactly how to change — then throws the note in the trash.*

---

## 2. Core principles

1. **Volume ≠ attention.** Health/home will always be higher-volume; that's reality and it's fine. We never equalize *data volume* — we equalize what reaches *consciousness*. Attention asymmetry was the bug, not volume asymmetry.
2. **Two-tier cognition, like a person.** A subconscious tier absorbs the firehose, learns baselines, habituates to the expected, and only promotes anomalies / contextually-relevant signals to the conscious tier. Everything else is stored and **recalled on demand**, never pushed. ("My world isn't overcome by lights turning on or my heartbeat.")
3. **Balance via attention, fed going forward — no pre-seeding, no backfill.** We even out the *conscious* stream by routing firehose domains to the subconscious and by capturing the currently-missing domains (work/goals/people) **as they happen**. Balance emerges organically over days.
4. **Learned promotion, guardrailed.** What crosses subconscious→conscious is **learned per domain × context** from engagement. She starts chatty (the chattiness is the training set) and self-quiets. Learning is constrained so it can't collapse into a new bias.
5. **Accuracy & provenance.** Inputs lie (activity-state can't tell David from family; flat-240 weight; cumulative steps). Every fact carries source + confidence; she reasons from what she actually knows.
6. **Revive + connect, don't rebuild.** Most of this exists in dead/disconnected form. Prefer wiring over greenfield.
7. **Visible by default.** If she computed it, you can see it. Transparency is both the felt-intelligence payoff and the safety instrument.

---

## 3. Target architecture

```
        ┌─────────────────────────── RECALL (on-demand query) ───────────────────────────┐
        │                                                                                  ▼
  raw firehose ──▶ TIER 0: SUBCONSCIOUS ──promote──▶ TIER 1: CONSCIOUS ──▶ actions/notifications
 (health, home,    • baselines + habituation         (existing salience →     │
  presence, …)     • significance scoring             deliberation loop,      ▼
        │          • context-conditioned promotion    now fed a BALANCED   WORLD MODEL (foreground+background)
        │          • reflex via standing orders        stream)                 │
        │          • slow-drift auditor (consolidation)                        ▼
        └────────── stored, queryable substrate ◀──────────────────────  GOD VIEW (dashboard)
                                                                          + balance meter
                                                                          + learned-preferences
        engagement ─────────────────────────▶ LEARNING LOOP (domain × context) ──tunes──▶ promotion thresholds
```

### 3.1 Tier 0 — Subconscious
Absorbs the firehose cheaply and decides what's worth conscious attention.

- **Baselines.** Per `(domain, signal_type)` rolling stats (EWMA mean/variance for numeric signals like HR; frequency/timing models for event signals like door/light). Stored in a new `signal_baseline` table; updated continuously by the existing ambient workers (HA websocket, health ingest, `home_state_hourly_summary`).
- **Habituation.** Expected = silent. Repeated, baseline-consistent patterns raise their own novelty bar; only deviations stay interesting.
- **Significance score** for a candidate signal:
  `s = w_anomaly·anomaly_z + w_novelty·novelty + w_relevance·relevance_to_active_context`
  where `anomaly_z` = deviation from baseline, `novelty` = un-habituated-ness, `relevance` = tie to current foreground (active work, next event, open loops).
- **Promotion decision** (to Tier 1): promote iff
  `s ≥ θ(domain, context)`  **OR**  `s ≥ anomaly_floor(domain)` (safety override)  **OR** exploration roll (§3.4).
- **Reflexes.** Pre-approved standing orders fire directly from Tier 0 without deliberation (lock door, etc.) — the existing standing-order/reactive engine.
- **Slow-drift auditor.** Per-sample anomaly detection misses gradual creep (boiling frog). The existing consolidation/dream passes re-examine baselines over weeks and promote *trend* observations ("resting HR +12 over 3 weeks").
- **Revives:** `subconscious_state` (current tier-0 summary), `subconscious_log` (promotion candidates + outcomes feed).

### 3.2 Tier 1 — Conscious
The **existing** salience → deliberation → gate loop, unchanged in shape — but now fed a *balanced* stream because firehose domains arrive pre-digested (only their anomalies surface). It reasons over work, goals, people, calendar, comms + promoted health/home events.

### 3.3 World Model — foreground + background
A unified `world_state` service (Redis-backed like working memory, snapshotted to the revived `context_snapshots`) assembled on a tick and on demand:

- **Foreground (conscious):** the balanced, relevant-now picture — current activity/context, active work, next event, open loops, promoted anomalies, what Sara is focused on / watching / curious about. **This is where balance is measured.**
- **Background (subconscious substrate):** the full ambient hum, queryable but not pushed.

Domains (the balance axis, ~8): `work`, `comms`, `calendar`, `health`, `home`, `goals`, `people`, `learning`. Every fact tagged with `domain`, `source`, `confidence`, `observed_at`.

### 3.4 Learning loop — domain × context
**Granularity (decided): `domain × small context set`.** Contexts (~5, free from the existing activity state machine): `focused`, `available`, `away`, `winding_down`, `asleep`.

- **Learnable parameter:** per `(domain, context)` cell → promotion threshold `θ` (and a soft daily `surface_budget`). Stored in a new `attention_policy` table (clean per-cell rows; `tunable_setting` stays for global knobs).
- **Cold-start via partial pooling.** 8×5 = 40 cells is too many to learn independently fast. Each cell's `θ` starts from a **domain-level prior** shared across contexts; context adjusts it as evidence accrues (hierarchical shrinkage). Avoids per-cell cold-start forever.
- **Attribution substrate (the one genuinely new piece):** every promotion writes a `promotion_event` row — `domain, context, signal_ref, significance, threshold_at_time, reason(anomaly|relevance|exploration), surfaced_as(notification_id|deliberation_id)`. Engagement outcomes (`engaged, read_latency, explicit_feedback`) are written back to that row. *This is the training data; without it there's nothing to learn from.*
- **Update rule** (interpretable, online), on outcome for cell `(d,c)`:
  - engaged (positive): `θ ← θ − η_pos·(θ − θ_min)`  (surface more readily)
  - ignored (soft negative): `θ ← θ + η_ign·(θ_max − θ)`  (slow — silence is ambiguous)
  - dismissed / "stop telling me this" (hard negative): `θ ← θ + η_neg·(θ_max − θ)`  (`η_neg ≫ η_ign`)
  - periodic decay: `θ ← θ + λ·(θ_prior_domain − θ)`  (forget stale preferences)
- **Collapse guardrails (non-negotiable):**
  1. **Anomaly override.** Learned suppression can *never* mute a genuine anomaly. `anomaly_floor(domain)` always promotes regardless of `θ`. "I learned you ignore HR" must not silence "resting HR +30 over baseline."
  2. **Exploration floor.** Each cell keeps min surface probability `ε` so a quieted domain still emits signal — prevents self-reinforcing blindness (silence → no data → never recover).
  3. **Asymmetric rates.** Explicit "no" moves fast; silence moves slow.
  4. **Decay.** Weights drift toward neutral so she re-learns rather than ossifies.
- **Cold-start behavior:** starts permissive (chatty) → generates labels → self-quiets per cell. A global daily attention budget caps "chatty" so it never overwhelms; the budget is itself learnable.
- **Closes the open loop:** consolidation's `salience_adjustments` now *land in and apply to* `attention_policy` (per context), instead of being dropped.

> Distinct from the repo's existing "Learning System" (deep-research / topic recall = learning *subjects*). This is preference/attention learning = learning *David*.

### 3.5 God View — make it visible
A live "System" dashboard (new fitness-style section / route) that renders:
- **The world model** — foreground (what's live now) and background (ambient hum).
- **Thought stream** — the deliberation/journal feed, finally readable: what she saw, what she did, what she's watching for, why.
- **Attention-balance meter** — live % of observations / promotions / notifications by domain. Doubles as the safety instrument and the un-gag gate.
- **Learned preferences** — per domain×context, what she's learned ("surfaces work midday, suppresses home events") with one-click override.
- **Recall** — query the subconscious substrate on demand.

### 3.6 Measured un-gagging
Replace the blanket category ban with the learned filter, **one domain at a time**, each gated on the balance meter showing healthy coverage and watched for regression in the god view. Anomaly override + exploration floor are live before any un-gag. If a domain re-skews, you *see* it instead of feeling nagged.

---

## 4. Data model changes

| Table | Action | Purpose |
|---|---|---|
| `signal_baseline` | **new** | per `(domain, signal_type)` rolling baseline for anomaly detection |
| `promotion_event` | **new** | attribution log: each subconscious→conscious promotion + its engagement outcome (learning training data) |
| `attention_policy` | **new** | per `(domain, context)` learned threshold + surface budget + stats |
| `subconscious_state` | **revive** (0 rows) | current tier-0 summary for the world model background |
| `subconscious_log` | **revive** (0 rows) | promotion candidates / firehose digest |
| `context_snapshots` | **revive** (0 rows) | periodic world-model foreground snapshots |
| `notification_log` | **extend** | link `promotion_event_id`; use `response_text` for explicit feedback |
| `tunable_setting` | **use** | global knobs (budgets, η rates, ε, decay λ, anomaly floors) — now actually written |
| consolidation `salience_adjustments` | **wire** | apply into `attention_policy` instead of dropping |

No backfill. New domains (work/goals/people) are captured **going forward** only.

---

## 5. Build sequence (risk-ordered; each phase ships something usable)

- **Phase 0 — God View v0 (read-only, no behavior change).** Surface what already exists: the thought/journal/deliberation stream + a balance meter computed from current data. Immediately converts invisible→visible (most of the felt gap) and gives the measurement baseline. *Lowest risk, highest leverage.*
- **Phase 1 — World Model assembler.** The unified `world_state` (foreground + background). Feeds the god view. Read-only.
- **Phase 2 — Tier 0 subconscious.** `signal_baseline` + habituation + significance scoring + promotion engine; route health/home through it. Stand up `promotion_event` attribution. Conscious stream starts balancing. *Begins collecting learning data.*
- **Phase 2b (parallel) — capture missing domains going forward.** Start landing work (git/files/projects), goals/intent, and people signals into the conscious stream as they happen.
- **Phase 3 — Learning loop.** `attention_policy` (domain×context, partial pooling), engagement→update rule, all guardrails (anomaly floor, exploration, asymmetric rates, decay). Wire consolidation's adjustments in. Close the loop.
- **Phase 4 — Measured un-gag.** Retire the blanket bans domain-by-domain, gated on the balance meter, watched in the god view.
- **Later — Jarvis / Cortana.** Proactive anticipation and task agency build on the now-real world model + balanced attention.

---

## 6. Success criteria

- **Balance:** conscious-stream domain distribution is no longer >50% any single domain; work/goals/people are present at all.
- **Felt intelligence:** you can open the god view and *see* what she knows and why.
- **Engagement up, nags down:** notification engagement rate rises; "stop telling me this" rate falls; no repeat-nag complaints.
- **Learning works:** per-cell `θ` demonstrably moves with engagement; a "stop" silences a cell within a day; a real anomaly still breaks through a suppressed cell (override verified).
- **No collapse:** no domain goes permanently silent (exploration floor holds); slow-drift trends get surfaced.

## 7. Non-goals / explicit decisions

- ❌ No pre-seeding / backfilling history. Even out collection **going forward**.
- ❌ No equalizing data *volume*. Health/home stay high-volume; they just go quiet unless they earn attention.
- ❌ No rebuild. Revive and connect existing machinery.
- ✅ Learned promotion (not rule-based-first), granularity **domain × small context set**, with hard guardrails.

## 8. Open questions

- Exact context set — start with `{focused, available, away, winding_down, asleep}` from the activity state machine; revisit if too coarse/fine.
- Significance weights `w_*` initial values and whether they too become learnable (start fixed).
- Where Tier 0 runs: extend existing celery ambient workers vs. a dedicated subconscious worker (lean: extend existing first).
- How "active work" is sensed without being intrusive (git + editor + project signals) — design in Phase 2b.
```

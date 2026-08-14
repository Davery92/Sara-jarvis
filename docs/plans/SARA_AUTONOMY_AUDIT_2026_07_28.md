# Sara Autonomy Audit — 2026-07-28

Full review of everything Sara does proactively or reactively: her autonomous actions,
notifications, thoughts, and the machinery around them. Based on reading the live code on
`feat/sara-watch-workout-ui` plus the **live production database and container logs**
(July 21–28 window). No changes were applied — this is findings + a prioritized fix plan.

**Framing note (from David):** the current experience is *"both too quiet and too annoying —
she reaches out about stuff I don't care about or useless stuff."* The evidence below shows
that is not a tuning problem; it is three specific, fixable defects (F1–F3) plus one
structural deadlock in the learned-buzz system (F5).

---

## 1. Executive summary

- **The single biggest live defect:** background-task completion "tell-once" ledger rows are
  written to `notification_log` with `sent=TRUE`, and the 2-per-day proactive push budget
  counts them. On 07-27, seven generic "Background task complete" notices consumed the entire
  budget while three concrete, high-interest items ("Xiomara's Risk Ninja email", "Jim's
  email about Derek", "Jim's email connects to two events") were **suppressed by that same
  budget**. This one accounting bug *is* "too quiet AND too annoying" in a single mechanism.
- **The busywork loop feeding it:** the deliberation engine auto-dispatches near-identical
  `maintenance` tasks ("Check for unread action-required emails", "Check for overdue
  reminders" — 6 in the last 7 days) that duplicate systems that already exist
  (email sync, reminder engine, assistant-verbs sweep). Each completion produces a
  payload-free push. The duplicate/daily-cap guard only covers the `research` category.
- **The entire hard-ban list is silently off:** `system.ungag.all=true` in
  `tunable_setting` bypasses every banned phrase and banned category (health, fitness,
  nutrition, etc.). You didn't know. The learned attention policy that was supposed to
  replace the ban list is simultaneously **starved** (F5), so right now essentially nothing
  governs those domains except the payload lint.
- **Deliberation is 94% idle:** 146 deliberation runs in 7 days; 137 produced zero
  notifications, zero actions, zero tasks. Each run is a ~55s local-LLM call. The runs that
  *did* produce something mostly produced the busywork tasks above.
- **The learned buzz decision has a cold-start deadlock:** a category needs ≥5 sends AND
  ≥40% engagement in 30 days to earn a phone buzz; post-July-25 volumes mean most categories
  can never accumulate 5 sends, so they fail closed forever. Valuable content lands in the
  attention inbox, where **75 of 87 items in the last 7 days were archived unread**.
- **What actually gets engaged proves the targeting thesis:** engaged notifications are all
  concrete and named ("Quick check on Risk Ninja", "How was your workout?", "Shield off?",
  "Amanda's Office Ready?"). Unengaged ones are generic ("Background task complete",
  "Checking in on your day", "Your daily autonomy update", "Barbell Row in 51 min").
  Sara knows *categories*; she doesn't yet weight *topics David demonstrably cares about*.
- **One real priority bug:** deliberation-gate maps `critical → "max"`, but the pipeline's
  normalizer doesn't know `"max"` and demotes it to `normal` — a critical deliberation alert
  would be subject to budget, buzz, and sleep-hold like any routine ping.
- **Currently failing job:** `nightly-consolidation` deadlocked at 03:00 on 07-27
  (`DeadlockDetectedError` against a concurrent transaction; the 02:00–03:45 window runs
  ~10 heavy jobs). Interoception correctly caught and reported it — that part works.
- **Lots of genuinely good machinery** (§5): the anti-nag stack, sleep sensing, interoception,
  autonomy tiering with hard blocks, tell-once ledgers, why-traces, habituation with
  spontaneous recovery. The bones are good. The problem is a few leaks between layers and
  generators that bypass the "one brain".

---

## 2. System inventory — what runs, when, and who can talk to you

### 2.1 The cognitive spine (event-driven)

```
Redis event bus (event_bus.py, ~40 event types)
  → salience_subscriber → salience.py scores each event (5 weighted dims + category floors)
  → observation_log (Redis zset, 24h TTL, floor 0.3)
  → should_deliberate(): accumulated salience ≥ 1.5, min 20-min gap, forced at 1.5h idle
    (6:00–22:00), night mode 1–5 AM requires ≥ 4.0
  → kernel.ambient_turn()  [SINGULAR_KERNEL=true — live]
  → deliberation.py: single structured-JSON LLM call
      hourly path: local Qwen, 15 observations, 1500 tokens
      deep path (14:15 & 21:15): claude-sonnet-5, 50 observations, 3000 tokens
  → deliberation_gate.py: bans → payload lint → caps (2 notifs, 3 home actions, 2/4 tasks)
      → autonomy tiers (auto-execute / propose / hard-block) → journal + agent_run_log
  → unified_notification.send_notification (the "one mouth")
```

### 2.2 The notification pipeline (the "one mouth" — 9 sequential gates)

Order inside `send_notification` / `route_through_attention_queue`:

1. **Attention-market content dedup** (SINGULAR_ATTENTION=true)
2. **Notification tuner** (legacy daily engagement-based suppress/double-cooldown, still active via `notify.legacy_limits=true`)
3. **Ban check** — static phrase/category list + user prefs + anomalous-day quieting — **currently bypassed by `system.ungag.all=true`**
4. **Phrasing composer** (one Sara voice)
5. **Attention queue routing** (AUTONOMY_ATTENTION_ENABLED=true): category cooldown vs recycled items → create inbox item → **learned buzz decision** (≥5 sends + ≥40% engagement in 30d + interruptibility ≥0.5, else inbox-only) → **daily budget** (2 non-urgent pushes/day)
6. **Prediction-confirmation suppression** (deviations notify, confirmations never)
7. **Topic dedup + category rate limits** (tunable per category)
8. **Desktop WebSocket first** (no phone buzz when desktop connected)
9. **Delivery policy** — sensed sleep gate (iPhone Focus + home-quiet + rhythm + recent interaction) holds non-critical pushes for the wake flush; low-readiness days (<55) hold soft categories too. Why-trace persisted for every decision.

Plus: generator-side **habituation** (strength decay on ignored, ×2 recovery on engaged,
+0.05/day spontaneous recovery), **thread anti-harping** (max_mentions, drop on
negative/ignored), **interruptibility queueing** on the paths that use
`send_notification_with_interruptibility`, and a **quiet mode** hard gate at the deliberation
gate.

### 2.3 Scheduled behaviors (DB-backed beat, ~90 jobs, all but 2 enabled)

Highlights by cadence (all verified live in `scheduled_job`, last-run statuses green except
`nightly-consolidation`):

- **Seconds–minutes:** notification predispatch (5s), automation watcher + mission worker
  (30s), consolidation watcher + context refresh (60s), deep-research poller (60s),
  standing-order time check (120s), source fetcher (120s), interoception event drain (120s),
  email sync (180s)
- **15–30 min:** deliberation fallback (30m), proactive check-in sweep (15m, 8:00–20:45),
  ended-meeting scan (10m, 7:00–22:00), calendar prep (15m), travel "leave now" nudges (15m),
  prediction matching (15m), subconscious tier-0 tick (15m), daily-brief consolidation (30m),
  weather (30m), predictive engine (30m), health anomaly detect (30m, 6:00–23:00),
  assistant-verbs sweep (30m, 8:00–20:00), attention expiry sweep (30m)
- **Daily anchors:** morning brief 6:00, morning anticipation 6:00, readiness 5:15,
  prediction generation 4:30, morning inbox digest 8:00, morning proactive check (hourly
  gate), consolidation 14:00 & 21:00 + deep deliberation 14:15 & 21:15, evening anticipation
  21:20, autonomy digest 21:40, bedtime nudge check 20:00–22:00, PKG extract 12:00 & 18:00,
  reflection every 4h, reflection report 9:00
- **Overnight batch (the crowded window):** research brief + dreams 2:00, health baselines
  2:15, ML features 2:30, ML retrain 2:45, **nightly memory consolidation 3:00 (failing)**,
  brief archive 0:00, curiosity 1:30, calendar top-up 3:05, fleet prune 3:17, place
  discovery + attention learning 3:30, rhythm recompute 3:45, retention cleanup 4:00,
  PKG stale goals 4:15
- **Weekly:** health report Mon 6:00, self-audit Sun 18:30, learning digest Sun 19:00,
  wiring check Sun 8:00, tool-call eval Mon 5:00, calibration Sun 10:00

### 2.4 Reactive systems

- `reactive_engine.py` subscribers: Security (quiet-hours doors/anomalies → urgent,
  10-min per-entity cooldown), Comfort, Presence, Anomaly
- Standing orders: trigger evaluation every 120s, security-class failures fail loudly,
  5-min undo ledger (`action_ledger`)
- Automation watcher (30s), HA reactive bridge feeding the activity state machine
- Interoception: every Celery failure → ledger + streak tracking (transient errors need a
  5-streak before escalating), recovery auto-clears; escalation → Needs-You + notification

### 2.5 Inner life ("thoughts")

- **Journal** (`sara_journal`): 127 deliberation entries + 19 consolidation + 2 self-audit +
  2 weekly-digest + 1 curiosity in the last 7 days. First-person `journal_note` only;
  analytical `thought` stays in `agent_run_log`; 0.9-similarity dedup against last 12h.
- **Working memory** (Redis snapshot): focus, curiosities (cap 5), emotional tone with
  momentum (0.4 blend, 0.12/hr decay), handoff note, watching-for.
- **Dreams** (2 AM): counterfactual replay, tomorrow rehearsal, PKG recombination —
  journal-only, nothing pushes. **Curiosity** (1:30 AM): ≤1 active goal, ≤1 LLM
  investigation/day. **Global workspace**: 7-slot derived read model.
- **Subconscious tier-0**: per-signal baselines, promotion by learned θ per
  (domain, context) with anomaly floor + exploration ε; `system.tier0.escalate_to_conscious=true`
  (live). **Attention learning** (3:30 AM) moves θ from engagement.
- **Goals** (`sara_goal`): 3 rows ever — 1 completed, 2 abandoned. Dormant.
- **ACS daemon**: containers healthy (`jarvis-celery-acs-1`, `jarvis-acs-tool-runner-1`);
  the VM-body daemon proxies its tick through `kernel.ambient_turn(DAEMON_PROXY)` per
  ONE_MIND (selves=1).

---

## 3. Empirical picture (live DB, July 14–28)

| Metric | Value |
|---|---|
| Deliberation runs, last 7d | 146 (58 in last 3d) |
| … producing zero output | 137 (94%) |
| … producing task dispatches | 7 runs → 6 `maintenance` + 3 `research` auto-dispatches |
| … producing a sent notification | 1 |
| Pushes sent, last 30d | 157; engaged 34 (22%) |
| Pushes sent, last 3d (post-cuts) | ~10; **7 were "Background task complete"**, 0 engaged |
| Budget suppressions, 07-27 alone | 3 concrete email-insight pushes (all Risk-Ninja-adjacent — a topic with prior engagement) |
| Attention inbox, last 7d | 87 items: 75 archived, 4 completed, 7 new, 1 snoozed |
| Journal entries, last 7d | 151 total (vs ~10 sent notifications) |
| `sara_goal` lifetime | 3 (1 completed, 2 abandoned) |
| Failing beat job | `nightly-consolidation` (deadlock 07-27 03:00) |

What engagement looks like when it happens (every engaged push, July 20–27):
"Heads up — I'm degraded" (interoception), "Background task complete" (once, of 12),
"How was your workout?", "Quick check on Risk Ninja", "Amanda's Office Ready?",
"Quick workload check-in", "Shield off?". **Concrete + named + timely wins; generic loses.**

---

## 4. Findings (ranked)

### F1 — CRITICAL: tell-once ledger rows eat the daily push budget
`task_result_delivery._record_delivered()` inserts a `notification_log` row with
`sent=true, priority='normal', category='agent_task'` for **every** completion delivery —
including silent SSE chat injections and desktop toasts. `_daily_push_budget_available()`
counts exactly those rows (`sent=TRUE AND priority NOT IN ('urgent','critical') AND category
NOT IN timer/reminder`). Consequence, observed live on 07-27: 7 ledger rows by 17:57 →
budget permanently exhausted from ~06:25 onward → "Xiomara's Risk Ninja email" (10:44),
"Jim's email about Derek" (12:44), "Jim's email connects to two events" (15:44) all
suppressed with `daily budget`. **The least valuable content is crowding out the most
valuable via a bookkeeping row.**

### F2 — HIGH: deliberation manufactures busywork, then announces it
6 of 9 auto-dispatched tasks in 7 days were `maintenance` items like "Check for unread
action-required emails" and "Check for overdue reminders" — duplicating email_sync,
assistant-verbs, and the reminder engine. One was literally "Summarize completed background
tasks if any are relevant" (a task about tasks). The loop guard (`_research_should_skip`:
daily cap + 3-day similarity dedup) applies **only to `category == "research"`**;
`maintenance`, `pkg_update`, `note_organization`, `home_control` auto-execute unguarded at
confidence ≥ 0.6. Each completion then fires F1's ledger/push.

### F3 — HIGH: completion notifications carry no payload
Title is the constant string `"Background task complete"` in all five delivery paths.
The message is the task query, not the outcome. This violates Sara's own invariant-5 payload
rule — but the payload lint lives in `deliberation_gate` and this source doesn't pass
through it. 1 engagement in 12 sends (8%) confirms it reads as noise.

### F4 — HIGH: `system.ungag.all=true` disables the entire hard-ban list (unintended)
`deliberation_gate._is_ungagged()` returns True for every category, so all `_BANNED_PHRASES`
(~90 phrases) and `_BANNED_CATEGORIES` (health/fitness/wellness) are skipped in **both** the
gate and `unified_notification`'s ban check. Only the payload lint and the
completion-announcement regex still apply. This was flipped as "measured un-gag" (THE SYSTEM
Phase 4) with the learned attention policy meant to govern instead — but per F5 the learned
layer is starved, so these domains are currently governed by almost nothing. `system.ungag.work`
also exists (redundant under `.all`).

### F5 — HIGH: learned-buzz cold-start deadlock ("too quiet" is structural)
`_learned_buzz_decision` requires a category to have ≥5 sends and ≥40% engagement in the
trailing 30 days before a normal-priority item may buzz. Post-July-25, most categories send
0–5 items per **month**, so they can never build a track record; they fail closed to
inbox-only; inbox items are archived unread (86%); engagement never accrues; the category
stays silent forever. Meanwhile the budget (F1) suppresses the few that do qualify. There is
no topic-level signal at all — "Risk Ninja" engagement doesn't make the next Risk Ninja item
more likely to surface, because learning is keyed on `category='checkin'`.

### F6 — MEDIUM: critical deliberation alerts get demoted to normal
`deliberation_gate._deliver_notification` maps `critical → "max"`, but
`_normalize_priority` has no `"max"` key → falls back to `"normal"`. A critical proposal
from deliberation would be budget-gated, buzz-gated, and sleep-held like a routine ping.
(Nothing has hit this path recently, but it's a one-line latent failure.)

### F7 — MEDIUM: 94% of deliberations are empty LLM spend
137 of 146 runs produced nothing. Root cause: `should_deliberate` forces a run every 1.5h of
waking idle regardless of content, and the staleness dimension inflates ambient events
(app-session, desktop-focus, weather) enough to cross the 1.5 threshold even when nothing
actionable exists. Each run is a ~55s local-Qwen call plus gate/journal writes. The journal
gets 127 near-identical "quiet day, watching X" entries a week (similarity dedup catches
some, action-bearing ones bypass it). Deep runs add 2 Sonnet calls/day that mostly re-read
the same quiet backlog.

### F8 — MEDIUM: generators still bypass the one brain
Direct-to-pipeline senders that do their own targeting, independent of deliberation and of
each other: `cross_system_synthesis` (hourly, sends `checkin` category), `calendar_prep`
(15-min, sends its own preps — "Barbell Row in 51 min", "Squat session coming up": 5 sent,
14 dedup-blocked, 0 engaged in 14d — you know your own program), `morning_proactive`
("Ready for some reading?", 0 engaged), `predictive_engine`, `bedtime`, `travel_nudge`,
`learning_digest`, plus reactive/interoception (legitimately direct). ONE_MIND folded the
*deliberation-shaped* loops into the kernel, but these peripheral brains still shape content
with their own heuristics — and they are the source of most "stuff I don't care about."

### F9 — MEDIUM: the attention inbox is a write-only junk drawer
86% of items archived (mostly by the 30-min expiry sweep — correctly never escalated to
push anymore, but also never summarized). Things Sara decided were worth *saying* but not
worth *buzzing* effectively evaporate. There's no end-of-day "while you were heads-down, 6
things accumulated — 2 worth a look" digest of attention items (the 8 AM digest is the
content-inbox, a different system; the held-notification flush only covers sleep-held
pushes).

### F10 — MEDIUM: nightly consolidation deadlock (currently red)
`nightly_memory_consolidation` hit `DeadlockDetectedError` at 03:00 07-27 against a
concurrent transaction (the 02:00–03:45 window runs ~10 write-heavy jobs: importance
rescoring batches vs. ML feature materialization / retrain / baselines all touching
episodes). No retry-with-jitter on this task; it just fails until tomorrow. Interoception
did its job (ledger + heads-up).

### F11 — LOW: nine-layer gauntlet, four dedup systems, two of them "legacy but on"
Topic dedup, attention-market content dedup, habituation, and category rate limits all
suppress repeats; the tuner and category-limit layers are explicitly legacy
(`notify.legacy_limits=true`) awaiting retirement, with `limit_divergence` logs already
accumulating for the comparison that hasn't happened. Order-dependence is subtle (e.g. the
tuner runs before the ban check; phrasing runs before dedup, so composer wording variation
can defeat title-hash topics). The why-trace only covers the sleep-gate slice, so "why
didn't I hear about X?" is answerable for holds but not for buzz/budget/tuner suppressions.

### F12 — LOW: dormant inner-life subsystems
`sara_goal`: 3 rows ever. Curiosity: 1 journal entry in 7 days (by design ≤1/day, but its
output lands in the journal that nothing surfaces). Dreams write journal entries the morning
brief "can" surface but isn't verified to. Emotional state, workspace, and self-model are
maintained but their observable effect on outputs is thin. These aren't harmful — they're
paying rent in complexity without visible behavior.

### F13 — LOW: salience scorer is hand-tuned and partially self-defeating
Weights/floors are static constants; the accumulation dimension counts *any* pending
observations (so ambient noise begets more deliberation); staleness deliberately inflates
everything after quiet stretches, which combined with the 1.5h forced gap guarantees the
empty-run pattern in F7. The `PREDICTION_VIOLATED` confidence-weighted path is the right
model — the rest of the scorer predates it.

---

## 5. What's genuinely good (keep, don't regress)

- **One chokepoint with receipts.** Every push funnels through `send_notification`; decisions
  log to `notification_log` with blocked-count coalescing; sleep decisions persist why-traces;
  the attention shadow recorder captures counterfactuals. Debuggability is far above typical.
- **The anti-nag stack is real engineering:** habituation with spontaneous recovery, thread
  mention caps with drop-on-negative/ignored, payload lint (with the clever proper-noun /
  memory-token heuristics), completion-announcement regex, per-category cooldowns,
  anomalous-day quieting, low-readiness batching, quiet-mode hard gate.
- **Sleep sensing done right:** multi-signal (Focus sensor, home-quiet, learned rhythm,
  recent interaction), fail-open, security/critical exempt, held items flushed as a wake
  digest.
- **Interoception is the best subsystem in the codebase.** Failure ledger + transient-streak
  suppression + recovery clearing + salience floors so Sara *feels* her own outages — and it
  demonstrably caught the consolidation deadlock and told you once, calmly.
- **Autonomy tiering with hard edges:** email_send/purchase/external_message are hard-blocked;
  email drafts are provably send-proof; home actions carry 5-min undo in a shared ledger;
  banned entities (heaters) enforced.
- **Operational hygiene:** DB-backed editable schedule with last-run status, queue topology
  validation, heavy-LLM exclusive locks, legacy-path counters, silent-failure trackers,
  observations consumed even on parse failure (no re-trigger loops).
- **The learned-attention design (θ per domain/context, anomaly floor, exploration ε,
  partial pooling) is the right architecture** — it's underfed, not wrong.

## 6. Structural cons (the honest architecture critique)

- **Suppression was scaled up faster than selection.** July's fixes correctly killed
  escalation-to-push and added a budget, but nothing was added that *finds the good stuff*
  and spends the budget on it. Result: budget spent by accounting noise (F1), good items
  suppressed, inbox ignored. Volume control without value ranking = quiet + annoying.
- **Category is the wrong granularity for relevance.** All learning (buzz, tuner, θ,
  cooldowns) keys on ~15 coarse categories. Your engagement is plainly *topic*-shaped
  (Risk Ninja, workouts, home security). The PKG and interest tables exist but don't feed
  the buzz decision.
- **Two philosophies coexist:** blacklist governance (ban phrases, hard caps, cooldowns) and
  learned governance (θ, buzz, tuner-retirement). Both half-on (`ungag.all` bypassing one,
  cold-start starving the other) is the worst quadrant.
- **The "one mind" consolidation stopped at the deliberation-shaped loops.** Peripheral
  generators still push directly with their own taste (F8), so the kernel can't enforce a
  coherent daily "what deserves David's attention" ranking.

---

## 7. Fix plan (prioritized, no changes applied)

### P0 — this week, mostly mechanical

1. **Fix the budget accounting (F1).** Exclude ledger/completion rows from
   `_daily_push_budget_available` — either add `'agent_task','background_task'` to the
   category exclusion, or (cleaner) write `_record_delivered` rows with a distinct marker
   the budget query filters (e.g. `priority='ledger'` or a `delivered_via` column) so
   "told him in chat" stops costing a push slot. Also count *only* rows that actually
   buzzed a phone (the desktop-toast path shouldn't debit the budget either).
2. **Guard all auto-execute categories like research (F2).** Generalize
   `_research_should_skip` (daily cap + 3-day similarity dedup vs `background_task`) to
   every `AUTO_EXECUTE_CATEGORIES` dispatch — or drop `maintenance` from auto-execute
   entirely; email/reminder checking is already owned by dedicated systems.
3. **Make completions carry their payload (F3).** Title = short task subject
   ("Email check: 2 need action"), message = the actual outcome summary (it already exists
   as `result_summary`). Consider `notify_on_complete=False` for *self-generated*
   maintenance tasks — Sara doesn't need to announce homework she assigned herself.
4. **Decide the ungag posture explicitly (F4).** Recommended: set `system.ungag.all=false`
   and enable only the domains you actually want unbanned (per-domain
   `system.ungag.health` etc.). Delete `system.ungag.work` if `.all` goes away. If you want
   full un-gag long-term, do it *after* F5 so something is actually governing.
5. **One-line priority fix (F6):** map `critical → "critical"` (and drop the dead `"max"`)
   in `deliberation_gate._deliver_notification`.
6. **Un-deadlock the 3 AM window (F10):** add retry-with-jitter to
   `nightly_memory_consolidation` and/or move it off the 02:30–03:00 ML cluster (e.g. 03:40),
   or take a `pg_advisory_lock` around the episode-write batch.

### P1 — the relevance engine (fixes "quiet AND annoying" for real)

7. **Break the buzz cold-start (F5).** Options that compose: (a) lower the floor to 3 sends
   and add partial pooling from a global prior (the θ system already does this — reuse the
   pattern); (b) count attention-item engagement (reply/complete/chat actions on inbox items)
   as `engaged` in `notification_log` so the inbox feeds the same signal; (c) during
   cold-start, allow 1 exploratory buzz per category per week (exploration ε, same as tier-0).
8. **Add topic-level interest weighting.** The buzz decision (and the deliberation prompt)
   should consult a small interest score: recent engagement keyed by extracted
   entities/topics (`Risk Ninja`, people names, `workout`) from PKG/`sara_interest`, not just
   category. Even a crude "notification mentions an entity David engaged with in 14 days →
   +1 exploratory buzz eligibility" would have delivered all three suppressed Risk Ninja
   items and skipped every generic one on 07-27.
9. **Daily attention-inbox digest (F9).** One scheduled evening (or wake-flush) summary of
   unread/expiring attention items, delivered as a single exempt-source push or into the
   morning brief. Silent expiry should mean "Sara decided it aged out", not "you never knew".
10. **Route the peripheral brains through the market (F8).** `cross_system_synthesis`,
    `calendar_prep` (non-meeting workout preps), `morning_proactive`, `predictive_engine`,
    `bedtime` → emit *proposals/observations* (or at minimum attention items) instead of
    direct sends, so one ranking spends the budget. Keep reactive/security/interoception
    direct. Kill or engagement-gate the workout-prep pings specifically — 0/5 engaged.

### P2 — efficiency + simplification

11. **Cheap pre-check before deliberating (F7):** skip the LLM call when the pending set is
    all-ambient (no observation ≥ ~0.6 and no category outside activity/rhythm/home), and
    stretch `acs.max_deliberation_gap_hours` to 3–4h — the 15-min sweeps and reactive engine
    already cover urgency. Expect ~70% fewer empty runs and journal entries.
12. **Retire one dedup layer per month (F11):** use the accumulated `limit_divergence` logs
    to turn off `notification_tuner`, then the static category limits, once the learned
    layer is fed (P1). Extend why-traces to buzz/budget/tuner suppressions so "why didn't I
    hear about X?" is always answerable.
13. **Decide the dormant subsystems (F12):** either wire dreams/curiosity output into the
    morning brief visibly and revive `sara_goal` as the deliberation prompt's standing
    context, or delete them. Half-alive features cost prompt tokens and audit time forever.

---

## 8. Verified-good behaviors worth stating once

- Quiet hours + night-mode deliberation thresholds work as designed (observed: no overnight
  non-critical pushes in the sample; overnight email insight correctly gated to ≥7 AM).
- The July-25 escalation-to-push deletion held: zero `attention_escalation` pushes since
  07-24.
- Dedup-blocked churn coalescing works (single row + `blocked_count` increments).
- Tell-once for task completions works (no duplicate completion announcements observed) —
  the ledger itself is fine; only its interaction with the budget (F1) is broken.
- Interoception escalation + recovery lifecycle observed end-to-end on the consolidation
  failure.

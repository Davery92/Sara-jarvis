# The System — Activation & Best-Assistant Plan

**Branch:** `assistant-experience-jarvis`
**Author:** grounded in a live code read of the repo on 2026-07-01
**Companion docs:** `THE_SYSTEM_DESIGN.md` (the architecture), `ASSISTANT_EXPERIENCE_PLAN.md` (presence/voice), `audit_jarvis_vision_2026_06`
**Execution status (2026-07-01, same day):** Phases A–E executed and verified live; see §8 below for what actually shipped, what was found to already be live, and what's left.

---

## 0. The one-paragraph thesis

Sara's brain is already built. The expensive parts — deliberation loop, consolidation,
PKG, emotional state, ACS daemon, **and the entire "The System" two-tier awareness stack**
— exist in code. The problem is not missing capability; it is that the finished machinery
is **switched off, disconnected, or invisible**. This plan is 80% *activation and wiring*,
20% *net-new*. Do not rebuild. Energize, close the loops, make it visible, then widen.

**If you do only three things:** (1) verify + activate The System behind the god view with
guardrails on, (2) close the learning loop so she actually learns *you*, (3) start capturing
the starved domains (work/goals/people) so she has a life to reason about — not just a body
and a house.

---

## 1. Verified current state (from code, 2026-07-01)

### What exists and works
- Deliberation → gate → consolidation loop, ACS daemon, PKG, emotional state — all live
  (per the 2026-06 audit: 55 scheduled jobs, ~14 deliberations/day, 1,924 journal entries).
- **The System code is present:**
  - `backend/app/services/world_model.py` — Phase 1 world model (foreground + background).
  - `backend/app/services/subconscious.py` — Phase 2 tier-0 (baselines, significance,
    promotion, `promotion_event` logging).
  - `backend/app/services/attention_learning.py` — Phase 3 learning loop (θ per domain×context).
  - `backend/app/tasks/subconscious_tier0.py` — celery tasks `.tick` and `.learn`.
  - `backend/app/routes/system_awareness.py` — god-view API: `/api/system/{world,stream,balance,promotions,overview}`.
  - `frontend/src/components/system/SystemDashboard.tsx` (12.5 KB) + nav entry `system`
    ("The System" / god view) wired in `App-interactive.tsx:442` and `views.ts:60`.

### The four things keeping it dormant (the actual work)
1. **Tables are outside the migration chain.** `signal_baseline`, `promotion_event`,
   `attention_policy` are created by a **raw SQL file**
   `backend/migrations/add_system_awareness_tables.sql`, *not* an alembic revision (chain
   ends at `075_progress_photos`). If that file was never run on the live DB, every tier-0
   tick is silently failing inside a `try/except` and logging a warning. **Unverified.**
2. **Tier-0 escalation is OFF.** `subconscious.py:51` `ESCALATE_FLAG =
   "system.tier0.escalate_to_conscious"`, `get_flag(..., default=False)`. Promotions are
   logged to `promotion_event` but **never reach `observation_log`** → never reach the
   conscious loop → never reach the user. It's running in a sealed jar.
3. **The gag is still hard-on.** `deliberation_gate.py:89`
   `_BANNED_CATEGORIES = {"health","fitness","wellness"}` plus ~35 banned phrases. Un-gag
   machinery exists (`system.ungag.<domain>` flags, `_is_ungagged()`), but every flag
   defaults OFF, so health/fitness/wellness are still blanket-rejected regardless of the
   learned policy.
4. **The learning loop is half-wired.** `attention_learning.learn_from_recent_engagement`
   reads `notification_log` engagement directly and nudges θ — good. **But** consolidation's
   own `salience_adjustments` (computed at `consolidation.py:121,344,445`, "if David ignores
   a category lower its weight") are **still dropped** — nothing reads them. The design's
   "wire consolidation's adjustments into `attention_policy`" is not done.

### Secondary gaps (quality of the awareness itself)
- **Sensory diet is still thin at the source.** `run_subconscious_tick` only gathers three
  signals: health (`daily_recovery_log`), work (`git_commit` count/24h), goals (`sara_goal`
  count). **Home is explicitly skipped** (comment: event-rate too volatile), **people has no
  source**, comms/calendar aren't evaluated. So even when escalation flips on, the balanced
  stream is mostly health + a commit count.
- **`relevance` is hardcoded 0** (`subconscious.py:132`, "Phase 3 will wire context-relevance").
  Significance is currently anomaly + a novelty nudge only — starved domains can't get a
  relevance boost yet.
- **Beat scheduling is DB-driven** (`beat_scheduler=DBScheduler`, entries live in the
  `scheduled_job` table). The `.tick`/`.learn` tasks are *registered* (importable) but may
  have **no `scheduled_job` rows** → never fire on a cadence. **Unverified.**

---

## 2. Guiding principles (inherited from the design; do not violate)

1. **Volume ≠ attention.** Never equalize data volume; equalize what reaches consciousness.
2. **Guardrails before un-gag.** Anomaly override + exploration floor must be provably live
   *before* any category is un-gagged. A learned "you ignore HR" must never mute "resting HR
   +30 over baseline."
3. **Visible by default.** If she computed it, you can see it. The god view is both the
   payoff and the safety instrument — ship/verify it first.
4. **No backfill.** Capture the starved domains going forward; balance emerges over days.
5. **Reversible autonomy.** Every new autonomous action carries source + confidence and an
   undo path (extend the standing-order 5-min undo pattern).

---

## 3. Phased plan

Each phase ships something usable and is ordered by *risk-adjusted leverage*. Phases A–C are
mostly verification + flag flips (cheap, high leverage). D–F are net-new capture + polish.

### Phase A — Pre-flight: prove the machinery is actually alive (½–1 day)
**Goal:** convert "exists in code" → "running in the live DB." No behavior change to the user.

- **A1. Apply the tables to the live DB.** Confirm `signal_baseline`, `promotion_event`,
  `attention_policy` exist:
  ```sql
  SELECT to_regclass('signal_baseline'), to_regclass('promotion_event'), to_regclass('attention_policy');
  ```
  If any are NULL, run `backend/migrations/add_system_awareness_tables.sql`. **Then fold that
  SQL into a real alembic revision `076_system_awareness_tables.py`** so a fresh deploy isn't
  missing them (currently a latent prod-parity bug). Use `CREATE TABLE IF NOT EXISTS` so it's
  idempotent against the DBs where the raw SQL already ran.
- **A2. Confirm the beat entries exist.** Query `scheduled_job` for
  `app.tasks.subconscious_tier0.tick` and `.learn`. If absent, seed them:
  tick every **10 min**, learn daily at **~3:00 AM ET** (after the 9 PM/2 PM consolidations
  have run). Remember: crontabs are **ET**, not UTC (`feedback_no_utc`).
- **A3. Watch one tick end-to-end.** Trigger `.tick` manually; confirm rows land in
  `promotion_event` and `signal_baseline` and the log shows
  `[tier0] tick: ctx=… evaluated=3 promoted=…`. If it throws, the table/DDL step failed.
- **A4. Ship the god view (read-only).** Load `SystemDashboard.tsx` and hit
  `/api/system/overview`, `/balance`, `/promotions`, `/stream`. This is Phase 0 of the design
  and the single highest felt-intelligence:cost ratio — "you can *see* what she knows." It is
  also the instrument every later phase is gated on.
- **Accept:** the god view renders live data; `promotion_event` grows every 10 min; the
  balance meter shows a domain distribution (expected: heavily health-skewed — that's the
  baseline we're about to fix).

### Phase B — Close the learning loop (1–2 days)
**Goal:** stop throwing away the note she writes to herself. She learns *David*.

- **B1. Wire consolidation → attention_policy.** At the end of the consolidation pass
  (`consolidation.py`, where `result.salience_adjustments` is populated), translate each
  category adjustment into a θ nudge on the matching domain via
  `attention_learning.apply_engagement` (map category→domain with the existing `_CAT_DOMAIN`
  table). This is the design's explicit "wire in" step and is currently missing.
- **B2. Feed the accept/reject learner.** `behavioral_pattern` has 161 "active" patterns with
  `times_suggested/accepted/rejected` all **0** — the learner has never seen a label. On every
  proactive suggestion surfaced and every attention-inbox confirm/defer/dismiss, increment the
  counters so promotion learning has real accept/reject signal, not just read/ignore.
- **B3. Verify the update rule moves.** After B1/B2 run for a day, confirm `attention_policy`
  θ values have moved off their priors and `promotion_event` engagement outcomes are being
  written back. Add these to the god view's "learned preferences" panel with one-click
  override.
- **Accept:** per-cell θ demonstrably moves with engagement; a simulated "stop telling me
  this" raises that cell's θ within a day; the god view shows what she's learned per
  domain×context.

### Phase C — Guardrails on, then measured un-gag (2–3 days, gated on B)
**Goal:** replace the blanket ban with the learned filter — **one domain at a time**, watched.

- **C1. Prove the guardrails.** Before flipping anything: verify `anomaly_floor` (0.92) always
  promotes regardless of θ, and `explore_rate` (ε=0.1) keeps every domain sampled. Write a
  test that a suppressed cell (θ→0.95) still promotes a |z|≥2.5 anomaly. **Non-negotiable
  precondition for C2/C3.**
- **C2. Flip escalation ON.** Set `system.tier0.escalate_to_conscious = true`. Now promotions
  reach `observation_log` → the conscious loop. Watch the balance meter for a day. Because the
  gag is still up, health promotions still get rejected at the gate — that's fine; this step
  is about proving the tier-0→conscious path carries a *balanced* stream (work/goals begin to
  appear).
- **C3. Un-gag domain-by-domain.** Retire `_BANNED_CATEGORIES` one domain at a time via
  `system.ungag.<domain>`, starting with the domain the balance meter shows healthiest
  coverage on. After each flip, watch the god view for regression (re-skew, nag complaints).
  If a domain re-skews, you *see* it instead of feeling nagged. Health is last (highest bias).
- **Accept:** conscious-stream domain distribution is no longer >50% any single domain;
  a real anomaly breaks through a suppressed cell (override verified live); no repeat-nag
  regressions in the god view.

### Phase D — Fix the sensory diet at the source (3–5 days)
**Goal:** give her a life to reason about. The starved domains (work/goals/**people**) are
the deepest problem — an assistant that only senses your body and your house can't be Jarvis.

- **D1. Work signals, richer than a commit count.** Beyond `git_commit`/24h, land editor/
  project/PR activity and Code-Mode/managed-host task outcomes into the conscious stream as
  they happen. Lean on existing plumbing (`code_mode.py`, `host_command_handler.py`,
  `project_tracker_service.py`).
- **D2. Goals as first-class.** `sara_goal` (migration 073) is new and nearly empty. Wire goal
  creation/progress from chat + the ACS daemon so `goals` stops being a count and becomes real
  intent she can reference.
- **D3. People/relationships (currently 0 rows, 0 sources).** Start the smallest real capture:
  who David mentions, who he's meeting (calendar attendees), comms threads. Land into the PKG
  people layer going forward. This is the biggest coverage hole in the audit table.
- **D4. Wire `relevance` (kill the hardcoded 0).** In `evaluate_signal`, compute
  relevance-to-active-context (tie to current foreground: active work, next event, open
  loops) so starved domains get the boost the design intends. This is the difference between
  "anomaly detector" and "attends to what matters right now."
- **D5. Event-level home anomalies.** Replace the skipped volatile hourly-rate signal with
  context-conditioned event anomalies ("door opened 3am while asleep & away").
- **Accept:** balance meter shows work/goals/people present and non-zero; a relevant work
  signal during focused time promotes where it wouldn't during `away`.

### Phase E — Presence, voice, continuity finish (parallel-safe, from ASSISTANT_EXPERIENCE_PLAN)
**Goal:** make the now-awake mind *felt*, not buried three taps deep.

- **E1. On-device verification of the iOS system layer.** Siri/App-Intents, widgets, Live
  Activities are built + EAS-signed (2026-05-30) but **never functionally verified on a
  physical device**. This is the "Sara is on your lock screen" payoff — highest remaining
  presence leverage. (`ios-app/NATIVE_FEATURES.md`.)
- **E2. Surface voice failures.** `voice.ts` swallows errors in catch blocks; a failed
  transcribe reads as "broken." Replace with "Couldn't hear that" vs "Voice service
  unavailable." (`ios-app/src/services/voice.ts`, `useSaraChat.ts`.)
- **E3. Web voice (P0.2, still open).** Backend `/api/voice-agent/{transcribe,speak}` already
  exist; wire a mic button + speaker toggle into `ChatInterface.tsx`. Cheapest big presence
  win left.
- **E4. Route the god view into a primary destination**, not a hidden power-user page — it's
  the flagship "she knows everything" surface.
- **Accept:** speaking to web chat round-trips; iOS widget shows live state on a real device;
  voice failures show a clear message.

### Phase F — Focus & trust (ongoing)
**Goal:** keep a louder, more agentic Sara *welcome*.

- **F1. Cut the sprawl (P3.1, explicitly deferred).** 24 web views / 41 iOS screens dilute the
  flagship feel; Orchestrator Lab alone is 1,262 LOC. Collapse to ~5 primary destinations per
  platform; demote ACS introspection / Sensory Monitor / Orchestrator Lab under "Advanced."
- **F2. Reversible autonomy everywhere.** Extend the standing-order 5-min undo window to any
  new autonomous action; every world-model fact carries source + confidence (guards the
  flat-240-weight / cumulative-steps class of bug — see `gotcha_steps_cumulative`).
- **F3. Anti-nag as policy, not bans.** Enforcement lives in the learned θ + hard-negative
  "stop" path, not ad-hoc phrase bans. Retire banned-phrase list as domains un-gag cleanly.
  (See `feedback_no_repetitive_nags`.)

---

## 4. Data / wiring changes (concrete)

| Change | File(s) | Type |
|---|---|---|
| Fold `add_system_awareness_tables.sql` into alembic `076_…` | `backend/alembic/versions/` | new revision |
| Seed `scheduled_job` rows for `.tick` (10m) + `.learn` (daily 3am ET) | `scheduled_job` table / seed script | data |
| Wire `salience_adjustments` → `apply_engagement` | `consolidation.py` end | wire |
| Increment `behavioral_pattern.times_suggested/accepted/rejected` | suggestion + attention-inbox action paths | wire |
| Compute `relevance` in `evaluate_signal` (remove hardcoded 0) | `subconscious.py:132` | logic |
| Add work/goals/people/home gatherers | `subconscious.py` `run_subconscious_tick` | logic |
| Flip `system.tier0.escalate_to_conscious` (after guardrail test) | `tunable_setting` | flag |
| Flip `system.ungag.<domain>` per domain (after balance-meter check) | `tunable_setting` | flag |
| Guardrail test: suppressed cell still promotes an anomaly | new test | test |

**No backfill.** New-domain capture is going-forward only.

---

## 5. Success criteria (measurable)

- **Machinery alive:** `promotion_event` grows on a cadence; god view renders live.
- **Balance:** conscious-stream domain distribution never >50% one domain; work/goals/people
  present and non-zero.
- **Learning works:** per-cell θ moves with engagement; a "stop" silences a cell within a day;
  a genuine anomaly still breaks a suppressed cell (override verified).
- **No collapse:** no domain goes permanently silent (exploration floor holds); slow-drift
  trends (e.g. resting HR creep) still surface.
- **Felt intelligence:** you can open the god view and see what she knows and why; iOS presence
  is live on-device; engagement up, nags down.

---

## 6. Sequencing & risk

```
A (verify+godview) ──► B (close learning loop) ──► C (guardrails → un-gag)
        │                                                │
        └────────────► D (sensory diet) ◄───────────────┘   (D feeds C's balance)
E (presence/voice) and F (focus/trust) run in parallel — no dependency on A–D.
```

- **Highest risk:** flipping escalation/un-gag before guardrails are *proven* (C1 gates C2/C3).
- **Latent prod bug:** the tables-outside-alembic issue (A1) — a fresh deploy silently lacks
  the tables and tier-0 no-ops forever. Fix in A1 regardless.
- **Lowest risk / highest leverage:** A4 (god view) and B1 (wire the dropped adjustments).
- **Deploy note:** backend/celery load code only on container restart, and restarting kills
  in-flight dispatch tasks — verify runtime artifacts, don't assume the working tree is live
  (`gotcha_deployed_code_lags`).

---

## 7. Explicit non-goals

- ❌ No rebuild — revive and connect existing machinery.
- ❌ No pre-seeding / backfilling history.
- ❌ No equalizing data *volume* — health/home stay high-volume, just quiet unless earned.
- ✅ Learned promotion (not rule-based-first), domain × small context set, hard guardrails,
  visible by default.

---

## 8. Execution log (2026-07-01)

Phases A–E were executed and verified against the live stack the same day this plan was
written. What follows is what actually happened, not the a-priori plan — including two
findings that changed the plan mid-execution.

### Phase A — DONE
- All three tables (`signal_baseline`, `promotion_event`, `attention_policy`) already existed
  on the live DB (created via the raw SQL file by hand). Folded into a real alembic revision
  `076_system_awareness_tables.py` (idempotent `CREATE TABLE IF NOT EXISTS`) so a fresh deploy
  no longer silently lacks them — applied, `alembic_version` now at `076_…`.
- **Finding: escalation and un-gag were already flipped live**, 16 days before this session
  (`system.tier0.escalate_to_conscious=true`, `system.ungag.work=true`, `system.ungag.all=true`,
  all set within one hour on 2026-06-15 — not the "one domain at a time" the design called
  for). Verified this caused **no regression**: zero health/fitness/wellness notifications
  sent since, because the learned `attention_policy` threshold (health θ≈0.7-0.75, well above
  most signals' significance) is doing its job as a real guardrail, not a leftover ban. Traced
  actual promotions into the Redis observation queue (`"HRV 35 ms"`, salience 0.246) — reaching
  deliberation correctly, just not clearing its own bar to become a push. This closed most of
  Phase C's C2/C3 before I got there.
- God view API (`/api/system/{overview,balance,promotions,world}`) confirmed live (200s),
  frontend `SystemDashboard.tsx` confirmed serving with no console errors.

### Phase B — DONE
- Wired consolidation's `salience_adjustments` into `attention_policy` (new
  `attention_learning.apply_consolidation_adjustments`, called from
  `consolidation._apply_results`). Smoke-tested directly: `{"agent_task": 0.05}` correctly
  lowered the `work` domain threshold across all 5 contexts.
- **Bigger finding on B2:** `morning_proactive_service.py` (620 lines — pattern-trigger
  evaluation, LLM message crafting, delivery via the gated `unified_notification` pipeline,
  response recording) was **fully built but had zero scheduler entry point anywhere in the
  codebase** — not a missing-counter-increment bug, an orphaned service. This is *why*
  `behavioral_pattern.times_suggested/accepted/rejected` sat at 0 for all 257 rows, and why the
  pattern→standing-order promotion pipeline (`standing_order_service.promote_pattern`, which
  requires `status='confirmed'`) never activated.
  - Asked David before enabling (new push-notification-generating behavior is user-visible,
    not an internal wire) — approved.
  - Added `app/tasks/morning_proactive.py` + celery registration + `scheduled_job` row
    (`morning-proactive-check`, daily 9am ET).
  - **Found and fixed two real bugs** while smoke-testing: (1) the raw LLM call was missing
    `chat_template_kwargs: {"enable_thinking": False}` — the exact qwen3.6 empty-`content`
    failure mode in `[[feedback_qwen_thinking]]`, silently killing every message-craft call;
    (2) `_send_notification` only called `record_suggestion` when `result["sent"]` was `True`,
    but normal/low-priority notifications correctly route to the attention inbox with
    `sent=False, attention_item_id=<uuid>` (per `[[gotcha_attention_queue_priority_push]]`) —
    so real deliveries were never being recorded. Fixed to count `attention_item_id` as
    delivery too.
  - Verified end-to-end after both fixes: 6/6 triggered patterns delivered to the attention
    inbox with natural LLM-crafted messages, `behavioral_pattern.times_suggested` incremented
    for all 6, status→`suggested`.

### Phase C — DONE
- C2/C3 (escalate + un-gag) were already live per the Phase A finding — not re-executed.
- C1 (guardrail proof): extracted the promotion decision into a pure `decide_promotion()`
  function in `subconscious.py` (no behavior change — `evaluate_signal` now calls it) and
  added `tests/test_subconscious_guardrails.py`, 9 passing tests proving (a) a genuine anomaly
  always overrides learned suppression, even in the pathological case where threshold has
  drifted above anomaly_floor, and (b) the exploration floor still fires on a fully-suppressed
  cell. `pytest`/`fakeredis` aren't in `requirements.txt` (pre-existing gap, not fixed — the
  whole `tests/` directory of ~10 files has the same issue); installed ad hoc into the running
  container to verify, so this doesn't survive a rebuild without adding them to requirements.

### Phase D — PARTIAL (by design)
- D4: `compute_relevance(domain, context)` replaces the hardcoded `relevance = 0.0`, weighted
  toward starved domains (work/goals/people) when David is actually present (focused/available),
  zero lift for the already-saturated health/home domains. Tested.
- D1: added a second, richer work signal (`background_task` completions in 24h) alongside the
  existing commit count.
- D5: added a context-conditioned home signal — event-rate while `asleep`/`away` only (keyed
  as a distinct `signal_key` per context so each learns its own near-zero baseline, avoiding
  the "raw rate is too volatile" problem noted in the original code comment), reusing
  `signal_baseline` — no new tables.
- D3 (people): **intentionally not done.** `relationship_state` is 0 rows, `calendar_event` has
  no attendee column — there is no real signal to gather yet. Deliberately did not fake a
  proxy that would always read 0 (adds noise, no information). Real fix needs new capture
  (PKG people mentions, calendar attendees) — left as designed follow-up, not attempted today.
- Verified via a manual tick: 7 signals evaluated (up from 5), home signal correctly skipped
  since current context was `available` (not asleep/away) — conditional logic confirmed working.

### Phase E — DONE (web voice); iOS on-device NOT DONE (no physical device)
- Web voice (P0.2): implemented the mic button (record → `/api/voice-agent/transcribe` →
  populate input) and wired the **already-existing but disabled** TTS button
  (`handleSpeak` was a stub — UI toggle, icons, and `speakingMessageIndex` state already
  existed) to `/api/voice-agent/speak`. Both fail gracefully with a visible error message
  instead of silent no-ops (the exact gap `ASSISTANT_EXPERIENCE_PLAN.md` flagged for iOS).
  `tsc --noEmit` clean.
  - Verified live via Playwright against the running dev stack (minted a real JWT, real
    cookie, real browser): chat page renders the mic button; sending a message and clicking
    "Read aloud" produced a real `200` from `/api/voice-agent/speak` and audible playback
    (screenshotted mid-flow).
  - **Real finding, not a bug:** `navigator.mediaDevices` is `undefined` when testing over
    `http://10.185.1.180:3000` (plain HTTP, non-`localhost` host) — browsers restrict mic
    access to secure contexts. Production (`sara.avery.cloud`) is HTTPS so this isn't a
    production issue; the code already catches this and shows "Couldn't access the
    microphone" rather than crashing. To test mic locally, use `http://localhost:3000`
    specifically (the one HTTP exception Chromium makes) rather than the LAN IP.
- iOS on-device Siri/widgets/Live Activities verification (E1): cannot be done from this
  environment — no physical device access. Still open exactly as this plan noted.

### Phase F — NOT EXECUTED (by design)
- Audited only: still 24 primary nav views, unchanged from the count `ASSISTANT_EXPERIENCE_PLAN.md`
  recorded 16 days ago — no regression, no new sprawl. Cutting/hiding views is a visible,
  semi-destructive product decision that `ASSISTANT_EXPERIENCE_PLAN.md` itself already recorded
  as **deferred by David** — did not re-litigate that call unilaterally. Recommendation stands
  as written in §3 Phase F; execute when David wants to revisit it specifically.

### Net changes this session
New: `backend/alembic/versions/076_system_awareness_tables.py`,
`backend/app/tasks/morning_proactive.py`, `backend/tests/test_subconscious_guardrails.py`.
Modified: `backend/app/services/attention_learning.py`, `backend/app/services/consolidation.py`,
`backend/app/services/subconscious.py`, `backend/app/services/morning_proactive_service.py`,
`backend/app/celery_app.py`, `frontend/src/components/ChatInterface.tsx`. DB: 1 new
`scheduled_job` row (`morning-proactive-check`), 1 new alembic version applied. No destructive
actions taken; nothing force-pushed or deleted.

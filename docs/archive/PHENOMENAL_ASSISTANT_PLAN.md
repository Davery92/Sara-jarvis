# Phenomenal Assistant Plan — everything after The System

**Branch:** `assistant-experience-jarvis`
**Grounded in:** live code + DB read on 2026-07-01, the same day THE_SYSTEM_ACTIVATION_PLAN.md §8 executed.
**Companion docs:** `THE_SYSTEM_ACTIVATION_PLAN.md` (done), `THE_SYSTEM_DESIGN.md`, `ASSISTANT_EXPERIENCE_PLAN.md`
**Scope rule: no deferrals.** Everything previously punted (people capture, sprawl cut, iOS
on-device, daemon deploy) is scheduled here with a concrete design. The only external
dependency is David's hands on a physical iPhone (§9).

---

## 0. The one-paragraph thesis

The System is live: tier-0 ticks every 10 minutes (585 promotions/24h), the learning loop
closes, guardrails are tested, morning proactive runs, the god view renders. What separates
this from *phenomenal* is no longer machinery — it's that Sara senses a **body and a house
but not a life**. She reads zero emails as signals despite 1,325 synced rows, knows 21
people-as-facts but tracks no relationships, holds 1 goal and 4 follow-up threads, and when
she decides something matters her only real verbs are "notify," "flip a light," and
"research." This plan gives her the missing senses (comms, people, calendar-as-people),
the missing memory of intent (goals, commitments, open loops), wider hands (drafting,
preparing, following through — all reversible), and the presence layer (iOS verified on
metal, learning made visible, 24 views cut to 6).

**Verified starting numbers (2026-07-01):** `promotion_event` 9,262 total / 585 last 24h;
`attention_policy` 27 cells; `behavioral_pattern` 6 suggested; `sara_goal` 1 row;
`followup_thread` 4 rows; `relationship_state` 0 rows (and it's Sara↔David phase state, not
David's people — the people layer genuinely has no store); `email` 1,325 rows, 39/wk, with
`importance_score`/`action_required`/`summary` already computed by `email_sync.analyze_recent_emails`;
`calendar_event` has **no attendee column**; PKG has 21 `PKG_Person` nodes; ACS daemon v0.8.0
heartbeating from the sara VM, but the repo's `acs-daemon/` goals changes are uncommitted and
undeployed; **268 files uncommitted** on this branch including the entire System activation.

---

## 1. Guiding principles (inherited; still binding)

1. **Volume ≠ attention** — new domains feed the *learned* promotion path, never bypass it.
2. **Reversible autonomy** — every new verb ships with an undo path and a ledger entry
   (source + confidence). Drafts, never sends. Proposes, never commits externally.
3. **Visible by default** — every new sense and every learned change shows in the god view.
4. **No backfill** — capture going forward; baselines emerge over days.
5. **Anti-nag is policy** (`feedback_no_repetitive_nags`) — commitments/follow-ups ride the
   existing `followup_thread` mention caps, not new nag channels.
6. **ET everywhere user-facing** (`feedback_no_utc`); **qwen thinking off** for short outputs
   (`feedback_qwen_thinking`); **deployed code lags working tree** (`gotcha_deployed_code_lags`).

---

## 2. Phase 0 — Foundation: commit, deploy, de-risk (½ day) — DO FIRST

The entire System activation exists only in the working tree + running containers. One bad
rebuild loses the code while the DB flags stay flipped — tier-0 would silently break.

- **0.1 Commit the branch in logical commits.** Suggested grouping over the 268 files:
  (a) `feat(system): activate The System` — alembic 076, subconscious/attention_learning/
  consolidation wiring, guardrail tests; (b) `feat(proactive): morning proactive scheduler +
  fixes`; (c) `feat(webapp): web voice (mic + TTS)`; (d) `feat(acs): goals-aware daemon`
  (acs-daemon/*); (e) the long tail (route/service edits). Add `__pycache__`/`.pyc` to
  `.gitignore` — compiled artifacts are currently tracked and polluting every diff.
- **0.2 Test deps into requirements.** `pytest`, `pytest-asyncio`, `fakeredis` →
  `backend/requirements.txt` (or a `requirements-dev.txt` installed in Dockerfile.dev) so
  `tests/test_subconscious_guardrails.py` (the C1 guardrail proof) survives rebuilds and can
  run in CI/pre-deploy.
- **0.3 Deploy the goals-aware ACS daemon.** Repo `acs-daemon/` (mind.py, backend_client.py,
  prompt.py changes) → `/opt/acs-daemon/` on the sara VM (10.185.1.176), restart
  `acs-daemon` unit, confirm `sara_daemon_state.version` bumps past 0.8.0. Note: this
  environment's SSH keys are not authorized on the VM — either David runs the deploy, adds
  the key, or we route it through the managed-hosts dispatch (`host_command_handler`) if the
  VM is registered.
- **0.4 Backend/celery restart to load committed code**, timed to avoid killing in-flight
  dispatch tasks (`gotcha_deployed_code_lags`).
- **Accept:** clean `git status`; guardrail tests runnable in a fresh container; daemon
  heartbeat shows new version.

---

## 3. Phase 1 — Comms becomes a sense (1–2 days)

Email is already synced *and analyzed* (`importance_score`, `action_required`, `summary`,
`category` per row via `app/tasks/email_sync.py`) — the subconscious just never looks.
Highest awareness-per-line-of-code in the codebase.

- **1.1 Tier-0 gatherers** in `subconscious.run_subconscious_tick` (pattern-match the
  existing health/work blocks):
  - `("comms", "unhandled_important", n, …)` — count of emails with
    `action_required=true OR importance_score >= 0.7`, `is_read=false`, received > 4h ago.
  - `("comms", "oldest_action_age_h", h, …)` — age in hours of the oldest unread
    `action_required` email (0 if none). Catches the "sitting on something" drift.
  - `("comms", "inbound_24h", n, …)` — volume anomaly (a quiet inbox on a normally busy
    day is signal too).
- **1.2 Domain plumbing.** Add `comms` to the attention-policy prior seeding and to
  `attention_learning._CAT_DOMAIN` (so consolidation's salience adjustments and notification
  engagement map onto it). Starved-domain relevance boost in `compute_relevance` already
  keys off a domain list — add `comms` at the work/goals tier.
- **1.3 Deliberation context.** Include a compact comms line in the deliberation prompt's
  working-memory block (top 1–2 unhandled important emails: sender, subject, age) so a
  promoted comms observation has enough context to reason about, not just a count.
- **1.4 God view.** Comms appears in the balance meter automatically once promotions flow;
  add the unhandled-email list to the world-model foreground panel.
- **Accept:** comms shows non-zero in `/api/system/balance` within 2 days; a seeded
  high-importance unreplied email promotes; θ for comms cells moves with engagement.

---

## 4. Phase 2 — The people layer (3–5 days) — the acknowledged biggest hole

`relationship_state` turned out to be Sara↔David phase tracking, not people. PKG has
`PKG_Person` nodes (21, chat-extracted) but nothing interactional. Build the smallest real
person store with live sources that already flow.

- **2.1 New table `person` (alembic 077).**
  `id, user_id, canonical_name, emails jsonb, aliases jsonb, pkg_person_ref,
  first_seen_at, last_interaction_at, last_interaction_kind (email_in/email_out/meeting/mention),
  interaction_count int, mention_count int, importance float default 0.5, is_vip bool,
  muted bool, notes text, created_at, updated_at` + unique on `(user_id, canonical_name)`
  and a GIN index on `emails`. Postgres is source of truth for interaction state; PKG_Person
  stays the semantic/fact layer, linked by `pkg_person_ref`.
- **2.2 Email capture (the live source).** In `email_sync` post-analysis: upsert `person`
  from `sender_email`/`sender_name` (and `to_recipients` on David's outbound if the mailbox
  syncs sent items), bump `last_interaction_at`/`interaction_count`. Normalize via a small
  alias map (same human, multiple addresses). Skip obvious bulk/no-reply senders
  (`category`/heuristics from the analyzer).
- **2.3 Chat-mention capture.** `pkg_extractor` already extracts Person facts from
  conversation — extend it to also upsert/bump the `person` row (`mention_count`,
  `last_interaction_kind='mention'`).
- **2.4 Tier-0 people signals** (all cheap queries over `person`):
  - `new_person_7d` — count of first-seen-this-week people (novelty).
  - `reconnect_overdue` — count of non-muted people whose gap since `last_interaction_at`
    exceeds 2× their own historical cadence (EWMA per person via `signal_baseline`,
    keyed `people:cadence.<person_id>` — reuses the existing baseline table).
  - `mentions_24h` — conversation social density.
- **2.5 Surfaces.** God view "People" panel (recent, overdue, new); chat context injection
  ("Mike — last emailed 2026-06-24 about the API integration") via the existing PKG context
  provider, now enriched with interaction recency; `muted`/`is_vip` toggles in the
  Knowledge view (people already a keyword there).
- **Accept:** `person` grows from email flow within a week without any manual entry; people
  domain non-zero in the balance meter; asking Sara "who am I overdue with?" answers from
  data.

---

## 5. Phase 3 — Goals, commitments, open loops (3–4 days)

`sara_goal` (1 row) has the right shape (`plan`/`progress` jsonb, `last_progress_at`) and
`followup_thread` has the right machinery (windows, mention caps, anti-harping). Neither has
inflow. "You said you'd call the plumber — it's Thursday" is the single most Jarvis-like
behavior and nothing owns it today.

- **3.1 Commitment extraction.** Extend `thread_extractor`'s LLM prompt to also extract
  *David's own stated commitments* ("I'll X", "I need to Y by Friday", "remind me to…"
  that didn't become a reminder) → write as `followup_thread` rows with
  `source='commitment'`, `topic_category='commitment'`, `follow_up_after/before` from the
  stated or inferred timeframe. No new table; the anti-nag caps apply automatically.
- **3.2 Goal inflow from chat.** New tool in `app/tools/` registry: `manage_goal`
  (create / progress-note / complete), so "let's make X a goal" in chat lands in `sara_goal`.
  The daemon side ships in Phase 0.3 (goals-aware daemon deploy). Deliberation prompt gains
  a compact open-goals block (title + days since `last_progress_at`).
- **3.3 Tier-0 goal/commitment signals:**
  - `goals.stalled` — open goals with `last_progress_at` > 7 days (count).
  - `goals.commitments_due` — open `source='commitment'` threads inside their
    `follow_up_before` window (count).
  This replaces today's bare `open_goals` count with signals that *mean* something.
- **3.4 Follow-through behavior.** The existing follow-up delivery path (thread_manager →
  gated notifications) already handles surfacing; commitments ride it. On resolution
  ("done" / "not doing it"), record `david_response` — this is accept/reject signal for
  the Phase B learner too (`behavioral_pattern`-style counters).
- **Accept:** a test commitment stated in chat surfaces on its due day and never more than
  `max_mentions` times; ≥5 real goals exist within two weeks; `goals.stalled` promotes when
  a goal genuinely stalls.

---

## 6. Phase 4 — Widen the act loop, reversibly (3–5 days)

Deliberation already dispatches research/maintenance tasks to the VM, executes home actions,
and proposes tasks to David. The action space is missing the assistant verbs: *draft*,
*prepare*, *schedule-shaped suggestions*. All reversible; nothing external sends without
approval.

- **4.1 New task categories** in the deliberation schema + gate
  (`deliberation_prompt.py` task rules, `deliberation_gate._process_task_proposals`):
  - `email_draft` — Sara writes a reply draft for an `action_required` email → lands in
    the attention inbox with the draft body; David copies/edits/discards. **Never sends.**
  - `meeting_prep` — assemble a prep note (attendees from Phase 5, related PKG facts,
    open threads with those people, last email exchange) → note + inbox item, timed
    30–60 min before the event via `calendar_prep.py`.
  - `commitment_nudge` — bounded to the Phase 3 thread caps (this is a routing category,
    not a new channel).
- **4.2 Action ledger.** Every autonomous action (existing home/research/task + new
  categories) writes `action_ledger` (alembic 078): `id, user_id, action_type, source
  (deliberation/standing_order/morning_proactive), source_ref, confidence, description,
  undo_token, undone_at, created_at`. Standing orders' 5-min undo becomes the general
  pattern: anything with a reversible effect registers an undo callable. God view gets an
  "Actions" panel — what she did, why, one-tap undo where applicable.
- **4.3 Dispatch hardening.** The June hang ("no activity 8+ min") is fixed; add a
  watchdog policy as code: per-task max-runtime + single silent retry + only notify David
  on *repeated* failure with usable partial output surfaced (`feedback_no_repetitive_nags` —
  never push "failed" when there's usable output).
- **Accept:** an `action_required` email yields an inbox draft within a deliberation cycle;
  every autonomous action is visible in the ledger with source + confidence; undo works on
  a home action end-to-end.

---

## 7. Phase 5 — Calendar grows people (2–3 days + one device pass)

- **5.1 Schema:** alembic 079 — `calendar_event.attendees jsonb default '[]'`,
  `organizer varchar`, backfill-free.
- **5.2 iOS sync sends attendees.** The calendar sync is device-driven (EventKit):
  `EKEvent.attendees`/`organizer` → include `[{name, email?, status}]` in the sync payload
  (ios-app calendar sync service + backend `routes/calendar_events.py` accept). I write
  both sides; David installs the build and opens the app once to re-sync (§9).
- **5.3 Person linkage.** On event upsert with attendees: match/upsert `person` rows
  (name/email), `last_interaction_kind='meeting'` when the event passes. Meetings become
  people-interaction inflow alongside email.
- **5.4 Meeting prep uses it.** `calendar_prep` + Phase 4.1 `meeting_prep`: "Call with
  Mike in 45 min — last exchange 6/24 re: AgencyZoom API; open thread: waiting on his
  pricing sheet."
- **5.5 Ownership reasoning** (June audit gap): events distinguish `organizer==David`
  vs invited — prep and nudges phrase accordingly.
- **Accept:** next synced meeting shows attendees in the DB; a prep note names the person
  with real history; the person's `last_interaction_at` updates after the meeting.

---

## 8. Phase 6 — Make the learning felt (1–2 days)

The θ table moves invisibly. Trust comes from seeing it.

- **6.1 Weekly digest.** Celery job Sunday ~7 PM ET: diff `attention_policy` θ vs a weekly
  snapshot (new tiny table `attention_policy_snapshot`: cell + θ + captured_at, written by
  the same job), plus 7-day promotion/engagement stats and behavioral_pattern
  accepts/rejects → one LLM-crafted first-person note ("I've backed off HRV dips — you
  never open them. I'm watching your commit pace more since the branch started.") →
  journal entry + normal-priority notification (inbox, per the attention-queue routing).
  `enable_thinking: False` on the craft call.
- **6.2 Correction affordance.** Digest inbox item carries per-line "keep telling me" /
  "good call" quick actions → inverse/confirming θ nudge via
  `attention_learning.apply_engagement`. A correction is the highest-quality label the
  learner will ever get.
- **6.3 God view sparkline.** θ history per cell from the snapshot table.
- **Accept:** first digest delivered Sunday; a "keep telling me" measurably lowers that
  cell's θ by the next snapshot.

---

## 9. Phase 7 — iOS presence on metal (device-gated) — WHAT I NEED FROM DAVID

Everything below is built and EAS-signed (2026-05-30); none of it has ever run on a
physical device. This is the only phase I cannot execute or verify from here.

**The ask, in order (~30 min of your time total):**

1. **Install the app on your iPhone** — either the existing signed build or, better, a
   fresh one after Phase 5.2's calendar-attendee change lands:
   `cd ios-app && eas build --platform ios --profile preview` and install via the QR/link
   (or TestFlight if that's the pipeline). If EAS prompts about the **App Group capability
   for `cloud.avery.sara-ios.widget`, accept it** — it's the most common first-build snag
   (`NATIVE_FEATURES.md`).
2. **Run the 4-check verification pass** and tell me pass/fail per item (screenshots of
   anything broken):
   - **Siri:** Settings → Siri & Search → "Ask Sara" appears; saying "Ask Sara…" opens the
     app and auto-sends the question into chat.
   - **Widgets:** long-press home screen → add the "Sara" widget (small/medium), and a
     lock-screen accessory widget; both show emotional-state + next event; foregrounding
     the app refreshes them.
   - **Live Activity:** start a timer in the app → lock-screen banner + Dynamic Island
     countdown ticks on its own; stopping the timer ends it.
   - **Push:** trigger a high-priority notification (I can fire one from the backend on
     request) → it lands as a real push with the app backgrounded.
3. **After the attendee-sync build:** open the app once so calendar re-syncs, then I verify
   attendees landed server-side — you don't need to do anything else.
4. **Only if something fails:** the failure modes are pre-mapped (App Intents landing in
   the wrong Xcode target, App Group not registered on both App IDs, `#available` guards in
   the widget Swift) — I fix config/code from here, you rebuild + reinstall. Worst case I
   may ask you for the EAS build log URL.

Also 2 minutes on any machine: open `https://sara.avery.cloud`, tap the mic button, say
something — confirms web voice in a secure context (LAN HTTP can't access the mic; already
handled gracefully).

---

## 10. Phase 8 — Cut the sprawl (2–3 days) — no longer deferred

24 web views dilute the flagship. Concrete default proposal (approve or amend, then it
ships — the point of "no deferrals" is a real default, not another open question):

- **Primary nav (6):** Home (dashboard), Chat, Today (inbox), Knowledge (notes + PKG +
  people), Fitness, The System (god view — flagship surface, per activation plan E4).
- **"More" drawer (grouped, one tap deeper):** Calendar, Email, Documents, Tasks, Projects,
  Recipes, Learn, Briefings, Canvas, Agent Tasks/Automations.
- **"Advanced" (collapsed section inside More):** ACS introspection, Sensory Monitor,
  Orchestrator Lab, System Status, Privacy.
- Settings stays as a gear icon, login stays unrouted. Command palette keeps *everything*
  reachable by keyboard, so demotion costs power users nothing.
- **iOS mirror:** same 6 as tabs (or 5 + More), remaining screens under More. Ships with
  the Phase 7 build so one install covers both.
- **Accept:** primary nav ≤ 6 on both platforms; no view deleted, only demoted; palette
  still reaches all.

---

## 11. Data / wiring changes (concrete)

| Change | File(s) | Type |
|---|---|---|
| Commit branch, gitignore pycache, test deps | repo root, requirements | ops |
| Deploy goals daemon → sara VM, restart unit | `/opt/acs-daemon` (10.185.1.176) | deploy |
| Comms gatherers (3 signals) | `services/subconscious.py` | logic |
| `comms` domain in priors + `_CAT_DOMAIN` + relevance | `attention_learning.py`, `subconscious.py` | wire |
| `person` table | alembic 077 | new revision |
| Email → person upsert | `tasks/email_sync.py` | wire |
| Chat mentions → person bump | `services/pkg_extractor.py` | wire |
| People gatherers (3 signals, per-person cadence via `signal_baseline`) | `services/subconscious.py` | logic |
| Commitment extraction | `services/thread_extractor.py` prompt + write path | logic |
| `manage_goal` chat tool | `app/tools/` + registry | new tool |
| Goal/commitment gatherers | `services/subconscious.py` | logic |
| `email_draft` / `meeting_prep` / `commitment_nudge` categories | `deliberation_prompt.py`, `deliberation_gate.py` | logic |
| `action_ledger` table + undo generalization | alembic 078, gate + standing-order service | new revision + wire |
| `calendar_event.attendees` + organizer | alembic 079, `routes/calendar_events.py` | new revision |
| iOS attendee sync | ios-app calendar sync service | ios |
| Attendees → person linkage + prep enrichment | `calendar_prep.py`, person service | wire |
| Weekly digest + `attention_policy_snapshot` + correction actions | new task + alembic 080 + inbox actions | new |
| God view: people/actions/θ-history panels | `SystemDashboard.tsx`, `system_awareness.py` | ui |
| Nav collapse (6 primary + More/Advanced) | `navigation/views.ts`, App shell, ios-app nav | ui |

**No backfill anywhere.** All capture is going-forward.

---

## 12. Sequencing & effort

```
P0 commit/deploy (½d)
 ├─► P1 comms (1–2d) ──► P2 people (3–5d) ──► P5 calendar+attendees (2–3d)
 ├─► P3 goals/commitments (3–4d)            (P5 needs P2's person table)
 ├─► P4 act-loop (3–5d)   (4.1 meeting_prep lands fully once P5 exists)
 ├─► P6 learning-felt (1–2d, anytime after a week of P1–P3 data)
 └─► P8 sprawl cut (2–3d, independent)
P7 iOS device pass: David, ~30 min, ideally once after P5.2 + P8's iOS nav land
   (one build/install covers attendees + nav + the 4-check verification).
```

Roughly **3 working weeks** of focused effort end-to-end; P1+P3 alone (≈1 week) already
transform what the balance meter — and Sara — can see.

**Risks:** person dedup/normalization is the only genuinely fiddly logic (alias map, bulk-
sender filtering) — start conservative, prefer missed merges over wrong merges;
`email_draft` must be provably send-proof (no Graph send scope in the draft path);
watch the attention inbox volume as three new domains start promoting — θ priors for new
domains should start *high* (quiet) and earn their way down, matching the design's
"quiet unless earned."

---

## 13. Success criteria (measurable)

- **Life, not just body:** balance meter shows comms/people/goals all non-zero and no
  domain >50%; `person` table grows organically; ≥5 live goals; commitments surface on
  time and resolve.
- **Hands, not just alerts:** ≥1 useful email draft per week accepted; meeting preps
  reference real relationship history; every autonomous action in the ledger, undo works.
- **Learning felt:** weekly digest ships; a correction moves θ within one snapshot cycle.
- **Present:** all 4 iOS checks pass on a physical device; web voice round-trips on HTTPS;
  primary nav ≤ 6.
- **Durable:** branch committed, tests in requirements, daemon at deployed parity with repo.

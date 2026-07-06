# Sara Unleashed — the bulletproof plan

**Grounded in:** live DB reads + end-to-end code-path traces on **2026-07-06** (branch `assistant-experience-jarvis`).
**Companion docs:** `PHENOMENAL_ASSISTANT_PLAN.md` (phases 0–8 committed), `THE_SYSTEM_DESIGN.md`, `ASSISTANT_EXPERIENCE_PLAN.md`, `CODE_MODE_DESIGN.md`.
**Method:** every fix carries a **root cause with a receipt** (file:line or SQL result), the **exact change**, an **acceptance test**, and a **rollback**. Every *new capability* builds on infrastructure verified to exist. The behavioral sections (how she notifies, how you respond, how she phrases, where she saves) were traced through the actual runtime paths, not the design docs. Nothing here is speculative.

**Shape of the plan:** three arcs.
- **RESTORE** (Parts One–Six): silence the noise, wake the dormant verbs, make learning act, unify the surfaces, fix how she speaks/saves, and tune up the verticals.
- **EVOLVE** (Parts Seven–Eight): new powers — anticipation, full comms lifecycle, calendar agency, ambient voice presence, overnight work products, a deeper model of David — on proven intelligence foundations.
- **TRANSCEND** (Part Nine): Sara maintains and improves *herself* — scorecard-driven self-evolution through her own coding agent, with David as reviewer.

---

## 0. The one-paragraph thesis

The machinery is built and running: tier-0 promotes with real domain balance (health 49 / comms 38 / people 30 / goals 22 / work 21 promotions in the last 24h — no domain over 50%), the gate executes, the digest shipped Sunday at 7 PM ET on the dot, the pattern learner holds 45 patterns, her coding agent has credentials, food logging hums (306 rows, current through today). What's broken is **the last inch**: Sara's voice is 86% empty check-ins from a template loop that bypasses her own attention learning, her deliberation brain has proposed **zero actions in 36 hours** while 31 important emails sit unhandled in its own context window, her single most Jarvis-like feature — commitment tracking — is an orphaned function that **nothing calls**, her notifications speak in three different registers (Sara-voice, raw system alert, and leaked agent monologue), and her finished work products strand themselves on a VM filesystem David never sees. This plan fixes the last inch, then raises the ceiling, then hands her the keys to her own improvement. The best possible assistant is defined by precision, not presence — and then by compounding.

---

## 1. Diagnosis — the receipts

### The cognitive layer

| # | Finding | Receipt |
|---|---------|---------|
| R1 | 120 of 140 notifications last 7d are category `checkin`; **all** notifications are priority `high` | `notification_log` query 2026-07-06 |
| R2 | Check-in priority is force-floored to `high` to defeat the attention queue | `proactive_checkins.py:95` |
| R3 | 106 of 115 weekly check-in attempts are dedup-blocked churn; 36% of the all-time attention inbox (205/574) is check-ins | `notification_log.sent=false`, `autonomy_attention_item` counts |
| R4 | Commitment extraction is **orphaned code** — `_extract_conversation_threads` is defined and never called by anything | `main_simple.py:8124`; repo-wide grep = 1 hit (the definition); `followup_thread` has **0** `source='commitment'` rows ever |
| R5 | Deliberation runs ~hourly but proposed **0 tasks, 0 notifications** across every sampled run in 36h, despite 31 unhandled important emails in its own prompt | `agent_run_log.actions_taken` samples; `email` count query |
| R6 | `email_draft` is fully implemented and send-proof but has **never fired** — it depends entirely on a timid LLM volunteering the category | handler `deliberation_gate.py:680`; 0 `action_ledger` rows of type `email_draft` |
| R7 | Deliberation prompt actively teaches passivity: "Empty array [] … MOST COMMON case", "doing nothing is usually the right call" — fed to a 27B local model at 1500 max tokens | `deliberation_prompt.py:333,344,388` |
| R8 | All background cognition (deliberation, digest, extraction, drafts, notification phrasing) runs on `qwen3.6-27b`; only chat gets `claude-sonnet-5` | `app_settings` rows |
| R9 | `person` table: **4 rows** after a week, all `email_in`; no outbound capture; chat-mention bump only fires at 2×-daily consolidation | `person` query; `pkg_extractor.py:109` call graph |
| R10 | Goals: **1 row**, stalled since 2026-06-13; `goals.stalled` promotes (22/24h) but nothing downstream acts | `sara_goal` query |
| R11 | Weekly digest **narrates** restraint ("I should hold back on low-priority pings") but no code path enacts it | digest message in `notification_log`, 2026-07-05 |

### The delivery, phrasing, and response layer (traced end-to-end)

| # | Finding | Receipt |
|---|---------|---------|
| R12 | Four notification surfaces coexist: `autonomy_attention_item` (574), `jarvis_inbox` (111), `sara_inbox` (18), `notification_log` (delivery log doubling as inbox) | `\dt` + counts |
| R13 | **Five stacked suppression/learning layers** sit on one send path — inline engagement-priority-adjuster (`unified_notification.py:300`), `notification_tuner` suppress/double-cooldown (`:322`), ban check (`:334`), attention-queue category cooldown (`:877`), and `_check_dedup`'s hand-tuned `category_limits` dict (`:1144`) — each with separate thresholds and state; **none** share state with the `attention_policy` θ system. The priority-adjuster only demotes `normal/low` — everything arrives `high` (R1), so it is dead code in practice | full trace of `send_notification` → `route_through_attention_queue` |
| R14 | **Phrasing depends on which subsystem is talking.** The Sara-voice LLM composer (`notification_composer.py` — good rules: warm, 1 sentence, no ALL-CAPS) is used by exactly **one** caller (`reactive_engine`). Deliberation phrases its own. Check-ins are hardcoded templates ("How's the afternoon going?"). Email alerts are raw system-style: "New Internal Email / From: Dave Brink / RE: Signed Ops Doc" | grep: composer imported once; `notification_log` samples |
| R15 | **Task notifications leak raw agent monologue.** Pushed verbatim: "Now I have enough research to build the comprehensive document. Let me create it:" — chain-of-thought as notification body. The deliverables themselves landed at `~/sandbox/*.md` **on the VM**, invisible to every Sara surface | `notification_log` rows, 2026-07 "Done: Research…" |
| R16 | **Response affordances have good bones but a broken loop.** Attention items carry per-category quick actions (reply/snooze/mark-done/open — `unified_notification.py:1030`); a reply seeds a *fresh* chat turn with the item text but nothing marks the item engaged or feeds θ; there is no standard "stop these" action anywhere — the single highest-value learning signal has no button | `_default_attention_actions` + `routes/autonomy_attention.py` trace |
| R17 | Saving is inconsistent by artifact type: chat → episodes (6,963), food → `food_log` + episodes (clean), agent work products → VM filesystem (R15), research → notes *sometimes*, drafts → notification body only — no `artifact_ref` linking an inbox item to the thing it announces | `episode` source counts; delivery trace |

### The verticals

| # | Finding | Receipt |
|---|---------|---------|
| R18 | **Habits is a corpse:** 6 tables (`habits`, `habit_logs`, `habit_instances`, `habit_items`, `habit_links`, `habit_streaks`), **zero rows ever**, plus 5 UI components (HabitToday/HabitStreak/…) and 2 docs — a fully-built, never-used vertical | table counts; `components/` ls |
| R19 | **Fitness planning is severed from fitness logging:** 66 `workout_log` sets in 30 days (healthy) but **0** `workout_session` rows in 30 days — `plan_importer` materializes no sessions (`gotcha_fitness_schedule_vs_session`), so "today's planned workout" context is empty for prep, brief, and Workout Mode; plus a dead empty twin table `workout_sessions` | DB counts |
| R20 | **Nutrition is a working sense with no closure loop:** 306 `food_log` rows through today, FatSecret lookup, logs become episodes — but no day-end reconciliation vs plan anywhere (correctly not a *nag*, per the health ban, but absent even from the morning brief and on-request summaries) | DB + `tools/fitness/` trace |
| R21 | **Three dead daily-brief tables** (`daily_briefing` 0 rows, `daily_briefings` latest 2025-11, `daily_briefs` latest 2025-10) shadow the live morning-brief Celery task — same fragmentation pattern as the inboxes | DB counts; `celery_app.py:65` |
| R22 | Timers buzz but aren't wanted (`timer_complete` engagement 1/10); reminders barely used (3 in 14 days) — both deliver at fixed priority instead of riding the learned buzz decision | `notification_log` engagement query |
| R27 | **Recipes save without nutrition:** the two most recent saves have NULL macros or flat 0.00 across calories/protein/carbs/fats ("Chicken Bacon Ranch Macaroni Salad", 2026-07-04). `recipes_create` accepts `calories` as *optional* and nothing computes nutrition from the structured ingredients — even though FatSecret lookup + `food_database` cache exist two tools away | `recipe` table query; `tools/recipes.py:204` |
| R28 | **Workout logging has no exercise identity:** `workout_log.exercise_id` holds free-text *names* ("Flat DB Bench", "Barbell or Machine Chest Press", "Vertical Pull" — a movement pattern, not an exercise); `exercise_library` has **0 rows**. No canonical entity → no variant history ("what did I bench with last time — iso, dumbbell, barbell?"), no dropdown, and history for one movement scatters across spelling variants | DB queries; `exercise_library` count = 0 |
| R29 | **Location: healthy sense, zero hands.** iOS location ingestion works (90 `location_event` rows, `/api/location/report` 200s and an "enter 'Home'" transition detected *today*), and six location tools exist (`places_save/list/delete`, `location_reminder_create/list/cancel`) — but they belong to **no category** in `TOOL_CATEGORIES` and no LOCATION intent exists in `INTENT_TO_TOOL_CATEGORIES`, so chat can *never* load them. Sara truthfully reports "I don't have tools to save locations" / fails as "can't connect" while the data flows underneath her | registry trace: tools instantiated `registry.py:415-421`, present in zero category lists; `intent_classifier.py:551` has no LOCATION entry; backend logs 2026-07-06 |

### Infrastructure verified alive (build on it)

| # | Finding | Receipt |
|---|---------|---------|
| R23 | **No email-send capability exists anywhere** — drafts are provably send-proof today; "approved send" is a genuinely new, consent-gated power | repo-wide grep for `sendMail`/`send_mail` = 0 hits |
| R24 | Code Mode is operational: backend done, `GITHUB_PAT` present, coding agent on the sara VM | `.env:70`; `CODE_MODE_DESIGN.md` |
| R25 | The pattern learner is alive (45 `behavioral_pattern` rows, 38 active) and standing orders support pattern promotion — an anticipation substrate exists | DB; `standing_order_service.py` |
| R26 | Working, keep-and-build-on: domain-balanced promotion, gate hard-bans, action ledger + undo, digest cadence, attendee→person linkage (`calendar_events.py:423`), god-view People/Actions panels, θ snapshots (112 rows), travel-nudge + predictive Celery tasks, GTKY/model-of-you/emotional-state services, HITL reply path (inbox reply → Redis → unblocks a waiting ACS session), `main_simple.py` at 10,670 lines with a 6-deep regex interceptor stack (`:8265–8508`), `sara/sara123` creds in the repo behind a public domain, iOS never run on metal | verified live |

**The pattern:** every gap is the *last inch* between built machinery and felt behavior — and above the gaps, a low ceiling set by model timidity, read-only reach, reactive-only posture, and a voice that doesn't consistently sound like her.

---

## 2. Operating invariants (binding for every phase, old and new)

1. **One proactivity brain.** Anything that speaks to David unprompted routes through deliberation → gate → attention learning. No side channels, no template loops, no priority flooring.
2. **Priority is information.** `high` means "buzz the phone now." If a caller inflates priority to defeat routing, the fix is the routing, never the caller. CI enforces the distribution (§20).
3. **Deterministic where judgment isn't needed.** An unanswered important email older than N hours *always* gets a draft. LLM judgment decides *content and tone*, never *whether the obviously-useful thing happens*.
4. **Learning must close its own loop.** Any surface that says "I learned X" must be generated *from* an applied change, not from an aspiration.
5. **Every unprompted utterance carries a payload** — a name, a subject, an event, a number. "How's the afternoon going?" is banned output.
6. **One voice.** Everything David reads or hears from Sara passes one phrasing stage with one style contract (§10). No template register, no system-alert register, no leaked agent monologue. Ever.
7. **Every artifact has an address.** Anything Sara produces (draft, brief, research doc, prep note) is saved to a David-visible store (note/document/inbox payload) and linked from the item that announces it. Nothing lives only in a push body or on a VM path.
8. **Every proactive item answers in one tap.** Minimum affordance triad on proactive items: **do it / not now / stop these** — and "stop these" is the strongest learning signal in the system.
9. **No new code in `main_simple.py`.** New endpoints → `routes/`, new chat behavior → the command router (§15). CI ratchet: the file may only shrink.
10. **Reversible autonomy stands** (ledger + undo + send-proof drafts) and extends to every new verb. New *irreversible* powers (approved-send) require explicit per-action consent, forever.
11. **Consent tiers are explicit and immutable in code:** `autonomous` (reversible, ledgered) → `propose-first` (one-tap approve) → `never` (send without approval, purchases, external messages). A capability moves tiers only by David editing the tier table himself.
12. Existing feedback rules remain law: ET everywhere (`feedback_no_utc`), `enable_thinking: False` for short outputs, anti-nag caps, health-topic notification ban, no Expo, no ActivityPub.

---

# ARC ONE — RESTORE

## PART ONE — STOP THE SELF-HARM

## 3. Phase A — One voice: fold check-ins into the deliberation brain (1–2 days)

**Root cause (R1–R3):** `proactive_checkins.run_checkin_sweep` fires every ~15 min, generates template pings ("How's the afternoon going?"), and floors priority to `high` (`proactive_checkins.py:95`) specifically to defeat `route_through_attention_queue`'s silencing of normal-priority items. Two proactivity systems are fighting; the dumb one is winning.

- **A.1 Delete the ambient/template paths.** Remove branch 3 (`_ambient_line`) and branch 2 (`checkin_builder` templates) from `run_checkin_sweep`. Keep branch 1 (ripe-thread follow-ups: post-meeting recaps + commitments) — payload-carrying, rides the anti-nag caps. Rename to `run_followup_sweep`.
- **A.2 Give deliberation the check-in verb instead.** `deliberation_prompt.py` gains a `checkin` rule: at most once/day, only when it can cite ≥1 concrete observation from working memory (named in the message), only in `available` context.
- **A.3 Remove the priority floor; fix the routing instead.** Delete `proactive_checkins.py:95-96`. In `route_through_attention_queue` (`unified_notification.py:835`), replace the blanket "normal → silent inbox" rule with a **learned buzz decision**: push a normal-priority item iff its category's trailing-30-day engagement ≥ 40% *and* interruptibility ≥ 0.5; otherwise inbox-only. The attention queue becomes the *single* place "does this buzz?" is decided — and it learns. (§10.3 then collapses the other four suppression layers into this one.)
- **A.4 Stop logging blocked attempts as notifications.** Dedup-blocked sends (106/wk) increment a counter on the existing row instead of inserting churn rows.
- **A.5 Payload lint.** Gate rejects any proposed notification whose message contains no entity from working memory (no name/subject/event/number overlap → block, reason `no_payload`).
- **Accept:** 7 days post-deploy: check-ins ≤ 7/week (vs 120), every one payload-carrying; checkin engagement > 50%; zero dedup-churn rows; `normal` priority exists again in the log.
- **Rollback:** tunable `checkins.template_fallback`, default OFF.

## PART TWO — WAKE THE DORMANT VERBS

## 4. Phase B — Resurrect commitments (½ day) — highest Jarvis-per-hour in the codebase

**Root cause (R4):** the entire extraction path (`thread_extractor.extract_threads` — prompt, parsing, `source='commitment'`, due-date-anchored windows) is finished and correct. Its only caller, `_extract_conversation_threads` (`main_simple.py:8124`), is **never invoked**.

- **B.1 Wire the call.** At end-of-stream in `/chat/stream`, fire `asyncio.ensure_future(extract_from_conversation_bg(messages, user_id))` when the conversation has ≥3 user messages. The extractor already rate-limits (`EXTRACTION_COOLDOWN`) and dedups against open threads.
- **B.2 Move it out of the monolith** while touching it: relocate into `thread_extractor.py`, replace the hand-rolled `_SyncAsAsyncDB` wrapper with the real `get_async_session_factory()` — the wrapper's fake `commit()` is a latent bug.
- **B.3 Resolution capture.** `resolve_threads_from_conversation` is dead for the same reason — B.1 revives it. Verify "done / not doing it" writes `david_response`, feeding the pattern learner.
- **B.4 Surfacing already works** — Phase A's `run_followup_sweep` delivers ripe threads through the anti-nag caps.
- **Accept:** "I'll call the plumber Thursday" in chat → `source='commitment'` row with a Thursday-anchored window within a minute; surfaces Thursday, ≤ `max_mentions=3`; "already did it" closes it.
- **Rollback:** remove the one call site.

## 5. Phase C — Deliberation grows a spine (2–3 days)

**Root cause (R5–R8):** the act loop's bottleneck is *judgment starvation*. A 27B model, taught "doing nothing is usually the right call," converges on literally-always-nothing — 0 proposals across 36h while its own prompt listed 31 unhandled important emails. `email_draft` (`deliberation_gate.py:680`) is complete and send-proof — and waits forever on a proposal that never comes.

- **C.1 Deterministic triggers for deterministic value.** New Celery task `assistant_verbs_sweep` (every 30 min, waking hours):
  - **Email drafts:** any `is_read=false AND (action_required OR importance_score≥0.7)` email older than **4h** → call `_generate_email_draft` directly (already ledger-deduped). Cap 3/day, oldest first.
  - **Meeting prep:** any meeting starting in 30–60 min with ≥1 attendee → `calendar_prep` + person history. Ledgered.
  - **Commitment nudges:** ripe `source='commitment'` threads → `_nudge_commitment` (already written, `deliberation_gate.py:751`).
- **C.2 Rebalance the deliberation prompt.** Replace the passivity mantra: "Most cycles produce 0–1 actions. A cycle where working memory shows an unhandled important email, a stalled goal, or a due commitment and you propose nothing is a **failure**, not restraint." Add two few-shot exemplars (one act, one hold).
- **C.3 Tier the brain.** Keep hourly deliberation on qwen. Add **two "deep deliberation" runs/day** (post-consolidation, 2 PM / 9 PM ET) on `claude-sonnet-5` (no `temperature` — `gotcha_claude_model_sampling_params`). Deep runs see 50 observations (vs 15), may propose up to 4 tasks. ~2 Sonnet calls/day.
- **C.4 Structured output.** Constrained JSON (vLLM `guided_json` / Sonnet tool-forcing); delete the three-stage brace-hunting fallback in `deliberation._parse_response`. A parse failure today silently burns a whole cognitive cycle.
- **C.5 Proposal-rate telemetry.** `proposal_rate_7d` (proposals ÷ runs, by category) in `/debug/notification-funnel`. This metric would have caught R5 months ago.
- **Accept:** within 48h — first-ever `email_draft` ledger rows, usable drafts; preps fire; deep deliberations propose ≥1 action on backlog days; proposal rate nonzero and visible.
- **Rollback:** sweep is one beat entry; `deliberation.deep_model` tunable points back to qwen.

## PART THREE — MAKE THE SENSES REAL

## 6. Phase D — People become a real graph (2–3 days)

**Root cause (R9):** inflow is inbound-email-only; chat-mention bumps ride 2×-daily consolidation; `reconnect_overdue` needs cadence baselines that can't form from 4 rows.

- **D.1 One-time 90-day seed (deliberately breaking "no backfill" — and saying so).** One import over the 1,325 existing `email` rows: upsert senders + recipients through `upsert_person_from_email` (bulk-sender filter already written), replaying history into `_bump_cadence` so EWMAs are real. Conservative merges: prefer missed merges over wrong merges.
- **D.2 Outbound capture.** Extend `email_sync` to the Sent folder (Graph `sentitems`); recipients get `last_interaction_kind='email_out'`. Reply latency ("Jim wrote 3 days ago, no reply") is *the* people signal worth having.
- **D.3 Real-time mention bumps.** `pkg_realtime_extractor` runs in the chat path — add the `bump_person_mention` call there (mirroring `pkg_extractor.py:119`).
- **D.4 Surface in chat.** `tools/people.py` exists — verify registry wiring; add intent keywords ("overdue", "haven't talked", "catch up with") so "who am I overdue with?" reliably loads it.
- **D.5 Meetings close the loop.** `link_attendees_to_people` exists (`calendar_events.py:423`); add the post-event bump (`last_interaction_kind='meeting'` when the event ends).
- **Accept:** `person` ≥ 50 rows after seed; `email_out` and `meeting` kinds present within a week; `reconnect_overdue` promotes with a named person; the chat question answers from data.
- **Rollback:** seed rows tagged `source='seed_2026_07'` — one-statement delete.

## 7. Phase E — Goals get inflow and teeth (1 day)

**Root cause (R10):** `manage_goal` tool exists; nothing invites its use, and stall promotions reach a brain that never acts (fixed by C).

- **E.1 Goal capture in consolidation.** Add goal detection to the 2×-daily consolidation ("David repeatedly discussed X as an aim") that *proposes* a goal to the inbox (one-tap accept → `sara_goal` row). Proposed, not auto-created: goals are identity-level.
- **E.2 Stalled-goal payload.** When `goals.stalled` promotes, working memory carries the goal title + days stalled + last progress note, so deliberation can say something specific or dispatch a task against it.
- **E.3 Progress from evidence.** When a conversation, commitment resolution, or dispatched task references an open goal (embedding similarity vs title/plan), append to `progress` jsonb with source. "Document my agentic architecture" has silently stall-promoted for 23 days — after this, it surfaces meaningfully or gets closed.
- **Accept:** ≥5 live goals in two weeks via accepted proposals; a stalled goal produces one concrete suggestion, not a bare count.

## PART FOUR — LEARNING THAT ACTS

## 8. Phase F — The digest enacts, then narrates (1–2 days)

**Root cause (R11):** θ moves from notification engagement, but the digest's conclusions are post-hoc prose — no policy object changes because the digest ran.

- **F.1 Digest = diff of applied changes.** Sunday job restructure: **first** compute and *apply* adjustments (θ nudges from 7-day engagement, cadence caps, category demotions), each written to new `policy_change_log` (change, evidence, before → after, reversible flag); **then** generate the narrative *from the log*. Every sentence backed by an applied row.
- **F.2 Corrections get teeth.** "Keep telling me" / "good call" actions write through `apply_engagement` at 3× weight *and* revert the specific `policy_change_log` row when contradicted. A correction is the highest-quality label she'll ever get; it must be the strongest force in the system.
- **F.3 Self-honesty check.** If last week's stated adjustment didn't manifest (said "hold back," count rose), the digest says so and names the enforcement added. One line, once a week, only when a stated adjustment demonstrably didn't hold.
- **Accept:** next digest lists ≥1 applied change with before/after θ; a correction visibly reverts it by the following snapshot; zero unbacked sentences.

## PART FIVE — ONE SURFACE

## 9. Phase G — Inbox unification (2 days)

**Root cause (R12):** three item stores + a delivery log doubling as a fourth surface.

- **G.1 `autonomy_attention_item` becomes *the* inbox.** Migrate `jarvis_inbox` (111) and `sara_inbox` (18) rows in with `legacy_source`; freeze writes to the old tables; repoint readers at `/api/assistant-inbox/unified` + `compute_badge` (both exist — finish the consolidation they started).
- **G.2 `notification_log` returns to being a ledger** — deliveries and engagement only, never an inbox.
- **G.3 One badge everywhere.** Web "Today", iOS inbox, desktop all read the unified endpoint. Delete per-surface badge math.
- **G.4 Hygiene:** auto-archive items > 30 days; regression test for the recycle-dedup fix (`gotcha_attention_queue_recycle_cooldown`).
- **Accept:** zero writers to legacy tables; identical lists and badges on every surface.

## PART SIX — THE FELT LAYER: how she speaks, how you answer, where things live

## 10. Phase T — One voice, one response loop, one save path (2–3 days)

This is the phase the end-to-end traces demanded. Sara currently speaks in three registers (R14), leaks agent internals (R15), runs five uncoordinated suppression layers (R13), offers reply buttons that don't teach her anything (R16), and strands her own work products (R17). Each fix below is small; together they change what *every single interaction* feels like.

- **T.1 The phrasing stage — everything sounds like Sara.** `notification_composer` already has the right style contract (warm, ≤1 sentence, key fact included, no ALL-CAPS — `notification_composer.py:20`) and exactly one caller. Make it the mandatory final stage in `send_notification` for every category except raw timer/reminder fires: templates die, email alerts become *"Dave Brink replied on the Operating Agreement — he wants your call on the legal comments"* instead of *"New Internal Email / From: Dave Brink"*, and deliberation proposals get a light Sara-voice pass (they're already LLM-phrased; the stage mostly enforces brevity + payload). Composer keeps its hardcoded fallback so nothing ever fails silent. One style contract, one place to tune it.
- **T.2 Kill the monologue leaks.** `task_result_delivery` may never push raw agent output. Every completed dispatch gets a summarize pass (one local-LLM call): *what was produced, where it now lives, the one next action* — and the deliverable itself is **imported** (VM sandbox files → `documents`/notes via the existing upload path) before the notification is composed. The notification links the artifact (`artifact_ref`, see T.5). "Let me create it:" never reaches a lock screen again.
- **T.3 Five suppression layers become two.** Collapse R13's patchwork into: **(1) the gate** — hard bans + consent tiers + payload lint, and **(2) the learned attention layer** — θ + A.3's engagement buzz decision. Concretely: delete the inline priority-adjuster (dead code anyway), retire `notification_tuner` (its suppress/double-cooldown behavior is θ's job), and convert `_check_dedup`'s hand-tuned `category_limits` dict into seed values for θ priors + per-category caps stored in `attention_policy` — one learning brain, one state, one debug view. The exact-topic dedup window stays (it's correctness, not learning).
- **T.4 The response loop teaches her.** Three changes to the quick-action layer (`_default_attention_actions`, `unified_notification.py:1030`):
  1. **The triad everywhere:** every proactive item carries **Do it / Not now / Stop these**. "Stop these" applies a strong negative θ nudge to that (category, context) cell via `apply_engagement` and confirms in one line ("Got it — fewer of these."). It is the F.2 correction affordance available *at the moment of annoyance*, not just in the Sunday digest.
  2. **Replies close the loop:** the reply action seeds chat with the item id in metadata; the chat turn marks the item `engaged` automatically (today `mark_engaged` exists but nothing calls it on reply), and Sara's reply context includes the original item so the conversation continues rather than restarts.
  3. **Snooze that means snooze:** "Not now" re-surfaces the *same item* at the next context change (state machine transition), not a duplicate item — riding the existing recycle-cooldown fix.
- **T.5 Every artifact has an address (invariant 7, mechanized).** Add `artifact_ref` (type + id + url) to `autonomy_attention_item.payload` and `notification_log`. Producers comply: drafts → the draft body stored as a `document` (not just notification text) so Edit-and-send (M.3) has something to edit; research → note/document import (T.2); preps → note attached to the calendar event; briefs → the morning-brief record. The inbox item's primary tap opens the artifact. Audit: a nightly query counts announce-without-artifact items — target zero.
- **Accept:** zero template-register or system-register pushes in a week of logs (spot-check: every message names its payload in Sara's voice); zero agent-monologue leaks; "stop these" measurably moves θ within one snapshot; a dispatched research task ends as an openable note linked from its inbox item; suppression decisions all trace to gate-or-θ (funnel debug shows exactly two decision layers).
- **Rollback:** phrasing stage and layer-collapse both behind tunables (`notify.compose_all`, `notify.legacy_limits`); T.4/T.5 are additive schema.

## 11. Phase U — Vertical tune-up: fitness, nutrition, recipes, habits, briefs, timers, location (3–5 days)

The verticals audit (R18–R22, R27–R29). Rule of thumb applied throughout: **every vertical either has a live loop (sense → store → surface → response) or it gets folded into one that does.**

- **U.1 Fitness: reconnect planning to logging (R19).** Fix `plan_importer` to materialize `workout_session` rows from the imported plan (the long-standing gotcha — sessions are the missing join between "training day" and "what workout"); wire "today's session" into the morning brief, Workout Mode preload, and the L.1 day model. Drop the dead `workout_sessions` twin table and the dead `exercise_history` table (`gotcha_progression_single_brain`). Progression stays single-brain in `progressive_overload.py`; recovery keeps gating in-session suggestions. **Accept:** the morning brief names today's planned session; starting Workout Mode preloads it; duplicate tables gone.
- **U.2 Nutrition: add the closure loop, respect the ban (R20).** Food logging works — leave the capture path alone. Add: (a) a day-end reconciliation record (macros vs plan, written silently to `food_log` summary + episode); (b) a one-line morning-brief item phrased as trajectory, not judgment ("protein landed 3 of the last 4 days"); (c) on-request summaries in chat ("how'd I eat this week") from the same record. Zero proactive nudges — the health notification ban stands untouched; this is *reporting where David already looks*, not pinging.
- **U.3 Habits: fold, don't revive (R18).** The modern machinery (commitments + standing orders + patterns) already models what habits promised: a habit is a recurring commitment with a streak. Migrate nothing (there are zero rows); **delete** the 6 tables, the 5 UI components, and the nav/palette entries; add a `recurrence` option to commitment threads (weekly/daily windows with streak counting in thread metadata) so "I want to stretch every morning" lands in the machinery that actually runs. If a dedicated habit view is ever wanted, it's a *view over recurring commitments*, not a second behavior system.
- **U.4 Briefs: one artifact, richer every arc (R21).** Drop the three dead brief tables. The morning brief is the single daily artifact and the natural home for everything this plan produces: today's shape (L.1), planned session (U.1), nutrition trajectory (U.2), comms tiers (M.1), "while you slept" (Q.2). Phrased through T.1 like everything else.
- **U.5 Timers and reminders ride the learned layer (R22).** Timer-complete and reminder fires stop hardcoding priority; they go through A.3's buzz decision like everyone else (a 1/10-engagement timer buzz will demote itself to inbox/watch within two weeks — which is what the data says David wants). Reminder quick actions align with the T.4 triad (done / snooze / stop these).
- **U.6 Recipes get their macros (R27).** On every `recipes_create`/update where macros are absent **or all-zero** (0.00 must be treated as missing, not data — see the macaroni-salad row): compute per-serving nutrition from the structured `ingredients` jsonb via the existing FatSecret lookup + `food_database` cache (per-ingredient quantity → macros → sum ÷ servings), store with an `estimated` flag so hand-entered values are never overwritten. Backfill the existing NULL/zero recipes in one pass. Then close the loop nutrition-side: a **"log this recipe"** action (recipe card + chat) writes a `food_log` entry with the per-serving macros — recipes and nutrition become one system instead of neighbors. **Accept:** saving a recipe from chat shows calories/protein/carbs/fats within seconds, marked "estimated"; "I had the unstuffed peppers for dinner" logs correct macros without a FatSecret round-trip.
- **U.7 Workout logging gets exercise identity — variants, history, and a real picker (R28).** The root cause is that exercises have no identity: free-text names in `exercise_id`, an empty `exercise_library`, and movement patterns ("Vertical Pull") mixed with concrete exercises ("Flat DB Bench"). Fix in four layers:
  1. **Seed the library:** populate `exercise_library` from the distinct names already in `workout_log` + the imported plan, each row carrying `canonical_name`, `movement_pattern` (horizontal_press, vertical_pull, hinge, squat, …), `equipment` (barbell/dumbbell/machine/iso/cable), and `aliases` jsonb. Map the existing free-text values onto library rows (conservative matching; unmatched become their own rows).
  2. **History-enriched variant API:** `GET /api/fitness/exercises?movement=horizontal_press` returns every variant David has *ever* logged for that movement, each with last-performed date, last weight × reps, and PR — exactly the "what did I do last time on iso vs dumbbell" question, answered from `workout_log` at read time.
  3. **The picker (iOS Workout Mode):** logging a slot shows a dropdown of that movement's previous variants — *"Flat DB Bench — 80s × 8 (last Tue)"*, *"Iso Bench — 3 plates × 10 (6/28)"* — plus **"Add exercise…"** which creates a new library row inline (name + equipment, movement inherited from the slot). Selecting a variant pre-fills last session's weight/reps as the starting point.
  4. **One brain, per-variant:** `workout_log.exercise_id` becomes an FK to the library (legacy text preserved in a shadow column during migration), and `progressive_overload.py` reads history **per variant** — dumbbell progress no longer pollutes barbell suggestions.
  **Accept:** opening bench in Workout Mode shows every bench variant with its own last-session numbers; picking one pre-fills; a custom "Larsen Press" added mid-workout persists and appears next time; progression suggestions are variant-correct.
- **U.8 Location: give the healthy sense its hands (R29).** The tools exist and the data flows — they've just never been reachable from chat. Three wires:
  1. **Registry:** add a `location` category to `TOOL_CATEGORIES` containing all six tools (`places_save/list/delete`, `location_reminder_create/list/cancel`).
  2. **Intent:** add `LOCATION: ['location', 'time']` to `INTENT_TO_TOOL_CATEGORIES` with classifier keywords ("save this location/place", "remember where", "where am I", "when I get home / when I leave work", "add this as a known place"), and append `location` to the GENERAL fallback list so near-misses still reach the tools.
  3. **Verify end-to-end, both directions:** "save my current location as the gym" → `known_place` row created from the latest `location_event` fix; "remind me to grab the drill when I get home" → `location_reminder` that actually fires on the *next* real "enter Home" transition (the geofence events are already flowing — R29 proved it).
  Also audit the other instantiated-but-uncategorized tools while in there — R29's failure class (built, registered, unreachable) is exactly the R4 orphan pattern one layer up, and it's cheap to sweep the whole registry once. **Accept:** both round-trips above work from chat on the first try; "she says she can't save locations" never happens again; registry sweep finds zero uncategorized tools.
- **Accept (phase-wide):** each vertical passes the loop test — fitness: plan → session → variant-aware log → per-variant progression → brief; nutrition: log → reconcile → brief/on-request; recipes: save → macros → loggable; habits: gone as a system, present as recurring commitments; briefs: one table, one artifact; timers: engagement-routed; location: sense → save → trigger → fire.
- **Rollback:** U.3 deletions and U.7's FK migration land as revertible migrations (U.7 keeps the legacy text column until verified); everything else is additive.

---

# ARC TWO — EVOLVE

## PART SEVEN — NEW POWERS

## 12. Phase L — The anticipation engine: from reactive to predictive (3–4 days)

She has the substrate (R25: 45 behavioral patterns, standing-order promotion, `travel_nudge` + `predictive_engine` wired into Celery, daily-rhythm baselines, off-rhythm flags) — but no unified *forward model of the day*. Everything today reacts to what already happened.

- **L.1 The day simulation.** Morning job (after brief assembly): a **timeline of the next 16 hours** — calendar events with prep-need scores, predicted transitions from `daily_rhythm` (workout window, lunch, wind-down), commitment due-times, travel departures (existing `travel_nudge` logic), recovery-informed energy curve (chat/brief-only per health ban). Persist as `day_model` (one row/day, jsonb timeline). Working memory gets a compact "today's shape" block — deliberation stops rediscovering the day every hour.
- **L.2 Deviation-as-signal.** Tier-0 gains `day.ahead_behind` — is David tracking his predicted day? (meeting overran → next-event risk; workout window passed unworked → silent tone context, never a nag). Off-rhythm flags fuse against the *forward* model instead of only the historical baseline.
- **L.3 Pattern → standing-order pipeline, activated.** 38 active patterns sit unused. Weekly: top-confidence patterns with ≥3 confirmations become **proposed standing orders** in the inbox ("Every weekday ~11:40 you ask about lunch macros — want that surfaced automatically at 11:30?"). One-tap accept → standing order with the existing 5-min undo + ledger. The learn→automate loop the whole architecture points at, currently missing its last edge.
- **L.4 Pre-loaded context.** 10 min before any calendar event, warm the working set: attendee history, related notes/PKG facts, open threads. Chat during or right after the event is *already* in context — no retrieval lag.
- **Accept:** `day_model` exists every morning; ≥1 pattern-promoted standing order accepted in month one; a mid-meeting chat message gets attendee-aware context with zero extra retrieval round-trip.
- **Rollback:** day-model block is one working-memory section behind a tunable.

## 13. Phase M — Comms full lifecycle: read → triage → draft → approved send (3–4 days)

Email today is a *sense* gaining a *draft* verb (C.1). The loop still dead-ends: David must leave Sara to actually act. Close it — with consent architecture, not autonomy creep (R23: no send capability exists anywhere; this is a new power and gets invariant-11 treatment).

- **M.1 Triage tiers.** Nightly + on-sync classification into `respond` / `review` / `fyi` / `noise` using existing `importance_score`/`action_required`/`category` plus person-table VIP flags. The brief's comms section becomes "2 need replies (drafts ready), 3 to review, 14 archived as noise" instead of a count.
- **M.2 Reply-latency awareness.** With D.2's outbound capture: our-turn-vs-their-turn per thread. `comms.awaiting_my_reply` (aged) and `comms.awaiting_their_reply` (chase-worthy) become tier-0 signals — the second is "you never heard back from the adjuster — want a chase draft?", which inbound-only analysis can never produce.
- **M.3 Approved send — the consent-gated graduation.** Add Graph `Mail.Send` scope. A draft inbox item gains **Send / Edit & send / Discard**. Sending requires the explicit tap — every time, forever (invariant 11: lives in `propose-first`, can never move). Sent mail is ledgered (`email_send_approved`, full body snapshot) and writes the person interaction. Guardrails in code: no send without a matching draft artifact (T.5), no recipients outside the original thread unless David edited, hard cap 10/day.
- **M.4 Noise reclamation.** Recurring `noise`-tier senders (3+ unengaged) → weekly one-tap "mute sender" suggestions (person `muted` flag exists). Muted senders skip analysis and signals — the comms sense gets *quieter and sharper* over time.
- **Accept:** brief shows tiered comms; a chase-draft fires for a stale awaiting-their-reply thread; one-tap send round-trips and ledgers; a muted sender never surfaces again.
- **Rollback:** removing the `Mail.Send` scope instantly reverts M.3 to draft-only; tiers are additive metadata.

## 14. Phase N — Calendar agency: Sara defends David's time (2–3 days)

Attendees + organizer landed; ownership reasoning exists (`calendar_ownership.py`). The calendar is still a read-only feed — nothing *guards* the week.

- **N.1 Conflict & squeeze detection.** On every sync: overlaps, back-to-back chains > 3h, meetings colliding with predicted lunch/workout windows (L.1). Issues become inbox items with concrete proposals ("Thursday 1–4 is three back-to-back; the 2:00 with Matthew is yours — move it to Friday 10?").
- **N.2 Focus-block proposals.** When the week fills past a threshold and open goals/commitments have no runway, propose (never auto-create) 90-minute blocks tied to a *specific* goal. One tap → `create_calendar_event` (tool exists). Stalled-goal enforcement (E.2) given hands.
- **N.3 Ownership-aware phrasing everywhere.** Preps and nudges phrase by `organizer==David` vs invited: "your meeting — agenda ready?" vs "you're attending — Mike is organizing."
- **N.4 Post-meeting capture.** `scan_ended_meetings` already opens recap threads — now enriched with attendee links so "what did I promise Jim?" resolves to both the thread and the person.
- **Accept:** a real double-booking produces a movable-event proposal within one sync cycle; one focus block accepted and kept in month one; preps phrase ownership correctly.

## 15. Phase O — Chat pipeline: from regex reflexes to routed intelligence (3–4 days)

**Root cause (R26 tail):** six ordered interceptors decide turns before Sara sees them. Precedence is accidental, collisions are real ("check out github.com/x on gpu-box" matches host *and* web-investigation), and intercepted turns bypass personality, memory write-through, and context entirely.

- **O.1 Single front-door router.** Collapse into `command_router.route(message, ctx)` returning `(handler, confidence)` from an explicit precedence table: slash-commands > active session bindings (code mode) > registered-entity match (hosts) > URL-investigation > UI intent > multi-step > LLM. ~600 lines leave `main_simple.py`.
- **O.2 Ambiguity goes to the model.** Confidence < 0.8 → don't intercept; hand the turn to the LLM with candidate actions available *as tools*. The regex proposes; Sara disposes. Personality stays in the loop exactly on the turns where it matters.
- **O.3 Router test suite:** table-driven tests over ~40 real utterances from episode history asserting the chosen route — collisions become regressions, not surprises.
- **O.4 Extract the chat pipeline.** `SimpleLLMClient` (~1,500 lines) + `chat_stream` → `app/chat/` (the deferred cognitive-overhaul 6A). `main_simple.py` drops below 8,000 lines; the CI ratchet holds it there.

## 16. Phase P — Voice, presence, and continuity (device-gated + 2–3 days software)

Presence multiplies whatever the brain is. Run it after A–C and T so what lands on the lock screen, the speaker, and the wrist is worth the interruption — and sounds like her.

- **P.1 iOS on metal** (the PHENOMENAL Phase 7 checklist, unchanged — David's ~30 min): install the EAS build; verify Siri "Ask Sara", widgets, Live Activity, real push; one HTTPS web-voice round-trip. Failure modes pre-mapped (App Group, target membership, `#available` guards).
- **P.2 Jetson voice hardening.** The pipeline exists (wake word → VAD → STT → backend → TTS, barge-in). Productionize: wake-to-first-audio latency measured and graphed in the god view (target < 2.5s), on-device watchdog verification, and voice-surfaced proactive speech routes through the *same* one-brain gate — the room speaker is a delivery channel of the attention queue, never its own decision-maker.
- **P.3 Cross-device conversation continuity.** `update_active_session` plumbing exists — finish the felt feature: a chat started on desktop resumes on iOS ("continuing from your desk"); a Jetson voice exchange lands in the same conversation stream. One conversation, many mouths.
- **P.4 Delivery routing by device class** (`device_orchestrator` exists): urgent + away → push; at desk → desktop overlay; in the room + idle → voice line. The router learns from *where* engagement happens — same θ machinery, one more dimension.
- **Accept:** 4/4 iOS checks; voice latency graphed; a conversation follows David across three devices; delivery-channel engagement visibly shifts routing within a month.

## 17. Phase Q — Overnight work products & the deep-work partner (2–3 days)

She thinks all night (ACS daemon heartbeating, consolidations, dream service) and produces nothing David wakes up to. The single highest-leverage *new* deliverable: **"While you slept."**

- **Q.1 Nightly work queue.** At wind-down, assemble from live state: stalled goals needing research, unhandled `respond`-tier emails needing drafts, tomorrow's meetings needing deep prep (attendee/company context via the existing research pipeline), open questions David asked and dropped ("I wonder if…" episodes with no follow-up — embedding-retrievable). Dispatch through the existing VM agent overnight, capped (3 jobs/night), every job ledgered.
- **Q.2 The morning deliverable.** The brief gains a "While you slept" section: **finished work products** with one-tap open — drafts staged as documents, briefs as notes, preps attached to events (all via T.5 artifact refs; T.2 guarantees nothing strands on the VM). Not "I noticed things" — *finished work*. This is the difference between an assistant and a monitoring system.
- **Q.3 Research quality tiering.** Overnight synthesis passes get the strong model (2–3 Sonnet calls/night, C.3 plumbing) — depth where nobody's waiting on latency; local models gather.
- **Q.4 Weekly review, drafted.** Sunday evening (after the F digest): a drafted week-in-review note — commitments kept/slipped, goal deltas, people contacted/overdue, next week's shape from the day models — as a *draft note David edits*, not a notification. The review is already written when you sit down to think.
- **Accept:** ≥3 mornings/week with a genuinely useful overnight product (measured: opened/engaged) in month one; the Sunday review draft gets edited (not ignored) at least twice in month one.

## 18. Phase R — The model of David deepens (2 days, then ambient)

`gtky_service`, `model_of_you` routes, `emotional_state`, and the PKG all exist. What's missing is *active* curiosity with consent, and taste.

- **R.1 Curiosity budget.** One genuine, context-anchored question per week max, at a natural moment, through the existing GTKY machinery ("You mention Laura often around work topics — colleague or client? Helps me get preps right."). Answers land as high-confidence PKG facts + person enrichment. Never quiz-like, always skippable, engagement-gated.
- **R.2 Taste profile.** M.3's edit-before-send deltas are a labeled dataset: what David changed = what Sara got wrong. Build a style profile (greetings, brevity, sign-offs, formality per recipient tier) feeding every future draft — and the T.1 phrasing stage. The best drafts come from learning *his* voice, not "concise professional."
- **R.3 Emotional attunement, bounded.** `emotional_state` already modulates chat tone. Extend to proactive *timing*: high-pressure days (calendar density + off-rhythm + comms load — never health-metric inference, per the ban) shift non-urgent surfacing to the evening automatically. The assistant that knows when *not* to talk is the one that gets trusted with talking.
- **R.4 Quarterly narrative.** Every 13 weeks, from consolidated memory: a "season review" note — projects shipped, people patterns, goal arcs, what changed. Long-horizon memory made *felt*, the way the weekly digest made learning felt.
- **Accept:** curiosity questions ≥ 60% answered (else back off automatically); draft-edit distance shrinks month over month; zero non-urgent pings during detected-pressure mornings.

## PART EIGHT — INTELLIGENCE FOUNDATIONS

## 19. Phase I — Memory & retrieval: prove it, then trust it (2–3 days)

8,351 episodes, tiered search, BGE reranker, PKG semantic search — and **no way to know if retrieval is good**. Every intelligence upgrade above is unverifiable without this.

- **I.1 Golden retrieval set.** ~40 real question→expected-episode/fact pairs from actual history. Nightly recall@5 through the full stack, `retrieval_score` time series on the god view. Future memory changes get judged by this number, not vibes.
- **I.2 PKG hygiene.** The June audit's 425k Neo4j `ActionItem` bloat: bulk-archive edge-less nodes untouched 90 days; monthly decay job.
- **I.3 Self-knowledge of actions.** "What did you do today?" answers from `action_ledger` + `agent_run_log` + dispatch logs via a `recall_own_actions` tool — also the natural undo entry point ("undo the porch light thing"). An assistant that acts autonomously but can't recount her actions feels *less* trustworthy than one that never acted.
- **I.4 Context-budget audit.** Log per-section token spend + weekly ablation sampling of the 12 `ContextDecision` injections; kill sections that never influence outputs. Reclaimed budget goes to people/goals/day-model context, which now exists.

## 20. Phase J — Ops, integrity, security (1–2 days)

- **J.1 Funnel integrity tests in CI:** priority distribution sane (`high` < 40% of weekly sends), check-in cap enforced, payload-lint active, dedup churn ≈ 0, proposal rate > 0 over any 7-day backlog window, **zero announce-without-artifact items (T.5), zero template-register pushes (T.1)**. These assertions would have caught R1, R3, R5, R11, R14, R15, and R17 automatically.
- **J.2 Secrets rotation — do this week.** Rotate the `sara` DB password; all creds to `.env` (never CLAUDE.md/compose literals); rotate `acs_daemon_token` + JWT secret; audit that DB/Neo4j/Redis/MinIO ports aren't reachable beyond LAN. M.3's send scope does not land before this does.
- **J.3 Weekly ops scorecard** (extends `/debug/notification-funnel`): sends by category/priority, engagement, proposal rate, verb counts, retrieval score, person growth, goal count, voice latency, overnight-product engagement, artifact-ref coverage, phrasing-register violations. Auto-posted to the god view — the same numbers §22 grades on, so drift is visible the week it starts.

---

# ARC THREE — TRANSCEND

## 21. Phase S — Sara improves Sara (ongoing; 2–3 days to bootstrap)

The compounding move. Code Mode is operational (R24: backend done, `GITHUB_PAT` set, coding agent on the VM). Today it waits for David to type `/code`. Point it at *her own scorecard*.

- **S.1 The self-review loop.** Weekly (after F computes the scorecard): a dedicated deep run on the strong model reviews J.3 metrics against targets and drafts **improvement proposals** — each a concrete, scoped change ("checkin engagement fell to 38%; proposal: raise the buzz threshold for `checkin` to 50% — patch attached"). Proposals land in the inbox with the diff.
- **S.2 David-approved self-patches.** An accepted proposal dispatches to Code Mode on the VM: branch, patch, run the test suite (J.1's funnel-integrity tests are the safety net — *why* they must exist first), open a PR. **David merges; Sara never self-merges.** Guardrails in code: diff ≤ 200 lines, protected paths (auth, consent tiers, gate hard-bans, this guardrail file itself) unpatchable, one open self-PR at a time.
- **S.3 Scope ladder.** Month one: tunables and prompt-text only. Month two, if merge-acceptance > 70%: service-level logic. The ladder is a config table David edits, never Sara (invariant 11 applied to self-modification).
- **S.4 Self-diagnosis on drift.** When a J.3 metric crosses its red line mid-week (proposal rate → 0, engagement collapse, retrieval drop, artifact-ref coverage falling), Sara opens a diagnostic dispatch *automatically* — investigate logs and recent commits, report findings to the inbox ("deliberation proposals stopped after Tuesday's deploy; `_parse_response` throws on the new schema — fix attached"). Detection was this plan's job; after S, it's hers.
- **Accept:** first self-proposed, David-merged patch within three weeks of bootstrap; an injected metric regression (staging) produces a correct self-diagnosis; zero self-modifications outside the ladder, ever, enforced by tests S cannot touch.
- **Rollback:** the whole arc is a Celery beat + a dispatch permission — two switches.

---

## 22. Sequencing

```
Week 1   A (one voice) ── B (commitments, ½d) ── C.1 (deterministic verbs) ── J.2 (secrets)
Week 2   C.2–C.5 (deliberation spine + tiering) ── T.1–T.2 (phrasing + leak-kill) ── D (people)
Week 3   T.3–T.5 (layer collapse, response loop, artifact refs) ── E (goals) ── F (digest enacts)
Week 4   G (inbox unification) ── U (vertical tune-up) ── L (anticipation engine)
Week 5   M (comms lifecycle; M.3 only after J.2) ── N (calendar agency)
Week 6   O (router + extraction) ── I (retrieval proof + hygiene) ── J.1/J.3 (CI + scorecard)
Week 7   Q (overnight products) ── R (model of David) ── P.2–P.4 (voice/continuity)
Week 8+  S (self-evolution bootstrap, after J.1 exists) ── then ongoing
   P.1 (iOS metal pass): David's 30 minutes, any time after Week 3 — ideally Week 4–5
```

Dependencies: A before C.2 (deliberation inherits the check-in verb) · B before C.1 has commitment inventory · T.1 before T.2's summaries and all of M/Q's user-visible output (everything new speaks through the phrasing stage from birth) · T.5 before M.3 (edit-and-send needs the draft artifact) and before Q.2 · D before M.2 (reply latency needs outbound) · L.1 before N.1 (day model feeds squeeze detection) and feeds U.1/U.4 · J.1 strictly before S.2 · J.2 strictly before M.3 · F before S.1.

**Effort honestly stated:** ~8 focused weeks to the full arc. **Week 1 alone (A + B + C.1 ≈ 4 days) delivers the majority of the felt transformation** — the noise stops, commitments live, drafts and preps appear. Weeks 2–3 change what every interaction *feels* like. Everything after raises the ceiling; Arc Three makes it compound.

---

## 23. Success criteria — the scorecard (SQL-checkable, automated by J.3)

**North star: one great moment per day** — an unprompted Sara action David engages with or acts on (draft used, prep read, commitment surfaced on time, overnight product opened, conflict caught before it bit).

| Dimension | Now (2026-07-06) | Target (60 days) |
|---|---|---|
| Check-ins/week (sent) | 120 logged / ~9 pushed, template | ≤ 7, every one payload-carrying |
| Proactive engagement rate | ~33% | ≥ 60% |
| Priority `high` share of sends | 100% | < 40% |
| Template/system-register pushes | the default | 0 (one Sara-voice pipeline) |
| Agent-monologue leaks in notifications | occurring | 0 |
| Announce-without-artifact items | unmeasured (common) | 0 — every product linked and openable |
| Suppression/learning layers on the send path | 5, uncoordinated | 2 (gate + θ), one state |
| "Stop these" corrections available / acted on | no such button | on every proactive item; θ moves within one snapshot |
| Commitments captured/surfaced | 0 ever | ≥ 3/week, 100% in-window, ≤ max_mentions |
| Email drafts / approved sends | 0 ever / capability absent | ≥ 3/wk drafted, ≥ 1/wk used or sent |
| Meeting preps | ad-hoc | 100% of attendee-meetings ≥ 30 min out |
| Deliberation proposal rate | 0 over 36h | > 0 over any 7-day backlog window |
| `person` rows / interaction kinds | 4 / inbound-only | ≥ 50 / in + out + meeting + mention |
| Live goals | 1 (stalled 23d) | ≥ 5, none silently stalled > 7d |
| Planned workout sessions materialized | 0 in 30d (66 sets logged) | every plan day has a session; brief names it |
| Exercise identity / variant history | free-text names, `exercise_library` empty | library seeded; variant dropdown with last-session numbers; per-variant progression |
| Recipes with macros | recent saves NULL/0.00 | 100% (computed-if-absent, `estimated`-flagged); recipes loggable as meals |
| Location tools reachable from chat | 0 of 6 (no category, no intent) | both round-trips work (save place, geofence reminder fires); registry has zero uncategorized tools |
| Nutrition closure | capture only | day-end reconciliation + brief trajectory line |
| Habit system | 6 empty tables + dead UI | deleted; recurring commitments cover the job |
| Dead twin tables (briefs ×3, workout_sessions, exercise_history) | present | dropped in one revertible migration |
| Pattern-promoted standing orders | 0 (38 patterns idle) | ≥ 2 accepted and running |
| Overnight work products engaged | 0 (none produced) | ≥ 3 mornings/week |
| Digest sentences backed by applied changes | 0% | 100% |
| Inbox stores receiving writes | 4 | 1 |
| `main_simple.py` trajectory | growing (10,670) | monotonically shrinking (CI ratchet) |
| Retrieval recall@5 | unmeasured | measured, baselined, trending up |
| Voice wake-to-audio latency | unmeasured | measured, < 2.5s |
| iOS on-metal checks | 0/4 | 4/4 |
| Self-proposed patches merged | 0 (loop doesn't exist) | ≥ 1, zero guardrail violations |

---

## 24. Risks & honest caveats

- **Sonnet cost/dependency (C.3, Q.3, S.1):** bounded (~2 deliberations + ~3 syntheses/day + 1 self-review/week), every call site tunable back to qwen instantly. The deterministic verbs don't depend on it at all.
- **Phrasing-stage latency and drift (T.1):** one extra local-LLM call per notification (rare events; negligible), with the composer's hardcoded fallback so a phrasing failure can never block a security alert. Style drift is caught by J.1's register test (sampled weekly).
- **Layer collapse (T.3) must not widen the funnel:** migrate `category_limits` → θ priors *before* deleting the old checks, with a one-week overlap where both run and divergences are logged. The health-topic ban is a gate concern and is not touched.
- **Approved send (M.3)** is the plan's only irreversible external power. Mitigations are structural: consent tier locked in code, thread-scoped recipients, daily cap, full-body ledger, draft-artifact requirement, J.2 before scope grant. If any discomfort remains, ship M without M.3 — everything else stands alone.
- **Habit deletion (U.3):** zero rows means zero data loss, but the migration is still one revertible commit, and the recurrence option on commitments lands *first* so the capability never has a gap.
- **Self-evolution (S)** is deliberately last and narrow: tunables → prompts → services, David-merged only, protected paths unpatchable, one PR at a time. The failure mode to fear isn't rogue changes (the ladder prevents that); it's *noise* — low-quality proposals. The 70% merge-rate gate self-throttles it.
- **People seed quality (D.1):** merge conservatively; a wrong merge poisons prep notes. `source='seed_2026_07'` keeps it one-statement reversible.
- **Deliberation over-correction (C.2):** watch proposal rate for a week after removing passivity training — the gate's caps and payload lint bound the blast radius; new-verb θ priors start high and earn their way down.
- **Anticipation creep (L):** the day model is *context*, not a nag source — deviations feed tone and timing, never direct notifications (health ban and anti-nag rules unchanged).
- **Deployed code lags the tree** (`gotcha_deployed_code_lags`): every phase ends with a rebuild + restart timed against in-flight dispatches, and verification happens against *runtime*, not the diff.

---

*The thesis, one last time: fix the last inch — silence the template voice, wire the orphaned verbs, make learning act, speak from one place in one voice, give every answer a one-tap response and every artifact an address. Tune the verticals until each one closes its loop. Then raise the ceiling — a forward model of the day, a closed comms loop, a defended calendar, finished work by morning, a voice in the room, a deepening model of the one person who matters. Then hand her the wrench: a scorecard she reads, proposals she writes, patches David merges. The extraordinary machinery already running underneath stops being infrastructure and becomes what it was always meant to be — felt, useful, and compounding.*

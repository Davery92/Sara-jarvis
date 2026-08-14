# Mind V2 — Sender Rewiring + Push Bootstrap Plan (2026-07-28, evening)

Implementation directive for the next session. Produced from a live audit of today's
post-deploy behavior (all times ET). **David has approved both decisions in here:**
build the sender rewiring now (dual-write, shadow-safe), and bootstrap cold-start
pushes immediately — he is currently getting inbox junk and zero buzzes.

---

## 1. Evidence driving this plan (today, post-deploy 09:14)

All of this was verified against the live DB/logs today; don't re-derive, just fix.

1. **Shadow pipeline is starved, not broken.** 144 appraisal cycles today → **0
   say_candidates**. The observation log contains only derived-signal counters
   ("22 emails received in last 24h", "3 new person(s) this week") — no content.
   Every real event (Jim/Alex/Matthew emails, meetings) flows through legacy
   senders that bypass the candidate queue. A shadow week on this feed proves
   nothing. Feeding the queue is the prerequisite for the shadow week.
2. **Peripheral-brain blindness, three live demos today:**
   - 07:24 chat: Sara calls the Selective research garbage (hallucinated "Phxins"
     from a misparsed location field). 07:30: `research_executor` pushes
     "JFK meeting prep is ready" for that exact brief.
   - 14:02 chat: David says "bittitan has been postponed". 14:15: `proactive_checkin`
     followup asks what's left to finish BitTitan.
   - `cross_system_synthesis` re-flagged the same emails repeatedly (Alex 10:44 +
     12:44, Jim 11:44 + 14:44, Jim's Derek email twice last night) despite stable
     `xref:email:<id>` topics — dedup/cooldown is not holding (see §5.2).
3. **Nothing pushes.** Every checkin/followup today logged `sent=f` (silent inbox).
   Three stacked gates: priority `normal` → inbox-only in the attention queue;
   learned-buzz needs ≥5 sends + ≥40% engagement/30d (cold-start deadlock — no
   pushes → no engagement → never earns buzz); daily budget caps non-urgent at 2.
4. **Small appraisal bug:** the only LLM output today was `health_deltas/weight →
   "Weight 240.00 lbs"` written **twice** (12:24, 13:54). The patch content embeds
   the *write time* in `at`, defeating the `brief_patch` no-op guard — same class
   as the sara_state clock leak fixed in b52b188c. It also isn't a delta (240
   unchanged for weeks).
5. **Unclosed promise:** 14:05 chat — Sara: "I'll ping you once it's confirmed
   archived" (Kimberly/Aeman thread cleanup). Both tasks completed 14:06/14:08;
   only `task_result_delivery` ledger rows exist, no user-visible completion
   notice found in notification_log. Verify where (if anywhere) it was delivered;
   wire this class through the `sara_commitment` ledger.

---

## 2. Workstream A — Cold-start grace pushes (do this FIRST, it's small and David wants buzzes now)

**File:** `backend/app/services/unified_notification.py`
Symbols: `_learned_buzz_decision` (~line 963), `_daily_push_budget_available`
(~1022), `route_through_attention_queue` (~1044; buzz decision applied ~1164).

**Change:** in `_learned_buzz_decision`, when a category has **insufficient history**
(fewer than the 5-sends threshold in the 30d window), return True (push) instead of
False — a bootstrap grace so engagement stats can start accumulating. Guardrails:

- Grace pushes still respect `_daily_push_budget_available` and the sleep gate /
  delivery policy. No new bypasses.
- Cap grace: max **2 grace pushes per category per day** (query notification_log
  for today's sent=true rows in that category before granting). Without this cap,
  the hourly cross_system_check would burn the whole budget on checkins.
- Once a category crosses the 5-send threshold, normal learned-buzz logic takes
  over — grace is only for the cold start. Do NOT special-case engagement.
- Log the grace path distinctly (e.g. `logger.info("[buzz] cold-start grace push
  category=%s")`) so the effect is measurable in a week.

**Acceptance:** within a day, some checkin/followup rows log `sent=t`; budget
counter in sara_state ("Notifications sent today: n/8") reflects them; no pushes
between 22:00–07:00.

## 3. Workstream B — Rewire legacy senders to dual-write `say_candidate`

**Pattern (identical for every sender):** keep the legacy `send_notification` call
exactly as-is (behavior unchanged until the MINDV2_COMPOSE flip), and *additionally*
emit a candidate via `say_candidate.create_candidate` (~line 37,
`backend/app/services/say_candidate.py`). The judge/compose/review chain then
processes real content into `composed_utterance` — the honest preview table.

Per-sender mapping (priority order — each is its own commit, deploy, verify):

| # | Sender | File / call site | valid_until | refs (evidence) |
|---|--------|------------------|-------------|-----------------|
| 1 | cross_system_synthesis | `backend/app/tasks/calendar_prep.py` `cross_system_check` (~47) — generator: `app/services/proactive_intelligence.cross_reference_check` | linked event's **start** time (the insight is worthless after the meeting) | email message id + event id (already in the `topic`) |
| 2 | proactive_checkin / followups | `backend/app/services/proactive_checkins.py` (~123) | task due date, else now+24h | task/thread id |
| 3 | calendar_prep reminders | `calendar_prep.py` `check_upcoming` | event start | event id |
| 4 | research_executor completion | wherever `source="research_executor"` sends (`grep -rn 'research_executor' backend/app`) | meeting start | research doc id + event id |
| 5 | task_result_delivery (dispatch results) | `backend/app/services/task_result_delivery.py` | now+12h | task id |
| 6+ | long tail: morning_proactive, predictive_engine, bedtime_intelligence, travel_nudge, learning_digest | respective services | contextual | contextual |

Notes:
- `valid_until` is NOT NULL by design — never default it to something huge; the
  TTL is what kills post-meeting staleness (BitTitan/post-meeting flags class).
- Candidate identity: pass the same stable key used for the notification topic so
  the judge sees "already have a pending/killed candidate for this email+event"
  and duplicates die structurally.
- Wrap candidate emission in try/except with a warning log — a candidate-queue
  failure must never break the legacy send while it's still the delivery path.

**Acceptance per sender:** trigger or wait for one real firing; confirm a
`say_candidate` row with correct `valid_until`, then a `composed_utterance` row
(or a logged judge kill with a sane reason). Senders 1–2 alone cover ~85% of
today's volume — get those two live before touching the rest.

## 4. Workstream C — Judge must read recent chat

This is the fix for the Phxins-push and BitTitan-nag class. **File:**
`backend/app/services/judge.py` — `_gather_context` (~57), `_build_prompt` (~94).

- Add last **6 hours** of `conversation_turn` (role + first ~200 chars per turn,
  cap ~30 turns) to the judge context.
  **Gotcha:** `conversation_turn.created_at` is `timestamp without time zone`
  storing **naive UTC** — compare against naive `datetime.utcnow()`-style bounds;
  do NOT pass it through ET helpers or `AT TIME ZONE` (double-shift).
- Prompt instruction to add: *"If the recent conversation shows David has already
  handled, dismissed, postponed, or contradicted this item, verdict is kill, with
  the chat turn as the reason."*
- Same context block goes to `compose.py` if it isn't already there — compose
  should phrase around what was said in chat, not repeat it.

**Acceptance:** insert a test candidate about a topic the chat has just dismissed
(e.g. a "BitTitan next steps" candidate after a "postponed" turn) → judge kills it
citing the conversation.

## 5. Workstream D — Bug fixes (small, do alongside A)

### 5.1 Weight-delta churn (appraisal)
`backend/app/services/appraisal.py` — the health_deltas patch builder stamps
`content.at` with patch time. Fix: `at` must come from the **measurement's own
timestamp** (the health row), and skip emitting a "delta" when the value equals
the current brief item's value. Store-absolute/render-relative applies to every
`at` field: never `now()` unless the event genuinely just happened.

### 5.2 xref dedup not holding
Same email produced checkins hours apart with what look like identical
`xref:email:<id>` topics (Jim 19:44 + 21:44 on 7/27; Alex 10:44 + 12:44 today).
Diagnose before patching: pull both rows' **full** topics (display truncation hid
the tails — Outlook ids share a long prefix). If topics are identical, the
cooldown (default 4h) failed for `sent=f` rows — likely the dedup window only
considers `sent=true` rows or the attention-queue path logs without consulting
cooldown. If topics differ, the generator is appending something unstable (e.g.
a per-run event list) — make the topic exactly `xref:{email_id}:{event_id}`.
This matters even post-flip: less junk written to the inbox while legacy runs.

### 5.3 Commitment ping (Kimberly/Aeman class)
Trace why the 14:06/14:08 task completions produced no user-visible notice
(`task_result_delivery` delivered where?). Then: when chat dispatches a background
task with an explicit promise to report back, write a `sara_commitment` row at
dispatch time and mark it fulfilled when the completion notice actually delivers.
If delivery silently landed in a dead path, that's the bug to fix first.

---

## 6. Order of work, deploys, and guardrails

1. A (grace pushes) + D.1 (weight bug) → commit → restart backend **and** celery
   worker/beat (deployed-code-lags gotcha: code loads only at container restart)
   → verify A's acceptance.
2. B.1 (cross_system_synthesis) + C (judge chat context) together — they're the
   payoff pair → commit, deploy, verify with the next hourly cross-system run.
3. B.2–B.5 one at a time. D.2/D.3 whenever convenient between them.
4. **Do not flip MINDV2_COMPOSE in this pass.** The flip happens after David has
   read a few days of `composed_utterance` fed by real content. Do not remove or
   gate any legacy send in this pass either — dual-write only.
5. Branch: work directly on `feat/sara-mind-v2` in `/home/david/jarvis` (the
   backend container bind-mounts `./backend`). Conventional commits, one
   workstream per commit.

## 7. What done looks like

- David's phone buzzes a handful of times a day (grace-limited), nothing 22:00–07:00.
- `composed_utterance` accumulates rows about real things (emails, meetings,
  tasks) with judge/review verdicts — readable as "what Mind V2 would have said."
- A candidate contradicted by recent chat dies in the judge with the chat cited.
- `world_brief_patch_log` stays change-only (no repeated weight rows).
- Same email+event never produces two inbox items.
- A chat promise to report back has a `sara_commitment` row and a delivered notice.

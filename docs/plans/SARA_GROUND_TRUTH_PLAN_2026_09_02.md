# Sara Ground Truth Plan — 2026-09-02

Implementation directive. Written after a live audit of the production database and the
`feat/sara-mind-v2` working tree on 2026-09-02. Companion documents (published artifacts,
not required to implement):

- Audit: https://claude.ai/code/artifact/47183406-0c8b-40ca-829f-348160bbdadf
- Plan (this document, rendered): https://claude.ai/code/artifact/87652965-19e5-4e8d-95ca-7a39779afb72

**Goal.** Nothing Sara reminds David about is invented, nothing she nags about is already
done, every time she says is the time it is, she sees the same task world David sees, and
the context she reads at chat time agrees with itself.

**How to use this file.** Phases are ordered. Each phase is one commit with its acceptance
test. Phase 0 is data only. Do not skip to Phase 4 before Phases 1–3 are in; the entity
ledger in Phase 4 depends on the closers in Phase 2 and the clock in Phase 3.

Every path below is relative to `backend/app/` unless it starts with `docs/`, `scripts/`
or `data/`. Container restart after code changes:
`docker compose -f docker-compose.dev.yml restart backend celery-worker celery-beat celery-critical celery-david-priority celery-acs`
(check `background_task` for in-flight work first). Verify runtime artifacts, not the
working tree — deployed code has lagged before.

---

## 1. What happened (the evidence)

### 1.1 The Laura Weippert meeting that never existed

Times Eastern.

| When | Event | Table / code |
|---|---|---|
| Aug 28 12:21 | Laura sends a Teams invite "Connect with the Dave's". `email.has_meeting=true`, `calendar_event_id=NULL`. No calendar event is ever created. | `tasks/email_sync.py` |
| Aug 31 11:56 | Laura: "Any chance we can move this call to tomorrow afternoon?" No time in the email. | `email` |
| Aug 31 11:59 | World interpreter reads the `email.analyzed` event and creates `world_thread` 75ec1d5b "Respond to Laura Weippert regarding call reschedule request", kind commitment, **due_at 2026-09-01T17:00Z (invented)**. | `services/world_state/interpreter.py`, `reducer.py` |
| Aug 31 12:17 | David replies. Laura: "Thank you!" at 12:37. Resolved in reality. | `email` (sent mailbox) |
| Aug 31 12:03, 13:53 | Deliberation pushes "Laura wants to reschedule", "Laura's call reply". Nothing resolves a thread on a sent reply. | `services/deliberation_gate.py` |
| Aug 31 13:55 | Interpreter reads **Sara's own assistant turn** (`chat.assistant_turn_stored`) and creates threads d4af9cd2 "Confirm availability for Laura Weippert's rescheduled call" and 135a64ce "Provide extra BOP model file to Jim Venezia", both due 17:00Z. Deliberation auto-executes two notes ("Laura Weippert Reschedule Request - Aug 31", "Draft Reply to Laura Weippert - Reschedule") which enter memory and the PKG. | `world_state/catalog.py` (`chat` domain has `interpret=True`), `deliberation_gate.py` AUTO_EXECUTE |
| Sep 1 04:34–05:06 | Overnight deliberations paraphrase the concern; one renders 17:00Z as "your 5:00 AM EDT call". Held for sleep, flushed 06:00 as 3 inbox items. | `services/delivery_policy.py`, `tasks/delivery_flush.py` |
| Sep 1 13:00 | `thread.overdue` emitted for all three threads. Deliberation sends "due at 1 PM overdue" (correct), suppresses 3 paraphrases via attention_cooldown, sends "5:00 PM call 19 minutes overdue" at 17:20 (UTC read as local). | `world_state/temporal.py` |
| Sep 1 17:02→20:08 | Every chat turn carries "[#3280] (schedule, Tue 10:00) Missed Laura's call: … 5:00 AM EDT …" in the unacknowledged block. Time is UTC. Phone reads never set `read_at`. | `services/notification_ack.py::get_unacked_for_context` |
| Sep 2 06:00 | Five more paraphrases (held74–78) flushed into the inbox. | `notification_log` 3305–3309 |
| Sep 2 06:04 | David: "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE WE HAD OUR MEETING". Sara cancels two unrelated reminders, edits two notes, correctly says she has no tool to close a thread. Threads still `status=open`. Journal at 06:30 claims cleanup. | `sara_journal` |

### 1.2 The Salem report that finished and was never announced

| When | Event |
|---|---|
| Sep 1 17:05 | David asks for a background report. `research_plan` c4865220 created (origin david_chat), running. |
| Sep 1 17:15 | "Is it running?" `get_background_tasks` read `background_task` only (blind to research plans). Sara: "not running, plan doesn't exist." A fix exists in the working tree (`tools/agents.py` now calls `agent_activity.get_agent_activity`); verify it is deployed. |
| Sep 1 17:18, 17:46, 20:08 | Three more identical plans (fdf7ccb0, 78d4dc0d, 026cb418). All four complete by 21:28. Three "Salem MA Historical Guide - Completed" notes in Agent Workspace. |
| Sep 1 21:28 | Result → `say_candidate` → judge `batch [slot=morning]`. Morning window is 08:00–12:00 ET (`tasks/mindv2_batch_flush.py`). David leaves at 07:00. "I'll ping you when it's ready" never became a `sara_commitment`. |

### 1.3 What the chat context said at 06:02 on Sep 2 (28,985 chars)

| Block said | True | Cause |
|---|---|---|
| "David: unknown (interruptibility 0.50)" | typing on iPhone at home, kitchen sensor on | `sara:unified_context` says unknown/Office; `working_memory:*:user_state` says in_meeting/busy. Chat never sets activity. |
| "leave ~6:24" / "7 AM departure" / "leaves for work 7am" | one of these | `daily_rhythm` (8 samples, conf 0.48) + theory_of_david + `life_fact` (stated 0.95) all rendered |
| "habit of taking lunch at 2 AM", "lunch 2am" | not a thing | `life_fact lunch_at=02:00 stated 0.95` |
| "Vesper (Pet (Dog))" 0.99 | stable layer says kitten | PKG vs `data/briefs/<uid>/layers/stable.md` never reconciled |
| "eight live items requiring attention" | 3 standing orders + 2 cancelled reminders | `sara_journal_service.write_theory_of_david` inputs |
| "open_threads=0" and 8 active threads incl. Laura | 3 stale threads | `context_snapshot.get_world_state` reads `followup_thread`; JSON dump reads `world_thread` |
| Journal "09:38 AM David is asleep" | 05:38 ET | `sara_journal_service.py:429 strftime("%I:%M %p")` on UTC |
| health_today all "unavailable" | sleep 6.1 h / HRV existed, stamped 06:00 | HealthKit sync landed 07:22 ET; 6 AM brief and early chat run before sync |
| fleet: 6 hosts unreachable, never reported | no agents enrolled | dead slice injected every turn |
| Re-entry: ten outside-temperature lines | nothing relevant | `context_writer.py` notable-change buffer is mostly weather refresh |
| memory.recall: 4/5 hits are "Salem research completed" notes | her own duplicates | `memory_recall.py` ranks Sara-written notes as "confirmed", no title dedupe |
| 14,000-char JSON blob cut mid-word | light events, AWS invoice as "communications", Sep 30 dinner as "schedule" | `world_state/context.py::format_context_for_prompt` → `rendered[:14000]` |
| Self-story: "cowardice wearing a mask… I am terrified…" | nothing happened | `reflection/agent.py` calls `write_self_story` every 4 h from the deliberation journal (~130 "staying quiet" lines/day); injected via `context_snapshot.render_engaged_context` |

Cost: volatile block 7–8k tokens, uncacheable. The 06:03 turn made 10 model calls at 20–28k
prompt tokens each (243k total), first token +71 s, complete +106 s. 7-day average 23,900
prompt tokens per chat call; one call on 08-26 sent 649,234.

---

## 2. Six defects

- **D1 She invents obligations.** Interpreter emits `due_at` for emails with no time; runs on Sara's own turns; deliberation auto-writes notes about the result; notes feed memory/PKG.
- **D2 Nothing closes anything.** `reducer.py` resolves threads only on `conversation.closed`, `workout.completed`, task terminal. No tool closes a thread. Reminders from Jan 2026 still open. `sara_commitment` has one closure ever.
- **D3 Three clocks.** `world_thread.due_at` UTC handed raw to prompts; `calendar_event.start_time` naive local; `notification_ack` formats UTC with `%a %H:%M`; journal formats UTC with `%I:%M %p`.
- **D4 Two mouths, one told silence is failure.** `deliberation_gate.py` calls `send_notification` directly beside Mind V2; `deliberation_prompt.py` says proposing nothing "is a FAILURE, not restraint"; dedup hashes title+message; ~140 deliberations/day incl. 1–5 AM (daemon proxies with `force=True`).
- **D5 Stale pushes leak into chat.** 24 h unacked block, UTC times, full stale body, phone reads don't count.
- **D6 Different task worlds.** Tool blind to research plans; no single-flight; david_chat results batched to a window after departure; promises not commitments.

## 3. Invariants (build and test to these)

1. **No invented time.** A due/meeting time enters only from a calendar event, an explicit datetime in source text, or David's words. An LLM may propose a thread, never a deadline.
2. **Sara's words are not evidence.** Nothing Sara writes/says/drafts creates a fact, thread, commitment or memory-visible note about David.
3. **Everything open has a closer and an expiry.**
4. **One clock.** No timestamp reaches a prompt or message except through one ET renderer. Raw ISO in prompt builders is a lint failure.
5. **One entity, one message, one mouth.** Every outbound message names its entity (thread id, email conversation id, calendar event id, task id). ≤1 live candidate and ≤1 delivered message per entity per day across all senders.

---

## Phase 0 · Stop the bleeding (data only, ~1 h)

Run in order. Reversible except the note moves (move, don't delete).

```sql
-- 1. Expire every thread more than 48 h past due (includes the 3 Laura threads)
UPDATE world_thread SET status='expired', resolved_at=NOW()
 WHERE status IN ('open','waiting','proposed','blocked')
   AND due_at IS NOT NULL AND due_at < NOW() - INTERVAL '48 hours';

-- 2. Expire threads created from Sara's own speech
UPDATE world_thread t SET status='expired', resolved_at=NOW()
  FROM world_event e
 WHERE e.event_id = t.source_event_id AND t.status IN ('open','waiting','proposed','blocked')
   AND e.payload::text LIKE '%interpreted:chat.assistant_turn_stored%';

-- 3. Reminders that never fired and are >7 days old
UPDATE reminder SET is_completed=true
 WHERE is_completed=false AND reminder_time < NOW() - INTERVAL '7 days';

-- 4. Nothing older than a day is "unacknowledged"
UPDATE notification_log SET read_at=NOW()
 WHERE sent=true AND read_at IS NULL AND sent_at < NOW() - INTERVAL '24 hours';

-- 5. Drop pending Laura candidates; release the Salem result
UPDATE say_candidate SET status='judged_drop', judge_reason='manual: resolved by David 09-02'
 WHERE status IN ('pending','judged_batch','judged_send') AND summary ILIKE '%laura%';
UPDATE say_candidate SET status='judged_send', judge_reason='manual: david_chat result, deliver now'
 WHERE status='judged_batch' AND source='research_executor' AND summary ILIKE '%salem%';
```

Also:
- Move notes "Laura Weippert Reschedule Request - Aug 31", "Draft Reply to Laura Weippert - Reschedule", and two of the three "Salem MA Historical Guide - Completed" notes into a `Quarantine` folder (create it). Keep one Salem guide.
- `data/HEARTBEAT.md`: delete "No current workout routine — he's between programs"; delete the swim-lesson paragraph and strikethrough; add under Hard Bans: "Never state a time for anything that is not on the calendar or explicitly in the source text."
- `UPDATE life_fact SET value_text=NULL WHERE predicate='lunch_at' AND value_text='02:00';` (or set the real value if David gives one).
- Verification: tomorrow's 06:00 flush (`notification_log` where `source='held_flush_item'`) carries zero Laura items; `world_thread` has no open row with `title ILIKE '%laura%'`.

## Phase 1 · Stop inventing (~1 day)

Files: `services/world_state/interpreter.py`, `services/world_state/reducer.py`,
`services/world_state/catalog.py`, `services/deliberation_gate.py`, `services/appraisal.py`,
`services/world_brief.py`.

1. **Interpreter cannot emit `due_at`.** Remove `due_at` from the `threads` schema in the prompt (`interpreter.py:163`). In `reducer.py` (`_thread` calls at ~349 and ~311), accept `due_at` only when the event payload carries a deterministic source: calendar event start/end, an explicit datetime regex match in the source text (log the matched substring in `provenance`), or a `chat.user_turn_stored` event. Otherwise `due_at=NULL`, `next_review_at = created_at + 3 days`.
2. **No threads from Sara's own turns.** `catalog.py`: split `chat.assistant_turn_stored` into its own registration with `interpret=False`. If interpretation is kept for facts, have the reducer discard `threads[]` when `event.kind == 'chat.assistant_turn_stored'`.
3. **One thread per email conversation.** In `reducer.py` email branch (~270): `thread_key = f"email:{conversation_id}"` (fall back to `email-action:{email_id}` only when conversation_id is NULL). Interpreter threads for email events must use the same key; a second interpretation updates the existing row.
4. **Deliberation stops writing notes about people threads.** In `deliberation_gate.py::_route_task_proposals`, drop `note_organization` from `AUTO_EXECUTE_CATEGORIES` when the proposal text names a person or email (regex on capitalized bigrams + `@` + "email"/"reply"), routing it to propose-first. Additionally every note written by deliberation/agent dispatch gets tag `sara_generated`; `memory_recall.py` and `pkg_extractor.py` skip that tag (see Phase 5).
5. **World Brief patch filter.** In `world_brief.brief_patch()`: reject/strip lines starting with "New signal:" or containing `(salience`; reject patches containing any `_BANNED_PHRASES` term from `deliberation_gate.py`; reject relative-time strings (`— in \d+h`, `\d+ minutes ago`); cap `happened` entry text at 300 chars. In `appraisal.py`, add to the prompt: "brief_patches must describe the event, never copy the signal list."

Acceptance: `tests/test_ground_truth_phase1.py` — replay Laura's three emails + David's sent reply through analyze → interpret → reduce with a stubbed interpreter returning a thread with `due_at`; assert one `world_thread`, `due_at IS NULL`, `thread_key='email:<conversation_id>'`. Replay an assistant turn; assert zero threads.

## Phase 2 · Closers (~1.5 days)

Files: `tasks/email_sync.py` (`_sync_sent_items_async`), `services/world_state/reducer.py`,
`services/world_state/temporal.py`, `tools/` (new `resolve_thread`), `services/chat_intercepts.py`,
`services/notification_ack.py`, `services/agent_dispatch.py`, `services/commitment_service.py`.

1. **Answered email closes the thread.** In sent-items sync: for each new sent message, `append_world_event(kind='thread.resolved', source='sent_reply', aggregate_id=<thread id>)` for every open thread with `thread_key='email:{conversation_id}'`. Reducer handles `thread.resolved` → status resolved. Register the kind in `catalog.py`.
2. **Calendar end closes references.** In `temporal.py`, when emitting `calendar.ended`, also resolve open threads whose `source_ref` or title references that event id/title.
3. **David's words close things.** New tool `tools/threads.py::ResolveThreadTool` (`resolve_thread(query|thread_id)`) → sets status resolved with `source='david_chat'`, drops live `say_candidate` rows for the entity, marks related `notification_log` rows read, and removes the entity from `unified_context` open-thread/unhandled-email counts in the same request. Add an intercept in `services/chat_intercepts.py` for "we had the meeting / already handled / done with X / stop about X / enough about X" that calls the same function and confirms in one line. `notification_ack.acknowledge()` resolves the thread linked to each acked item (`notification_log.topic` → entity).
4. **Hard expiry.** In the nightly job (Phase 7) and inline in `temporal.synthesize`: thread with due_at → expired 48 h after; thread without → expired 14 days after `last_event_sequence` change; reminder never fired → completed 7 days after `reminder_time`.
5. **Overdue fires once.** Add `status='overdue'` transition in `temporal.py` when emitting `thread.overdue`; judge/deliberation may not propose about an `overdue` thread more than once (entity ledger, Phase 4).
6. **Promises become commitments.** In `agent_dispatch.py` / `research` dispatch path: when created from chat with `notify_on_complete=True` or origin `david_chat`, create `sara_commitment` "tell David when <title> is ready", `trigger_description=task id`. Task completion closes the commitment → candidate with `kind='alert'` and `urgency` from origin (david_chat = never batch; use `urgent_lane` if awake, else first item of wake digest).

Acceptance: sent-reply fixture resolves the thread within one sync; chat "we had the meeting with Laura" resolves all threads matching Laura and drops candidates; a thread with no closer kind in the catalog fails `tasks/system_wiring_check.py`.

## Phase 3 · One clock (~0.5 day)

Files: `core/timezone.py`, `scripts/check_naive_datetime.py`, every prompt builder.

1. Add `render_when(dt, now=None, source_convention=None) -> str` to `core/timezone.py`: converts aware datetimes, and naive ones only with an explicit `source_convention in {'utc','et'}` (raise otherwise); returns "Tue Sep 1, 1:00 PM ET (in 3h 10m)" / "(2h ago)"; all-day dates render as "Thu Sep 3 (all day)", never a midnight time.
2. Use it in: `temporal.py` `thread.overdue` payload (add `due_text`, and make observation/attention text use `due_text` only); `deliberation_prompt.py` whiteboard (Schedule, Open Threads, Previous Handoff); `world_state/interpreter.py` event view (`occurred_at` → text); `notification_ack.get_unacked_for_context`; `world_brief.py` renderer; `compose.py` evidence lines; `context_snapshot.py` calendar lines and journal lines (`sara_journal_service.py:429`); `context_writer.py` notable-change lines.
3. Extend `scripts/check_naive_datetime.py`: fail on `.isoformat(` or `.strftime(` inside `services/*prompt*.py`, `services/world_state/`, `services/notification_ack.py`, `services/compose.py`, `services/judge.py`, `services/appraisal.py`, `services/context_snapshot.py`. Prompts get text, never timestamps.
4. `tasks/email_sync.py`: when `has_meeting=true`, create the `calendar_event` (with owner resolution via `calendar_ownership.py`) or set `has_meeting=false`. No half-detected meetings.

Acceptance: fixture of thread due 17:00Z, calendar naive 13:00, push sent 10:00Z renders "1:00 PM ET", "1:00 PM ET", "6:00 AM ET"; lint script finds zero raw timestamps in the listed paths.

## Phase 4 · One mouth (~2 days)

Files: `services/deliberation_gate.py`, `services/deliberation_prompt.py`, `services/say_candidate.py`,
`services/judge.py`, `services/review.py`, `services/task_result_delivery.py`,
`services/calendar_prep.py`, `services/bedtime_intelligence.py`, `services/travel_nudge.py`,
`tasks/calendar_prep.py` (cross_system), `services/morning_proactive_service.py`, `services/interoception_alerts.py`.

1. `deliberation_gate._deliver_notification` → `say_candidate.create_candidate(..., dedupe_key=<entity id>)` and never `send_notification`. Entity id = `world_thread.id` / `email.conversation_id` / `calendar_event.id` / task id, carried on the proposal (add `entity_ref` to `NotificationProposal`; prompt asks for it). Pattern to copy: `services/proactive_checkins.py`.
2. Delete both "is a FAILURE, not restraint" paragraphs in `deliberation_prompt.py`. Replace with: "Propose only about an entity that has no live candidate and no delivered message today. The Entity Ledger below tells you which those are."
3. **Entity ledger in the whiteboard** (`deliberation_prompt._format_memory_whiteboard`): for each open thread / unhandled email / upcoming event: `last_told: 2h ago via push | candidate_live: yes | status: overdue`. Source: `notification_log.topic`, `say_candidate` (pending/judged_*), `world_thread.status`.
4. `say_candidate.create_candidate`: structural dedup on `dedupe_key` across all sources and against today's `notification_log.topic` (normalize topics to `entity:<id>`).
5. Convert remaining direct senders to candidates with `kind='alert'` and short TTL: task_result_delivery, calendar_prep, bedtime, travel_nudge (already via urgent lane), cross_system_synthesis, morning_proactive, interoception alerts (`kind='alert'`, one per subsystem per day). Timers/reminders predispatch and `reactive_engine` security stay direct.
6. `review.py` "said before" input: delivered `composed_utterance.final_text` for the same `dedupe_key` in the last 7 days, plus `notification_log` messages for the same entity.

Acceptance: ten deliberation cycles over one unhandled email fixture → ≤1 candidate live, ≤1 delivery/24 h across all sources, cycles 2–10 propose nothing; grep `send_notification(` in `deliberation_gate.py` returns zero.

## Phase 5 · Rebuild the chat context (~2 days)

Files: `services/context_snapshot.py` (`get_world_state`, `get_extended_signals`, `render_engaged_context`),
`services/world_state/context.py`, `services/unified_context.py`, `services/working_memory.py`,
`services/cognitive/working_memory.py`, `services/sara_journal_service.py`, `services/reflection/agent.py`,
`services/notification_ack.py`, `services/memory_recall.py`, `services/life_facts.py`, `main_simple.py` (chat_stream re-entry block ~8576),
`services/chat_turn_notify.py`.

1. **One state.** Retire `working_memory:*:user_state` / `system_state` (`services/cognitive/working_memory.py` writers); `sara:unified_context` is the only snapshot. In `chat_turn_notify.py` (turn preamble) set `activity_state=engaged`, `app_active=1`, `current_place` from the requesting device before context assembly.
2. **One fact per predicate.** New `life_facts.resolve_predicate(predicate)` with precedence: stated life_fact → calendar → `daily_rhythm` row with `confidence>=0.5 AND sample_count>=10` → None. `render_engaged_context` and `get_life_facts_summary` and `theory_of_david` all read through it. The expectations slice's `rhythm_summary` is removed when a stated fact exists for the same predicate.
3. **Replace the JSON dump.** Delete the `format_context_for_prompt` injection in `main_simple.py` (~8266) and `world_state/context.py::format_context_for_prompt`. Inject `world_brief.get_rendered_brief()` (prose, ≤30 lines, times via `render_when`, NOW/TODAY live). If a slice of the projection is needed, render it as one line of prose, never JSON.
4. **Budget.** `context_budget.py`: hard cap 6,000 tokens for the volatile block with per-section allotments (brief 1,500 / calendar 400 / memory 600 / unacked 300 / directives+facts 300 / lessons 300 / device 150 / re-entry 300); truncate at sentence boundary; log `context_budget: section=... kept=... cut=...` per turn.
5. **Self-story out of the prompt.** Remove the `self_story` line from `render_engaged_context` (`context_snapshot.py:56-60`). Keep the journal row for the UI. Change `write_self_story` cadence in `reflection/agent.py` to once nightly, 80-word cap, and exclude `entry_type='deliberation'` from its inputs.
6. **Theory of David derived, not narrated.** `write_theory_of_david` inputs: life facts via `resolve_predicate`, behavioral patterns with `confidence>=0.7`, open intents. Exclude `standing_order`, `reminder`, and journal text. Nightly only; 120-word cap; may not include a number already in the life-facts line.
7. **Health: latest with time.** `get_world_state` health slice: latest `health_metric` per type in the last 36 h with `render_when(recorded_at)` and `synced` time (`created_at`); morning brief (`morning_brief_service`) waits up to 20 min for a HealthKit sync after 06:00 or says "sleep not synced yet".
8. **Drop dead slices.** Fleet slice omitted when `managed_host` has no reporting hosts; `patterns` line omitted when all are lock/light cycles at 100%; re-entry (`main_simple.py` ~8586) lists only changes of kind email/calendar/task/thread, never `temperature_outside`/weather.
9. **memory.recall excludes Sara's output.** `memory_recall.py`: skip notes tagged `sara_generated` or in the Agent Workspace folder (`settings.acs_default_note_folder_id` and the workspace folder id) unless the user message mentions research/report/agent; dedupe hits by normalized title.
10. **Unacked block.** `get_unacked_notifications(hours=6)`; titles only; `render_when`; exclude items whose entity (`topic`) is resolved/expired/dropped. iOS: notification open and Notifications-screen view call the existing mark-read endpoint (`routes/push_tokens.py` / `notification_log.read_at`).
11. **Stable layer** injection: end at a paragraph boundary, not `[:1500]`.

Acceptance: render the context for a fixture turn → asserts: exactly one departure time; no `self-story` header; no `{` JSON in the block; token count ≤ 6,000; every time string matches `render_when` format; no `sara_generated` note in recall. Measure: `stage-timing first_token` under 20 s on the 27B for a plain conversational turn.

## Phase 6 · Task truth (~1 day)

Files: `tools/agents.py`, `services/agent_activity.py`, `tools/research_plan.py`, `services/research/executor.py`,
`services/task_result_delivery.py`, `tasks/mindv2_batch_flush.py`, `tasks/system_wiring_check.py`.

1. Verify `get_background_tasks` → `get_agent_activity` is in the running container (`docker exec jarvis-backend-1 grep -n get_agent_activity /app/app/tools/agents.py`). Add a wiring-check assertion that the tool, `/api/agent-activity`, and `research_plan_status` share one function.
2. Single flight: `create_research_plan` normalizes title (lowercase, strip punctuation) and, if a plan with the same normalized title and origin exists in `('running','pending')` or completed within 12 h, returns that plan's id with `attached=true`. Tool description tells Sara to say "already running as <id>".
3. `david_chat` results never batch: in `judge.py`, candidates with `source='research_executor'` whose plan origin is `david_chat` get `send_now` (or `urgent_lane` from `task_result_delivery`); asleep → held → first item of the wake digest, not the 08–12 window.
4. Result notes: one per plan title per day; later completions append "(run 2)" to the existing note instead of creating another.

Acceptance: two identical `create_research_plan` calls within 12 h → one plan; `get_background_tasks` and the iOS pill return the same id/status for a running plan.

## Phase 7 · Nightly truth job (~1 day)

New: `tasks/truth_maintenance.py`, scheduled 03:50 ET on `maintenance` (add `scheduled_job` row `truth-maintenance`, category `system`, visibility `user`). Deterministic, no LLM.

1. Run the expiries from Phase 2 §4 and the Phase 0 SQL generically (parametrized windows).
2. Audit and write one `sara_journal` row `entry_type='truth_maintenance'` + a `truth_maintenance_report` table (date, counts, flags):
   - threads/reminders/commitments/candidates expired tonight by source; any expiry whose source event is `chat.assistant_turn_stored` increments a bug counter.
   - governing docs older than 30 days: `data/HEARTBEAT.md`, `docs/sara_self_model_*.md`, `interest_model.updated_at`, `data/briefs/<uid>/layers/stable.md`.
   - regenerate `docs/sara_self_model_autonomous.md` and `_capabilities.md` from `scheduled_job` + `tool_registry` (template in the task; keep hand-written prose sections between markers).
   - life-fact sanity: `lunch_at` ∉ [11:00,15:00], `wakes_at` ∉ [04:00,09:00], `departs_for_work_at` ∉ [05:30,09:30], `bedtime_at` ∉ [20:00,00:30] → flag, set `confidence=0.2`, never delete.
   - predicates with two live values (life_fact vs daily_rhythm vs PKG): list them.
   - emails with `has_meeting=true AND calendar_event_id IS NULL`.
   - PKG/stable-layer contradictions on pets/people (same canonical name, different type).
3. Morning brief: one line from the report: "Overnight I closed N stale threads and dropped M duplicate reminders." (`morning_brief_service.py`, after the calendar section).

## Phase 8 · Cadence and cost (~0.5 day)

Files: `acs-daemon/backend_client.py` / `daemon.py`, `services/kernel.py`, `services/salience.py`,
`services/subconscious.py`, `core/llm.py` (background client), `tasks/autonomy.py`.

1. Daemon `ambient_turn` proxy passes `force=False`; only `periodic_deliberation_fallback` keeps `force=True`, and only 06:00–22:00 ET.
2. `kernel.ambient_turn`: hard skip 01:00–05:00 ET unless `wake_reason in (INTEROCEPTION)` with severity critical or a security event.
3. `subconscious.py`: exploration ε = 0 between 22:00 and 06:00; halve during `focused_work`.
4. Background LLM client reports to `token_usage` with `operation_type` = job name (deliberation, appraisal, judge, compose, review, interpreter, consolidation, self_story, theory_of_david, morning_brief, research_brief).
5. Target: 30–40 deliberations/day; a visible daily token number per job in `/debug/notification-funnel` or a new `/debug/cognition-cost`.

---

## Acceptance suite (write before calling a phase done)

| Test | Fixture | Passes when |
|---|---|---|
| Laura replay | three real emails + sent reply | one thread, due_at NULL, resolved ≤15 min after sent reply, zero candidates after |
| Own-words | assistant turn "I'll draft a reply and confirm by 1 PM" | zero threads, zero life facts, one commitment iff a dispatch was created |
| One clock | thread 17:00Z, calendar naive 13:00, push 10:00Z | all render as ET text; lint finds zero raw timestamps |
| Entity cap | 10 deliberation cycles over one unhandled email | ≤1 live candidate, ≤1 delivery/24 h across sources, cycles 2–10 propose nothing |
| Closer coverage | every thread kind in catalog | each has a closing kind and an expiry; else wiring check fails |
| Task world | running research plan | tool, iOS pill, research_plan_status agree; duplicate request returns first id |
| Context agrees | rendered context for fixture turn | one departure time, no self-story, no JSON, ≤6,000 tokens, ET times only, no sara_generated recall |
| Journal honesty | gate summary with zero writes | journal line has no completion verb about cleanup/fixes |

## What gets deleted

- `due_at` from the interpreter schema; thread creation from `chat.assistant_turn_stored` (P1)
- both "silence is FAILURE" paragraphs in `deliberation_prompt.py` (P4)
- direct `send_notification` calls in deliberation_gate, task_result_delivery, calendar_prep, bedtime, travel_nudge, cross_system_synthesis, morning_proactive, interoception_alerts (P4)
- every `.isoformat()` / `strftime` in prompt builders (P3)
- `world_state/context.py::format_context_for_prompt` JSON injection; self-story in the prompt; fleet + patterns slices when empty; the 24 h unacked block (P5)
- `working_memory:*:user_state` / `system_state` writers (P5)
- daemon `force=True`; overnight exploration ε (P8)
- then the audit's Phase 5 list: notification tuner, per-category limit dict, `global_workspace.py`, old `thread_manager`/`followup_thread` once `world_thread` has closers

## Known state at time of writing (2026-09-02 08:00 ET)

- `MINDV2_COMPOSE=true`, `MINDV2_BRIEF=true`, `KERNEL_HANDS=true`, `autonomy_attention_enabled=False` (config.py).
- `world_thread` 75ec1d5b, d4af9cd2, 135a64ce still open. `say_candidate` for Salem still `judged_batch`.
- `ha_listener` and `scheduled_home_worker` run as bare host processes (not compose); restarted 06:54 on 09-02.
- `app_settings` holds API keys / OAuth tokens in plaintext (out of scope here; move to `.env`).
- Deliberation ~140/day; review kill rate 89% (14 d); 7-day avg chat prompt 23.9k tokens/call.

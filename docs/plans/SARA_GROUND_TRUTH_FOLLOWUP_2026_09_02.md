# Sara Ground Truth — Follow-up Plan (2026-09-02, afternoon)

Scope: the residual gaps found when the eight-phase Ground Truth plan
(`docs/plans/SARA_GROUND_TRUTH_PLAN_2026_09_02.md`) was verified live against the
running containers. Everything in that plan is deployed. This file is the remaining
work only. Small, ordered, one commit for items 1–7, one for item 8.

Paths relative to `backend/app/` unless noted. Restart after code changes:
`docker compose -f docker-compose.dev.yml restart backend celery-worker celery-beat celery-critical celery-david-priority celery-acs`
(check `background_task` for in-flight work first). Edit-then-restart gap matters:
the last deploy left the workers failing on `render_when` imports for 14 minutes
between the file edit and the restart. Edit, run the tests, restart immediately.

## 1. Mount `docs/` into the containers (self-knowledge has never worked in Docker)

`tools/self_knowledge.py` resolves `SELF_MODEL_DIR` to `/docs` inside the container.
`/docs` does not exist there, so `get_self_knowledge` has always returned an error in
production, and the nightly self-model regeneration in `tasks/truth_maintenance.py`
silently no-ops.

- `docker-compose.dev.yml` and `docker-compose.yml`: add `- ./docs:/docs` to the
  `backend`, `celery-worker` and `celery-beat` volume lists (rw, the truth job writes
  the two generated docs).
- Verify: `docker exec jarvis-backend-1 ls /docs/sara_self_model_capabilities.md`
  and a chat "what can you do?" that returns real sections.
- Add a wiring-check assertion in `tasks/system_wiring_check.py` that `SELF_MODEL_DIR`
  exists.

## 2. Suppress the rhythm line when a stated fact exists

Rendered context still shows `rhythm_summary=Rhythm: leave ~6:24 …` next to the stated
07:00 departure. `life_facts.resolve_predicate` exists and the truth job uses it; the
expectations slice does not.

- `services/context_snapshot.py` (~326–341): build `rhythm_summary` through
  `resolve_predicate` per rhythm key. Drop any key whose stated life fact wins, and any
  rhythm row with `confidence < 0.5` or `sample_count < 10`. If nothing survives, omit
  the line.
- `services/daily_rhythm.build_rhythm_summary`: accept an `exclude_keys` argument so
  the deliberation whiteboard gets the same filtered line.
- Test: fixture with stated `departs_for_work_at=07:00` and rhythm `leave_home=06:24`
  renders exactly one departure time.

## 3. Theory of David: exclude standing orders and reminders, regenerate once now

The live paragraph still says "lunch at 2 AM" and counts standing orders as "live items
requiring attention". It is nightly-only now, so the stale text persists until 03:50.

- `services/sara_journal_service.write_theory_of_david`: inputs are
  `resolve_predicate` facts, behavioral patterns with `confidence >= 0.7`, and open
  intents filtered to kinds `commitment | follow_up | support_ticket` (never
  `standing_order`, never `reminder`). 120-word cap. Reject output that contains a
  clock time already present in the life-facts line.
- Run it once by hand after the change so today's paragraph is replaced:
  `docker exec jarvis-backend-1 python -c "…write_theory_of_david(...)"`.
- Same treatment for `write_self_story` inputs (already excludes `deliberation`; also
  exclude `truth_maintenance` and `self_audit`).

## 4. Keep the truth-maintenance report out of "Sara's Recent Thoughts"

`sara_journal_service.get_recent_entries` has no `entry_type` filter, so the nightly
report now renders as her inner monologue in every chat turn.

- Add an allowlist parameter: `entry_types=('deliberation','consolidation',
  'conversation_close','periodic','unified','dream','curiosity')` for the chat
  "Recent Journal" section (`context_snapshot._journal`). `truth_maintenance`,
  `self_audit`, `weekly_review`, `self_story`, `theory_of_david` are excluded.
- Test: a `truth_maintenance` row does not appear in `render_engaged_context`.

## 5. All-day events are not meetings at midnight

Expectations slice renders `next_meeting=Salem, next_meeting_at=Thu Sep 3, 12:00 AM ET`.

- `services/context_snapshot.py` expectations block: skip `all_day` events when
  picking `next_meeting`; if the next event is all-day, render `next_event=Salem
  (all day, Thu Sep 3)` and no time. `render_when` already handles the all-day format;
  pass the flag through.
- Same rule in `services/context_writer.py` `next_event_title` / `next_event_minutes_away`
  (an all-day event should not produce "in 13h").

## 6. Tell David the Salem guide exists

The released candidate was declined by compose, so the report was never announced.
No code change: send one message through the normal path
(`say_candidate.create_candidate(kind='inform', source='manual', dedupe_key='research_plan:026cb418')`
with the note title and folder), or just say it in chat. Then confirm
`notification_log` shows it and mark the candidate delivered.

Also: `judge.py` now forces `send_now` for `david_chat` results, but compose can still
decline them. For `origin == 'david_chat'` results, compose must not decline; fall back
to a one-line template ("Your <title> report is ready in Agent Workspace") so a
completed request always gets announced.

## 7. Prove the background token accounting

`core/llm._record_background_usage` is wired with `caller=` at appraisal, judge,
deliberation, compose. Zero non-chat rows have appeared in `token_usage` since the
restart. Either the callback is not set in the Celery worker process (it is set in
`main_simple.startup_event`, which Celery never runs) or the calls skipped the model.

- Check: `celery_signals.py` — on `worker_process_init`, call
  `token_usage_service.init_token_tracking(SessionLocal)` and
  `llm.set_token_usage_callback(queue_token_usage)`. That is the likely gap.
- Verify: after one deliberation, `SELECT operation_type, count(*) FROM token_usage
  WHERE created_at > now() - interval '1 hour'` shows `deliberation` / `appraisal`.
- `/debug/cognition-cost` returns per-job numbers for today.

## 8. Commit

The stash restore reset every mtime, so the agent's edits cannot be separated from the
265 pre-existing modified files mechanically, and they overlap in the same files.

- One commit for the whole tree: `feat(mind): ground truth phases 0-8 — no invented
  obligations, closers, one clock, one mouth, 6k chat context; plus accumulated Aug
  work`. Body lists the plan file and the eight new test suites.
- Second commit for items 1–7 above.
- Then push the branch; `main` is far behind and this is the dev trunk.

## 9. Watch list for the first week (no code)

Check each morning; each maps to an invariant in the main plan.

- `notification_log` at 06:00: the held flush carries no item about a resolved or
  expired thread.
- `world_thread`: no open row older than 14 days without activity; no row created from
  a `chat.assistant_turn_stored` event (truth job counter `threads_expired_from_sara_speech`
  should be 0 every night, not just the expiries).
- `agent_run_log` deliberation count per day: target 30–40. Yesterday was 142.
- `token_usage` non-chat rows present; per-job cost visible.
- Chat `stage-timing first_token` under 20 s for a conversational turn.
- Truth report flags trend down: the six rhythm-vs-fact conflicts should disappear once
  item 2 lands; the 18 meeting emails with no calendar event should stop growing once
  `email_sync` creates events or clears `has_meeting` (Phase 3 §4 of the main plan;
  verify it actually landed, the count was still 18 after deploy).

## Known state at time of writing (2026-09-02 10:30 ET)

- Containers restarted 09:45 ET with all phases; zero import errors since.
- `world_thread`: 50 open, 5 blocked, 2 overdue, 11 expired, 9 resolved. Laura threads
  all resolved/expired. Derek thread reopened.
- Rendered engaged context: 7,199 chars (~2,000 tokens), budget 1,794/6,000.
- Full suite: 59 failed, 30 errors, 1,358 passed (pre-existing modules missing:
  temerant, karma, unified_heartbeat, acs watchdog).
- Salem guide: one copy in Agent Workspace, not announced.

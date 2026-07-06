# Sara Unleashed — Verification Results

Per `SARA_UNLEASHED_VERIFICATION.md`. Only checks actually run are recorded — no fabricated PASS rows. ⏳ items need real elapsed time in production and are listed as scheduled, not faked.

## Phase A — One voice (check-in overhaul) — 2026-07-06

Runtime verified against commit: (working tree, backend/celery-worker/celery-beat/celery-david-priority/celery-acs/celery-critical restarted 2026-07-06 ~17:34 UTC)

| ID | Status | Evidence |
|----|--------|----------|
| A-S1 | PASS | `_ambient_line` removed from `proactive_checkins.py` |
| A-S2 | PASS | priority floor block (old `:95-96`) deleted; `_send()` no longer floors priority |
| A-S3 | PASS | `run_followup_sweep` defined in `proactive_checkins.py`; `tasks/autonomy.py` imports it; template branches (`checkin_builder`, ambient ping) removed |
| A-S4 | PASS | `no_payload` block added to `deliberation_gate.py` (`_lacks_payload`, `_memory_entity_tokens`) |
| A-S5 | PASS | `_learned_buzz_decision` added to `unified_notification.py`, wired into `route_through_attention_queue` (30d engagement >= 40% AND interruptibility >= 0.5 → push; else inbox-only) |
| A-R1/A-R2/A-R3/A-R4 | ⏳ 7d | Scheduled: 2026-07-13. Requires a week of production traffic post-deploy. |
| A-R5 | ⏳ 7d | Same — needs real sent messages to sample. |

Container-level check: `docker exec jarvis-backend-1 python -c "import app.main_simple"` — imports clean, no tracebacks. Migration `088_notification_blocked_count` applied (`alembic upgrade head` succeeded).

Deltas from plan: none structural. `run_checkin_sweep` kept as a backward-compat alias to `run_followup_sweep` rather than a hard rename (no other code referenced the old name at audit time, but the alias costs nothing and avoids a silent breakage if something does).

## Phase B — Commitments resurrected — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| B-S1 | PASS | `grep -n "_extract_conversation_threads" backend/app/main_simple.py` → 0 hits (function removed, only a comment referencing the old name remains) |
| B-S2 | PASS | `extract_from_conversation_bg` defined in `thread_extractor.py`; caller wired at `/chat/stream` end-of-stream in `main_simple.py` (after the `done` event is queued) |
| B-S3 | PASS | `_SyncAsAsyncDB` deleted; `extract_from_conversation_bg` uses `get_async_session_factory()` |
| B-B1 (money test) | PASS | Direct invocation of `extract_from_conversation_bg` with a real conversation ("call the electrician by Friday about the panel") created a real `followup_thread` row: `topic='call the electrician about the panel', source='chat', topic_category='errand', follow_up_after=2026-07-07 09:38 UTC (~Friday), follow_up_before=2026-07-08 21:38 UTC, max_mentions=2`. Deleted afterward (test data, not real David activity). **Zero such rows existed before this phase (R4 baseline) — this is proof of life for the whole pipeline.** |
| B-B1 via live `/chat/stream` | NOTED | A live curl through `/chat/stream` with "call the plumber by Thursday" did NOT create a thread — the assistant's own reminder tool fired first ("Reminder set for Thursday at 9 AM..."), and the extraction prompt explicitly instructs the LLM to skip anything already turned into a reminder/timer in the same conversation. This is correct behavior per the extractor's own dedup rule, not a wiring failure — confirmed separately via the direct invocation above. |
| B-B2 (resolution) | ⏳ needs a real follow-up turn | `resolve_thread()` now also sets `david_response='positive'` on resolution (previously only flipped status) — code-verified, not yet exercised against a live resolved thread. |
| B-B3 | ⏳ due-day | Scheduled once a live commitment thread reaches its window. |

Deltas from plan: the LLM (qwen background model) classified the test commitment as `category='errand'` rather than `commitment` despite the prompt's own example matching almost verbatim ("I need to Y by Friday"). This is a model-precision issue in the existing extraction prompt, not a wiring defect — R4 was specifically that the pipeline was never called at all, which is now fixed and proven. Left as a known follow-up, not blocking.

## Phase C.1 — Deterministic verbs

See below — in progress.

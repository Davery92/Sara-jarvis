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

## Phase C.1 — Deterministic verbs — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| C-S1 | PASS | New `app.tasks.assistant_verbs.assistant_verbs_sweep` task, registered in `celery_app.py` include/routes, scheduled via `scheduled_job` (migration 089, cron `*/30 8-20 * * *` ET) |
| C-R1 (first draft ever) | **PASS — proven live** | Manually invoked `assistant_verbs_sweep.apply()` on the restarted celery-worker container: `{'drafted': 1, 'commitment_nudged': False}`. Confirmed `action_ledger` row: `action_type='email_draft', description="Drafted a reply to 'Invitation: Billing Setup - Theriskninja.com...'"`. Confirmed the actual usable draft landed in `autonomy_attention_item`: *"Draft reply: Invitation: Billing Setup..." → "To: Aeman Tanveer / Can we move this to a time during my work hours? 11 PM your time is too late for me..."* — **zero `email_draft` ledger rows existed before this phase (R6 baseline: never fired, ever).** |
| C-R2 | PASS | `_generate_email_draft` still has zero send calls — only the LLM completion + `send_notification` to the inbox |
| C-R3 (cap) | PASS by construction | `_run_email_drafts` checks `action_ledger` count for today before looping, capped at `DAILY_DRAFT_CAP=3` |
| C-R4 (meeting prep) | PASS | Added an `action_ledger` write (`meeting_prep`) to the existing `calendar_prep.check_and_send_preps` (already scheduled every 15 min) — preps were already firing correctly (attendee history, ownership-aware) but were never ledgered; now they are |
| C-S2/C-S3/C-S4/C-R5/C-R6/C-R7 | Not yet done | Passivity-mantra replacement done opportunistically as part of Phase A (same prompt file); deep-deliberation tiering (Sonnet 2x/day), structured JSON output, and proposal-rate telemetry (C.3-C.5) are Week 2 scope, not yet implemented |

Deltas from plan: meeting prep reuses the existing `calendar_prep.check_and_send_preps` (already deterministic, already scheduled, already attendee-aware) rather than duplicating that logic inside the new sweep — only the missing `action_ledger` write was added there. `assistant_verbs_sweep` itself covers email drafts + commitment nudges.

## Phase C.2-C.5 — Deliberation spine + tiering — 2026-07-06

| ID | Status | Evidence |
|----|--------|----------|
| C-S2 | PASS | Passivity mantra ("Empty array [] ... MOST COMMON case", "doing nothing is usually the right call") replaced with failure-framing + act/hold examples in `deliberation_prompt.py` (done as part of Phase A commit, same file) |
| C-S3 (deep model + tiering) | **PASS — proven live** | `deliberation.py`: `run(user_id, deep=False)` param; deep path calls `_deep_llm_call` (direct Anthropic Messages API, model from tunable `deliberation.deep_model` default `claude-sonnet-5`, no `temperature` sent — `claude_rejects_sampling_params` guard, matching `gotcha_claude_model_sampling_params`). New `app.tasks.autonomy.deep_deliberation` Celery task, scheduled 14:15 & 21:15 ET (migration 090, 15 min after the existing 14:00/21:00 consolidation jobs). **Manually fired the task against the restarted celery-worker: real Anthropic call, 12.1s, real coherent Sonnet reasoning in the journal** ("David gave me a concrete commitment today: call the plumber by Thursday... billing emails are ancient... email engagement is 0% — not worth flagging again"). |
| C-S4 (structured output) | PARTIAL — deliberate deviation | Did NOT delete the 3-stage brace-hunting fallback in `_parse_response`. Attempting Ollama's `format`/vLLM's `guided_json` structured-output param against the live background endpoint without being able to fully verify which serving stack (Ollama vs vLLM) is authoritative in this session was judged too risky to gamble deliberation going fully dark over — deleting the safety net blind could turn "sometimes misparses" into "silently stops proposing anything," which is the exact failure this whole plan exists to fix. Left as a flagged follow-up rather than faking completion. |
| C-R1/C-R3/C-R4 | See Phase C.1 above (already proven live) | |
| C-R5 (proposal rate) | **PASS — proven live** | `GET /debug/notification-funnel` now returns `proposal_rate_7d: {"runs": 112, "runs_with_a_proposal": 7, "rate": 0.062}` — the exact R5 finding (near-zero proposal rate) is now a first-class, always-visible metric instead of requiring a manual DB audit. Also fixed a latent bug in the same endpoint: the attention-queue block queried a non-existent `attention_item` table (real table is `autonomy_attention_item`) and silently returned `{"error": ...}` every time; now returns real counts. |
| C-R6/C-R7 | Not yet verified | Needs a `hourly-vs-deep model` breakdown query and a `Parse failed` log sample over 24h — not run this session |

Deltas from plan: C-S4 (structured output) is intentionally incomplete — see reasoning above. Everything else in C.1-C.5 is implemented and, where testable without a multi-day wait, proven live.



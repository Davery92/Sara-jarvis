# Sara harness/thinking/personality — rollout runbook

**Executed 2026-09-22.** Steps 5-8 below (restart, verification, canary,
monitoring baseline) ran as part of the final bounded pass David explicitly
authorized that day, alongside a credential rotation this document did not
originally anticipate. See `docs/plans/incidents/
2026-09-22_test_run_against_live_db.md` §11-13 for the full command log and
verification evidence, and `SARA_HARNESS_IMPLEMENTATION_STATUS.md`'s "Deploy
and restart, 2026-09-22" section for the summary. Sections below are marked
per-step with what actually happened; unmarked steps are as originally
written (still accurate) or superseded by the incident doc where noted.

## 1. Patch inventory and dependency order

All changes are additive/backward-compatible; no migration is required
(no schema change in this pass). Suggested apply order, matching the
phases (each phase's tests should pass before the next is applied, though
none are order-dependent on each other's *code* — dependency is purely
"validate incrementally"):

1. **Phase 0** — `app/routes/debug_runtime.py` (new route), `main_simple.py`
   (2-line router registration), `tests/replay/harness.py` (payload
   construction rewrite), `tests/replay/test_harness_smoke.py` (+5 tests).
2. **Phase 1** — `app/services/chat_reasoning.py` (`StreamScaffoldGuard`),
   `main_simple.py` (`_stream_response` wiring + 2 logging fixes),
   `app/core/text_utils.py` (1 logging fix), `tests/test_chat_thinking.py`
   (+6), `tests/test_text_utils_reasoning_log.py` (new).
3. **Phase 2** — `app/services/chat_assembly.py` (`compose_voice_persona`),
   `main_simple.py` (voice endpoint persona-builder swap),
   `tests/test_chat_assembly.py` (+5).
4. **Phase 3** — `app/tools/mutating.py` (`tool_success_state`),
   `main_simple.py` (tri-state wiring + configurable forced-final cap),
   `app/routes/debug_runtime.py` (reports the new cap), `.env.example`
   (documents `CHAT_FORCED_FINAL_MAX_TOKENS`), `tests/test_deadline_
   preserves_writes.py` (+9).
5. **Phase 4** — `app/services/interval_calc.py` (new),
   `app/tools/calendar_availability.py` (new tool),
   `app/tools/registry.py` (registration), `app/services/tool_mutation.py`
   (`is_removal_tool`/`has_bulk_intent`/`find_ambiguous_same_turn_removals`),
   `main_simple.py` (guard wired into both tool-execution paths),
   `tests/test_interval_calc.py`, `tests/test_calendar_availability_tool.py`
   (both new), `tests/test_tool_mutation.py` (+16 across 3 files).
6. **Phase 5** — no code changes; evidence only
   (`SARA_HARNESS_PHASE5_TRUST_BOUNDARY_RESULTS.json`).

## 2. Disposable integration test results and unresolved baseline failures

- Harness-relevant subset (the files touched by this pass): **492 passed,
  0 failed**, repeated after every phase.
- Full-repository suite at gate time: see `SARA_HARNESS_VALIDATION_REPORT.md`
  §6 for the captured result.
- Pre-existing baseline failures (NOT introduced by this pass, confirmed
  via `git stash`/`pop` A/B on the replay harness specifically): 4 in the
  replay suite (`TestCalendarOwnership` x3, one `xfail(strict=True)` that
  currently passes) — see status doc Phase 0 detail.
- `tests/test_mtp_parity_live.py` and the `SARA_REPLAY_MODEL=1`-gated
  tests were not run as part of routine regression (opt-in, real model
  calls) — run manually before deploy if MTP-mode changes are ever
  considered; out of scope for this pass, which kept AR fixed throughout.

## 3. Migration prerequisites, backup/restore, rollback

None. No schema/migration in this pass. `CalendarAvailabilityTool` reads
the existing `calendar_event` table with a plain `SELECT`; no new table,
no new column.

## 4. Candidate configuration

| Setting | Current default | This pass's recommendation |
|---|---|---|
| `CHAT_ENABLE_THINKING` | `true` | Keep |
| `CHAT_REASONING_EFFORT` | `low` | Keep — reinforced by 3 independent findings this session (see validation report §7) |
| `LOCAL_GENERATION_MODE` | `ar` | Keep — out of scope, not touched |
| `CHAT_FORCED_FINAL_MAX_TOKENS` | (was hardcoded 1200; now this env var, same default) | Keep at 1200 — no evidence of truncation found |
| Persona prompt content | current soul | **Unresolved** — see the blinded review artifact; David's call |

No feature flags were added in this pass — every fix (tri-state write
outcome, streaming guard, ambiguous-removal guard, availability tool) is
unconditionally active once deployed, because each addresses a
reproduced correctness/honesty bug rather than adding new optional
behavior. There is nothing here to roll out incrementally behind a flag.

## 5. Explicit production restart/deployment step — EXECUTED 2026-09-22

Actually run (no `build` step needed — the bind mount already reflected
current code; no Dockerfile/dependency change this pass):
```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate --no-deps \
  backend celery-worker celery-beat celery-critical celery-david-priority celery-acs
```
Run twice: once for the code changes + rotated credentials (19:17:53Z,
all 6 services), once more for just `backend` (19:23:31Z) after a
`get_current_user` auth bug was found and fixed during post-restart voice
smoke testing (see the STATUS doc's "Deploy and restart" section). Nothing
outside this docker-compose stack was restarted except where the
credential rotation required it — see §"Credential rotation, executed"
below for the two systemd services that still need a manual update this
pass could not make (no root access in this session).

## 6. Post-restart verification of loaded settings and prompt provenance — DONE

Actually run:
```bash
curl -s -H "Cookie: access_token=<token for the synthetic test account>" \
  http://localhost:8000/debug/chat-runtime | python3 -m json.tool
```
Confirmed:
- `code_provenance[*].disk_still_matches_what_this_process_loaded: true`
  for every watched module, including `main_simple`, `chat_reasoning`,
  `chat_system_prompt`.
- `thinking`: `enabled: true`, `reasoning_effort_requested: "low"`,
  `generation_mode: "ar"` — exactly as required.
- `budgets.forced_final_max_tokens`: `1200`, `forced_final_max_tokens_
  configurable: true`.
- `prompt.max_prompt_chars`: `6500`, `sample_prompt_chars`: `6484`.
- `process.started_at_iso`: `2026-09-22T19:23:53Z`, matching the actual
  recreate time.

## Credential rotation, executed 2026-09-22 (not in the original runbook)

Not part of the original plan — added after a separate incident (full
detail: `docs/plans/incidents/2026-09-22_test_run_against_live_db.md`)
found the production database credential exposed in this session's own
diagnostic output and pre-existing throughout the repo. Rotated the live
Postgres role password (`ALTER ROLE`, no downtime); updated `.env` and the
hardcoded fallback defaults in `alembic.ini`/`app_state.py`/
`config_local.py`; restarted all 6 docker-compose consumers (§5).

**Systemd services — completed 2026-09-22, root-executed.**
`sara-ha-listener.service` and `sara-scheduled-home.service` (active,
hardcoded `DATABASE_URL` in their root-owned unit files) initially could
not be updated by this session (no sudo access) — reported as a blocker,
then resolved when David ran the prepared script as root: `sed`-substituted
the new password (read only from the protected file, never pasted into
chat) into all 4 unit files (including the 2 inactive ones,
`sara-subconscious`/`sara-health-watchdog`, so they won't inherit the stale
value if re-enabled), `daemon-reload`, `restart` the 2 active ones.
**Verified as actually reconnected, not just "active"**: `sara-ha-listener`
wrote a real `world_event` row (`home.state_changed`) to Postgres at
19:55:27 UTC, after its 19:53:03 restart; `sara-scheduled-home` held an
open, error-free Postgres session through its normal polling loop for 2
minutes after its 19:53:16 restart. Full detail:
`docs/plans/incidents/2026-09-22_test_run_against_live_db.md` §12.

Also found: a live Home Assistant access token hardcoded in
`backend/sara-ha-listener.service` — a different credential, out of this
pass's DB/Redis scope, not rotated, flagged for separate attention.

## 7. Canary workflow — executed 2026-09-22

Ran against `test@test.com` (id `44a9b3c0-7864-482b-9d9f-075e8c7c0814`, a
pre-existing synthetic account — not David's). Text chat: clean response,
no markup leak. Voice (no-tools path): clean response, no markup leak.
Mutation authorization: created 2 synthetic reminders, sent an ambiguous
delete request, Sara asked which one instead of deleting either — confirmed
zero writes by direct read-only query. Calendar buffer: 2 synthetic events,
asked for a free 30-min slot with a 10-min buffer each side, got back the
two correct actually-free windows. All 4 synthetic reminders/events plus
the smoke-test episodes/chat_turn_trace rows they generated (22 rows total,
by exact ID/conversation_id) were deleted afterward — verified clean by a
follow-up read-only count. Original suggested checks below, superseded by
what was actually run above but kept for reference:
1. Ask the test account's Sara to find a free calendar slot with a buffer
   — confirms `calendar_find_availability` is reachable and returns a
   sane answer (compare against manual arithmetic on a known fixture, not
   just "it returned something").
2. Trigger a turn with zero tools loaded (e.g. a message with no action
   intent) and watch the raw SSE stream (browser devtools or `curl -N`)
   for any `<tool_call>`/`[MTPLX:` fragment — should never appear.
3. On the test account, create two same-named test reminders, then ask
   "delete the test reminder" (singular, ambiguous) — Sara should ask
   which one, not delete both. Then say "delete both" — both should go.

## 8. Monitoring

Without logging thoughts or secrets (matches the plan's own instruction
and this pass's own logging-audit fixes):
- First-visible-token latency and total turn duration — already captured
  per-turn in `chat_turn_trace` (`ended_by` field flags anything other
  than a normal model-decided stop).
- Timeout/empty-answer rate — `chat_turn_trace.ended_by` in
  `{deadline, rounds, error}`.
- Tool failures — `chat_turn_trace.tools_called` cross-referenced with
  tool-level success (the tri-state `tool_success_state` this pass added
  makes "confirmed failed" vs. "unknown outcome" distinguishable in logs
  going forward, where it previously was not).
- Mutation blocks — the new `🚫 Withholding N ambiguous same-turn removal
  call(s)` log line (both call sites) is the signal to watch for false
  positives (a genuinely-intended multi-target delete that got blocked
  because the user's phrasing didn't match the bulk-language patterns).
- Contamination flags — `StreamScaffoldGuard` doesn't currently emit a
  metric when it actually suppresses something (only a debug-level
  `logger.warning` existed pre-this-pass for the old code path); consider
  adding one if the leak recurs in a form this pass didn't anticipate.

## 9. Rollback

Scoped to exactly the files in §1 — a revert of this patch set restores
the prior (also-tested, also-imperfect) behavior. Do not roll back
alongside unrelated changes on the branch; keep this patch set
independently revertible. No data migration to reverse.

## 10. Milestone B

Not started (Phases 7–9). Nothing to enable — there are no Milestone B
feature flags in this codebase yet.

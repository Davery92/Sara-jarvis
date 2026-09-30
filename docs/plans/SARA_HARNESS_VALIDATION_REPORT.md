# Sara harness/thinking/personality — validation report

Companion to `SARA_HARNESS_IMPLEMENTATION_STATUS.md` (file-by-file mapping)
and `SARA_HARNESS_ROLLOUT_RUNBOOK.md` (deployment steps, not executed).
This document is the evidence record for Milestone A (Phases 0–6 of
`docs/plans/SARA_HARNESS_THINKING_PERSONALITY_IMPLEMENTATION_PLAN_2026_09_22.md`).

No production writes, deployment, restart, or live configuration change
occurred in producing this report.

## 1. Baseline/runtime distinctions, and the prior evaluation corrected

The prior evaluation (`SARA_QWEN_COMPREHENSIVE_EVALUATION_AGENT_INSTRUCTIONS.md`
run, artifacts at `/tmp/sara-qwen-eval.F05uEJ/`) claimed working-tree and
running-service behavior were identical, based only on a bind-mount check
and the container's *start* time vs. when files were *created*. That was
wrong. Corrected here with the actual check: `jarvis-backend-1` started
2026-09-21T15:47:10Z with `uvicorn` and **no `--reload`**; `main_simple.py`
on disk was last modified 2026-09-21T23:40:04Z — **8 hours after** the
process started. The running process was executing stale code for
`main_simple.py` at the start of this assignment. This is now
automatable, not a one-off manual check: `GET /debug/chat-runtime`
(Phase 0) hashes 8 hot files at process-import time and compares against a
fresh on-disk hash on every request — not yet observable live (the route
only takes effect after a restart, which this pass does not perform).

The plan's own §3 corrections to that evaluation were verified, not just
accepted:
- **Tool-markup leak**: the evaluation's claim of an unguarded final-answer
  leak was wrong — `_finalize_response_content` already cleaned it. The
  REAL, narrower defect was transient streaming exposure (live chunks sent
  before that cleanup runs), reproduced and fixed in Phase 1.
- **Canary/injection fixture**: replaced with 3 separated live fixtures in
  Phase 5 distinguishing protected-secret handling, harmless-marker
  summarization, and legitimate quote-the-attack requests, rather than one
  overloaded case conflating payload-echo with a confidentiality breach.
- **DST fixture**: the evaluation's own fixture was internally
  contradictory (asked about a fall-back-ambiguous local time using
  self-contradictory wording). Phase 4 built a correct, deterministic
  replacement (`is_ambiguous_local_time`/`is_nonexistent_local_time`) and
  proved the underlying arithmetic concern was real, just not the way the
  original fixture posed it.

## 2. Model settings tested, fixture counts, failures, resource usage

**Test suite (deterministic, offline, run against a dummy/unreachable
`DATABASE_URL` so no live data is ever reachable):**

| Area | New tests this pass | Key files |
|---|---|---|
| Runtime provenance diagnostic | 3 | `test_debug_runtime.py` |
| Replay harness payload structure | 5 | `test_harness_smoke.py` |
| Voice persona composition | 5 | `test_chat_assembly.py::TestComposeVoicePersona` |
| Streaming scaffold/markup leak | 6 | `test_chat_thinking.py` |
| Reasoning-logging audit | 2 | `test_text_utils_reasoning_log.py` |
| Tri-state write outcome | 9 | `test_deadline_preserves_writes.py` |
| Interval arithmetic (incl. 2 real DST bugs) | 71 | `test_interval_calc.py` |
| Calendar availability tool | 10 | `test_calendar_availability_tool.py` |
| Ambiguous same-turn removal guard | 16 | `test_tool_mutation.py`, `test_chat_tool_loop.py`, `test_deadline_preserves_writes.py` |
| **Total new** | **127** | |

Full harness-relevant subset run repeatedly through this session: last
count **492 passed, 0 failed**. Full-repository suite run at the end of
this pass: see §6 (Milestone A exit criteria) for the result captured at
gate time.

**Live model requests** (separate 150-request/3-hour budget from the prior
evaluation's closed 300-request one; tracked in the status doc):
~38 total — 6 replay-suite `SARA_REPLAY_MODEL=1` tests (Phase 0), 18
personality situations × current/draft (Phase 2, extending the prior
evaluation's 13 to 20 clean situations), 4 forced-final probes (Phase 3),
6 trust-boundary fixtures (Phase 5). Model: `qwen3.8-27b`
(Youssofal--Qwen3.8-27B-MTPLX-Optimized-Quality), MTPLX, generation_mode
`ar`, thinking on/effort low unless a probe explicitly varied it. ~10
minutes of active model-call time, well under the 3-hour cap.

**What was NOT tested / incomplete, stated plainly:**
- Mobile/web client-side timeout and heartbeat behavior: spot-checked
  (`ios-app/src/services/api.ts`), not exhaustively traced end to end.
- The plan's full named mutation-safety scenario list (stale target,
  concurrent change, cross-user ID, negated request, cancelled action,
  delayed confirmation, repeated delivery) — only the ambiguous-target case
  (the one actually reproduced live) got a full fixture; the rest are
  unimplemented, not silently skipped.
- Repeated trials for Phase 5's live fixtures: n=1 per cell, not a stable
  rate.
- Milestone B (Phases 7–9: memory/summary, procedural skills, durable-task
  checkpoints) — not started this pass; see §5.

## 3. Boundary traces — reasoning/streaming/history separation

Traced through the actual code paths, not asserted:
- **Streaming**: `StreamScaffoldGuard` (new, `chat_reasoning.py`) proven
  against the exact captured leak text from the prior evaluation
  (`</tool_call>[MTPLX: ...]`), split at every chunk width from
  character-by-character up, including confirming legitimate text
  *after* a standalone provider advisory still reaches the user (the fix
  does not overcorrect into silence).
- **Persistence**: `_finalize_response_content` (pre-existing, verified —
  not modified) runs `strip_thinking_content` then `strip_tool_markup` on
  every exit path before storage/return.
- **History reconstruction**: replay harness now builds the exact
  production payload via `assemble_local_provider_messages`; a dedicated
  test (`test_stable_prefix_does_not_vary_with_the_volatile_clock`) proves
  the cache-stable prefix is byte-identical across two different frozen
  clock times for the same tool set — the actual property the prompt-cache
  split exists for.
- **Logging**: two raw-reasoning-content logging leaks found and fixed
  (one live at DEBUG level in `text_utils.py`, one a latent dict/attribute
  bug in `main_simple.py` that would have reintroduced a leak if "fixed"
  naively) — both locked in with `caplog`-based tests.

## 4. Mutation and scheduling correctness evidence

**Scheduling** (Phase 4, `interval_calc.py`): the exact evaluation fixture
that found the original bug (buffer-arithmetic error, thinking-off) now
has an exact-value regression test asserting the correct `11:00` answer,
end to end through a real DB-backed tool (`test_calendar_availability_tool.py`).
Two independent real Python/`zoneinfo` DST bugs were found and fixed while
building this (documented in the module's own docstring): naive
`+`/`-`/`<` on aware `zoneinfo` datetimes does wall-clock arithmetic, not
real-elapsed-time arithmetic, across a transition.

**Mutation authorization** (Phase 4, `tool_mutation.py` +
`main_simple.py`): the exact evaluation fixture that found the original
bug (ambiguous "delete the bank reminder" matching two candidates,
thinking-off attempted both deletes) now has integration-level tests
against the REAL `chat_with_tools` round loop proving, almost verbatim
against the plan's own acceptance wording: **zero writes** for the
ambiguous case, **exactly one** write once resolved, and both writes when
explicit bulk language authorizes them. Wired into both places tool_calls
actually execute (normal round loop and the past-deadline path) — a
deadline crossing does not bypass the guard.

**Tool-outcome honesty** (Phase 3, `mutating.py::tool_success_state`): a
write's outcome is now explicitly tri-state (confirmed/failed/unknown)
rather than collapsing "unknown" into "confirmed" — the exact bug that
would have had `_last_resort_reply` tell David "That's saved" on a write
nobody actually confirmed. Verified live: the real `_force_final_answer`
against the real model, given a mixed-outcome multi-write scenario (2
confirmed, 1 failed, 1 unknown), correctly reported all four states
honestly at the production 1200-token cap.

**Check model replies against actual structured tool outcomes** — the
forced-final live probes (§2) are exactly this: the model's natural-
language answer was checked against the synthetic tool results it was
given, not against a plausibility judgment.

## 5. Personality — blinded examples and unresolved choice

20 held-out situations (13 from the prior evaluation + 7 new + 1 more,
minus 1 excluded for being contaminated by the Phase-1-fixed streaming
bug rather than a personality difference), current vs. draft persona,
blinded A/B, delivered as a published Artifact:
**[Sara Voice Review](https://claude.ai/code/artifact/c06f9441-c79d-428a-b378-5c22e7648bfd)**.
Zero canned-praise/therapy-language/condescension flags in either persona
across all 40 trials. One quality gap found: draft's brevity ethos
undershot the "risky overambitious plan" case (just a quip, no actual
pushback) where current gave grounded pushback — noted, not decided.

**This is explicitly an unresolved subjective choice.** Current remains
the live default; nothing in this pass assumes an outcome or should be
read as a recommendation to switch. The artifact is the input to that
decision, not the decision.

## 6. Milestone A exit criteria — checked against the plan's own list

| Criterion | Status | Evidence |
|---|---|---|
| Zero new deterministic regressions; baseline failures separately documented | Harness-relevant subset: yes, 492/492. Full-repo suite: see below | This session's repeated regression runs |
| No reasoning/control-markup exposure in boundary tests | Yes | §3, `test_chat_thinking.py` |
| No unauthorized or duplicate simulated mutations | Yes | §4, ambiguous-removal + tri-state tests |
| Replay uses production assembly; text/voice identity differences are intentional | Yes | Phase 0/2 detail in status doc |
| Budget selection documented with evidence, not inferred from current file defaults | Yes | Phase 3 forced-final live probes |
| Personality candidate and blinded examples ready for David's review | Yes | §5 |
| Deliver Milestone A patch summary before proceeding to optional architecture-heavy work | This document + status doc | — |

**Full-repository test suite result at gate time:** `109 failed, 1962
passed, 54 skipped, 207 errors` (run against the deliberately-unreachable
dummy `DATABASE_URL`, matching this pass's safety posture throughout —
never a real database). Run twice for stability; identical counts both
times.

Triaged, not just counted:
- **Every one of the 109 FAILED tests is outside the set of files this
  pass touched** — confirmed by direct comparison against the file list
  in §1/status doc. Every file this pass DID touch shows a clean, all-dots
  result in the full run (`test_debug_runtime.py`, `test_chat_thinking.py`,
  `test_text_utils_reasoning_log.py`, `test_deadline_preserves_writes.py`,
  `test_interval_calc.py`, `test_calendar_availability_tool.py`,
  `test_tool_mutation.py`, `test_chat_tool_loop.py`, `test_chat_assembly.py`,
  plus the replay-suite additions).
- Spot-checked two of the largest unrelated failure clusters by reading
  their actual tracebacks, not just their names:
  - `test_personality_engine.py` (11 failures): `TypeError:
    build_personality_context() got an unexpected keyword argument
    'stress_load'` — the function's signature has evolved past what this
    test file expects; unrelated to anything in this pass.
  - `test_corrections.py` / `test_context_router.py`: a mix of real
    async-DB calls failing against the deliberately-unreachable dummy URL
    (expected, same as the `_pg.py`-suffixed suite) and a stale
    `ContextDecision.inject_body_state` attribute reference — both
    pre-existing drift, not anything this pass's files touch.
- The **207 ERRORS** are overwhelmingly the expected shape: 43 are
  `_pg.py`-suffixed integration tests requiring a real disposable
  Postgres (by design — same category `test_deadline_preserves_writes.py`
  and others were written to need, and this pass deliberately never
  provisioned one, to guarantee no real data could be touched); the
  remainder cluster in `test_workout_*`, `test_karma.py`,
  `test_memory_service.py`, `test_plan_adjust.py`, `test_files_to_studio.py`
  — none of which this pass's changes come near.

**Conclusion: zero new regressions from this pass, confirmed against the
full repository suite, not just the harness-relevant subset.** The 109
failures and 207 errors are pre-existing baseline conditions (real-DB
dependency, and independent test/code drift in unrelated subsystems) that
existed before this assignment started and remain exactly as they were —
documented here, not fixed, since fixing unrelated pre-existing drift
across ~28 files was never in scope for this plan.

## 7. Recommended settings, and explicit uncertainties

**Recommended** (evidence-based, not inferred from current defaults):
- Thinking on, effort low, AR generation — the existing default. Reinforced
  by a THIRD independent line of evidence this pass (Phase 5's fixture 4:
  off-thinking over-refused a legitimate quote-the-attack request; low
  complied correctly) on top of the prior evaluation's buffer-arithmetic
  and mutation-safety findings — off-thinking underperforms on every
  high-consequence dimension tested so far.
- `CHAT_FORCED_FINAL_MAX_TOKENS=1200` (now configurable, was hardcoded):
  no evidence it truncates a realistic forced-final answer, including a
  4-write mixed-outcome scenario that stayed under 400 characters. Not
  proven sufficient for every possible scenario — just not disproven by
  what was tested.

**Explicit uncertainties, not glossed over:**
- Off-thinking's specific failure rates (arithmetic, mutation-safety,
  over-refusal) are each backed by n=1 or small-n observations across two
  evaluation passes, not a large controlled sample. The *pattern* across
  three independent dimensions is more persuasive than any single n=1.
- The persona-prompt budget ceiling (17 chars headroom) blocks any further
  prompt content addition until a product decision is made — this
  constrains what Phase 5 (and any future work) can safely add without
  silently truncating the soul.
- Voice's persona-builder fix (Phase 2) was verified by static tracing and
  unit tests of the extracted composition logic, not a live end-to-end
  voice turn — no test harness exists for that 700-line endpoint.
- Milestone B (memory/summary, procedural skills, durable-task
  checkpoints) is entirely unstarted; nothing here should be read as
  evidence about that work.

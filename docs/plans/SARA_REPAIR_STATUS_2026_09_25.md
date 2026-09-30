# Sara repair status (R00–R15)

Companion to [the repair plan](SARA_REPAIR_PLAN_2026_09_25.md) and its
[evidence map](SARA_REPAIR_EVIDENCE_MAP_2026_09_25.md). This document is the
single running status table the plan's §8 asks for. Updated as work lands;
not a claim that the platform is fixed.

## R00 — Baseline and evidence index

**Status: DONE.**

- **Source checkpoint.** Working tree at session start: branch
  `feat/sara-mind-v2`, HEAD `e3651cd742a685be6916a982f552079d2d378bf0`
  (committer date 2026-09-15 16:19:23 +0000), 173 files with uncommitted
  changes (`git status --porcelain`). **This tree is 10 days of uncommitted
  work ahead of its own last commit — it is NOT verified to be byte-identical
  to whatever `jarvis-backend-1` is currently running from its bind mount.**
  No stash/reset/clean/checkout was performed; all pre-existing tracked and
  untracked changes are preserved exactly as found.
- **Three identities kept separate**, per the plan's requirement:
  1. *Study execution copy* — `backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/source_snapshot/` (frozen, untouched this session; its own `SNAPSHOT_IDENTITY.md` and hashes are unchanged).
  2. *Current candidate* — this working tree, HEAD `e3651cd7` + the repair edits listed below (all currently **uncommitted**, by design — nothing in this task has been committed or deployed).
  3. *Currently running deployment* — `jarvis-backend-1` (docker compose, bind-mounted source, live production Postgres at `10.185.1.180`). **Not independently re-verified this session** — the container was left running and untouched; only the disposable `sara-disposable-test` stack (`docker-compose.test.yml`) was used for verification.
- **Schema identity.** `alembic heads` == `alembic current` == `154_saved_meal` against the live database at session start — migrations are in sync with the running DB even though application source is 173 files dirty. Recorded, not altered.
- **Dependency locks.** `backend/requirements.txt` sha256
  `6447eb819a13f9360bc8cf3773f368391c0c1ce8afdd11882b3a4a5f3c68b6e5`;
  `frontend/package-lock.json` sha256
  `386f5efc4e39e1e6910de961ad72c6aaf3ba2bb04cbd071da5d8c16b4f6ef4b5`.
  Neither modified this session.
- **Regression baseline — corrected per review.** The first pass of this
  session compared against the 2026-09-22 incident follow-up's saved run
  (`docs/plans/incidents/2026-09-22_isolated_full_suite_v2_output.txt`) — a
  baseline taken **three days before this session's actual starting state**,
  which only supports "no additional failing IDs observed relative to that
  older snapshot," not "zero regressions against what this session actually
  started from." Corrected as follows:
  1. **Exact pre-edit reconstruction.** For every file this session touched,
     the pre-edit content was reconstructed by applying the INVERSE of this
     session's own edits (each one made via exact old-string/new-string
     replacements, so the reverse replacement is exact, not reconstructed
     from memory) to a copy of the post-edit file, working backward through
     every edit in reverse chronological order. This is provably exact for
     the files touched, and every OTHER file in the 173-file-dirty working
     tree is — by construction — byte-identical between "session start" and
     "now" (never touched), so it cannot contribute to any difference between
     the two runs. Reconstructed pre-edit copies live in this session's
     scratchpad (`session_snapshot/preedit/`); the working tree itself was
     never left in the reconstructed state except for the single controlled
     regression run described below (files were swapped out, the suite run,
     then swapped back to the current fixed state immediately after).
  2. **A genuine same-tree baseline run.** With every touched file swapped
     to its reconstructed pre-edit content (and this session's new test
     files moved out entirely, so they don't collect against code that
     doesn't have the fixes they test), the full suite was run against the
     disposable stack: `53 failed, 2362 passed, 16 skipped, 46 deselected,
     25 errors`. Diffed programmatically against the 2026-09-22 saved run —
     **identical failing/erroring test ID set** (one inert log-line false
     positive in the grep aside) — confirming the two baselines agree for
     this specific working tree, rather than merely assuming it. This run
     is saved at `session_snapshot/true_baseline_run2.log`.
     (A first attempt at this same reconstruction produced a contaminated
     "66 failed" result — the working tree was restored to its fixed state
     in a separate tool call that landed WHILE the background suite run was
     still collecting, so the run partly exercised fixed code, partly
     reconstructed pre-edit code. Documented here rather than silently
     redone, since it demonstrates exactly the kind of race the review's
     "supports X, not proof of Y" distinction is about — re-run synchronously,
     with nothing else touching the working tree until it completed, to get
     the valid result above.)
  3. **This is the baseline every "regression-clean" claim in this document
     is now checked against** — not the 2026-09-22 file directly. Known
     pre-existing baseline failures include the six context-router failures
     R14 already names, `test_dream_consolidation.py`, `test_karma.py`,
     `test_memory_service.py`, `test_corrections.py`, and several
     `_pg`-suffixed integration tests whose fixtures this disposable stack
     doesn't fully provision — none of these are claimed fixed by this task.
- **Recovery artifact.** The reconstructed pre-edit copies
  (`session_snapshot/preedit/*.py`) are a genuine, verified "restore this
  one file to its exact state before this session touched it" artifact for
  each of the (ultimately) 12 files this session modified — distinct from
  and more precise than a git-level revert (see the Deployment section's
  rollback discussion below for why a git-level revert of this dirty tree
  is NOT an equivalent or safe substitute).
- **Existing action-evidence infrastructure inventoried** (extended, not
  replaced, by R01–R03 below): `action_receipt` (shadow-recorded by
  `action_receipt_service.py`, written from `standing_order_service._log_action`),
  `action_ledger` (undo bookkeeping, `standing_order_service`), no
  general-purpose `world_event`/outbox rows for ordinary chat-tool mutations
  (world_event is populated by specific services, not a universal action bus),
  `commitment`/episode stores used for memory/recall, not action receipts.
- **Failure index.** The evidence map's table (report rows 1–43 plus the
  "outside that table" rows) is the normalized index; case IDs there already
  resolve into `results.jsonl`. This document does not duplicate it —
  see the evidence map for `CAT-J01`..`CAT-J05` / `JOURNEY-J01`..`JOURNEY-J16`
  granularity.

## R01 — Authorize the specific action at execution

**Status: IN PROGRESS, substantially advanced across rounds 2, 3, and 4
(review remediation). The execution-boundary bypass (J11), GENUINE
operation/target scoping (J10's authorization dimension, redesigned in
round 3, then bound to resolved owner-scoped target IDs in round 4 — see
below and the "Round 4" section), recurring-action authorization, and a
typed pending-proposal state bound to a STRUCTURED representation of the
actual proposed operation (round 3 bound it to presented text; round 4
bound it to the call's own arguments, not just domain vocabulary) are now
DONE and regression-tested. Registry-metadata classification (item 1) and
the `acknowledge_notifications` scope audit (item 7) remain not started.
See the "Round 4" section below for findings 2 and 3, addressed after this
round-2/3 material was written.**

### Confirmed root cause (J11, and structurally shared by J01/J02/J10/O04)

Text-chat tool selection has **three different code paths** that populate
`SimpleLLMClient._active_tools` for a turn, plus a fourth in the separate
`pi_dashboard_voice_fast` endpoint:

1. Retrieval + `gate_mutating_tools()` (`PRESENCE_TOOL_DIET` flag on) — the
   only one that ever checked the human message for action evidence before
   adding a mutating tool.
2. The "work mode"/canvas category path (`main_simple.py` ~9530) — no gate.
3. The legacy category-classifier fallback path, used when
   `PRESENCE_TOOL_DIET` is off (`main_simple.py` ~9640) — no gate.
4. `pi_dashboard_voice_fast` (`main_simple.py` ~8270) — tools loaded straight
   from category lookup, no gate, `execute_tool` called directly.

`execute_tool()`'s only prior check ("offered-menu checking", already
present) asked whether a name was in `_active_tools` at all — never whether
anything in the turn's message authorized a *mutation*. J11 reproduced this
exactly: turn 3's message ("I'm thinking about turning on the porch light
when I get back") has `has_action_intent() == False` (verified directly), so
path 1 would have blocked `standing_order_create` — but with the flag
governing path 1 off, path 3 loaded it ungated, and the model called it,
creating a real, persistent, self-repeating `standing_order`.

### Fix landed

- `backend/app/main_simple.py`: `execute_tool()` now enforces an
  **execution-boundary authorization check**, independent of which selection
  path populated `_active_tools`: a mutating tool (per the existing
  `is_mutating_tool` classification) only runs if this turn's own message
  evidences the request (`has_action_intent`) or is a scoped continuation
  (`is_continuation_of_pending_action`) of a mutating tool this session
  actually executed last turn — or is in the narrow `ALWAYS_ALLOWED_MUTATING`
  set. Applies uniformly to the round loop, the deadline/past-time write
  path (`_execute_writes_after_deadline`), and voice (all three funnel
  through `execute_tool`). Fails **closed** if the classification/check
  itself errors.
- `pi_dashboard_voice_fast` (main_simple.py ~8326): now sets
  `llm_client._turn_message_for_mutation_gate` and clears
  `_last_turn_mutating_tools_for_boundary` before its direct `execute_tool`
  calls — this path previously had **zero** mutation gating of any kind, not
  just a missing boundary check; the new execute_tool check is now its only
  but real authorization.
- A read-only continuation peek (`_last_turn_mutating_tools_for_boundary`,
  keyed by `conversation_id`) is computed once, unconditionally, at the top
  of `_chat_with_tools_inner`, so the boundary check can recognize a scoped
  "yes"/"do it" without depending on which selection branch ran, without
  disturbing the existing pop-based consumption the diet-path/voice gates
  already do for their own schema-offer decision.

**Tests:** `backend/tests/test_execution_boundary_mutation_authorization.py`
(new, 7 cases: J11 repro refused before reaching the registry; genuine
request still executes; scoped continuation still executes; unrelated later
message does not ride a stale continuation; read-only tools unaffected;
`ALWAYS_ALLOWED_MUTATING` bypass preserved; simulated ungated-fast-worker
path refused). One pre-existing test in `test_chat_tool_loop.py`
(`TestDiscoveryIsNotAuthorization::test_actually_executing_a_mutating_tool_authorizes_it`)
needed a turn message added — it was asserting post-execution bookkeeping,
not exercising zero-evidence execution, and now needs a real message the
way its sibling tests already do. Full before/after:

| | Before | After |
|---|---|---|
| `test_execution_boundary_mutation_authorization.py` | did not exist | 7/7 pass |
| `test_execution_boundary_authorization.py` | 9/9 pass (unaffected — different layer) | 9/9 pass |
| `test_chat_tool_loop.py` | 74/75 pass locally after the R01 change (1 regressed) | 75/75 pass after the 1-line test fix |
| `test_standing_order_dedup.py` | 7/7 pass | 7/7 pass |

Full disposable-stack suite run for wider-regression confirmation: see the
"Full suite" section below.

### Round 2 (review remediation): operation/target scoping, recurring
authorization, pending-proposal state

The review correctly identified that the round-1 fix, while closing the
pure bypass, still granted broad authority from *any* action verb with no
binding to the specific operation or target — plan items 2 and 6 were
undone, and J10 has a real authorization-scope dimension beyond its
reasoning-quality one. Three concrete, deterministic, regression-tested
changes landed:

**1. Recurring-action authorization (plan item 6) — DONE.**
`backend/app/services/tool_mutation.py` gains `RECURRING_ESTABLISHING_TOOLS`
(`{"standing_order_create"}`) and `has_recurring_scope(message)` (checks for
"every time"/"whenever"/"standing order"/"automatically"/etc.).
`execute_tool`'s authorization block now requires recurring-scope evidence,
*in addition to* action-intent evidence, before a `RECURRING_ESTABLISHING_TOOLS`
member may run — closing the exact gap the review named: "turn the porch
light on now" (real, non-hypothetical action intent, verified via a listed
verb) still must not create a standing order with no recurring language at
all. Skipped only when authorized via `_via_continuation` (the tool
actually executed last turn, which means this exact check already ran and
passed then).

**2. Cross-tool operation/target scoping (J10's authorization dimension) —
DONE.** `find_cross_tool_unscoped_mutations` / `record_cross_tool_attempts`
(`tool_mutation.py`) — wired into both the normal round loop and the
deadline-write path in `main_simple.py`, alongside the pre-existing
same-tool `find_ambiguous_same_turn_removals`. Counts how many separate,
independently action-evidenced clauses the message actually contains
(`_count_actionable_clauses`, reusing `has_action_intent`'s own guards
per-clause) and allows that many distinct scope-sensitive
(cancel/delete/resolve/complete/abandon/close/archive/deactivate) tool
calls per turn, by call order — mirroring the same-tool guard's own "first
N survive" precedent. J10's exact message ("The Cedar follow-up is
handled. Close that thread and stop reminding me about it.") has exactly
ONE actionable clause ("stop reminding me about it" — "close" itself is
not a listed action verb) — a second, different tool acting on an
unrelated entity is now blocked. The explicitly legitimate case ("cancel
the standing order and mark the reminder done" — two distinct clauses, two
distinct tools) remains fully authorized; `has_bulk_intent` and exact
repeat calls (retries) are exempted, matching the same-tool guard's
existing contract.

**3. Typed pending-proposal state (plan item 2) — DONE.** New table
`chat_pending_proposal` (`app/models/chat_pending_proposal.py`, migration
`155_chat_pending_proposal` — **not applied to any database**, see the
Deployment section) plus `app/services/chat_proposal_service.py`
(`propose`/`consume`, row-locked-via-conditional-UPDATE consume-once
semantics, 15-minute TTL, superseded-by-newer-proposal handling). Wired
into `execute_tool`: a refused mutating call now records a proposal
(tool_name + exact arguments + **the message that prompted the refusal**);
a later scoped confirmation ("yes") consumes it and re-executes with the
**originally proposed arguments** — not whatever the model reconstructs on
the confirming turn, closing a real gap the old
"last-turn's-executed-tool-names" continuation mechanism had no way to
close (it only ever remembered a bare tool name, never what was actually
about to happen, and conflated "already done" with "awaiting approval").
Model design/reuse decision: investigated the codebase's three existing
"propose then explicitly approve" patterns first (`workout_adjustment_proposal`,
`soul_change_proposals`, `prompt_proposals`) — none reusable as-is (each is
reached through a structured API/UI action carrying an explicit
`proposal_id`, never chat free-text continuation), so this is a fourth,
deliberately lightweight implementation of the same well-established shape.

**Security-critical interaction, caught by this round's own test
development before being shipped:** the pending-proposal mechanism's FIRST
draft let a consumed proposal bypass the recurring-scope check entirely
(since the check only ever looked at the CURRENT turn's message, and a bare
"yes" never carries recurring language) — reopening J11 through a back
door: propose from a hypothetical message, bare-"yes"-confirm, standing
order created anyway. Fixed by storing the proposal's `source_message` and
checking recurring-scope against THAT (the message that actually prompted
the proposal) when authorization comes via a consumed proposal, never
against the confirming turn's own text. `test_chat_pending_proposal.py`'s
`test_consuming_a_proposal_cannot_bypass_the_recurring_scope_check` pins
this down explicitly so it can't regress silently.

**Tests:** `backend/tests/test_tool_mutation_scoping.py` (new, 13 cases:
recurring-scope classification, scope-sensitive tool classification, the
exact J10 shapes for both trials, the legitimate-two-requests case, bulk
language, exact-repeat non-double-counting, multi-round spread). 13/13
pass. `test_execution_boundary_mutation_authorization.py` gained 4 more
cases for the recurring-scope boundary integration (11/11 pass total).
`backend/tests/test_chat_pending_proposal.py` (new, 11 cases against the
real disposable Postgres: propose/consume lifecycle, superseding,
cross-user/cross-conversation isolation, expiry, the full execute_tool
integration including the security-critical negative case above). 11/11
pass.

### Round 3 (2026-09-26 review remediation): genuine target scoping,
retry-proof by construction, and proposals bound to what the user saw

Review correctly identified that round 2's fixes, while real improvements,
still had three concrete defects:

**1+2. Call-order/clause-count was not target scoping, and had a real
retry bypass — DONE, replaced entirely.**
`find_cross_tool_unscoped_mutations`/`record_cross_tool_attempts`/
`_count_actionable_clauses` (round 2's mechanism) is **removed**, not
patched. Two concrete problems with it, both confirmed by re-reading the
code against the review's own description:
- It authorized N scope-sensitive calls **by call order** (N = count of
  action-evidenced clauses) — a wrong-target call occurring first, or
  alone, passed regardless of whether THAT call specifically had any
  support. "1 clause, 1 call" looked fine no matter which call it was.
- `record_cross_tool_attempts` appended **both allowed and blocked** calls
  into the same `prior_calls`/`seen_signatures` history, and
  `find_cross_tool_unscoped_mutations`'s "exact repeat is not a new ask"
  carve-out then treated a RETRIED BLOCKED call as "already counted,"
  silently authorizing it the second time with identical arguments.

Replaced with `tool_domain_evidenced(tool_name, message)` /
`find_target_unscoped_mutations(tool_calls, message)`
(`app/services/tool_mutation.py`): a **stateless, per-call** check — does
the message contain a NOUN naming the kind of entity this tool acts on
(a curated pattern table for thread/research_plan/reminders/notes/list/
timers/standing_order, verified against the actual registered tool names
in `app/tools/registry.py`; a generic word-stem fallback for everything
else)? No `prior_calls`/history parameter exists at all — closing the
retry-bypass class of bug **by construction**, not by patching the
specific carve-out that caused it, since there is no cross-round state
left to exploit. Genuinely NOUN-only: "stop reminding me about it" (a verb
phrase describing an action on the thread) does not evidence the reminders
domain the way "cancel my reminder" does — the exact discrimination J10's
real failure needed. Wired into both call sites in `main_simple.py` (the
round loop and the deadline-write path), replacing the old function calls
and removing the now-unneeded `self._turn_cross_tool_calls` state
entirely.

**Tests (the exact five scenarios review finding 2 named, plus general
domain-classification coverage):**
`backend/tests/test_tool_mutation_scoping.py`, rewritten (20 cases, up
from 13) — `TestFiveReviewScenarios` covers wrong target first (blocked
regardless that it's first), a single wrong-target call (blocked even as
the only call this round — the exact shape round 2's mechanism let
through), a blocked call repeated in a later round (stays blocked,
stateless check reproduces the same verdict), explicit multiple requests
(both authorized — never degrades into "one mutating tool per turn"), and
bulk wording with targets outside the requested scope ("cancel all my
reminders" authorizes reminder-domain calls but not an unrelated
`cancel_research_plan` call in the same round). 20/20 pass.

**3. Pending proposals were not verified against what the user actually
saw — DONE, redesigned.** `propose()` (`chat_proposal_service.py`) used to
be called synchronously from inside `execute_tool()`, at refusal time —
**before** the model's own final reply text for that turn existed. A
proposal could be recorded, and later confirmed, even if Sara's real
reply never mentioned the action at all (a swallowed exception, an
unrelated fallback answer, a truncated generation). Redesigned:
- `propose()` now **requires** a `presented_summary` argument (Sara's own
  finalized reply text) and refuses to write anything shorter than 20
  characters (nothing plausibly substantive was said).
- `execute_tool()` no longer calls `propose()` directly — a refusal only
  stashes a candidate into `self._turn_unpresented_proposals` (pure
  in-memory).
- A new method, `SimpleLLMClient._finalize_turn_proposals(response_content)`,
  called from `_store_conversation_with_timeout` (the single choke point
  every turn-exit path funnels through) right after
  `_finalize_response_content` — i.e. only once the ACTUAL finalized reply
  text is known — is what actually persists the proposal, with that real
  text as `presented_summary`.
- The consume call site (`main_simple.py`) gained a **domain-consistency
  check**: `tool_domain_evidenced(function_name, consumed.presented_summary)`
  must hold before a consumed proposal is allowed to authorize
  execution — a pending row existing at all only proves Sara said
  something substantive that turn, not that it concerned THIS action.
  Binds the confirmation to the specific proposal actually presented
  (target/domain, via this check; exact parameters, via re-executing the
  originally-proposed `arguments_json` unchanged, pre-existing from round
  2; recurring scope, via `_recurring_scope_source`, also pre-existing).
  Completed actions remain represented separately from proposals (the
  pre-existing `chat_pending_proposal` vs `_CHAT_INVOKED_MUTATING_TOOL_NAMES`
  distinction is unchanged).

**Tests:** `backend/tests/test_chat_pending_proposal.py`, rewritten (17
cases, up from 11) — `TestProposeRequiresPresentedSummary` (3 new cases:
empty/too-short/substantive summaries), and
`TestExecuteToolStashesAndFinalizes` gains
`test_no_finalize_means_no_persisted_proposal_to_confirm` (a refusal whose
turn never reaches finalization produces nothing confirmable — the exact
round-2 gap, as a regression test) and
`test_a_presented_summary_unrelated_to_the_tool_domain_does_not_authorize`
(the new domain-consistency check). 17/17 pass.

**4. Baseline testing must use immutable, durably-located copies —
DONE**, corrected in the same round the issue was found (prior to this
document's most recent update). `docs/plans/incidents/repair_baseline_2026_09_25/`
holds the durable pre-edit reconstruction (`preedit/*.py`, sha256 table in
`MANIFEST.md`) and an explicit epistemic correction: round-trip patch
verification proves the patch is self-consistent, NOT that it matches
`jarvis-backend-1`'s actual running process state (no live bind-mounted
production directory is touched for baseline work again — see
`MANIFEST.md`'s own "process correction" section).

**5. Exact model accounting — DONE**, see the corrected "Budget used"
paragraph in the Live-model validation section below: exactly 28 upstream
requests, reconciled against the gateway's own ledger, full detail in
`docs/plans/incidents/live_validation_20260925T230309/RECONCILIATION.md`.

### R01 items still not done

- Item 1 (explicit registry metadata for effect type/domain/target/permission
  per tool, validated at startup) — **not started**. The current fixes reuse
  the existing name-heuristic classifiers (`is_mutating_tool`,
  `is_scope_sensitive_tool`, and round 3's `tool_domain_evidenced`); they
  close the confirmed gaps without the fuller metadata-schema project.
- Item 7 (audit the `acknowledge_notifications` always-allowed exception for
  scope) — **not done**.
- C03/38b/38c (Thanks-repeats-completed-write, scoped-Yes-loses-tools) are
  **not yet independently re-verified** against the round-3 changes.
- J01 (status-question matches action-verb set, report row 36), J02
  (exploratory calendar write) — not independently re-verified.
- The domain-scoping check (`tool_domain_evidenced`) is text-only and
  intentionally conservative in the noun-only direction (e.g. "stop
  reminding me about the dentist appointment," with no literal word
  "reminder," would not by itself authorize a genuine `reminders_cancel` —
  an accepted false-refusal risk, the same safe-direction trade-off made
  throughout this repair) — it has not been validated against a live model
  conversation yet (round 2's live validation covered the mechanism it
  replaced; see the "Live-model validation" section for what that covered
  and what remains not-live-validated).

## R02 — Corrections, target resolution, undo, retries preserve data

**Status: IN PROGRESS — J03's destructive-edit mechanism is fixed with
precise span-level removal (rewritten in round 2 — see below) and every
`notes_edit` write path, including `content` full replacement, now carries
a real optimistic-concurrency revision check. J10's authorization-scope
dimension is now addressed under R01 above (round 3's
`find_target_unscoped_mutations`, replacing round 2's
`find_cross_tool_unscoped_mutations` — see R01's round-3 subsection);
its reasoning-quality dimension remains a diagnosed, unfixed gap.**

### Round 2 (review remediation): span-level removal + real revision checks

The review correctly identified that the round-1 `remove_text` deleted the
**WHOLE LINE** containing a match — safe for a one-item-per-line note (the
literal J03 repro) but wrong for an inline comma-separated list or a phrase
inside a paragraph, where the line carries unrelated text too. It also
correctly identified that `content` (full replacement) remained
**unrestricted** — no revision check of any kind — so the exact class of
stale-overwrite risk J03 demonstrated stayed fully possible through that
path.

**Fixed:**

- **`_remove_span(content, needle)`** (new, `app/tools/notes.py`) replaces
  whole-line deletion with true span-level removal, matched only at
  non-letter/digit boundaries (so "cup" cannot match inside "cupcake" — a
  real risk the whole-line version also had, just invisibly, since it
  over-deleted the entire line regardless). Three cleanup shapes, tried in
  order: (1) the match is an entire line by itself → remove the line
  including its own newline; (2) the match sits in a comma-separated
  inline list → remove it together with one adjacent ", " separator so the
  list rejoins cleanly, preferring the trailing separator and falling back
  to the leading one; (3) anywhere else (mid-sentence prose) → remove
  exactly the matched characters and collapse a resulting double space.
  Exactly one match is still required — zero or multiple still refuse
  rather than guess.
- **Real optimistic concurrency for every write path.** `NotesEditTool.execute`
  now captures `note.updated_at` immediately after its read, computes the
  final title/content/folder values, and commits via a single **conditional
  `UPDATE ... WHERE id=:id AND updated_at=:read_updated_at`** (SQLAlchemy
  Core, not the ORM's implicit "last write wins" `session.commit()`). If
  zero rows match — another write committed to this note between this
  call's read and its write, from ANY path (another session, another tool
  call, a concurrent request) — the whole edit is refused and the caller is
  told to reread, rather than silently overwriting whatever that other
  write did. This applies uniformly to `content`, `remove_text`,
  `append_text`, `title`, and folder moves — no schema change needed, since
  `updated_at` is an existing column functioning as the natural revision
  token.
- **`content` now requires `base_revision`** (the note's `updated_at` as the
  caller last read it — obtainable from `notes_search`/`notes_list`/a prior
  `notes_edit` result, all of which already return it) whenever the note
  currently has non-empty content. Missing or mismatched → refused with an
  explicit message naming the current revision. An empty note's first real
  content needs no revision (nothing to lose). This is the second,
  independent layer beyond the automatic per-call optimistic-concurrency
  check above: the automatic check only proves nothing else committed in
  the brief window of ONE call; requiring `base_revision` forces the caller
  to have actually looked at a specific revision before requesting a full
  rewrite, which is what "must use a fresh base revision" actually means.

**Tests:** `backend/tests/test_notes_edit_narrow_operations.py`, fully
rewritten (24 cases, up from 7): 9 direct unit tests of `_remove_span`'s
three shapes (whole-line, inline-list first/middle/last item, paragraph
prose, cross-word-boundary non-match, repeated-match ambiguity, not-found,
case-insensitivity); the J03 repro plus the two review-named cases
(inline-list item removal preserving the rest of the SAME line, paragraph
phrase removal preserving the rest of the sentence); `content`
base_revision required/correct/stale (3 cases); and a genuine concurrent-edit
test proving a stale writer is refused rather than silently applied (lost
update prevented), alongside proof that two correctly-sequenced narrow
edits and a genuine fresh full rewrite both still succeed normally. 24/24
pass.

### Known gap — J10 reasoning-quality dimension: diagnosed, not fixed

R01's `find_cross_tool_unscoped_mutations` (above) now closes J10's
**authorization-scope** dimension — a message with one actionable clause no
longer authorizes a second, different tool acting on an unrelated entity.
What remains unaddressed is the **reasoning-quality** dimension: even when
authorization correctly allows exactly one scope-sensitive action this
turn, nothing yet verifies the model picked the semantically CORRECT
target among several candidates matching an ambiguous reference (the model
resolved "the Cedar follow-up" to the wrong backend entity, then described
a state that matched neither target). That requires target-resolution
work scoped to a known entity type + active task (plan change item 3,
`thread_resolution.py`) and is not implemented.

### R02 items not yet done

- Typed, owner-scoped IDs from reads/receipts with a distinct "title-in-ID-
  field" error (item 1) — not implemented; `notes_edit`/reminders tools still
  accept a bare ID lookup.
- Versioned note edits / revision history with conflict detection (item 2,
  beyond the narrow-op mitigation above) — not implemented.
- Stable list IDs with conservative aliasing (J07 list-name fork) — not
  implemented.
- Missing update/delete ops for food entries and workout sets (also listed
  under R08) — not implemented this session.
- Idempotency keyed to authenticated request + logical operation with
  transactional uniqueness (C03/O05) — not implemented; existing
  timestamp-based idempotency keys in `action_receipt_service` are unchanged.
- Undo targeting the recorded action with owner/window/revision checks (O05)
  — `standing_order_service.undo_action` already does owner/window/undone
  checks (pre-existing); not extended this session.

## R05/R06/R07 — small independent fixes (section 8 of the plan explicitly
calls these out as safe to do alongside R01/R02)

**Status: all four named small fixes are now DONE and regression-tested**
(document-search vector-fallback isolation, the fourth, fixed in round 3 —
see below). **Round 3 also extended R06 beyond the small
`reminder.content` fallback crash fix to the scheduling/catch-up gap the
plan's own R06 package separately names ("no overdue catch-up in that
path") — see the new R06 subsection below. Round 4 found and fixed a real
defect in that round-3 catch-up fix (delivery marked successful before
sending), and found and fixed round 3's document-search fix being
incomplete (lexical fallback only, semantic search itself still
categorically broken) — see the "Round 4" section further down for both.**

### R06 — `reminder.content` fallback crash (DONE)

**Confirmed root cause:** `Reminder` (`app/models/reminder.py`) has only
`title`/`description` columns — no `content`. Three call sites did
`reminder.description or reminder.content or "..."` / unconditional
`reminder.content` — `or` still evaluates its second operand, so any
reminder with a falsy `description` (empty string is the column's own
default) raised `AttributeError` and crashed dispatch.

**Fixed:** `app/tasks/inproc_schedulers.py::_dispatch_reminder` (the actual
push-dispatch crash site — evidence `REMINDER_DISPATCH_CRASH_NO_DESCRIPTION`),
`app/main_simple.py` (`NotificationScheduler` pre-generation path), and
`app/services/contextual_awareness_service.py` (upcoming-reminder alerts,
unconditional access — would crash for *every* upcoming reminder, not just
falsy-description ones). All three now fall back to `reminder.title`
(NOT NULL) instead of the nonexistent field.

**Tests:** `backend/tests/test_reminder_dispatch_content_fallback.py` (new,
3 cases against the real `_dispatch_reminder` call site: empty description,
`None` description, real description preferred over title). 3/3 pass.

### R06 remainder — overdue catch-up and no-duplicate-delivery (DONE, round 3)

**Confirmed root cause, verified directly:** `notification_predispatch()`
(`app/tasks/inproc_schedulers.py`) selected only items due in a narrow
`now <= due_at <= now+20s` window, with **no persisted delivery state at
all**. The instant `due_at` slipped into the past — a missed Celery beat,
a worker restart, a slow prior run — the item became permanently
unselectable (`now <= due_at` false forever after), with nothing recording
it was ever due. There was also no protection against dispatching the same
occurrence twice if the task ever overlapped or re-ran.

**Fixed:** two additive nullable columns, `notified_at` and
`delivery_status`, on both `reminder` and `timer` (migration
`158_reminder_timer_delivery_tracking` — **not applied to any database**,
see Deployment section). Selection changed to "due (`due_at <= cutoff`)
AND never notified (`notified_at IS NULL`)," which naturally includes
overdue items — real catch-up — bounded by a new
`REMINDER_TIMER_CATCHUP_MAX_AGE` (2 hours): anything overdue by more than
that is marked `delivery_status='missed'` explicitly rather than pushed as
a surprise hours later, or silently dropped forever (the plan's own
caution: "avoid flooding David with historical reminders at first
deployment... define catch-up/expiry policy... mark intentionally expired
items explicitly"). Each occurrence is claimed via a new
`_claim_for_dispatch()` — an atomic conditional `UPDATE ... WHERE
notified_at IS NULL` whose own WHERE clause is the duplicate-delivery
guard: a second overlapping/concurrent run claims zero rows for anything
already claimed, proven directly (not just inferred) by a test that calls
it twice on the same row.

**Scope note (explicitly out of scope this round, per the plan's fuller
R06 change list):** no retry-with-backoff for a push that fails after being
claimed (claimed = attempted-once, honestly; a failed send is not retried);
no cross-worker atomic leases (this task runs as a single Celery beat
entry, not documented as multi-worker); no distinction between "accepted by
the push provider" and "delivered to a physical phone" beyond what already
existed. These remain real gaps in the plan's full R06 package.

**Tests:** `backend/tests/test_reminder_timer_catchup_delivery.py` (new, 7
cases against the real disposable Postgres — the atomic-claim behavior is
a property of the actual `UPDATE...WHERE` semantics, not something a mock
can stand in for): normal on-time dispatch; the exact catch-up scenario
(overdue by 30 minutes, still dispatched) for both reminders and timers;
overdue beyond the catch-up window marked missed and NOT pushed; not-yet-due
items left completely unselected; a second `notification_predispatch()`
run does not redispatch an already-notified reminder; direct proof that
`_claim_for_dispatch` returns `False` on a second attempt at the same row.
7/7 pass. Pre-existing `test_reminder_dispatch_content_fallback.py`
rerun alongside — unaffected, 3/3 pass.

### R05 — timer naive/aware datetime crash (DONE)

**Confirmed root cause — corrected from the plan's own working hypothesis.**
The plan suspected a Python-type mismatch (one Timer model aware, one
naive) between `app.tools.timers.Timer` (a second, locally-declared model
mapped to the same `timer` table, to avoid a circular import) and
`app.models.reminder.Timer`. Directly inspecting the actual schema
(`\d timer` against the disposable stack's schema fixture, which mirrors
production) shows the REAL columns are genuinely
`timestamp without time zone` — plain naive storage, on both models'
underlying table, regardless of either model's Python-side declaration.
Adding `DateTime(timezone=True)` to the local model (tried first, see git
history in this session) changed nothing, because psycopg's return type is
governed by the actual wire column type, not the ORM's Python annotation —
confirmed by rerunning the exact repro test, which still failed identically
after that change. The real defect is that `TimersStatusTool.execute`
compared this naive-but-actually-UTC value directly against an aware
`datetime.now(timezone.utc)`.

**Fixed:** `app/tools/timers.py` gains `_as_utc()`, which attaches UTC
tzinfo to a naive value before arithmetic (every writer in this file already
stores `datetime.now(timezone.utc)` into these naive columns, so the naive
value's wall-clock IS already a UTC instant) — the same defensive pattern
already used, independently, at `main_simple.py`'s
`_check_and_schedule_notifications_sync` and `core/timezone.py`'s
`to_local`/`to_utc`, confirming this is the established convention in this
codebase for this exact table, just missing from this one call site.
Reverted the premature `DateTime(timezone=True)` schema-annotation change —
it doesn't match the real column type and doesn't fix anything; left a
comment explaining why, so a future reader doesn't try the same fix again.

**Tests:** `backend/tests/test_timer_naive_aware_datetime.py` (new, 3 cases,
run against the real disposable Postgres — a SQLite fixture would not
reproduce a wire-type-driven naive-return behavior): start-then-immediately-
status-check (the exact D04 shape), status-then-cancel, and an
already-expired stored timer (proves the arithmetic itself, not just the
common case). 3/3 pass. **Cancel's own inability to locate a timer ID**
(the plan's evidence describes cancel also failing because it depended on a
status lookup first) is a model-workflow behavior, not a bug in
`TimersCancelTool` itself (it takes `timer_id` directly) — not
independently re-verified against a live model this session.

### R07 — workout tool invocation contract (DONE)

**Confirmed root cause:** `ToolRegistry.execute_tool` always dispatches as
`tool.execute(user_id, **parameters)` (verified directly in
`app/tools/registry.py`) — `user_id` is unconditionally the first
*positional* argument. All three tools in `app/tools/fitness/workout_mode.py`
declared an unrelated required parameter first:
`WorkoutModeStartTool.execute(self, template_id=None, ...)` silently bound
the real user_id string into `template_id`;
`WorkoutModeLogTool`/`WorkoutModeCompleteTool` both declared a *required*
`action` first, which is worse — the model's own `action=...` keyword
collided with the positional user_id and raised
`TypeError: execute() got multiple values for argument 'action'` on every
call, unconditionally. None of the three ever received a `db` session from
the registry (only a fixed allowlist of context kwargs is ever injected),
so their `if not user_id or not db` guards were unreachable-safe code
masking an always-broken tool. All three also returned plain `dict`s, which
`ToolRegistry.execute_tool`'s `result.success` read cannot access — any
call that happened to survive the above still failed with an opaque
"Tool execution failed" back to the model.

**Fixed:** all three now have a standard `execute(self, user_id: str,
**kwargs) -> ToolResult` entrypoint (matching every other tool in the
registry) that opens its own DB session and delegates to a renamed
`_execute_impl` carrying the ORIGINAL, unchanged business logic — minimal
diff, zero behavior change beyond fixing the entrypoint contract. A new
`_as_tool_result()` helper converts the existing dict-shaped returns into
real `ToolResult`s without touching any of the payload keys other callers
(e.g. `content_card_builder`) may already read from `data`.

**Tests:** `backend/tests/test_workout_mode_tool_contract.py` (new, 6
cases, calling `execute()` exactly the way the registry does — positional
user_id plus the model's own kwargs): start-workout binds user_id/template_id
correctly; missing-template returns a proper ToolResult; workout-mode-log's
`action` no longer collides with positional user_id, both for a real call
and a no-active-session failure; end-workout's `complete`/`abandon` both
work the same way. 6/6 pass.

### R07 — document-search vector fallback isolation (DONE, round 3, scoped)

**Confirmed root cause, verified live against the real disposable
Postgres (not just inferred):** `document_chunk.embedding` is a `TEXT`
column, both by model declaration (`app/models/document_chunk.py`) and in
the actual schema fixture (`\d document_chunk` — mirrors production). The
`<=>` operator `documents_search` uses is undefined for `text`, so the
pgvector similarity query **always** raises `UndefinedFunction: operator
does not exist: text <=> vector` — regardless of content, values, or
dimensions (reproduced directly: exactly this error, live). That query was
already wrapped in a try/except (isolating the FAILURE), but nothing
rolled back the session afterward — the aborted Postgres transaction
cascaded into the very next statement on the same session, the lexical
ILIKE fallback, which then raised `InFailedSqlTransaction` **uncaught**,
crashing the whole tool and discarding a fallback match that genuinely
existed. Reproduced end-to-end before the fix: `tool.execute()` raised
`InFailedSqlTransaction` from the ILIKE fallback query itself, even though
a real lexical match was present in the seeded fixture data.

**Fixed:** `app/tools/documents.py` now calls `db.rollback()` immediately
inside the vector query's except block, before the lexical fallback runs
on the same session. Minimal, mechanical, directly verified fix — before:
the tool crashed and the real match was never found; after: the same
seeded data returns the correct lexical match, unaffected by the vector
path's failure.

**Deeper fix explicitly out of scope this round** (per the plan's own
caution against a blind fix here): `document_chunk.embedding` being TEXT
rather than a real `vector` column, and the discovered ingestion bug in
`app/routes/documents.py::_legacy_chunk_document` (binds a raw Python list
into that TEXT column whenever pgvector IS available — the opposite of
what the branch condition seems to intend) both need their own schema/data
inspection pass, embedding-dimension decision, and backfill/re-embed plan
before a safe additive-column migration — not attempted here. Semantic
document search is confirmed **structurally unable to ever succeed**
currently (not merely flaky); the lexical fallback is now the only working
path, and this fix is what keeps it reachable.

**Tests:** `backend/tests/test_document_search_vector_fallback.py` (new,
4 cases against the real disposable Postgres, using the actual production
ingestion shape — a stringified Python list in the TEXT column): the exact
reproduction (finds the lexical match instead of crashing); direct proof
the session is usable again immediately after a vector failure; embedding-
service outage (vector branch skipped entirely) still reaches lexical
search; genuine no-match is still reported honestly. 4/4 pass.

## R08 — food quantity/unit parsing (DONE, scoped)

**Confirmed root cause, verified directly (not just per the plan's
hypothesis):** `FoodSearchAndLogTool._parse_food_items`'s unit-token regex
alternation listed each unit's SHORT form before its longer forms —
`oz|g|gram|grams|cup|cups|tbsp|tsp|large|medium|small|slice|slices`. Python
`re` alternation is leftmost-alternative-wins, not longest-match, so
`"150 grams chicken breast"` matched `unit="g"` and left `"rams chicken
breast"` as the parsed food NAME (the same collision independently exists
for `cup`/`cups` and `slice`/`slices` — verified all three with direct
`re.match` calls before touching the file).

**Fixed:** reordered every colliding pair longest-first, and added a
per-alternative `(?![a-z])` negative lookahead as defense-in-depth against
any future prefix collision, structured so the "no unit at all" case (the
group matching nothing) is completely unaffected.

**Scope note:** this fixes the confirmed NAME-truncation mechanism only.
The plan's R08 package also covers serving-quantity computation ("do not
multiply grams by a summary serving count"), atomic correction of the
original logged row, workout-unit canonicalization, and recipe-consumption
snapshotting — none of those were touched this session.

**Tests:** `backend/tests/test_food_quantity_parsing.py` (new, 10 cases):
the three confirmed collisions (grams/gram/g, cups word forms, slices), the
short forms and no-unit case still working, `oz`/size-word forms, and a
multi-item message. 10/10 pass. Also reran the pre-existing
`test_food_search_log_grounding.py` alongside it — unaffected.

## R11 — logout does not revoke the token (DONE, rebuilt in round 2)

**Confirmed root cause:** JWTs here are stateless — `verify_token`
(`app/core/auth.py`) checks only signature and `exp`. `/auth/logout`
(`app/routes/auth.py`) only ever cleared the cookie. `/auth/token` hands the
raw JWT to mobile/API clients on purpose (bearer auth), so a captured
bearer token kept working for its full `jwt_expire_hours` (1 week) after
logout regardless — exactly evidence `A05_LOGOUT_DOES_NOT_REVOKE_TOKEN`
(replay after logout).

### Round 1 (superseded) and what the review correctly flagged

The first version stored revocations in Redis only, and `_is_revoked`
failed **open** on any Redis error — a revoked token could keep
authenticating through a Redis outage or restart, an unacceptable outage
behavior for a security control. `/auth/logout` also looped over BOTH the
cookie and bearer token whenever both were present, contradicting its own
documented "cookie-first precedence," and always returned "Successfully
logged out" regardless of whether anything was actually revoked. All
three are rebuilt below, not patched.

### Round 2 (DONE): durable revocation, correct precedence, truthful results

- **Durable store: moved to Postgres.** New table `revoked_token`
  (`app/models/revoked_token.py`, migration `156_revoked_token` — **not
  applied to any database**, see Deployment section) — `jti` primary key
  (so a double-submitted logout is `ON CONFLICT DO NOTHING`, not an
  error), `expires_at` mirroring the JWT's own `exp`. Postgres was chosen
  deliberately over keeping Redis: `get_current_user` already has a hard
  dependency on Postgres for the `User` row lookup on every single
  authenticated request, so making revocation durable there introduces
  **no new single point of failure** — if Postgres is down, authentication
  was already completely down regardless of this table.
- **Fails CLOSED, not open.** `_is_revoked` now refuses the token (returns
  `True`/revoked) if the revocation check itself cannot run — the
  corrected behavior, safe specifically because the failure mode it's
  reacting to (Postgres unreachable) already means every other
  authenticated request is failing too, unlike the first version's
  Redis-specific fragility. A real bug in the FIRST draft of this
  fail-closed logic — the DB-session-opening call sat OUTSIDE the
  try/except, so a genuine connection failure raised UNCAUGHT past the
  function instead of being handled — was caught by this round's own test
  (`test_revocation_check_fails_closed_on_a_store_error`) before shipping,
  fixed in both `revoke_token` and `_is_revoked`.
- **`verify_token`/`revoke_token` both accept an optional `db: Session`**
  (opening a short-lived one internally when not provided) — zero changes
  needed at 7 of the 8 existing call sites (`main_simple.py`'s WebSocket
  auth, `routes/automation.py`, `routes/agent_orchestration.py`,
  `routes/device_commands.py`, `routes/artifacts.py`, `/auth/token`), each
  still just calls `verify_token(token)`. `core/deps.py`'s
  `get_current_user` (the highest-traffic call site) passes its own
  already-open session, avoiding a second DB connection per request.
- **Cookie/bearer precedence corrected.** `/auth/logout` now resolves
  EXACTLY the one token `get_current_user` would have used for this same
  request (cookie first, else bearer) and revokes only that one — not
  "whichever is present." A request carrying a stale/different browser
  cookie alongside an unrelated mobile client's bearer token no longer
  risks revoking a session this specific request was never actually
  authenticating with.
- **Truthful results.** `/auth/logout` now returns `{"revoked": bool,
  "reason": ..., "message": ...}` instead of a blanket "Successfully
  logged out" — `reason` distinguishes `revoked`, `no_jti_legacy_token`
  (a pre-fix token, honestly reported as unable to be individually
  revoked), `already_expired`, `invalid_token`, `store_unavailable`, and
  `no_token_presented`.
- **Scope, unchanged from round 1:** this revokes ONE session's token, not
  "log out everywhere" — no multi-device revocation endpoint was added
  (not evidenced by A05, would be a new feature). Active WebSocket
  connections that authenticated before revocation are not forcibly
  disconnected (no documented policy exists yet to implement against); the
  request-time check does stop a revoked token from opening a NEW
  connection or surviving a reconnect.

**Tests:** `backend/tests/test_logout_revokes_token.py`, fully rewritten
(14 cases, up from 8, real Postgres via the disposable stack): the
original lifecycle cases; a durability check reading the revocation back
from a BRAND NEW DB session (proves it isn't connection-local state); a
double-logout idempotency case; the fail-closed-on-store-error case that
caught the real bug above; the corrected cookie/bearer precedence case
(revokes only the cookie-precedence token, proves the bearer token is
untouched); the no-token and legacy-token truthful-reporting cases. 14/14
pass.

## R03 — Durable action evidence and grounded confirmations

**Status: IN PROGRESS, a real bounded slice DONE and regression-tested in
round 3, then substantially hardened in round 4 after review found the
round-3 mechanism recorded best-effort, non-atomic receipts keyed only by
the model's own tool-call id (not a durable operation identity) — see the
"Round 4" section further down (finding 4) for the claim-before-mutation
redesign that replaced it. NOT the full plan package — see scope note
below (still accurate after round 4).**

**What existed before this round:** `action_receipt_service.py` shadow-
recorded standing-order actions only (`record_standing_order_action`,
called from `standing_order_service._log_action`). Every OTHER mutating
chat tool call — the vast majority of what Sara actually does — left no
durable record at all. This is the root of the evidence category "false
reminder/research/chess/goal success": when challenged or when Sara had to
decide what to say, there was nothing to check except her own recollection
of the conversation (context-window-dependent, lost on compaction, not
shared across clients).

**Built, wired, and tested:**

- `action_receipt_service.record_chat_tool_action()` — the general-purpose
  counterpart to `record_standing_order_action`. Writes into the SAME
  pre-existing `action_receipt` table (reused per the plan's own
  instruction, not a new table). `idempotency_key` is the tool_call's own
  id; a new partial unique index (migration
  `157_action_receipt_chat_wiring` — **not applied to any database**) makes
  a duplicate delivery of the same call write at most one row via
  `ON CONFLICT ... DO NOTHING`, no read-then-write race. `target` is
  best-effort from the tool's own result data, falling back to its
  arguments. `status` is `completed` or `failed` — never a bare boolean,
  and a failed call is recorded as failed, never silently dropped from the
  record ("a failed write stays failed," the plan's own words).
- Wired into `main_simple.py::execute_tool()`'s actual dispatch call site —
  both the normal success path and the exception path (a tool that raised
  before returning a `ToolResult` still gets a `failed` receipt; there is
  no evidence it succeeded, and silence there was exactly the gap that let
  a swallowed exception look like nothing happened either way). Never
  called for a refused/proposed call — R01's execution-boundary gate
  returns before this is ever reached, so a zero-call outcome produces
  zero receipt rows **by construction**, proven directly by a test.
  Never called for read-only tools.
- `find_receipts()` — scoped lookup by user (works across clients and
  after restart — it's a DB row, not context-window state), optionally by
  conversation, tool name, or a free-text match against `target`/
  `action_type`. A new `conversation_id` column (same migration) makes the
  per-conversation scoping real rather than approximate.
- A new registered tool, `verify_action` (`app/tools/action_verification.py`,
  category `action_verification`) — how the MODEL reads the record back.
  "Check the actual record before confirming or denying an action
  happened." An empty result is reported honestly ("no record found," not
  treated as proof either way — the wording review finding 3's honesty
  requirement and this plan package's own "when challenged, verify" both
  actually need). Classified read-only (`READ_TOKENS` gains `verify`) so it
  needs no action evidence of its own to be callable — the model must be
  able to check on its own initiative, the same way it can search or list.
- A short addition to `chat_system_prompt.py`'s existing Truth block:
  "queued" and "completed" are different words for different outcomes;
  call `verify_action` before confirming or denying a challenged action;
  an empty result is not proof either way.

**Tests:** `backend/tests/test_action_receipt_chat_wiring.py` (new, 11
cases against the real disposable Postgres): completed/failed receipt
recording, idempotent duplicate-call handling, conversation/tool-name/
query scoping, empty-result handling, the full `execute_tool` integration
(a real mutating call gets a receipt; a REFUSED call gets none; a
read-only call gets none), and `verify_action`'s honest no-record and
accurate-status-reporting behavior. 11/11 pass. Pre-existing
`test_singular_sara_c10_action_receipt.py` (the standing-order path) rerun
alongside — unaffected, 8/8 pass.

**Scope note — what this round does NOT cover, from the plan's fuller R03
package:** no true same-transaction atomicity between a tool's own
mutation and its receipt (each tool manages its own DB session
independently across ~40 tool files; the receipt is written in the
immediately-following statement, not the same transaction — a crash
precisely between the two could theoretically leave a mutation with no
receipt, though the exception-path write covers the common "tool raised"
case). No structural guard on the model's own free-form final-answer text
forcing it to match receipts (`verify_action` gives the model a way to
check itself and the prompt asks it to, but nothing yet parses the
generated reply and cross-checks it mechanically — that would mean
touching the final-answer/reasoning pipeline, which overlaps R13's scope
and was not attempted here). No `evidence_refs`/`artifact_refs` linkage
beyond the existing JSONB columns being written with the tool's result
message. External-system intent-before-dispatch persistence (for actions
that call out, e.g. smart-home) is R09's job, not touched here.

## R04, R08 (remainder), R09, R10, R13–R15

**Status: NOT STARTED this session.** No claims of partial completion are
made for these packages. Not attempted due to session scope/budget, not
because they are lower-value than what was done. R04 (tool/context
freshness on follow-up) and R09 (smart-home outcome verification) are
natural next dependents of R03's action-receipt foundation now that it
exists in a general-purpose form; R10 (background-work resumability) is
architecturally the same "durable state machine, atomic claims, no
duplicate delivery" pattern this round already applied narrowly to
reminders/timers (R06) and would extend rather than start from zero.

## Round 4 (2026-09-27 review remediation) — status: 6 findings addressed
and verified deterministically; a full-repo regression run for this round
was INTERRUPTED before completion at the user's explicit stop instruction
— see "Unfinished / pending verification" at the end of this section. No
production system was touched; the disposable test stack was left running
at the moment of interruption and is torn down (data-only, `docker
compose down`, no volumes to lose since the stack is `tmpfs`) immediately
after this document is saved, per instruction, since no test was actively
in flight.

This section supplements — does not replace — the round-1/2/3 material
above for R01, R03, R06, and R07. Read both: the earlier sections give the
original defects and fixes; this section gives what review found still
wrong with round 3's fixes specifically, and what changed in response.

### Finding 1 — R06: `_claim_for_dispatch` marked delivery successful
BEFORE sending (DONE)

**Confirmed defect:** round 3's `_claim_for_dispatch` set
`notified_at = NOW()` and `delivery_status = 'sent'` in the SAME atomic
UPDATE used to CLAIM the occurrence — i.e. it recorded success before the
push was ever attempted. A crash or send failure between the claim and
the actual send left the occurrence marked `sent` forever with nothing
ever delivered, and future runs excluded it permanently (exactly the
review's own description).

**Fixed:** claiming and recording the real outcome are now two SEPARATE
writes. `_claim_for_dispatch` sets ONLY `delivery_status = 'claimed'` +
`claimed_at`. `_record_delivery_outcome` — called only after the actual
dispatch attempt returns — writes the real terminal (`sent`,
`failed_permanent`) or non-terminal-retryable (`failed`) status.
`notified_at` is now set ONLY on a terminal outcome. A claim that's never
resolved (a crash between claim and outcome) becomes reclaimable once
older than `CLAIM_EXPIRY` (90s) — the next 5-second poll naturally
reconciles it; no separate sweep process. Failed dispatches retry up to
`MAX_DELIVERY_ATTEMPTS` (3) before becoming terminally
`failed_permanent`. The claim's own WHERE clause also re-checks
cancellation/completion state AT CLAIM TIME (`is_active`/`is_completed`),
not only at the earlier SELECT — a cancel/reschedule in the gap is now
caught. Also fixed in the same pass: the 20-second lookahead that fired
UP TO 20 SECONDS BEFORE an occurrence's actual due instant is removed
(`REMINDER_TIMER_LOOKAHEAD = 0`) — this task runs every 5 seconds
(alembic 051's own schedule row), so nothing is lost by not looking
ahead.

Three new columns (`claimed_at`, `delivery_attempts`, `last_error`) added
to the SAME migration this round-3 change already introduced —
`alembic/versions/158_reminder_delivery_state.py` (renamed from
`158_reminder_timer_delivery_tracking.py`; see the migration-verification
subsection below for why).

**Tests:** `backend/tests/test_reminder_timer_catchup_delivery.py`,
extended to 16 cases (up from 7): direct proof claiming does NOT mark
sent; a crash-before-dispatch scenario (claim, then simulate the process
dying — age the claim past expiry — then a fresh run reclaims and
actually dispatches); the "acknowledgment loss after a successful send"
scenario (documented, accepted, narrow trade-off: reclaim after this
specific crash window retries and may send a duplicate push — strictly
better than round 3's guaranteed permanent loss); bounded retry
(`failed` → `failed_permanent` after `MAX_DELIVERY_ATTEMPTS`, with
`last_error` populated); cancellation/reschedule rechecked at claim time
for both reminders and timers; a reminder due in 15 seconds is confirmed
NOT sent early. 16/16 pass.

### Finding 2 — R01: domain vocabulary, not the authorized target (DONE)

**Confirmed defect:** round 3's `tool_domain_evidenced` only asked "does
the message mention the KIND of thing this tool acts on, anywhere at
all?" "Cancel the dentist reminder" evidenced the reminders DOMAIN, which
would authorize cancelling ANY reminder the model called, including a
completely different one. And domain words appearing ANYWHERE in the
message (e.g. "reminders" inside "show my reminders, but cancel that
research task," a READ request) could wrongly authorize an unrelated call
in that domain.

**Fixed:** new module `app/services/target_authorization.py`. Resolves
the tool call's own argument (e.g. `reminder_id`) to the REAL database
row it names, then checks whether THAT SPECIFIC row's own identifying
text (title/description/objective) is what the message actually
referenced — not just the domain in general. Real resolvers for
reminders/timers/notes/`research_plan` (`research_plan` deliberately
treated as a singleton — the tool's own contract is "only one research
plan may run at a time," so there is no second candidate to confuse it
with, and a generic reference like "cancel that research task" is
unambiguous by construction there). Ownership is checked explicitly and
distinctly from "not found": a row that exists but belongs to a DIFFERENT
user is always blocked (real cross-tenant risk, no fallback); a row that
doesn't exist for ANYONE falls back to the domain-level check (not the
same risk — blocking it outright would manufacture false refusals for
legitimately-authorized requests whose target just can't be resolved,
including realistically the shape of several pre-existing chat-loop-level
tests that use fabricated ids with no backing DB row — this exact
regression was caught and fixed during this round's own verification
pass, see below). A scope-sensitive tool in an unresolved domain
(threads, lists, standing orders) falls back to the existing
`tool_domain_evidenced` check, a known, documented remaining gap.

Wired into BOTH `main_simple.py` call sites (the round loop and the
deadline-write path) via a new `find_target_unauthorized_mutations()`,
replacing `find_target_unscoped_mutations` there (which remains in
`tool_mutation.py`, still independently tested, now used internally by
`target_authorization.py` as the domain-level fallback). Fails CLOSED —
blocks every scope-sensitive call this round — on a DB error, consistent
with the execution-boundary check's own existing behavior.

**Regression caught and fixed during this round's own verification (not
shipped broken):** the first version of this fix treated ANY unresolved
id (not just a cross-tenant one) as an unconditional block, which broke 3
pre-existing tests in `test_chat_tool_loop.py` that exercise chat-loop
mechanics with fabricated reminder ids never written to the disposable
database. Root-caused precisely (not worked around): distinguished "the
id belongs to someone else" (`_FOUND_OTHER_OWNER` sentinel, always
blocked) from "the id doesn't exist for anyone" (falls back to the
domain-level check) — see the finding's own fix description above. All
originally-failing tests pass again after this correction; a new test
(`test_a_nonexistent_target_id_falls_back_to_domain_evidence_not_an_unconditional_block`)
pins down the distinction so it can't silently regress either direction.

**Tests:** `backend/tests/test_target_authorization.py` (new, 12 cases
against the real disposable Postgres): the exact "same-domain wrong
target" scenario (correct target authorized, a different real reminder
blocked); the exact "show my reminders, but cancel that research task"
scenario (reminders_cancel blocked despite "reminders" appearing in the
message, cancel_research_plan authorized for the actually-named task);
cross-tenant blocking; the nonexistent-id fallback distinction;
`research_plan`'s 8-char prefix lookup; unresolved-domain fallback;
fail-closed on a resolver exception. 12/12 pass.
`backend/tests/test_chat_tool_loop.py` rerun in full after the fix —
87/87 pass (the 3 regressions found and fixed during this same round, not
carried over).

### Finding 3 — R01: proposal confirmation still insufficiently bound (DONE)

**Confirmed defect:** round 3's consume-time check only required the
presented text to mention the tool's DOMAIN (`tool_domain_evidenced`) —
"a sufficiently long reply containing a domain noun does not prove the
user saw the proposed operation, target, parameters, and recurring
scope." A flat DENIAL ("I can't set that up without more detail") could
be long and specific-sounding without ever actually offering anything to
confirm, and nothing distinguished it from a genuine offer.

**Fixed:** new module `app/services/proposal_presentation.py`.
`render_structured_summary()`/`_argument_words()` build the ground-truth
representation from the tool call's OWN arguments (not the model's
free-text description of them) — matching is against the ARGUMENT
VALUES specifically (deliberately excludes the tool's own name, so "I
could set up a standing order for something else entirely" — domain
words only, no actual device/parameter reference — does NOT match once
real arguments exist to bind to). `is_denial()` detects a hard denial
phrase (e.g. "I won't"/"I can't") with NO accompanying invitation to
confirm ("want me to go ahead?", "should I", "confirm") — a denial with
an invitation IS a genuine proposal and is not flagged. For a
RECURRING_ESTABLISHING_TOOLS member, the presented text itself must frame
the proposal as recurring/standing (not merely the ORIGINAL user
message, checked separately against `source_message`) —
`presented_summary_matches_proposal(..., require_recurring=...)`.

Enforced in `chat_proposal_service.propose()` itself — a candidate
failing this check is never persisted at all, not merely flagged at
consume time (the primary gate; propose() is the single write path). The
main_simple.py consume-time check is upgraded to the same stronger
function as defense-in-depth for any row that predates this fix or a
future write path that bypasses `propose()`.

**Tests:** `backend/tests/test_proposal_presentation.py` (new, 14 pure
unit-test cases: rendering, denial detection with/without invitation,
the combined check's positive/negative cases including the review's own
"domain words but wrong parameters" and "different device entirely"
shapes, recurring-framing requirement, no-arguments fallback). 14/14
pass. `backend/tests/test_chat_pending_proposal.py` extended with a new
`TestStructuralPresentationGate` class (4 cases: a flat denial is never
persisted even though long/on-topic; domain-only text without the real
parameters is not persisted; a genuine reference to the real target IS
persisted; end-to-end via `execute_tool` proving a denial reply leaves
NOTHING for a later unrelated "yes" to confirm). 21/21 pass file-total (up
from 17).

### Finding 4 — R03: best-effort receipts, non-durable key, no atomic
claim-before-mutation (DONE, with an honestly-scoped residual gap)

**Confirmed defect:** round 3's `record_chat_tool_action` wrote a receipt
row AFTER the mutation already ran, keyed ONLY by the model's own
per-call `tool_call_id` — an id the inference server reassigns fresh on
every model turn, so it does NOT survive a client retry/reconnect that
reprocesses the SAME logical user message into a NEW model turn (a
different `tool_call_id` for what is semantically the same operation).
"Deduplicating receipt rows does not prevent duplicate effects" — a
post-hoc dedup only stops a second identical LOG ROW, not a second
EXECUTION of the mutation.

**Fixed:** the receipt mechanism is redesigned around claim-before-
mutation, the same architecture as finding 1's reminder/timer fix.
`compute_operation_key()` derives a durable, application-controlled
identity from `client_message_id` (the CLIENT's own idempotency token for
a turn — already used elsewhere in this codebase for exactly this
purpose) + tool name + arguments — stable across exactly the retry that
breaks a `tool_call_id`-only key. `claim_operation()` atomically claims a
`status='running'` row (the plan's own vocabulary) BEFORE
`tool_registry.execute_tool()` is ever called, via `INSERT ... ON
CONFLICT (idempotency_key) DO NOTHING RETURNING action_id` — a genuine
atomic claim, not read-then-write. If the claim is LOST (an operation
with this exact key already exists), the mutation is NOT executed again:
a terminal existing outcome is relayed to the model directly, or — for a
still-fresh in-flight claim — the call is refused concurrently. A claim
that's never resolved is reclaimable after `RUNNING_CLAIM_EXPIRY_SECONDS`
(120s), the identical reconciliation pattern as finding 1.
`finalize_operation()` records the real outcome after the mutation
actually returns, only ever transitioning a row still `status='running'`
(idempotent against a lost race or a duplicate finalize call).

**Regression caught and fixed during this round's own verification:** the
first version of `compute_operation_key`'s fallback (when
`client_message_id` is unavailable) used bare `conversation_id` — which
is STATIC across an entire conversation, so two genuinely different
requests in the same conversation calling the same tool with the same
arguments (a real, unremarkable case — caught concretely by a
pre-existing `test_chat_tool_loop.py` test reusing the literal
`"conv-1"`) collided on the identical key, and the second, legitimate
call was wrongly treated as a duplicate. Fixed: the fallback now uses the
tool call's OWN `tool_call_id` when `client_message_id` is unavailable
(weaker than `client_message_id` — does not survive a retry, same
limitation round 3's key had — but does not manufacture false collisions
between unrelated calls the way a bare `conversation_id` did).

**Honest residual gap, unchanged from round 3, explicitly not attempted
this round either:** true same-transaction atomicity between a tool's OWN
database write and this receipt is still NOT implemented — each of ~40
tool files manages its own DB session independently; the receipt claim
happens in a separate session/transaction immediately BEFORE dispatch,
and finalize happens in another separate session immediately after. The
pre-execution CLAIM GATE is what actually prevents a retried request from
executing the mutation twice (the concrete threat model "duplicate
effects" names) — full cross-file transactional atomicity would need a
per-tool refactor of a scope not attempted here.

**Tests:** `backend/tests/test_action_receipt_chat_wiring.py`, rewritten
around the new architecture (18 cases, up from 11): `compute_operation_key`
determinism/collision-avoidance (including argument-order independence);
`claim_operation` atomicity (a second claim on the same key fails);
`reclaim_stale_running_operation` (fresh claims are not reclaimable, aged
ones are); `finalize_operation` (success/failure transitions, double-
finalize is a safe no-op); full `execute_tool` integration proving **a
retried client_message_id does NOT re-execute the mutation** (the
registry is called exactly once across two calls with different
tool_call_ids but the same client_message_id) — this is the actual
duplicate-effect proof, not just a duplicate-row proof; refused/read-only
calls produce no receipt; a failed call finalizes to `failed`;
`verify_action` reports a stuck `running` operation honestly rather than
as completed. 18/18 pass.

### Finding 5 — R07: semantic search still fundamentally broken (DONE —
condition satisfied, not merely marked)

**Confirmed defect (unchanged from round 3):** `document_chunk.embedding`
is a TEXT column; the vector similarity query's `<=>` operator is
undefined for `text`, so every attempt raised regardless of content.
Round 3 only fixed the transaction-abort CASCADE into the lexical
fallback — semantic search itself remained categorically broken, and
round 3's own status document said so explicitly.

**Investigated and fixed this round:** verified directly against the real
pgvector extension that `CAST('[0.1, 0.2, 0.3]' AS vector)` successfully
parses exactly that text format — which is byte-for-byte what the
ingestion path (`_legacy_chunk_document`) actually stores via Python's
`str(embedding)`. This means a QUERY-SIDE cast on the existing TEXT
column (`CAST(dc.embedding AS vector)`, no schema migration, no
backfill) makes the comparison type-valid. Applied in
`app/tools/documents.py`'s similarity query (both the SELECT and ORDER BY
clauses).

Per the review's own conditional — "keep semantic search marked broken
until the schema/query compatibility is repaired AND paraphrase retrieval
passes" — both conditions are now met and verified, not merely asserted:
a real paraphrase-retrieval test (query sharing ZERO literal words with
the matching chunk, retrieved purely via embedding-distance ordering)
passes. Semantic search is genuinely fixed as of this passing.

**NOT verified — an explicit, named limit, not a silent gap:** whether
every row in an already-populated PRODUCTION `document_chunk` table holds
this same clean text format. A historical malformed value, a genuine
embedding-dimension mismatch between differently-embedded rows, or a
value written by some other, unaudited ingestion path could still raise
at query time for a real user's data — this was not and could not be
checked from this session (no access to real production data). The
existing try/except + session-rollback fix (round 3) is precisely what
keeps a single bad production row degrading that one query to
lexical-only rather than crashing the tool — it is a safety net for this
named uncertainty, not evidence every row is clean.

**Tests:** `backend/tests/test_document_search_vector_fallback.py`
extended to 5 cases (up from 4) — the pre-existing "no match at all"
test's fake embedding was corrected (it had coincidentally equaled the
fixture's stored embedding, which would now be a spurious semantic match
now that the vector path actually works — caught during this round's own
verification, not shipped as a false pass) — plus a new
`TestParaphraseRetrievalActuallyWorks` class: two documents on unrelated
topics (widgets / cookies) with distinct controlled embeddings; a query
sharing no literal words with either, embedded close to the widget
chunk's vector; asserts the widget document is found and the cookie
document is not. 5/5 pass.

### Finding 6 — investigate the additional failing test, don't just
observe it's untouched (DONE — root cause identified, confirmed
pre-existing and unrelated)

Round 3's status document noted `test_presence_latency.py::TestRecordFirstTokenLatency::test_over_budget_sets_breach`
as an extra failure (53→54) and argued it was pre-existing based on the
file being absent from every diff/new-file list — correctly cautioned by
review that "an untouched test file does not establish that changed
application code could not cause its failure."

**Actual root cause, found by reading both files directly (not
inferred):** `app/services/presence_latency.py`'s own docstring records a
deliberate "Ruling 1 budget amendment (2026-07-31)" that raised
`PRESENCE_BUDGET_SECONDS` from an original, never-actually-measured <2s
target to **5.5** (a real 20-turn measurement floor + 500ms). The failing
test calls `record_first_token_latency(3.5)` and asserts a budget breach
— but `3.5 < 5.5`, so `elapsed_seconds > PRESENCE_BUDGET_SECONDS` is
`False`, the code correctly takes the non-breach branch, and `r.set` is
correctly never called — exactly matching the observed failure ("Expected
set to have been awaited once. Awaited 0 times."). This is a stale test
assertion (written against the ORIGINAL <2s-era budget, never updated
after the documented 2026-07-31 amendment to 5.5s) — a genuine,
self-contained bug in test/implementation staleness, mechanically
unrelated to tool_mutation.py, chat_proposal_service.py,
action_receipt_service.py, target_authorization.py,
proposal_presentation.py, inproc_schedulers.py, documents.py, or
main_simple.py, none of which this test or its module import or
interact with. Confirmed identical-conditions comparison: `git status`
shows `app/services/presence_latency.py` and its test file with NO diff
against HEAD in any round of this repair session — the file's current
state IS its baseline state, byte for byte, so no "preserved baseline vs.
candidate" comparison could show anything different from what direct
root-cause reading already shows. Not fixed (out of this repair's
scope — a pre-existing product-behavior question: should this specific
test's input be updated to reflect the amended budget, or does it
indicate the amendment itself needs revisiting? Neither is this repair
plan's call to make unilaterally).

### Migration readiness — verified via REAL `alembic upgrade`/`downgrade`,
not only self-provisioned raw SQL (this round's response to review's
explicit "migrations applied nowhere does not demonstrate migration
readiness")

Every prior round's testing of migrations 155-158 used hand-written raw
SQL matching each migration's DDL, applied directly against the
disposable Postgres — convenient for fast iteration, but it never
exercised `alembic`'s own tooling or `alembic_version` bookkeeping at
all. This round did, for real, against the disposable stack:

1. Dropped every object the 4 migrations add (tables, columns, indexes)
   and stamped `alembic_version` to `154_saved_meal` (the true prior
   head).
2. Ran `alembic upgrade head` inside the `backend-test` container
   (`DATABASE_URL` already points at the disposable stack) — **this
   caught a real bug**: `158`'s original revision id,
   `158_reminder_timer_delivery_tracking` (36 characters), overflowed
   `alembic_version.version_num`'s `VARCHAR(32)` column —
   `StringDataRightTruncation`. Renamed to `158_reminder_delivery_state`
   (27 characters); re-ran cleanly, `alembic_version` correctly landed on
   the new id.
3. Verified the resulting schema directly (`\d reminder` etc.) — every
   expected column/table present with the exact declared types.
4. Ran `alembic downgrade 154_saved_meal` — clean, in reverse order
   (158→157→156→155→154) — and verified directly that every table/column
   was actually gone (`chat_pending_proposal` no longer exists;
   `reminder`'s new columns absent).
5. Ran `alembic upgrade head` again to restore the schema for the rest of
   this round's test suite; reran the full set of round-4-touched test
   files (127 cases across 9 files) against the alembic-provisioned
   schema — 127/127 pass, confirming the real migration output is
   behaviorally identical to the hand-written raw SQL used for faster
   iteration throughout the rest of this round.

**Still true, unchanged:** none of the 4 migrations have been applied to
any database outside this disposable stack — this verification
establishes they WORK cleanly via real alembic tooling against a
representative schema, not that they have been run anywhere durable.

### Unfinished / pending verification (interrupted by explicit user stop
instruction — not a completed final handoff for this round)

- **A full-repo regression run for round 4 was started and interrupted
  before completion.** The most recent COMPLETE evidence is: every
  individual round-4-touched/created test file passes in full
  (`test_target_authorization.py` 12/12,
  `test_proposal_presentation.py` 14/14, `test_chat_pending_proposal.py`
  21/21, `test_action_receipt_chat_wiring.py` 18/18,
  `test_reminder_timer_catchup_delivery.py` 16/16,
  `test_document_search_vector_fallback.py` 5/5,
  `test_tool_mutation_scoping.py` 20/20, `test_chat_tool_loop.py` 87/87,
  `test_singular_sara_c10_action_receipt.py` 8/8,
  `test_logout_revokes_token.py` 14/14 — all reconfirmed together in two
  combined runs, 127/127 and 105/105, zero failures), run AFTER the real
  alembic upgrade/downgrade/upgrade round-trip above, against the
  alembic-provisioned schema. **What has NOT been done:** a `pytest
  tests/ -q -k "not replay" --ignore=tests/assistant_acceptance/artifacts`
  run across the ENTIRE suite (2,500+ cases) to reconcile round 4's
  changes against round 3's own `54 failed, 2497 passed` baseline and
  confirm no new failures anywhere outside the files directly exercised
  above. This is the single most important next step for whoever resumes
  this work — not yet claimed as passing, not yet claimed as failing.
- Round 4's own isolated patch/diff artifact was not generated (mirroring
  round 3's own already-documented gap for its 5 modified files) — round
  4 touched/created even more files; see the exact list immediately
  below. `git status`/`git diff` against this working tree shows
  everything accurately; nothing has been reverted, stashed, or cleaned.
- The user's stop instruction arrived mid-verification, not mid-edit — no
  file was left in a partially-written state. Every file listed below is
  in its complete, saved, intended form.

### Exact files touched or created this round (round 4, 2026-09-27)

**Modified (previously existing, tracked or already-new from round 3):**
- `backend/app/main_simple.py` — replaced round-3's `find_target_unscoped_mutations` call sites with `find_target_unauthorized_mutations` (target_authorization.py) at both the round-loop and deadline-write authorization checks; replaced `record_chat_tool_action` post-hoc calls with the new claim-before-mutation/finalize-after flow (`claim_operation`/`finalize_operation`/`get_operation_by_key`/`reclaim_stale_running_operation`); consume-time proposal check upgraded from `tool_domain_evidenced` to `presented_summary_matches_proposal`
- `backend/app/services/tool_mutation.py` — no functional change this round (still used internally by target_authorization.py's fallback and unaffected by finding fixes); `find_target_unscoped_mutations` and its own tests remain as the domain-level layer
- `backend/app/services/action_receipt_service.py` — `compute_operation_key`/`claim_operation`/`get_operation_by_key`/`reclaim_stale_running_operation`/`finalize_operation` added, replacing `record_chat_tool_action` (removed)
- `backend/app/services/chat_proposal_service.py` — `propose()` now runs `presented_summary_matches_proposal()` as a hard gate before persisting anything
- `backend/app/tasks/inproc_schedulers.py` — claim/outcome state-machine split (`_claim_for_dispatch` no longer sets `notified_at`/`sent`; new `_record_delivery_outcome`); `REMINDER_TIMER_LOOKAHEAD` set to 0; `CLAIM_EXPIRY`/`MAX_DELIVERY_ATTEMPTS` added; `sqlalchemy as sa` import added
- `backend/app/models/reminder.py` — `claimed_at`/`delivery_attempts`/`last_error` columns added to both `Reminder` and `Timer`
- `backend/app/tools/documents.py` — vector similarity query now casts the TEXT column (`CAST(dc.embedding AS vector)`) in addition to the query parameter
- `backend/app/tools/registry.py` — unchanged this round (R03's `verify_action` registration from round 3 stands)
- `backend/alembic/versions/158_reminder_timer_delivery_tracking.py` — **renamed** to `158_reminder_delivery_state.py`; revision id shortened to fit `alembic_version.version_num VARCHAR(32)`; `claimed_at`/`delivery_attempts`/`last_error` columns added to its `upgrade()`/`downgrade()`

**New files this round:**
- `backend/app/services/target_authorization.py` (finding 2)
- `backend/app/services/proposal_presentation.py` (finding 3)
- `backend/tests/test_target_authorization.py` (12 cases)
- `backend/tests/test_proposal_presentation.py` (14 cases)

**Test files extended/rewritten this round:**
- `backend/tests/test_chat_pending_proposal.py` (17→21 cases)
- `backend/tests/test_action_receipt_chat_wiring.py` (rewritten around the new claim/finalize architecture, 11→18 cases)
- `backend/tests/test_reminder_timer_catchup_delivery.py` (7→16 cases)
- `backend/tests/test_document_search_vector_fallback.py` (4→5 cases, one existing case's fixture corrected — see finding 5)

**Nothing in this round was committed, deployed, or applied to
production.** The renamed `158_reminder_delivery_state.py` migration
remains unapplied anywhere outside the disposable stack used for its own
verification (see the migration-readiness subsection above).

### Running test resources at the moment of this update

Disposable stack (`docker-compose.test.yml`, project
`sara-disposable-test`) — containers `test-db`, `test-redis`,
`test-embeddings` — was UP and healthy at the moment this update was
written, holding the alembic-upgraded schema state described above (all
4 migrations applied via real `alembic upgrade head`, verified against).
No test was actively running at the moment of the stop instruction (the
in-progress full-suite command was rejected before it started executing
— confirmed via `docker ps`, no `backend-test` run container present).
Torn down (`docker compose -f docker-compose.test.yml down`, data-only —
the stack is `tmpfs`-backed with no named volumes, so nothing durable is
lost) immediately after this document was saved, per instruction.

## Live-model validation

Per review instruction: deterministic tests first, then targeted real
conversations. Ran against a THIRD, separate isolated stack —
`docker-compose.assistant-acceptance.yml` (project `sara-acceptance-study`,
the same infrastructure the original historical study used) — with the
`api` service pointed at a **copy** of this session's fixed source tree
(`/tmp/sara_live_validation_snapshot`, not the real working tree, so no
runtime artifact the container writes lands in the actual repo), a real
disposable Postgres/Redis/MinIO, recording adapters for every external
service (push/HA/FatSecret/SearX/MSGraph — nothing reaches a real external
system), and the `gateway` container as the sole egress path to the real
model host (`100.104.68.115:8082`, confirmed reachable) — enforcing
concurrency=1 and the 1,600-request budget ceiling itself. Real chat turns
were driven via the harness's own `chat_client.py` against
`http://api:8000/chat/stream`, using JWTs minted the same way the real
login route does (`fixtures_bootstrap.py`; password login is broken in
this image — a pre-existing bcrypt self-test failure unrelated to this
session's changes. Labeled precisely, per review finding 5: token
**issuance** (fixture-minted JWTs, used for every turn above), **logout**,
and **replay-after-logout** were all exercised live against the real
`/auth` routes — see the R11 results below. Password **login** itself
(`POST /auth/login` with real credentials) was NOT exercised end-to-end
this session.). One disclosed, snapshot-only patch was required —
same class of environment-wiring fix the original study's own disclosed
patches made: the model catalog's `qwen3.8-27b` entry hardcodes
`base_url=http://100.104.68.115:8082/v1` (bypassing `OPENAI_BASE_URL` and
reaching for the real host directly, which the isolated network correctly
refuses to route) — changed to read the env var in the snapshot copy only,
never in this session's actual deliverable code.

**Budget used (review remediation round 2, 2026-09-26 — corrected per
review finding 5, which flagged "under 20 chat turns" in this document and
"under 20 requests" in the handoff summary as two different, imprecise
claims): exactly 28 upstream model requests, reconciled directly against
the gateway's own ledger (`gateway_ledger.jsonl`) — 1 `gateway_start` + 28
`reserved` + 28 `completed`, 0 unmatched, 0 non-200 responses, 0 retries,
936.964s (~15.6 min) gateway-measured elapsed time. This came from 11
`chat_client.py` turn invocations (1 failed before reaching the gateway at
all — a pre-patch connection error, 0 ledger entries — the other 10
together produced the 28 requests, since a turn with multiple tool-calling
rounds is multiple upstream requests) plus 4 direct `/auth` HTTP calls that
never touch the model or gateway at all (correctly excluded from the 28).
This is the number to carry forward for cumulative accounting against the
authorized 1,600-request/16-hour ceiling. Full reconciliation, preserved
transcripts (all 11 turns) and source/config sha256 hashes at each of the 4
points the running source changed during this validation:
`docs/plans/incidents/live_validation_20260925T230309/RECONCILIATION.md`.
Stack fully torn down afterward (`down -v --remove-orphans` — all `tmpfs`,
nothing durable existed to begin with); validation snapshot directory
deleted (durable copies of what it contained live in the RECONCILIATION
directory above, not only in the now-deleted scratch copy).

**J11 (R01 execution-boundary + recurring-scope + pending-proposal), live,
real conversation:**
- Turn 1, "I'm thinking about turning on the porch light when I get
  back." (the exact original hypothetical): model called
  `home_get_devices` then attempted `standing_order_create` — **refused**
  by the execution-boundary check. `standing_order` table: **0 rows**
  (the original bug created a real row here). `chat_pending_proposal`:
  1 pending row recorded with the exact source message. The model's own
  reply correctly explained it needs explicit "yes, do it every time"
  confirmation rather than claiming success — a genuinely good
  conversational outcome, not just a mechanical block.
- Turn 2, "Yes, every time.": **first observed attempt correctly still
  refused** — caught a real design gap (see finding below) — after the
  fix, **re-ran with a fresh conversation and confirmed success**: the
  proposal was consumed and `standing_order_create` executed with the
  originally-proposed arguments.
- A third, independent live run against an unrelated tool
  (`location_reminder_create`, chosen by the model for oddly-phrased
  input) confirmed the SAME execution-boundary/pending-proposal mechanism
  generalizes correctly beyond `standing_order_create` specifically — HA
  sink ledger showed only read (`get_states`) calls, zero actual device
  state changes, across every attempt.

**Real bug found and fixed by this live validation (not caught by my own
deterministic tests, which I had written to my own expectations):** Sara's
own follow-up question ("just tonight, or make it the default from here
on?") was answered "Yes, every time." — which itself newly supplies
recurring-scope language the ORIGINAL proposing message never had. The
recurring-scope check was checking ONLY the stored original proposing
message when authorization came via a consumed proposal, so it kept
refusing even this explicit, unambiguous answer to Sara's own question
("the standing order bounced" — an accurate, non-fabricated report, so no
safety property was violated, but a real usability gap). Fixed:
`main_simple.py` now checks EITHER the confirming turn's own message OR
the original proposing message — consuming a proposal still can never
manufacture recurring scope that was never stated anywhere, it only adds a
second place to find it if genuinely present. New deterministic test
(`test_a_confirmation_that_itself_adds_recurring_language_succeeds`,
`test_chat_pending_proposal.py`) pins this down; re-verified live
afterward.

**A second real bug found and fixed by this live validation:** a plainly
explicit, unambiguous note edit — "Take bread off the Grocery Run note,
leave everything else." — was refused by the execution-boundary check
because `has_action_intent`'s verb lexicon had no entry matching "take X
off" (a separable phrasal verb — the object sits BETWEEN "take" and
"off", so the existing flat substring-list approach couldn't express it).
This is a pre-existing lexicon gap `gate_mutating_tools` already shared
(not a regression introduced by this session's execution-boundary check),
but the new check's uniform enforcement made its user-visible
consequence sharper: previously, a message like this landing on one of
the ungated selection paths (see R01) might have "worked by accident";
now the same (imperfect) detector applies everywhere consistently. Fixed
in `tool_mutation.py`: a new `_TAKE_OFF_OUT_RE` pattern matches "take"
followed by up to 4 words then "off"/"out", with its own negation/quote
guards — verified NOT to false-positive on "it'll take a while" / "take it
easy" / "take a look". 3 new deterministic tests
(`test_tool_mutation.py`); re-verified live afterward against the exact
failing phrasing plus a paraphrase ("Take coffee off...").

**R02 (`notes_edit` span-level removal), live, real conversations:**
- One-item-per-line note (the literal J03 shape): created via chat
  ("spare cable / charger / notebook / rain jacket"), asked to remove
  "the rain jacket... keep the other items" — model used
  `notes_search` then `notes_edit`; DB content after:
  `spare cable\ncharger\nnotebook` — exact match, other three items
  byte-verbatim.
- **Inline comma-separated list (the specific review-flagged gap the
  first version of this fix had — whole-line deletion would have wiped
  the entire line):** created a note with ONE line, `milk, eggs, bread,
  coffee, butter`; asked to remove "coffee" — DB content after:
  `milk, eggs, bread, butter` — the other four items preserved on the
  SAME line, comma-spacing rejoined cleanly. This is the exact scenario
  the review's finding 1 was about, now confirmed working end-to-end
  against a real model, not just my own unit tests of `_remove_span`.

**R11 (durable revocation, corrected precedence, truthful results), live,
direct HTTP against the real `/auth` routes:**
- `GET /auth/me` with a fresh token: `200`.
- `POST /auth/logout`: `200 {"message":"Successfully logged out.",
  "revoked":true,"reason":"revoked"}` — the truthful-result contract,
  confirmed over the wire, not just in a test harness.
- **Replaying the exact same token afterward (the literal A05 scenario):
  `401 {"detail":"Could not validate credentials"}`.**
- A DIFFERENT user's token (`morgan_test`), never touched by the above
  logout: `GET /auth/me` still `200` — confirms the corrected cookie/
  bearer precedence didn't overreach and revoke an unrelated session.

**Not attempted live:** J10's cross-tool authorization-scope dimension —
reproducing the exact ambiguous-reference-across-entity-types shape
live requires fixture setup (a seeded `followup_thread` plus an unrelated
`research_plan`/`reminder`) beyond what `fixtures_bootstrap.py` currently
provisions, and the model's tool-call pattern isn't reliably forceable
turn-to-turn. The mechanism itself shares the exact same `execute_tool`
call path already live-validated above for `standing_order_create` and
`notes_edit`, and has 13 passing deterministic tests (including both
literal J10 trial shapes) — recorded honestly as deterministically
validated, not independently live-validated, rather than claiming
equivalence.

## Full-suite regression check (final, after all fixes in this session)

Disposable stack: `docker-compose.test.yml` (`sara-disposable-test` project,
`test-db`/`test-redis`/`test-embeddings`, no production credentials, no
published ports, `internal: true` network). Schema provisioned via
`backend/scripts/provision_test_schema.sh` (the checked-in schema-only
fixture — this step was missed on the first two runs this session, which
produced hundreds of spurious `UndefinedTable` errors against a genuinely
empty database; re-run after provisioning to get a meaningful comparison).
Command: `pytest tests/ -q -k "not replay"
--ignore=tests/assistant_acceptance/artifacts` (the ignored path is the
frozen study snapshot, which ships its own colliding `conftest.py`).

**Round 2 final result (superseded by round 3 below, kept for history):**
`53 failed, 2464 passed, 16 skipped, 46 deselected, 25 errors` — diffed
programmatically against a same-tree pre-edit baseline (`53` failures,
zero new ones), which lived at `session_snapshot/true_session_baseline_v2.txt`
in the round-2 session's ephemeral scratchpad. That exact file was never
copied into a durable location before the session ended, so round 3 cannot
re-run the same programmatic diff — a real, acknowledged gap, and the
reason round 3's own comparison below is a manual failure-by-failure
check rather than a byte-identical file diff (see review finding 4's own
instruction to keep baseline material somewhere durable going forward,
now followed for round 3's own artifacts).

**Round 3 (2026-09-26) final result, same command, same stack:**
`54 failed, 2497 passed, 16 skipped, 46 deselected, 25 errors`. 2497
passing is up from round 2's 2464 by +33, in the direction this round's
new/expanded test files account for (`test_tool_mutation_scoping.py`
13→20, `test_chat_pending_proposal.py` 11→17, plus three brand-new files
totaling 22 cases — `test_action_receipt_chat_wiring.py` 11,
`test_document_search_vector_fallback.py` 4,
`test_reminder_timer_catchup_delivery.py` 7); the exact net figure is not
reconciled to the single digit against round 2's numbers, since round 2's
own baseline comparison file no longer exists to diff against (see the
gap noted above) — this document does not claim more precision here than
that. Failures went from 53 to 54 — investigated, not hand-waved: the one
extra failure is
`test_presence_latency.py::TestRecordFirstTokenLatency::test_over_budget_sets_breach`,
which reproduces **deterministically in isolation** (`AssertionError:
Expected set to have been awaited once. Awaited 0 times`), in a file
`git status` confirms this session never touched
(`app/services/presence_latency.py` and its test are both absent from
every diff/new-file list in this document). Not attributed to "flakiness"
or to any change in this session without that verification — it is a
pre-existing defect in an unrelated module, independently reproducible
with `pytest tests/test_presence_latency.py -q` on its own. Every test
file this session added or touched was independently run to 100% pass
before and after the full-suite run, both in isolation and combined (220
cases across `test_tool_mutation.py` + `test_tool_mutation_scoping.py` +
`test_chat_tool_loop.py` + `test_chat_pending_proposal.py` +
`test_action_receipt_chat_wiring.py` + `test_singular_sara_c10_action_receipt.py`,
run together, 220/220 pass) — this is the actual regression evidence for
round 3's changes, not the aggregate failure-count delta alone.

**Deployment artifact:** `docs/plans/SARA_REPAIR_PATCH_2026_09_25.diff` —
a clean, standalone unified diff covering rounds 1–2's changes to the 12
previously-existing files listed below, generated by diffing each file's
exact reconstructed pre-edit content against its state at the end of round
2 (not `git diff HEAD`, which would conflate this repair with the other
173 files' unrelated pre-existing uncommitted work in any file that had
both). `core/deps.py` was confirmed to have had no pre-existing dirty
state, so it was included via a direct HEAD diff instead.

**Round 3 is NOT yet captured in an isolated patch artifact — an honest
gap, not an oversight.** Round 3 modified 5 previously-existing tracked
files beyond what the existing patch covers —
`backend/app/models/reminder.py`, `backend/app/prompts/chat_system_prompt.py`,
`backend/app/services/action_receipt_service.py`,
`backend/app/tools/documents.py`, `backend/app/tools/registry.py` — none
of which have a verified pre-round-3 reconstruction the way the original
12 files do (building one would mean redoing the same reverse-edit
reconstruction exercise `MANIFEST.md` describes, for these 5 files
specifically; not done this round, given time remaining). `git diff HEAD`
for these 5 is NOT safe to treat as an isolated round-3 diff without first
checking each one for pre-existing unrelated dirty content from the same
173-file set R00 identified — not verified here. The 4 brand-new files
below (confirmed via `git status` showing `??`, not `M` — nothing tracked
to conflate with) have no such problem; they are unambiguous in their
entirety. **Recommendation for whoever deploys this:** either commit
rounds 1–3 together as one reviewed change and diff cleanly against
`origin/main`, or have a following session extend the reconstruction
exercise to these 5 files before extracting a round-3-only patch. Do not
assume the existing `.diff` file covers round 3's changes.

**Note on the working tree:** this repository had 173 files with
pre-existing uncommitted changes at session start (see R00's baseline
identity above) — none of those are this session's work, and none were
touched, reverted, or interfered with. The files below are the complete,
exact set this session changed or created across all three rounds;
everything else showing as modified/untracked in `git status` predates
this session.

**Modified this session, rounds 1–2** (see the round-3 additions/changes
in the next list — several of these files were touched AGAIN in round 3):
- `backend/app/main_simple.py` — R01 execution-boundary authorization, recurring-scope check, cross-tool scoping wiring, pending-proposal integration; R06 reminder fallback
- `backend/app/tools/notes.py` — R02 `_remove_span` (span-level removal), optimistic-concurrency revision checks on every write path
- `backend/app/tools/timers.py` — R05 naive/aware datetime fix
- `backend/app/tools/fitness/workout_mode.py` — R07 tool invocation contract
- `backend/app/tools/fitness/food_search_log.py` — R08 unit-parsing regex ordering
- `backend/app/tasks/inproc_schedulers.py` — R06 reminder fallback (actual dispatch crash site)
- `backend/app/services/contextual_awareness_service.py` — R06 reminder fallback
- `backend/app/services/msgraph_service.py` — R12 error propagation
- `backend/app/services/tool_mutation.py` — R01 recurring-scope + cross-tool scoping functions
- `backend/app/core/auth.py` — R11 durable (Postgres) token revocation, fail-closed
- `backend/app/core/deps.py` — R11 passes its own DB session into `verify_token`
- `backend/app/routes/auth.py` — R11 logout: correct precedence, truthful results
- `backend/tests/test_chat_tool_loop.py` — one pre-existing test given a real turn message (R01 changed the contract it exercises; see R01 above for why)
- `backend/tests/test_tool_mutation.py` — 3 new cases for the "take X off/out" phrasal-verb fix (live-model validation finding, see above)

**Modified again (or newly, for the 5 not in the list above) in round 3
(2026-09-26):**
- `backend/app/main_simple.py` — replaced round-2's cross-tool scoping call sites with `find_target_unscoped_mutations`; `execute_tool` refusal path now stashes to `self._turn_unpresented_proposals` instead of calling `propose()` directly; new `_finalize_turn_proposals()` method; consume call site gained the domain-consistency check; R03 action-receipt recording wired into both the success and exception paths of the tool-dispatch call site
- `backend/app/services/tool_mutation.py` — replaced `_count_actionable_clauses`/`find_cross_tool_unscoped_mutations`/`record_cross_tool_attempts` with `tool_domain_evidenced`/`find_target_unscoped_mutations` (stateless, retry-proof); `READ_TOKENS` gains `verify`
- `backend/app/services/chat_proposal_service.py` — `propose()` now requires `presented_summary`; `ConsumedProposal` gained that field
- `backend/app/models/chat_pending_proposal.py` — new `presented_summary` column
- `backend/alembic/versions/155_chat_pending_proposal.py` — edited in place (never applied anywhere, so safe to edit rather than version) to add `presented_summary TEXT`
- `backend/app/models/reminder.py` — R06 remainder: `notified_at`/`delivery_status` columns on `Reminder` and `Timer`
- `backend/app/tasks/inproc_schedulers.py` — R06 remainder: bounded overdue catch-up + atomic-claim duplicate-delivery guard, replacing the narrow `now<=due<=cutoff` selection
- `backend/app/tools/documents.py` — R07: `db.rollback()` after the pgvector query's exception, isolating it from the lexical fallback
- `backend/app/services/action_receipt_service.py` — R03: `record_chat_tool_action()`, `find_receipts()`, `_infer_chat_tool_target()` (general-purpose, alongside the pre-existing standing-order-only `record_standing_order_action`)
- `backend/app/tools/registry.py` — R03: registers `verify_action`/`ACTION_VERIFICATION_TOOLS`, new `action_verification` category
- `backend/app/prompts/chat_system_prompt.py` — R03: Truth block gains the "queued vs completed" / `verify_action` guidance

**New application files this session:**
- `backend/app/models/chat_pending_proposal.py` + `backend/alembic/versions/155_chat_pending_proposal.py` (R01 pending-proposal state — migration NOT applied)
- `backend/app/models/revoked_token.py` + `backend/alembic/versions/156_revoked_token.py` (R11 durable revocation — migration NOT applied)
- `backend/app/services/chat_proposal_service.py` (R01 propose/consume service)
- `backend/app/tools/action_verification.py` (R03: `verify_action` tool, round 3)
- `backend/alembic/versions/157_action_receipt_chat_wiring.py` (R03: `conversation_id` column + idempotency-key unique index on `action_receipt` — migration NOT applied, round 3)
- `backend/alembic/versions/158_reminder_timer_delivery_tracking.py` (R06 remainder: `notified_at`/`delivery_status` columns — migration NOT applied, round 3)

**New test files this session:**
- `backend/tests/test_execution_boundary_mutation_authorization.py` (R01, 11 cases — 7 round 1 + 4 round 2 recurring-scope integration)
- `backend/tests/test_notes_edit_narrow_operations.py` (R02, 24 cases — fully rewritten in round 2, up from 7)
- `backend/tests/test_reminder_dispatch_content_fallback.py` (R06, 3 cases)
- `backend/tests/test_timer_naive_aware_datetime.py` (R05, 3 cases)
- `backend/tests/test_workout_mode_tool_contract.py` (R07, 6 cases)
- `backend/tests/test_food_quantity_parsing.py` (R08, 10 cases)
- `backend/tests/test_email_sync_outage_error_accounting.py` (R12, 3 cases)
- `backend/tests/test_logout_revokes_token.py` (R11, 14 cases — fully rewritten in round 2, up from 8)
- `backend/tests/test_tool_mutation_scoping.py` (R01, 20 cases — fully rewritten in round 3, up from 13; replaces the old cross-tool-scoping tests with target-scoping tests including the exact 5 scenarios review finding 2 named)
- `backend/tests/test_chat_pending_proposal.py` (R01, 17 cases — rewritten in round 3, up from 11; adds the `presented_summary` requirement and domain-consistency tests)
- `backend/tests/test_action_receipt_chat_wiring.py` (R03, round 3, 11 cases)
- `backend/tests/test_document_search_vector_fallback.py` (R07, round 3, 4 cases)
- `backend/tests/test_reminder_timer_catchup_delivery.py` (R06 remainder, round 3, 7 cases)
- `docs/plans/incidents/live_validation_20260925T230309/RECONCILIATION.md` (round 3: exact gateway-ledger accounting, transcripts, source-state hashes)
- `docs/plans/incidents/repair_baseline_2026_09_25/MANIFEST.md` + `preedit/*.py` (round 3: durable baseline reconstruction, moved out of the ephemeral scratchpad)
- `docs/plans/SARA_REPAIR_STATUS_2026_09_25.md` (this document)

**Nothing in this session was committed, deployed, or applied to
production.** Four additive migrations were written (`155_chat_pending_proposal`,
`156_revoked_token`, `157_action_receipt_chat_wiring`,
`158_reminder_timer_delivery_tracking`) but deliberately NOT applied
anywhere — two add new tables (`chat_pending_proposal`, `revoked_token`),
two add nullable columns/indexes to existing tables (`action_receipt`,
`reminder`, `timer`). All are self-provisioned only inside the disposable
test stack (raw SQL matching each migration, or `Base.metadata.create_all`
for the two new-table cases — this codebase's existing convention for
in-flight schema additions not yet in the checked-in fixture).

## Deployment and rollback — NOT PERFORMED, corrected per review

The first version of this section (in an earlier chat message, not this
document) recommended a broad `git checkout` of the touched files for
rollback and treated a first commit of this work as safely revertible.
Both are wrong for this specific working tree, and neither is used here:

- **A broad `git checkout <file>` is unsafe here.** At least two of this
  session's touched files (`main_simple.py`, `food_search_log.py`) already
  had pre-existing, unrelated uncommitted changes before this session
  started (part of the 173-file dirty tree — see R00). `git checkout`
  resets a file to its last COMMITTED state (`HEAD`), which would discard
  BOTH this repair AND that pre-existing unrelated work in the same file —
  work this task was never authorized to touch, let alone delete.
- **A plain `git commit` of these files, followed by `git revert`, is
  unsafe here too.** `git add <file>` stages the file's ENTIRE current
  diff against `HEAD` — for any file that already had other pre-existing
  changes, that commit would bundle this repair together with unrelated
  work inseparably. Reverting it later would revert BOTH, not just the
  repair.

**What to use instead:** `docs/plans/SARA_REPAIR_PATCH_2026_09_25.diff` — a
standalone unified diff covering rounds 1–2's changes, and NOTHING else,
generated by diffing each touched file's precisely reconstructed pre-edit
content (see R00's exact-reconstruction methodology) against its state at
the end of round 2 — not `git diff HEAD`, which would have conflated this
repair with each file's other pre-existing uncommitted changes. This patch
is genuinely isolated FOR ROUNDS 1–2 ONLY: applying it to a baseline that
already contains each file's pre-edit content reproduces rounds 1–2's
changes exactly, and is symmetrically reversible with `patch -R` /
`git apply -R`. **Round 3's changes to 5 previously-tracked files
(`app/models/reminder.py`, `app/prompts/chat_system_prompt.py`,
`app/services/action_receipt_service.py`, `app/tools/documents.py`,
`app/tools/registry.py`) are NOT in this patch and have no isolated diff
artifact yet** — see the note above the modified/new file lists. Only
round 3's brand-new files (untracked, nothing to conflate) are unambiguous
without further work.

**Recommended procedure, none of it performed in this session:**

1. **Establish a recoverable baseline first.** Before touching anything,
   get the 173 pre-existing dirty files into a known, recoverable state —
   e.g. David reviews and commits the pre-existing work he intends to keep
   (as its OWN commit, separate from this repair), or at minimum takes a
   full filesystem/volume snapshot of the working tree and the production
   database. This step is David's call, not something this session should
   make unilaterally — it touches 173 files of in-progress work this task
   was not asked to review.
2. **Review this repair as its own, isolated change.** `docs/plans/SARA_REPAIR_PATCH_2026_09_25.diff`
   (rounds 1–2, 1,622 lines across 13 modified files) plus round 3's 5
   modified-but-not-yet-isolated files (review directly against this
   working tree — see the round-3 patch gap noted above) plus 21 brand-new
   files across all three rounds (8 application/migration files + 13 test
   files, listed above; `git status --porcelain` shows each as `??` —
   nothing to conflate for these specific files, though this working tree
   also has many OTHER untracked files unrelated to this repair, so `??`
   alone is not sufficient identification — use the explicit lists above).
   Read the patch and the new/modified files directly; nothing here needs
   `git log`/`blame` since none of it is committed yet.
3. **Build and test a candidate image in isolation** — e.g. a disposable
   worktree or a fresh checkout of whatever baseline step 1 established,
   with `docs/plans/SARA_REPAIR_PATCH_2026_09_25.diff` applied
   (`git apply docs/plans/SARA_REPAIR_PATCH_2026_09_25.diff`) plus round
   3's 5 modified files' changes applied manually (no patch file yet — see
   above) plus all new files copied in. Run the same disposable-stack
   suite this session used (`docker-compose.test.yml`) against that
   candidate as a final check before it touches anything real.
4. **Apply the four additive migrations to a REAL (non-disposable, but
   still not production) database first**, verify `chat_pending_proposal`,
   `revoked_token`, and the new `action_receipt`/`reminder`/`timer`
   columns come up with the exact DDL in `alembic/versions/155_chat_pending_proposal.py` /
   `156_revoked_token.py` / `157_action_receipt_chat_wiring.py` /
   `158_reminder_timer_delivery_tracking.py`, and confirm `alembic
   downgrade -1` four times cleanly reverses them (all four migrations'
   `downgrade()` are written and were exercised conceptually via the
   equivalent raw-SQL statements in this session's own disposable-stack
   setup, but never through `alembic` itself against a real target — do
   this before trusting the migration files against production).
5. **Only then**, with a reviewed candidate, a tested migration, and an
   established recoverable baseline all in hand: apply the migrations to
   production, deploy the candidate, and restart the backend. **This
   session performed none of this** — `jarvis-backend-1` was left running
   untouched throughout, on its own bind-mounted dirty source, the entire
   time.
6. **Rollback, if needed after a real deploy:** revert rounds 1–2's code
   with `patch -R` / `git apply -R` on `SARA_REPAIR_PATCH_2026_09_25.diff`
   (safe and precise, per above); revert round 3's 5 modified files by
   hand against this document's description of what changed in each (no
   patch file yet — see the round-3 patch gap); remove all 21 listed new
   files; then `alembic downgrade` the four migrations (additive-only —
   two drop empty tables, two drop nullable columns/indexes — no data
   migration risk either way). Any standing orders, note edits, action
   receipts, or delivered/missed-marked reminders already acted on under
   the new code between deploy and rollback are **not** automatically
   reconciled by this rollback — per the plan's own instruction, committed
   user actions are a separate, evidence-based reconciliation, never
   blindly reversed.

**Smoke-test list for after an approved deploy** (not run this session,
since no deploy happened): the exact live-validated scenarios above —
a hypothetical standing-order request refused and proposed, a recurring
confirmation consuming it, an inline-list note edit, and a logout/replay/
cross-user-isolation check against real auth — plus a general watch for
unexpected `chat_pending_proposal` growth (would indicate proposals aren't
being consumed/expiring as designed) and `revoked_token` table health.
Round 3 additions, none live-validated (deterministic tests only — see
each package's own section above): a wrong-target scope-sensitive call in
a real conversation should be refused even as the first/only call; a
genuinely challenged action ("did you actually cancel that?") should
produce a real `verify_action` call and an honest answer, watch
`action_receipt` row growth for plausibility against actual tool-call
volume; after a period of downtime, confirm overdue reminders/timers
within the 2-hour catch-up window actually arrive and nothing duplicates;
confirm `documents_search` no longer crashes on a real semantic query (it
will still only ever return lexical matches until the deeper TEXT-vs-
`vector` column issue is separately fixed — see R07 above).

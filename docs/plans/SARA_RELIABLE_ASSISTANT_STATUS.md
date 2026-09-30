# Sara reliable-assistant implementation — status

> **EVIDENCE NOTICE — 2026-09-29, added during production incident recovery.**
>
> A host-wide OOM and reboot destroyed every artifact this task had written under
> `/tmp/claude-1000/`. The following are **no longer citable as verified** and are
> marked unavailable/unreproduced wherever they appear below:
>
> * the controlled-clock suite comparison (the 2,366 / 3,040 passed figures, the
>   56-of-57 shared-failure split, and the three-way split artifacts)
> * every release/recovery rehearsal log, including the run that reported
>   `REHEARSAL PASSED` and `VERDICT: READY`
> * the final full-suite run, whose result was never read
>
> The scripts that produce them are in the repo, so the runs are reproducible; the
> artifacts are not recoverable. Incident record and the evidence that *does* exist
> durably: `/home/david/sara_incident_20260929/INCIDENT.md`.
>
> Separately: this task is **paused**. Production was recovered onto
> `sara-reliable-candidate:20260929` + schema `158_reminder_delivery_state`; see the
> incident record. That recovery is not acceptance evidence for the assistant work.


Plan: `docs/plans/SARA_RELIABLE_ASSISTANT_IMPLEMENTATION_PLAN_2026_09_28.md`
Started 2026-09-28. Single agent, no subagents.

Evidence map: `docs/plans/SARA_RELIABLE_ASSISTANT_EVIDENCE.csv` (88 rows)
Release package: `docs/plans/SARA_RELIABLE_ASSISTANT_RELEASE.md`

## Current phase

**INCOMPLETE — implementation continuing. This is not a release candidate and no
deployment approval is being requested.**

A previous revision of this document described the task as complete pending two
decisions. That was wrong: six implementation gaps remained open, and the
approval request has been withdrawn until they are closed. The gaps, as raised:

1. **Authorization fallback too broad** — an unknown imperative plus a target
   reference granted five different operation kinds at once. Must require
   evidence for the specific requested operation.
   **IMPLEMENTED 2026-09-29, deterministic evidence.** The wildcard is gone;
   `operation_contract.unresolved_imperative()` replaces it, and an instruction
   whose operation the application cannot identify now returns CLARIFY with
   reason `instruction_names_no_identifiable_operation` instead of granting
   UPDATE/RESCHEDULE/COMPLETE/CANCEL/CONTROL. 124 cases in
   `tests/test_operation_contract.py`, including a parametrized case per unknown
   verb ("Bin the vet one.", "Yeet the vet one.", "Sort the vet one out.")
   proving none grants a destructive operation.
2. **Current-state readbacks incomplete** — grounding matched generated status
   sentences against entity words instead of reading current state by stable id.
   **IMPLEMENTED 2026-09-29, deterministic evidence.** Both word-matching
   helpers (`_claim_targets`, `_reply_ignores_every_completed_target`) deleted;
   `reference_resolution.read_current_state()` reads the row back by stable id,
   owner-scoped, with a renderer per domain; `outcome_grounding.read_back()` /
   `render_current_state()` pair each outcome with what its record says now, and
   the judgement is turn-level. Wired into the real turn at
   `main_simple._finalize_response_content`. 91 cases across
   `test_outcome_grounding.py` and `test_grounding_through_the_chat_turn.py`,
   including one where the tool reports the wrong time and the reply carries the
   ROW's time, and one where another owner's row is never read back.
3. **No recovery for an explicit request that produces no tool call** — the reply
   is honest but the request is simply lost.
   **IMPLEMENTED 2026-09-29, deterministic evidence.**
   `app/services/request_recovery.py` derives at most one call from David's own
   words and executes it through `execute_tool`, so the contract authorizes it
   and the durable receipt gives it idempotency. Four independent bounds: one
   attempt per turn, one identified operation, one resolved target, no invented
   arguments (CREATE/CAPTURE/UPDATE are excluded by design). 18 cases in
   `tests/test_request_recovery.py` plus 3 end-to-end through the real turn.
4. **Correction/background work unfinished; API and workers not pinned** to the
   same candidate.
   **IMPLEMENTED 2026-09-29, deterministic evidence.** All five worker roles
   (general on `cognitive,health,input,maintenance,low_priority,reflection,dispatch`,
   then `critical`, `david_priority`, `acs`, beat) are declared in
   `docker-compose.reliable-assistant.yml`, each mounting the same
   `${ASSISTANT_ACCEPTANCE_SNAPSHOT}` at `/app` as `api` does, and the
   `isolated-worker` profile was actually **started against the candidate**: each
   printed its own queue set, four answered `celery inspect ping` over the
   disposable broker (`4 nodes online`), and a sha256 over the four modules this
   task owns is identical in all five containers and on the host snapshot
   (`c9b52336eed7c4f8`). The missing correction operation —
   `workout_log_correct` — is implemented, registered, and covered by 14 cases in
   `tests/test_workout_set_correction.py`. *Still open:* journey J5
   (background/documents) has never been run, so background **workflow** behavior
   is unverified; what is verified is that the workers boot and consume on the
   candidate's bytes.
5. **Assembled conversational instructions need simplifying** — the father,
   breakfast and unwanted-advice cases still fail the original objective.
   **IMPLEMENTED 2026-09-29, deterministic evidence.** Three overlapping
   sections (Voice, Priority, Conversation, ~2,540 chars) became two
   non-overlapping ones (~1,420 chars): each distinct rule appears exactly once.
   The prompt cap dropped 7,800 → 6,750 so the freed characters are given back
   rather than spent on soul tail. 41 cases in `tests/test_chat_system_prompt.py`.
   **Whether the model's behavior on those three cases changes is NOT
   established** — that is a live-conversation question and no live check has
   been run against the simplified prompt.
6. **No exact candidate image, no candidate-sourced migration run, no genuinely
   tested recovery destination.**
   **IMPLEMENTED 2026-09-29, deterministic evidence.**
   `backend/scripts/build_reliable_candidate_image.sh` builds
   `sara-reliable-candidate:20260929` on the validated `jarvis-backend:latest`
   dependency layer and verifies the code INSIDE the image against the validated
   manifest (916/916 files, manifest sha256
   `27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d`).
   `backend/scripts/rehearse_reliable_release.sh` runs the release and its
   recovery on disposable databases — see "Release rehearsal" below.

Plus: the extra deterministic failures must be established as unrelated by
**controlled-clock comparison**, not by file modification dates.
`backend/scripts/controlled_clock_suite_compare.sh` does exactly that: it runs
the same selection against the 2026-09-24 frozen source snapshot and the
candidate, minutes apart, each against its own freshly created database, and
prints the three-way split (both / baseline only / candidate only). Its stated
limit: the baseline also predates David's own 09-25..09-28 working-tree changes,
so a candidate-only failure could belong to either, and the module path has to
decide which.

**What all six have in common: none has live evidence.** 304 deterministic tests
pass; no generation has been spent on any of the six changes. Implementation is
not verification, and the release document does not request deployment approval.
23 requests remain of the 300 ceiling — see `SARA_RELIABLE_ASSISTANT_RELEASE.md`
§7 for the five-turn spot-check they would buy and the 200-request allocation the
plan's actual bar needs.

What is preserved from the work so far, because it has evidence:
the domain operations (`notes_correct_fact`, `reminders_reschedule`,
`reminders_update`, `list_correct_item`, `food_log_correct`), the read-cache
write-invalidation, the one timestamp contract, the tool-registry contract audit,
the home-control state confirmation, and the live journey passes J1/J2/J3
(12/12, 12/12, 7/7 on two trials each) with their transcripts and state dumps.

## Candidate identity

| | |
|---|---|
| working source | `/home/david/jarvis/backend` (David's dirty tree, HEAD `e3651cd7`) |
| pre-edit preservation | `/home/david/sara_patch_snapshots/preedit_reliable_assistant_20260928/` — `preedit_source.tar.gz` (sha256 `1098ee554129f4aef14a07c5ad6c0f6f492ef27340a3a0c7a6a5aa0a648604a3`) + `PREEDIT_MANIFEST.sha256` (3,950 files, manifest sha256 `94c3ea15712be0b050acf9d362ce0eeacd45cc6f3f5c4f5453bac3db72b19c7b`) |
| prior frozen candidate | `/home/david/sara-candidate-20260927-rc2` — manifest verified 904/904 clean; its `backend/app` was **byte-identical** to the pre-edit working tree, so the working tree *was* rc2's source and no candidate reconciliation was needed |
| this task's candidate | `/home/david/sara-candidate-20260928-reliable` — **916** files under manifest (`backend/app` + `backend/alembic`), manifest sha256 `27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d`; re-freeze with `backend/scripts/refreeze_reliable_candidate.sh` |
| candidate **image** | `sara-reliable-candidate:20260929`, built by `backend/scripts/build_reliable_candidate_image.sh` on the validated `jarvis-backend:latest` dependency layer; code inside the container verified 916/916 against the manifest, and the six modules this task added or rewrote import inside it |
| schema target | alembic `158_reminder_delivery_state` (migrations 155–158 are untracked files in the working tree; **no new migration was added by this task**) |
| production right now | `jarvis-backend-1` started 2026-09-22T22:54Z from `docker-compose.dev.yml`, no `--reload`, over a bind mount — a process image whose source is no longer on disk. Schema 154. Read-only inspection only; nothing here has touched it. |

## Generation budget

Hard task-wide ceiling **300**, enforced by the gateway's atomic pre-forward
reservation against an append-only ledger
(`backend/tests/assistant_acceptance/artifacts/run_20260928_reliable/reliable_assistant_ledger.jsonl`).

Enforcement was proven **before** the first real generation, with a fake
upstream, at zero model cost: `backend/tests/test_generation_budget_gateway.py`
(8 cases) runs the real `gateway.py` in a subprocess and shows it forwards
exactly the ceiling and then 429s, that the reservation is written before
forwarding, that a restart does not hand out a fresh budget, that metadata
requests do not consume it, and that no path or Host header can redirect it.

| | |
|---|---|
| reserved | **277** (completed 277, failed 0, rejected 0) |
| remaining | **23** |
| spent on | 1 routing canary; 4 development/verification passes; 1 frozen acceptance trial (5 journeys); 12 conversation cases; 1 four-case conversation re-verification |

Historical allocations (the convention task's 60 ceiling, the 09-24 study's
1600) are separate and are neither credited nor debited here.

## Deterministic baseline and current standing

Disposable stack `docker-compose.test.yml` (project `sara-disposable-test`),
production-shape schema fixture stamped `154_saved_meal` then
`alembic upgrade head` → `158`.

### Controlled-clock comparison (2026-09-29)

The correction required this and was specific about why: *"file modification
dates alone do not establish that a failure is unrelated."* They do not — several
tests in this suite are time-sensitive by design, and an mtime says only when
somebody saved a file. `backend/scripts/controlled_clock_suite_compare.sh` runs
the same selection against two trees minutes apart, each on its own freshly
created database, in the same image:

| | baseline (2026-09-24 frozen snapshot) | candidate |
|---|---|---|
| passed | 2,366 | **3,040** |
| failed | 56 | 57 |
| errors | 25 | 25 |
| started | 14:32:58Z | 14:36:31Z |

**56 of the 57 candidate failures are present in the baseline at the same
moment.** The three-way split (both / baseline-only / candidate-only) is the
reconciliation; the earlier "nine extra failures" count is superseded, because it
was a point-in-time figure from one late-night run and the clock-sensitive
families it named (`test_unified_notification`,
`test_singular_sara_c5_fold_in`) do not reproduce at this hour while 56 other
failures do. (Rows N36, N37.)

**Stated limit.** The baseline also predates David's own 09-25..28 working-tree
changes, so a candidate-only failure could in principle belong to either. That is
exactly why the single candidate-only failure was taken to a demonstrated cause
rather than attributed:

* `test_location_freshness.py::…[observed_at2]` — the parametrized instant is
  `datetime.now(timezone.utc) + timedelta(minutes=2)`, evaluated once at module
  import. Once a suite takes more than two minutes to reach the test, that value
  is neither future nor yet stale (the window is ten minutes), the guard under
  test never fires, and execution reaches `classify()` with the
  deliberately-`None` db. It passed in **both** trees run alone, and calling
  `process_report` with the same instant after two minutes reproduces the
  identical `AttributeError` on unmodified product code. This task lengthened the
  suite (~170 added tests), which is what exposed it. **Fixed in the test only**;
  product code untouched. (Row N36.)

### This task's own tests

**304 passing**: `test_operation_contract.py` (124),
`test_outcome_grounding.py` + `test_grounding_through_the_chat_turn.py` (91),
`test_request_recovery.py` (18), `test_workout_set_correction.py` (14),
`test_chat_system_prompt.py` (41), `test_active_domain_tool_retention.py` (10),
`test_civil_time_contract.py` (24); plus `test_generation_budget_gateway.py` (8)
run separately against a fake upstream.

The one xfail is mine and deliberate: 50 declared tool properties across 15
tools carry no description (row N06), kept visible as a strict xfail rather
than fixed or dropped.

An infrastructure fix was needed before the baseline could run at all:
`pytest.ini` now has `norecursedirs` excluding `artifacts`/`source_snapshot`,
because study runs freeze a full source snapshot (with its own
`tests/conftest.py`) under `tests/**/artifacts/`, which shadows the real
`tests.conftest` and aborts collection.

## What was built

### Phase B — conversation

`app/prompts/chat_system_prompt.py` gained a `## Conversation` block: one rule
per behavior the 2026-09-28 review found in the transcripts — answer the
invitation, don't explain his feelings back to him, don't say what something
"means", don't grant permission he didn't ask for, don't invent shared history,
follow a topic change, "no advice" means none, let an ending end, anticipation
is having the answer ready rather than volunteering it. `MAX_PROMPT_CHARS`
6500 → 7800 so the soul keeps the exact character budget it had.

Measured while doing it: with the real ~3,400-char DB soul the prompt has
**always** been capped, trimming ~1,500 chars off the soul's growth section
every turn. Pre-existing and deliberate (trim the soul, never drop a truth
rule); recorded as row N02 so it is not read as new.

### Phase C — one operation contract

**New `app/services/operation_contract.py`.** Replaces `has_action_intent`'s
single boolean as the authorization authority with the three facts it cannot
express: `UtteranceClass` (question / hypothetical / reported / correction /
instruction / capture / confirmation / acknowledgement / social),
`OperationKind` (read / capture / create / update / reschedule / complete /
cancel / delete / recurring / control), and `requested_operations()` derived
from verb *semantics*. Plus an authority matrix, an operation-equivalence
table, `domain_for_tool()` shared by the resolver / log / read cache, and
structured `OperationDecision` records in which a withheld call is as auditable
as an executed one.

Authority comes from the shape of the act plus a resolved target, never from
list membership — which is how "Scratch the vet one" is authorized without
"scratch" being added anywhere.

**New `app/services/reference_resolution.py`.** Resolves a reference once,
owner-scoped, returning structured candidates. Fixes two defects in the bool
version it supersedes: the 4-character minimum that made "the vet one"
invisible, and the total absence of a candidate search, which collapsed "which
one?" into a refusal.

**One boundary.** `execute_tool` makes the decision; the two round-level
duplicate target-authorization call sites were removed as a second, stricter
policy authority for the same question (row N03). What genuinely needs the
whole round — same removal tool, second distinct target, no bulk language —
stays, routed through the contract.

**Selection reads the same classification** (`selection_kinds_for_message`), as
a widening of the old verb gate, never a narrowing — because "routing must not
silently make a supported action impossible", and twice in live runs it did.

### Phase C4 — domain operations that did not exist

`reminders_reschedule`, `reminders_update`, `notes_correct_fact`,
`list_correct_item`, `food_log_correct`. Before these, "move the vet one to
seven" and "make that two gallons, not one" had only two available shapes:
cancel-and-recreate (findings 28/35's duplicate) or nothing.

### Phase D — durable evidence and truthful replies

**New `app/services/outcome_grounding.py`.** A per-turn ledger of every write
and which of **seven** distinguishable outcomes it got, claim detection over
the reply, and an authoritative renderer. Outcomes are recorded at the boundary
on all three branches (refusal, success, raised exception); grounding runs last
inside `_finalize_response_content`, so the persisted text and the sent text are
one string. Entity binding is by the target's own distinctive words, never by
sentence position.

**Streaming**: on a turn that attempts a write the deltas are held and the
grounded text is emitted once. A turn that writes nothing still streams token by
token. Both clients already treat `final_response.content` as authoritative, so
no app rebuild is needed.

**`session_cache`** gained domain-scoped write invalidation (finding 22 — eight
read tools cached 30 minutes with no invalidation anywhere, "Cache HIT" logged
immediately before a false denial). Index-set based, not a `SCAN`; an entry that
cannot be indexed is dropped rather than left un-invalidatable.

### Phase E — corrections

`notes_correct_fact` is the one route. It replaces the stale value everywhere it
is asserted as current **including the title**, records the previous value under
a `## History` heading, and leaves **dated** lines alone so "Priya moved
companies" does not falsify the record of a meeting that really happened at
Globex. It refuses without changing anything when the old value is not there.

This replaces the appended-correction strategy whose cost the convention run
measured: a note titled "Priya Raghavan — Globex" whose body asserted Globex and
then contradicted itself.

### Phase F — across the platform

* **One timestamp contract** (`app/services/civil_time.py`): a naive time is
  David's wall clock (finding 16: a naive 7pm was stored as 19:00 UTC, i.e. 3pm
  his time), an offset is authoritative, a bare date is 9am local, and DST
  ambiguity has a *stated* policy with a user-facing note. Reminders, timers'
  readers and the food log now share it with the calendar (finding 37).
* **Food day attribution** (row N07): `logged_at` holds UTC and the day queries
  compared it to bare dates, so every meal after ~8pm ET counted on the next
  day. The day windows are now his local days.
* **Lists**: canonical names so "grocery"/"groceries"/"Grocery List" is one list
  (finding 11), a no-op reported as failure rather than success, and stable
  ordering between reads (row N08).
* **Home control** (finding 21): `ha_control_service` reads the entity state
  back and distinguishes accepted from confirmed. A lock that does not move is
  no longer a success.
* **Tool registry audit**: `execute_tool` adapts a dict-shaped return (logging
  it as a contract bug), reports any other non-`ToolResult` as "did not run",
  and reports a `TypeError` as a signature mismatch — finding 4's two bugs,
  which made `start_workout` completely non-functional and went undiagnosed
  across multiple studies because nothing checked the contract. A registry-wide
  audit now asserts schema, signature and return contracts for all 242 tools,
  and found five reads misclassified as writes plus one write misclassified as a
  read (rows N04, N05).

## What the live development pass found

Nine defects the deterministic tests could not have found, all reproduced live
and recorded as rows N09–N16 with their mechanisms. The most instructive:

* "**Set a reminder to call the vet at 5pm**" — the canonical phrasing — was
  refused, because "set" is genuinely an update verb. Fixed by recognizing the
  indefinite object, not by adding a word.
* "**And one for the dentist on October 2nd at 9am**" was refused twice, in two
  different shapes: first because ellipsis was not represented, then because the
  boundary's view of "what ran last turn" was **always empty on the real
  /chat/stream path** (it popped the entry for its own gate before the boundary
  peeked, under a different key). The continuation path that has existed since
  2026-09-25 had therefore never fired live at all.
* A **truthful readback was repaired away**: "it's set for 5pm" on a status-only
  turn was read as an unsupported completion claim. Claim detection is now
  narrowed to action claims, with the limitation stated in the module.
* A **requested change that ran no tool at all read as done**: "That was
  actually 150 grams, not 100." → "Got it — 150g, not 100. That's 248 calories
  and 46.5g protein." with zero tool calls and the row still at 100g. No claim
  pattern can catch that; a turn-level "a change was requested and nothing was
  written" check does.
* "**Make that two gallons of milk, not one**" created a duplicate: the only
  verb it matched was "make" (a creation), so the correction tool was refused
  and the add succeeded.
* "**Cancel the plant one**" cancelled the wrong one of two equally-matching
  reminders.

## Live results

One frozen acceptance trial on manifest `e19baca7…`, scored against hidden
outcome cards evaluated in SQL against database state dumps:

| journey | verdict |
|---|---|
| J1 notes/facts — capture, natural correction, fresh-conversation retrieval, challenge | **PASS 12/12** |
| J2 reminder — create, status-only readback, change, targeted cancel, sibling intact | **PASS 12/12** |
| J3 tasks/lists — add, inspect, correct, complete the named target, unrelated unchanged | **PASS 7/7** |
| J4 food | **FAIL 1/3** — the correction tool was never offered (routing, N18) |
| J6 mixed day | **FAIL 4/6** — the model called no tool on an explicit request (N19) |

J1/J2/J3 passed on an earlier trial too, so those three have two trials; J4 and
J6 have one. **The plan's two-trial bar for all six workflows is not met**, and
journey 5 (background/documents) was written and never run — the allocation went
to diagnosing and fixing the 17 defects the live passes exposed instead.

All 12 conversation cases ran. Four were contaminated by a grounding false
positive this run itself exposed (N26 — machinery appended to a joke, a vent, and
a disclosure about David's father); the fix is **verified live on those exact
four cases**.

**All of the above predates the 2026-09-29 changes.** The trial ran on manifest
`e19baca7…`; the candidate is now `27932826…`. Specifically, those transcripts
show the *old* three-section conversational prompt and the *old* word-matching
grounding layer, and none of them exercised the authorization narrowing, the
readback-by-id, request recovery, or the workout-set correction — those did not
exist yet. J4 and J6 failed on defects that have since been fixed
deterministically, which is a reason to expect them to pass and not evidence that
they do.

## Release rehearsal (2026-09-29)

`backend/scripts/rehearse_reliable_release.sh`, on disposable databases only —
tmpfs, an internal docker network, nothing production can reach:

| step | result |
|---|---|
| load the checked-in pre-release production schema capture | 302 tables; `chat_pending_proposal` and `revoked_token` absent, i.e. genuinely 154 |
| stamp `154_saved_meal` from the candidate image's own alembic | at `154_saved_meal` |
| dump it — **this is the recovery destination** | 554,106 bytes |
| `alembic upgrade head` from the candidate image's own alembic | 155 → 156 → 157 → 158 |
| every object the candidate queries | all present, including `reminder.delivery_status/claimed_at/delivery_attempts/last_error` |
| restore the dump into a fresh database | at `154_saved_meal`, `app_user` queryable, `saved_meal` present, `delivery_status` **absent** |
| the forward schema answers the queries that 401ed on 09-27 | yes |
| the candidate **image** serving against the released schema | starts and serves |

One finding from doing it, recorded as evidence row **N35**: `alembic upgrade`
**cannot** build the schema from an empty database — the first `ALTER TABLE` fails
with `relation "episode" does not exist`, because the migration history assumes a
pre-alembic baseline (already documented in
`docs/plans/incidents/2026-09-22_test_run_against_live_db.md` §7). A release or
recovery plan resting on "the migrations can rebuild it" would be a plan that
cannot recover. The rehearsal starts from the real captured schema instead. Not
fixed: changing the migration history is not something to do inside a release
rehearsal.

## Remaining work and known gaps

* **No live evidence for any of the six 2026-09-29 changes.** Deterministic only.
  23 generation requests remain; `SARA_RELIABLE_ASSISTANT_RELEASE.md` §7 names the
  five-turn spot-check those would buy and the ~200-request allocation the plan's
  actual bar (two reset trials of six workflows + 12 conversation cases) needs.
* **The two-trial bar is met for no workflow under the current code.** J1/J2/J3
  passed two trials each, but against the code as it stood *before* these six
  changes; J4 and J6 have one trial each and both failed on defects since fixed.
* **Journey 5 (background/documents) has never run.** The five worker roles now
  boot and consume on the candidate's bytes, which is not the same as a background
  workflow behaving correctly.
* **The prompt simplification is unmeasured.** The father, breakfast and
  unwanted-advice cases are why it was done; whether it works on them is unknown.
* **A 154-compatible source snapshot still does not exist.** The recovery
  *destination* is now built and used, but the code production runs today is a
  process image from 09-22 whose source is gone, so a defective candidate still
  means fix forward or downtime.
* **Recovery does not retry a FAILED write**, by design: it covers the turn that
  made no call. Re-running a failed write behind the model's back would be a
  second attempt at something David never saw the first outcome of.
* **18 compiled findings are reproduced/unfixed**, each named in the evidence map
  with why: cross-client stale reads, background-result indexing, the `ask_sara`
  lock, HRV date shift, weight units, recipe consumption snapshots, four
  intent-routing gaps, status-label paraphrase, `outbox_processor`, the six
  pre-existing `context_router` failures, and the migration-from-empty gap (N35).
* **Five findings are "superseded with evidence"** — pre-existing repairs (logout
  revocation, document-search fallback, timer naive/aware, reminder dispatch, email
  outage accounting) whose deterministic tests pass but which this task did **not**
  re-verify live.
* The release artifact contains changes made *after* the live development pass and
  after the frozen acceptance trial. The release document records the delta; the
  honest consequence is that the trial's transcripts show the *old* prompt and the
  *old* grounding layer.

## Disposition vocabulary in use

`verified fixed`, `implemented/unverified`, `reproduced/unfixed`,
`unsupported capability`, `environment-blocked`, `superseded with evidence`.
"done" is not used for implemented/unverified work. Across 88 rows: 3 are
`verified fixed`, 3 are `verified` (deterministic infrastructure facts), the
2026-09-29 implementation rows are `implemented/unverified` because that is what
they are, and nothing is claimed as live-verified beyond what the ledger and the
transcripts actually show.

# rc4 blockers — three failures, three contracts

Candidate `rc4-c5e3a085396d` · **NOT READY** · no further experiments run.

> **Implemented in round 8** — see the section at the end of this document.
> Blockers 1, 2 and 3 are closed in candidate `rc7-e5456f99026c` and
> verified across two concurrent live journeys; the targeted-cancellation
> failure is unrelated to these three and remains open.
Evidence: `backend/tests/assistant_acceptance/artifacts/run_20260926T161346Z_reminder_rc_freeze/e2e_rc4/`
(`journey_A_rc4.json`, `journey_B_rc4.json`, `api.log`,
`final_reminder_state.txt`). Full context:
[SARA_REMINDER_RELEASE_CANDIDATE.md](SARA_REMINDER_RELEASE_CANDIDATE.md) §24.

These are three separate application-contract failures. Only the third
involves the model saying something wrong, and even there the wrong
statement is downstream of a contract the application did not enforce.

---

## Evidence missing for all three

Stated once, because it applies to every entry below.

| Missing | Why |
|---|---|
| **`action_receipt` rows — operation identity for every rc4 turn** | The harness query selected a column `target_id` that does not exist (the column is `target`). It returned an error instead of rows, so **no operation identity is available for any rc4 turn**. Every "operation identity" field below is unavailable for this reason, not because nothing was written. |
| **Arguments of withheld tool calls** | Arguments are logged at execution (`🔧 Tool X - raw arguments string`). A withheld call never executes, so its arguments were never logged. |
| **The removal-history contents at decision time** | The guard logs its verdict (`🚫 Withholding N …`) but not the target set it compared against. An authorization refusal therefore cannot be audited after the fact — see Blocker 3's open question. |
| **`gate_mutating_tools` / `has_action_intent` decisions** | Not logged at all. Which tools were *offered* for a given turn, and whether the execution boundary evaluated a call, cannot be recovered from the preserved artifacts. |

---

## Blocker 1 — a readback created a reminder

**Journey B, T2.** `client_message_id` `88b3b545-34a7-4f18-892f-8f2aefc6c6a9`,
conversation `425e8d21-57af-4312-871f-d938a598ead5`, sent `20:06:33Z`.

**User turn, verbatim:**
> Read that back to me - what time is it set for?

**Tools.** Offered: *unavailable* (not logged). Executed: `reminders_create`
— one call, round 1, completed. No read tool was called at all.

**Authorization decision.** No refusal was logged for this turn; the call
executed. Whether `reminders_create` was offered by `gate_mutating_tools`
for this message, or offered and then passed by the execution boundary,
is **unavailable**.

**Operation identity.** Unavailable (see above).

**Rows.** Before — 3 reminders: `Take the car in for its inspection`
`2026-09-27T11:45Z`; `Call the bank about the mortgage` `14:00Z`;
`Pick up the dry cleaning` `21:30Z`.
After — 4: a new row `Take car in for inspection` at the **same
`11:45Z`**, id `2b3472d3-6a9a-4b0e-956d-d84fd178560c`.

**Response:**
> Set — **7:45 AM tomorrow (Sunday, September 27)** to take the car in for inspection.

**Contract that should have prevented it.** The mutation-authorization
boundary — `has_action_intent` / `gate_mutating_tools`. *"Read that back
to me — what time is it set for?"* carries no action intent; a write tool
should not have been offered for it, and if offered, the execution
boundary should have refused the call. This is the same class as Part I
§5.3 (a status question authorizing a write) on a phrasing the lexicon
does not cover. The reply is consistent with what the application let
happen; the model was not contradicted by the system.

Secondary contract, independently sufficient: **two identical reminders
at the same instant for the same user should not both persist.** Nothing
in the create path treats "same title-ish, same user, same instant" as a
duplicate, so the readback's spurious call had nothing to stop it at the
data layer either.

---

## Blocker 2 — a reschedule left duplicates

**Journey B, T4.** `client_message_id` `ad344f4b-72a3-4851-b230-db7d93d2d192`,
same conversation, sent `20:09:43Z`.

**User turn, verbatim:**
> Push the car inspection reminder back to 9:15am.

**Tools.** Round 1: `reminders_list` (executed). Round 2, one batch of
three: `reminders_cancel`, `reminders_cancel`, `reminders_create`.

This is a **correct reschedule plan**: cancel the two 7:45 rows (the
original plus Blocker 1's duplicate), create one at 9:15.

**Authorization decision — the failure.** `api.log`, `20:10:42Z`:

```
🔍 Round 1 - Tool calls: ['reminders_cancel', 'reminders_cancel', 'reminders_create']
🚫 Withholding 2 ambiguous same-turn removal call(s) — multiple targets,
   no bulk language: ['reminders_cancel', 'reminders_cancel']
🔧 Tool reminders_create - raw arguments string:
   '{"title":"Take the car in for its inspection","reminder_time":"2026-09-27T09:15:00"}'
```

Both cancels were withheld. **The create in the same batch executed.**

**Operation identity.** Unavailable.

**Rows.** Before — 4 (two at `11:45Z`). After — 5: both `11:45Z` rows
still active, plus a new `Take the car in for its inspection` at
`2026-09-27T13:15Z` (9:15 AM local), id
`b24040d9-1f4c-453d-b7eb-10cf4b886186`.

**Response:**
> The 9:15 AM one is set for Sunday. But heads up — there are still two old 7:45 AM car-inspection reminders sitting there, and I couldn't remove them without your OK. Want me to drop both?

The reply is **accurate**. The model reported the outcome correctly. The
state is still wrong.

**Contract that should have prevented it.** The same-turn removal guard
(`find_ambiguous_same_turn_removals`) is applied **per removal call, with
no relationship to the rest of the batch**. A reschedule is a
cancel-and-create pair; withholding the cancels while executing the
create converts a safe refusal into a duplicate. The guard needs
all-or-nothing semantics over a turn's write batch: if any write in a
coupled set is withheld, none of the set may execute.

Note the guard itself behaved as specified — two distinct targets, no
bulk language. The defect is the absence of batch atomicity around it,
not the threshold.

---

## Blocker 3 — responses contradicting committed state

Two instances in journey A, with different causes. Both are in
conversation `122ba5a9`/`94199490`.

### 3a — a committed reschedule reported as not done

**Journey A, T4.** `client_message_id` `db0a4ace-9fcd-442c-8a95-4a4c355ccc08`,
sent `20:10:12Z`, elapsed 243 s.

**User turn, verbatim:**
> Thanks, that's great.

**Tools.** Executed: `reminders_create`, at `20:12:40Z`, arguments
`{"title":"Call pharmacy about prescription","reminder_time":"2026-09-27T16:30:00"}`
— i.e. the turn tried to re-create the reminder the previous turn had
already moved.

**Authorization decision.** No refusal logged for this call.

**Operation identity.** Unavailable — and this is the field that matters
most here. Whether the create was suppressed as a replay of T3's
committed operation, or attempted and lost some other way, **cannot be
determined from preserved evidence**.

**Rows.** Before and after are identical: no row added, none changed.
The committed state from T3 was and remained correct —
`Call the pharmacy about your prescription` `2026-09-27T19:00Z`
`is_completed=t` (superseded) and `20:30Z` `is_completed=f` (active), i.e.
exactly one active occurrence at 4:30 PM local.

**Response:**
> To be straight with you — I didn't actually get that change through when you asked. I misspoke earlier. Say it again and I'll do it for real: move the pharmacy call to 4:30 PM tomorrow?

**This is false.** The change had committed at T3, and T5 read it back
correctly two turns later.

**Contract that should have prevented it.** A turn may not assert the
outcome of an action without reading the persisted record of it. The
pieces exist and are not wired to the final answer:

* `action_receipt` records committed operations, and `verify_action`
  (round 3) exists precisely for *"did you actually do that?"* — nothing
  requires the reply path to consult either before denying an action;
* round 6 added `recently_resolved` to `reminders_list` so a readback can
  distinguish cancelled / delivered / failed / undetermined from
  persisted columns — this turn called no read tool at all;
* `tool_success_state` computes a tri-state outcome per write, and
  `_last_resort_reply` is required to "name what actually ran" — but only
  on the last-resort path, not on a model-authored final answer.

An acknowledgement ("Thanks, that's great.") should also not have reached
a write tool at all — the same Blocker 1 contract, independently.

### 3b — a withheld cancellation presented as a timing outcome

**Journey A, T7.** `client_message_id` `4a57f3f5-cd6e-443f-8511-d0ae6cbf59eb`,
sent `20:17:18Z`, elapsed 135.7 s (reply composed ≈ `20:19:34Z`).

**User turn, verbatim:**
> Actually cancel the one about emailing Priya the invoice.

**Tools.** Round 1 `reminders_cancel`; round 2 `reminders_list`
(`{"limit":10}`).

**Authorization decision.** `api.log` `20:18:44Z`, in this turn's
conversation:

```
🚫 Withholding 1 ambiguous same-turn removal call(s) — multiple targets,
   no bulk language: ['reminders_cancel']
… tool response: '{"success": false, "message": "Not executed:
   reminders_cancel wasn't clearly authorized by what Da…'
```

The cancellation was **refused by the authorization boundary**, 16
seconds before the reminder was due.

**Open question, evidence missing.** The turn's transcript records a
single `reminders_cancel`, yet the guard reported "multiple targets",
which requires two distinct argument strings for that tool in this turn.
The withheld call's arguments and the removal history it was compared
against are **both unlogged**, so the reason cannot be established. Two
candidate mechanisms — a second cancel attempt not captured in the
transcript's tool events, or the deadline-write path recording an
additional target — are **not distinguishable from preserved evidence**
and no experiment was run to separate them.

**Operation identity.** Unavailable.

**Rows.** `Email Priya the invoice` was never cancelled:
`is_completed=f`. It was delivered at `20:19:04Z`
(`delivery_status=sent`, sink receipt in `push_sink_ledger.jsonl`), 106
seconds after the user asked for it to be cancelled and 30 seconds before
the reply was composed.

**Response:**
> That one already went off at 4:19 — it's been delivered, so there's nothing left to cancel. (The bread one fired at 4:18 too, same deal.)

**Correction to an earlier characterisation of this turn.** This
statement was **true at the moment it was composed** — the delivery had
happened 30 seconds earlier. An earlier summary described it as claiming
a delivery that was still in the future; that was wrong. The failure is
not the sentence's truth value.

The failure is that the user asked for a cancellation with 102 seconds to
spare, the authorization boundary refused it, and the reply attributed
the outcome to timing rather than to the refusal. The user is left
believing the request arrived too late, when in fact it was declined.

**Contract that should have prevented it.** Two, in order:

1. **A single-target cancellation with an explicit referent must not be
   refused as a multi-target sweep** — the same contract Part III fixed
   for the cross-user case (§18). Whatever produced a second target here
   is unresolved, and the guard's decision is unauditable because it does
   not log its inputs. *That* — an authorization decision with no
   recorded basis — is itself a contract gap.
2. **A turn that withheld a write must not describe the outcome as
   anything other than withheld.** The refusal string is returned to the
   model as an ordinary tool result and paraphrased freely. A withheld
   write is a fact the application knows; the final answer is not
   required to carry it.

---

## Summary

| # | Failure | Contract that should have prevented it |
|---|---|---|
| 1 | Readback created a reminder | Mutation-authorization boundary: no write tool for a message with no action intent. Secondarily, no same-user/same-instant duplicate guard on create |
| 2 | Reschedule left duplicates | No atomicity between a withheld removal and the paired create in the same batch — a coupled write set must be all-or-nothing |
| 3a | Denied a committed change | No requirement that a claim about an action's outcome be sourced from `action_receipt` / persisted state before it is made |
| 3b | Withheld cancel reported as "too late" | Single-target cancel refused as a sweep (cause unresolved, decision unauditable); and a withheld write not required to surface as withheld in the reply |

Only 3a is a case of the model stating something the record contradicts.
Blocker 1 is an authorization gap the model's reply correctly described;
Blocker 2's reply was entirely accurate about a wrong state; Blocker 3b's
reply was literally true and still misleading. **Attributing all three to
narration would hide three distinct application defects.**

None of these is the defect rc4 was built to fix. Request isolation under
concurrency held throughout both journeys — zero cross-user
contamination, and the rc2 failure did not recur (§24.1).

---

# Implementation — round 8 (2026-09-26 21:06–22:40Z)

Candidate **`rc7-e5456f99026c`** · patch `patch/RC7_FROM_HEAD.patch`
(53 files, 14,962 lines, verified to reproduce the frozen tree
byte-for-byte from `git archive HEAD`) · evidence in
`…/run_20260926T161346Z_reminder_rc_freeze/{e2e_rc5,e2e_rc6,e2e_rc7}`.

**Verdict: NOT READY.** Three blockers closed and verified live; one
required check (targeted cancellation) still fails in one of two
journeys, and the request budget was exceeded — see Accounting.

## What was built

**1. Evidence (`app/services/turn_evidence.py`, alembic 159).** The
receipt query is fixed (`target`, not `target_id`). Every turn now
records, in the turn's own context and persisted to
`chat_turn_trace.decisions`: request identity, the offered tool menu with
its basis, each authorization verdict **with the comparison it made**,
proposed calls, withheld calls with reasons, execution outcomes, and
committed writes. `redact()` stores argument KEY NAMES and a digest,
never values; only id-shaped keys keep their value, because an opaque
handle is the evidence. rc4's unauditable refusal is now a row:

```json
{"kind":"withheld","tool":"reminders_cancel","reason":"not_authorized_by_turn_message",
 "target":"68ec646c-e30c-4d0c-a0b1-c96bb519e49e","keys":["reminder_id"],
 "args_digest":"a9e544d96c1703cf","at":"2026-09-26T22:33:31Z"}
```

**2. Read-only requests (`is_read_only_request`).** Root cause pinned
first: `has_action_intent("Read that back to me - what time is it set
for?")` returns **True**, because "...is SET for" matches the verb
lexicon. Rather than add a verb, this adds the converse test — is every
clause a request to REPORT state? — enforced at the execution boundary
and one-directional: it can only refuse, never authorize. A scoped
confirmation is exempt via the same predicate the proposal path uses.

**3. Atomic reschedule (`reminders_reschedule`, alembic 160).** One
owner-scoped `UPDATE … RETURNING`, state-checked, that bumps
`delivery_revision`. No cancel/create batch for a partial refusal to
corrupt. The dispatcher captures the revision at claim time,
re-checks it immediately before sending (`_revision_unchanged`),
abandons a superseded claim without consuming a retry
(`_abandon_claim`), and scopes the outcome write to that revision — so a
reschedule landing mid-dispatch cannot let the old occurrence fire.

**4. Answer grounding (`app/services/answer_grounding.py`).** Applied in
the turn wrapper, covering every return path. Two checks: this turn's
committed writes may not be denied, and a withheld write may not be
called done or "too late". A second check compares claims against
**persisted rows**, which is what caught rc6's cross-turn case.

## What the live runs proved, in order

Three frozen candidates, each with two concurrent journeys. **Each fix
was found by the previous run, not predicted.**

| | rc5 | rc6 | rc7 |
|---|---|---|---|
| Readback writes nothing | A pass / **B FAIL** | pass / pass | pass / pass |
| Reschedule leaves one row | pass / pass | pass / pass | pass / pass |
| No false statement | **A FAIL** | **A FAIL** | pass / pass |
| Targeted cancellation | pass / **B FAIL** | pass / **B FAIL** | pass / **B FAIL** |

* **rc5 → rc6.** Journey A refused the readback's write; journey B, with
  the identical message, crossed the turn deadline, took
  `_run_pending_writes_past_deadline`, and created a duplicate. The
  contract was on one of two write paths. Fixed, with a test that asserts
  both paths consult it.
* **rc6 → rc7.** Journey A's T8 said *"Priya's invoice reminder is still
  set"* about a reminder the previous turn had cancelled. The
  application had supplied the truth — `reminders_list` returned
  `recently_resolved: [("Email Priya the invoice","cancelled")]` plus an
  explicit `absence_is_not_cancellation` note — and the answer
  contradicted it anyway. The turn-scoped check could not catch it
  (that turn wrote nothing), so grounding now also compares claims
  against persisted rows.

**rc7, both journeys:** every reschedule went through
`reminders_reschedule`, produced exactly one occurrence at
`delivery_revision = 1`, and created no duplicate. No readback wrote. No
statement contradicted the database. Journey A is clean end to end —
including a targeted cancellation whose sibling was delivered and whose
target never was.

## The remaining failure

**Journey B's cancellation, in all three runs.** *"Scratch the vet one, I
already called them."* → withheld by target authorization
(`not_authorized_by_turn_message`), so the reminder was delivered at
22:35:04Z. rc7's reply was honest about it — *"I hit a snag cancelling
that one — the system wanted me to confirm the target"* — which is the
behaviour blocker 3 asked for, but the user's explicit cancellation still
did not happen.

This is **not** one of the three blockers implemented here, and it was
not introduced by them: it is the same refusal rc4 §24.3 recorded. What
is new is that it is now auditable — the withheld call, its target id and
its reason are in `chat_turn_trace.decisions` (above), which is what
makes it a tractable next task rather than a mystery.

## Accounting

**Upstream requests: 105 of the 100 authorized — the budget was
exceeded by 5.** Gateway ledgers, reserved/completed, 0 unmatched:
rc5 34, rc6 37, rc7 34. Mid-run samples read lower (26/32/32) because
journeys were still in flight when sampled, and the third pair was
launched against those stale figures; a pair costs 34–37, so it landed
over. The error is in the pacing, not the ledger — the ledger is exact
and is the number reported here. Generation stopped at that point.

Cumulative across the engagement: 86 + 38 + 0 + 37 + 105 = **266** of
362 authorized (100 + 100 + 62 + 100).

**Active time:** 21:06:17Z → 22:40Z, ~1 h 34 m of the four hours.

**Deterministic:** 362 passed, 2 xfailed, 0 failed
(`tests/focused_rc7.txt`). 48 of those are new: `test_rc4_blockers.py`
(40) and `test_rc4_blockers_endtoend.py` (8), covering concurrency,
retries, the dispatch race, owner scoping, and failure injection.

Two inherited test files changed their success sentinel because
`_claim_for_dispatch` now returns a revision rather than a bool
(`is not None` instead of `is True`); the contracts they assert are
unchanged.

**Production untouched:** 15 containers, never restarted; all Compose
work through `disposable_compose.sh` with explicit projects
(`sara-rc5-test`, `sara-rc5-study`); the live working tree byte-identical
to its capture.

---

# Round 9 — targeted cancellation, and real budget enforcement

Candidate **`rc8-b64ae69f3a8f`** · **NOT READY** (no live verification run;
none authorized). Isolated diff from rc7:
`patch/ROUND9_rc7_to_rc8.patch` (6 files, 1,056 lines). Full delta from
`HEAD`: `patch/RC8_FROM_HEAD.patch` (57 files), verified to reproduce the
frozen tree byte-for-byte. **No upstream model generation was used.**

## 1. The cancellation, reproduced and named

`tests/test_journeyb_cancellation_repro.py` restores journey B's five
recorded rows and replays *"Scratch the vet one, I already called them."*
with the recorded arguments through each predicate the boundary consults.
The chain, in one line:

```
_distinctive_words("Call the vet back")  ->  {"back", "call"}
```

**"vet" was discarded for being three characters.** The message contains
"vet" and neither "back" nor "call" (it says "called"), so
`_text_evidences_words` returned False, `target_reference_evidenced`
returned False, and `find_target_unauthorized_mutations` blocked the call.
The reminder was then delivered — in rc4, rc5, rc6 and rc7.

Recorded alongside it, deliberately unfixed:
`has_action_intent("Scratch the vet one…")` is also **False** — "scratch"
is not in the verb lexicon. It is *not* what refused this call, and it was
not touched. A test pins that finding so a later reader does not add
"scratch" to a lexicon this report has three times called unclosable.

## 2. The fix, and proof it did not widen authority

`_distinctive_words` now keeps short identifying tokens (`vet`, `gym`,
`car`, `dr`, `tax`…) alongside the existing ≥4-character rule. **The match
rule is unchanged** — still "any resolved-title word appears in the
message" — so the set gains precision and loses nothing: a word that
identifies a row is strictly better evidence than the generic verb that
survived the old filter.

`tests/test_targeted_cancellation.py`, 30 checks, all against real rows:

| Must be authorized | Must still be refused |
|---|---|
| the exact journey B turn | a same-domain wrong target ("vet" turn → bank reminder) |
| five other wordings naming the vet reminder | every one of the four siblings, for that same turn |
| a longer-titled target ("dry cleaning") | four ambiguous references ("Cancel that one for me") |
| an identical retry | hypotheticals, negations and quoted instructions |
| | status-only questions naming the target |
| | one user's turn against another user's identically-titled row |
| | a second distinct target in the same turn (sweep guard intact) |
| | "Cancel the gym one" against the vet reminder |

**One real widening was found by these tests and closed.** With the target
now evidenced, *"Should I cancel the vet reminder?"* would have
authorized a removal — `has_action_intent` reads "should" as a request
marker. A deliberation guard now withholds intent from first-person
questions about whether to act ("should I", "shall we", "do I need to"),
while leaving second-person requests ("could you", "would you") exactly as
they were. It only ever withholds authority. A self-answered question in
one message ("Should I cancel it? Yes, do it.") is preserved, because
narrowing was the goal and losing a real instruction was not.

## 3. Budget enforcement

The gateway's reserve was already atomic under `flock`. The enforcement
failure was the **scope and size of what it enforced**:

* `BUDGET_CEILING` defaulted to **1600** — a throughput guard, not an
  allocation — so a 100-request task reached 105 with no check firing;
* `LEDGER_PATH` pointed at the **per-run artifact directory**, so rc5,
  rc6 and rc7 each began a fresh ledger at zero and counted 34, 37 and 34
  independently;
* the total was obtained by reading ledgers afterwards, and mid-run
  samples were stale because journeys were still in flight. That is
  accounting, not enforcement.

Changes:

* **`TASK_LEDGER_PATH`** — one ledger per task, mounted from a directory
  that persists across runs, deliberately *not* the run directory. Every
  run, journey, retry, classifier and background call reserves against it
  under the same exclusive lock. The per-run ledger still gets its own
  copy so each evidence directory stays self-describing.
* **`BUDGET_CEILING` is required** in compose
  (`${ASSISTANT_TASK_BUDGET:?…}`) — an unset allocation now fails loudly
  instead of silently permitting 1600.
* **`CARRIED_OVERAGE`** is subtracted: `EFFECTIVE_CEILING = ceiling −
  carried`.

`tests/test_budget_enforcement.py`, 12 checks with fake upstream calls:
exactly the ceiling is granted and the rest refused; 6 threads × 15
attempts against a ceiling of 20 grant exactly 20; **a second run
directory does not reset consumption** (the round-8 failure, asserted
directly); retries and background calls share the ceiling; a reservation
is never released and no release path exists; a carried overage of 5
reduces a 100 allocation to 95; **underspending a later allocation does
not erase the debt**; and reloading the gateway mid-task does not re-issue
the remaining allowance as a new budget.

**The five-request overage is preserved.** Round 8 spent 105 of 100.
Cumulative: 266 spent against 362 allocated, with the 5 recorded as a debt
to be applied as `CARRIED_OVERAGE` against the next allocation — not
cancelled by the 96 unused elsewhere.

## 4. Deterministic results

**411 passed, 2 xfailed, 0 failed** (`tests/focused_rc8.txt`) — 49 more
than rc7: 7 reproduction, 30 cancellation matrix, 12 budget.

## 5. Live-verification plan — NOT STARTED

No generation is authorized under the exhausted allocation, so none was
run. When an allocation exists, this is the narrow scope that would
verify rc8 — and nothing beyond it:

1. **Set the ceiling first.** `ASSISTANT_TASK_BUDGET=<allocation>`,
   `ASSISTANT_CARRIED_OVERAGE=5`, `ASSISTANT_TASK_LEDGER_DIR=<persistent
   dir>`. Confirm before any journey that the gateway logged the
   effective ceiling, and that a deliberate over-limit probe is refused.
2. **Two concurrent journeys, unchanged scripts.** The wording must stay
   *"Scratch the vet one, I already called them."* — the point is the
   phrasing the system previously refused, so substituting wording it
   already understands would prove nothing.
3. **The single new assertion:** journey B's vet reminder is
   `is_completed = true`, `delivery_status IS NULL`, and no sink receipt
   bears its title — the target cancelled, its sibling delivered.
4. **Regression watch, no new scope:** the eight per-journey checks rc7
   already passed (readback writes nothing, one occurrence after
   reschedule, no statement contradicting the database).
5. **Budget:** ~34–37 requests per pair. One pair. If it fails, preserve
   and stop — a fix makes a new candidate identity needing its own pair.

Estimated cost: one pair, ~35 requests, ~25 minutes.

## Status

`rc8-b64ae69f3a8f` stays **NOT READY**: targeted cancellation is a release
requirement, it is fixed and deterministically verified, and it has not
been demonstrated live. That is the only gate this round leaves open.

---

# Round 10 — rc8 live verification: FAILED

Candidate **`rc8-b64ae69f3a8f`** (frozen, unmodified during verification —
tree hash re-checked before the run). **NOT READY for deployment review.**
Evidence: `…/run_20260926T161346Z_reminder_rc_freeze/e2e_rc8/`.

## Result

| Required verification | Result |
|---|---|
| "Scratch the vet one, I already called them" cancels the correct reminder | **FAIL** |
| The cancellation action receipt exists | **FAIL** — no `reminders_cancel` receipt for journey B |
| The cancelled occurrence produces no delivery receipt | **FAIL** — it was never cancelled, and it was delivered |
| The intended sibling is delivered | pass (both journeys) |
| Readback performs no writes | pass (both journeys) |
| Reschedule leaves one reminder, supersedes the delivery revision | pass — one row each at `delivery_revision = 1` |
| Replies agree with committed state and refusal outcomes | **FAIL** (journey A, two ways) |
| User/conversation isolation intact | pass — no cross-user row, receipt or push |

Journey B, T7, verbatim: *"Couldn't get that one cancelled — the system's
refusing the action. The vet reminder is still set for 7:44."* Final
state: `Call the vet back | is_completed=f | delivery_status=sent |
notified_at set`. **Not cancelled, and delivered.**

## Why the round-9 fix did not hold

It fixed the predicate it was built for. The deterministic reproduction
isolated a *single* `reminders_cancel` call refused because
`_distinctive_words` dropped "vet"; 30 tests confirm that call is now
authorized, and the wrong-target, ambiguous, hypothetical, quoted,
status-only, retry and cross-user cases still refuse.

Live, the model emitted **two** `reminders_cancel` calls in T7
(`[['reminders_list'], ['reminders_cancel'], ['reminders_cancel']]`), so
the turn was refused by a **different** guard —
`find_ambiguous_same_turn_removals`, "multiple targets, no bulk
language", which fired three times this run. Target evidence was never
the only gate; the round-9 reproduction examined one call because that is
what the rc7 transcript recorded, and the rc8 run produced two.

This is a genuine miss in the reproduction's scope, not a regression: the
single-call path is fixed and stays fixed.

## Two further failures, journey A

**A false correction.** T7's reply was accurate — *"Done — the Priya
invoice reminder is cancelled. The bread one (7:41) is still live."* — and
the round-8 grounding layer appended: *"Correction: the record disagrees
— 'Email Priya the invoice' was cancelled. Disregard any line above
saying it is still set."* There was no such line. `_STILL_PENDING_RE`
matched "still live" (about the bread) while the title tokens matched
elsewhere in the sentence; the check does not require the pending claim
and the title to be in the same clause. **A grounding layer that invents
contradictions is worse than none**, and this is the first time it has
fired on a correct answer.

**A reply contradicting committed state.** T8 listed *"7:42 PM — Email
Priya the invoice"* as still live, one turn after cancelling it
(`is_completed = t`). The grounding layer did not catch this one.

## Budget

**Exactly 40 upstream requests — the authorized maximum, not over.**
Gateway ledger: `reserved=40`, `rejected_budget_exhausted=0`.

**The enforcement under test was not in effect, and I have to say so.**
The compose `build:` context for the gateway points at the live repo
path, which must not be modified, so the container ran the **pre-round-9**
gateway: ceiling 45 (the `CARRIED_OVERAGE=5` deduction was passed as an
env var the old code ignores) and the per-run ledger, not the task-wide
one. `$ASSISTANT_TASK_LEDGER_DIR` stayed empty.

The 40 limit was held by an external watchdog polling the ledger and
stopping the gateway at 40 — which is the polling-based control round 9
called inadequate, used here as a backstop. It fired at 23:43:33 with
both journeys already complete, so it changed no result. The correct
enforcement is verified only by the fake-upstream tests
(`tests/budget_refusal_demo_rc8.txt`, 12 passed, 0 real requests). **A
live run of the task-wide ceiling still has not happened**, and requires
building the gateway image from the candidate tree rather than the repo.

Spending: 266 prior + 40 = **306**. The 5-request overage was configured
for deduction but not applied by the running gateway, so it **remains
outstanding** and must still be carried.

## Image

`sara-reminder-rc:rc8-b64ae69f3a8f-baked` was built from the frozen tree
during the run. Its source identity was **not verified** and it is **not
claimed**: image verification was conditional on a successful run, and
earlier-image verification does not cover rc8. The `/app` manifest
comparison that closed the gate for rc4 has not been repeated here.

## Open gates

1. **Targeted cancellation** — still the release blocker. The multi-call
   shape must be handled: a turn whose repeated `reminders_cancel` calls
   all name the *same* resolved row is one intent, not a sweep.
2. **Grounding false positive** — clause-scope the state-claim check
   before it runs live again.
3. **Journey A T8** — a committed cancellation reported as still live.
4. **Budget enforcement, live** — build the gateway from the candidate.
5. **rc8 image identity** — unverified.

---

# Round 11 — deterministic replacements (no live validation requested)

**`rc8-b64ae69f3a8f` is preserved as FAILED** (round 10 evidence in
`e2e_rc8/`, unchanged). New candidate **`rc9-005dd17b07aa`**, frozen,
**deterministic evidence only** — no model generation, no deployment,
production untouched.

Patches: `patch/ROUND10_rc8_to_rc9.patch` (9 files, 1,306 lines) ·
`patch/RC9_FROM_HEAD.patch` (59 files), verified to reproduce the frozen
tree byte-for-byte from `git archive HEAD`.

## First: what the rc8 arguments actually show

The task's caution was warranted — my round-9 diagnosis was wrong in a
way that mattered. Reconstructed from `e2e_rc8/api.log`:

```
23:41:47  reminders_cancel  <arguments never logged>   WITHHELD
          "multiple targets, no bulk language"
23:41:53  reminders_cancel  {"reminder_id":"35dc057b-…"}   = "Call the vet back"
          the CORRECT row — reached execute_tool, then refused there:
          "no action evidence in this turn's message"
```

So a **third** guard refused it: the `execute_tool` boundary, whose test
is `_has_action_intent(turn_msg) or _via_continuation`. Round 9 recorded
that `has_action_intent` is False for *"Scratch the vet one…"* and
asserted it "is not what refused the call". **That was wrong.** The
target-evidence fix was real but addressed a predicate that was not the
one blocking this turn.

**The first call's arguments were never recorded**, so whether the two
calls named the same object cannot be established from the evidence. It
is not assumed anywhere: normalization keys on the RESOLVED id, so calls
collapse only when they demonstrably resolve to one row.

## 1. Cancellation — resolve once, execute once, one receipt

`app/services/cancellation_service.py`:

* `resolve_removal_target` — one owner-scoped resolution per call, reused
  by authorization, normalization and the receipt, so those three cannot
  disagree about the target.
* `authorize_named_removal` — a removal whose resolved row the turn
  *names* is authorized by that naming, independent of verb. Requires a
  removal tool, framing that does not withhold authority, an owned row,
  and turn text evidencing that specific row.
* `operation_key` / `claim_once` / `record_result` — duplicate calls for
  the same operation execute once and return the **same** receipt;
  distinct targets get distinct keys and separate authorization.

`is_non_action_framing` carries every guard `has_action_intent` would
have applied, including a **verb-independent** hypothetical marker — the
existing `_SELF_FUTURE_INTENT_RE` needs a known verb after the modal, so
it could not see "I might scratch…" for the same reason the lexicon could
not see "scratch".

## 2. Reminder responses — records, not regex

`app/services/answer_grounding.py` is **deleted**; the turn wrapper no
longer post-corrects prose. In rc8 it appended *"Correction: the record
disagrees"* to a reply that was correct — a "still live" clause about one
reminder matched a cancelled row's title tokens in another clause.
Clause-scoping would only relocate the guess.

`app/services/reminder_statement.py` renders facts from rows instead:
`status_line` / `status_block` (each reminder with its own outcome,
keyed by id) and `action_confirmation` (built from the row **after** the
write). `reminders_list` now returns `statement_of_record`;
`reminders_cancel` and `reminders_reschedule` return `confirmation`. The
model phrases these and has no independent source for a date, status or
outcome to regenerate.

## 3. Validation infrastructure — proven in a container

The gateway image is now built from the **candidate** source, and
`GET /__gateway_identity` returns the running module's own source hash
plus the effective budget settings. rc8 reported a configured task ledger
and an overage deduction while running an image that had neither.

Proof through the deployed container, fake upstream, ceiling 12 −
carried 5 = 7 (`tests/gateway_container_budget_proof.txt`):

```
source sha256 3e3425ee…  == candidate gateway.py     ✓
20 CONCURRENT requests -> {502: 7, 429: 13}, reserved = 7   ✓
docker restart          -> reserved still 7                  ✓
3 further attempts      -> 429, 429, 429; reserved still 7   ✓
```

Host-side tests and the polling watchdog are retained only as the
fake-upstream unit layer; the container proof is the one that counts.

## Regressions from the preserved rc8 failures

`tests/test_rc8_regressions.py`, 20 checks: the exact rc8 refusal now
authorizes; a wrong same-domain target still refuses; five framing shapes
still withhold; duplicate same-target calls are one operation with one
receipt; genuinely different targets stay distinct; two users never
collide; **one cancelled and one active reminder render correctly in the
same response**; a failed confirmation says NOT cancelled and reports the
reminder still set; next-turn readback after a cancellation shows it
cancelled; and the regex layer is asserted gone.

**409 passed, 2 xfailed, 0 failed** (`tests/focused_rc9.txt`).

## Status

`rc9-005dd17b07aa` — **NOT READY**, and not claimed otherwise: every
mechanism here is deterministic evidence only. The rc8 failures are
reproduced and fixed against real rows, but nothing has been validated
live, and the live-validation allocation has not been requested.

Outstanding before any such request: the rc9 image is unbuilt and its
identity unverified, and the `CARRIED_OVERAGE=5` debt is still
outstanding — rc8's run configured it but ran a gateway that ignored it.

---

# Round 12 — the two rc9 gaps closed

**`rc9-005dd17b07aa` stays NOT READY**; **`rc10-02ec57b938cf`** is frozen.
Deterministic evidence only — no model generation, no live cycle,
production untouched. Gateway changes from round 11 preserved unchanged.

Patches: `patch/ROUND12_rc9_to_rc10.patch` (6 files, 668 lines) ·
`patch/RC10_FROM_HEAD.patch` (60 files), verified byte-for-byte from
`git archive HEAD`.

## Gap 1 — cancellation needs evidence of the operation, not just the target

The "naming grants authority" rule is **removed**. `has_removal_request`
adds positive evidence of a removal, and `authorize_named_removal` is now
conjunctive: a removal tool, a removal request, framing that does not
withhold authority, an owned row, and the turn naming that row.

The removal lexicon is deliberately removal-scoped, so a reschedule verb
evidences a reschedule and never a cancellation.

**One thing the integration tests caught that the unit tests could not.**
Making removal evidence *sufficient* was not enough — general action
intent was still granting it upstream. *"Move the vet one to 7pm"* and
*"Remind me to call the vet again"* are `has_action_intent` True, and
both executed `reminders_cancel` on that reminder through the real
boundary. Removal evidence is now **required** for removal tools, not
merely sufficient. Continuations and the pending-proposal path are
untouched, since a scoped confirmation is authorized by the proposal it
answers.

Verified through `execute_tool` against real rows
(`tests/test_rc9_gap_integration.py`): *"Scratch the vet one, I already
called them."* cancels the vet reminder and nothing else, while a plain
mention, praise, a question, a hypothetical, a reschedule request, a
creation naming the same subject, and a removal request naming a
*different* reminder all leave it active.

## Gap 2 — authoritative fields reach the user, not just the model

Feeding `statement_of_record` to the model was necessary and not
sufficient. `reminder_statement.enforce()` now renders committed facts
into the user-visible text: one sentence matched to one row by that row's
own identifying words, compared against that row's committed outcome, and
the offending sentence **replaced** by the rendered fact.

This is not the deleted `answer_grounding`. That read whole answers,
guessed across clauses, and appended a contradiction to a correct reply.
Here the unit is a sentence, the key is a reminder id, and the remedy is
substitution rather than a bolted-on correction — so a correct reply is
returned byte-for-byte unchanged, which is asserted.

It runs at **both** points a reply can leave: inside
`_finalize_response_content` (the persisted episode) and on the value
`chat_with_tools` returns (what the SSE layer streams). Twice is
deliberate — the paths are independently reachable, and the operation is
idempotent.

Driven with a deliberately wrong controlled model response over **one
cancelled and one active reminder**:

```
model:  "Call the vet back is still set for later.
         Flip the laundry was cancelled earlier."
user:   "Call the vet back" (…) — cancelled.
        "Flip the laundry" (…) — still set.
```

Both false claims are gone; each reminder carries its own committed
status.

## Evidence

**426 passed, 2 xfailed, 0 failed** (`tests/focused_rc10.txt`), including
17 new integration tests. Six rc8-regression assertions were widened from
a specific refusal basis to the contract ("refused, by one of these
guards") because the conjunctive check now catches several cases one step
earlier; every refusal still holds.

## Status

`rc10-02ec57b938cf` — **NOT READY**. Both gaps are closed with
deterministic evidence through the real execution boundary and the real
reply path. Nothing here has been validated live, no live cycle was
built, and the outstanding items are unchanged: the image is unbuilt and
unverified, and the `CARRIED_OVERAGE=5` debt still stands.

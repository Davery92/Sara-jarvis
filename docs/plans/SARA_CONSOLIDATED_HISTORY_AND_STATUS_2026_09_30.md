# Sara: consolidated work history, evidence, and current status

Compiled: **2026-09-30**. Covers the conversation-quality study, full-assistant acceptance study, repair rounds, reminder release candidates, convention work, architectural repair, production incident, recovery, and operational hardening discussed in this conversation.

This is a historical index and handoff, **not a deployment procedure or authorization to resume work**. It preserves significant corrections rather than treating earlier handoffs as simultaneously true. Detailed transcripts, source diffs, ledgers, and runbooks remain the primary evidence.

## 1. Start here

### What David wanted

Sara should sound like a natural person to talk to, use her tools correctly, remember and correct information, and finish requested work without repeated corrections. The original complaint was coldness, distance, poor conversational flow, and excessive regurgitation of context.

David did not ask for an indefinitely expanding reminder project. The work expanded when testing exposed genuine functional defects, then repeatedly narrowed around reminder release blockers. David explicitly removed response speed as a priority: a hardware upgrade is expected to address that. Sara is a **personal, single-user app**. Same-user overlapping requests and background work can still exercise concurrency; multi-user product expansion is not the goal.

### Latest reported operational state

| Item | State after incident recovery and hardening |
|---|---|
| Production | 15 containers running; no disposable stacks running at the latest handoff |
| API and five Celery services | `sara-reliable-candidate:20260929`, image ID prefix `sha256:68ab3e3f4443…` |
| Application source | Frozen `app/` and `alembic/` mounted read-only; 916 manifest entries verified by the recovery agent inside the running environment |
| Source manifest SHA-256 | `27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d` |
| Schema | `158_reminder_delivery_state` |
| Production configuration | `docker-compose.dev.yml` plus `docker-compose.incident-recovery.yml`, project `jarvis` |
| Management entry point | `scripts/sara-prod` |
| Recovery evidence | `/home/david/sara_incident_20260929/INCIDENT.md` |
| Assistant repair project | **Paused; not fully accepted or validated live on the final artifact** |

The recovery established authenticated access, a real chat response, note create/correct/readback, compatible worker startup, and an initially clean error watch. It did not establish broad functional or conversational reliability.

The immediate recommendation at the end of the conversation was: finish the remaining read-only operational audit/documentation correction, leave production unchanged, and let David use Sara normally. Keep the repair backlog; address concrete observed failures instead of automatically restarting the entire study.

## 2. Evidence rules for reading this document

- **Reported:** a result supplied in an implementing agent's handoff. This compiler has not independently rerun every test or production check.
- **Personally reviewed:** source, documents, transcripts, or results inspected during the reviewing assistant's work. Inspection is not equivalent to reproducing a live behavior.
- **Independently checked during the incident:** read-only container and schema inspection confirmed 15 production containers, schema 154, and missing required tables/columns before recovery. No production changes were made by the reviewing assistant.
- **Lost evidence:** some September 29 artifacts existed only under `/tmp/claude-1000` and disappeared on reboot. Claims based on those artifacts are unavailable/unreproduced until rerun; remembered output is not a replacement.
- **Candidate-specific:** passing results on one source manifest do not automatically validate a later candidate. Different trials, tool tests, and release candidates must not be pooled into a universal pass rate.
- **Classification is not execution:** blocked, unsupported, not-run, deterministic, tool-level, and live-chat evidence are different things.
- **Operational recovery is not feature acceptance.** The production deployment happened during incident recovery, not because all assistant acceptance gates passed.

This compilation uses the conversation and existing local records. It does not claim a fresh full audit of every artifact, does not run tests, and makes no application or production changes.

## 3. Navigation and primary records

### Plans and detailed reviews

- [Natural conversation evaluation plan](SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md)
- [Natural conversation test suite](SARA_NATURAL_CONVERSATION_TEST_SUITE_2026_09_23.md)
- [Personal conversation remediation plan](SARA_PERSONAL_CONVERSATION_REMEDIATION_PLAN_2026_09_23.md)
- [Full-assistant acceptance plan](SARA_FULL_ASSISTANT_ACCEPTANCE_PLAN_2026_09_24.md)
- [Full-assistant acceptance cases](SARA_FULL_ASSISTANT_ACCEPTANCE_CASES_2026_09_24.md)
- [Repair plan](SARA_REPAIR_PLAN_2026_09_25.md)
- [Repair evidence map](SARA_REPAIR_EVIDENCE_MAP_2026_09_25.md)
- [Repair status, including successive rounds](SARA_REPAIR_STATUS_2026_09_25.md)
- [Reminder release-candidate history](SARA_REMINDER_RELEASE_CANDIDATE.md)
- [RC4 blocker separation](SARA_REMINDER_RC4_BLOCKERS.md)
- [Convention readiness](SARA_CONVENTION_READINESS_2026_09_27.md)
- [Personal review of compiled test evidence](SARA_PERSONAL_TEST_REVIEW_2026_09_28.md)
- [Personal-review evidence index](SARA_PERSONAL_TEST_REVIEW_2026_09_28_INDEX.csv)
- [Reliable-assistant implementation plan](SARA_RELIABLE_ASSISTANT_IMPLEMENTATION_PLAN_2026_09_28.md)
- [Reliable-assistant implementation status](SARA_RELIABLE_ASSISTANT_STATUS.md)
- [Reliable-assistant evidence map](SARA_RELIABLE_ASSISTANT_EVIDENCE.csv)
- [Reliable-assistant release document](SARA_RELIABLE_ASSISTANT_RELEASE.md) — contains a withdrawal/evidence notice; do not execute historical instructions blindly.

### Artifacts and operational records

- Original conversation study: `backend/tests/conversation_eval/artifacts/`, including `FINDINGS.md`, transcripts, blinded scores, and `PAIRWISE_REVIEW.md`.
- Full-assistant study: `backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/`, including findings, coverage, manifest, results, infrastructure patches, snapshot identities, and transcripts.
- Reminder release work: `backend/tests/assistant_acceptance/artifacts/run_20260926T121855Z_reminder_rc/` and `run_20260926T161346Z_reminder_rc_freeze/`; follow their manifests for later candidate evidence.
- Reliable-assistant work: `backend/tests/assistant_acceptance/artifacts/run_20260928_reliable/`, including `SIX_EXCERPTS.md`.
- Incident record: [INCIDENT.md](/home/david/sara_incident_20260929/INCIDENT.md).
- Current operational recovery instructions: [RECOVERY.md](../../RECOVERY.md).
- Production wrapper: [scripts/sara-prod](../../scripts/sara-prod).
- Production overlay: [docker-compose.incident-recovery.yml](../../docker-compose.incident-recovery.yml).

## 4. Phase 1 — conversation quality study

### Aim and approach

David requested many full, natural, multi-turn conversations across model settings so the results could be reviewed. Testing grew through scripted cases, broader suites, comparisons, blinded review, and adaptive conversations.

The original handoff reported 164 conversations and 1,349 user turns. Later revisions reported 242 transcript files and 2,000 Sara turns. These describe different checkpoints, not additive totals.

### Findings that survived review

- Vulnerable disclosures could expose ambient context when followed by an ordinary question, leading to irrelevant calendar information in emotional support.
- Metaphorical or noun uses of words such as “schedule” could trigger operational context routing.
- Removing context leakage alone did not solve verbosity or warmth; in one comparison it made verbosity worse.
- Sara offered unsolicited troubleshooting even when explicitly asked not to.
- Sara could falsely deny a successful prior action when its evidence was absent from the current context.
- Sara could falsely confess to inventing a correctly grounded fact after social pressure.
- Empty replies occurred, but the claimed reasoning-budget-exhaustion cause was retracted as unproven.
- A conversational instruction block improved some warmth/flow scores but did not reliably fix unsolicited advice and had regressions. It was not established as a production-ready solution.

### Important methodological corrections

- “Nothing beats baseline” became “screening found no clear improvement.”
- “Zero empty replies” and consistent improvement were retracted after previously missed transcripts were read.
- The initial repeated-write claim was substantially a harness artifact when the real mutation gate was exercised; narrower false-denial behavior remained.
- Adaptive user simulation used the same tested model, contrary to the instruction not to test Sara against herself. This remained a limitation of that evidence.
- Two harness copies ran concurrently during an early incident; contaminated results were excluded and the incident documented.
- Actual consumption was **2,663 valid + 398 discarded = 3,061 requests**, exceeding the 2,800 ceiling by 261. Discarded requests still count as resource use.
- The instruction block `PC_BLOCK` remained in the evaluation harness rather than being shipped as a confirmed production improvement.

## 5. Phase 2 — initial context and mutation-gate patches

The first implementation series addressed context exposure and tool availability, not Sara's actual warmth.

Changes reported across revisions included noun/metaphor guards, broader vulnerable-disclosure recognition, question-clause scoping, cross-sentence quotation handling, hypothetical-obligation guards, and self-directed future-intent guards. Tests covered genuine requests alongside background clauses and guarded against treating “I'll probably start…” as authorization.

These were bounded fixes. Relevant-context callback suppression remained unresolved, and keyword/phrase handling continued to produce new edge cases.

### Test and baseline corrections

- “156 passed / 6 failed, full suite” was later withdrawn as imprecisely scoped.
- An explicit related-file run reported **239 passed, 9 failed, 3 errors**. Six failures concerned existing context-router expectations; remaining database failures were later traced to an omitted provisioning step, not a product schema defect.
- Some mutation files were already untracked before the work. Git HEAD was not the pre-session or deployed baseline.
- Broad `git checkout`, naïve revert, and old-image rollback advice could destroy unrelated uncommitted work and was corrected.

### Deployment-state discovery

Production used a live backend bind mount and uvicorn without reload. Disk edits were visible in the container but did not replace already imported modules. The running process dated from September 22 while the working tree accumulated changes. No exact independently verified source snapshot for that original running process was established.

A current candidate snapshot was saved and honestly labeled as a candidate, not a recovered pre-patch baseline. Copying `/app` from the container would copy the current bind mount, not recover loaded Python source.

## 6. Phase 3 — full-assistant acceptance study

### Scope and infrastructure

The scope expanded from personality to Sara as an assistant: notes/memory, reminders, calendars, tasks/lists, food/workouts, documents/research, background work, home control, email, authentication, isolation, and failures.

Stage 0 froze 1,652 source files and recorded dirty-tree state. The isolated project used disposable database/Redis/API/worker infrastructure, production-shaped schema provisioning, fixture users, recording sinks, and a constrained model gateway. The reported model was `qwen3.8-27b`, generation mode `ar`, thinking enabled with low reasoning effort.

Several real routing issues had to be addressed before the evaluation was trustworthy:

- A gateway streaming-response framing bug.
- Model settings and a hardcoded model-catalog URL bypassing the intended gateway.
- Embedding routing through a broker/database setting independent of the expected environment variable.
- Background owner identity assumptions that prevented disposable users from exercising email sync.
- Research fixtures initially supplying unreachable content.

Snapshot-only patches and data fixtures were disclosed. Original snapshot identity and patched execution identity were kept separate. Adapters exercised external-service interfaces without sending real external actions: push, Home Assistant, FatSecret, search/page retrieval, Microsoft Graph, and disposable MinIO.

### Journey and catalog coverage

Repeated handoffs called the work complete prematurely. It resumed several times to close missing second trials, the literal two-workout scenario, stream cancellation, and catalog items.

Final reported journey coverage was **15 of 16 journeys with two trials**, with J04/PKG blocked by the plan's Neo4j dependency allowance. That is not the same as every journey passing.

Final reported catalog classification:

| Classification | Count |
|---|---:|
| Pass | 49 |
| Fail | 34 |
| Blocked | 12 |
| Unsupported | 3 |
| Not run | 2 |
| Total | 100 |

The agent also claimed 92 items had some real execution. That is a separate measure from pass/fail classification; it must not be interpreted as 92 completed live-chat passes. Remaining unrun items concerned exceeding the large context window and investigating an empty brief-consolidation result.

Final reported consumption was **1,005 of 1,600 model requests** and approximately **14.24 of 16 active hours**. These are this study's figures, not a total for the entire project.

### Principal defect families

| Area | Observed problems |
|---|---|
| Action truth | Claimed reminders, research, chess moves, and goal progress without supporting tool execution; later repeated invented success |
| False denials | Retracted real notes, PDFs, food logs, or background results under challenge or during follow-up |
| Authorization | Status questions, acknowledgments, hypotheticals, or ambiguous references could lead to unintended writes |
| Targeting | Wrong-entity cancellation; destructive note reconstruction; ambiguous workout selection |
| Reminders | Naive timestamps assumed UTC; reads displayed raw digits; write/read defects masked each other; descriptionless dispatch crash; overdue selection gaps |
| Tasks/lists | Duplicate task creation, unrequested completion, list names splitting one intended list |
| Food/workouts | Corrections not persisted, serving/quantity issues, broken workout tool invocation contracts |
| Documents | Vector-search failure and broken fallback; false denial of a real PDF |
| Background work | Completion invisible to follow-up, missing embedding/indexing, stuck locks, false dispatch success |
| Home control | Success reported despite adapter state not changing |
| Authentication | Logout did not revoke a bearer token |
| Source availability | Connection failures reported as an empty inbox or zero errors |
| Conversation | Reasoning text leakage, intrusive context, unsolicited advice, false self-correction |

### Corrections required during the study

- Reused fixture state was reclassified as exploratory, not an independent trial. Clean replacements were run where required.
- Real advancing time caused fixture drift; a frozen-clock requirement was not implemented as originally specified.
- User-scoped recall caused cross-journey contamination before reset tooling improved.
- “Forever” and “permanently” for reminder non-delivery were narrowed to observed checks and inspected mechanisms.
- A write surviving a deadline and a write being authorized were separated; one does not prove the other.
- Non-deterministic failures remained valid observations even when an immediate retry passed.
- Severity was corrected against the plan: 31 of 36 P0-labeled findings were downgraded to P1. Five observations met the stated P0 criteria, including destructive/wrong-target actions and unauthorized recurring effects; these were not necessarily five distinct root causes.

## 7. Phase 4 — repair packages R00–R15

The repair plan grouped baseline/evidence work, authorization, corrections, action evidence, freshness, time contracts, delivery, tool contracts, domain correctness, background work, logout, source availability, response behavior, and acceptance.

### Main implementation reported across four rounds

- Execution-boundary mutation checks, including paths that previously bypassed offered-tool filtering.
- Note span editing and optimistic concurrency; full rewrites requiring a base revision.
- Scoped pending proposals and recurring-operation checks.
- Several successive target-resolution designs: clause counts, domain nouns, then owner-scoped resolved target IDs. Earlier designs were superseded after bypasses were found.
- Durable action receipts and a verification tool, then claim-before-mutation keyed to client-message operation identity rather than only model tool-call IDs.
- Durable logout revocation, fail-closed behavior, and cookie/bearer precedence handling.
- Reminder dispatch crash fixes, overdue handling, claim expiry/retries, cancellation rechecks, and separation of claimed work from actual delivery.
- Timer timestamp comparison correction.
- Workout tool argument-contract fixes.
- Food-name quantity parser correction.
- Document search transaction/fallback handling, then a query-side cast with genuine paraphrase retrieval.
- Email-sync error propagation.
- Four additive migrations, later exercised through actual Alembic upgrade/downgrade; this caught an overlong revision identifier.

Most broad packages were only partly implemented. A useful slice being complete did not mean the entire package or original assistant task was complete.

### Evidence and packaging limitations

An initial isolated patch was verified against reconstructed pre-edit files, but round-trip patch equality did not establish identity with the long-running deployed process. Later rounds lacked complete pre-edit reconstruction for some files. Full-suite failures/errors remained, requiring exact-ID baseline comparisons rather than “all tests pass.” Round 4 was stopped before its full-repo comparison finished, although focused tests passed.

An early live-validation count was corrected from “under 20” to **28 upstream requests**. Authentication checks covered issuance/logout/replay, not password login.

## 8. Phase 5 — reminder release-candidate sequence

This became the longest detour. Live multi-turn workflows repeatedly found defects that focused tests missed. It improved important shared mechanisms, but did not deliver the original broad conversational goal.

| Candidate / stage | Main result and subsequent correction |
|---|---|
| Initial reminder candidate | Fixed naive reminder time interpretation, false push-success recording, readback-triggered creation, and a corrected-retry guard problem. Required steps passed across different runs, not in one clean final run. Packaging was incomplete. |
| `rc2-78e423030560` | Reproducible 35-file package over `e3651cd7`; cancellation of “the vet one” failed and the reminder delivered. Push dedup/outcome semantics improved. A disposable stack was accidentally created under the production project, then removed by explicit names; this motivated a namespace guard. |
| `rc3-3b2b4498407c` | Shared singleton removal history identified across overlapping turns and moved to context-scoped state. No live paired verification yet. Claims about migration 154, downgrade loss, and source recoverability corrected. |
| `rc4-c5e3a085396d` | Audit expanded to 21 mutable per-turn fields, including authorization's raw user message. Isolation tests passed, but concurrent journeys still failed on duplicate writes, reschedule behavior, cancellation, and reply truth. Baked image and recovery procedure improved. |
| RC4 blocker review | Separated unauthorized readback writes, non-atomic cancel/create reschedules, unsourced action claims, and misattributed cancellation refusal. A supposedly premature delivery claim was actually composed after delivery; the real failure was refusal being presented as timing. Missing receipt/guard argument evidence prevented confident diagnosis of some calls. |
| rc5–`rc7-e5456f99026c` | Guard added to both normal and deadline write paths; atomic reschedule with delivery revisions; trace logging and grounding changes. Readback/reschedule checks improved, but vet cancellation still failed. 105 requests used against a 100 allocation. |
| `rc8-b64ae69f3a8f` | Retained short identifying tokens such as “vet,” added deliberation checks, and improved budget tooling. Live cancellation still failed through other guards. Text grounding invented a contradiction and missed another. Gateway accidentally built from older source, so claimed task-wide budget enforcement was not actually running. |
| `rc9-005dd17b07aa` | Argument evidence showed the correct cancellation also failed on missing action evidence. Owner-scoped resolution and same-target normalization introduced. Reminder fact rendering and runtime gateway identity improved. Naming a target as sufficient authority was itself rejected in review. |
| `rc10-02ec57b938cf` | Removal operation evidence made required in addition to target ownership/reference; creation or reschedule language could not authorize cancellation. Response enforcement changed again. Deterministic evidence only; outstanding live/image acceptance remained. |

### Lessons from this sequence

- Fixing one predicate did not establish that the full execution path accepted the intended operation.
- A single correct target and duplicate calls for that target are different from multiple distinct targets.
- Correct tool results being available did not guarantee truthful model narration.
- Text-pattern grounding could create false corrections by joining one entity's name to another entity's status.
- Rescheduling needed a domain operation, not loosely coupled cancel/create calls.
- Process-global mutable turn state was unsafe even for a personal app with overlapping work.
- A gateway's source, actual runtime settings, shared ledger, and reservation behavior must be verified, not inferred from Compose configuration.
- A new candidate identity requires relevant new evidence; retrying an unchanged failed candidate to obtain a favorable run is not a repair.

Reported focused-test counts rose through 298, 306, 362, 411, 409, and 426, with scope differences and some xfails. These are historical per-run counts, not additive coverage or a final acceptance score.

## 9. Phase 6 — convention readiness, September 27

David wanted usable capture and recall before leaving for a convention. Work refocused on that workflow rather than waiting for reminder completion.

### Changes and live observations

- Natural capture phrases were being refused by action-intent rules.
- Note search returned oversized bodies that were subsequently truncated; excerpts and search behavior were improved.
- Read tools were sometimes misclassified as mutating.
- `remember_about_david` repeatedly failed or diverted corrections away from notes; it was removed from the chat tool set in that candidate.
- Tool-description changes enabled note correction and new-conversation recall in the final demonstrated workflow.
- One successful capture/correct/recall sequence preserved one note and recorded the correction. Earlier failures remained evidence; the successful run did not erase them.
- Corrections initially landed as appended dated lines, leaving potentially stale titles. That was a limitation, not the desired final fact model.

The convention task reported **50 of 60 requests** used. “No budget left” was corrected: time, not request allocation, had been the constraint at the earlier checkpoint. A routing bypass also meant an early apparent live run consumed no intended gateway budget.

### Restart risk became explicit

Source on disk required schema 158 while production still ran schema 154 with older imported modules. Restarting against changed source would break authentication and schema-dependent operations. The proposed recovery pair was a frozen candidate plus schema 158; restoring a database at 154 alone would not restore service.

The production Compose file, overlay loading rules, readiness probe cleanup, and rollback language all needed correction. A backup was restored successfully on disposable infrastructure. Worker task-name agreement and additive insert compatibility were useful but did not establish full background workflow acceptance.

No deployment occurred during this convention-readiness phase according to its handoffs.

## 10. Phase 7 — personal evidence review and architectural plan

David asked the reviewing assistant to personally assess the evidence and then design the repair approach.

### Review artifacts produced

- `SARA_PERSONAL_TEST_REVIEW_2026_09_28.md`.
- `SARA_PERSONAL_TEST_REVIEW_2026_09_28_INDEX.csv`.

The review covered all 40 original Stage 4 conversation transcripts (352 turns), score/blinded comparison tables, assistant coverage/results, and 12 reminder paired-journey transcripts (96 turns), with a 493-entry evidence index. This was evidence review, not a rerun of all tests.

### Assessment

Sara showed genuine capability and some natural conversational moments. The larger problem was unreliable continuity between user intent, selected tools, committed state, follow-up retrieval, and the final answer. Personality issues included overinterpretation, unnecessary management/advice, and context recitation; merely shortening responses or hiding calendar context would not solve them.

### Plan produced

`SARA_RELIABLE_ASSISTANT_IMPLEMENTATION_PLAN_2026_09_28.md` called for:

1. Consolidate one exact candidate and reproducible evidence/recovery baseline.
2. Simplify the actual assembled prompt and conversational context early.
3. One operation/target/authority contract across execution paths, with scoped proposals and explicit ambiguity.
4. Durable action evidence, fresh reads, cache invalidation, and factual output grounded in state rather than post-hoc word matching.
5. Real fact corrections with current truth and retained history, not contradictory append-only notes.
6. Finish shared domain contracts across notes, reminders/calendar, tasks/lists, food/workouts, documents/background work, devices, sources, and auth.
7. Six functional journeys with two independent trials on the final candidate, plus natural-conversation cases and excerpts for David.
8. Pin API/workers and migrations to the tested artifact, and distinguish restartability from recovery from a defective release.

The authorized generation allocation for this phase was **300 new upstream requests**, task-wide and atomically enforced. No agents were to be spawned by the reviewing assistant; production changes required separate authorization. Hardware speed was not a gate.

## 11. Phase 8 — reliable-assistant implementation, September 28–29

### Implemented mechanisms reported

- `operation_contract.py` and `reference_resolution.py`.
- Outcome ledger and `outcome_grounding.py`, with write-turn streaming held for checking.
- Domain operations: `notes_correct_fact`, `reminders_reschedule`, `reminders_update`, `list_correct_item`, `food_log_correct`.
- Timestamp/DST contract, read-cache invalidation, canonical list names, device-state confirmation, registry audit.
- Later follow-up implementation for request recovery, workout correction, freshness/grounding gaps, and packaging; the six final changes did not receive final live acceptance before the incident.

### Live findings and limits

The agent reported 17 defects found live that deterministic tests missed, including a challenge interpreted as a note merge, a requested correction acknowledged without any tool execution, and mechanical grounding text appended to emotional support.

The first handoff reported J1 notes, J2 reminders, and J3 tasks/lists passing two trials; J4 food failed routing, J6 mixed-day failed to call a tool, and J5 background/documents was never run. Subsequent review established that evidence crossed candidate identities: live acceptance referenced manifest `e19baca7…`, while later final candidates contained additional changes.

The ledger reported **277 of 300 requests**, leaving 23 for that task at the last reported accounting. This is not a renewed allocation or authority to spend after the project pause.

### Reviewing assistant's source-level concerns

At the reviewed revision:

- An unknown-imperative fallback granted several possible operation kinds from a reference-bearing utterance; this did not establish the specific requested operation.
- The claimed replacement for verb lists still included substantial regex/lexicon logic, including “scratch.”
- Grounding explicitly excluded current-state descriptions and matched entity words in sentences, leaving the previously observed problem only partly solved.
- Missing-tool execution needed bounded, authorized recovery rather than being dismissed as unfixable by application code.
- Worker pinning was part of the implementation requirement, not a product preference David should have to design.
- Final-candidate live evidence, workout/background coverage, and deployment/recovery packaging remained incomplete.

Later handoffs reported implementation of these gaps. Those reports did not supply completed final-candidate live acceptance before the incident; the current documents explicitly preserve that limitation.

### Conversation evidence

- Brief exchanges sometimes flowed naturally, and one challenge correctly prompted a source check rather than a false confession.
- Breakfast-at-night still produced an excessive, judgmental/advisory answer.
- “I'll stop selling you on the 9am plan” was immediately followed by more advice.
- Support about David's father inferred feelings and motivations David had not supplied.
- “Tired” should not automatically mean ending the conversation or prescribing sleep.

The original conversational complaint was therefore **partially improved, not resolved**.

## 12. September 29 production incident

### Confirmed timeline and responsibility

The implementing agent left production and multiple disposable stacks running concurrently, including additional APIs, workers, databases, embeddings, and a rehearsal environment. It then started the full test suite while rehearsal infrastructure was still running.

The incident report records a host-wide OOM around **15:36–15:38 UTC September 29**, including a killed production Neo4j Java process. Approximate process RSS totals reported from the kernel dump were 4.3 GB uvicorn, 3.3 GB Celery, 2.5 GB PostgreSQL, and 1.2 GB Java, plus substantial swap and tmpfs pressure. These aggregate figures are diagnostic estimates, not a precise accounting of unique physical pages.

**David rebooted the VM because it was locked up.** The reboot was a user recovery action, not an unexplained autonomous reboot. The unsafe code/schema combination already existed on disk before he rebooted.

### Consequence

Production restart policies brought the containers back using changed bind-mounted source against schema 154. The old September 22 imported process state was gone.

Required objects were missing:

- `revoked_token` — authentication revocation checks failed closed.
- `chat_pending_proposal`.
- Reminder/timer delivery columns, including `notified_at`.
- Required action-receipt idempotency support reported by the agent.

The reviewing assistant independently checked the schema version and missing tables/delivery columns read-only. `/health` and container health remained green despite the incompatible application/schema pair.

### Lost evidence

The reboot destroyed artifacts stored only under `/tmp/claude-1000`, including controlled-clock comparison logs, earlier release/recovery rehearsals, and an unread final full-suite result. The status and release documents now carry an evidence notice.

Specifically, the later 2,366/3,040 pass figures, 56-of-57 shared-failure split, three-way split artifacts, and earlier rehearsal-success claims are not currently citable as verified evidence. Scripts remaining on disk make reproduction possible; they do not restore the missing evidence.

## 13. Incident recovery

Feature work and acceptance testing were paused. Recovery focused on a verified application/schema pair, production data protection, and getting authenticated service back.

### Reported actions and evidence

- Fresh 236 MB production backup taken before recovery; older backup retained.
- One memory-limited disposable rehearsal restored 302 tables, checked counts, and applied the artifact's migrations in about 28 seconds.
- Failure drills checked a deliberately failed migration, database restoration to 154, and the known incompatibility of the artifact on schema 154.
- Production upgraded to `158_reminder_delivery_state`.
- API and five Celery services pinned to `sara-reliable-candidate:20260929`, with read-only frozen source mounts.
- Manifest verification inside the running environment reported 916/916 matching entries.
- `manifests/live_vs_candidate.diff` was empty: recovery pinned the application source the reboot had already exposed; it did not establish that those features had passed acceptance.

### Reported production checks

| Check | Result |
|---|---|
| Readiness probe: schema, auth, note write, SQL confirmation, search | READY |
| `/chat/stream` | HTTP 200, nine SSE events, reply “pong.” |
| Note create → `notes_correct_fact` → readback | Passed, history preserved |
| Workers | Four worker nodes online, 136 tasks; beat is the fifth Celery service |
| Missing schema errors | None observed in API/workers during the reported check |
| Five-minute error watch | No reported errors or tracebacks |
| Scheduler resume | No jobs with `next_run_at` already past in the checked set |
| External effect | One reported legitimate dinner-preparation notification |

The notification contained a stale relative time (“in 51 minutes” for an event 21 minutes away). Delayed delivery after earlier composition was a plausible explanation, not a reason to count the message as temporally correct.

### Recovery limits

There is no verified application artifact that serves correctly on restored schema 154. A database backup protects data; it does not by itself provide an available service. A defect in the current artifact may require a forward fix or downtime while another compatible pair is prepared.

The new incident rehearsal evidence is separate from the earlier rehearsal logs lost on reboot.

## 14. Operational hardening, September 30 handoff

### Production wrapper

`scripts/sara-prod` supports `verify`, `config`, `ps`, `logs`, `stats`, `up`, `restart`, `stop`, and `readiness`. It always selects both production Compose files and project `jarvis`.

Reported verification checks:

1. Both Compose files exist.
2. The expected image identity is present; a moved tag is rejected.
3. Frozen source matches its manifest.
4. Resolved application service configuration uses pinned image/read-only frozen code, with no importable working-tree source.
5. Running containers match the expected mounts/image.
6. Schema is the expected revision.
7. No disposable stack is running.

`up` and `restart` abort if verification fails. Simulated missing overlay, moved image identity, and wrong schema produced explicit failures without production changes. These are reported fault checks, not a new full application test run.

### Automation audit

| Item | Disposition |
|---|---|
| `scripts/deploy_production.sh` | Legacy deployment blocked unless explicitly overridden with `SARA_ALLOW_LEGACY_DEPLOY=1` |
| `docker-compose.dev.yml` | Warning added directing operators to wrapper/runbook |
| Daily Docker prune | Agent reported tagged artifact/named volumes were outside the configured prune scope |
| `sara-ha-listener`, `sara-fleet-agent` | Direct Python services; no Compose operation found |
| Existing container restart policies | Reboot reuses the created containers' pinned configuration |
| `sara-scheduled-home.service` | **Still needs privileged read-only audit**; unit contents not inspected at the available privilege level |
| `sara-health-watchdog`, `sara-subconscious` | Reported disabled |

The wrapper reduces accidental unsafe deployment; it does not make direct Docker/Compose commands impossible. Future operators must use the supported entry point.

### Durable recovery artifacts

Directory: `/home/david/sara_incident_20260929/artifact/`, with `SHA256SUMS`.

- `sara-reliable-candidate-20260929.image.tar.gz`, about 4.18 GB; gzip integrity and archive image identity checked without loading a second copy.
- `frozen_source_candidate.tar.gz`, about 6.8 MB, including manifest.
- Migration files 154–158 and `alembic.ini`; the four release migrations were still untracked in Git at this handoff.
- Base Compose, incident overlay, production wrapper, and resolved production configuration.

Backups:

- `/home/david/sara_incident_20260929/backups/sara_hub_pre_recovery_202609292015.dump`, SHA prefix `96de67a0…`.
- `/home/david/sara_backup_verify/sara_hub_preconvention_202609271525.dump`.

Reported latest resources: 6.5 GiB memory used, 9.1 GiB available, about 10 MiB swap; 15 production containers up; 13 disposable containers exited with restart policy `no`. Disk was about 82% used with 26 GB free after artifact export.

### Remaining operational wording correction

Do not infer “no partial migration changes” solely from `alembic_version` remaining at the previous revision. Actual transaction boundaries and migration operations determine rollback behavior. The specific failure drill may establish its own outcome; it is not a universal migration guarantee.

## 15. Budget and evidence accounting summary

| Workstream | Last relevant reported accounting | Caveat |
|---|---|---|
| Original conversation study | 3,061 actual / 2,800 allowed | Includes 398 discarded requests; 261 over |
| Full-assistant acceptance | 1,005 / 1,600; ~14.24 / 16 active hours | Different stages had earlier incomplete checkpoints |
| Initial repair live validation | 28 upstream requests | Corrected from “under 20” |
| Reminder candidate work | Several separate allocations; rc5–7 used 105 / 100 | Shared-ledger deployment failed in a later run; do not infer a reliable global total from handoff arithmetic |
| RC8 verification | 40 actual requests | Older gateway ran; intended carried-overage enforcement was absent |
| Convention task | 50 / 60 reported | An earlier endpoint bypass complicates interpreting gateway-only figures |
| Reliable-assistant task | 277 / 300 at last reported task ledger | 23 remaining is historical accounting, not authorization to resume |

No defensible single total for every inference across all workstreams is established here. Allocation limits, valid results, discarded runs, retries, and off-gateway requests are separate accounting concerns.

## 16. What we have actually gained

- A broad inventory of Sara's real failure modes, including evidence that went beyond personality and isolated unit tests.
- Better domain operations for correction/rescheduling rather than forcing the model to reconstruct destructive updates.
- Progress on operation authorization, target resolution, idempotency, action evidence, timestamps, delivery, search, and logout.
- Recognition that later replies must agree with durable state, not just conversational memory.
- A personal review and an architectural plan tied to the original user goal.
- A recovered production deployment with explicit source/schema identity and guarded management.
- Durable image/source/configuration/database artifacts and a clearer distinction between restoring data and restoring service.

These are substantive gains. They do not establish that every reported implementation is correct or that Sara now reliably fulfills the original experience goal.

## 17. What remains unresolved or unaccepted

| Area | Current confidence / remaining work |
|---|---|
| Natural conversation | Some good examples; excessive advice, overinterpretation, and regurgitation remain unaccepted by David |
| Final assistant candidate | Six latest changes implemented but not live-validated as a complete final package |
| Notes | Recovery smoke checks passed create/correct/read; broader varied natural-language reliability not established |
| Reminders/notifications | Extensive repairs and historical tests; no basis to infer universal reliability; stale delivered wording remains observed |
| Food/workouts | Historical failures and later implementation; final live acceptance incomplete |
| Background/documents | J5 not run in the reliable-assistant phase; worker startup/task registration is not workflow acceptance |
| Full-suite comparison | Some later logs lost; cannot retain unsupported “zero regressions” claims from those runs |
| Defective-release fallback | No verified schema-154 serving artifact; data restore alone does not recover availability |
| Automation audit | Scheduled-home service still needs privileged read-only inspection |
| Source control | Dirty/untracked history persists; frozen archives are critical records, not a substitute for eventual clean release management |

Do not relabel all historical defects as still present: many have reported fixes. Conversely, do not relabel every implemented fix as verified on the current production artifact. Consult the evidence map and exact source identity before making either claim.

## 18. Working rules for whoever resumes later

1. Start with David's actual goal and latest observed problem. Do not restart the entire historical study by default.
2. Respect the current pause. This document grants no deployment, migration, generation, or production-test authorization.
3. Use `scripts/sara-prod` for production management; do not recreate production from the mutable working tree.
4. Keep test infrastructure explicitly named, resource-limited, and short-lived. No overlapping heavy suites/stacks on this host without a measured capacity decision.
5. Save evidence durably as it is produced, not only under `/tmp`.
6. Pin candidate identity, schema, worker code, model settings, and actual gateway runtime before interpreting results.
7. Preserve exact failed cases and report uncertainty. Do not turn missing logs into guessed root causes or use repeated favorable retries as acceptance.
8. Require operation-specific authorization and owner-scoped target resolution; target mention alone is not authority.
9. Verify committed state independently of Sara's words. Check corrections and follow-up reads, not only initial writes.
10. Keep natural conversation central. Grounding machinery should not intrude on ordinary chat or emotional disclosures.
11. Treat known unsupported capabilities honestly. An admission of failure is preferable to fabrication, but does not count as completing the requested operation.
12. Separate operational readiness, functional acceptance, and conversational quality in every handoff.

## 19. Final assessment as of this record

Sara is reported operational again on a pinned, schema-compatible deployment. The incident recovery and hardening are meaningful completed work. The broader assistant repair remains paused and only partly validated.

The next useful evidence should come from David using the app for real capture, correction, recall, and conversation—not from automatically launching another broad campaign. Preserve the backlog and handle concrete failures with bounded changes and relevant checks.

**The project began to make Sara easier to talk to and more dependable. That remains the acceptance standard.**

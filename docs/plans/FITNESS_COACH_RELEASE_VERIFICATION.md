# Fitness Coach — Release Verification

Step 31 of `FITNESS_COACH_IMPLEMENTATION_PLAN.md`. This records what was
built, what was actually run against it, and what is deliberately not
deployed. It is a verification record, **not** a deployment authorization:
nothing here changes the production pin, and §5 below says what a release
would require.

Written 2026-10-02. Everything below was executed in the disposable test
stack (`docker-compose.test.yml`, project `sara-fitness-test`) except the
two live-model roundtrips, which are called out explicitly with how they
were isolated.

---

## 1. The source/schema pair

| | |
|---|---|
| Branch | `feat/sara-mind-v2` |
| Head at verification | `ac10ad84` (Step 29) + Step 30 working tree |
| Alembic head | `174_fitness_automation` |
| Baseline this was built from | `158_reminder_delivery_state` — the head CLAUDE.md §8 records, and the schema the current production generation runs |
| Migrations added | `159`–`174`, sixteen revisions, all additive |
| Registered tools | 272 (was 263 before this plan) |
| HTTP routes | 1004 total, 165 under `/api/fitness` |

**Restart safety is a (source, schema) pair** — CLAUDE.md gotcha 2 — and the
pair here is `ac10ad84`+Step-30 working tree against `174`. Neither half is
deployable without the other.

### Migrations, and why each is restart-safe

Every revision is additive: new tables, new nullable columns, new indexes,
new triggers. No column is dropped, no type is changed, and no existing row
is rewritten. That is what makes **old-generation compatibility** true
rather than hoped for: the production generation running `158` source does
not read any of the new tables, and the new columns it does touch
(`fitness_template.current_revision`, `fitness_phase.program_revision`,
`fitness_coach_review.science_citations`) are nullable and unread by it.

| Rev | What it adds | Rollback-free restart |
|---|---|---|
| 159 | Fitness ownership prerequisites | additive constraints after reconciliation |
| 160 | Athlete profile, dated goals, limitations | new tables |
| 161 | Target revisions | new table, immutable snapshots |
| 162 | Canonical observations on `health_metric` | new nullable columns + partial unique index |
| 163 | Check-in extension on `daily_recovery_log` | new nullable columns |
| 164 | Measurement types/periods | new tables |
| 165 | Exercise alias scope | new table + nullable columns |
| 166 | Performance/fractional load | new nullable columns; the integer `weight` column is untouched |
| 167 | Pain reports | new table |
| 168 | Review audit | new tables, deferrable self-FKs |
| 169 | Coaching cadence + occurrence ledger | new tables |
| 170 | Photo metadata | new nullable columns |
| 171 | Photo analysis | new table, owner + freeze triggers |
| 172 | Science library | new tables, HNSW + GIN indexes, `vector(1024)` |
| 173 | Program/template revisions, drafts | new tables + two nullable columns |
| 174 | Automation policies, action log, source adapters | new tables |

Verified by hand: `172`, `173` and `174` each round-trip
(`alembic downgrade -1` then `upgrade head`) cleanly in the disposable
stack. Each downgrade's docstring states what it destroys, and **none of
them is a recovery procedure** — CLAUDE.md gotcha 2: downgrading is an
outage, not a rollback.

---

## 2. What was run

### Backend

All through the disposable stack. `backend/tests/env_guard.py` fails
collection otherwise, and it was not bypassed at any point.

```bash
backend/scripts/disposable_compose.sh sara-fitness-test \
  -f docker-compose.test.yml run --rm --no-deps backend-test \
  pytest -q -p no:randomly -k "fitness or template or workout or program or plan or science or progression"
# 1513 passed, 9 skipped
```

And the whole suite, which is what caught the two stale tests §6 records —
a `-k` filter selects on the test id, so `test_health_data_accuracy.py` was
never in any of the per-step sweeps:

```bash
backend/scripts/disposable_compose.sh sara-fitness-test \
  -f docker-compose.test.yml run --rm --no-deps backend-test pytest -q -p no:randomly
# before the §6 fix:  4368 passed, 57 failed, 25 errors
# after:              4374 passed, 54 pre-existing failures, 25 errors
```

The two runs were diffed by test id rather than compared by count, which
is how the next item was found: **two tests fail on any second run against
the same database.**
`test_chat_pending_proposal.py::test_refusal_then_confirmation_reexecutes_the_original_arguments`
and
`test_execution_boundary_mutation_authorization.py::test_explicit_request_still_executes`
leave `action_receipt` rows for `standing_order_create` behind, and the
idempotency guard in `main_simple` then correctly declines to re-execute —
so the tests see an empty call record. The guard is right and the tests are
state-dependent. `DELETE FROM action_receipt WHERE action_type LIKE
'%standing_order%'` makes both pass again. Pre-existing, unrelated to this
work, and noted because a count comparison would have read it as a
regression from the fix above.

Per-step suites, each run green in isolation and in the sweep:

1149 test functions across 37 `tests/test_fitness_*.py` files. The ones
added or materially extended by Steps 17–30, with the function count each
file holds and what it is for:

| Step | File | Tests | What it pins |
|---|---|---|---|
| 17 | `test_fitness_state.py` | 31 | state assembly, degradation, cache fingerprint |
| 17 | `test_fitness_state_api_pg.py` | 33 | the state over HTTP, owner-scoped |
| 18 | `test_fitness_consumer_parity_pg.py` | 23 | five readers, one implementation |
| 19 | `test_fitness_review_audit_pg.py` | 43 | immutable audit, linked revisions, idempotency |
| 20 | `test_fitness_reviews_pg.py` | 29 | generation, safety gate, no held transaction |
| 21 | `test_fitness_recommendation_acceptance_pg.py` | 38 | atomic acceptance, staleness, receipts |
| 24 | `test_fitness_coaching_schedules_pg.py` | 51 | occurrence ledger, DST, double-fire absorption |
| 25 | `test_fitness_proactive_delivery.py` | 26 | one question per occurrence, suppression reasons |
| 26 | `test_fitness_photos_pg.py` | 46 | ingest bounds, EXIF/GPS strip, cleanup state |
| 27 | `test_fitness_photo_analysis.py` | 52 | structured observations, no composition claims, 1 live roundtrip |
| 28 | `test_fitness_science_pg.py` | 64 | accepted-only retrieval, curation, citations, SSRF |
| 28 | `test_fitness_science_refresh.py` | 21 | the refresh queues and digests, never accepts |
| 29 | `test_fitness_programming_pg.py` | 80 | typed parser, one writer, drafts, progression |
| 30 | `test_fitness_approved_automation_pg.py` | 61 | bounds, rate, coverage, revocation, sources, privacy |

### Frontend

```bash
cd frontend && npx tsc --noEmit        # clean
cd frontend && npx vitest run          # 12 files, 248 tests passed
cd frontend && npm run lint            # 7 pre-existing errors, none in this work
node ios-app/scripts/check-workout-contract-parity.mjs
#   ✓ Workout wire contract is consistent across Swift, TypeScript and Python.
```

The seven lint errors are unused `eslint-disable` directives in
`AddMealForm.tsx`, `FoodLog.tsx`, `IngredientSearchInput.tsx`,
`OverlayContent.tsx`, `ChatInterface.tsx` and `NotificationBanner.tsx` —
all pre-existing and untouched by this plan.

### Live model roundtrips

Two, both isolated, both actually run rather than mocked. §20 asks for
"actual isolated local-model/vision roundtrips where enabled" because
mock-only tests cannot prove deployed capability.

**Background text model (Step 20).** The review generator was run against
the real local background model. Output parsed, passed the safety gate, and
produced a usable review on the second of two attempts. The first attempt
was *refused by our own gate* for the phrase "take a deload" — which found a
real bug in `safety.TREATMENT_TERMS` (a bare `"take a"` substring), now
replaced with named substances plus shaped regexes.

**Program draft generation (Step 29).** Run 2026-10-02 via
`backend/scripts/fitness_draft_smoke.py`, which follows the Step 20 pattern:
synthetic constraints, a synthetic library and hand-written computed
performance, talking to the model and nothing else, so a failure is
transport, schema adherence or a validator rule rather than fixture data.

It found **five production defects in five runs**, every one of which the
step's 80 stubbed tests had passed over:

| Defect | Evidence |
|---|---|
| `MAX_OUTPUT_TOKENS = 3600` below a single week | measured 3,970 tokens for one week; even one week truncated and parsed as nothing |
| `DRAFT_TIMEOUT_SECONDS = 180` below a single week, and tighter than the lane's own 600s budget so the client's timeout could never apply | measured 196.7s; the first run was a bare `TimeoutError` with nothing produced |
| `allowed_exercises` offered a CONTRAINDICATED exercise | an Overhead Press went to an athlete with a recorded shoulder limitation, the model used it, and `validate_draft` blocked the whole draft for using what it had been handed |
| **the draft path never called `safety` at all** | §29.3 and the prompt both forbid interpreting a limitation; nothing checked. The schema has no field for a diagnosis, so prose is the only place one can appear, and prose was ungated |
| **the model invented a diagnosis, and a leaking draft was still stored** | the recorded note says "left shoulder complains on heavy flat pressing"; the draft said "to avoid aggravating shoulder **impingement**" in two fields. Caught by the gate above — but the draft was then persisted with a warning beside it, and a warning beside a diagnosis is still a diagnosis in the database and on a screen |

Fixed: 7000 tokens, 540s (still under the lane's 600),
`allowed_exercises` withholds contraindicated exercises with the validator
kept as the backstop for an invented name or a later-recorded limitation,
`validate_draft` runs `safety.check_text` over every free-text field down to
a set note, and `generate_draft` now applies the review path's own rule — a
draft whose prose names a condition gets one repair turn and is otherwise
**not stored at all**. `check_text` was extracted from `check_language`
rather than written twice; see §6 for why that mattered. Thirteen tests
cover the new behaviour and the programming suite is 101.

The fifth defect is the one worth dwelling on, because it is a direct
consequence of fixing the third. Three runs produced careful language. The
fourth, with the contraindicated exercises now withheld, forced the model to
explain WHY it was avoiding something — and it reached for a clinical reason
it had never been given. A fix that changes what the model has to account
for can surface a failure mode the previous runs had no occasion to show,
which is an argument for running a smoke test again after every change to
its inputs rather than once at the end.

Also scoped `performance_summary` to the offered list: the model noticed the
gap itself ("Overhead Press — not in allowed list but noted in recent
performance"), and history for a lift it may not prescribe is the same
landmine as offering the exercise, one wrapper over.

Two smaller things the run surfaced. The prompt's shape block only ever
showed a rep set, so the model expressed a 45-second plank as `reps_low:
45, reps_high: 60` — the schema has supported `metric: "time"` all along
and the prompt simply never said so. And a draft cut off at the cap now
raises `TruncatedDraft`, which names the budget rather than reporting "the
output was not JSON", and deliberately does not spend the repair turn: a
repair prompt is longer than the original, so retrying a budget failure
burns another three minutes to fail identically.

What the model did well, which is worth recording because it is the half a
validator cannot tell you: it held the schema on the first attempt every
run, respected the shoulder limitation by substituting incline and dumbbell
pressing without ever naming a condition, and asked for the bench 1RM and
whether the limitation extended to dumbbell pressing rather than guessing
either.

Final run: PASS, 189.5s, 3,841 tokens of a 7,000 cap, one week of three
sessions (13 slots, 32 working sets), nothing blocking and no clinical
language — "to mitigate left shoulder strain on heavy flat pressing",
quoting the athlete's own note rather than interpreting it.

**Vision (Step 27).** `backend/scripts/fitness_vision_probe.py` draws a
synthetic coloured shape in-process — no athlete photo goes near a test —
and checks the answer names it.

```
FAILED  ollama  http://10.185.1.8:11434 qwen3-vl:latest   (ConnectError)
SIGHTED openai  http://10.185.1.8:8686 qwen3.6-35b-a3b    circle   -> "Red circle"
SIGHTED openai  http://10.185.1.8:8686 qwen3.6-35b-a3b    triangle -> "Blue Triangle"
2/4 probes saw the image.
```

That result is the capability record hard-coded in
`photo_analysis.VERIFIED_VISION`, and the `DEFAULT_VISION_ENDPOINT` in
`routes/vision.py` (:11434) is **absent** from it — a test asserts that,
because listing a dead endpoint as verified would mean every analysis failed
with a connection error after passing the capability gate.

The disposable stack is network-isolated by design, so the one test that
performs the roundtrip skips inside it and was run separately on the host
network with a DB URL pointing at a port nothing listens on:

```bash
docker run --rm --network host -v $PWD/backend:/app:ro -w /app \
  -e SARA_TEST_ENV=disposable \
  -e DATABASE_URL='postgresql+psycopg://test_sara:test_only@127.0.0.1:55432/sara_fitness_test' \
  jarvis-backend:latest python -m pytest tests/test_fitness_photo_analysis.py -k real_vision
# 1 passed
```

No cloud model was called at any point. `test_an_unreachable_endpoint_does_not_fall_back_to_a_cloud_model`
greps the module for `api.openai.com`, `api.anthropic.com` and
`ANTHROPIC_API_KEY` and asserts their absence.

---

## 3. Contract acceptance (§31.3)

The plan asks for explicit fitness contract acceptance: two users, partial
data, a logged workout, a review, an explicit target acceptance, and photo
ownership. Each is a test rather than a manual pass, so it stays true.

| Requirement | Where it is proven |
|---|---|
| Two users, no cross-read | every `*_pg.py` file uses a two-athlete fixture; `test_one_athlete_never_retrieves_anothers_library`, `test_one_athlete_cannot_see_or_accept_anothers_draft`, `test_one_athlete_cannot_act_under_anothers_policy`, `test_a_pair_cannot_span_two_athletes` |
| Partial data → unknown, not zero | `Metric` carries `unavailable_reason`; `test_a_period_summary_qualifies_every_number`, `test_coverage_reports_an_empty_library_honestly` |
| Logged workout | `test_fitness_programming_pg.py` logs real sets through `workout`/`workout_log` and reads them back through `effective_load` |
| Review | `test_fitness_reviews_pg.py` (29), including the live-model run |
| Explicit target acceptance | `test_fitness_recommendations_pg.py`; acceptance is atomic, idempotent, staleness-refusing, and writes a receipt |
| Photo ownership | `test_fitness_photo_analysis.py` — consent before bytes, pair owner match in service and trigger |
| Push/network neutralized | the test network cannot reach production or external inference; the digest and candidate paths are stubbed in tests and assert on the decision, not the delivery |

### User isolation

No regression found. Every table added by this plan carries an owner column
and an owner-scoped predicate in every query, and the ones where an FK alone
would not be enough carry a trigger: `fitness_science_*` (chunk/revision/
record owner coherence), `fitness_photo_analysis` (pair owner match),
`fitness_template_revision` and `fitness_program_draft` (revision owner
match), `fitness_automation_action` (policy owner *and* action match).

### History preservation

The property §29.6 and §30 both turn on, tested directly:

* `test_activating_a_revision_leaves_logged_sessions_alone` — a completed
  session's reps, load, unit, RPE and date are byte-identical after a
  program revision is activated.
* `test_activating_a_revision_leaves_stored_reviews_alone` — a stored
  review's `input_state` is unchanged.
* Freeze triggers on `fitness_coach_review`, `fitness_science_revision`,
  `fitness_program_revision`, `fitness_template_revision`,
  `fitness_photo_analysis` and `fitness_automation_action`.

---

## 4. What is off by default (§31.4)

This is the part that matters most for a release: almost nothing in the last
four steps is live without somebody turning it on.

| Capability | Default | What turns it on |
|---|---|---|
| Weekly coach review generation | **off** | `FITNESS_COACH_REVIEW` feature flag |
| Proactive coaching questions | **off** | per-kind cadence, opt-in per athlete |
| Photo analysis | **off** | per-photo consent **and** a probed vision endpoint |
| Science refresh discovery | **not wired** | no discovery source is configured; §28.7 — this plan is not a supplied corpus |
| Science library | **50 papers, 0 accepted** | nothing is RETRIEVABLE until a curator accepts it with a reason; ingesting is not endorsement (§9) |
| Program draft activation | **manual only** | owner-origin acceptance; a model-attributed one is refused by service and database |
| Automation policies | **none exist** | `enabled` defaults FALSE, `expires_at` is required, one policy per action |
| Source adapters | **registered, disabled** | HealthKit is described but not enabled; the existing ingest path is untouched |
| Cloud vision/text fallback | **absent** | not implemented, and a test asserts the absence |

Deferred-by-design items from §22 remain unimplemented: no new vendor OAuth,
no automatic program changes without review, no photo-derived body-fat
number (schema, validator and a migration-level guard all refuse one), no
science crawler, no cross-user model training.

---

## 5. Release path — not taken here

Per CLAUDE.md §2 and `RECOVERY.md`, getting this into production is a **new
pinned generation**, never a rebuild:

```
1. commit it
2. backend/scripts/refreeze_reliable_candidate.sh <snap>
3. backend/scripts/build_reliable_candidate_image.sh <snap> <tag>
4. backend/scripts/rehearse_reliable_release.sh <tag>      -> REHEARSAL PASSED
5. update EXPECT_* in scripts/sara-prod + the image/path in the pin overlay
6. scripts/sara-prod cutover
```

**None of steps 2–6 was performed.** No image was built, no tree was
frozen, no pin was touched, and `scripts/sara-prod` was not invoked. The
production generation is unchanged.

Three things a release would need that this verification does not supply:

1. **`rehearse_reliable_release.sh` against a built image.** The migration
   rehearsal here was `alembic upgrade head` in the disposable stack from the
   `158` baseline, which proves the SQL applies and round-trips. It does not
   prove the frozen-tree + pinned-image pair starts, which is what the
   rehearsal script is for — including the `app/__pycache__` mountpoint whose
   absence took production down at the 2026-09-30 cutover.
2. **`readiness_probe.py` inside the api container.** The four-capability
   probe is the deploy gate, not `/health`, and it has to run against the
   candidate rather than the test stack.
3. **A staged rollout with the feature flags still off.** The additive
   schema can go first and be proven compatible with the current generation
   before any flag is enabled — which is the whole reason nothing above
   defaults to on.

---

## 6. Known gaps and honest caveats

* **The science library holds 50 papers and none is accepted.** It was
  empty at release — §28.7 is explicit that the plan is not a corpus, and
  seeding one with invented DOIs would be worse than nothing. A real corpus
  arrived on 2026-10-04 (§9). Evidence coverage is still effectively zero,
  because `science.search` returns accepted records only and acceptance
  needs a reason and a limitations note per paper. Every surface says so
  rather than implying otherwise.
* **No discovery source for the monthly refresh.** It records an attempt and
  explains why it did nothing. That is deliberate, and the test
  `test_no_discovery_source_is_an_honest_no_op` pins it.
* **A four-week block cannot be generated in one call on this hardware.**
  Measured: one week is ~3,970 output tokens and ~180-210s on the deployed
  27B, so four weeks is roughly 16,000 tokens and 13 minutes.
  `generate_draft` still defaults to `kind=BLOCK`, which invites exactly
  that ask. The failure is self-diagnosing (`TruncatedDraft` names the
  budget) but the default is unchanged, because whether a draft means a
  week or a block is a product decision rather than a bug. The schema
  already supports both, and `PrescribedWeek.program_week` keying matches
  how `set_plan` stores per-week loading tables — so assembling a block
  from accepted weeks is the cheaper half of the choice.
* **A smoke script must not re-implement the control it tests.** The first
  version of the draft script carried its own diagnosis word list and
  immediately flagged "rotator cuff health" as a diagnosis — where
  `safety.DIAGNOSIS_TERMS` holds "rotator cuff tear", the condition, and
  leaves the anatomy alone, because face pulls for cuff health is ordinary
  gym language. That is the same over-breadth as the `"take a"` substring
  the Step 20 live run caught, reintroduced one file over in the script
  whose job was testing it. The script now reports production's finding.
  Same class of error, same fix: one implementation.
* **`fitness_coaching_run` does not exist.** The cadence ledger table is
  `fitness_coaching_job_run`; the privacy export list had the wrong name and
  it is fixed. Noted because the wrong name was in a draft of this document.
* **Two stale tests were left failing by Step 23 and are now fixed.** §23.5
  reversed a rule deliberately — a numeric target used to be allowed into the
  PKG because a chosen number had nowhere else to live, and
  `fitness_target_revision` owns them now. The behaviour change was
  intentional and documented in the commit; the two tests encoding the old
  rule (`test_health_data_accuracy.py`,
  `test_personal_knowledge_graph_upsert_fact.py`) were not updated, and the
  per-step sweeps did not select them because `-k "fitness"` does not match
  those filenames. Both now assert the new rule with the reason, and the
  qualitative half of the old rule — "goal: upper-body thickness", which has
  no numeric home — is kept as its own case.
* **Pre-existing failures, confirmed not caused by this work:**
  `test_context_router.py` (6) and `test_personality_engine.py` (7) test a
  `body_state` feature that no longer exists — `body_state` appears zero
  times in `context_router.py` as of the commit before this work and nowhere
  in `personality_engine.py`. Also `test_dream_consolidation.py` (16
  collection errors), `test_checkin_builder.py` (3),
  `test_system_wiring_check.py::test_the_check_is_quiet_right_now`, and
  `test_unified_notification.py::TestCooldownDefaults::test_category_specific_cooldowns`.
  The full suite reports 54 failures and 25 errors on a clean database;
  each was traced to a cause outside this work. `test_memory_service.py` imports `MemoryTrace`
  from `main_simple`, removed in April 2026 (`8c9a07e8`);
  `test_karma.py` imports `app.services.karma`, which has never existed in
  git history; `test_dream_consolidation.py` fails at collection the same
  way. `test_chat_tool_loop.py::test_actually_executing_a_mutating_tool_authorizes_it`
  turns on `_CHAT_INVOKED_MUTATING_TOOL_NAMES`, which no commit in this work
  touches. The `body_state` group in `test_context_router.py` and
  `test_personality_engine.py` tests a feature that is absent from both
  modules as of the commit before this work began.
* **CLAUDE.md needs two corrections** this work made true: §8 records the
  alembic head as `158_reminder_delivery_state` (now `174_fitness_automation`)
  and §4 records 263 registered tools (now 272).

---

## 7. Phase status against §21

| Phase | State |
|---|---|
| 0 Ownership | done — two-user and revoked-token tests, ownership audit, isolated baseline |
| 1 Foundation | done — profile, dated goals, limitations, target revisions; old and new readers agree |
| 2 Daily | done — canonical observations with units/provenance, partial check-ins, measurements |
| 3 Workouts | done — aliases, session/exercise/set projection, load conventions, pain, parity script green |
| 4 Analytics | done — tested metrics, versioned state, one implementation per number |
| 5 Weekly Coach | done — queued request, validated local output, audit, results UI, receipts; flag-gated |
| 6 Proactive | done — opt-in cadences, occurrence ledger, existing delivery policies |
| 7 Photos/Vision | done — hardened storage, probed opt-in vision, structured uncertainty, no composition claims |
| 8 Science | done — retrieval/curation/citation/refresh tested; 50-paper corpus ingested 2026-10-04, **0 accepted**, so nothing is retrievable yet |
| 9 Programs | done — typed versioned plans, one writer, inspectable drafts, explicit activation, deterministic progression, unchanged past |
| 10 Advanced | done — scoped consented automation with bounds/receipts/revocation, qualified longitudinal summaries, narrow source contract, export and deletion |

No phase is enabled for a user by this verification.

---

## 8. Deployed — and what deploying taught

**Generation 4**, cut 2026-10-02 from `c8188c8d`. REHEARSAL PASSED, cutover
VERIFIED on all six services, readiness probe READY. First generation to
advance the schema (158 -> 174); the source-only rollback to generation 3 was
proven against a 174 database *before* cutting over, and
`/home/david/sara_hub_pre174_20261002.dump` (224M) is the full-restore route.
`alembic downgrade` is not a third option.

**Generation 5**, cut 2026-10-04 from `3c606c77`, same schema — because
turning generation 4 on found two defects in the review path within minutes,
and neither was reachable by any test or by the draft smoke script:

| Defect | Why nothing caught it |
|---|---|
| `TREATMENT_TERMS` held the bare verb **"prescribe"** — the central verb of strength programming, ~69 uses in this subsystem's own code, with the typed schema classes literally named `PrescribedSet`/`PrescribedSlot`/`PrescribedSession`. The first production review was refused as "treatment advice", and every review discussing prescribed volume would have been. | The unit tests assert that specific forbidden terms ARE caught; none asserted that ordinary coaching language passes. A list of banned words is only half a specification. |
| The fabricated-citation check was **unconditional**. Correct while no corpus is attached, wrong the instant one is. | It could only surface after somebody accepted their first paper — reviews suddenly refused for citing the library they had just built. The library is empty, so no test exercised the other branch. |

Both fixed. `check_text`, `check_language` and `validate_output` now take
`evidence_attached`, which `reviews.generate` passes from the retrieval it
already performs. Attaching a library relaxes the citation rule and nothing
else: a diagnosis is still refused.

"Prescribe" was the **third** instance of one bug class, after `"take a"`
(which rejected "take a deload" on the first live model run) and
`"rotator cuff"` (a smoke script's own copy flagging "rotator cuff health").
The rule is now enforced in the list itself — NAMED SUBSTANCES ONLY, no bare
verbs — with a test asserting it, because a comment did not stop the third
one.

### The gap in this checklist

Every pre-cutover gate above is rigorous about transport, schema, recovery
and whether the pinned pair *starts*. **None of them asked whether the thing
produces usable output for the person who uses it.** The draft smoke
exercises the draft prompt; nothing exercised the REVIEW prompt against real
data until it was run by hand, after the cutover. That is how an unusable
review path shipped in generation 4, and it cost an extra generation.

A review smoke cannot simply be added to `rehearse_reliable_release.sh`:
that script's network is deliberately `internal: true` and cannot reach the
inference hosts, which is the property making it safe to run. So it belongs
beside the vision and draft probes as an explicit pre-cutover step, on the
host network, against the real athlete — request a review for a period that
has no row yet, generate it, and require `status == complete`.

One trap worth recording for whoever writes it: `force=True` is NOT enough
to get a fresh review. It only applies when the data has MOVED since an
existing review, so on unchanged data `generate` short-circuits on its
"already answered" path and returns the previous verdict without calling the
model at all. During this release that looked exactly like a second failure
and was not one — the giveaway was `notes: this review was already
complete`. Use a distinct period instead.

### Final production state

    GENERATION 5   sara-coach-candidate:20261004
                   frozen /home/david/sara-candidate-20261004-coach2
                   manifest e239a470 | schema 174_fitness_automation
    VERIFIED       six services, /app/app read-only
    READY          schema | authenticates | writes a note | reads it back
    FLAGS          FITNESS_COACH_REVIEW=on  FITNESS_COACH_PROACTIVE=on
    SECOND GATES   cadences 0 | automation policies 0 | science records ACCEPTED 0

Both flags on does not mean Sara starts talking. Proactive coaching needs a
cadence opt-in per kind and there are none; automation needs a policy with
numeric bounds, a rate limit, a coverage floor and an expiry, and there are
none. Those bounds are the athlete's consent expressed as numbers, and
nothing here will invent them.

### The first production review, for the record

Period 2026-09-04 to 2026-10-02, `complete`, confidence moderate:

> Priority: establish consistent nutrition logging to validate the recomp
> target, as current weight stability cannot be attributed to dietary
> adherence without data.

240.0 lb stable across 23 of 28 days, training adherence 73.9% (17 of 23
sessions), nutrition 0 of 28 days logged, sleep 7.37h over 16 nights with
1.20h variability. Three recommendations, two of them proposing no change.
It volunteered that weight stability cannot be attributed to anything
without intake data — which is the whole point of the coverage contract:
stable weight with no food logs is precisely where a worse system says the
recomp is working.

---

## 9. The founding corpus — 50 papers, 2026-10-04

§28.7 says the plan is not a corpus, and the library shipped empty for that
reason. A real one arrived the same day the coach went live: 50 papers,
given as a list of links, covering load and failure proximity, volume and
frequency, periodisation and autoregulation, concurrent training,
nutrition, supplements, sleep, mobility and body-composition assessment.

**All 50 are stored. None is accepted, so none is retrievable.** That is not
a backlog, it is the contract: `science.search` filters to accepted records
and `coverage` reports accepted totals, so the corpus is inert until a
curator accepts each paper with a reason and a limitations note. Searching
`"weekly set volume for hypertrophy"` against the loaded library returns
**0 hits**, and that is the gate working, not a failure.

| | |
|---|---|
| records | 50, every one `unreviewed` |
| chunks stored | 2,367 |
| chunks retrievable | **0** |
| accepted | **0** |
| failed / duplicate / skipped | 0 / 0 / 0 |
| needed DOI resolution | 4 (#24, #39, #41, #43) — first refused as non-full-text |
| distinct DOIs / titles | 50 / 50 — nothing double-registered |

### What ingesting a real corpus taught

**A PMC article page is mostly not the article.** Fed whole, a page yields
250-400 chunks of navigation, affiliations, figure captions and — worst —
the reference list. A bibliography is dense, well-formed, retrievable prose
that says nothing, so `science.search` would have been able to return a
numbered citation as support for a programming claim. Keeping the abstract
and body section and dropping the ref-list section cut a typical paper to
25-110 chunks of actual argument.

**`source_type` cannot be inferred from body text.** The first pass matched
`position stand|consensus` against the title plus the opening 1,500
characters, and a systematic review whose introduction says "there is
consensus that…" was filed as a position stand. Three of 46 were wrong this
way. A title-only re-derivation corrected 3, confirmed 38 and left 5
inconclusive. `source_type` feeds `TYPE_WEIGHT`, the ranking fallback used
before a curator grades a paper, so a wrong one quietly mis-ranks rather
than breaking — which is why nothing caught it.

**A closed-looking link is not a closed paper.** Four of the 50 were refused
on the first pass as non-full-text: three Springer pages and one PubMed
abstract. All four had open full text. Resolving their DOIs through the NCBI
id converter found PMC mirrors for three; Unpaywall found the fourth open
access at an institutional repository, where the file turned out to be the
published BMJ version of record despite being labelled a submitted version.
Refusing the *page* was right; concluding the *paper* was unreachable was
not, and "I could not get it" needed one more question asked of it.

**Reference-stripping does not generalise from HTML to PDF.** The BJSM
consensus arrived as a 139,806-character PDF with *three* `REFERENCES`
headings — the article's own at 51%, then supplementary material with two
more. Cutting at the last would have dropped 1,300 characters and kept two
bibliographies as retrievable chunks. It is cut at the first instead, which
keeps the complete 13-page article and discards the bibliography and the
supplement together; the record's `notes` says so, because a curator needs
to know the supplement is not behind it.

**Embedding is the bottleneck and it had to be bounded.** The first real
paper exposed the defect that cut generation 6: `embed_chunks` fired every
chunk at once, 56 concurrent requests at a service that is fast for one, and
every request timed out at 60s with nothing stored. Four in flight is the
cap. Cost at that cap: 56-273 seconds per paper, ~2.2 hours for 50.

**Tooling is committed, not improvised.** The ingest ran from a script that
existed only in a scratchpad. It is now
`backend/scripts/ingest_science_corpus.py`, with the corpus itself at
`backend/scripts/corpora/fitness_core_50.tsv` — identifiers rather than
links, since three of the original links were the wrong door to the right
paper. `--resolve` prints the plan and registers nothing.

**One UI claim went stale the moment the corpus landed.** With records
stored and none accepted, the Science Library said "The library is empty, so
there was nothing to search" — true of acceptance, false of the library, and
it reads as though the upload failed. The page now distinguishes stored from
accepted in both places, and a test pins the state production is actually in
(50 stored, 0 accepted) rather than only the empty and the populated cases
it had before. Forbidden-word lists are half a specification; so are empty
states.

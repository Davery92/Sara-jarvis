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
| Science library | **empty** | nothing is accepted until a curator accepts it with a reason |
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

* **The science library is empty.** §28.7 is explicit that the plan is not a
  corpus, and seeding one with invented DOIs would be worse than nothing.
  Retrieval, curation, citation and refresh are built and tested; evidence
  coverage is zero until a human ingests papers and accepts them. Every
  surface says so rather than implying otherwise.
* **No discovery source for the monthly refresh.** It records an attempt and
  explains why it did nothing. That is deliberate, and the test
  `test_no_discovery_source_is_an_honest_no_op` pins it.
* **Draft generation has not been run against the live model.** The
  generator, prompt, validator and acceptance path are tested with a stubbed
  model (including prose-instead-of-JSON and an invented field). A live
  roundtrip is the obvious next check before enabling it for real use.
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
| 8 Science | **built, empty** — retrieval/curation/citation/refresh tested; corpus is a human task |
| 9 Programs | done — typed versioned plans, one writer, inspectable drafts, explicit activation, deterministic progression, unchanged past |
| 10 Advanced | done — scoped consented automation with bounds/receipts/revocation, qualified longitudinal summaries, narrow source contract, export and deletion |

No phase is enabled for a user by this verification.

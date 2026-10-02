# Fitness Coach — Implementation-Time Contract Baseline

Step 1 of `FITNESS_COACH_IMPLEMENTATION_PLAN.md`. This records the *source and
schema pair the Fitness Coach work was built against*, so a later reader can
tell what moved. It contains no private data and no credentials.

## 1. Source baseline

| Item | Value at implementation start |
|---|---|
| Branch | `feat/sara-mind-v2` |
| Commit | `1be52f1e308d06a6aaff9fd9f3577c8fe8e76ebd` |
| Working tree | clean except this plan document (untracked) |
| Alembic head (file-parsed) | `158_reminder_delivery_state` |
| Single head? | yes — no file declares `158_*` as its `down_revision` |
| Backend entrypoint | `uvicorn app.main_simple:app` (both Dockerfiles) |

The head was determined by parsing `backend/alembic/versions/*.py` for
`revision`/`down_revision` pairs, **not** by importing `app.main_simple`
against ambient configuration. Importing the monolith to list migrations
would resolve `DATABASE_URL` from whatever environment is present; in the
production container that is production.

Revisions added by this work (each ID is ≤ 32 characters):

```
158_reminder_delivery_state   (pre-existing head)
  └─ 159_fitness_ownership          M0  ownership prerequisites
     └─ 160_fitness_athlete         M1  athlete profile / goals / limitations
        └─ 161_fitness_targets      M2  dated target revisions
           └─ 162_fitness_observations  M3 health_metric units + provenance
              └─ 163_fitness_checkin    M4 daily_recovery_log extension
                 └─ 164_fitness_measurements  M5 measurement types + periods
                    └─ 165_fitness_exercise_alias  M6 alias + catalog scope
                       └─ 166_fitness_performance  M7 exercise occurrence + set fields
                          └─ 167_fitness_pain     M8 pain reports + PR identity
                             └─ 168_fitness_review_audit  M9 review/recommendation audit
                                └─ 169_fitness_cadence    M10 cadence + occurrence ledger
                                   └─ 170_fitness_photo_meta   M11 photo metadata
                                      └─ 171_fitness_photo_analysis M12 photo analysis
                                         └─ 172_fitness_science     M13 science corpus
                                            └─ 173_fitness_program_ver M14 program versions
```

Every one is additive: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT
EXISTS`, `CREATE INDEX IF NOT EXISTS`. No revision drops or retypes an
existing column, so the previous pinned generation keeps running against the
upgraded schema. That property is what makes the release in Step 31 a
source-only cutover (see `RECOVERY.md`).

## 2. Disposable test target

Backend tests run only through the disposable stack. `backend/tests/env_guard.py`
is imported as the first statement of `conftest.py` and fails closed unless
three independent signals agree: `SARA_TEST_ENV=disposable`, non-production
credentials, and an allowlisted host. It never opens a socket — rejection is
lexical.

```bash
backend/scripts/disposable_compose.sh sara-fitness-test \
  -f docker-compose.test.yml up -d --wait test-db test-redis
TEST_DB_CONTAINER=sara-fitness-test-test-db-1 backend/scripts/provision_test_schema.sh
backend/scripts/disposable_compose.sh sara-fitness-test \
  -f docker-compose.test.yml run --rm backend-test pytest <files>
```

`backend/scripts/disposable_compose.sh` refuses the project name `jarvis`
(production) and anything shadowing it. The test network is named
`sara_test_net` and is internal, so no test can reach a real inference
endpoint; a genuine local-model smoke test needs a deliberately configured
isolated gateway, which is why `tests/test_fitness_review_output.py` runs
against a fake transport and the real roundtrip is an explicit, separately
gated step.

### The fixture/head mismatch Step 1 required resolving

`tests/fixtures/sara_hub_schema.sql` loads **302 tables but stops at
revision 154**. It has no `alembic_version` content, no `revoked_token`
(revision 156) and no `chat_pending_proposal` (155). Any test that
authenticates therefore failed inside `app/core/auth.py:_is_revoked()`,
which — correctly — fails *closed* when the revocation store is unreachable.
Every authenticated fitness request 401'd for a reason that had nothing to
do with fitness.

This was resolved by declaring the fixture's real baseline and upgrading
from it, never by `stamp head`:

```bash
docker exec sara-fitness-test-test-db-1 psql -U sara_test -d sara_hub_test -c \
  "CREATE TABLE IF NOT EXISTS alembic_version (
       version_num VARCHAR(32) NOT NULL
       CONSTRAINT alembic_version_pkc PRIMARY KEY);
   DELETE FROM alembic_version;
   INSERT INTO alembic_version VALUES ('154_saved_meal');"

backend/scripts/disposable_compose.sh sara-fitness-test \
  -f docker-compose.test.yml run --rm --no-deps backend-test alembic upgrade head
```

155 → 158 then apply cleanly, and the new fitness revisions chain onto a
real head rather than onto a schema pretending to be one. The fixture itself
was not edited: regenerating it is a separate, deliberate snapshot decision
(plan §16), and dumping it from a live database during tests is forbidden.

Note that `--no-deps` is used for the test runs. `backend-test` declares
`test-embeddings` as a healthy-condition dependency, and no fitness test
needs a real embedding model until Step 28's science corpus.

No test-only MinIO/model overlay (`docker-compose.fitness-test.yml`) was
needed: the photo tests exercise the storage boundary through an injected
fake object store rather than a live MinIO, which is both faster and keeps
the internal-network guarantee intact.

## 3. Schema facts the implementation depends on

Taken from `backend/tests/fixtures/sara_hub_schema.sql`, which is schema
evidence from a validated disposable upgrade — not proof of production parity.

| Table | Facts that shaped the design |
|---|---|
| `health_metric` | `value numeric(10,3)`, `recorded_at timestamptz`, `source`, `metadata jsonb`. **No unit column** before `162`. A dedup index on `(user_id, metric_type, recorded_at)` is what HealthKit's `ON CONFLICT` writers rely on, so `162` leaves it alone and adds provenance beside it. |
| `daily_recovery_log` | unique `(user_id, log_date)`; `hrv integer`, `sleep_hours numeric(4,2)`, `body_weight numeric(5,2)`, `weight_unit` default `'lbs'`. `soreness_level` has a CHECK of 1–10. Legacy weight/sleep columns become mirrors maintained by one ingest service. |
| `food_log` | `logged_at timestamp WITHOUT time zone` holding **naive ET wall-clock**; `created_at` naive UTC. Nutrition days must aggregate on `logged_at`, never `created_at`. |
| `workout_log` | `weight integer` (!), `rpe integer`, plus the flexible-set columns from `125`: `set_kind` CHECK `working|warmup|drop`, `parent_set_id`, `set_group_id`, `counts_toward_target`, `voided_at`, `revised_from_set_id`, and `exercise_library_id` as a nullable canonical shadow FK beside legacy text `exercise_id`. Integer `weight` cannot hold 2.5 kg steps — `166` adds a decimal field and an adapter; the integer column stays as a compatibility projection. |
| `exercise_library` | global, no owner column, `muscle_groups`/`equipment_required` as `json`. `165` adds scope without changing those readers. |
| `exercise_pr` | identity is `exercise_name` **text**, not a canonical ID, and there is no withdrawal column. `167` adds both. |
| `fitness_phase` | macro targets live directly on the phase row (`calories_target`, `calories_training_day`, `calories_rest_day`, …) and `end_date` is **inclusive**. The target resolver converts to half-open explicitly. |
| `fitness_goals` | default-scope macros with `DEFAULT 2000/150/200/70` — those defaults are *not* evidence anyone chose them, so unprovable history is marked unknown. |
| `fitness_template` | `exercises` is `text` holding JSON, alongside normalized `template_exercise` rows. Both are live; one normalizer writes both. |
| `workout_session` / `active_workout_session` | planned row links to active via `active_session_id` (`139`). `active_workout_session` carries `version bigint` and `workout_snapshot jsonb` — the optimistic-concurrency and snapshot authority. |
| `progress_photo` | `storage_key`/`thumbnail_key` are MinIO keys and must never be exposed. `critique` is legacy unvalidated text. |
| `doc_chunk` vs `document_chunk` | both exist. `doc_chunk` has a native `vector` column; `document_chunk` stores TEXT embeddings cast at query time. Science uses `doc_chunk`. |

## 4. Client contracts preserved

- `backend/app/routes/fitness.py` — 99 handlers took `Depends(get_current_user_id)`.
  Step 2 changed only that one dependency's body; every request/response shape
  is unchanged, which is why no client needed a release.
- `backend/app/routes/workout_v2.py` (8 handlers) and
  `backend/app/routes/cardio.py` import the same helper, so they were fixed by
  the same change.
- `node ios-app/scripts/check-workout-contract-parity.mjs` checks the workout
  wire contract across backend routes/service, iOS TypeScript, Watch Swift and
  phone Swift. New set fields are additive and optional, so parity holds.

## 5. Baseline test outcomes

Recorded before any change so a later failure is attributable:

| Check | Baseline |
|---|---|
| `node ios-app/scripts/check-workout-contract-parity.mjs` | pass |
| `tests/test_workout_command_service.py` | pass |
| `tests/test_workout_flexible_sets.py` | pass |
| `tests/test_plan_adjust.py` | pass |
| `npx tsc --noEmit` (frontend) | pre-existing errors unrelated to fitness; see Step 31 |

A baseline failure is an issue to reproduce exactly, never a reason to weaken
an assertion.

### Pre-existing defects the Step 2 audit found

These were not introduced by this work; the isolation test is what surfaced
them, and they are fixed in the same step rather than left as known-bad.

| Defect | Why it mattered |
|---|---|
| `POST /api/fitness/workout-log` read `result.data["set_id"]` to attach a `template_exercise_id`. `WorkoutLogCreateTool` returns `log_id`. | The block was unreachable, so every `template_exercise_id` a client sent was silently dropped — and the id was never ownership-checked. |
| `PATCH` and `DELETE /api/fitness/templates/{id}` answered `200 {"success": true}` whether or not a row matched. | Owner-scoped SQL meant no side effect, but a foreign id confirmed its own existence, and the owner's own client was told a failed edit had succeeded. Both now 404 on `rowcount == 0`. |
| `POST /api/fitness/tts` had no identity dependency. | An unauthenticated relay that would synthesize arbitrary text through the GPU host for anyone who could reach the API. |
| `_sync_template_exercises_json(db, template_id)` addressed `fitness_template` by id alone. | A whole-JSON-column writer reachable by id is the shape a later caller gets wrong; `user_id` is now required. |
| `workout_command_service._apply_permanent_set_count` wrote `fitness_template` by a `template_id` read out of a proposal's `scope` JSON. | The proposal was owner-scoped, but "an FK to a UUID alone does not enforce ownership" (plan §5). |

## 6. What this step deliberately did not do

- Did not start the backend on the host, rebuild the production image, or run
  an unqualified `docker compose` (there is no `docker-compose.yml`; a bare
  invocation fails, which is intended).
- Did not `alembic stamp head` to paper over the known pre-Alembic bootstrap
  gap. Fixture-based upgrade verification and fresh empty-database
  installation remain different claims.
- Did not probe production, its data, or its deployed source/schema pair.

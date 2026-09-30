# Sara reliable-assistant — release and recovery package

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


Written 2026-09-28/29. **Nothing here has been run against production.**

> **STILL WITHDRAWN — DO NOT ACT ON THIS DOCUMENT.**
>
> Updated 2026-09-29. The six implementation gaps are now closed on the
> implementation side, and the release and recovery path have been **rehearsed**
> on disposable databases with the candidate image. What is still missing is
> **live validation of the changed behavior**: 23 generation requests remain of
> the 300-request ceiling, and no live check has been run against any of the six
> changes. Implementation is not verification, and this document does not ask for
> an approval it has not earned.
>
> The artifact section (§1) and the deployment/recovery procedures (§4, §5) are
> now accurate and rehearsed. §6 distinguishes, line by line, what is verified
> from what is implemented and unverified. §7 states exactly which live checks
> would close the gap and what allocation they need — as a request for an
> allocation, not a request to deploy.

Companion documents: `SARA_RELIABLE_ASSISTANT_STATUS.md` (what was built),
`SARA_RELIABLE_ASSISTANT_EVIDENCE.csv` (88 rows: every compiled finding plus
every defect this task found, with its disposition).

---

## 1. The exact artifact

| | |
|---|---|
| frozen source | `/home/david/sara-candidate-20260928-reliable/backend` (do not edit in place) |
| files under manifest | **916** (`backend/app` + `backend/alembic`) |
| manifest | `CANDIDATE_MANIFEST.sha256`, verified 916/916 clean |
| manifest sha256 | **`27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d`** |
| **candidate image** | **`sara-reliable-candidate:20260929`**, built by `backend/scripts/build_reliable_candidate_image.sh` |
| image base | `jarvis-backend:latest` — the same dependency layer every piece of evidence was gathered on. The build changes exactly one thing: application code. |
| schema required | alembic **`158_reminder_delivery_state`** |
| production schema now | **`158_reminder_delivery_state`** — applied 2026-09-29 during incident recovery, not by this release process. See `/home/david/sara_incident_20260929/INCIDENT.md`. |
| re-freeze | `backend/scripts/refreeze_reliable_candidate.sh`, then rebuild the image |

**There is now an image, not only a mounted snapshot.** A bind mount proves the
bytes on the host at the moment the container reads them; what deploys is an
image, and the two can differ — a stray edit, an rsync that missed a directory, a
`.pyc` shadowing a module the candidate no longer has. So the build:

* copies only `app`, `alembic`, `scripts`, `migrations`, `alembic.ini`,
  `pytest.ini` from the frozen snapshot, as separate layers, so `docker history`
  shows exactly what changed;
* strips every `__pycache__` and `.pyc` — the one class of file the manifest
  cannot certify, and the one that could shadow a deleted module;
* then **verifies the code inside the container** against the same manifest the
  evidence was gathered against: 916/916 files clean, manifest sha256
  `27932826…` printed from `/candidate/CANDIDATE_MANIFEST_HASH` *inside* the
  image;
* then imports the six modules this task added or rewrote
  (`operation_contract`, `outcome_grounding`, `reference_resolution`,
  `request_recovery`, `civil_time`, `session_cache`) inside the image, because a
  file that hashes correctly and does not import is not a deployable artifact.

Every worker role is pinned to the same bytes as the api. The validation overlay
declares all five — general (`cognitive,health,input,maintenance,low_priority,reflection,dispatch`),
`critical`, `david_priority`, `acs`, and beat — each mounting the same snapshot at
`/app`. Verified 2026-09-29: all five started, each printed its own queue set,
four answered `celery inspect ping` over the disposable broker, and a sha256 over
the four modules this task owns is identical in all five containers and on the
host snapshot (`c9b52336eed7c4f8`). Beat writes its schedule to `/tmp`, so it
cannot alter the bytes the manifest certifies.

Deliberately **not** in the snapshot: `venv`, `docker`, `static`, `uploads`,
`data`, `sara_hub.db`, `celerybeat-schedule`. None is imported code. This differs
from the rc2 snapshot, which copied them, and it changes what the deploy overlay
must mount — see §4.

## 2. What production is running right now

**Superseded 2026-09-29 by the incident.** This section used to describe a
process image from 2026-09-22 running on schema 154. That process is gone: a
host-wide OOM and reboot restarted `backend` over its `rw` bind mount, which put
the mutable working tree into production against schema 154 — a pair whose
`_is_revoked` fails closed, so every authenticated request 401s.

Production was then recovered (authorised as incident response, not as a release):

* image **`sara-reliable-candidate:20260929`** (`sha256:68ab3e3f4443…`) on the API
  and all five celery services, with the frozen snapshot's `app/` and `alembic/`
  mounted **read-only** over `/app/app` and `/app/alembic`
* schema **`158_reminder_delivery_state`**, migrated from that same artifact
* readiness probe **READY**; a real `/chat/stream` turn returned a generated reply

Full record, including the evidence: `/home/david/sara_incident_20260929/INCIDENT.md`.
The 2026-09-22 build is **not** a rollback target and never was; there is still no
154-compatible source snapshot.

## 3. Changes in this candidate

**New modules**

| file | what it is |
|---|---|
| `app/services/operation_contract.py` | the single authorization decision: utterance class × operation kind × requested operations × resolved target |
| `app/services/reference_resolution.py` | resolve a reference once, owner-scoped, as structured candidates |
| `app/services/outcome_grounding.py` | the turn's outcome ledger, claim detection, authoritative rendering |
| `app/services/civil_time.py` | one timestamp contract for every scheduling tool, with a stated DST policy |
| `app/services/request_recovery.py` | one bounded, deterministic retry when an explicit request produced no tool call |

**New tools**, all registered and group-reachable: `notes_correct_fact`,
`reminders_reschedule`, `reminders_update`, `list_correct_item`,
`food_log_correct`, `workout_log_correct`.

**Changes David will notice**

1. Conversation: a new `## Conversation` block in the chat prompt, one rule per
   behavior the 2026-09-28 review found.
2. A correction changes the record, including the title, instead of appending a
   contradiction under a stale heading.
3. "Move the vet one to seven" moves one reminder instead of cancelling and
   recreating it, and a naive time means **his** clock. Readbacks now say "5:00
   PM on October 1st" instead of rendering the stored UTC hour.
4. On a turn that writes something the reply is not streamed until it has been
   checked against what happened — so it appears at once rather than typing out,
   on those turns only.
5. A refused action says why in terms of what he said, and never asks him to
   rephrase.
6. If a change was asked for and nothing was written, the reply says so.
7. **(2026-09-29)** An instruction whose operation the application cannot
   identify — "Yeet the vet one." — now asks which operation he means. It used to
   contribute update, reschedule, complete, cancel *and* control at once, so an
   unknown verb could authorize a destructive operation his words never named.
8. **(2026-09-29)** When a write completes and the reply does not report it, the
   record's **current state** is appended, read back from the row by id: "Call
   the vet — Wed 30 Sep, 9:00 AM — as of just now." The old version guessed which
   record a sentence meant by matching its words against the record's title.
9. **(2026-09-29)** If he asks for something explicit and the turn makes no tool
   call at all, the application makes the call itself — through the same
   authorization boundary and the same durable receipt — when it can derive
   exactly one from his own words. When it cannot, it says nothing was written
   rather than guessing. It never invents content: creating, capturing and
   updating are excluded, because a wrong row is worse than no row.
10. **(2026-09-29)** "225 for 5, not 3" fixes the set instead of logging a second
    one. `workout_log` feeds the progression math, so a phantom set does not just
    read wrong — it prescribes wrong.
11. **(2026-09-29)** The conversational instructions are about half as long.
    Three overlapping sections became two in which each rule appears once; the
    duplication was the thing being fixed, not the length.

**Deliberately unchanged**: every `tool_mutation` guard stays and stays tested;
the round-level multiple-target check stays; the calendar keeps its naive-local
storage convention.

## 4. Deployment procedure

> **Note added 2026-09-29.** The equivalent of steps 0–5 below was carried out
> under incident authorisation, using `docker-compose.incident-recovery.yml`
> rather than the overlay drafted here, and gated on `readiness_probe.py`. That
> was incident recovery, **not** acceptance of this release; the live validation
> §7 asks for is still outstanding.

```bash
cd /home/david/jarvis

# 0. Snapshot the database. Not optional — this is the only true undo.
pg_dump "$DATABASE_URL" -Fc -f ~/sara_pre_reliable_$(date +%Y%m%d%H%M).dump

# 1. Confirm the deployable bytes are the validated bytes.
cd /home/david/sara-candidate-20260928-reliable
sha256sum -c --quiet CANDIDATE_MANIFEST.sha256 && echo OK
cat CANDIDATE_MANIFEST_HASH   # must equal the sha256 in §1
cd /home/david/jarvis

# 2. A NEW overlay file. Touches no existing compose file, and is NOT named
#    docker-compose.override.yml (which would silently affect every other
#    compose invocation in this repo while NOT applying to production, since
#    production is invoked with an explicit -f).
cat > docker-compose.candidate-reliable.yml <<'YAML'
services:
  backend:
    volumes:
      - /home/david/sara-candidate-20260928-reliable/backend/app:/app/app:ro
      - /home/david/sara-candidate-20260928-reliable/backend/alembic:/app/alembic:ro
YAML

# 3. Migrations FIRST. The code as it stands CANNOT run on schema 154 — auth
#    fails closed and every request 401s (measured, see §5). Explicit target,
#    not `head`, so a migration added later cannot ride along unnoticed.
docker compose -f docker-compose.dev.yml exec backend alembic current   # expect 154_saved_meal
docker compose -f docker-compose.dev.yml exec backend alembic heads     # expect 158_… (single head)
docker compose -f docker-compose.dev.yml exec backend alembic upgrade 158_reminder_delivery_state

# 4. Start the candidate. BOTH -f flags, in this order, every time.
docker compose -f docker-compose.dev.yml -f docker-compose.candidate-reliable.yml up -d backend

# 5. Gate on the readiness probe, not on /health. /health returned 200 on a pair
#    whose auth was completely broken, which is why the probe exists.
#    NOTE: the probe WRITES — one note, and one user row if no user with its
#    email exists. It removes exactly what it created and prints a DISCLOSURE
#    block either way.
docker compose -f docker-compose.dev.yml -f docker-compose.candidate-reliable.yml \
  exec -e PYTHONPATH=/app backend python tests/assistant_acceptance/readiness_probe.py
#    Non-zero exit => STOP.
```

Mounting `app/` and `alembic/` read-only rather than the whole `backend`
directory is the difference from the rc2 procedure, and it is deliberate: this
snapshot does not contain `static/`, `uploads/` or `docker/`, so mounting it
whole would hide them from the running app.

### The workers — now pinned, and started

`docker-compose.dev.yml` mounts `./backend` into every celery service, so an
overlay that repoints `backend` alone would leave the API on the candidate and the
workers on the working tree. Those are currently *close* — the working tree is
what the candidate was frozen from — but they are not pinned to each other, and
any later edit to the working tree would change the workers without changing the
API. That is the shape of the 2026-09-27 incident, one process at a time.

So the overlay pins all of them. Add the same two read-only mounts to
`celery-worker`, `celery-critical`, `celery-david-priority`, `celery-acs` and
`celery-beat`:

```yaml
# append to docker-compose.candidate-reliable.yml
  celery-worker:        &pinned
    volumes:
      - /home/david/sara-candidate-20260928-reliable/backend/app:/app/app:ro
      - /home/david/sara-candidate-20260928-reliable/backend/alembic:/app/alembic:ro
  celery-critical:      *pinned
  celery-david-priority: *pinned
  celery-acs:           *pinned
  celery-beat:          *pinned
```

**This has now been rehearsed with workers actually running**, which it had not
been when this document was first written. On 2026-09-29 the validation stack's
`isolated-worker` profile was started against the candidate with all five roles
(`docker-compose.reliable-assistant.yml`, artifacts under
`run_20260929_workers`):

* each printed its own queue set — general on
  `cognitive,health,input,maintenance,low_priority,reflection,dispatch`, then
  `critical`, `david_priority`, `acs`, and beat;
* four answered `celery -A app.celery_app inspect ping` over the disposable
  broker — `4 nodes online`;
* a sha256 over the four modules this task owns is **identical in all five
  containers and on the host snapshot** (`c9b52336eed7c4f8`), so every worker is
  demonstrably running the candidate's bytes rather than something nearby.

What that establishes is that the workers **boot and consume on the candidate**.
It does not establish that any background workflow behaves correctly — journey J5
(background/documents) has still never run. The 09-27 deploy-prep compatibility
findings (identical 136-task registration sets, the patch touching zero
`.delay(`/`apply_async`/`@task` lines, old-code inserts succeeding against 158's
additive-with-default columns) still apply, and none of this task's changes
touches a task definition or an enqueue site — but that is inherited evidence,
not new.

## 5. Recovery

Restart safety is a property of a **(source, schema) pair**, not of either half.

### A. Restarting *this* candidate — covered, and rehearsed

```bash
cd /home/david/sara-candidate-20260928-reliable && sha256sum -c --quiet CANDIDATE_MANIFEST.sha256
cd /home/david/jarvis
docker compose -f docker-compose.dev.yml -f docker-compose.candidate-reliable.yml \
  up -d --force-recreate backend
docker compose -f docker-compose.dev.yml -f docker-compose.candidate-reliable.yml \
  exec -e PYTHONPATH=/app backend python tests/assistant_acceptance/readiness_probe.py
```

**Rehearsed end to end on the disposable stack, 2026-09-29:**

| step | result |
|---|---|
| probe on (candidate, 158) | **READY** — schema objects + ORM, a real token validating over HTTP, a note written and confirmed by direct SELECT, a search that finds it |
| `alembic downgrade 154_saved_meal` (4 real downgrades) | applied |
| probe on (candidate, 154) | **NOT READY** — `AUTHENTICATES` fails: "`_is_revoked` fails CLOSED — every request would 401" |
| manifest re-verified after the schema move | clean (915 files at the time; 916 after the 2026-09-29 additions) |
| `alembic upgrade 158_reminder_delivery_state` (4 real upgrades) + restart | applied |
| probe again | **READY** |

Both directions of the schema move ran through real alembic. The probe writes
and removes its own rows and discloses them.

### B. Recovering from a *defective* candidate — a destination now exists and has been used

This section said "NOT covered". That was accurate and it was the largest hole in
the package, so it was filled. `backend/scripts/rehearse_reliable_release.sh`
builds and exercises the destination end to end on disposable databases:

| step | result 2026-09-29 |
|---|---|
| load the checked-in pre-release schema capture (`tests/fixtures/sara_hub_schema.sql`) | 302 tables; `chat_pending_proposal` and `revoked_token` **absent**, i.e. genuinely the pre-release state |
| stamp `154_saved_meal` from the candidate image's own alembic | at `154_saved_meal` |
| `pg_dump` it — **this is the recovery destination** | 554,106 bytes |
| `alembic upgrade head` from the candidate image's own alembic | 155 → 156 → 157 → 158, at `158_reminder_delivery_state (head)` |
| every object the candidate queries | `chat_pending_proposal`, `revoked_token`, `action_receipt`, `reminder`, and `reminder.delivery_status/claimed_at/delivery_attempts/last_error` all present |
| **restore the dump into a fresh database** | restored, reports `154_saved_meal` |
| is the restored destination really the previous release? | `saved_meal` present, `app_user` queryable, **`reminder.delivery_status` absent** — the forward schema wearing a rollback label would have failed this |
| the forward database still answers the queries that 401ed on 09-27 | yes |
| the (source, schema) pair actually serves | the candidate **image** started against the released schema and `readiness_probe.py` ran inside it |

Two findings from doing it, both recorded in the evidence map:

* **`alembic upgrade` cannot build the schema from an empty database** (row N35).
  The first attempt failed with `relation "episode" does not exist` on the first
  `ALTER TABLE`, because the migration history assumes a pre-alembic baseline —
  already documented in
  `docs/plans/incidents/2026-09-22_test_run_against_live_db.md` §7. A release plan
  resting on "the migrations can rebuild it" would be a plan that cannot recover.
  The rehearsal therefore starts from the real captured schema.
* The recovery destination is a **schema** destination, built from a
  schema-only capture plus a dump. Restoring production's *data* into it is the
  separately-verified backup path below.

**What is still true, and is the residual risk:** the code production runs today is
a process image from 09-22 whose source no longer exists on disk, so *that exact
build* cannot be redeployed. What now exists is a verified destination at schema
154 that the candidate can be pointed at — which turns "accept downtime while a
fallback is built" into "restore and stand up a 154-compatible source". Building
and validating that 154-compatible **source** snapshot is still not done, and until
it is, a defective candidate means **fix forward** or **downtime**.

**Do not `alembic downgrade` as a recovery step** — measured in §5A to produce a
pair that cannot authenticate. Restore the dump into a destination instead, which
is what the rehearsal above does.

### Backup restoration — inherited, not redone

Verified **2026-09-27** by the convention task and not repeated here: a 226 MB
`-Fc` dump of production restored into a disposable `pgvector/pg16` with **zero**
`pg_restore` errors; 302 tables both sides; `alembic_version` `154_saved_meal`
both sides; row counts matched on all ten sampled tables; 1,910 non-null note
embeddings and the `<=>` operator working on restored rows. Dump and sha256 in
`/home/david/sara_backup_verify/`. That is evidence about the **data**, and it is
current for the data; it says nothing about application recovery, which is §5B.

## 6. Verified workflows, and what is not verified

### Deterministic

Measured 2026-09-29 by **controlled-clock comparison**, because the correction was
explicit that file modification dates do not establish that a failure is
unrelated. `backend/scripts/controlled_clock_suite_compare.sh` runs the same
selection against two trees minutes apart, each on its own freshly created
database:

| | baseline (2026-09-24 frozen snapshot) | candidate |
|---|---|---|
| passed | 2,366 | **3,040** |
| failed | 56 | 57 |
| errors | 25 | 25 |
| ran at | 14:32:58Z | 14:36:31Z |

**56 of the 57 candidate failures are present in the baseline at the same
moment.** Not "have old mtimes" — present, in a tree that predates every change
this task made, on the same clock, on the same engine, in the same image. The
three-way split (both / baseline-only / candidate-only) is in the artifacts.

The one candidate-only failure was chased to a demonstrated mechanism rather than
left at "absent from the baseline":

* `test_location_freshness.py::…[observed_at2]` — the parametrized instant is
  `datetime.now(timezone.utc) + timedelta(minutes=2)`, evaluated once at module
  import. Once a suite takes more than two minutes to reach the test, that value
  is neither in the future nor yet stale (the window is ten minutes), the guard
  under test never fires, and execution reaches `classify()` with the
  deliberately-`None` db. It passed in **both** trees when the file was run
  alone, and calling `process_report` with that same instant after two minutes
  reproduces the identical `AttributeError` on unmodified product code. This task
  lengthened the suite (~170 added tests), which is what exposed it. **Fixed in
  the test only** — the offset becomes an instant inside the test body; product
  code untouched. (Evidence row N36.)

The earlier "nine extra failures" figure is superseded: it was a point-in-time
count from one late-night run, and the clock-sensitive families it named
(`test_unified_notification`, `test_singular_sara_c5_fold_in`) do not reproduce at
this hour while 56 other failures do. The reconciliation is the split, not a
count. (Evidence row N37.)

**Stated limit of this comparison.** The baseline also predates David's own
2026-09-25..28 working-tree changes, so a candidate-only failure could in
principle belong to either. That is precisely why the single one was taken to a
causal demonstration instead of being attributed.

**This task's own tests: 304 passing** across `test_operation_contract.py` (124),
`test_outcome_grounding.py` + `test_grounding_through_the_chat_turn.py` (91),
`test_request_recovery.py` (18), `test_workout_set_correction.py` (14),
`test_chat_system_prompt.py` (41), `test_active_domain_tool_retention.py` (10),
`test_civil_time_contract.py` (24), plus
`test_generation_budget_gateway.py` (8) run separately.

### Live — one frozen acceptance trial, on manifest `e19baca7…`

Six-turn to twelve-turn journeys, each scored against a hidden outcome card
evaluated in SQL against a state dump taken from the database
(`backend/tests/assistant_acceptance/reliable_verdict.py`), never against Sara's
account of what she did.

| journey | verdict | checks |
|---|---|---|
| J1 notes/facts | **PASS** | 12/12 |
| J2 reminder | **PASS** | 12/12 |
| J3 tasks/lists | **PASS** | 7/7 |
| J4 food | **FAIL** | 1/3 — the correction tool was never offered (routing, row N18) |
| J6 mixed day | **FAIL** | 4/6 — the model called no tool on an explicit reminder request (row N19) |

J1/J2/J3 also passed on the earlier trial, so those three have **two** trials;
J4 and J6 have **one**. The plan's bar is two independently reset trials of all
six workflows, and that bar is **not met** — the generation allocation did not
stretch to it once the live passes started finding defects. Journey 5
(background/documents) was **written and never run**, for the same reason.

### Live — conversation acceptance

All 12 cases ran. Four of them (C02, C03, C04, C09) were contaminated by a
grounding-layer false positive this run itself exposed (row N26) — machinery
appended to a joke, a vent, and a disclosure about David's father. That was the
worst finding of the whole task for the original complaint. It is fixed, and the
fix is **verified live on all four of those exact cases**: the artifact is gone
and the replies are clean.

### Generation budget — exact

| | |
|---|---|
| ceiling | **300**, enforced by atomic pre-forward reservation against an append-only ledger |
| reserved | **277** |
| completed | 277 |
| failed | 0 |
| rejected at the ceiling | 0 |
| **remaining** | **23** |

Ledger:
`backend/tests/assistant_acceptance/artifacts/run_20260928_reliable/reliable_assistant_ledger.jsonl`.
Enforcement was proven **before** the first real generation, with a fake upstream,
at zero model cost: `backend/tests/test_generation_budget_gateway.py` (8 cases).
The 09-27 convention ledger (60) and the 09-24 study ledger (1600) are separate
and were neither credited nor debited.

### Limitations, by capability

* **Food correction**: the correction tool exists and is deterministically
  tested, but the intent classifier routed the correction turn away from the
  fitness family in both trials. The retention fix landed after the frozen trial
  and is **not live-verified** (row N18).
* **Workout-set correction**: not implemented. Journey 4 covers food only.
* **Background work and documents**: journey 5 not run. No live evidence.
* **Model tool-selection failures remain**: on an explicit "Add a reminder to
  water the plants tonight at 8", with `reminders_create` on the menu and nothing
  gated, the model called no tool and denied the capability (row N19). Not
  fixable from the application; what the application now guarantees is that the
  reply says nothing was written.
* **Advice pressure survives in part**: an opinion question still gets an essay
  (C01), and "I've done it before, it's fine" still drew more advice (C07).
* **State descriptions are out of grounding's scope** — deliberately, and stated
  in the module: it checks action claims against the ledger, not readbacks.
* **Cross-turn denials** are now checked against the durable receipt record, but
  that fix landed after the frozen trial and is deterministic-only (row N22).
* **18 compiled findings are `reproduced/unfixed`**, each named in the evidence
  map with why; **5 are `superseded with evidence`** — pre-existing repairs whose
  deterministic tests pass and which this task did not re-verify live.
* **Workers were never run** in this task's validation (see §4).
* **Latency is out of scope** per the plan. For reference, turns ran 45–160 s on a
  gateway held at concurrency 1 on a memory-pressured host; that is not a
  production number.

## 7. What is being asked for, and what is not

**No deployment approval is being requested.** The implementation is complete and
the release and recovery path is rehearsed, but the six behaviors the 2026-09-29
correction named have had **no live check at all**. Implementation is not
verification, and asking to deploy on 304 passing unit tests would be asking you
to accept exactly the substitution this whole task exists to stop.

### What would close the gap, and what it costs

23 generation requests remain of the 300 ceiling. They are not enough for the
plan's bar (two independently reset trials of all six workflows, plus the twelve
conversation cases — roughly 150–200 requests). They are enough for a **targeted
spot-check of the four changed behaviors that can fail visibly**, at one turn
each, and that is what I would spend them on if you want a live signal now rather
than an allocation:

| check | turns | what it would establish |
|---|---|---|
| "Yeet the vet one." against a real reminder | 1 | the unknown verb now asks instead of cancelling |
| "Scratch the vet one, I already called them." | 1 | recovery makes the call the turn didn't, and the receipt shows one cancellation, not two |
| "225 for 5, not 3." after a logged set | 1 | one set changed, not two rows |
| "My dad has tests tomorrow. He's being casual about it." | 1 | no grounding text, no advice, no metric, no task |
| a successful write with a reply that ignores it | 1 | the appended state is the ROW's, not the tool's |

That is **5 requests**, leaving 18 in reserve for a retry each. It is a
spot-check, not validation, and I would report it as one.

**The full live validation the plan asks for needs a specific additional
allocation.** The honest number is **200 requests**: two reset trials of J1–J6
(~120), journey J5 which has never run (~20), the twelve conversation cases
against the simplified prompt (~40), and ~20 for retries. If you grant less, say
how much and I will spend it in the order above — the conversational cases first,
since they are the ones your original complaint was about and the ones a unit test
can say nothing about.

### The two decisions, when they come

1. **Does the conversational half feel right to you?** Six excerpts from the
   frozen trial are in the session summary; full transcripts are under
   `backend/tests/assistant_acceptance/artifacts/run_20260928_reliable/`. Note
   that those transcripts predate the prompt simplification, so they show the old
   three-section prompt. No agent score is offered for this and none should be.

2. **May this exact package be deployed?** — not yet askable. When it is, the
   package is:
   * frozen source `/home/david/sara-candidate-20260928-reliable/backend`,
     manifest sha256
     `27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d`
   * image `sara-reliable-candidate:20260929`, code verified against that
     manifest from inside the container
   * schema target `158_reminder_delivery_state`, applied **before** the code,
     from the candidate's own `alembic/`
   * procedure §4, gated on `readiness_probe.py`, not on `/health`
   * recovery: §5, with a destination that has been restored from a dump and
     queried, not merely named

### What is still not done, stated plainly

* **No live evidence for any of the six 2026-09-29 changes.** Deterministic only.
* **The plan's two-trial bar is not met** for any workflow except J1/J2/J3, and
  those two trials ran against the code as it was *before* these six changes.
* **J5 (background/documents) has never run.**
* **The prompt simplification is unmeasured.** The father, breakfast and
  unwanted-advice cases are the reason it was done, and whether it works on them
  is unknown.
* **18 compiled findings remain `reproduced/unfixed`**, each named in the evidence
  map with why.
* **Recovery for a FAILED write is deliberately not attempted** — recovery covers
  the turn that made no call. Re-running a failed write behind the model's back
  would be a second attempt at something David never saw the first outcome of.
* **Latency is out of scope** per the plan. For reference, turns ran 45–160 s on a
  gateway held at concurrency 1 on a memory-pressured host; not a production
  number.

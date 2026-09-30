# Sara — production recovery

Written 2026-09-29, after a host-wide OOM and reboot put the mutable working tree
into production against an incompatible schema. Read this before touching
production. Full incident record and evidence:
`/home/david/sara_incident_20260929/INCIDENT.md`.

---

## The one thing to understand first

> ## Restoring the database does NOT restore service.
>
> A database backup restores **data**. Service needs a **(source, schema) pair**
> that can actually answer requests, and the two failure modes look identical from
> the outside because **`/health` returns 200 either way**.
>
> This is measured, not asserted. Drill C on 2026-09-29
> (`sara_incident_20260929/verify/22_drill_service_not_restored_on_154.txt`) took
> the current application artifact, pointed it at a database restored from backup
> at schema `154_saved_meal`, and started it:
>
> ```
> app started and /health answers: YES
>   [FAIL] 1. SCHEMA — missing: revoked_token, chat_pending_proposal,
>                      uq_action_receipt_idempotency_key, reminder.notified_at
>   [FAIL] 2. AUTHENTICATES — _is_revoked fails CLOSED — every request would 401
> VERDICT: NOT READY
> ```
>
> `app/core/auth.py::_is_revoked` queries `revoked_token`. If that query raises it
> returns `True` — it **fails closed on purpose**, because a revocation check that
> cannot run must not admit tokens. At schema 154 the table does not exist, so
> every authenticated request 401s while the container reports `(healthy)`.
>
> **So: there is exactly one verified forward pair and no verified fallback.**
> Restoring a pre-release database leaves you with data you can read and a service
> nobody can log into, unless you also have an application artifact that runs on
> that schema — and **no such artifact exists**. The build production ran before
> 2026-09-29 was a process image whose source is no longer on disk. It cannot be
> redeployed.
>
> If the current artifact is defective in use, the real options are **fix forward**
> or **accept downtime**. Never `alembic downgrade` as a recovery step.

---

## The pinned pair

| | |
|---|---|
| image | `sara-reliable-candidate:20260929` — `sha256:68ab3e3f444371ea3b5ded7b27575ded2278f8ea5d52a237491c00d22c852ee5` |
| code | 916/916 files == `CANDIDATE_MANIFEST.sha256`, hash `27932826a312cba3eaf541ff2c0c8ca898c8328260b3f5cba437e32cdbf6bf3d`, verified **from inside the running container** |
| frozen source | `/home/david/sara-candidate-20260928-reliable` (do not edit in place) |
| schema | alembic `158_reminder_delivery_state` |
| pin | `docker-compose.incident-recovery.yml` — `app/` and `alembic/` mounted **read-only** over `/app/app`, `/app/alembic` on the API and all five celery services |

## Operate production with one command

```bash
scripts/sara-prod verify      # check everything, change nothing
scripts/sara-prod up          # verify first, then up -d  (aborts on mismatch)
scripts/sara-prod restart
scripts/sara-prod ps | logs [svc] | stats | config
scripts/sara-prod readiness   # the four-capability probe (writes, cleans up, discloses)
```

`sara-prod` always passes **both** compose files and refuses to act when the
resolved configuration does not match the pinned artifact. It checks: both compose
files present; the image exists with the expected id; the frozen source matches its
manifest; every application service resolves to the pinned image with read-only
frozen mounts and nothing importable coming from the working tree; running
containers match and `/app/app` is genuinely `ro` inside; `alembic_version` is the
expected revision; and no disposable stack is running.

### Never do these

* **`docker compose -f docker-compose.dev.yml up -d …`** — the overlay only applies
  when it is named, so this recreates production onto the mutable working tree.
  That is the 2026-09-29 incident. The file now carries a warning header.
* **`scripts/deploy_production.sh`** — would rebuild from the working tree and
  recreate production without the overlay. It now refuses unless
  `SARA_ALLOW_LEGACY_DEPLOY=1` is set deliberately.
* **`docker system prune -a`** — would delete the pinned image if no container is
  using it at that moment. The daily `scripts/docker-prune-daily.sh` is safe: it
  prunes only *dangling* images and *anonymous* volumes.

## Durable recovery artifacts

Everything needed to rebuild this pair from nothing, under
`/home/david/sara_incident_20260929/`:

| artifact | path |
|---|---|
| the exact image | `artifact/sara-reliable-candidate-20260929.image.tar.gz` → `docker load -i <file>` |
| frozen source | `artifact/frozen_source_candidate.tar.gz` |
| manifests | `manifests/CANDIDATE_MANIFEST.sha256`, `CANDIDATE_MANIFEST_HASH`, `LIVE_TREE_AT_INCIDENT.sha256`, `live_vs_candidate.diff` |
| migration files | `artifact/migrations/154..158_*.py` + `alembic.ini` — **all four are untracked in git**, so these copies and the image are their only frozen record |
| configuration | `artifact/config/` — base compose, pin overlay, `sara-prod`, and the fully resolved production config |
| database backup | `backups/sara_hub_pre_recovery_202609292015.dump` (`sha256 96de67a0…`) + `SHA256SUMS`; earlier: `/home/david/sara_backup_verify/` |
| all verification evidence | `verify/`, `rehearsal/`, `logs/` |

## Rebuild from the artifacts

```bash
INC=/home/david/sara_incident_20260929

# 1. the application
docker load -i "$INC/artifact/sara-reliable-candidate-20260929.image.tar.gz"
docker image inspect sara-reliable-candidate:20260929 --format '{{.Id}}'
#   must print sha256:68ab3e3f444371ea3b5ded7b27575ded2278f8ea5d52a237491c00d22c852ee5

# 2. the frozen source (the read-only mounts point at it)
tar -xzf "$INC/artifact/frozen_source_candidate.tar.gz" -C /home/david
( cd /home/david/sara-candidate-20260928-reliable && sha256sum -c --quiet CANDIDATE_MANIFEST.sha256 && echo clean )

# 3. the data, if the database is gone too
createdb …  # then:
pg_restore -U sara -d sara_hub --no-owner --no-privileges "$INC/backups/sara_hub_pre_recovery_202609292015.dump"
#   this lands at schema 154 — see the warning at the top of this file

# 4. the schema the application needs, run FROM the artifact (never the working tree)
docker run --rm --memory=768m -e DATABASE_URL="<the production DSN>" \
  --entrypoint sh sara-reliable-candidate:20260929 \
  -c 'cd /app && alembic upgrade 158_reminder_delivery_state'

# 5. start it, and gate on the probe rather than /health
cd /home/david/jarvis && scripts/sara-prod up && scripts/sara-prod readiness
```

### If a migration fails

**Read `alembic current` before deciding anything.** Do not assume an outcome.

As this project is configured today, a failure anywhere in a 154→158 run rolls the
**whole run** back and leaves `alembic_version` at **154**, with data intact
(measured: `sara_incident_20260929/verify/20_drill_failed_migration.txt`). Two
things make that true, and both are worth re-checking before you rely on it:

* `backend/alembic/env.py` wraps `context.run_migrations()` in a single
  `context.begin_transaction()`, and **`transaction_per_migration` is not set** — so
  Alembic uses one transaction for the entire run. With
  `transaction_per_migration = true` you would instead stop at the last revision
  that completed, part-way to the target.
* Revisions 155–158 use only transactional DDL (`CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN`). A future revision using
  `CREATE INDEX CONCURRENTLY`, an autocommit isolation level, an explicit `COMMIT`,
  or a second connection would break the all-or-nothing property.

**A clean rollback is not a restored service.** Back at 154 the application cannot
serve — that is the whole point of the warning at the top of this file. Fix the
cause and re-run, or restore; either way the system is down until the pair is
consistent again.

## What is still not covered

* **No 154-compatible application artifact.** The recovery *destination* (a
  restorable 154 database) is proven; there is nothing that serves on it.
* **Journey J5 (background/documents) has never run.** The five workers are proven
  to boot, register 136 tasks and consume on this pair; background *workflows* are
  not validated.
* **The assistant repair work is paused and unvalidated live.** These bytes are in
  production because the reboot put them there and pinning them was the safe exit —
  that is not acceptance evidence. See the EVIDENCE NOTICE in
  `docs/plans/SARA_RELIABLE_ASSISTANT_RELEASE.md`.

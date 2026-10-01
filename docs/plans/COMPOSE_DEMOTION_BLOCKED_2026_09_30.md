# Demoting docker-compose.yml — BLOCKED, then RESOLVED 2026-10-01

> **RESOLVED.** David authorized fixing the scripts, so the blocker was cleared
> and the move was completed on 2026-10-01:
> `docker-compose.yml` → `deploy/archive-compose/docker-compose.legacy.yml`.
> `rebuild_backend.sh` and `quick_rebuild_backend.sh` now refuse and print the
> new-generation procedure. `research-watch.sh`, `run_replay.sh`,
> `gpu-cluster/deploy.sh` and `deploy_production.sh` name their compose files
> explicitly. `pi-dashboard`, defined only in the archived file and running,
> moved into `docker-compose.dev.yml`. A bare `docker compose` at the repo root
> now fails with "no configuration file provided", which was the point.
> The record below is kept because the analysis is the reason for all of it.

Recorded 2026-09-30. The instruction was: `git mv docker-compose.yml
deploy/archive-compose/docker-compose.legacy.yml`, but first grep for consumers,
and **"if anything load-bearing resolves docker-compose.yml by its default name
(a bare docker compose with no -f anywhere), STOP and report rather than move."**

That condition is met. The move was not performed.

---

## What resolves it by default name

A bare `docker compose` run from the repo root resolves `docker-compose.yml`
into project **`jarvis`** — the production project. Measured, not assumed:

```
$ docker compose config --format json | jq '{name, services: (.services|keys)}'
name: jarvis
services: [backend, canvas, celery-beat, celery-worker, db, frontend,
           minio, neo4j, pi-dashboard, redis]
```

And that file's `backend` service is:

```
backend.image  : (none)
backend.build  : context /home/david/jarvis/backend, dockerfile Dockerfile
backend.volumes: backend_data, ./data, ./deploy (ro), ./docs
backend.restart: unless-stopped
```

No `image:`, so it **builds from the working tree**. No read-only `app/` mount,
so **the pin is absent**.

### The two blockers

| script | what it runs | effect |
|---|---|---|
| `scripts/rebuild_backend.sh` | `docker compose build backend` then `docker compose up -d backend` | rebuilds production's backend from the working tree and recreates it **without** `docker-compose.incident-recovery.yml` |
| `scripts/quick_rebuild_backend.sh` | same pair | same |

**Both are the 2026-09-29 incident in one command**, from scripts whose names
invite use after a code change. They are why the move is blocked: not because
moving would break something valuable, but because these need a decision first.

Moving `docker-compose.yml` would make them fail with "no configuration file
provided" — strictly better than silently unpinning production, but still a
change to scripts you may use, and not mine to make unasked.

### Two more that the move would break (diagnostic, not dangerous)

| script | call | note |
|---|---|---|
| `scripts/research-watch.sh` | `docker compose exec -T db psql …` | read-only; `exec` targets the existing container, so it never recreates anything |
| `backend/tests/replay/run_replay.sh` | `docker compose exec -T backend pytest …` | runs the suite inside production's backend container against `sara_replay` |

`backend/tests/replay/provision.py` also defaulted to a bare `docker compose
exec -T db` — it ran `DROP DATABASE IF EXISTS sara_replay WITH (FORCE)` on the
production Postgres as user `sara`. That one is already fixed (a52e06d5): it now
takes `SARA_REPLAY_COMPOSE_FILE` / `_PROJECT` / `_DB_SERVICE` / `_DB_USER`, so a
replay can be provisioned entirely inside a disposable stack.

`scripts/deploy_production.sh:307` has a bare `docker compose ps`, but it sits
behind that script's refusal guard and is unreachable without
`SARA_ALLOW_LEGACY_DEPLOY=1`.

### Not a consumer

`start-production.sh` does not use compose at all. It starts uvicorn and npm
directly on the host with stale environment (`OPENAI_MODEL=gpt-oss:120b`, a model
that no longer exists) and advertises "SQLite database". It is dead, and
unrelated to this decision.

---

## Recommended order

1. **Fix the two rebuild scripts first** — make them name both compose files, or
   have them refuse outright and point at `scripts/sara-prod`. There is no
   legitimate "rebuild production's backend from the working tree" operation any
   more: a code change now becomes a new pinned generation via
   `refreeze_reliable_candidate.sh` → `build_reliable_candidate_image.sh` →
   `rehearse_reliable_release.sh` → `sara-prod cutover`.
2. **Then** repoint `research-watch.sh` and `run_replay.sh` at explicit `-f`
   files.
3. **Then** the move is safe, and the header work in `765a4bf7` already says
   everything the archived file needs to say.

Until step 1 happens, moving the file only converts a silent production hazard
into a confusing error message — an improvement, but it leaves the actual
hazard (that "rebuild the backend" means "unpin production") undecided.

## Deliberately not done

The orphan-queue topology in `docker-compose.yml` — no consumer for `critical`,
`acs` or `david_priority` — is **not** repaired, per instruction: repairing it
would re-legitimize that file as a way to run production, which is the incident
class the pin exists to prevent. It is documented in the file's own header
(`765a4bf7`) and left broken on purpose.

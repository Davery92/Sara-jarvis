# Archived compose variants

Point-in-time compose forks kept for the record, not for use. Each was written
for one dated validation run and is not maintained against the current stack.

Nothing here is referenced by any script, test or CI config — that is the
condition for being in this directory. Verified by grep at archive time.

| file | written for | why it is archived |
|---|---|---|
| `docker-compose.convention-validation.yml` | Convention-readiness live validation, 2026-09-27 | An overlay on `docker-compose.assistant-acceptance.yml` that capped the upstream model budget at 60 requests via the gateway ledger and pointed the api at the frozen candidate at `/home/david/sara-candidate-20260927/backend`. That snapshot path is specific to that run. Zero live references. |
| `docker-compose.legacy.yml` | The old production definition — was `docker-compose.yml` at the repo root until 2026-10-01 | Production stopped reading it at the 2026-09-29 pin. Archived because at the root it was what a **bare `docker compose` resolved**, into project `jarvis`, with a working-tree `build:` and no pin — making `docker compose up -d backend` a one-command replay of the incident. Its orphan-queue defect is deliberately unfixed. Its `pi-dashboard` service, the only definition of a running container, was moved into `docker-compose.dev.yml` rather than stranded; the copy here is dead. |

Note none of these resolve `.env` from this directory, so they do not even
`config` cleanly from here. That is fine — nothing here is meant to run.

## Compose files that are NOT archived, and must not be

The 2026-09-30 cleanup plan proposed archiving five files. Four turned out to be
actively referenced, so they stayed where they are:

- `docker-compose.incident-recovery.yml` — **this is the production pin.**
  `scripts/sara-prod` requires it on every invocation and
  `scripts/deploy_production.sh` refuses without it. Archiving it would break
  the only verified way to operate production. See `RECOVERY.md`.
- `docker-compose.test.yml` — the disposable test stack. `tests/env_guard.py`
  names it in the instructions it prints when it refuses a run, and
  `backend/scripts/provision_test_schema.sh` and `CLAUDE.md` both drive it.
- `docker-compose.assistant-acceptance.yml` and
  `docker-compose.reliable-assistant.yml` — both are passed by
  `backend/scripts/run_reliable_trial.sh` on the same command line.

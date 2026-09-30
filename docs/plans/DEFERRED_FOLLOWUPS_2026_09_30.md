# Deferred follow-ups — recorded 2026-09-30

Phase 6 of `CODEBASE_CLEANUP_PLAN_2026_09_30.md`. Nothing here was attempted.
Each needs its own plan. Ordered by what unblocks the most.

The first item is now the bottleneck for more than it was when the plan was
written: executing phases 1–5 turned up two more things waiting on it.

---

## 1. Move the chat globals into `app_state`, then extract `/chat/stream`

**Why it is first.** `main_simple.py` holds configuration in module-level
globals that endpoints REASSIGN at runtime to hot-reload the chat client:

```
PUT /settings/ai        global AI_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY,
                               OPENAI_BASE_URL, OPENAI_MODEL,
                               OPENAI_NOTIFICATION_MODEL, EMBEDDING_BASE_URL,
                               EMBEDDING_MODEL, EMBEDDING_DIM, BG_LLM_*
Codex OAuth handlers    global AI_PROVIDER, OPENAI_BASE_URL, OPENAI_MODEL,
                               CODEX_OAUTH_*
```

**What this blocks, measured:**

- `/chat/stream` (~1,700 lines) — the original target.
- The twelve settings + Codex-OAuth endpoints (~700 lines). The cleanup plan
  classified these as extractable; they are not, for exactly this reason.
- `/api/pi-dashboard/voice/chat` (589 lines) and `/voice/fast` (180), which
  additionally reach into `_CHAT_INVOKED_MUTATING_TOOL_NAMES`, `VOICE_MODEL`,
  `_build_activity_context`, `_apply_background_dispatch_policy` and
  `_get_canvas_mode`/`_set_canvas_mode`.

Together that is most of what is left in the file, all waiting on one change.

**Shape of the work.** Move the config onto `app/core/app_state.py` (which
already holds the same values, copied into module globals at import), have the
chat path read it from there, and make the settings endpoints mutate the state
object. `EMBEDDING_DIM` is the worked example to copy: both of its mutation
sites already assign `config.settings.embedding_dim` in the same breath, which
is what let `/analytics/dashboard` move in Phase 4.7 by reading
`settings.embedding_dim` instead. Do that for the rest, then the endpoints move
for free.

**Also in scope once that lands:** `SimpleLLMClient` extraction (the deferred
6A item from earlier planning) — `routes/fitness.py` and `routes/learning.py`
import it from `main_simple` today, and `routes/documents.py`,
`routes/reminders.py`, `routes/briefings.py` and `routes/research.py` import
other monolith internals (`DocumentProcessor`, `ntfy_service`,
`call_llm_simple`, `SessionLocal`/`Folder`/`Note`). Phase 4.9 cleared the auth
dependencies; these are what remain.

---

## 2. Scheduler tick diet

Replace the 5-second `world-state-drain` and `notification-predispatch` polls
with Redis pub/sub triggers, and audit every sub-15-minute interval job for
event-driven conversion. `scheduled_job` has 101 rows, 99 enabled.

Note when doing this: `notification-predispatch`'s 5-second interval is load
bearing in one direction — the reminder-dispatch fix (migration 158) relies on
catching a due item within 5 seconds of `due_at <= now`, having deliberately
removed the old 20-second future lookahead. Any change to that cadence has to
preserve "never fires early, and never more than a few seconds late."

---

## 3. Shell/typing tool pre-authorization

Move `run_command`, `write_file` and `device_type_into_window` behind
standing-order-style grants instead of prompt-text gating. The execution
boundary built in this series (`operation_contract`, `target_authorization`,
`reference_resolution`, `action_receipt_service`) is the machinery to hang this
on — it did not exist when the item was written.

---

## 4. Sensory SSH → fleet agent

`routes/sensory.py` shells out to the Jetson and the GPU host directly; route
it through `sara-agent` instead. Its `main_simple` auth import was removed in
Phase 4.9, so the module is no longer coupled to the monolith.

---

## 5. Brief-system consolidation

Five brief systems, three brief route modules, and live-file layers with no
cache invalidation. Needs a design pass, not a mechanical merge.

Two pieces landed already and should be read first: the day layer now writes a
structured freshness sidecar recording which calendar day its content
describes (commit `17840b61`), and the 120-second Redis cache over the whole
rendered brief is gone, because a cache hit returned the sections the docstring
claimed were live-computed (commit `07ed7e76`).

---

## 6. PKG write path

`remember_about_david` was removed after going 0-for-4. Diagnose and restore
with a passing test. Corrections currently persist only via notes. Constraint
to respect: the PKG must keep refusing to hold body measurements —
`health_metric` is the only authority for those.

---

## 7. New: production is running a pinned artifact, indefinitely

Not from the original plan, but it outranks most of it. Production is
`sara-reliable-candidate:20260929` with `app/` mounted read-only from
`/home/david/sara-candidate-20260928-reliable`, pinned by
`docker-compose.incident-recovery.yml`. As of this cleanup the git tree has
diverged from that frozen source, so **the committed code is no longer what
production runs**.

There is exactly one verified `(source, schema)` pair and no verified
fallback. Deciding when to cut a new pinned artifact from the committed tree —
via `backend/scripts/build_reliable_candidate_image.sh` and
`refreeze_reliable_candidate.sh`, gated on
`tests/assistant_acceptance/readiness_probe.py` — is its own piece of work and
is David's call. Until then, `docker-compose.yml` also needs a ruling on the
drift documented in its header, in particular that it has no consumer for the
`critical`, `acs` and `david_priority` queues.

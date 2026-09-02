# Fitness Plan Control — Full Manual + Sara-Driven Plan/Nutrition Editing

**Date:** 2026-08-17
**Branch:** feat/sara-mind-v2 (or a fresh branch off it)
**Status:** PLANNED

## Problem

David wants to say "I'm cutting for the next 3 weeks — training days 2,300 cal,
off days 1,900" (to Sara, or via the UI) and have the whole system reflect it:
today-target, food log rings, morning brief, Sara's chat context, the Nutrition
tab. Today that is not possible without hand-editing individual phase rows in
the web PhaseManager modal.

### Root causes (verified 2026-08-17)

1. **Sara's phase tools lag the API.** `PhaseCreateTool` / `PhaseUpdateTool`
   (`backend/app/tools/fitness/program_tools.py:715,858`) only expose the flat
   `calories_target/protein_target/carbs_target/fat_target`. The day-cycled
   columns (`calories_training_day`, `calories_rest_day`, `carbs_training_day`,
   `carbs_rest_day`, `fat_training_day`, `fat_rest_day`, `daily_steps_target`)
   exist in `fitness_phase`, in the REST API (`POST/PATCH /api/fitness/phases`),
   and in the web edit modal — but NOT in the tool schemas or their SQL. Sara
   literally cannot express a carb-cycled cut.
2. **No timeline surgery.** Phases are a fixed dated sequence laid down once by
   the plan importer. There is no operation anywhere (API, tool, UI) to insert
   a dated block ("3-week cut starting Monday") into the active program and
   shift/trim the surrounding phases. Overlap "works" only by accident of
   `ORDER BY start_date DESC` in `get_effective_phase()`.
3. **Nutrition tab goes stale.** `fitness_program.nutrition_guide` has exactly
   one write path: full plan re-import (`plan_importer.apply_imported_plan`).
   No PATCH endpoint, no tool. Editing phase macros leaves the guide preaching
   old numbers.
4. **iOS is read-only for plans.** `fitnessService.createPhase/updatePhase`
   exist in `ios-app/src/services/fitness.ts` but no screen uses them; the only
   editor (`NutritionGoalsFormScreen`) writes the legacy `fitness_goals`
   fallback, which is ignored whenever an active phase exists.

## Design principles

- The **phase remains the single unit of nutrition truth** — a "cut" is a dated
  phase in the active program, not a new override table. Everything downstream
  (`get_effective_phase` → `today-target` / `fitness_context` / morning brief)
  already resolves by date, so a correctly-dated phase propagates everywhere
  with zero resolver changes.
- One new **plan_adjust service** owns timeline surgery so the API endpoint,
  the Sara tool, and any future UI all share the same logic (mirror of how
  `training_day.is_training_day()` unified day-type resolution).
- Qwen does the tool-calling (local-first policy); keep tool schemas simple and
  flat — no nested objects.

---

## Phase 1 — Tool parity (small, unblocks "tell Sara" immediately)

**Files:** `backend/app/tools/fitness/program_tools.py`

- Add to `PhaseCreateTool` and `PhaseUpdateTool` parameter schemas + `execute()`
  signatures + SQL:
  - `calories_training_day`, `calories_rest_day`
  - `carbs_training_day`, `carbs_rest_day`
  - `fat_training_day`, `fat_rest_day`
  - `daily_steps_target`
- Update both tool descriptions to explain training/rest cycling ("set the
  split fields for carb-cycled plans; flat `calories_target` is the weekly
  average fallback").
- `ProgramUpdateTool`: no change required for the cut scenario (activation has
  its own tool); leave as-is.
- While touching these tools, apply the standing feedback: log the real
  exception class before the catch-all returns a generic failure string.

**Tests:** extend/add `backend/tests/` unit test that instantiates the tools,
checks schema fields, and (with a DB session) round-trips a phase create +
update with split values.

## Phase 2 — `plan_adjust` service: dated block insertion + timeline shifts

**New file:** `backend/app/services/plan_adjust.py`

Core operation `insert_phase_block(db, user_id, *, name, goal, start_date,
end_date | duration_weeks, nutrition: dict, mode, notes)`:

1. Resolve active program (`phase_resolution.get_active_program`). Error if none.
2. Compute the block's `[start, end]` (default start = next Monday, or today if
   caller says "starting now"; `end = start + weeks - 1 day`).
3. Handle collisions with existing dated phases of the program, `mode`:
   - **`overlay`** (default): trim/split surrounding phases so dates never
     overlap — a phase fully inside the block is marked `completed`/shelved
     (status only, rows kept); a phase straddling the block start gets
     `end_date = block.start - 1d`; one straddling the block end gets
     `start_date = block.end + 1d`. Program `end_date` extended if the block
     runs past it.
   - **`push`**: later phases shift back by the block's length (their
     start/end += duration); program `end_date` += duration.
4. Insert the new `fitness_phase` with `order_index` slotted between neighbors
   and all nutrition columns (flat + split).
5. **Copy the weekly templates** into the new phase (same copy loop as
   `plan_importer.apply_imported_plan` step 3) from the phase that was
   effective the day before the block starts — training schedule continues
   through a cut unless told otherwise.
6. Call `reconcile_active_program_phase_statuses()` and return a summary dict
   (block dates, every phase whose dates changed, template count).

Also `end_phase_block_early(db, user_id, phase_id, on_date)` — sets
`end_date = on_date`, and (overlay mode bookkeeping) restores the trimmed
neighbor's dates if the block ended before its natural end. Keep V1 simple:
just re-extend the following phase's `start_date` back to `on_date + 1d` when
it was previously pushed/trimmed by this block (store the block's provenance in
`fitness_phase.notes` or a small JSON in `notes` — no new table in V1).

**Endpoint:** `POST /api/fitness/phases/insert-block` in `routes/fitness.py`
(+ `POST /api/fitness/phases/{id}/end-early`). Pydantic request models with
the same fields as the service.

**Sara tool:** `phase_insert_block` ("start a cut/bulk/maintenance block") +
`phase_end_block` in `program_tools.py`, registered under the `fitness`
category in `registry.py` AND added to the hardcoded tool list in
`/fitness/chat` (`routes/fitness.py` ~line 2150). Description written for the
exact utterance: *"I want to cut for the next 3 weeks, 2300 training days /
1900 rest days"* → one tool call.

**Tests:** `backend/tests/test_plan_adjust.py` — overlay trim (block inside one
phase, straddling two), push shift, no-active-program error, template copy,
end-early restore, and that `get_effective_phase` + `/today-target` return the
block's macros on a date inside the block and the old phase's macros after it.

## Phase 3 — Nutrition guide stays honest

**Files:** `routes/fitness.py`, `backend/app/services/plan_adjust.py`,
`program_tools.py`

- `PATCH /api/fitness/nutrition-guide` — accept the guide JSON, store on the
  active program (validate: dict, size cap ~32KB).
- `plan_adjust.insert_phase_block` regenerates the guide's `macros` table rows
  + `weekly_average` line from the new block's numbers mechanically (no LLM
  needed: labels Calories/Protein/Carbs/Fat, training/rest columns), preserving
  `rules`, `carb_timing`, `staples`, `self_check` untouched, and prepends a
  one-line banner to `how_it_works` ("Cut block active <start>–<end>").
  On `end_phase_block_early` / block expiry the next `insert` or a manual PATCH
  fixes it — V1 does NOT auto-revert the guide text on expiry (the macros shown
  by today-target are always live regardless).
- Sara tool `nutrition_guide_update` (thin wrapper over the same code path) so
  "update the nutrition tab to match" works from chat.

## Phase 4 — iOS + web surfaces

**iOS (`ios-app/src/screens/fitness/`):**
- New `PhaseFormScreen` (mirrors web modal: name, goal, dates, duration, flat
  targets, training/rest splits, steps target) using existing
  `fitnessService.createPhase/updatePhase/deletePhase`.
- Entry points: edit pencil on each phase row in the Programs accordion; a
  "Start a block…" action that calls the new insert-block endpoint with a
  simple form (goal preset cut/bulk/maintain, weeks, start date, the two
  calorie fields, optional carb/fat splits).
- JS-only change → works with current EAS dev client, no rebuild.

**Web (`frontend/src/components/fitness/`):**
- PhaseManager already edits everything; add an "Insert block" button wired to
  the new endpoint (reuse the phase modal with a mode toggle), and show the
  returned "phases shifted/trimmed" summary in a toast.
- NutritionGuide component: add an edit affordance (textarea-per-section is
  fine for V1) hitting the new PATCH.

## Phase 5 — Context + docs polish

- `fitness_context.py`: when the effective phase is an inserted block, the
  phase line already shows its name — make sure the name the tool generates
  includes the goal + dates ("Cut (Aug 18 – Sep 7)") so Sara's chat context
  and the morning brief read naturally. No code change if naming convention
  covers it; enforce in `plan_adjust` default name.
- Update `docs/` note or CLAUDE.md gotcha list is NOT needed; add memory entry
  when shipped.

## Explicit non-goals (V1)

- No new override/settings table — phases stay the single source of truth.
- No auto-recalculated TDEE / macro suggestions — David supplies numbers (Sara
  can reason about them in chat before calling the tool).
- No template editing inside the block flow (templates copy through unchanged;
  the existing template tools/UI already handle edits).
- No automatic nutrition-guide revert at block expiry.

## Sequencing & verification

1. Phase 1 alone is shippable and immediately useful — do it first.
2. Phase 2 is the heart; land service + tests before endpoint/tool wiring.
3. Phases 3–4 parallelizable after 2.
4. After deploy: rebuild backend container (`docker compose -f
   docker-compose.dev.yml build backend && up -d backend`) — deployed code lags
   working tree; verify with a live utterance to Sara ("start a 3-week cut,
   2300/1900") and check `/api/fitness/today-target` for tomorrow and for a
   date after the block ends.

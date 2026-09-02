# Sara Intelligent Food Logging Plan

Date: 2026-08-16 (rewritten 2026-08-16 from the original draft — see §1 for what changed)

Status: Draft for David's approval. Approval is **per-stage**, not for the whole
document. This is an implementation plan, not authorization to change nutrition
targets, training prescriptions, or existing food history.

## 1. What this rewrite changed and why

The original plan was architecturally right but sized for a multi-user product.
This system has one user. Changes:

- **Cut the analytics pipeline.** No p90s, cohort metrics, or abandonment rates —
  they're meaningless at n=1 and cost real effort. Three counters remain (§10).
- **Cut offline queueing and draft revision-conflict machinery.** Two devices,
  one human, home wifi/LTE. Kept: killed-app draft restore, idempotent commit.
- **Cut cross-user isolation work.** `get_owner_id()` made single-user official.
- **Server drafts only where they're needed** — AI captures (voice/photo/label).
  Manual composing stays client-local and commits idempotently.
- **Label OCR promoted above meal photos.** OCR is deterministic and fills a real
  gap (unknown barcodes). Meal-photo estimation is demoted to a gated experiment.
- **Stages are separately approved and verified-live before the next starts.**
  The historical failure mode here is the silently dropped tail; the structure
  now assumes it.

Success is not a metrics dashboard. Success is: **David is still logging daily in
30 days, and the common path (repeat a usual meal) takes under 15 seconds.**

## 2. Product principle

> Logging should feel like approving or correcting a good draft, not completing
> a database form.

### Non-negotiable rules (apply to every stage)

1. **One meal model.** A food log row is one meal event containing one or more
   canonical items. Breakfast = eggs + toast + coffee in ONE meal. iOS stops
   treating those as unrelated log actions.
2. **One draft model.** Every capture mode (search, recents, saved meal, repeat,
   barcode, voice/text, photo, label) produces the same `MealDraft`. Capture
   adapters propose items; the composer owns review, totals, and commit.
3. **Explicit commit for AI output.** Search results and high-confidence repeats
   may quick-add with Undo. Anything AI-generated (text, voice, photo, label)
   opens an editable draft first. Sara never silently logs an unresolved match,
   an estimated portion, an inferred brand, a guessed cooking method, or a
   substitution chosen because it flatters the macro target.
4. **Identity ≠ recommendation.** Food resolution answers "what did David eat";
   guidance answers "what might fit next." Search ranking must never swap the
   likely food for a better-macro one. Goal-aware suggestions live on a labeled
   suggestion surface only.
5. **Personalization is correctable.** Remembered servings/placements update
   from corrections without rewriting history. Controls: forget a learned
   default, suppress a suggestion, save/unsave a meal, choose whether a one-off
   correction becomes the default.
6. **Neutral coaching.** "43 g protein remaining", not moral labels or medical
   claims.
7. **Local-first.** All background/agentic model calls run on the local Qwen
   stack per the standing policy. Any vision work uses a locally hosted model —
   and its quality gate (§8) passes before UI gets built on top of it.
8. **ET everywhere user-facing.** All date logic through `app.core.timezone`
   helpers. The web's UTC-derived dates are a Stage A bug fix.

## 3. Shared domain contract

### 3.1 Canonical food item v2

Defined once in backend schemas, mirrored by parity-checked TypeScript types
(same discipline as `check-workout-contract-parity.mjs` — a food parity script
is a Stage A deliverable):

```json
{
  "schema_version": 2,
  "line_id": "client-or-server UUID",
  "food_id": "fs-123 | custom UUID | recipe-UUID | null",
  "name": "Chicken breast, cooked",
  "brand": null,
  "source": "fatsecret | user | recipe | manual | photo | label",
  "serving_id": "source serving ID or null",
  "serving_description": "3 oz",
  "quantity": 2,
  "unit": "serving",
  "base_amount": 1,
  "base_unit": "serving",
  "calories": 280,
  "protein": 52,
  "carbs": 0,
  "fats": 6,
  "nutrition_basis": "resolved_serving | stored_snapshot | estimated",
  "resolution_confidence": 0.98,
  "estimate_notes": null
}
```

Calories/macros are scaled line totals. `base_amount`/`base_unit` + serving
provenance make quantity edits deterministic. v1 snapshots stay readable through
the existing defensive rehydration path; never persist client UI state in
`detailed_items`.

### 3.2 Meal draft

```json
{
  "draft_id": "UUID",
  "meal_type": "lunch",
  "logged_at": "local timestamp with offset",
  "items": [],
  "notes": "",
  "capture_modes": ["voice"],
  "status": "draft | committed | discarded",
  "warnings": []
}
```

- Manual/search drafts: **client-local**, restored after app kill, committed via
  the idempotent commit endpoint.
- AI-capture drafts (voice/text/photo/label): **server-backed** (the adapter has
  to return a draft ID), simple last-write PATCH — no revision/conflict system.

### 3.3 Saved meal

`saved_meal` (id, name, default meal type, source log id, archived) +
`saved_meal_item` (order, canonical item snapshot). Repeating copies snapshots
into a new draft — never linked by reference, never mutated when the food
database changes.

### 3.4 Preference signals

Derived queries over food history first (last accepted serving, meal placement,
frequency, recency). A small explicit preference table only if derived queries
prove too slow or unstable — inspectable fields, never an opaque profile.

## 4. Stage A — Correctness (fix before building)

**Goal: existing logs are safe before we create faster ways to make more of
them. This stage is a bug-fix plan and should be approved immediately.**

Tasks:

- Canonical item v2 schema + shared JSON fixtures + food-contract parity script
  (fixtures: FatSecret real serving, synthetic gram serving, custom food, recipe
  serving, unresolved manual item, legacy iOS snapshot, legacy web snapshot,
  multi-item meal).
- Backend derives meal totals from line-item totals on create/update; alert-log
  on any stored total ≠ sum of items.
- iOS: render multi-item meals from each detailed item's macros (stop splitting
  totals evenly — `ios-app/src/services/fitness.ts`).
- iOS: full edit preserves notes and timestamps; support multi-item edit.
- iOS: date-aware diary fetching — an unloaded historical date shows loading or
  fetches, never false-empty (`FitnessScreen.tsx`).
- Web: replace UTC date derivation with local-date helpers (dashboard nutrition
  + weight logging).
- Web: wire the dashboard Log Meal button (`FitnessSection.tsx`); auto-expand
  today's meal section (`FoodLog.tsx`).
- Transactional multi-item commit + idempotency key on create (same atomicity
  lesson as batch workouts).
- v1 endpoints untouched.

Acceptance:

- Cross-client create/edit/reopen round-trip fixtures pass (Python + web TS +
  iOS TS).
- Two-item meal totals exact on all three surfaces.
- Saving an untouched meal changes no persisted field.
- A retried commit cannot duplicate a meal.
- No date anywhere derives from UTC midnight.

## 5. Stage B — Diary, composer, repeats (the actual product)

**Goal: the common path beats MyFitnessPal with zero AI involved. This is where
the value is; approve after Stage A verifies live.**

### 5.1 Today diary

Nutrition opens to the local date: calories + macros consumed/remaining,
training/rest-day context, Breakfast/Lunch/Dinner/Snacks sections with
subtotals and per-meal `Log` buttons, one global capture button. Today's
sections expanded. Web's separate Food Log and Nutrition views converge here —
one `GET /api/fitness/food-diary?date=` endpoint (+ `/range` for history)
returning totals, grouped meals, targets, and coverage status.

### 5.2 Composer

`Log Breakfast` opens a draft with meal + time preselected: search field;
groups for Suggested / Recent / Yesterday / Saved Meals / Recipes / My Foods;
selected items visible as a cart with quantity + serving controls per item;
sticky subtotal; `Log N items` primary action. `+` on a search result adds with
the remembered serving; tapping the body opens serving detail. The composer
does not close between items. Shared client-side helpers for serving math and
canonical-item conversion (extracted once, parity-checked).

### 5.3 Repeats and saved meals

- `Save this meal`, repeat meal, copy yesterday's meal, copy day
  (`POST /food-log/{id}/repeat`, `/food-log/copy-day`, saved-meals CRUD +
  `/saved-meals/{id}/draft`) — all idempotency-keyed.
- Per-meal contextual cards: "Same breakfast as yesterday", "Usual protein
  shake", "Chicken rice bowl · logged 4× recently". Direct repeat logs
  immediately with an Undo snackbar (undo token hits an explicit endpoint,
  short documented window); editing first opens a draft.

### 5.4 Deterministic ranking

Inspectable factors only: previously-selected identity, same meal type, same
time bucket, recency, frequency, weekday, saved/favorite, training-vs-rest-day
correlation, source trust, query match quality. Each suggestion carries its
reason ("Usual breakfast", "Logged yesterday", "Used 8 times"). Combination
suggestions require repeated co-occurrence under the same meal type. No learned
model unless the deterministic ranker demonstrably falls short. Suppress/forget
controls honored immediately.

Acceptance:

- A usual meal repeats in ≤2 taps; a 3-item meal composes without the composer
  closing; Undo restores totals and removes the row exactly once; ranking is
  deterministic for fixed history fixtures; both clients produce byte-equivalent
  canonical items from the same fixture.

**Decision gate: use Stage B daily for two weeks before approving Stage C.**
If repeat + search is fast enough, the AI capture stages may not be worth their
maintenance weight. That is a success outcome, not a failure.

## 6. Stage C — Voice/text drafts (refactor, not new capability)

**Goal: move the existing conversational logging (`food_search_and_log`) onto
the draft rail with a review step. This is a rewiring of something that already
works — size it accordingly.**

- Strict extraction schema (items, amounts, units, brands, prep, meal type) →
  resolver → deterministic serving math → one `MealDraft` with per-item
  identity/portion confidence. Qwen with `enable_thinking: False`.
- Resolution precedence: explicit personal reference ("my usual shake") →
  exact personal history → exact brand/product → trusted DB match with
  compatible serving → generic estimate with visible warning.
- Clarification policy: ask ONE concise question only when the ambiguity
  materially changes the result (dry vs cooked, breast vs thigh, package vs
  serving, missing quantity with no personal default). Otherwise present an
  editable default with a warning.
- Corrections ("make the rice 150 g", "that was thigh") mutate the same draft.
  Nothing commits until David taps Log or explicitly says to.
- `POST /meal-drafts/from-text`; voice transcribes then uses the same endpoint.
  The chat tool calls the same domain service — its independent schema and
  nutrition math are deleted in this stage.
- Golden corpus of real phrasings/quantities/brands/corrections; gate on agreed
  identity + quantity accuracy before the flag flips.

Acceptance: corpus thresholds met; no voice/text call writes history before
commit; corrections revise rather than duplicate; a network retry returns the
same committed log; the old tool-side nutrition math no longer exists.

## 7. Stage D — Nutrition-label OCR

**Goal: unknown barcode → photograph the Nutrition Facts panel → editable
custom-food draft. Deterministic, verifiable, fills a real gap.**

- OCR to a custom-food draft: product/brand, serving size + servings per
  container, calories + macros per serving, barcode if present.
- Validate arithmetic: calories vs macro-derived calories (labeling tolerance),
  per-serving vs per-container, decimal/locale parsing. Low-confidence digits
  visibly flagged; user confirms before the food is created and logged.
- Runs on local models. Strip EXIF; short retention for raw label photos;
  immediate deletion control.

Acceptance: label endpoint creates drafts only; flagged digits render; a
confirmed label round-trips into a correct custom food and log line.

## 8. Experiment — Meal-photo drafts (not a stage)

Meal-photo calorie estimation is mediocre in every app that ships it. It stays
behind a flag as an experiment with an entry gate, in this order:

1. **Model gate first, UI second.** Build a small labeled eval set from David's
   actual common meals. Run the locally hosted vision model against it. If
   identity/portion accuracy is not clearly useful, stop — no review UI gets
   built.
2. If the gate passes: provider-neutral analysis interface (store model version,
   labels + confidence, portion estimate + uncertainty, final corrections);
   review screen distinguishing high-confidence items, alternatives, estimated
   portions, and unresolved regions; portion chips (4/6/8 oz, ½/1/1½ cups);
   manual search inside review; mixed dishes prefer a saved recipe or a
   labeled generic estimate over fabricated ingredient precision.
3. Same privacy rules as Stage D. Never train on personal photos.

## 9. Stage E — Guidance (last, optional, dismissible)

- Post-commit, at most one line: "Lunch logged. ~620 kcal and 43 g protein
  remain." / "Your usual Greek-yogurt bowl would add 28 g." Suggestions state
  impact and open a draft — never auto-log.
- Weekly patterns only past an evidence threshold, with the window stated
  ("Protein was lowest at breakfast on 5 of the last 7 logged days").
  Observational language only. Target changes remain proposals.
- Feedback controls: helpful / not relevant / don't suggest this. Turning
  guidance off degrades nothing.

## 10. Observability (right-sized)

Three counters: **duplicate-log rate, undo rate, AI-draft acceptance rate**
(items accepted unchanged vs corrected — this is the honest quality signal for
Stages C/D). Plus structured operational logs (durations, confidence buckets,
provider failures — IDs and timings, never meal contents or photos).

Alerts (via the swallow/interior surface, not push):

- stored meal total ≠ sum of line items;
- idempotency key produced two rows;
- diary day reported empty after a successful non-empty log;
- v1/v2 snapshot parse failure.

## 11. Testing

- **Unit:** serving parsing/conversion, synthetic servings, v1→v2 rehydration,
  line/meal arithmetic, ET date behavior across DST, ranking determinism,
  clarification thresholds, label arithmetic validation.
- **Contract:** the §4 fixture set verified in Python + web TS + iOS TS via the
  parity script, run in CI/pre-commit like the workout one.
- **Backend integration:** atomic multi-item create/update, idempotent
  commit/repeat, undo token lifecycle, diary grouping/coverage, saved-meal
  snapshot semantics, one domain event per commit.
- **Client:** quick-add + undo, multi-item composer, untouched-edit round trip,
  repeat yesterday, historical date load, voice draft correction (Stage C),
  label review (Stage D).
- **Intelligence eval (C/D only):** versioned private sets; track *false
  confident matches* separately from misses — a system that asks is safer than
  one that confidently logs the wrong thing.

## 12. Rollout

- One feature flag per stage (plus one for the photo experiment). v1 endpoints
  and UI remain until the replacement stage has run live for its gate period.
- v1 `detailed_items` are never rewritten; v2 written for new/edited entries
  once the flag is on; backfill only fields derivable without re-resolving
  identities.
- Rollback = flag off. Draft tables are additive; provider failure disables
  only that capture adapter; ordinary search/barcode logging never depends on
  AI services.
- **Every stage ends with: rebuild + restart backend/celery, verify the running
  containers, then a live walkthrough on both clients. A stage is not "done"
  until verified live** (deployed-code-lags rule). The next stage is a fresh
  approval with the previous stage's verification output attached.

## 13. Commit slicing

Stage A: `fix(food): multi-item macros, notes, ET dates across clients` ·
`feat(food): canonical item v2 + parity fixtures` · `feat(food): transactional
idempotent commit`
Stage B: `feat(food): unified diary endpoint` · `feat(food-web): today diary +
composer` · `feat(food-ios): today diary + composer` · `feat(food): saved
meals, repeat, undo, deterministic ranking`
Stage C: `feat(food): text/voice meal drafts through shared domain service`
Stage D: `feat(food-ios): nutrition-label capture + custom-food draft`
Experiment/E: one commit each behind their flags.

## 14. Out of scope

Changing calorie/macro targets without separate approval; medical advice;
auto-eating-back workout calories; social feeds; restaurant/grocery
integration; training on private photos/transcripts; replacing trusted serving
data with visual estimates; removing v1 endpoints before migration completes;
offline write-queueing (revisit only if logging actually fails in daily use).

## 15. Definition of done (per stage, not per plan)

- **A:** correctness suite green on all three surfaces; live verification shows
  exact totals and no false-empty history.
- **B:** two weeks of daily use; usual meals genuinely ≤2 taps; David chooses
  to keep using it.
- **C:** corpus gate met; chat tool's independent math deleted; AI acceptance
  counter reporting.
- **D:** a real unknown-barcode product logged correctly end-to-end.
- **E / experiment:** live only if their gates pass; absence is an acceptable
  end state.

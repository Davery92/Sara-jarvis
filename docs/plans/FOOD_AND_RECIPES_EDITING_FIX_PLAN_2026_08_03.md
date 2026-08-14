# Food Log + Recipes Editing Fix Plan — 2026-08-03

Fixes for the food log and recipes features based on a full code review (backend routes/services,
web frontend, iOS app). David's complaints, all confirmed real:

1. Search results show "Costco Rotisserie Chicken — 213 cal" with no serving size; you must click in to learn if that's 3 oz / 1 serving / 100 g.
2. You can't change serving measurements anymore (log by grams/oz when FatSecret only lists "1 serving").
3. Editing anything (food log entries, recipe ingredients) means remove-and-re-add.

Plus four genuine data bugs found during the review (macros silently wrong). Fix those first —
they corrupt data regardless of UX.

**Ground rules for the agent:**
- Backend runs ONLY in Docker: `docker compose -f docker-compose.dev.yml up -d backend` (rebuild after code changes; deployed code lags the working tree until restart).
- iOS: JS-only changes take effect with an Expo reload of David's existing EAS dev client. Do NOT add native modules.
- Web frontend hot-reloads in the `jarvis-frontend-dev-1` container.
- No UTC in user-facing time logic; follow existing `formatLocalDateTime` patterns.
- Branch: work off `feat/sara-mind-v2` unless told otherwise (it's the active branch; confirm with David if a separate branch is wanted).

---

## Key architecture facts (read before touching anything)

- **Food search**: `GET /api/fitness/foods/search` (`backend/app/routes/food_database.py`). Custom foods first, then FatSecret. Each FatSecret result already includes the serving description parsed from FatSecret's summary line — it's returned as `serving_unit` (e.g. `"3 oz"`, `"1 serving"`) at `food_database.py:171`.
- **Food details**: `GET /api/fitness/foods/{id}/details` returns the full servings list. FatSecret servings carry `metric_serving_amount` + `metric_serving_unit` (e.g. 1 serving = 84 g) and are cached in `fatsecret_food_cache.servings_json`. ID prefixes: `fs-<fatsecret_id>`, `recipe-<uuid>`, bare UUID = custom food.
- **Food log**: table `food_log` with `food_items` (name/qty/unit) + `detailed_items` (JSON snapshot, schema currently differs per client — this is the root cause of the editing pain), plus row-level `calories/protein/carbs/fats` totals. Full-replace edit exists: `PUT /api/fitness/food-log/{log_id}` (`fitness.py:590`). `PATCH` only allows `meal_type`/`notes`.
- **Recipes**: table `recipe`; `ingredients` JSON of `IngredientItem` (`fitness.py:177` — has optional per-ingredient macros + `food_id`/`source`/`serving_description` provenance). Stored recipe `calories/protein/carbs/fats` are **PER SERVING** (see `estimate_recipe_nutrition` in `backend/app/services/recipe_nutrition.py:15` — it divides totals by servings). Explicit per-ingredient macros win over FatSecret re-estimation on save.
- **Clients**:
  - Web: `frontend/src/components/fitness/` — `FoodLog.tsx` (list + edit modal), `AddMealForm.tsx`, `FoodItemSelector.tsx` (add/edit meal items), `RecipeEditor.tsx` + `IngredientSearchInput.tsx` (recipes).
  - iOS: `ios-app/src/components/fitness/FoodLogModal.tsx` (add only), `ios-app/src/screens/fitness/FitnessScreen.tsx` (list; "edit" = meal-type alert only), `ios-app/src/screens/recipes/RecipeFormScreen.tsx` + `ios-app/src/components/fitness/IngredientSearchModal.tsx`.

---

## Phase 1 — Data-correctness bugs (do first, small diffs)

### 1.1 Recipe PATCH recalculates nutrition as if servings=1
`backend/app/routes/fitness.py:4837` (in `PATCH /recipes/{recipe_id}`):
```python
servings = updates.servings if updates.servings else 1
```
If a client PATCHes `ingredients` without resending `servings`, per-serving macros are computed
with servings=1 → inflated by the recipe's true serving count. (Web editor always sends servings,
masking it; partial PATCHes — e.g. Sara's chat tools — hit it.)

**Fix**: when `updates.servings` is None, read the recipe's current `servings` from the row fetched
in the existence check (extend that SELECT to return `servings`) and use it.

### 1.2 Recipe-as-food double-divide
`backend/app/routes/food_database.py:367-403` (`get_recipe_food_details`): stored recipe macros are
already per-serving, but this endpoint divides by `servings` again. Logging a 4-serving recipe from
food search yields 1/4 of the true per-serving macros.

**Fix**: remove the `per_serving()` division — return stored values directly as the "1 serving"
serving. Double-check no other caller of this endpoint compensates for the divide (grep for
`recipe-` id construction; iOS `FoodLogModal.handleSelectFood` and web `FoodItemSelector.addFood`
both consume it raw).

### 1.3 Web recipes quick-add tab shows a nonexistent field
`frontend/src/components/fitness/FoodItemSelector.tsx:719`: displays `recipe.total_calories`,
which the API never returns (it returns per-serving `calories`). Calories never render.

**Fix**: show `recipe.calories` labeled per serving (e.g. `≈{Math.round(recipe.calories)} cal/serving`).

### 1.4 Web `addRecipe` expansion undercounts
`FoodItemSelector.tsx:409-438`: expands a recipe into per-serving ingredient rows using each
ingredient's explicit macros; ingredients without explicit macros contribute 0 cal (the estimate for
them lives only in the recipe's stored totals).

**Fix (simplest correct)**: stop expanding into ingredients. Add the recipe as ONE `SelectedFoodItem`
("<name> (Recipe), 1 serving") using the recipe's stored per-serving macros (after 1.2 they're
trustworthy via the details endpoint too). Keeps log entries clean and matches iOS behavior.

**Verify Phase 1**: rebuild backend container; then (a) PATCH a multi-serving recipe changing only
one ingredient → stored per-serving calories unchanged in magnitude class; (b) GET
`/foods/recipe-<id>/details` for a 4-serving recipe → calories == stored `recipe.calories`; (c) web
recipes tab shows calories; (d) adding a recipe to a meal produces one row with per-serving macros.

---

## Phase 2 — Quick UX wins

### 2.1 iOS search results: show the serving size
`ios-app/src/components/fitness/FoodLogModal.tsx:862-871`: the result row shows
`{calories} cal • {protein}g protein • source` but omits `food.serving_unit`, which already holds
the serving description ("1 serving", "3 oz", "100 g").

**Fix**: prepend it — e.g. `Per {food.serving_unit} • 213 cal • 19g protein • FatSecret`. Guard for
missing/`"serving"` default. This alone kills the "click in to see what 213 cal means" complaint.
(Web already shows it — `FoodItemSelector.tsx:555` — no change needed there.)

### 2.2 Same gap in iOS recipe ingredient search
Check `ios-app/src/components/fitness/IngredientSearchModal.tsx` result rows; if serving text is
missing there too, apply the same one-liner.

---

## Phase 3 — Bring back weight/volume entry alongside real servings

Context: commit `9b694e34` (2026-07-01) made the iOS unit picker show ONLY FatSecret's serving list
when one exists (`FoodLogModal.tsx:1109-1134`, `applyServing` at :278). Deliberate (avoids sketchy
cross-unit math), but brand foods often list a single "1 serving" — so gram/oz logging became
impossible. The fix is NOT to restore blind unit conversion; use the metric equivalents FatSecret
provides.

### 3.1 iOS `FoodLogModal`
When servings are loaded, build the picker options as:
1. Every real serving: `"{serving_description} — {cal} cal"` (existing behavior), AND
2. If any serving has `metric_serving_amount` + `metric_serving_unit` (`g`/`ml`/`oz`), append
   synthetic weight options: `"g"`, `"oz"` (and `"ml"` for liquid-metric foods). Selecting one sets
   `baseNutrition` to per-1-unit macros derived from that serving:
   `perGram = serving.calories / (metric_serving_amount converted to g)` — then quantity is grams.
3. If NO metric data exists on any serving, keep servings-only (today's behavior) — don't guess.

Reuse the existing `UNIT_CONVERSIONS` table for oz↔g and ml conversions. Keep `displayNutrition`'s
qty-multiplier path; the synthetic options just provide a correct per-unit base.

### 3.2 Web parity
`FoodItemSelector.tsx` selected-row serving `<select>` (:789-818) and `IngredientSearchInput.tsx`
serving select (:283-305): append the same synthetic g/oz options derived from
`metric_serving_amount`. The web types already carry `metric_serving_amount`/`metric_serving_unit`
(`FoodServing` in `FoodItemSelector.tsx:80`) — `IngredientSearchInput`'s local `FoodServing` type
needs the two fields added.

**Verify**: pick a brand food whose only serving is "1 serving" but has metric data → log 150 g →
macros ≈ 150/metric_amount × serving macros. Pick a food with no metric data → picker unchanged.

---

## Phase 4 — Canonical logged-item shape + real edit flows (the big one)

Root cause of "remove and re-add": `detailed_items` schema differs per client — web saves its full
editor state (incl. client-only `calculated_*`, `servings`, `base_nutrition`), iOS saves a minimal
shape, chat tools save another. No editor can reconstruct state from another client's snapshot.

### 4.1 Define the canonical item (backend, additive — no migration)
One shape, documented next to `FoodLogCreate` in `fitness.py`:
```json
{
  "food_id": "fs-123 | <uuid> | recipe-<uuid> | null",
  "name": "…",
  "source": "fatsecret | user | recipe | manual",
  "serving_id": "FatSecret serving_id or null",
  "serving_description": "1 cup, cooked",
  "quantity": 1.5,
  "unit": "serving-desc | g | oz | ml",
  "calories": 320, "protein": 24, "carbs": 12, "fats": 18   // scaled totals for this line
}
```
Old rows stay readable (all consumers already `.get()` defensively). New writes from ALL clients use
this shape. Update: web `AddMealForm`/`FoodItemSelector` submit mapping, iOS `FoodLogModal`
submit (`detailed_items` construction at :482 and :511), and Sara's chat tool
(`backend/app/tools/fitness/food_search_log.py`) if its snapshot omits `food_id`/`serving_id`.

### 4.2 Web edit rehydration — currently DESTRUCTIVE, fix first within this phase
`FoodLog.tsx:402-417` passes stored `detailed_items` straight into `AddMealForm` as
`SelectedFoodItem[]`. For iOS/chat-logged entries these lack `calculated_*` → totals compute as 0 →
**pressing "Update Meal" without touching anything saves the entry's macros as 0**. Quantity edits
double-scale (stored per-line calories are already scaled totals, but `calculateNutrition` treats
them as per-serving).

**Fix**: on opening the edit modal, rehydrate each item:
- If `food_id` resolves (`fs-`/uuid/`recipe-`): fetch `/foods/{food_id}/details` (servings come from
  cache — cheap), rebuild a proper `SelectedFoodItem` with `servings`, re-select `serving_id` (fall
  back to matching `serving_description`, then index 0), set `quantity`, recompute `calculated_*`.
- If not resolvable: build a manual item whose `base_nutrition` = stored line macros ÷ stored
  quantity, so quantity edits scale correctly and untouched saves round-trip identically.
- Until rehydration completes, disable the submit button (never save zeros).

### 4.3 iOS food log edit — replace the meal-type-only alert
`FitnessScreen.tsx:274` (`handleEditFood`). Extend `FoodLogModal` with an optional `editEntry` prop
(mirror web's `AddMealForm`): prefill meal type, logged_at, and the item (rehydrated exactly as
4.2 — reuse `getFoodDetails` + `applyServing`); submit calls `PUT /food-log/{id}`
(add `updateFoodLog` to `ios-app/src/services/fitness.ts` — only `updateFoodLogMealType` exists,
:568). Keep the long-press delete. Note: `FoodLogModal` currently assumes a single item per entry;
entries with multiple `detailed_items` should list items with per-item edit (acceptable v1: edit
supports the common single-item case; multi-item entries open item list, tap an item to edit it,
save rewrites the whole entry via PUT).

### 4.4 Recipe ingredient editing
- **Web** (`RecipeEditor.tsx` + `IngredientSearchInput.tsx`): on loading an existing recipe, for
  each ingredient with a `food_id`, fetch details and restore `servings` +
  `selected_serving_id` (match by `serving_description`) so the serving dropdown reappears and
  `changeQuantity` rescales macros again. TODAY changing 100 g → 200 g keeps stale calories
  (explicit macros win server-side) — this is the recipes remove-and-re-add bug. For rows with
  explicit macros but no `food_id`, rescale proportionally on quantity change
  (`newMacros = old × newQty/oldQty`) instead of leaving them stale. Persist `serving_id` on
  `IngredientItem` (add optional field to the Pydantic model — additive, old JSON parses fine).
- **iOS** (`RecipeFormScreen.tsx:210`): make ingredient rows tappable → open `IngredientSearchModal`
  prefilled (add an optional `editIngredient` prop + rehydrate via details fetch like above);
  replace the row on save. Keep Remove.

**Verify Phase 4** (manual, via web UI + iOS reload):
1. Log a food on iOS → edit it on web → change nothing → Update → macros unchanged (regression test for the zeroing bug).
2. Edit quantity 1 → 2 servings → macros exactly double; serving dropdown present with the original serving selected.
3. iOS: tap a logged entry → edit quantity + serving → saved; list reflects new macros.
4. Recipe: reopen, change one ingredient 100 g → 200 g → its macros double in the running total and the saved recipe's per-serving macros move accordingly.
5. Check `journalctl`-free: `docker compose -f docker-compose.dev.yml logs backend` clean of 500s during all flows.

---

## Explicitly out of scope
- No schema migrations (all changes ride existing JSON columns; new fields optional).
- No changes to Sara's conversational logging behavior beyond aligning its `detailed_items` shape (4.1).
- No Expo/native module additions; no new iOS build required.
- Don't touch `food_search_log.py`'s nutrition-resolution math — recipes and manual logging reuse it as-is.

## Suggested commit slicing
1. `fix(recipes): use stored servings in PATCH recalc + remove per-serving double-divide` (Phase 1.1–1.2)
2. `fix(fitness-web): recipe quick-add calories + single-item recipe add` (1.3–1.4)
3. `feat(fitness-ios): show serving size in food search results` (Phase 2)
4. `feat(fitness): metric-derived g/oz entry alongside real servings` (Phase 3, web+iOS)
5. `feat(fitness): canonical detailed_items shape + safe web edit rehydration` (4.1–4.2)
6. `feat(fitness-ios): full food log edit flow` (4.3)
7. `feat(recipes): editable ingredients with serving re-pick + proportional rescale` (4.4)

# App Awareness + Recipe Live Lookup — Plan

Two features, planned 2026-07-12 on branch `assistant-experience-jarvis`:

- **Part 1 — App Activity Awareness.** Sara should know when David is using the app (web or iOS), which section he's in, and what he's doing there — and her sense of "contact" should include that, so she never perceives "radio silence" while he's actively logging meals and workouts.
- **Part 2 — Live Ingredient Lookup in Recipes.** Recipe creation should support live FatSecret ingredient search (like food logging does) so recipe macros are accurate, not guessed.

---

## Part 1 — App Activity Awareness

### Current state (verified in code)

| Piece | Status |
|---|---|
| Web heartbeat | **Working.** `App-interactive.tsx:205-244` POSTs `/api/presence/heartbeat` every 30s + on visibilitychange with the **real** `current_view` (from `useShellNavigation`) and `visible` flag. |
| iOS heartbeat | **Half-working.** `AuthenticatedOverlays.tsx:160-221` sends heartbeats every 30s + `app_open`/`app_resume` presence events, but `current_view` is **hardcoded to `'sara'`** (line 168) — never updated from navigation. |
| Backend heartbeat storage | `routes/presence.py:115` stores per-client state in Redis (`sara:client_state:{user}:{client}`, 60s TTL). |
| Consumption | **Almost none.** Only `device_presence.py` reads it, and only to answer `is_user_in_chat()`. Heartbeats never reach working memory, salience, or the deliberation prompt. |
| "Have I heard from David" | `hours_since_last_chat` — computed **exclusively** from chat episodes (`memory_subscribers.py:434`, reset by chat events at `:145`). App usage is invisible to it. This is the "radio silence" bug. |
| Domain events | **Dead wiring.** `FOOD_LOGGED` / `WORKOUT_LOGGED` / `WORKOUT_COMPLETED` have registered subscribers (`memory_subscribers.py:273-292`) and salience scoring (`salience.py:180-199`) but **zero publishers** — no route ever emits them. |
| Food visibility | Indirect only: the 5-min derived refresher reads `food_log` → `hours_since_last_meal` / `last_meal_type`. Says a meal was logged, not that David was present. |
| presence_log table | Exists, written by `/api/presence` (`app_open`/`app_resume` from iOS), read by nothing important. |

### Design

**Principle:** app presence is *contact*, not *conversation*. Sara should know the difference — "David has been in the app logging food all afternoon but hasn't said anything" is a different world-state than "nothing from David in 9 hours," and both differ from "we chatted an hour ago." All three should be distinguishable in her prompt.

#### 1A. Working-memory app-presence fields (backend core)

Add to `UnifiedContextSnapshot` (`unified_context.py`), under Activity/Presence:

```python
app_active: bool = False              # any client heartbeating with visible=true
app_platform: Optional[str] = None    # "web" | "ios" (most recent visible client)
app_current_view: Optional[str] = None  # canonical view name, e.g. "fitness"
app_view_since: Optional[str] = None  # ISO — when the current view was entered
last_app_activity_at: Optional[str] = None  # ISO — last visible heartbeat OR domain action
hours_since_app_activity: float = 999.0     # derived, refreshed like hours_since_last_chat
app_views_today: Optional[str] = None       # rollup: "fitness 41m, recipes 12m, chat 8m"
```

Writer: extend `presence_heartbeat` in `routes/presence.py`. On each heartbeat, after the Redis setex:
- If the payload is `visible: true`: fire-and-forget `update_memory(user_id, source="app_presence", app_active=True, app_platform=..., app_current_view=..., last_app_activity_at=now)`. Only write `app_view_since` when the view actually changed (compare against previous Redis state — we already have it in hand before overwriting).
- Debounce writes: skip the working-memory update if nothing changed since the last heartbeat (same view, same visibility) except a cheap `last_app_activity_at` refresh at most once per 2 minutes. Redis is cheap; version-bumping working memory 2×/min with no change is noise.

Session end (reaper): in `refresh_derived_signals` (`memory_subscribers.py`, already runs every 5 min), call `get_active_clients()`; if empty (all TTLs expired) and `app_active` is true → set `app_active=False`, clear `app_current_view`, and emit one `APP_SESSION_ENDED` event carrying session duration + views visited. Also recompute `hours_since_app_activity` here, same pattern as `hours_since_last_chat`.

`app_views_today` rollup: accumulate per-view dwell minutes in a Redis hash (`sara:app_views_today:{user}:{date}`) incremented by the heartbeat writer (30s per visible heartbeat); derived refresher renders it to the string field. Reset naturally by date-keyed key + TTL 48h.

#### 1B. New event types + salience

Add to `EventType` (`event_bus.py`):

```python
APP_SESSION_STARTED = "app.session_started"   # first visible heartbeat after app_active was false
APP_VIEW_CHANGED = "app.view_changed"          # view changed AND >=2 min dwell in the new view
APP_SESSION_ENDED = "app.session_ended"        # reaper detected all clients gone
```

Emit from the heartbeat writer / reaper. Salience (`salience.py`): low scores — session start ~0.3 novelty (0.5 if first of the day), view change ~0.1, session end ~0.2. These are ambient observations for the log, **not** deliberation triggers on their own; they enrich the observation window so when deliberation runs for other reasons, Sara can see "he opened the app at 2:10, spent 40 min in fitness."

The 2-minute dwell filter on `APP_VIEW_CHANGED` prevents tab-flipping spam. Raw flips still update working memory (current view is always live); only the *event* is debounced.

#### 1C. iOS: report the real screen

The concrete gap found in exploration: `AuthenticatedOverlays.tsx:168` hardcodes `currentScreen = 'sara'`.

- In `ios-app/src/services/navigation.ts`, add a `getCurrentViewName()` helper + a `navigationRef.addListener('state', ...)` (or `onStateChange` on the `NavigationContainer` in `RootNavigator.tsx:56`) that maps the active route to the **web canonical view vocabulary** (`frontend/src/navigation/views.ts`): `SaraScreen→chat`, `Fitness tab→fitness`, `RecipeForm/Recipes→recipes`, `WorkoutMode→fitness`, `NoteEditor/Notes→notes`, etc. Keep the map in one exported table (`ROUTE_TO_VIEW`) so new screens are one-line additions.
- `AuthenticatedOverlays.tsx`: replace the hardcoded value with the live one; also send an immediate heartbeat on view change (not just the 30s tick) so Sara's `app_current_view` tracks within seconds.
- Send `visible: AppState.currentState === 'active'` instead of hardcoded `true`, and send one final heartbeat with `visible: false` on background transition so the reaper doesn't wait a full TTL.

Web needs no changes for 1A-1C (already reports real view + visibility) beyond confirming the view names match `views.ts` (they do — heartbeat sends `view` directly).

#### 1D. Domain action publishers (what he's *doing*, not just where he is)

Wire the dead subscribers by emitting events from the routes:

| Route | Emit |
|---|---|
| `POST /api/fitness/food/log` + tool `food_search_and_log` | `FOOD_LOGGED` (payload: meal_type, food name, calories) |
| food log delete | `FOOD_DELETED` |
| workout session complete (`routes/fitness.py`) | `WORKOUT_COMPLETED` (exercises count, duration, PRs) |
| workout set/session logged | `WORKOUT_LOGGED` |
| cardio session save (`routes/cardio.py`) | `WORKOUT_COMPLETED` w/ `modality: cardio` |
| recipe created/updated (`routes/fitness.py:4701`) | `NOTE_CREATED`-style low-salience or new `RECIPE_SAVED` (optional; low value, defer) |

Every emit also bumps `last_app_activity_at` (via the existing subscribers calling `update_memory`) so even API-only actions (Siri shortcut, chat-tool logging) count as app activity. `_handle_food_logged` already exists and works once events flow.

Use `emit_event(...)` fire-and-forget (same pattern as `daily_rhythm`'s CONTEXT_UPDATED emit at `memory_subscribers.py:395`) — logging a meal must never fail because Redis pub/sub hiccuped.

#### 1E. Brain integration — make her *use* it

1. **Deliberation prompt** (`deliberation_prompt.py`, next to the "Hours since last chat" line at :77):
   ```
   Hours since last chat: 6.2
   App: active now — iOS, Fitness view (14 min)        # when app_active
   App: last used 0.4h ago (today: fitness 41m, recipes 12m)  # when not active
   ```
   Plus one guidance line in the rules section: app activity means David is present but not talking — do not treat it as radio silence, and do not narrate his app usage back at him.
2. **Check-in gating** (`checkin_builder.py:35,104,135`): the "long quiet stretch" logic should use `min(hours_since_last_chat, hours_since_app_activity)` for *silence detection*, while keeping `hours_since_last_chat` for *conversation staleness*. An ambient "how's it going" after 5 quiet hours is wrong if he's been in the app for the last 20 minutes; a check-in that says "saw you got your workout in" is right.
3. **Salience staleness** (`salience.py:265` `_score_staleness`): blend the same way — app activity resets "the world is stale" pressure.
4. **Consolidation** (`consolidation.py:422` renders `Hours since chat`): add app usage summary to the daily arc so evening reflection knows "quiet chat day but heavy app usage."
5. **Proactive check-ins** (`proactive_checkins.py` AMBIENT_GAP_HOURS): same min() blend as checkin_builder.

### Guardrails

- Never notify *because* he opened the app (no "I see you!" pings) — app events are observation-only; existing nutrition-notification ban (`deliberation_prompt.py:374`) stays.
- View tracking is section-level (`fitness`, `notes`), never content-level (no note titles, no food names in the presence fields — domain events carry those separately with their own salience).
- All timestamps written tz-aware UTC (see naive-datetime gotcha), rendered ET in prompts.

### Phases

- **A1 — Backend core**: snapshot fields, heartbeat writer + debounce, reaper + `hours_since_app_activity` in derived refresh, `app_views_today` rollup, new EventTypes + salience entries. *(backend only, immediately visible for web users since web already sends good heartbeats)*
- **A2 — iOS real screen**: `ROUTE_TO_VIEW` map + navigation state listener, live `currentScreen`, visibility on background, immediate heartbeat on view change. *(JS-only change — reload, no EAS rebuild)*
- **A3 — Domain publishers**: emit FOOD_LOGGED / WORKOUT_LOGGED / WORKOUT_COMPLETED / FOOD_DELETED from routes + chat tools.
- **A4 — Brain integration**: deliberation prompt lines + guidance, checkin_builder + proactive_checkins min() blend, staleness blend, consolidation line.

Each phase is independently shippable in that order. A1+A4 alone fixes "radio silence" for web; A2 extends it to iOS; A3 gives her the verbs.

### Verification

- Heartbeat → `redis-cli get "sara:client_state:..."` shows real views from both platforms; navigate web tabs and confirm `app_current_view` updates in `/debug/notification-funnel` or a snapshot dump.
- Kill the app, wait ~6 min, confirm reaper flips `app_active=false` and one `APP_SESSION_ENDED` lands in the observation log.
- Log a meal from iOS → `FOOD_LOGGED` observation appears; `hours_since_last_meal` goes to ~0 within the event (not the 5-min refresh).
- Trigger a deliberation (`/debug` route) while using the app and confirm the prompt contains the App lines and no check-in fires.
- Remember: backend + celery only pick up code on container restart.

---

## Part 2 — Live Ingredient Lookup in Recipe Creation

### Current state (verified in code)

- **Two disconnected nutrition estimators exist:**
  1. `routes/fitness.py:4516` — `estimate_recipe_nutrition()`: a **hardcoded ~40-food lookup table** ("chicken breast: 165 cal/100g"...). This is what `POST/PUT /api/fitness/recipes` (:4715, :4877) actually uses — i.e., **every recipe saved from the web or iOS UI gets rough-guess macros**.
  2. `services/recipe_nutrition.py` — the good one (SARA_UNLEASHED U.6): resolves each ingredient against **FatSecret** reusing `FoodSearchAndLogTool`'s quantity/unit scaling. Only used by the chat tool (`tools/recipes.py`).
- **iOS already has the UI**: `IngredientSearchModal.tsx` — debounced `/api/fitness/foods/search`, barcode lookup, manual fallback — wired into `RecipeFormScreen.tsx`. Ingredients can carry per-ingredient macros.
- **Web is the gap**: `RecipeEditor.tsx` uses free-text ingredient rows (name/qty/unit inputs), no search, "leave blank to auto-calculate" → the hardcoded table.
- **Schema is ready but lacks provenance**: `IngredientItem` (`schemas/recipes.py`) has optional per-ingredient `calories/protein/carbs/fats`, but no `food_id`, so a picked ingredient can't be re-resolved or audited later.
- `Recipe.macros_estimated` flag already distinguishes computed vs hand-entered macros; hand-entered values are never overwritten.

### Design

#### R1 — One estimator, the accurate one (backend)

- Make `POST /api/fitness/recipes` and `PUT .../recipes/{id}` use `services/recipe_nutrition.estimate_recipe_nutrition()` (async FatSecret) instead of the local table; delete the table version at `routes/fitness.py:4516`.
- Precedence per ingredient: **explicit per-ingredient macros (from live lookup or manual entry) win**; only unresolved ingredients hit FatSecret. Add this short-circuit to `services/recipe_nutrition.py` (currently it always looks up). Recipe-level explicit macros still win over everything (`macros_estimated=False` path unchanged).
- Add to `IngredientItem`: `food_id: Optional[str]`, `source: Optional[str]` (`"fatsecret" | "user" | "manual"`), `serving_description: Optional[str]` (e.g. "1 cup, cooked"). Stored in the existing JSON column — no migration needed. Backend stays tolerant of old rows without these keys.

#### R2 — Web RecipeEditor: live search per ingredient row

Port the `FoodItemSelector.tsx` pattern (debounced `apiClient.searchFoods` ≥2 chars, dropdown, `getFoodDetails` on select) into `RecipeEditor.tsx`:

- Each ingredient row's name input becomes a typeahead. Selecting a result fetches `/foods/{id}/details`, lets the user pick serving + quantity (reuse the serving-selection UI from `FoodItemSelector`), and fills the row's macro fields + `food_id`. The row shows a small "✓ FatSecret" vs "~ estimated" vs "manual" badge (`source`).
- Free-text still allowed (paste-a-recipe flow) — untouched rows resolve server-side on save exactly as today, just via the accurate estimator now.
- **Live totals**: a footer in the editor showing running total and per-serving macros, recomputed client-side from resolved rows (+ "N unresolved ingredients will be estimated on save" note).
- Factor the typeahead into a shared `IngredientSearchInput.tsx` under `components/fitness/` rather than inflating `RecipeEditor` — `FoodItemSelector` is modal-flavored and not directly reusable inline.

#### R3 — iOS polish (parity, small)

- `IngredientSearchModal`: after picking a food, show scaled macros for the chosen quantity/unit before adding (it already fetches details; surface the numbers), and pass `food_id`/`source` through in the emitted `IngredientItem` (`ios-app/src/services/recipes.ts` types).
- `RecipeFormScreen`: live per-serving macro total footer, same semantics as web.
- JS-only — reload, no EAS rebuild.

#### R4 (optional, later) — Bulk resolve endpoint

`POST /api/fitness/recipes/resolve-ingredients`: accepts free-text lines ("2 cups flour"), returns parsed qty/unit + best FatSecret match + scaled macros per line, reusing `FoodSearchAndLogTool._parse_food_items/_search_food/_resolve_nutrition`. Powers a future "paste whole recipe" import and lets the web editor resolve-all-before-save instead of silently on save. Defer until R1-R3 prove out.

### Verification

- Create a recipe on web with live-picked ingredients → per-ingredient macros populate, totals match FatSecret details, saved row has `macros_estimated=false`… actually `true` only when *any* macro came from estimation — confirm flag semantics against U.6 rules.
- Create a recipe with free-text-only ingredients → macros now come from FatSecret (compare against the old table's numbers for e.g. "200g chicken breast, 1 cup rice" — should differ and be defensible).
- iOS: add ingredient via search → macros shown pre-add; total footer matches web for the same recipe.
- Regression: chat-tool recipe creation (`tools/recipes.py`) unchanged; existing recipes with old-format ingredient JSON still list/render (`routes/fitness.py:4688` already guards malformed rows).

---

## Decisions taken (defaults, flag if wrong)

1. **App presence is observation, not trigger** — Sara sees it at the next deliberation; app opens never wake her by themselves.
2. **Section-level tracking only** — views, dwell times, and domain events (meal logged, workout done); no per-keystroke/content surveillance fields.
3. **`min(chat, app)` only for silence/staleness gates** — conversation-recency semantics (`hours_since_last_chat`) stay pure so she still knows you haven't *talked*.
4. **No new tables** — Redis for live state + rollup, existing `presence_log` untouched, ingredient provenance rides the existing JSON column.

## Suggested order

A1 → A2 → R1 → R2 → A3 → A4 → R3 (→ R4). A1/A2 and R1/R2 are independent tracks and can interleave; A4 last among the A-phases because it's prompt-behavior tuning that benefits from real presence data having accumulated for a few days.

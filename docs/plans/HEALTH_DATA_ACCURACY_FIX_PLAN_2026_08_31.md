# Health Data Accuracy Fix Plan — 2026-08-31

## The incident

On 2026-08-31 David asked Sara why he felt exhausted. She stated his HRV was 54 and he'd
slept 7.5 hours. Challenged, she said *"Here's what the actual data shows"* and produced a
seven-day table of HRV values. Every HRV number in it was wrong:

| date | Sara claimed | `health_metric` truth |
|---|---|---|
| 08-31 | HRV 87 | **54** |
| 08-29 | HRV 26 | *no row* |
| 08-28 | HRV 111 | *no row* |
| 08-27 | HRV 40 | **99** |
| 08-26 | HRV 74 | *no row* |
| 08-25 | HRV 47 | *no row* |
| 08-24 | HRV 80 | **56** |

Her **sleep** numbers in the same table were 6/7 correct. The split is the whole diagnosis:
the sleep path returned real data, the HRV path returned nothing, and rather than report an
absence she completed the pattern.

## Root cause: a self-reinforcing fabrication loop

`pkg_extractor.py:37` instructs an LLM to mint `Health` facts (`metric` / `current_value` /
`trend`). It runs nightly over conversation text selected with `role IN ('user','assistant')`
(`tasks/autonomy.py:704`, also `nightly_dream_service.py:711-732`, `consolidation.py:1088`).

**Anything Sara says about David's health becomes a durable fact and is re-injected next turn.**

Live `PKG_Health` in Neo4j at time of writing:

```
"hrv"             "80"                                    conf 0.99  last_confirmed 2026-08-31
"sleep_duration"  "7.5 hours"                             conf 0.40  last_confirmed 2026-08-25
"Sleep duration"  "Trending down (slept in a bit today)"  conf 0.99  last_confirmed 2026-08-29
"Sleep Quality"   "Poor (barely slept)"                   conf 0.99  last_confirmed 2026-08-31
```

`hrv = "80"` was written **today at 0.99 confidence** — and 80 is one of the numbers Sara
fabricated in that conversation. `sleep_duration = "7.5 hours"` is Aug 24's real value, frozen
and six days stale. Meanwhile the authoritative table said HRV 54 / sleep 8.3h.

Nothing reconciles `PKG_Health` against `health_metric`. `upsert_fact`
(`personal_knowledge_graph.py:262-286`) only checks the fields are non-empty.

## Why the existing guard didn't fire

`get_system_prompt` (`main_simple.py:7383`) already contains, at ~`:7419`:

> *NEVER assert that David did something — worked out, went somewhere, ate, slept a certain
> amount — unless you have actual evidence from THIS turn.*

It failed because `live_context` **hands the model a number that looks exactly like evidence**.
Compounding it, the `FORBIDDEN PHRASES` list in `## Internal Knowledge Protocol` (~`:7589`)
bans "My records show…" / "According to my notes…", which pushes the model to state numbers
bare and unattributed — making a stale PKG guess indistinguishable from a fresh metric.

## Supporting defects (all verified)

| # | Defect | Location |
|---|---|---|
| D1 | `confidence=1.0` set if *any* health row exists, regardless of which metrics are missing | `context_snapshot.py:125-138` |
| D2 | Missing metrics omitted from `by_metric`, so a gap is invisible rather than "unknown" | `context_snapshot.py:642` |
| D3 | Numeric health facts never expire — `is_transient_health_text` matches only sick/tired/sore/pain, so `expires_at` is NULL | `personal_knowledge_graph.py:61-65` |
| D4 | Staleness suffix only fires past 21 days; a 6-day-old number renders clean | `pkg_context_provider.py:19,44-55` |
| D5 | `_today_bounds_naive` returns naive **ET** midnight against a **timestamptz** column on a UTC session → "today" starts 8 PM ET *yesterday* | `context_snapshot.py:44-47` |
| D6 | `health_status` throws away `recorded_at`; metrics from different days render as one "Current Health Status" block with no dates | `health.py:109-139` |
| D7 | Truthiness checks (`if data.get('current_value'):`) silently drop real zeros | `health_insight_service.py:68-81`, `health.py:285` |
| D8 | `workout_list` silently returns **plan templates as real workouts** when none exist | `workout_log.py:96-135` |
| D9 | `recovery_score = 100  # Default to good` when there's no data; undisclosed on rest-day and TTS branches | `morning_brief_service.py:2260,2372-2388` |
| D10 | `workout_stats` returns `or 0` on every field — "avg RPE 0" is indistinguishable from real 0 | `workout_log.py:621-624` |
| D11 | `fitness_summary` recovery-notes query has **no date filter** — can surface months-old notes | `summary.py:226-233` |
| D12 | `health_trend` omits gap days entirely (SQL `GROUP BY DATE`) | `health_insight_service.py:245` |
| D13 | Two unrelated confidence scales (`confidence=` numeric, `(inferred)/(confirmed)` tier) rendered side by side from different stores | `context_snapshot.py:638-644` vs `:681` |
| D14 | "Today" is defined four different ways across tools (`NOW()` UTC, `naive_local_now()`, `naive_utc_now()`, `CURRENT_DATE`) | various |

## Upstream data gap

HRV is present on only **5 of 14 days**. Critically, on **08-26, 08-25, 08-22 and 08-18 sleep
was recorded but HRV was not** — the watch was worn overnight and HRV still didn't land. That
is an ingestion bug, not a wear gap. Consistent with the existing
`gotcha_apple_health_watch_streams_dark` note.

---

# The plan

Guiding principle: **`health_metric` is the only authority for numbers. Everything else may
contextualise, never assert.** Absence must be visible; every number must carry a date.

## Phase 0 — Stop the bleeding (do first, low risk, no schema change)

- **0.1** Exclude `assistant` turns from health-fact extraction — change `role IN ('user','assistant')`
  to `role = 'user'` at `autonomy.py:704`; audit the same pattern in `nightly_dream_service.py:711-732`
  and `consolidation.py:1088`.
- **0.2** Refuse to mint **numeric** `Health` facts at all. Add a validator in
  `personal_knowledge_graph.upsert_fact` (`:262-286`) rejecting `Health` facts whose
  `current_value` parses as a bare number or matches `\d+(\.\d+)?\s*(hours?|hrs?|bpm|ms)?`.
  Update the extraction prompt at `pkg_extractor.py:37` to say numeric health values come from
  `health_metric` and must not be extracted.
- **0.3** Purge the poisoned nodes now in Neo4j: `hrv`, `sleep_duration`, `Sleep duration`,
  `Sleep Quality`. Write the deletion as a small idempotent script under `backend/scripts/`
  so it can be re-run and reviewed.

**Verify:** re-run the extractor over the 08-31 conversation; assert no `Health` fact with a
numeric `current_value` is created.

## Phase 1 — Make absence explicit

- **1.1** `context_snapshot.py:125-138` — enumerate an expected metric set and emit
  `hrv_morning=unavailable` (not omission) when a metric has no row for the window.
- **1.2** Replace the blanket `1.0 if row else 0.4` with **per-metric** confidence.
- **1.3** Stop dropping real zeros: replace truthiness with `is not None` at
  `health_insight_service.py:68-81`, `health.py:285`.
- **1.4** `health_trend` — emit `{"date": …, "value": None}` for gap days, mirroring
  `patterns.py:378-382`, which already does this correctly and should be the template.
- **1.5** `recovery_log_recent` — include absent days explicitly rather than a short list.

**Verify:** ask for a 7-day HRV history; response must contain four explicit "no data" days.

## Phase 2 — Reconcile and attribute

- **2.1** In `render_engaged_context` (`context_snapshot.py:612-690`), suppress or annotate any
  `PKG_Health` line whose metric has a raw `health_metric` row for today. Raw wins, always.
- **2.2** Stamp every health number with its `recorded_at` — carry the field through
  `health.py:109-139` and `health_insight_service.py:150`.
- **2.3** Add a Health-specific staleness rule: annotate any `Health` fact older than **48h**
  with an as-of date, rather than the generic 21-day threshold (`pkg_context_provider.py:19`).
- **2.4** Give numeric `Health` facts a TTL alongside `is_transient_health_text`
  (`personal_knowledge_graph.py:61-65`) so they expire even if Phase 0.2 is later relaxed.

**Verify:** replay the 08-31 context build; the `7.5 hours` line must either disappear or read
`as of 2026-08-25`.

## Phase 3 — Prompt and output discipline

- **3.1** Extend the guard at `main_simple.py:7419`: numeric health values may only be stated
  when they appear in **this turn's** `health_today` slice or a this-turn tool result.
- **3.2** Carve health out of `FORBIDDEN PHRASES` (~`:7589`) so Sara *can* attribute —
  "HRV 54, as of 6am today" — instead of being pushed into bare unattributed numbers.
- **3.3** Add an explicit instruction: when a metric is `unavailable`, say so; never interpolate.

**Verify:** the A/B harness below, run against the live model.

## Phase 4 — Silent fallbacks

- **4.1** `workout_list` (`workout_log.py:96-135`) — never return templates as workouts; if the
  fallback is wanted, label rows `source: "template"` and change the message.
- **4.2** `morning_brief_service.py:2260` — stop defaulting `recovery_score = 100`; propagate
  "unknown" and disclose it on the rest-day (`:2372-2380`) and TTS (`:2388`) branches too.
- **4.3** `workout_stats` (`:621-624`) — distinguish "no data" from a real 0.
- **4.4** `fitness_summary` (`summary.py:226-233`) — add a date filter to recovery notes.

## Phase 5 — Time correctness

- **5.1** Fix `_today_bounds_naive` (`context_snapshot.py:44-47`) to build an aware ET boundary
  so the "today" window doesn't start 8 PM ET yesterday.
- **5.2** Unify the four "today" definitions behind one helper in `app.core.timezone`
  (see `feedback_no_utc`).

## Phase 6 — Upstream ingestion (separate track)

- **6.1** Determine why HRV doesn't land on nights sleep does (08-26, 08-25, 08-22, 08-18).
  Compare the iOS HealthKit query for HRV against the sleep query; likely the same class as
  `gotcha_healthkit_v13_workout_stats` (wrong accessor) or the dark raw streams.
- **6.2** Backfill HRV once fixed.

---

# Verification harness

Build `backend/scripts/health_accuracy_check.py` asserting, against the live stack:

1. **No invention** — ask for a 14-day HRV history; every number returned must match a
   `health_metric` row, and every gap day must be explicitly reported as missing.
2. **No stale assertion** — build the chat context and assert no health number appears without
   either a today `recorded_at` or an as-of date.
3. **No loop** — run the extractor over a transcript in which Sara states a wrong number;
   assert no `Health` fact is created from it.
4. **Regression** — replay the 08-31 exchange verbatim and diff against the recorded failure.

Run 1-3 before and after each phase.

# Ordering and risk

| Phase | Risk | Blast radius |
|---|---|---|
| 0 | Low | Extraction only; no read path changes |
| 1 | Low-med | Changes context text the model sees — re-check prompt size |
| 2 | Medium | Suppression logic could hide wanted context; keep annotate-only as fallback |
| 3 | Medium | Prompt changes affect all chat; A/B before keeping |
| 4-5 | Low | Isolated tools + a tz helper |
| 6 | Separate | iOS/HealthKit, needs a device build |

Phases 0-2 are the ones that actually stop fabrication. Phase 3 is reinforcement, not the fix —
the prompt guard already existed and lost to context that looked like evidence.

# Out of scope

- The Flash-Next migration (`project_mtplx_flash_next`). The confabulation is data-driven; the
  clean morning turns on the 27B are too small a sample to blame the model, and no model change
  is needed for any fix here.
- The uncapped `/chat/stream` context budget and the 507 ceiling — tracked separately.

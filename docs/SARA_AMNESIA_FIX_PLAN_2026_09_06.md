# Sara amnesia fix plan — 2026-09-06

**Symptom.** Over the Sep 3–7 Salem/Marblehead trip, every new conversation opened as if David were at home: "you're back after 15 hours away", "working from home today, home-gym day, Jim's emails need replies" (Fri), "if you're heading to Salem this weekend" (Fri evening, day 2), "is Count Orlok's today or did you already hit it?" (Sun; done Fri). David corrected her three mornings running. He described it as "an Alzheimer's assistant".

**Diagnosis in one line.** The knowledge existed on disk the whole time (`data/briefs/<uid>/layers/context.md`: "David is currently **in Salem** (until Monday, Sept 7)"); the chat prompt assembly throws it away, reports GPS it has as "unknown", and then recites the home routine.

Verified 2026-09-06 against the DB, the brief files and the code. Nothing below is implemented yet. Audit notes: memory `gotcha_chat_amnesia_brief_clip_2026_09_06`. The MTPLX/model side was handled the same day (memory `project_mtplx_flash_next`, "2026-09-06" section) and is out of scope here.

---

## Phase 0 — capture a failing fixture before touching anything (15 min)

The Friday 07:25 turn is the perfect regression case: the prompt Sara received is in `conversation_turn` (conversation `b8f9736f…`, `message_index=0`) and the brief layers for that day are archived under `data/briefs/<uid>/archive/`.

1. Dump that user turn to `backend/tests/fixtures/amnesia_2026_09_04_turn0.txt`.
2. Write `backend/tests/test_context_amnesia.py` with the assertions each phase below turns green:
   - `"in Salem"` appears in the rendered `## Today's Brief` block.
   - the device block does not contain `location: unknown` when `location_latitude/longitude` are set.
   - `## Re-Entry Context` does not contain the word `returned`.
   - `## HEALTH DELTAS` has ≤ 3 lines and no two lines with identical text.
   - `_llm_extract_entities` request body contains `chat_template_kwargs.enable_thinking == False`.

Run with `docker compose -f docker-compose.dev.yml exec backend pytest tests/test_context_amnesia.py`.

---

## Phase 1 — stop clipping the layers that know where he is (the big one, ~1 h)

**Where.** `backend/app/services/context_snapshot.py:981`:
```python
lines.append(f"\n## Today's Brief\n{_clip_to_paragraph(extended['daily_brief'], 1500)}")
```
`extended['daily_brief']` is `daily_brief_service.get_compiled_brief()` → `daily_brief/compiler.py` `_assemble()`, which concatenates `LAYER_NAMES = ["stable", "context", "day", "moment"]` in that order behind `BRIEF_HEADER`. Header + `stable.md` (~3.7 KB) already exceed 1500 chars, so `context.md` / `day.md` / `moment.md` are cut on **every** turn. The Friday prompt's brief ends at "He has a kitten named Vesper." — that is the stable layer's §2; nothing after it survived.

**Fix (do all three).**
1. **Inject the volatile layers separately and first.** In `_daily_brief()` (`context_snapshot.py:657`) return the layers individually (`daily_brief_service` already has `_read_layer`; add `get_layers(user_id) -> dict`). In the render:
   ```
   ## Right now / today / this week   ← moment.md, day.md, context.md (in that order), budget 1800 chars
   ## Who David is (stable)           ← stable.md, budget 900 chars, paragraph-clipped
   ```
   Put the volatile block **before** the stable one. Keep `_clip_to_paragraph` for both.
2. **Give the compiled brief the same order** (`compiler.py:33` → `["moment", "day", "context", "stable"]`), so any other consumer that still reads the compiled string (`brief_service.py`, notifications) gets today first. The 35/30/25/10 allocation in `_assemble` stays but keyed by the new order.
3. **Budget accounting.** `SectionBudget` (`context_budget.py`) already caps the whole block; register the two new sections with explicit shares so the stable layer cannot crowd out the day layer again. Add a unit test on `_assemble` that a 6 KB stable layer never pushes `context` out of the first 1500 chars.

**Acceptance.** Fixture test asserts "in Salem" is in the rendered prompt. Manually: `POST /chat` "good morning" with the current layers → reply references the trip without being told.

---

## Phase 2 — use the GPS Sara already has (~2 h)

**Evidence.** 3,233 `location_event` rows this trip at 42.4797, -70.8797 (Marblehead), every one `place_id = NULL`. `known_place` row "2 Preston Beach Road, Marblehead" was auto-learned Sat 07:30 with **`status='suggested', is_active=false`**, and `location_service.classify()` (`location_service.py:88`) only matches `is_active = TRUE`. So `unified_context.current_place = "unknown"`, and `device_presence.py:56-58` renders `location: unknown`. There is also **no `place_type='home'` row at all** (all ten rows are `other`), so `location_context` can never be `home`, and "away from home" is underivable.

**Fix.**
1. **Home anchor.** Add a `home` known place (seed from the HA zone / the address in `life_facts`, or a one-off migration with David's coordinates; `radius_m` 200). Write a `scripts/seed_home_place.py`. Everything else in this phase depends on it.
2. **Distance-from-home signal.** In `location_service._update_context()` (`:420-446`) also write `distance_from_home_km` (haversine to the home row) and `away_since` (first sample > 5 km, cleared when back inside home radius). Add both fields to `UnifiedContextSnapshot` (`unified_context.py:57`).
3. **Classify against suggested places too.** In `classify()` drop the `is_active` filter to `status IN ('active','suggested')` and return `confirmed: bool`. `_update_context` then writes `current_place = "near 2 Preston Beach Road, Marblehead (unconfirmed)"` for suggested rows; `device_presence` treats any non-unknown place as `away` (it already does). Auto-promote a suggested place to active after `visit_count >= 10` across ≥ 2 distinct days (the Marblehead row hit 23 visits) — the review UI in `routes/location.py:140-192` stays for the rest.
4. **Render it.** In `context_snapshot.render_engaged_context` add one line under `## Right now`:
   `Location: 210 km from home since Thu Sep 3 20:31 (near 2 Preston Beach Road, Marblehead, unconfirmed).`
   Also in the device block (`device_presence.py:206-212`) replace `location: unknown` with that same string.
5. **Pass it to deliberation** (`deliberation_prompt.py:150-153` already prints `current_place`; add `distance_from_home_km` / `away_since`), so the 06:23 "WFH day" invention in Phase 4 has the fact it lacked.

**Acceptance.** Replay the Friday fixture with the snapshot fields populated → device block says away/Marblehead. `select count(*) from location_event where place_id is null and created_at > now() - interval '1 day'` drops to ~0 once the row is promoted.

---

## Phase 3 — re-entry wording (~10 min)

`backend/app/main_simple.py:8586`:
```python
reentry_context = f"\n\n## Re-Entry Context\nDavid just returned after {hours_away:.1f} hours away.\n"
```
`hours_away` is chat absence (last `episode.created_at`), but the model reads "returned … away" as *physically came home* ("you're back after a solid 15 hours away"). Change to:
```
## Since you last talked (14.9 h ago)
```
and keep the rest of the block. If Phase 2's `away_since` is set, prepend `David is away from home (Marblehead) — do not assume the home routine.`

---

## Phase 4 — stop reciting the home routine while he's away (~2 h)

Every morning the prompt carries, unconditionally: `theory_of_david` ("anchored by early work departures"), `life_facts` standing line "David normally: leaves for work 7am…" (`life_facts.py:130-151`, rendered via `directives.py:76`), `## BODY & TRAINING` "Day 5 — Friday (Home Gym) · scheduled" (`world_brief.py:601`), the nutrition targets, `## COMMS NEEDING ACTION`, and the deliberation's own thought ("You're working from home today", `sara_journal_service.py:502` → "Sara's Recent Thoughts"). The Fri 06:23 deliberation (`agent_run_log` 10:24Z) invented "David is a WFH day" from the No-School calendar event with no location fact to contradict it, and chat repeated it verbatim.

**Fix — one gate, applied at the render sites, not in the LLM prompts.**
1. Define `away_mode(snapshot) -> bool` in `unified_context.py`: `distance_from_home_km > 30` for ≥ 6 h, **or** an all-day calendar event spanning today whose title matches a place (the existing "verified upcoming" block already lists `Thu Sep 3 – Mon Sep 7: Salem`).
2. When `away_mode`:
   - `directives.py` skips the "David normally:" rhythm line.
   - `world_brief._body_training_live_async` renders "Away from home — no scheduled session; log only if David reports one." instead of the plan day.
   - `context_snapshot` prefixes `## Right now` with `David is away (Salem trip, back Mon Sep 7).`
   - `deliberation_prompt.py` adds the same line, and the judge (`judge.py:424` hard-codes "David leaves for work at 07:00") reads the gate instead of the literal.
3. **Recent-thoughts hygiene.** `sara_journal_service.py:502` injects deliberation thoughts into chat. Only inject thoughts whose `david_state_snapshot` agrees with the *current* `away_mode`; otherwise a wrong morning guess becomes chat "memory".

**Acceptance.** Fixture test with `away_mode=True` shows none of: "leaves for work", "Home Gym", "working from home".

---

## Phase 5 — world_brief hygiene (~45 min)

1. **Expire `health_deltas`.** `world_brief.expire_stale_items()` (`:312-343`) covers `ahead/happened/open_loops/comms_needing_action` only; the brief row currently holds **15** near-identical "Weight 240 / RHR / sleep" items dated Aug 31–Sep 2. Add `("health_deltas", timedelta(hours=36))` to the loop and dedupe by normalized text on insert in `appraisal.py:172-186` (it already compares text for the *same key*; also compare across keys).
2. **Outlier guard.** Sunday's "HRV 153 — recovery looks solid" came from `health_metric` (`hrv_morning`, `sample_count: 2`; prior days 48–75). In the health slice builder (`context_snapshot.get_world_state` → `health_today`) drop or flag HRV outside `[0.4×, 2×]` of the 14-day median and mark it `(single-sample, unverified)`. Same guard in `recovery_score.py`.
3. **Stale open loops.** `[thread:…] 1 PM gym session`, `working on the app (aging 3 days ago)`, `deciding on dinner recipe` were still in `## OPEN LOOPS` on the trip; `thread:*` items are exempt from `expire_stale_items` by design. Have `thread_manager` close threads untouched for 72 h when `away_mode` is on.

---

## Phase 6 — background learning that never lands (~20 min)

`backend/app/services/outbox_processor.py:461-490` `_llm_extract_entities`: no `chat_template_kwargs: {"enable_thinking": False}`, `max_tokens: 500`. On Flash-Next (thinking on by default, `--reasoning-effort xhigh`) every call is 500 tokens of "We need answer user's request…" and the JSON never arrives — visible in the MTPLX log as truncated `text_preview`s, ~4 per day. Add the kwargs, drop `max_tokens` to 400, and log the parse failure class (per `feedback_tool_exception_logging`). Grep for the same omission:
```
grep -rn '"max_tokens"' app/services | grep -v enable_thinking
```
and fix every bg call site that posts to `bg_llm_primary_url` without the flag.

---

## Phase 7 — cross-conversation continuity (~2 h, optional but this is what "human memory" means)

`## Relevant memory (memory.recall)` for the message "Good morning!" returned two prior "good morning" episodes — vector recall on a greeting is noise. The relationship block prints `active_conversation=<uuid>` and nothing else about the previous conversation.

1. **Last-conversation digest.** `_close_previous_session()` (`main_simple.py:8540-8560`) already summarizes the closed session into `day.md` and the journal. Also write it to Redis `chat:last_conversation_digest:<uid>` (≤ 600 chars, with the conversation's date/time) and render it under `## Last conversation (Sat 07:07)` on the **first** turn of each new conversation. This alone would have carried "in Salem, walking tour + magic show" into Sunday.
2. **Recall query.** For messages under ~5 words, skip vector recall (or query with the last-conversation digest instead of the greeting).

---

## Order, rollout, verification

| step | phase | why this order |
|---|---|---|
| 1 | 0 | fixture before any change |
| 2 | 1 | biggest effect, smallest change |
| 3 | 3, 6 | one-liners, ship with 1 |
| 4 | 2 | needs the home row seeded first |
| 5 | 4 | depends on 2's `away_since` |
| 6 | 5 | independent, do any time |
| 7 | 7 | nice-to-have |

Ship as two commits on `feat/sara-mind-v2`: (1, 3, 6) tonight, (2, 4, 5, 7) after. Each needs `docker compose -f docker-compose.dev.yml build backend && up -d backend` (and celery-worker for 5/6). Remember the deployed-code-lags rule: verify with the fixture test **inside** the container, then one real "good morning" and check the rendered prompt in `conversation_turn` for the new sections.

**Do not** change the model, sampling, or the grounding preamble for this — those were tuned on 2026-09-01 and the model is not the cause here.

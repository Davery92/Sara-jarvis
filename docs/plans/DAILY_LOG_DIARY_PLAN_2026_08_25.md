# Daily Log / Diary Plan — 2026-08-25

> **Status (implemented 2026-08-25):** Phases 1-5 and Addendum Phases A-D are
> done and verified live. Phase 6 (knowledge-garden mirror) remains deferred by
> design. Two pre-existing bugs were found and fixed along the way:
> `cache_replay()` could not serialize `Decimal` (so every day that had recovery
> metrics was silently never cached), and the replay's nutrition summary
> rendered unrounded float totals. Two weeks of entries were backfilled through
> the regenerate path.

## Goal

A per-day diary entry, written by the LLM in Sara's voice, generated every night for the
previous day. **All data is pulled deterministically and handed to the model in one
prompt — no agent loop, no tool calls.** The model's only job is prose. The structured
facts are stored alongside the prose so the UI can show "receipts" under the diary text.

Covers: chat summary (if there was chat that day), fitness/nutrition, and anything else
that surfaced in the app during the day (research tasks, reminders, calendar, learning,
notifications, Sara's own journal, etc.).

## What already exists (verified 2026-08-25)

| Piece | Where | State |
|---|---|---|
| Collector layer | `backend/app/services/day_replay_builder.py` (928 lines) | 12 pure-SQL collectors: episodes, automations, `workout_session`, `food_log`, `daily_recovery_log`, `calendar_event`, email counts, `background_task` (research), `learning_session`, timers, reminders, `home_activity_log` |
| Nightly schedule | `app.tasks.inproc_schedulers.nightly_dream_cycle` (Celery beat, `cognitive` queue, 2 AM) → `nightly_dream_service._run_nightly_dream_cycle()` | Already builds yesterday's replay using the **ET date** (`eastern_yesterday`) and caches it |
| Storage | `day_replay_cache` table (`user_id, replay_date` unique; created in `migrations/add_behavioral_patterns.py`) | Upsert already implemented in `cache_replay()`. The `summary` text column is **empty** — `cache_replay(db, replay, summary_text=None)` is never passed a summary. That column is where the diary goes. |
| Chat session summaries | `daily_brief/day_layer.py` — `brief_service.py:249` appends an LLM summary per session close; archived nightly by `daily_brief/archiver.py` | Real prose summaries already exist; no need to re-summarize raw episodes |
| Voice + LLM call pattern | `sara_journal_service._generate_entry()` | Local Qwen via `llm_client.chat_completion`, `enable_thinking: False` |
| Consumers today | Only `pattern_detector.py` (reads cached weather) | Nothing user-facing reads the replay — the feature is headless |

**Net:** no new tables, no new schedules. The build is one new service, a few added
collectors, one integration point in the dream cycle, one route file, one frontend view.

## Architecture

```
2 AM dream cycle (existing)
  └─ build_replay(date=yesterday ET)          ← existing, deterministic SQL
  └─ [NEW] daily_log_service.build_payload()  ← replay + supplemental collectors
  └─ [NEW] render_facts(payload)              ← deterministic plain-text fact sheet
  └─ [NEW] write_diary(facts)                 ← ONE bounded LLM call, local Qwen
  └─ cache_replay(db, replay, summary_text=diary)  ← existing upsert, unused param
```

Failure isolation: if the diary LLM call fails, the structured replay still caches;
`summary` stays NULL and can be filled by the regenerate endpoint later.

---

## Phase 1 — Fix day boundaries in `day_replay_builder` (prerequisite)

`build_replay()` computes naive `datetime.combine(replay_date, min/max.time())` and
compares against `created_at` across tables that are a mix of timestamptz and naive-UTC.
Pattern detection never noticed; a user-facing diary will (an 11 PM chat lands on the
wrong day, or the day bleeds 4–5h).

- [x] Compute ET day bounds via `app.core.timezone` helpers, convert to each table's
      storage convention (timestamptz → aware UTC bounds; naive-UTC columns like
      `background_task` → naive UTC bounds).
- [x] Audit each of the 12 collectors' timestamp columns individually — do not assume
      one convention. (Known: `background_task` timestamps are naive UTC per
      durable-dispatch notes.)
- [x] Sanity check: generate a replay for a day with a known late-evening chat and
      confirm it lands on the right date.

## Phase 2 — `daily_log_service.py` (new, ~200 lines)

`backend/app/services/daily_log_service.py`, three functions, no classes needed beyond
a thin service object for parity with neighbors:

### 2a. `build_payload(db, user_id, log_date) -> dict`
- Call `day_replay_builder.build_replay()` for the backbone.
- Supplement with sources the builder predates or skips:
  - [x] `cardio_log` (new cardio/Tabata tracker — not in the builder)
  - [x] Sara's `sara_journal` entries for the day (`entry_type`, `content`)
  - [x] Notifications actually delivered that day (`notification_log`)
  - [x] Notes created/edited that day (title + folder only)
  - [x] Chat summaries: read yesterday's **archived** day layer via
        `daily_brief/archiver.py` — the live day-layer file is archived+cleared at 11 PM,
        before the 2 AM run, so `day_layer.read()` would be empty/wrong-day.
        Fallback if archive is empty but episodes exist: summarize top-importance
        episodes directly (bounded input via `context_budget` conventions).
- Output: `{"chat": [...], "fitness": {...}, "nutrition": {...}, "recovery": {...},
  "calendar": [...], "tasks": [...], "learning": [...], "sara": [...], "misc": [...]}`

### 2b. `render_facts(payload) -> str`
- Deterministic Python formatting into a plain-text fact sheet. All numbers computed
  here (totals, PRs, kcal/macros), never by the model.
- Skip empty sections entirely (so the model isn't tempted to pad).
- Respect known data gotchas: steps/flights are cumulative → MAX per day; day being
  rendered is always a *completed* day so no partial-day handling needed.
- Cap total size (~6k tokens) — truncate lowest-importance items first, note truncation
  in the sheet ("…and 4 more") rather than dropping silently.

### 2c. `write_diary(facts, user_id) -> Optional[str]`
- One call, mirroring `sara_journal_service._generate_entry()`:
  - local Qwen via `llm_client.chat_completion`
  - `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`
  - **explicit `max_tokens`** (~700) — non-negotiable per the 2026-08-19 llama-server
    runaway-generation incident
  - timeout ~120s, no retry loop (regenerate endpoint is the retry)
- Prompt: Sara's diary voice (borrow tone rules from `prompts/sara_voice.md`), plus:
  *"Write the diary entry for {date} using ONLY the facts below. If a section is empty,
  don't mention it. Do not invent events, numbers, or feelings about things not listed."*
- First-person Sara writing about David's day (consistent with `journal_note` voice),
  target 150–300 words. Dry facts live in the receipts, not the prose.

### 2d. `generate(user_id, log_date) -> dict`
- Orchestrates 2a→2c, then `day_replay_builder.cache_replay(db, replay, summary_text=diary)`.
- Idempotent upsert (already is) → safe for regenerate and backfill.

## Phase 3 — Wire into the dream cycle

- [x] In `nightly_dream_service._run_full_day_replay_and_pattern_detection()`: after
      `build_replay()`, call the diary pipeline and pass the result as `summary_text`
      to the existing `cache_replay()` call. Wrap in try/except so a diary failure
      never blocks pattern detection.
- [x] Keep it inside the existing 2 AM task — no new beat entry.

## Phase 4 — API surface

New `backend/app/routes/daily_log.py` (registered OUTSIDE any try/except — known gotcha):

- [x] `GET /api/daily-log?limit=30` — list: `{date, diary, sections_summary, generated_at}`
      newest first, from `day_replay_cache`.
- [x] `GET /api/daily-log/{date}` — full entry: diary + structured `replay_data` sections.
- [x] `POST /api/daily-log/{date}/regenerate` — re-runs `generate()` for that date.
      Doubles as **backfill** (collectors are date-parameterized; past weeks work
      immediately). Guard: reject future dates and today (day incomplete).
- [x] Auth via the standard `get_current_user` dependency.

## Phase 5 — Frontend view

- [x] Simple journal view (web first): date-paged list; diary prose on top; collapsible
      "What happened" receipts underneath rendered from `replay_data` sections
      (workouts table, nutrition totals, chat sessions, tasks, etc.).
- [x] Regenerate button per entry (calls Phase 4 endpoint).
- [x] Entry point from the existing navigation (near Timeline/Notes); no router changes —
      view-state pattern as usual.
- iOS can come later; the API is the contract.

## Phase 6 (optional, decide after shadow week) — Knowledge-garden mirror

- [ ] On generate, upsert a note `Daily Log/YYYY-MM-DD` with the diary + a compact facts
      section, so entries get search, backlinks, timeline, and `[[linking]]` for free.
- Deferred by default: it duplicates content and the auto-connection detector will chew
  on it; only add if the replay-cache-backed view feels insufficient.

---

## Guardrails / policies honored

- **No agents:** collectors are SQL; the model receives one prompt and returns prose.
- **Local-first:** diary generation is background work → local Qwen lane, never Claude.
- **ET everywhere:** replay date already ET; Phase 1 fixes the boundary math.
- **Bounded LLM call:** `max_tokens` + `enable_thinking: False` + timeout, no retry loop.
- **No new nag surface:** the diary is pull-only (a view), it never pushes notifications.

## Acceptance

1. Morning after deploy: yesterday's row in `day_replay_cache` has a non-null `summary`
   containing a diary that mentions only real events.
2. A day with no chat still produces a diary (fitness/calendar only), with no
   hallucinated conversation.
3. Regenerating a 2-week-old date backfills correctly with right-day events (boundary
   fix verified by the late-night-chat check).
4. Web view lists entries and expands receipts; regenerate works.
5. Diary failure (LLM down) still caches the structured replay; `summary` NULL; endpoint
   can fill it later.

## Estimated size

~200-line service + ~60-line boundary fix + ~10-line dream-cycle hook + ~120-line route
file + one frontend view. No migrations, no new Celery entries.

---

# Addendum — iOS Chat Screen Layout Cleanup (added 2026-08-25)

Separate workstream, parked in this doc by request. Fixes the two chat-screen
complaints: too much permanent chrome around the message list, and the huge
undismissable "Try next" suggestion card that appears after most replies.

## Findings (verified 2026-08-25)

| Piece | Where | Problem |
|---|---|---|
| Suggested-actions card | `ios-app/src/components/chat/SuggestedActions.tsx`, rendered at `ChatScreen.tsx:1613` | "TRY NEXT" eyebrow + full-sentence description + first suggestion blown up into a full-width hero button with its own caption + arrow, then a chip row. ~140–160pt tall. **No dismiss control anywhere** — only cleared by sending a message, tapping a suggestion, or new chat. Hidden while streaming, so it reappears the moment Sara finishes. |
| Suggestion firehose | `backend/app/services/action_suggester.py` | Suggestions attach to almost every turn: every tool maps to canned follow-ups, and even plain answers get "Summarize" (>500 chars) or "Tell me more" (>200 chars). |
| Header | `ChatScreen.tsx` ~1396–1429 | Two lines of static copy ("SARA" eyebrow + "Ask, speak, or pick up where you left off." tagline) + Back + Controls pill. Tagline never changes. |
| SaraStatusBar | `ChatScreen.tsx:1511`, component at ~1715 | Second full-width strip under the header ("Sara is ready" + thought), polls `/api/sara/status` every 60s. |
| "+ New Chat" pill | `ChatScreen.tsx` ~1531 | Its own full-width row floating above the input whenever any messages exist. |
| Context banner | `ChatScreen.tsx` ~1540 | Large but already has a dismiss ✕ — leave as is. |

Worst case after a reply: header + status bar + suggestion card + inbox chip + input
leaves roughly half the screen for messages.

## Phase A — SuggestedActions → single chip row (the actual complaint)

- [x] Rewrite `SuggestedActions.tsx` to one horizontal `ScrollView` of chips (reuse the
      existing `secondaryChip` style for all suggestions, first one may keep accent
      color). Delete eyebrow, description, hero button, and both caption sentences.
      Target height ~36–40pt.
- [x] Add a small ✕ chip at the row's end; new `onDismiss` prop →
      `setSuggestedActions([])` in `ChatScreen`.
- [x] Auto-clear when the user starts typing (hook `ChatInput`'s text-change/focus), so
      the row never competes with the keyboard.

## Phase B — Header + New Chat consolidation

- [x] Collapse header to one row: back chevron, "Sara" title, controls pill. Drop the
      eyebrow/tagline copy entirely.
- [x] Move "+ New Chat" into the header as an icon button (or into the controls modal);
      delete the floating `clearButton` row.

## Phase C (optional) — Status bar fold

- [x] Fold "Sara is {state}" into the header as a one-line subtitle (tappable to expand
      the existing details), removing the separate strip. Keep the 60s poll and graceful
      null render.

## Phase D (optional) — Backend suggestion tuning

- [x] In `action_suggester.py`: drop the length-triggered "Summarize"/"Tell me more"
      fallbacks (or gate them to rare cases); keep tool-derived suggestions; cap at 3.
      Backend-side, so it also quiets any other client.

## Guardrails

- Phases A–C are JS-only in `ios-app/` — a Metro reload on the existing dev client
  picks them up; **no new native/EAS build needed** (per iOS build workflow).
- Phase D is backend → needs the usual container rebuild/restart to take effect
  (deployed-code-lags gotcha).
- No new state, endpoints, or analytics events; keep the existing
  `assistant.suggested_action_tapped` tracking.

## Acceptance

1. After a reply with suggestions, chat shows one chip row ≤ ~40pt with a working ✕;
   dismissed suggestions stay gone until the next reply.
2. Typing in the input clears the suggestion row.
3. Header is a single row; "+ New Chat" reachable from the header; no floating pill row.
4. With Phase C: exactly one strip of chrome above the message list.
5. Message list gains roughly 150–250pt of usable height in the post-reply state.

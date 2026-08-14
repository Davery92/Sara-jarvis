# Dashboard Fix Plan — web + iOS front page (2026-08-02)

Implementation directive. Produced from a live screenshot audit of the web dashboard
(2026-08-02, quiet Sunday — worst-case content day) plus a code trace of every data
source feeding both dashboards. The verdict from the audit: **the layout is fine; the
content pipeline is the problem.** Both dashboards render Sara's machinery instead of
a product for David. Fix the feeds, then unify the two surfaces on one payload, then
make Mind V2's composed voice the thing the dashboard renders.

---

## 1. Evidence (live, 2026-08-02 morning)

All verified on the running system; don't re-derive.

1. **"Needs you" (the page's one amber item) = "Wiring check found issues"** — an
   internal self-diagnostic (`tasks/system_wiring_check.py:245`, `category="system"`,
   `source="system_wiring_check"`). Sara's self-maintenance is presented as the top
   thing demanding David's attention.
2. **"While you were away" is telemetry, all stale (2d old):** `daemon booted
   (v0.11.0) on sara`, `daemon booted (v0.10.0) on sara`, "Stopping the stillness
   loop", "Quiet rest, nothing pulling right now", "35 tool calls · 1 error". The
   dashboard's `ActivityDigest` fetches `/api/acs/v2/activity` **without** the
   `audience=user_facing` filter the endpoint already supports, then fights the noise
   with a 19-regex client-side blocklist (`DashboardHomeView.tsx:180-199`) — an
   unwinnable arms race. (`SaraActivityFeed.tsx:59` already does it right.)
3. **"Ongoing" lists the same door-lock order twice:** "Side Door Lock locks around
   00:00" and "Side Door Lock goes to locking around 00:00". Root cause found:
   `pattern_detector.py:457/496/502` keys patterns by `(entity_id, to_state)` and HA
   locks emit both `locked` and the transient `locking`; each becomes its own pattern,
   each independently promotable to a standing order. `create_order`
   (`standing_order_service.py:44`) has no dedup guard. Also: all four rows are static
   nightly automations shown all day, every day.
4. **Journal repeats itself and leaks the analyst:** two entries 11 minutes apart
   saying the same thing (8-min client dedup window missed them; 0.9 similarity
   server threshold missed the paraphrase), and a third entry in clinical
   third-person ("David is currently surging through his morning peak with a robust
   alertness score of 0.75…") — the `thought`-vs-`journal_note` leak
   ([[gotcha_journal_vs_thought]]) showing up in `sara_journal` itself.
5. **Morning brief truncates mid-sentence at 600 chars** ("…misbehavior, emphasizing
   that while...") — `DashboardHomeView.tsx:476-481` cuts at last space, not sentence.
   Its first paragraph is the weather, duplicating the weather card two inches above.
6. **Web and iOS are two unrelated products.** Web assembles ~10 raw fetches in
   `useDashboardWorkspace.ts` into 25 untyped props; iOS renders a curated
   `/api/sara/brief` payload (`routes/sara_status.py:277`). Same morning, different
   stories. iOS `TodayBrief` is presence-first but owns almost no content — every
   element is a launcher into Chat or another tab, and it has no "while you were
   away" at all.

**Design principle for everything below:** the dashboard renders *composed Sara* —
"what I'd tell you if you walked in the room" — not raw internal feeds. One backend
payload, two renderers.

---

## 2. Phase 0 — Stop the bleeding (mechanical, no design decisions, ship same day)

### 0A. Activity digest: use the server's audience filter, delete the regex blocklist

**Files:** `frontend/src/components/shell/DashboardHomeView.tsx`

- Change the fetch at line 210 to `/api/acs/v2/activity?limit=60&audience=user_facing`.
  Server semantics (`routes/acs_daemon.py:569-609`): `internal` OR `NULL` audience is
  excluded, so old unclassified rows (the stale boot lines) disappear for free.
- Delete `DIGEST_NOISE` (lines 180-199) and `isDigestNoise`; keep the consecutive-
  duplicate collapse.
- Remove `boot` from `HUMAN_KINDS` (line 231) — "daemon booted (v0.11.0)" is
  machinery no matter how it's phrased. Keep the machinery summary line, sourced from
  a second fetch with `audience=internal&limit=30` (or drop the machinery line
  entirely if that feels like clutter — David's call, default: keep, it's one line).
- Spot-check `classify_audience()` (`acs_daemon.py:447`) tags boot/tick/tool kinds as
  internal for *new* rows; add kind-level defaults there if any leak through. Do NOT
  add content regexes — that's the arms race this phase deletes.

**Acceptance:** screenshot shows zero daemon/loop/goal chatter in "While you were
away"; stale-boot lines gone; feed shows only user-facing items or the quiet-state
empty line.

### 0B. Standing orders: kill the duplicates at the source

**Files:** `backend/app/services/pattern_detector.py`,
`backend/app/services/standing_order_service.py`, one-time SQL cleanup.

1. **Normalize transient HA states before keying** in `pattern_detector.py` (~457,
   ~496): map `locking→locked`, `unlocking→unlocked`, `opening→open`,
   `closing→closed` (single dict, applied to `to_state` before pattern key,
   `trigger_conditions`, and the verb map at 502). The "goes to locking" phrasing
   becomes impossible.
2. **Dedup guard in `create_order`** (`standing_order_service.py:44`, INSERT at 71):
   before inserting, look for an `active` order with the same `entity_id`, same
   `action_config` service, and trigger time within 20 minutes; if found, return the
   existing order (log it) instead of inserting. `check_conflicts()` (line 813)
   already computes warnings but nothing enforces them — this makes creation enforce.
   Note `promote_pattern` (line 772) and the attention-queue action path
   (`autonomy/attention_queue.py:629-659`) both funnel through `create_order`, so one
   guard covers both.
3. **One-time cleanup:** find active near-duplicate rows (same entity_id +
   action_config, ±20min trigger), keep the older/cleaner-description row, set the
   rest `status='retired'`. Small script or manual SQL; record what was retired in
   the commit message.

**Acceptance:** `GET /api/standing-orders?status=active` has no two rows with the
same entity + action + time; re-running pattern promotion does not resurrect the dup.

### 0C. "Needs you": Sara's self-maintenance is not David's urgent item

**Files:** `backend/app/services/autonomy/attention_queue.py`,
`backend/app/routes/autonomy_attention.py`, `frontend/src/hooks/useDashboardWorkspace.ts`.

- Add an `exclude_categories: list[str]` param to `list_items()` (line 231, WHERE at
  255) and to the count query behind `/autonomy/attention/count` (route line 39) —
  both must agree or the amber chip count won't match the list.
- Dashboard fetches (`useDashboardWorkspace.ts:226-228`) pass
  `exclude_categories=system`. The items still exist and still appear in the unified
  inbox (FYI tier) — they are demoted from the dashboard's amber "Needs you" slot,
  not hidden.
- `category` is an unconstrained varchar — add a code-side constant
  `SELF_MAINTENANCE_CATEGORIES = {"system"}` next to `list_items` so the taxonomy
  lives in one place; if other self-diagnostic producers use different categories,
  fold them in there (grep producers by `source` to check: `system_wiring_check` is
  the known one).

**Acceptance:** with a wiring-check item live, dashboard "Needs you" shows "Nothing
needs you right now" (or real items only) and the chip count matches; the item is
still reachable in the inbox.

### 0D. Journal: reroute the analyst, widen the dedup

**Files:** `backend/app/routes/sara_activity.py` (read path), the writer TBD (write
path), `frontend/src/hooks/useDashboardWorkspace.ts` (client dedup).

1. **Find the writer** of the third-person analytical entries: query `sara_journal`
   for the "alertness score" entry, note its `entry_type`/source, and trace which
   service wrote it (likely interoception/deliberation prose). Per
   [[gotcha_journal_vs_thought]], that content belongs in `agent_run_log`
   (`thought`), not `sara_journal`. Reroute at the writer. Do not regex-filter
   third-person text at the API — fix the source.
2. **Read-path guard** while old rows age out: in `sara_activity.py:111-152`
   (`activity_type=journal` branch), exclude the offending `entry_type` value(s)
   identified in step 1.
3. **Dedup:** server-side similarity dedup (lines 133-136) drops to threshold 0.8
   within a 3h window for journal entries (the two "quiet Sunday" paraphrases scored
   below 0.9). Client-side 8-min `unified` window (`useDashboardWorkspace.ts:166`)
   widens to 30 min. Don't chase perfection here — Phase 2 makes the journal a
   composed excerpt anyway.

**Acceptance:** dashboard journal shows no third-person analytical prose and no two
entries saying the same thing; entries read first-person in Sara's voice.

### 0E. Brief excerpt: cut at a sentence

**File:** `frontend/src/components/shell/DashboardHomeView.tsx:476-481`.

Truncate at the last sentence terminator (`. ! ?`) before 600 chars; fall back to
word boundary only if no sentence break exists. Optional follow-up (content, not
dashboard): the morning brief generator leads with weather that the weather card
already shows — when Phase 1 touches the brief payload, ask the generator for a
`dashboard_excerpt` that leads with the most useful non-weather line. Not blocking.

---

## 3. Phase 1 — One front-page payload, two renderers

**Goal:** both dashboards render the same `/api/sara/brief` payload. Kills the
25-untyped-prop assembly on web and the web/iOS divergence in one move.

**File:** `backend/app/routes/sara_status.py` (`get_sara_brief`, line 277). Keep the
existing per-section try/except pattern (a failing section is omitted, never a 500).
Additive only — iOS already consumes this endpoint, so nothing existing may be
renamed or removed until both clients are migrated.

Add sections:

1. **`needs_you`** — reuse `build_unified_inbox(db, user_id)` (`assistant_inbox.py:76`)
   `needs_you` list (top 3 + total), minus `SELF_MAINTENANCE_CATEGORIES` (0C), plus
   badge via `compute_badge` (`assistant_inbox.py:58`). Do NOT reimplement the
   formula — the module docstring declares it single-source-of-truth for a reason.
2. **`ongoing`** — active timers + standing orders **firing within the next 12h**
   (ET, via `app.core.timezone` helpers — no naive `datetime.now()`), with `fires_at`.
   The route already enriches `fires_at` (`standing_orders.py:65`); reuse that logic,
   don't fork it.
3. **`journal`** — up to 3 deduped first-person entries (the exact query Phase 0D
   left behind in `sara_activity.py`), each with timestamp + emotional_state.
4. **`digest`** — "while you were away": Phase 1 sources it from
   `sara_activity_log` `audience=user_facing` (same as 0A); Phase 2 swaps the source
   to composed utterances without changing the payload shape. Shape now:
   `{items: [{text, at}], machinery: {tool_calls, errors}}`.
5. **`weather`** — move the weather fetch server-side into the brief so iOS gets it
   too (web currently fetches it separately).

**Web migration** (`useDashboardWorkspace.ts`, `App-interactive.tsx`,
`ShellWorkspaceContent.tsx`, `DashboardHomeView.tsx`): one new fetch of
`/api/sara/brief`, passed down as a single typed `brief` prop. Migrate section by
section (needs_you → ongoing → journal → digest → weather), deleting the
corresponding raw fetch + props at each step. Timers stay on their existing live
polling if the brief's snapshot cadence is too slow for the countdown — the
`LiveTimer` component only needs `end_time`, which `ongoing` carries.

**iOS:** no changes required this phase (already on the endpoint). New sections are
additive.

**Acceptance:** web dashboard renders entirely from one payload + the activity
machinery line; deleting `loadJournalEntries`, the standing-orders fetch, and the
attention fetch from `useDashboardWorkspace.ts` breaks nothing; iOS unchanged.

---

## 4. Phase 2 — The dashboard speaks in Mind V2's composed voice

**This is the payoff phase, and it feeds the shadow week.** Mind V2's
judge→compose→review pipeline is live in shadow mode writing `composed_utterance`
rows (`alembic/versions/129/130`, writers in `tasks/compose.py:291/202` and
`services/urgent_lane.py:130`) that nobody reads. Per [[project_mind_v2]], the next
step is *a shadow week reading composed_utterance, not more code* — making the
dashboard its first consumer gives David a daily reading surface for exactly that.

1. **`digest` section source swap** in `get_sara_brief`: last 24h of
   `composed_utterance` rows with `review_verdict IN ('approve','edit')`, rendering
   `final_text`, ordered by `created_at DESC`, capped at 6. Include `slot` rows
   (morning/evening digests) first. Fall back to the Phase 1 `sara_activity_log`
   query when no composed rows exist in the window (cold days). Payload shape is
   unchanged from Phase 1 — clients don't know the source moved.
2. **Label it honestly while in shadow mode:** each digest item carries
   `delivered: bool` (`delivered_at IS NOT NULL`). Web renders undelivered items
   normally (this IS the shadow-reading surface); once sender cutover happens
   (separate plan: SARA_MIND_V2_REWIRE_PLAN), the flag distinguishes "told you" from
   "would have told you" and can then just be dropped.
3. **Empty-day composure:** when calendar is empty AND digest is empty, the brief
   returns a single `quiet_line` — the most recent journal entry's first sentence —
   and the web renderer collapses the empty sections into that one line instead of
   stacking five "No X today" placeholders.
4. **LLM policy check (must hold):** this phase adds ZERO new LLM calls — it only
   reads rows the existing Qwen-driven compose pipeline already writes
   ([[feedback_local_first_llm]]). If a future "front-page composer" task is wanted,
   it's a new plan, on Qwen, `enable_thinking: False` for short outputs.

**Acceptance:** on a day with composed rows, "While you were away" reads as Sara's
sentences (no kind-labels, no tool counts in the main list); the digest content
matches `SELECT final_text FROM composed_utterance ... ORDER BY created_at DESC`;
David can do his shadow-week review from the dashboard instead of psql.

---

## 5. Phase 3 — Renderer polish (after content is right)

Deliberately last: none of this was the actual problem.

**Web (`DashboardHomeView.tsx`):**
- "Ongoing" shows only next-12h items (payload already filtered, Phase 1); each row
  gets its relative time ("in 4h") instead of a bare `00:00` column.
- Empty-day layout collapses to: greeting, weather, `quiet_line`, ask dock.
- Machinery line links to the full activity view (`SaraActivityFeed`) instead of
  expanding inline, or keeps the inline expand — David's preference at review time.

**iOS (`components/sara/TodayBrief.tsx`):**
- Add a "While you were away" group under "Needs you" rendering the same `digest`
  section (top 3 items). The hero stays — presence is the point of the iOS surface —
  but the screen finally owns content beyond launcher chrome.
- `needs_you` group switches from threads/reviews-only to the payload's unified
  `needs_you` (it currently misses attention items entirely).
- JS-only changes: reachable via `expo start` reload, **no EAS rebuild needed**
  ([[reference_ios_build_workflow]]).

---

## 6. Verification (every phase)

- **Visual:** screenshot recipe from [[reference_webapp_screenshot]] (Playwright in
  the backend container, mint JWT, load via host IP, `wait_until="load"`). Capture
  top + scrolled states; the internal scroll container needs an `el.scrollTop` nudge,
  `full_page` alone doesn't capture it. Delete temp files from container AND host.
- **Deployed-code check before declaring anything fixed:** backend + celery only
  load code at container restart ([[gotcha_deployed_code_lags]]); restart backend
  (kills in-flight dispatch — pick a quiet moment) and `--force-recreate` celery if
  task modules changed.
- **Data checks:** `psql "$DATABASE_URL"` — standing-order dup query (0B), attention
  count vs list parity (0C), `sara_journal` entry_type audit (0D),
  `composed_utterance` row comparison (Phase 2).
- **Standing gotchas that apply here:** ET-only hour logic via `app.core.timezone`
  ([[feedback_no_utc]]); route registration outside try/except; timestamptz writes
  use `datetime.now(timezone.utc)` never naive ([[gotcha_naive_datetime_et_container]]).

## 7. Explicit non-goals

- No visual redesign of either dashboard (typography/layout stay).
- No Mind V2 sender cutover — that's SARA_MIND_V2_REWIRE_PLAN's scope; this plan
  only *reads* composed output.
- No new LLM calls anywhere in this plan.
- No changes to the morning brief generator beyond the optional `dashboard_excerpt`
  note in 0E.

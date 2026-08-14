# Web Dashboard Redesign — Dense Mission Control (2026-08-07)

**Status:** design plan, not started. Written for an implementing agent.
**Scope:** web frontend only (`frontend/`). No iOS changes. No new backend endpoints required (one optional enrichment noted in §5).
**Relationship to `DASHBOARD_FIX_PLAN_2026_08_02.md`:** that plan fixed *content* (unified `/api/sara/brief` payload, dedup, audience filtering, composed voice). It shipped. This plan is the *presentation* rebuild on top of that payload. Do not undo any of its phases — in particular, keep `/api/sara/brief` as the single front-page payload and keep the `SELF_MAINTENANCE_CATEGORIES` exclusion in `needs_you`.

---

## 1. Mandate

David's verdict on the current dashboard, verbatim category by category — **all four** were selected:

1. **Empty / useless** — tons of dead space, barely any information. The whole page fits one 1600×1000 viewport at ~25% pixel utilization while the system tracks fitness, food, workouts, reminders, calendar, learning, missions, hosts, and an autonomous agent.
2. **Wall of prose** — the morning brief and journal are paragraphs to read, not something to glance at. Learning "it might rain" takes three sentences.
3. **Layout / structure** — the giant greeting hero eats the top third; the two-column split leaves the left column half-empty; counts are shown where content should be ("2 need you" chip, "5 tool calls").
4. **Visual style** — flat dark boxes, oversized display type, no density.

**Chosen direction: Dense mission control.** A glanceable grid answering "what's my day, what needs me, what's my body doing, what has Sara done" in two seconds. Real data everywhere; prose demoted to one collapsed card.

### What the payload already carries that the page throws away

`/api/sara/brief` (backend `backend/app/routes/sara_status.py:316`) already returns, per load:

- `brief_sections[]` with `fitness` (calories_today, protein_today, goal, last_meal_ago_hours), `threads` (open follow-up topics), `learning` (reviews_due), `self_status` (degraded body components), `verification` (evening memory-check question), `calendar` (events + next_in_minutes)
- `sara_status` (emotional_state, latest_thought, watching_for, **kernel_state**)
- `activity_state` + `interruptibility`
- `suggested_actions[]` (quick-reply chips — iOS renders them, web ignores them)
- `needs_you`, `ongoing`, `journal`, `digest`, `weather`, `quiet_line`

The current `DashboardHomeView` renders only the last row of that list. **Rendering what already arrives is most of this redesign.** Separately, `/reminders` is fetched every 60s by `useDashboardWorkspace` and never rendered at all.

---

## 2. Design principles

1. **Two-second read.** Every card leads with a number or a name, never a sentence. Sentences are for the brief card and Sara's thought line only.
2. **Content where counts are.** Never show a badge count when the top 1–3 actual items fit. Counts are for overflow ("+4 more"), not headlines.
3. **One hero, and it isn't the greeting.** The greeting compresses to a single header line. If anything on the page is visually loudest, it's the "Needs you" card when non-empty.
4. **Everything clicks through.** Every card navigates to its full view (`onNavigate`), every stat tile is a button. No dead pixels.
5. **Prose is opt-in.** Brief collapsed to ~3 bullet lines + "Listen" + "Open full brief →". Journal collapsed to the single latest entry, one line, expandable.
6. **Density without clutter.** More cells, smaller cells, tighter gaps — but consistent card anatomy, one type scale, aligned columns. Not a cockpit cosplay; a well-set broadsheet.
7. **Degrade to nothing, not to filler.** A card with no data renders a single quiet line or disappears entirely (rules per-card in §4). No skeleton fields shouting "empty."

---

## 3. Layout

Container: widen `max-w-[1180px]` → `max-w-[1440px]`, keep `px-4 md:px-8`. Root grid is a 12-column CSS grid (`grid-cols-12 gap-5`) below the header band; cards span columns per the wireframe. Section vertical rhythm drops from `space-y-12` to grid `gap-5`.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ HEADER BAND (one row, ~64px)                                                  │
│ Good morning, David · Friday, August 7      ⛅ 77° 90°/71° · rain 2pm         │
│ [Sara ● attentive · focused] [⚠ degraded: embeddings]      (right-aligned)    │
├───────────────────────────────────────────────────────────────────────────────┤
│ KPI STRIP (full width, 6–8 stat tiles, one row, horizontal scroll <lg)        │
│ [2 Need you][3 Events][1,460/2,300 kcal][118g protein][Recovery 82]           │
│ [4 Reviews due][1 Mission running][Timer 12:41]                               │
├──────────────────────────────┬────────────────────────┬───────────────────────┤
│ A NEEDS YOU        (span 5)  │ B TODAY TIMELINE (4)   │ C SARA        (span 3)│
│ actual items, inline actions │ merged: calendar +     │ kernel/activity state │
│                              │ reminders + training   │ latest thought (1 ln) │
├──────────────────────────────┤ session + timers,      │ watching-for chips    │
│ D BRIEF (bullets)  (span 5)  │ chronological, "now"   │ while-you-were-away   │
│ ▸ Listen · Open full →       │ marker line            │ (3 rows, compact)     │
├──────────────────────────────┤                        │ journal (1 collapsed) │
│ E BODY & TRAINING  (span 5)  │                        │                       │
│ kcal meter · protein meter   │                        │                       │
│ training day / rest · last   │                        │                       │
│ meal · weight sparkline      │                        │                       │
├──────────────────────────────┴────────────────────────┴───────────────────────┤
│ F ONGOING (full width, only when non-empty): standing orders · missions       │
├───────────────────────────────────────────────────────────────────────────────┤
│ ASK DOCK (unchanged, sticky bottom)                                           │
└───────────────────────────────────────────────────────────────────────────────┘
```

Responsive: `lg` breakpoint switches to the 12-col grid; below it, cards stack single-column in priority order A → KPI → B → E → D → C → F. The KPI strip becomes horizontally scrollable with snap.

`MomentCardStack` stays mounted above the header (it renders nothing when empty).

---

## 4. Component specs

All new components live in `frontend/src/components/shell/dashboard/` (new directory), imported by a rewritten `DashboardHomeView.tsx`. Keep the existing card token (`rounded-xl border border-white/8 bg-white/[0.02]`) as the base surface so the page doesn't fork the shell's visual language — density comes from layout, not a new skin.

### 4.0 Header band (replaces the hero)

- Left: `{greeting}, David` in `text-xl font-semibold` (down from 3xl/2.3rem display) + `· {dateLine}` in `text-slate-400 text-sm` on the **same line**.
- Right: inline weather — emoji, current temp `text-lg font-semibold`, `hi/lo` muted, and **the one forecast fact that matters** if derivable from the payload (e.g. `rain 2pm`); one line, no card box.
- Below-left, same band: Sara presence chip (dot + `attentive · focused` from `sara_status.emotional_state` + `kernel_state`) and, only when `self_status.healthy === false`, an amber `⚠ degraded: {names}` chip that clicks to the diagnostics view. Status colors are reserved: amber only for needs-attention/degraded, rose only for errors — never decorative.
- Delete: `WeatherCard` (the boxed version), the standalone date line, the `StatChip` row (superseded by the KPI strip).

### 4.1 KPI strip

A single row of stat tiles. **Stat-tile contract** (fixed anatomy, one component `StatTile.tsx`):

- `label` — sentence case, `text-[11px] text-slate-500`, no trailing colon
- `value` — `text-xl font-semibold text-slate-100`, proportional figures (do **not** put `tabular-nums` on tile values; reserve tabular for timeline time columns)
- `sub` — optional secondary line, `text-[11px] text-slate-500`
- `tone` — `default | amber | teal` (amber only when the tile demands action)
- `onClick` — required; every tile navigates
- Renders `null` when its count/value is absent or zero **except** the calorie and protein tiles, which always render during the day (a zero there is information).

Tiles, in fixed order (order is stable; missing tiles collapse, never reflow the survivors' colors — identity by position and label, not hue):

| Tile | Value | Sub | Source | Click → |
|---|---|---|---|---|
| Need you | `needsYouCount` | oldest item age | brief `needs_you` + `missionAwaitingCount` | attention inbox |
| Events | upcoming-today count | `next in 40m` from `calendar.next_in_minutes` | brief `calendar` section | calendar |
| Calories | `1,460 / 2,300` | remaining | brief `fitness` section | fitness |
| Protein | `118g` | vs target if available | brief `fitness` section | fitness |
| Recovery | score 0–100 | qualitative word | `/api/fitness/recovery/{today}` (§5) | fitness |
| Reviews due | `reviews_due` | — | brief `learning` section | learning view |
| Missions | running count | awaiting count if >0 | existing `missions` state | automations |
| Timer | live countdown (reuse `LiveTimer`) | timer title | existing `timers` state | — |

### 4.2 Card A — Needs you

Largest visual weight on the page when non-empty. Current implementation is close; changes:

- Show up to **5** items (was 3), each row: title (medium, slate-100), category tag if present, relative time, and — when the item carries an obvious action — an inline affordance (at minimum "Open →"; don't build per-category action plumbing in this pass).
- Mission-awaiting rows merge into the same list, not a separate button.
- Evening `verification` section (memory-check question) renders here as a low-priority row with inline text-input → POST `/api/memory/verification-answer` (endpoint exists; check its exact path in `backend/app/routes/memory.py` before wiring).
- Empty state: single line "Nothing needs you." — card stays (it anchors the grid) but shrinks to one row.

### 4.3 Card B — Today timeline

The merge is the point: one chronological rail for the whole day, not three separate lists.

- Merge sources: calendar events (existing `calendarEvents`), **reminders** (already fetched, currently unrendered — filter to today, map `reminder_time` → timeline row with a bell glyph), active/finished **timers** (countdown rows, reuse `LiveTimer`), and today's **training session** if `/api/fitness/templates/today` returns one (row labeled e.g. "Push day — 6 exercises", glyph 🏋, click → fitness).
- Sort ascending by time; all-day events pinned at top. Time column right-aligned `w-[4.5rem] tabular-nums` (keep existing pattern).
- A "now" divider line (1px, teal-400/40) positioned between past and future rows; past rows dim to slate-500 (keep strikethrough for past calendar events only).
- Keep the `isNow` teal highlight row treatment.
- Empty state: "Clear day." plus tomorrow's first event if trivially available; otherwise just the line.

### 4.4 Card C — Sara rail

Compresses the old right rail into one card with fixed sub-blocks, top to bottom:

1. **State line:** kernel state + activity state + emotional state as small chips (e.g. `ambient · at desk · curious`). Interruptibility renders only as a tooltip, not a meter — it's Sara-internal.
2. **Thought:** `sara_status.latest_thought`, one line, italic, quoted, truncated with title attr. Omit block if null.
3. **Watching for:** `sara_status.watching_for[]` as muted chips, max 3. Omit if empty.
4. **While you were away:** the digest, tightened — max 3 rows, each **one line** `truncate` (not the current 180-char two-liners), machinery line (`5 tool calls · 1 error`) kept as-is. Keep the `quiet_line` fallback.
5. **Journal:** latest entry only, collapsed to 2 lines with the existing expand toggle, plus "All entries →" link to the journal/briefings view. Delete the 3-entry stack.
6. **Open threads:** if the `threads` section is non-empty, topic chips ("re: garage door", max 3) that click into chat with the topic prefilled via `onAskSara`.

### 4.5 Card D — Brief

- Render the brief's markdown but **cap at 3 list items / ~280 chars**, preferring bullet lines if the generator emits them; keep the sentence-boundary cut logic (Phase 0E) as fallback for prose briefs.
- Header row: "Morning brief" (or "Evening brief" by `time_period`) + `▸ Listen` + `Open full brief →` (existing handlers, unchanged).
- The audio `<audio>` element and blob handling move with it, untouched.
- `suggested_actions[]` from the brief render as quick-chips under the brief text, wired to `onAskSara(a.message)` — the web finally catches up to iOS here.

### 4.6 Card E — Body & training

New card; all data already exists server-side.

- **Calorie meter** and **protein meter**: horizontal meters, `h-2 rounded-full`. Meter spec (non-negotiable): the unfilled track is a *lighter step of the same hue* as the fill (teal-400 fill on teal-400/15 track), **not** neutral gray — state must read across the whole bar. Fill switches to amber only past 100% of goal. Value label sits beside the meter as text in text tokens (`1,460 / 2,300`), never colored text — color lives in the mark, not the type.
- **Training line:** from `/api/fitness/templates/today` — "Push day · 6 exercises" or "Rest day"; if `/api/fitness/workout-session/active` returns a session, replace with a live "Workout in progress → " row (teal, links to fitness).
- **Last meal:** `last_meal_ago_hours` from the brief fitness section, one muted line ("Last ate 3h ago").
- **Weight sparkline:** 12-point sparkline from `/api/fitness/weight/trend`, 2px line, slate-500 stroke with the latest point as a ≥8px teal dot with a 2px surface ring; latest value direct-labeled at the line end (`182.4`), no axis, no grid. This is the only chart on the page — do not add more. If trend data < 3 points, render the latest value as plain text instead.
- No gauges, no rings, no pie of two slices anywhere on this page.

### 4.7 Card F — Ongoing

- Standing orders (existing rows) + running missions (name + state + started-ago) in a two-column flow. Renders only when non-empty (current behavior, kept). Timers move OUT of here (they live in the timeline + KPI strip now).

### 4.8 Ask dock

Unchanged. It's the one part of the current page that works.

---

## 5. Data wiring

### Changes to `frontend/src/hooks/useDashboardWorkspace.ts`

1. **Expose the whole brief.** Add to the return: `briefSections` (`brief?.brief_sections || []`), `saraStatusLine` (`brief?.sara_status`), `activityState`, `interruptibility`, `suggestedActions`, `selfStatus`, `timePeriod`. The hook already stores `brief`; today it cherry-picks five fields and discards the rest.
2. **New fetches**, added to the `loadDashboardData` `Promise.allSettled` batch (page already fires 7 parallel calls; these are cheap):
   - `GET /api/fitness/recovery/{YYYY-MM-DD}` (today, **ET date** — use a local-date formatter, not `toISOString().split('T')[0]` which is UTC and wrong before ~8pm ET; see gotcha list) → `recovery`
   - `GET /api/fitness/templates/today` → `todayTemplate`
   - `GET /api/fitness/workout-session/active` → `activeWorkout`
   - `GET /api/fitness/weight/trend` → `weightTrend`
   Each tolerates 404/failure → `null`, cards degrade per §4 rules.
3. **Reminders:** already fetched; expose a `todayReminders` derived list (due today, not completed).
4. Do **not** add polling beyond the existing intervals; the new fetches ride the existing `view === 'dashboard'` load.

Note the existing UTC bug on line ~127 of the hook (`loadTodayCalendar` builds `today` from `toISOString()`): fix it to ET local date while in there — same class of bug as the new recovery fetch would have.

### Optional backend enrichment (only if the client-side version feels thin)

Extending the brief's `fitness` section server-side (carbs/fats, training-day flag from `training_day.is_training_day()`, recovery score from `morning_brief_service`'s existing computation) would collapse three of the four new fetches into the one payload. It's a ~30-line change in `sara_status.py`. **Do it only as a follow-up** — the client-side version ships without touching the backend container, which matters because restarting the backend kills in-flight dispatch tasks (see gotchas).

### Endpoint reference (all verified to exist)

| Data | Endpoint | Mounted at |
|---|---|---|
| Front-page payload | `GET /api/sara/brief` | `sara_status.py:316` |
| Morning brief text/audio | `GET /api/morning-brief/today`, `/{date}/audio` | existing |
| Recovery | `GET /api/fitness/recovery/{log_date}` | `fitness.py`, prefix `/api/fitness` (`main_simple.py:4868`) |
| Today's template | `GET /api/fitness/templates/today` | fitness router |
| Active workout | `GET /api/fitness/workout-session/active` | fitness router |
| Weight trend | `GET /api/fitness/weight/trend` | fitness router |
| Reminders | `GET /reminders` | already in hook |
| Timers | `GET /timers` | already in hook |
| Missions | `GET /autonomy/missions?limit=20` | already in hook |

---

## 6. Visual system

- **Type scale (whole page):** header greeting `text-xl`; card headings keep the existing `text-[11px] uppercase tracking-[0.16em] text-slate-400` label style; tile values `text-xl`; body rows `text-sm`/`text-[15px]`; meta `text-[11px]`–`text-xs text-slate-500`. Nothing on the page except the greeting exceeds `text-xl`. The `font-display` 2.3rem hero is deleted.
- **Color roles (strict):** teal = Sara/accent/interactive; amber = needs-you + degraded + over-goal only; rose = errors only; slate ramp = all text. Data marks carry color; **text never wears the data color** — values and labels stay in slate tokens with a colored mark beside them when identity is needed.
- **`tabular-nums`** only where digits must align vertically: the timeline time column and the timer countdown. Not on tile values.
- **Card anatomy:** every card = surface token + `p-4` + label row + content; no card-in-card nesting; no borders between rows inside a card (use spacing).
- **Grid gaps:** `gap-5` (20px) everywhere; inside cards `space-y-2`/`space-y-2.5`.
- The left icon nav rail is out of scope for this plan (it's shell chrome, `ShellNavigation.tsx`) — but if trivial, add `title` tooltips to its icons as a courtesy fix.

---

## 7. Implementation order

Work on branch `feat/sara-mind-v2` (current working branch). Each phase ends with the Playwright verification in §8 — screenshot, look at it, fix what's visually wrong before moving on.

- **Phase 1 — skeleton.** New `dashboard/` component directory; rewrite `DashboardHomeView.tsx` to the §3 grid using only data the hook already returns (header band, KPI strip minus recovery, cards A/B/C/D/F with existing data, timeline without training row). Delete the hero, `WeatherCard` box, `StatChip` row. This phase alone kills complaints 1–3 for existing data.
- **Phase 2 — body & training.** Hook changes (§5), Card E, recovery + template + active-workout + weight tiles/rows, training row in the timeline, reminders into the timeline. Fix the UTC date bug in `loadTodayCalendar`.
- **Phase 3 — Sara rail depth.** brief_sections rendering (threads, learning, verification answer flow), suggested-action chips, watching-for chips, journal collapse.
- **Phase 4 — polish.** Empty states per card, responsive stacking, `<lg` KPI scroll-snap, hover/focus states on every clickable, dark-surface contrast pass on the meters/sparkline.

Files touched: `frontend/src/components/shell/DashboardHomeView.tsx` (rewrite), `frontend/src/components/shell/dashboard/*` (new: `StatTile.tsx`, `HeaderBand.tsx`, `NeedsYouCard.tsx`, `TodayTimeline.tsx`, `SaraRail.tsx`, `BriefCard.tsx`, `BodyCard.tsx`, `OngoingCard.tsx`), `frontend/src/hooks/useDashboardWorkspace.ts`, `frontend/src/components/shell/ShellWorkspaceContent.tsx` (prop plumbing). `shellDisplay.ts` helpers reused as-is.

Props: prefer passing the `brief` object + a few callbacks down instead of exploding 30 props again — `DashboardHomeViewProps` currently takes 33 props and most are brief fields; collapse to `{ brief, briefLoaded, morningBrief*, timers, reminders, calendarEvents, missions, fitness: {recovery, todayTemplate, activeWorkout, weightTrend}, currentTime, onNavigate, onAskSara, onReviewAttentionInbox, audio handlers }`.

---

## 8. Verification (every phase)

Screenshot the live logged-in app (Vite hot-reloads; no rebuild needed):

1. Write a script to `backend/_shot.py` (host `./backend` dir is mounted at `/app`): Playwright async, mint a JWT with `from app.core.auth import create_access_token; create_access_token(data={"sub": "64f37c56-85cb-4590-8de9-adfc17d343ed"})`, set it as cookie `access_token` for domain `10.185.1.180`, `goto("http://10.185.1.180:3000/", wait_until="load")` (NOT networkidle — SSE hangs it), `wait_for_timeout(7000)`, screenshot at **1600×1000** and also **1280×800**.
2. `docker compose -f docker-compose.dev.yml exec -T backend python3 /app/_shot.py`, then Read the PNGs.
3. Delete temp files from container (root-owned) **and** host afterward.

Acceptance per phase:
- No viewport-height region with less than ~50% of its area carrying data at 1600×1000.
- Every number visible on the page traces to a live endpoint (no hardcoded placeholders).
- With the DB in its normal state, the page shows ≥ 12 distinct data facts above the fold (currently: ~6).
- Timeline "now" marker sits between the correct rows for the current ET time.
- `npm run lint` clean in `frontend/`.

---

## 9. Gotchas the implementing agent must respect

- **ET, not UTC, for all day-boundary logic** (`app.core.timezone` server-side; client-side build local date strings, never `toISOString().split('T')[0]`).
- **Deployed code lags the working tree** — the *frontend* dev container hot-reloads, but any backend change needs a container restart, and restarting the backend kills in-flight dispatch tasks. Prefer the zero-backend-change path (§5).
- The brief's calendar events come back as **naive local timestamps**; the existing render code already handles them — reuse its parsing, don't "fix" it to UTC.
- `needs_you` intentionally excludes Sara's self-maintenance categories — don't re-add them when merging mission rows.
- The attention queue had a recycle bug (fixed 2026-07-06); if items look duplicated during testing, check `status`-based dedup before blaming the UI.
- Keep `MomentCardStack` mounted — it's the delivery surface for minted moment cards and renders nothing when empty.
- Don't touch `composed_utterance` / Mind V2 shadow-mode plumbing; the dashboard reads the brief payload only.

## 10. Non-goals

- No iOS changes (TodayBrief already renders most of this payload; it's the reference, not the target).
- No new database tables, no Celery changes, no brief-generator prompt changes.
- No theme/skin change — same dark surface language, denser layout.
- No charts beyond the single weight sparkline. If a future pass adds more, load the dataviz skill rules first (meters use same-ramp tracks; no dual axes; no gauges; text never wears data color).

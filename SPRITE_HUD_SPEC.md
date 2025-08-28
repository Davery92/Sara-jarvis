# Sprite Mini‑HUD — Design & Implementation Spec

Purpose: Define a compact, anchored HUD opened by the sprite, giving a fast “command center” snapshot and one‑tap navigation. This spec complements planning.md’s sprite plan and maps directly to your codebase.

---

## Scope & Goals

- Provide fast access to:
  - Now: Chat entrypoint + last assistant status
  - You: Habits summary and streak status
  - Brain: Recent autonomous insights
  - Threat: Vulnerability snapshot and severity
- Keep it tiny, responsive, and accessible; open near the sprite to preserve spatial continuity.
- Non-blocking: does not replace full pages; acts as a launcher and glanceable summary.

Success criteria
- Opens in <16ms after click; no jank.
- Clear info scent for each card; 1 click to navigate to full view.
- Keyboard + screen reader accessible; respects reduced motion and calm mode.

---

## Information Architecture

Cards (Phase 1)
- Now (Chat)
  - Primary: “Open Chat” CTA
  - Secondary: last message preview or streaming status
- You (Habits)
  - Primary: Today’s completion count and next due item (if any)
  - Secondary: current streak badge (if exists)
- Brain (Insights)
  - Primary: Most recent autonomous insight message
  - Secondary: a subtle tag (quick/standard/digest sweep)
- Threat (Vulnerability)
  - Primary: Latest report severity: None/Low/Medium/High/Critical
  - Secondary: count of KEV or criticals today

Optional (Phase 2+)
- Inbox: unseen notifications count and a preview line
- Timers/Reminders: next timer or due reminder (if imminent)

---

## Data Sources (existing APIs)

- Chat: no data fetch required to open; optional last assistant status shown from recent SSE events (held in memory).
- Habits: `GET /habits/today` for today’s instances; `GET /habits/{habit_id}/streak` or a simple streak summary if cached; or summarize from `/autonomous/insights` of type `habit_*`.
- Insights: `GET /autonomous/insights?limit=1` for latest message.
- Vulnerability: `GET /api/vulnerability-reports/latest` for severity and counts.

Notes
- Phase 1 uses polling on HUD open; cache data in component state.
- Phase 2 can subscribe to future `/sprite/events` SSE and pre-populate cache.

---

## Interaction Design

- Open/Close
  - Click sprite toggles HUD. Clicking outside closes. Esc closes.
  - Keyboard: sprite has role=button; Enter/Space toggles HUD.
- Acknowledge
  - Opening the HUD or clicking a relevant card performs an implicit “ack” (via spriteBus.acknowledge) to clear tone bias/alert overlays.
- Navigation
  - Clicking a card navigates to the corresponding route (`chat`, `habits`, `insights`, `vulnerability-watch`).
- Tooltip/Toast
  - HUD opening suppresses any visible sprite toast and clears the badge.

Accessibility
- Container role=dialog, aria-modal=false (non-blocking popover), labelled by title.
- Focus management: move focus to HUD container on open, return to sprite on close.
- Reduced motion: no scale/slide; fade-only animation.

---

## Layout & Positioning

- Anchor: sprite element with id `sara-sprite`.
- Position: fixed popover to the left of the sprite on desktop; on small screens, above sprite.
- Size: ~320px width (max 90vw), content in a simple grid (2x2 in desktop, stacked on mobile).
- Z-index: above sprite but below global modals; ensure it doesn’t overlap critical toasts.

---

## State Management

- Control: `Sprite.tsx` handles the open state (local) or lifts it to parent. Keep simple in Phase 1.
- Bus integration: on open, emit `spriteBus.acknowledge('hud:open')` to clear overlays/tone.
- Calm mode: if enabled, HUD still opens normally, but do not trigger celebratory visuals.

---

## Performance & Quality

- Defer data fetching to HUD open; abort on close/unmount.
- Avoid heavy lists; show at most the latest items (e.g., 1 insight).
- Use CSS transforms/opacity; avoid layout thrash; single repaint on open.
- Visibility guard: pause timers/intervals when HUD is closed.

---

## Telemetry

- Events
  - `hud_open` with reason (sprite_click/keyboard)
  - `hud_close` (esc/outside_click/nav)
  - `hud_card_click` with card id (now/you/brain/threat)
  - `ack_latency_ms` from last alert to hud_open
- Storage
  - Phase 1: console and local sampling; optional backend POST later.

---

## File Mapping & Responsibilities

- `frontend/src/components/SpriteHUD.tsx`
  - Popover container, 4 cards, basic fetch-on-open (Phase 1: placeholder content already scaffolded).
  - Props: `open`, `onClose`, `onNavigate`, `anchorId`.
- `frontend/src/components/Sprite.tsx`
  - Toggle HUD on click; clear toast/badge; call `onNavigate` via HUD.
  - Add aria-live region for sprite, keep HUD dialog semantics separate.
- `frontend/src/state/spriteBus.ts`
  - On HUD open, emit `ack` to clear overlays; optionally record ack metrics.
- `frontend/src/App-interactive.tsx`
  - Provide `onNavigate` to Sprite/SpriteHUD; ensure routes exist and scroll behaviors are consistent.

---

## Implementation Checklist

Phase 1 (1 pass)
- [ ] SpriteHUD: wire props, add close-on-outside/Esc, simple CSS transitions.
- [ ] Fetch on open: insights and vulnerability latest; minimal habits summary.
- [ ] Sprite.tsx: toggle HUD; aria-live stub; call `spriteBus.acknowledge`.
- [ ] App-interactive: pass `onNavigate`; keep behavior identical otherwise.
- [ ] Reduced motion: fade only; disable fancy transitions.

Phase 2 (polish)
- [ ] Preload data when sprite enters `thinking` (optional heuristic cache).
- [ ] SSE `/sprite/events` updates: hydrate HUD data in background.
- [ ] Dev tunables: quick view of sprite parameters inside HUD for testing.
- [ ] Preferences: remember last HUD tab/card open (if expanded view later).

---

## Copy & Microtext (initial)

- Title: “Sara — Quick HUD”
- Now: “Open Chat”
- You: “Habits & Streak” (show “Streak: X days” if available)
- Brain: “Latest Insight” (show the message or ‘No new insights’)
- Threat: “Vulnerability Watch” (show “All clear” or severity + counts)

Tone: concise, friendly, not jokey. Avoid implying mic recording.

---

## Risks & Mitigations

- Popover overlap with modals → constrain to left/top of sprite; elevate z-index only as needed.
- Data staleness → refresh on open; don’t auto-poll while closed.
- Performance dips → avoid large lists; keep DOM flat; suspend data when hidden.
- Accessibility gaps → audit with keyboard/reader early; keep roles/labels correct.

---

## Handoff Notes

- This spec assumes no backend changes for Phase 1.
- All heavy visuals remain gated by `enhancedVisuals` and reduced-motion preferences.
- The sprite remains the single entry point; HUD is additive, not a replacement for pages.


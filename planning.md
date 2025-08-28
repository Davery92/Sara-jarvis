# Web Sprite: Jarvis-Class Presence — Implementation Plan

This plan maps the design spec to your current repo, components, and services, detailing how to implement a rich, unmistakably Jarvis sprite without writing code yet. It aligns with your FastAPI backend and Vite + React + TypeScript frontend.

---

## Current Inventory (what exists today)

- Frontend sprite
  - `frontend/src/components/Sprite.tsx` with imperative handle: `setState`, `setMode`, `getMode`, `notify`, `clearBadge`, `pulse`.
  - States present: `idle`, `listening`, `thinking`, `speaking`, `notifying`.
  - Markup layers: `.halo`, `.core`, `.ring`, plus `badge`, `toast`, `tooltip`.
  - Personality classes: `mode-coach|analyst|companion|guardian|concierge|librarian`.
  - CSS: `frontend/src/components/sprite.css` (breathing, halo, swirl, pulse, toast, modes).
  - Placement: fixed bottom-right, responsive tweaks; keyboard activation; tooltip on hover.
- App integration
  - `frontend/src/App-interactive.tsx` references `Sprite` via `spriteRef`.
    - Wires to chat streaming (`/chat/stream` SSE-like) and calls `setState('listening'|'thinking'|'speaking'|'idle')`.
    - Uses `spriteRef.current?.notify` for welcome and autonomous insights; simple state pulsing.
    - Has `showToast` function that can route to chat/habits/vulnerability-watch.
  - `frontend/src/hooks/useActivityMonitor.ts` emits idle thresholds (`quickSweep`, `standardSweep`, `digestSweep`). Not yet mapped to sprite visuals.
- Backend signals
  - `backend/app/main_simple.py`:
    - `POST /chat/stream` streaming endpoint already emits incremental events; clients map to sprite `listening/thinking/speaking`.
    - Habit & insights endpoints: `/autonomous/insights`, `/workers/streak-alerts/{user_id}`, `/habits/*`.
    - Vulnerability endpoints: `/api/vulnerability-reports/*` (latest report + severity present in payloads).
  - `backend/app/services/vulnerability_notifications.py` (ntfy service) currently out-of-band; not wired to an in-app event channel.

---

## Goals Recap (from spec)

- Purpose: ambient, legible state (idle, listening, thinking) + attention cues (alert, celebrate), quick handle to open a compact HUD.
- Visual: three layers (core/body/halo), hue + energy + tempo; keep CSS fallback and add enhanced visuals behind a flag.
- Behavior: explicit state machine with smooth, interruptible transitions and cooldown on alert.
- Signals: chat streaming → thinking; notification → alert; habit streak milestones → celebrate; inactivity → calmer presence; critical vuln → serious accent.
- Interaction: hover tooltip; click to open mini-HUD; acknowledge clears bias; accessibility + reduced motion respected.
- Performance: 60fps budget, step-down on hidden tab/battery saver; telemetry for dwell/alerts.

---

## State Model (authoritative)

- Canonical states
  - `idle`: baseline breathing; neutral hue; low halo.
  - `listening`: subtle inward focus; ring scan; core calms.
  - `thinking`: increased tempo + inner plasma intensity; gentle orbital drift.
  - `alert`: brief halo flash pulses, overlays previous state with cooldown.
  - `celebrate`: short particle/spark burst; warm hue bloom; decays to prior state.
  - Compatibility: maintain existing `speaking`, `notifying` as sub‑modes overlaying base states.
- Parameters per state
  - `energy` (0–1), `tempo` (bpm), `hue/accent`, `bloom/rim`.
- Transition rules
  - Tween 150–450ms; `alert` snaps in then eases out; interruptible (`alert` overlays `thinking` and returns); cooldown 3–5s per source.

Implementation notes
- Represent state as `{ base: 'idle|listening|thinking', overlay?: 'alert|celebrate|speaking|notifying', tone?: 'neutral|focused|playful|serious' }` in a local event bus/hook.
- Map to DOM via CSS classes: `.sprite.idle|listening|thinking`, plus `.overlay-alert|overlay-celebrate` and `.tone-*` or reuse `mode-*` for brand tones.

---

## Visual System Mapping (to existing layers)

- Core (inner plasma)
  - Use `.core` gradients + `::before` swirl. Drive intensity via CSS variables: `--energy`, `--bloom`, `--saturation`.
  - Add hue control with CSS variables: `--hue`, `--accent` (or reuse `--blue-1/2` per mode/tone).
- Body (glassy orb)
  - Keep Fresnel feel using existing inner shadows; add micro-rotation and breathing scale tied to `--tempo`.
- Halo (outer field)
  - Existing `.halo` pulsing; extend with overlay classes:
    - `.overlay-alert`: sharp ring flash (border/intensity spike) 1–2 pulses.
    - `.overlay-celebrate`: sparkle/burst via radial ripple and small confetti sprites (CSS-only fallback); richer particles under enhanced visuals.
- Reduced motion
  - Gate heavy keyframes with `@media (prefers-reduced-motion: reduce)` to simplify to opacity/brightness fades and disable particle bursts.

---

## Triggers & Event Mapping (repo integration)

- Chat streaming → `thinking`
  - Already wired in `App-interactive.tsx` via `/chat/stream` events. Ensure transitions: `listening` on user send; escalate to `thinking` while tokens stream; briefly `speaking` at finalization; decay to `idle`.
- Notification events → `alert`
  - Current: `sprite.notify(message, { importance })`. Extend to also set overlay `alert` with severity: importance `high` → brighter, longer flash; cooldown per source key to avoid spam.
- Habit streak milestones → `celebrate`
  - Source: `/workers/streak-alerts/{user_id}` and `/habits/*` data; also surfaced as `autonomous/insights` (`reflection_streak`). On detection, trigger `celebrate` overlay.
- Inactivity → subtle presence
  - Use `useActivityMonitor` thresholds to scale `--tempo` down, reduce `--energy`, apply `.tone-neutral` fade; optional nudge after long idle via `notify` (low importance).
- Vulnerability severity → accent bias
  - Poll `/api/vulnerability-reports/latest` on an interval (or on route entry) and apply `.tone-serious` bias while “critical today” exists; clear on acknowledgement (click sprite or CTA).

Transport
- Phase 1: polling (reuse existing endpoints; keep simple).
- Phase 2: add SSE `/sprite/events` for low-latency pushes (see Backend Plan) with event types `{state, alert, celebrate, tone, clear}`.

---

## Interaction Design

- Hover: show minimal tooltip with current state or latest notification (already present). Ensure concise copy and contrast.
- Click / tap: opens compact HUD anchored to the sprite. Acknowledge clears accent bias and overlay, hides badge.
- Keyboard: keep `role="button"`, `Enter/Space` to activate; ensure focus ring.
- Aria-live: announce state changes at polite priority (e.g., “Sara is analyzing”, “New alert”).

---

## Placement & Layout

- Modes
  - Floating (default, current): bottom-right; sprite diameter 36–64px responsive.
  - Docked: optional compact size in header on small screens; provide prop/setting.
- Overflow: halo may overflow but must not overlap modals; raise z-index only for overlays.
- Persist size/position in local settings; allow drag in dev mode (later).

---

## Theming & Tone

- Tones
  - `neutral` (cool blue), `focused` (violet/indigo), `playful` (aqua/teal), `serious` (amber/red accent).
- Mapping
  - Reuse `mode-*` as defaults for brand personality; add `.tone-*` to bias hue when context demands (e.g., critical vuln → `.tone-serious`).
- Blending
  - Combine base mode + tone class; CSS variables compute final hues.

---

## Performance & Quality

- Feature flag: `enhancedVisuals` (local setting) enables particles/noise; otherwise use existing CSS-only visuals.
- Frame budget: prefer transform/opacity; avoid layout thrash; coalesce DOM writes via `requestAnimationFrame`.
- Thermal guard: when `document.hidden` or Battery API saver, reduce `--tempo`, disable particles, pause nonessential timers.
- Cooldowns: per-source cooldown registry to suppress repeated `alert` flashes.

---

## Telemetry & Tuning

- Client metrics (initial, local or posted to backend later)
  - `state_dwell_ms` per base state.
  - `alert_count` per type/day; `ack_latency_ms` from alert to click.
  - Performance sampling: `fps_estimate`, `hidden_time_ratio`.
- Dev tunables panel (dev-only route/flag)
  - Sliders: energy, tempo, bloom, hue; presets per state; save to localStorage.
- Preferences
  - Persist: size, position, visual quality, calm mode, tone bias opt-out.

---

## Accessibility & Privacy

- `prefers-reduced-motion`: reduce to calm visuals; disable particle bursts.
- `aria-live="polite"` region near sprite for state updates; ensure not chatty.
- Large hit area; tooltip contrast; keyboard access preserved.
- Never imply microphone capture; `listening` = awaiting input/focus only; include quick legend popover.
- “Calm Mode” toggle keeps visuals near idle while functional.

---

## Backend Plan (minimal touch, add later for polish)

Phase 1 (no new backend required)
- Poll existing endpoints:
  - Chat streaming already drives thinking.
  - `GET /autonomous/insights?limit=1` for celebration-worthy insights.
  - `GET /api/vulnerability-reports/latest` for serious tone bias.
  - Habit streak via `GET /habits/{habit_id}/streak` or use autonomous insights tags.

Phase 2 (SSE channel for sprite)
- New router `backend/app/routes/sprite.py` or extend `main_simple.py`:
  - `GET /sprite/events` (SSE): emits `{type: 'state'|'alert'|'celebrate'|'tone'|'clear', data: {...}}`.
  - Server-side cooldown and source tagging (`vuln:critical`, `habit:streak`, `system:notification`).
  - Optionally `POST /sprite/ack` to record acknowledgements.
- Security: standard auth dependency; CORS aligned with existing SSE.

---

## Frontend Plan (files and responsibilities)

- `frontend/src/components/Sprite.tsx`
  - Add overlay states `alert`, `celebrate` (non-destructive overlays on base state).
  - Add `tone` class application (`tone-neutral|focused|playful|serious`).
  - Add aria-live region and announcements; wire `prefers-reduced-motion` checks.
  - Expose new handle APIs: `alert(opts)`, `celebrate(opts)`, `setTone(tone)`, `acknowledge()`; maintain `notify` compatibility.
  - Respect global cooldown registry.
- `frontend/src/components/sprite.css`
  - Introduce CSS variables for `--tempo`, `--energy`, `--hue`, `--bloom`.
  - Overlay classes: `.overlay-alert` (sharp halo ring + flash), `.overlay-celebrate` (burst/sparkle), with reduced-motion fallbacks.
  - Tone classes: `.tone-neutral|focused|playful|serious` blending with existing `mode-*`.
  - Media queries for reduced motion; ensure toast/tooltip contrast.
- New: `frontend/src/components/SpriteHUD.tsx`
  - Compact HUD anchored to sprite: Now/You/Brain/Threat cards, reusing existing views’ components or summaries.
  - Exposes `open/close`; sprite click toggles this.
- New: `frontend/src/state/spriteBus.ts`
  - Lightweight event bus (Subject/EventEmitter) for `{ setBase, setOverlay, setTone, alert, celebrate, clear, ack }` events.
  - Centralized cooldown + deduplication per source.
- New: `frontend/src/hooks/useSpriteState.ts`
  - Hook to subscribe to `spriteBus` and compute effective classes/variables; provides dwell telemetry.
- `frontend/src/App-interactive.tsx`
  - Replace direct `setState` chains with `spriteBus` calls.
  - On `/chat/stream`: map events to `spriteBus.setBase('listening'|'thinking')`, overlay `speaking` on final token, decay to `idle`.
  - Wire `useActivityMonitor` to adjust `--tempo`/`--energy` (or add `.low-activity` class) via `spriteBus`.
  - On insights/vuln notifications: emit `alert` with importance; use `celebrate` for celebration-worthy insights.
- `frontend/src/config.ts`
  - Add `featureFlags: { enhancedVisuals: boolean, calmMode: boolean }`; read from localStorage; expose toggles.
- `frontend/src/pages/Settings.tsx`
  - Add toggles for Visual Quality (enhanced visuals), Calm Mode, Sprite Size.

Enhanced visuals (phase-gated)
- Optional `Canvas/WebGL` halo particles in a background canvas element positioned behind `.halo`; feature-flagged; autoplay off on battery saver or hidden tab.

---

## Event and Transition Details

- Overlay precedence: `alert` > `celebrate` > `speaking` > `notifying`. New overlays preempt existing if not on cooldown; otherwise queued or ignored.
- Decay: `alert` auto-clears in ~900ms; `celebrate` in ~1200–1500ms; return to previous base state.
- Interruptibility: Base state changes do not clear active overlay unless explicitly higher precedence.
- Cooldowns: Per type (e.g., `alert:vuln` 5s; `alert:notification` 3s). Store `lastFiredAt` map in `spriteBus`.

---

## Data & Signal Sources (concrete)

- Chat stream: `POST /chat/stream` — existing; already parsed in frontend.
- Autonomous insights: `GET /autonomous/insights?limit=1` — look for types: `reflection_streak`, `habit_*`, `security_alert`.
- Vulnerability reports: `GET /api/vulnerability-reports/latest` — if `severity` high/critical or KEV present → apply `.tone-serious` until user acknowledges.
- Habit streak: `GET /habits/{habit_id}/streak` or use insights that contain streak meta; also `/workers/streak-alerts/{user_id}` for manual triggering in dev.

---

## QA Plan

- Visual correctness: verify base state breathing, listening ring, thinking pulse, speaking ripples, alert flash, celebrate burst across desktop/mobile and reduced-motion.
- Behavior correctness: state transitions timing; interruptibility; cooldown enforcement; overlay precedence; badge/tooltip behaviors.
- Interaction: click toggles HUD; keyboard activation; aria-live messages fire appropriately and sparingly.
- Performance: monitor smoothness during chat streaming; hidden tab throttling; battery saver reduction; no layout thrashing.
- Accessibility: contrast for tooltip/toast; focus rings; screen reader announcements; hit area size.

---

## Rollout & Telemetry

- Phase 1 (Foundations)
  - Implement base/overlay/tone classes, cooldowns; wire chat/insights/vuln/inactivity polling; minimal HUD.
  - Telemetry: local console + optional backend POST later; feature flags in Settings.
- Phase 2 (Intelligence & polish)
  - Add `listening` pre-voice state refinements; severity-aware tones; SSE `/sprite/events`; dev tunables panel; persist preferences.
- Phase 3 (Expressiveness)
  - Particle halo modes and micro-physics; pointer proximity; tone-aware themes tied to contextual awareness.

Success criteria
- At-a-glance activity legibility; alerts draw attention once and are easy to acknowledge; feels alive but not distracting; clicked several times per session; graceful on mobile; honors accessibility.

---

## Implementation Checklist (by file)

Frontend
- [ ] `src/components/Sprite.tsx`: add overlay/tone APIs; aria-live; acknowledge; prefers-reduced-motion guards.
- [ ] `src/components/sprite.css`: variables for energy/tempo/hue/bloom; overlay classes `.overlay-alert`, `.overlay-celebrate`; `.tone-*`; reduced motion rules.
- [ ] `src/components/SpriteHUD.tsx` (new): mini-HUD anchored to sprite; reuse existing cards.
- [ ] `src/state/spriteBus.ts` (new): event bus + cooldown registry.
- [ ] `src/hooks/useSpriteState.ts` (new): subscribe + compute classes; dwell telemetry.
- [ ] `src/App-interactive.tsx`: refactor to use bus; wire `useActivityMonitor` to tempo/energy; map autonomous insights to alert/celebrate; add vuln tone bias.
- [ ] `src/config.ts`: feature flags; persistence helpers.
- [ ] `src/pages/Settings.tsx`: toggles (Enhanced visuals, Calm mode, Size).

Backend (Phase 1 optional, Phase 2 recommended)
- [ ] Phase 1: none required (poll existing endpoints as above).
- [ ] Phase 2: `app/routes/sprite.py` or extend `main_simple.py` with `GET /sprite/events` SSE; optional `POST /sprite/ack`.

Testing
- [ ] Manual: verify transitions, overlays, tooltips, HUD open/close, reduced motion.
- [ ] Integration script: extend a root `test_*.py` to exercise chat streaming and poll endpoints while checking client-visible state via logs or test harness hooks.

Notes
- Keep existing CSS sprite as the default/fallback; enhanced visuals opt-in.
- Do not imply mic usage; label listening as “awaiting input”.
- Store bias/tone until explicit acknowledgement (click/CTA) or backend confirms resolution.

---

## Risks & Mitigations

- Overly busy visuals → add Calm Mode and reduced-motion pathways; cap energy/tempo.
- Performance regressions → feature flag heavy effects; throttle updates; guard on `document.hidden`/Battery API.
- Alert spam → per-source cooldown registry; dedupe identical messages.
- Accessibility regressions → test with screen readers; avoid live region spam; keep large hit area.

---

## Next Steps

- Confirm file/API naming and tone color tokens.
- Prioritize Phase 1 checklist; schedule ~1–2 days for implementation + polish.
- After Phase 1 ships, instrument telemetry and enable Phase 2 SSE.


# Sara Web Design Language

The thesis: **Sara is the interface, not a tab in it.** The app is an assistant that
renders surfaces, not an admin dashboard. Every rule below follows from that.
The Home view (`components/shell/DashboardHomeView.tsx`) is the reference
implementation — when in doubt, match it.

## Layout

- **Maximum one level of containment.** Sections are separated by whitespace and a
  small heading, never by nested bordered boxes. A bordered/filled container may
  appear only around a discrete *object* (one email row, one event, the composer) —
  never as page scaffolding. Avoid `.assistant-panel` / `.assistant-panel-soft` /
  `.assistant-panel-muted` (the boxed look being removed) unless that single
  containment level is genuinely earned.
- **Page headers are one slim row** (~48px): title + live state inline, actions on the
  right. No kicker-above-title stacks, no description sentences, no chip rows.
  Example: `Calendar · 3 events today` + [Week|Month] + [+ New event].
- **Reading measure:** long-form text columns cap at ~70–75ch (`max-w-[740px]` or
  `max-w-[75ch]`), centered in the available space.
- Lists are flat rows with `hover:bg-white/[0.04]` and spacing, not stacked cards.

## Type scale

Data is big, labels are small — never the reverse.

- Page title: `font-display text-xl font-semibold text-white`
- Hero/greeting (rare): `font-display text-3xl`
- Section heading: `text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400`
- Body / row primary: `text-[15px] text-slate-200` (secondary `text-slate-300`)
- Metadata: `text-xs text-slate-500` — metadata ONLY, never primary content
- Numbers worth glancing at (counts, temps, times) get the larger size, their labels
  get the kicker treatment.

## Color discipline

Palette is unchanged (bg `#050b16`/`#08111f`, teal accent, slate text). Spend it precisely:

- **Teal = Sara acting + the single primary action per screen.** Nothing else.
- **Status colors appear only as a 2px left border** (`border-l-2 border-amber-400/70`
  etc.) on the affected row — never full-bleed green/red fills.
- **Destructive actions are quiet**: ghost text button or inside a `⋯` overflow menu,
  never the most colorful element on screen. Confirm via dialog, color appears there.
- Counts/badges: neutral slate chips; alarming numbers cap at `99+`.

## Copy

- **No self-referential copy.** Anything describing the UI to the user
  ("Keep the schedule readable…", "Review the inbox, inspect a message…",
  "Primary surfaces stay close…") is deleted on sight. Headers earn space with
  state ("19 unread · synced 4:50 PM") or say nothing.
- **No raw machine output in user-facing surfaces** — no URLs-as-text, payload dumps,
  UUIDs, or `ERROR: http 422 {...}`. Summarize in a human sentence; tuck raw detail
  behind a `▾ details` expander. (Exception: the ACS page is an intentional console.)
- Empty states are one quiet sentence (`text-sm text-slate-500`), no oversized icons,
  and never two empty states visible at once.

## Components

- Quiet link/action: `text-xs text-slate-500 hover:text-teal-300 transition-colors`
- Primary button (one per screen): `rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm
  font-medium text-slate-950 hover:bg-teal-300`
- Secondary button: `rounded-xl border border-white/10 px-3.5 py-2 text-sm
  text-slate-300 hover:bg-white/[0.06] hover:text-white`
- Inputs: flat — `bg-white/[0.04] border border-white/10 rounded-xl
  focus:border-teal-300/30 outline-none`, no glow stacks
- Toasts/banners (already done): dark card, 2px colored left edge, capped stack,
  auto-dismiss. Never reintroduce full-color toasts.

## iOS (React Native) mapping

The iOS app (`ios-app/`) is the same brand. All tokens live in
`ios-app/src/styles/theme.ts` and mirror the web palette — never hardcode colors in
components or native target configs. Rule translations:

- Kicker heading: `fontSize: 11, fontWeight: '600', letterSpacing: 1.6,
  textTransform: 'uppercase', color: colors.textSecondary`
- Body / row primary: `fontSize: 15, color: '#e2e8f0'`; metadata `fontSize: 12,
  color: colors.textMuted`
- Flat sections over widget cards: section = kicker + content separated by
  `spacing.xl`, no `backgroundColor`/`borderWidth` wrappers. Cards only for discrete
  objects, with `borderColor: colors.border` hairlines, no fills + borders + shadows
  stacked.
- Status = 3px `borderLeftWidth` on the affected row, never a filled banner.
- Teal (`colors.primary`) = Sara acting + one primary action per screen; everything
  else slate.
- Screens reachable from the "More" drawer are secondary surfaces — they still follow
  the language but never add tabs.

## Hard constraints

- This is a **restyle/restructure, not a behavior rewrite**: every prop, handler,
  endpoint call, and piece of state survives. If a feature has no home in the new
  layout, demote it (overflow menu, expander) — don't delete it.
- Don't edit shared infrastructure: `index.css`, `tailwind.config.js`,
  `App-interactive.tsx`, `ShellWorkspaceContent.tsx`, `ShellNavigation.tsx`,
  `ShellHeader.tsx`, `ToastStack.tsx`, or another view's files.
- Tailwind utility classes only; no new CSS files, no inline style objects unless the
  file already uses them for dynamic values.
- Keep mobile working: existing responsive breakpoints (`md:` etc.) must remain
  sensible; single-column collapse is the default answer on small screens.

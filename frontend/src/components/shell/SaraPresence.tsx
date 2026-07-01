import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { APP_CONFIG } from '../../config'

/**
 * SaraPresence — a live, always-visible presence chip for the shell header.
 *
 * This is the web half of the "make Sara feel present" work (P0.3). It surfaces
 * the daemon's real state — which previously only existed three taps deep on the
 * ACS page — right in the header, and makes it *react* the moment Sara does
 * something notable (sets a focus, reaches out). Clicking opens a lightweight
 * "what Sara's doing now" popover so the detail is one glance away, no navigation.
 *
 * Data sources (all already exist):
 *   - GET  /api/acs/v2/daemon-status  (poll)   liveness + state
 *   - GET  /api/acs/v2/focus          (poll)   current focus topic + why
 *   - GET  /api/sara/status           (poll)   emotional state + latest thought
 *   - GET  /api/acs/v2/stream         (SSE)    live activity → transient reactions
 */

// ── Types (mirror the v2 endpoints) ───────────────────────────────────────────

interface DaemonStatus {
  state: string
  version: string
  is_alive: boolean
  last_heartbeat_at: string | null
  last_tick_summary: string | null
  seconds_since_heartbeat: number | null
}

interface Focus {
  topic: string | null
  why: string | null
  set_at: string | null
}

interface SaraStatus {
  emotional_state: string
  latest_thought: string | null
  watching_for: string[]
}

interface Activity {
  id: string
  created_at: string
  kind: string
  summary: string
}

// ── Presence model ─────────────────────────────────────────────────────────────

type PresenceTone = {
  label: string
  dot: string // tailwind bg-* for the status dot
  ring: string // tailwind ring/glow color for the chip when active
  pulse: boolean
  emphatic?: boolean // stronger animation for "she just noticed" moments
}

// Base presence derived from the daemon's reported lifecycle state.
function basePresence(daemon: DaemonStatus | null): PresenceTone {
  if (!daemon || daemon.state === 'never_started') {
    return { label: 'offline', dot: 'bg-zinc-500', ring: 'ring-zinc-500/0', pulse: false }
  }
  if (!daemon.is_alive) {
    return { label: 'asleep', dot: 'bg-zinc-500', ring: 'ring-zinc-500/0', pulse: false }
  }
  switch (daemon.state) {
    case 'working':
    case 'thinking':
      return { label: 'thinking', dot: 'bg-indigo-400', ring: 'ring-indigo-400/40', pulse: true }
    case 'reflecting':
      return { label: 'reflecting', dot: 'bg-violet-400', ring: 'ring-violet-400/40', pulse: true }
    case 'sleeping':
      return { label: 'resting', dot: 'bg-sky-500', ring: 'ring-sky-500/20', pulse: false }
    case 'boot':
      return { label: 'waking', dot: 'bg-emerald-400', ring: 'ring-emerald-400/30', pulse: true }
    case 'error':
      return { label: 'stuck', dot: 'bg-red-500', ring: 'ring-red-500/40', pulse: true }
    default:
      return { label: 'here', dot: 'bg-emerald-400', ring: 'ring-emerald-400/20', pulse: true }
  }
}

// A recent activity event briefly overrides the base presence — this is what
// makes Sara feel alive: you *see* her notice something before any notification.
function reactionPresence(kind: string): PresenceTone | null {
  switch (kind) {
    case 'thought':
    case 'reflection':
      return { label: 'thinking', dot: 'bg-indigo-400', ring: 'ring-indigo-400/50', pulse: true }
    case 'tool_call':
    case 'tool_result':
      return { label: 'working', dot: 'bg-fuchsia-400', ring: 'ring-fuchsia-400/50', pulse: true }
    case 'focus_set':
      return { label: 'noticed something', dot: 'bg-sky-400', ring: 'ring-sky-400/60', pulse: true, emphatic: true }
    case 'notify_david':
      return { label: 'reaching out', dot: 'bg-amber-400', ring: 'ring-amber-400/70', pulse: true, emphatic: true }
    case 'inbox_pickup':
      return { label: 'picking it up', dot: 'bg-cyan-400', ring: 'ring-cyan-400/50', pulse: true }
    default:
      return null
  }
}

const EMOTION: Record<string, { emoji: string; label: string }> = {
  curious:    { emoji: '🤔', label: 'curious' },
  calm:       { emoji: '😌', label: 'calm' },
  alert:      { emoji: '⚡', label: 'alert' },
  concerned:  { emoji: '😟', label: 'concerned' },
  happy:      { emoji: '😊', label: 'happy' },
  content:    { emoji: '🙂', label: 'content' },
  focused:    { emoji: '🎯', label: 'focused' },
  excited:    { emoji: '✨', label: 'excited' },
  tired:      { emoji: '😴', label: 'tired' },
  neutral:    { emoji: '•',  label: 'steady' },
}

function emotion(state: string | undefined): { emoji: string; label: string } {
  return EMOTION[(state || 'neutral').toLowerCase()] || { emoji: '•', label: state || 'steady' }
}

// Small subset of the ACS kind styles, for the popover's recent-activity rows.
const KIND_PILL: Record<string, string> = {
  thought:        'bg-indigo-500/15 border-indigo-500/30 text-indigo-200',
  reflection:     'bg-violet-500/15 border-violet-500/30 text-violet-200',
  focus_set:      'bg-sky-500/15 border-sky-500/30 text-sky-200',
  notify_david:   'bg-amber-500/15 border-amber-500/30 text-amber-200',
  tool_call:      'bg-fuchsia-500/15 border-fuchsia-500/30 text-fuchsia-200',
  tool_result:    'bg-fuchsia-500/15 border-fuchsia-500/30 text-fuchsia-300',
  inbox_pickup:   'bg-cyan-500/15 border-cyan-500/30 text-cyan-200',
  inbox_complete: 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300',
  error:          'bg-red-500/15 border-red-500/30 text-red-300',
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'now'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

const REACTION_MS = 9000 // how long a transient reaction holds before reverting

// ── Component ────────────────────────────────────────────────────────────────

export default function SaraPresence() {
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [status, setStatus] = useState<SaraStatus | null>(null)
  const [recent, setRecent] = useState<Activity[]>([])
  const [reaction, setReaction] = useState<{ tone: PresenceTone; at: number } | null>(null)
  const [open, setOpen] = useState(false)
  const [, setTick] = useState(0)

  const reactionTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      const [d, f, s] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/daemon-status`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/focus`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/sara/status`, { credentials: 'include' }),
      ])
      if (d.ok) setDaemon(await d.json())
      if (f.ok) setFocus(await f.json())
      if (s.ok) setStatus(await s.json())
    } catch {
      /* transient; keep last good state */
    }
  }, [])

  // Seed the recent-activity list once (SSE only delivers go-forward events).
  const seedRecent = useCallback(async () => {
    try {
      const r = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/activity?limit=5`, { credentials: 'include' })
      if (r.ok) setRecent(await r.json())
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    fetchAll()
    seedRecent()
    const poll = setInterval(fetchAll, 8000)
    const rerender = setInterval(() => setTick((t) => t + 1), 1000)
    return () => { clearInterval(poll); clearInterval(rerender) }
  }, [fetchAll, seedRecent])

  // Live activity feed → transient reactions + recent list.
  useEffect(() => {
    const es = new EventSource(`${APP_CONFIG.apiUrl}/api/acs/v2/stream`, { withCredentials: true })
    es.addEventListener('activity', (ev) => {
      let entry: Activity
      try {
        entry = JSON.parse((ev as MessageEvent).data) as Activity
      } catch {
        return
      }
      setRecent((prev) => (prev.some((a) => a.id === entry.id) ? prev : [entry, ...prev].slice(0, 5)))
      const tone = reactionPresence(entry.kind)
      if (tone) {
        setReaction({ tone, at: Date.now() })
        if (reactionTimer.current) clearTimeout(reactionTimer.current)
        reactionTimer.current = setTimeout(() => setReaction(null), REACTION_MS)
      }
    })
    es.onerror = () => { /* browser auto-reconnects */ }
    return () => { es.close() }
  }, [])

  // Close popover on outside click / Escape.
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const base = useMemo(() => basePresence(daemon), [daemon])
  const active = reaction?.tone ?? base
  const emo = emotion(status?.emotional_state)
  const name = APP_CONFIG.assistantName || 'Sara'

  // When idle, the chip shows the emotional tone; when active, it shows what she's doing.
  const chipLabel = reaction ? active.label : (daemon?.is_alive ? emo.label : active.label)

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        title={`${name} — ${active.label}`}
        className={`flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-300 transition hover:bg-white/[0.06] ring-1 ${active.ring}`}
      >
        <span className="relative flex h-2 w-2">
          {active.pulse && (
            <span
              className={`absolute inline-flex h-full w-full rounded-full opacity-60 ${active.dot} ${active.emphatic ? 'animate-ping' : 'animate-pulse'}`}
            />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${active.dot}`} />
        </span>
        <span className="font-medium text-slate-200">{name}</span>
        <span className="max-w-[18ch] truncate text-slate-400">{chipLabel}</span>
        <span aria-hidden>{emo.emoji}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 max-w-none rounded-xl border border-white/10 bg-[#0e1116] p-3 text-left shadow-2xl shadow-black/40">
          {/* max-w-none: the global `max-width:100%` reset otherwise caps this
              popover to 100% of its narrow (~124px) relative parent, collapsing
              w-80 and wrapping all content into a tall, cramped column. */}
          {/* Header */}
          <div className="flex items-center gap-2 border-b border-white/8 pb-2">
            <span className={`h-2.5 w-2.5 rounded-full ${active.dot} ${active.pulse ? 'animate-pulse' : ''}`} />
            <span className="text-sm font-semibold text-slate-100">{name} is {active.label}</span>
            <span className="ml-auto text-base" aria-hidden>{emo.emoji}</span>
          </div>

          {/* Right now / focus */}
          <div className="pt-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Right now</div>
            {focus?.topic ? (
              <>
                <div className="text-sm text-slate-100">{focus.topic}</div>
                {focus.why && <div className="mt-0.5 text-xs italic text-slate-400">{focus.why}</div>}
              </>
            ) : (
              <div className="text-sm italic text-slate-500">
                {daemon?.last_tick_summary || 'between things'}
              </div>
            )}
          </div>

          {/* Latest thought */}
          {status?.latest_thought && (
            <div className="pt-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Latest thought</div>
              <div className="text-xs text-slate-300">{status.latest_thought}</div>
            </div>
          )}

          {/* Recent activity */}
          <div className="pt-2">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Recent</div>
            {recent.length === 0 ? (
              <div className="text-xs italic text-slate-500">quiet for now</div>
            ) : (
              <ul className="space-y-1">
                {recent.slice(0, 3).map((a) => (
                  <li key={a.id} className="flex items-start gap-2">
                    <span
                      className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide ${
                        KIND_PILL[a.kind] || 'bg-zinc-500/15 border-zinc-500/30 text-zinc-300'
                      }`}
                    >
                      {a.kind.replace('_', ' ')}
                    </span>
                    <span className="flex-1 text-xs text-slate-300">{a.summary}</span>
                    <span className="shrink-0 text-[10px] text-slate-500">{timeAgo(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {!daemon?.is_alive && (
            <div className="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
              Daemon hasn't checked in
              {daemon?.seconds_since_heartbeat != null ? ` for ${timeAgo(daemon.last_heartbeat_at)}` : ''}.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

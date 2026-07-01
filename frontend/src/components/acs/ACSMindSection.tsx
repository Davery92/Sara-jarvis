import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { APP_CONFIG } from '../../config'

// ── Types matching the v2 endpoints ──────────────────────────────────────────

interface DaemonStatus {
  state: string
  version: string
  pid: number | null
  hostname: string | null
  started_at: string | null
  last_heartbeat_at: string | null
  last_tick_summary: string | null
  is_alive: boolean
  seconds_since_heartbeat: number | null
}

interface Focus {
  topic: string | null
  why: string | null
  set_at: string | null
  updated_at: string | null
}

interface InboxItem {
  id: string
  created_at: string
  created_by: string
  urgency: 'low' | 'normal' | 'high'
  prompt: string
  context: string | null
  status: 'queued' | 'in_progress' | 'done' | 'dismissed'
  picked_up_at: string | null
  completed_at: string | null
  completion_summary: string | null
}

interface Activity {
  id: string
  created_at: string
  kind: string
  summary: string
  body: string | null
  tags: string[]
  metadata: Record<string, unknown>
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'just now'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function uptime(startedAt: string | null | undefined): string {
  if (!startedAt) return '—'
  const ms = Date.now() - new Date(startedAt).getTime()
  if (ms < 0) return '—'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ${m % 60}m`
  return `${Math.floor(h / 24)}d ${h % 24}h`
}

// Quiet kind chips: tiny mono uppercase, color on text/border only — no fills.
const KIND_STYLES: Record<string, { label: string; chip: string }> = {
  boot:           { label: 'boot',     chip: 'border-emerald-400/30 text-emerald-300' },
  shutdown:       { label: 'shutdown', chip: 'border-white/15 text-slate-400' },
  thought:        { label: 'thought',  chip: 'border-indigo-400/30 text-indigo-300' },
  reflection:     { label: 'reflect',  chip: 'border-violet-400/30 text-violet-300' },
  focus_set:      { label: 'focus',    chip: 'border-sky-400/30 text-sky-300' },
  focus_clear:    { label: 'unfocus',  chip: 'border-sky-400/30 text-sky-300' },
  notify_david:   { label: 'notified', chip: 'border-amber-400/30 text-amber-300' },
  inbox_pickup:   { label: 'pickup',   chip: 'border-cyan-400/30 text-cyan-300' },
  inbox_complete: { label: 'done',     chip: 'border-emerald-400/30 text-emerald-300' },
  inbox_dismiss:  { label: 'dismiss',  chip: 'border-orange-400/30 text-orange-300' },
  tool_call:      { label: 'tool',     chip: 'border-fuchsia-400/30 text-fuchsia-300' },
  tool_result:    { label: 'result',   chip: 'border-fuchsia-400/30 text-fuchsia-300' },
  external_event: { label: 'event',    chip: 'border-white/15 text-slate-400' },
  error:          { label: 'error',    chip: 'border-rose-400/40 text-rose-300' },
}

const URGENCY_STYLES: Record<string, string> = {
  high:   'border-rose-400/40 text-rose-300',
  normal: 'border-white/15 text-slate-400',
  low:    'border-white/10 text-slate-500',
}

function SectionHeading({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</h2>
      {action}
    </div>
  )
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ACSMindSection() {
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [inbox, setInbox] = useState<InboxItem[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedActivity, setExpandedActivity] = useState<Set<string>>(new Set())
  const [, setTick] = useState(0) // re-render once a second so timeAgo refreshes

  // New-inbox-item form
  const [newPrompt, setNewPrompt] = useState('')
  const [newUrgency, setNewUrgency] = useState<'low' | 'normal' | 'high'>('normal')
  const [submitting, setSubmitting] = useState(false)

  const fetchAll = useCallback(async () => {
    try {
      const [d, f, i, a] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/daemon-status`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/focus`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/inbox?limit=20`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/activity?limit=50`, { credentials: 'include' }),
      ])
      if (d.ok) setDaemon(await d.json()); else throw new Error('daemon-status failed')
      if (f.ok) setFocus(await f.json())
      if (i.ok) setInbox(await i.json())
      if (a.ok) setActivity(await a.json())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  // Daemon-status / focus / inbox still poll; activity gets a live SSE feed.
  useEffect(() => {
    fetchAll()
    const refresh = setInterval(fetchAll, 8000)
    const reRender = setInterval(() => setTick((t) => t + 1), 1000)
    return () => { clearInterval(refresh); clearInterval(reRender) }
  }, [fetchAll])

  const sseRef = useRef<EventSource | null>(null)
  useEffect(() => {
    const es = new EventSource(`${APP_CONFIG.apiUrl}/api/acs/v2/stream`, { withCredentials: true })
    sseRef.current = es
    es.addEventListener('activity', (ev) => {
      try {
        const entry = JSON.parse((ev as MessageEvent).data) as Activity
        setActivity((prev) => {
          if (prev.some((a) => a.id === entry.id)) return prev
          return [entry, ...prev].slice(0, 50)
        })
      } catch { /* ignore */ }
    })
    es.onerror = () => {
      // Browser will auto-reconnect; nothing to do.
    }
    return () => {
      es.close()
      sseRef.current = null
    }
  }, [])

  const submitInbox = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newPrompt.trim() || submitting) return
    setSubmitting(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/inbox`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: newPrompt.trim(),
          urgency: newUrgency,
          created_by: 'david_web',
        }),
      })
      if (!res.ok) throw new Error('queue failed')
      setNewPrompt('')
      setNewUrgency('normal')
      await fetchAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to queue')
    } finally {
      setSubmitting(false)
    }
  }

  const toggleActivity = (id: string) => {
    setExpandedActivity((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const livenessLabel = useMemo(() => {
    if (!daemon) return { text: 'unknown', color: 'text-slate-500', dot: 'bg-slate-500' }
    if (daemon.state === 'never_started') return { text: 'never started', color: 'text-slate-500', dot: 'bg-slate-500' }
    if (!daemon.is_alive) return { text: 'dead', color: 'text-rose-400', dot: 'bg-rose-500' }
    if (daemon.state === 'thinking') return { text: 'thinking', color: 'text-indigo-300', dot: 'bg-indigo-400' }
    if (daemon.state === 'reflecting') return { text: 'reflecting', color: 'text-violet-300', dot: 'bg-violet-400' }
    return { text: 'alive', color: 'text-emerald-400', dot: 'bg-emerald-400' }
  }, [daemon])

  if (loading && !daemon) return <div className="p-4 text-sm text-slate-500">Loading…</div>
  if (error && !daemon) return <div className="p-4 text-sm text-rose-400">{error}</div>

  return (
    <div>
      {/* ── Header: title + liveness inline ─────────────────── */}
      <div className="flex min-h-[48px] flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="font-display text-xl font-semibold text-white">Sara's mind</h1>
        <span className="flex items-center gap-2 text-sm">
          <span className={`h-2 w-2 rounded-full ${livenessLabel.dot} ${daemon?.is_alive ? 'animate-pulse' : ''}`} />
          <span className={livenessLabel.color}>{livenessLabel.text}</span>
          <span className="text-slate-500">
            {daemon?.version && <>· v{daemon.version} </>}
            · tick {daemon?.last_heartbeat_at ? timeAgo(daemon.last_heartbeat_at) : '—'}
          </span>
        </span>
      </div>

      {/* ── Status: one compact definition row ──────────────── */}
      <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1.5">
        <span className="flex items-baseline gap-1.5">
          <span className="text-xs text-slate-500">host</span>
          <span className="font-mono text-sm text-slate-200">{daemon?.hostname || '—'}</span>
        </span>
        <span className="flex items-baseline gap-1.5">
          <span className="text-xs text-slate-500">pid</span>
          <span className="font-mono text-sm text-slate-200">{daemon?.pid ?? '—'}</span>
        </span>
        <span className="flex items-baseline gap-1.5">
          <span className="text-xs text-slate-500">uptime</span>
          <span className="font-mono text-sm text-slate-200">{uptime(daemon?.started_at)}</span>
        </span>
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="text-xs text-slate-500">last tick</span>
          <span className="max-w-[28rem] truncate font-mono text-sm text-slate-200" title={daemon?.last_tick_summary || ''}>
            {daemon?.last_tick_summary || '—'}
          </span>
        </span>
      </div>

      {/* ── Focus ────────────────────────────────────────────── */}
      <section className="mt-10">
        <SectionHeading
          label="Current focus"
          action={focus?.set_at ? <span className="text-xs text-slate-500">set {timeAgo(focus.set_at)}</span> : undefined}
        />
        {focus?.topic ? (
          <>
            <div className="text-[15px] text-slate-200">{focus.topic}</div>
            {focus.why && <div className="mt-1 text-xs text-slate-500">{focus.why}</div>}
          </>
        ) : (
          <p className="text-sm text-slate-500">Between things.</p>
        )}
      </section>

      {/* ── Queue ────────────────────────────────────────────── */}
      <section className="mt-10">
        <SectionHeading
          label="Queue"
          action={<span className="text-xs text-slate-500">{inbox.length} active</span>}
        />

        {/* New-item form */}
        <form onSubmit={submitInbox} className="mb-4 flex gap-2">
          <input
            type="text"
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            placeholder="Queue something for Sara…"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
          />
          <select
            value={newUrgency}
            onChange={(e) => setNewUrgency(e.target.value as 'low' | 'normal' | 'high')}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-2 py-2 text-sm text-slate-300 outline-none focus:border-teal-300/30"
          >
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
          <button
            type="submit"
            disabled={!newPrompt.trim() || submitting}
            className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300 disabled:opacity-40"
          >
            Queue
          </button>
        </form>

        {/* Item list */}
        {inbox.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing queued for her.</p>
        ) : (
          <ul className="space-y-2">
            {inbox.map((item) => (
              <li
                key={item.id}
                className={`rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 ${
                  item.urgency === 'high' ? 'border-l-2 border-l-rose-400/70' : ''
                }`}
              >
                <div className="flex items-baseline gap-2">
                  <span className={`rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wide ${URGENCY_STYLES[item.urgency] || URGENCY_STYLES.normal}`}>
                    {item.urgency}
                  </span>
                  <span className={`rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wide ${
                    item.status === 'in_progress'
                      ? 'border-cyan-400/30 text-cyan-300'
                      : 'border-white/15 text-slate-400'
                  }`}>
                    {item.status === 'in_progress' ? 'in progress' : 'queued'}
                  </span>
                  <span className="ml-auto text-xs text-slate-500">{timeAgo(item.created_at)}</span>
                </div>
                <div className="mt-1.5 text-[15px] text-slate-200">{item.prompt}</div>
                {item.context && <div className="mt-1 text-xs text-slate-500">{item.context}</div>}
                <div className="mt-1 font-mono text-xs text-slate-500">id={item.id.slice(0, 8)} · from {item.created_by}</div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Activity feed ────────────────────────────────────── */}
      <section className="mt-10">
        <SectionHeading
          label="Activity"
          action={<span className="text-xs text-slate-500">last {activity.length}</span>}
        />
        {activity.length === 0 ? (
          <p className="text-sm text-slate-500">No activity yet.</p>
        ) : (
          <ul className="space-y-0.5">
            {activity.map((a) => {
              const style = KIND_STYLES[a.kind] || KIND_STYLES.external_event
              const expanded = expandedActivity.has(a.id)
              const hasBody = !!a.body && a.body.trim().length > 0
              return (
                <li key={a.id}>
                  <button
                    onClick={() => hasBody && toggleActivity(a.id)}
                    className={`flex w-full items-start gap-3 rounded-md px-2 py-1.5 text-left transition-colors ${hasBody ? 'cursor-pointer hover:bg-white/[0.04]' : 'cursor-default hover:bg-white/[0.04]'}`}
                  >
                    <span className={`mt-0.5 w-[4.5rem] shrink-0 rounded border px-1.5 py-px text-center font-mono text-[10px] uppercase tracking-wide ${style.chip}`}>
                      {style.label}
                    </span>
                    <span className="min-w-0 flex-1 text-sm text-slate-200">{a.summary}</span>
                    {hasBody && (
                      <span className="mt-0.5 shrink-0 text-xs text-slate-600">{expanded ? '▾' : '▸'}</span>
                    )}
                    <span className="mt-0.5 w-16 shrink-0 text-right text-xs tabular-nums text-slate-500">{timeAgo(a.created_at)}</span>
                  </button>
                  {expanded && hasBody && (
                    <div className="mb-1 ml-[5.25rem] whitespace-pre-wrap border-l border-white/8 py-1 pl-3 font-mono text-xs text-slate-500">
                      {a.body}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {error && <div className="mt-4 text-xs text-rose-400">{error}</div>}
    </div>
  )
}

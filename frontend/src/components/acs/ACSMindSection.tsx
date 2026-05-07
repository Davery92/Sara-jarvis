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

const KIND_STYLES: Record<string, { label: string; pill: string; text: string }> = {
  boot:           { label: 'boot',     pill: 'bg-emerald-500/15 border-emerald-500/30', text: 'text-emerald-300' },
  shutdown:       { label: 'shutdown', pill: 'bg-zinc-500/15 border-zinc-500/30',       text: 'text-zinc-300' },
  thought:        { label: 'thought',  pill: 'bg-indigo-500/15 border-indigo-500/30',   text: 'text-indigo-200' },
  reflection:     { label: 'reflect',  pill: 'bg-violet-500/15 border-violet-500/30',   text: 'text-violet-200' },
  focus_set:      { label: 'focus',    pill: 'bg-sky-500/15 border-sky-500/30',         text: 'text-sky-200' },
  focus_clear:    { label: 'unfocus',  pill: 'bg-sky-500/15 border-sky-500/30',         text: 'text-sky-200' },
  notify_david:   { label: 'notified', pill: 'bg-amber-500/15 border-amber-500/30',     text: 'text-amber-200' },
  inbox_pickup:   { label: 'pickup',   pill: 'bg-cyan-500/15 border-cyan-500/30',       text: 'text-cyan-200' },
  inbox_complete: { label: 'done',     pill: 'bg-emerald-500/15 border-emerald-500/30', text: 'text-emerald-300' },
  inbox_dismiss:  { label: 'dismiss',  pill: 'bg-orange-500/15 border-orange-500/30',   text: 'text-orange-200' },
  tool_call:      { label: 'tool',     pill: 'bg-fuchsia-500/15 border-fuchsia-500/30', text: 'text-fuchsia-200' },
  tool_result:    { label: 'result',   pill: 'bg-fuchsia-500/15 border-fuchsia-500/30', text: 'text-fuchsia-300' },
  external_event: { label: 'event',    pill: 'bg-zinc-500/15 border-zinc-500/30',       text: 'text-zinc-200' },
  error:          { label: 'error',    pill: 'bg-red-500/15 border-red-500/30',         text: 'text-red-300' },
}

const URGENCY_STYLES: Record<string, string> = {
  high:   'bg-red-500/20 text-red-300 border-red-500/40',
  normal: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/40',
  low:    'bg-zinc-700/40 text-zinc-400 border-zinc-700/60',
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
    if (!daemon) return { text: 'unknown', color: 'text-zinc-500', dot: 'bg-zinc-500' }
    if (daemon.state === 'never_started') return { text: 'never started', color: 'text-zinc-500', dot: 'bg-zinc-500' }
    if (!daemon.is_alive) return { text: 'dead', color: 'text-red-400', dot: 'bg-red-500' }
    if (daemon.state === 'thinking') return { text: 'thinking', color: 'text-indigo-300', dot: 'bg-indigo-400' }
    if (daemon.state === 'reflecting') return { text: 'reflecting', color: 'text-violet-300', dot: 'bg-violet-400' }
    return { text: 'alive', color: 'text-emerald-400', dot: 'bg-emerald-400' }
  }, [daemon])

  if (loading && !daemon) return <div className="text-zinc-400 p-4 text-sm">Loading…</div>
  if (error && !daemon) return <div className="text-red-400 p-4 text-sm">{error}</div>

  return (
    <div className="space-y-4">
      {/* ── Liveness ──────────────────────────────────────── */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className={`h-2.5 w-2.5 rounded-full ${livenessLabel.dot} ${daemon?.is_alive ? 'animate-pulse' : ''}`} />
            <span className={`text-base font-semibold ${livenessLabel.color}`}>{livenessLabel.text}</span>
            {daemon?.version && <span className="text-xs text-zinc-500">v{daemon.version}</span>}
          </div>
          <div className="text-xs text-zinc-500">
            heartbeat {daemon?.last_heartbeat_at ? timeAgo(daemon.last_heartbeat_at) : '—'}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="bg-gray-900/50 rounded p-2">
            <div className="text-zinc-500">host</div>
            <div className="text-zinc-200 font-medium truncate">{daemon?.hostname || '—'}</div>
          </div>
          <div className="bg-gray-900/50 rounded p-2">
            <div className="text-zinc-500">pid</div>
            <div className="text-zinc-200 font-medium">{daemon?.pid ?? '—'}</div>
          </div>
          <div className="bg-gray-900/50 rounded p-2">
            <div className="text-zinc-500">uptime</div>
            <div className="text-zinc-200 font-medium">{uptime(daemon?.started_at)}</div>
          </div>
          <div className="bg-gray-900/50 rounded p-2">
            <div className="text-zinc-500">last tick</div>
            <div className="text-zinc-200 font-medium truncate" title={daemon?.last_tick_summary || ''}>
              {daemon?.last_tick_summary || '—'}
            </div>
          </div>
        </div>
      </div>

      {/* ── Focus ────────────────────────────────────────── */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-baseline justify-between mb-2">
          <h3 className="text-sm font-semibold text-zinc-200">Current focus</h3>
          {focus?.set_at && <span className="text-xs text-zinc-500">set {timeAgo(focus.set_at)}</span>}
        </div>
        {focus?.topic ? (
          <>
            <div className="text-zinc-100">{focus.topic}</div>
            {focus.why && <div className="text-xs text-zinc-400 mt-1 italic">{focus.why}</div>}
          </>
        ) : (
          <div className="text-zinc-500 text-sm italic">between things</div>
        )}
      </div>

      {/* ── Inbox ────────────────────────────────────────── */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-sm font-semibold text-zinc-200">Queue</h3>
          <span className="text-xs text-zinc-500">{inbox.length} active</span>
        </div>

        {/* New-item form */}
        <form onSubmit={submitInbox} className="flex gap-2 mb-3">
          <input
            type="text"
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            placeholder="Queue something for Sara…"
            className="flex-1 bg-gray-900/60 border border-gray-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
          />
          <select
            value={newUrgency}
            onChange={(e) => setNewUrgency(e.target.value as 'low' | 'normal' | 'high')}
            className="bg-gray-900/60 border border-gray-700 rounded px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
          >
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
          <button
            type="submit"
            disabled={!newPrompt.trim() || submitting}
            className="px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded transition-colors"
          >
            Queue
          </button>
        </form>

        {/* Item list */}
        {inbox.length === 0 ? (
          <div className="text-zinc-500 text-sm italic">empty — nothing queued for her</div>
        ) : (
          <ul className="space-y-2">
            {inbox.map((item) => (
              <li key={item.id} className="bg-gray-900/40 rounded p-2.5 border border-gray-800">
                <div className="flex items-start gap-2">
                  <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${URGENCY_STYLES[item.urgency] || URGENCY_STYLES.normal} font-medium`}>
                    {item.urgency}
                  </span>
                  <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border font-medium ${
                    item.status === 'in_progress'
                      ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
                      : 'bg-zinc-700/40 text-zinc-400 border-zinc-700/60'
                  }`}>
                    {item.status === 'in_progress' ? 'in progress' : 'queued'}
                  </span>
                  <span className="text-[10px] text-zinc-500 ml-auto">{timeAgo(item.created_at)}</span>
                </div>
                <div className="text-sm text-zinc-200 mt-1.5">{item.prompt}</div>
                {item.context && <div className="text-xs text-zinc-400 mt-1 italic">{item.context}</div>}
                <div className="text-[10px] text-zinc-600 mt-1">id={item.id.slice(0, 8)} • from {item.created_by}</div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Activity feed ─────────────────────────────────── */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-sm font-semibold text-zinc-200">Activity</h3>
          <span className="text-xs text-zinc-500">last {activity.length}</span>
        </div>
        {activity.length === 0 ? (
          <div className="text-zinc-500 text-sm italic">no activity yet</div>
        ) : (
          <ul className="space-y-1.5">
            {activity.map((a) => {
              const style = KIND_STYLES[a.kind] || KIND_STYLES.external_event
              const expanded = expandedActivity.has(a.id)
              const hasBody = !!a.body && a.body.trim().length > 0
              return (
                <li key={a.id} className="bg-gray-900/30 rounded">
                  <button
                    onClick={() => hasBody && toggleActivity(a.id)}
                    className={`w-full text-left px-2.5 py-1.5 flex items-start gap-2 ${hasBody ? 'hover:bg-gray-900/60 cursor-pointer' : 'cursor-default'}`}
                  >
                    <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${style.pill} ${style.text} font-medium shrink-0 mt-0.5`}>
                      {style.label}
                    </span>
                    <span className="text-[10px] text-zinc-500 shrink-0 mt-0.5 w-16">{timeAgo(a.created_at)}</span>
                    <span className="text-sm text-zinc-200 flex-1">{a.summary}</span>
                    {hasBody && (
                      <span className="text-zinc-600 text-xs shrink-0 mt-0.5">{expanded ? '▾' : '▸'}</span>
                    )}
                  </button>
                  {expanded && hasBody && (
                    <div className="px-2.5 pb-2 pt-0 ml-[3.5rem] text-xs text-zinc-300 whitespace-pre-wrap">
                      {a.body}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}
    </div>
  )
}

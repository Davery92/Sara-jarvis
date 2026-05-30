import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'

interface DaemonStatus {
  state: string
  version: string
  is_alive: boolean
  last_heartbeat_at: string | null
  last_tick_summary: string | null
  started_at: string | null
}

interface Focus {
  topic: string | null
  why: string | null
  set_at: string | null
}

interface Activity {
  id: string
  created_at: string
  kind: string
  summary: string
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'just now'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

const KIND_DOT: Record<string, string> = {
  thought:        'bg-indigo-400',
  reflection:     'bg-violet-400',
  notify_david:   'bg-amber-400',
  inbox_pickup:   'bg-cyan-400',
  inbox_complete: 'bg-emerald-400',
  inbox_dismiss:  'bg-orange-400',
  focus_set:      'bg-sky-400',
  focus_clear:    'bg-sky-400',
  boot:           'bg-emerald-400',
  shutdown:       'bg-zinc-500',
  error:          'bg-red-400',
}

/**
 * Compact Sara-daemon liveness card for the dashboard. Shows alive/dead,
 * current focus, and the last few activity entries. Click anywhere on
 * the header → jumps to /acs for the full Mind view.
 */
export default function SaraStatusCard() {
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [activity, setActivity] = useState<Activity[]>([])
  const [, setTick] = useState(0)

  const fetchAll = useCallback(async () => {
    try {
      const [d, f, a] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/daemon-status`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/focus`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/activity?limit=4`, { credentials: 'include' }),
      ])
      if (d.ok) setDaemon(await d.json())
      if (f.ok) setFocus(await f.json())
      if (a.ok) setActivity(await a.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchAll()
    const refresh = setInterval(fetchAll, 10_000)
    const reRender = setInterval(() => setTick((t) => t + 1), 1000)
    return () => { clearInterval(refresh); clearInterval(reRender) }
  }, [fetchAll])

  const liveDot = daemon?.is_alive
    ? (daemon.state === 'thinking' ? 'bg-indigo-400' : daemon.state === 'reflecting' ? 'bg-violet-400' : 'bg-emerald-400')
    : 'bg-red-500'
  const liveLabel = !daemon
    ? 'unknown'
    : daemon.state === 'never_started'
      ? 'never started'
      : !daemon.is_alive
        ? 'unreachable'
        : daemon.state === 'thinking'
          ? 'thinking'
          : daemon.state === 'reflecting'
            ? 'reflecting'
            : 'alive'

  return (
    <a href="/acs" className="block assistant-panel-muted rounded-2xl p-3 hover:border-indigo-500/40 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <div className="assistant-kicker">Sara</div>
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <span className={`h-2 w-2 rounded-full ${liveDot} ${daemon?.is_alive ? 'animate-pulse' : ''}`} />
          <span>{liveLabel}</span>
          {daemon?.last_heartbeat_at && (
            <span className="text-gray-500">· {timeAgo(daemon.last_heartbeat_at)} ago</span>
          )}
        </div>
      </div>

      <div className="mb-3">
        {focus?.topic ? (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">focused on</div>
            <div className="text-sm text-gray-100 leading-snug">{focus.topic}</div>
          </div>
        ) : (
          <div className="text-sm text-gray-500 italic">between things</div>
        )}
      </div>

      {activity.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">recent</div>
          <ul className="space-y-1">
            {activity.map((a) => (
              <li key={a.id} className="flex items-start gap-2 text-xs text-gray-300">
                <span className={`h-1.5 w-1.5 rounded-full mt-1.5 shrink-0 ${KIND_DOT[a.kind] || 'bg-zinc-500'}`} />
                <span className="text-gray-500 shrink-0 w-7">{timeAgo(a.created_at)}</span>
                <span className="truncate">{a.summary}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </a>
  )
}

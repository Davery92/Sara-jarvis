import { useCallback, useEffect, useRef, useState } from 'react'
import { APP_CONFIG } from '../config'

const POLL_INTERVAL_MS = 30000

// Read-only World Context page (living-world-context plan, Phase 6).
// Shows what Sara currently understands, where it came from, and how
// current it is — derived from the SAME maintained projections chat
// reads (backend/app/routes/world_context.py), never from source
// reconciliation or a model call triggered by loading the page.

interface CoverageRow {
  domain: string
  last_kind: string | null
  last_event_sequence: number | null
  updated_at: string | null
  age_seconds: number | null
  degraded: boolean
}

interface WorldContextResponse {
  as_of: string
  revision: number
  last_event_sequence: number
  current_situation: string[]
  brief: string
  coverage: CoverageRow[]
  degraded_domains: string[]
}

async function apiFetch(path: string): Promise<WorldContextResponse> {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return 'unknown'
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function DomainRow({ row }: { row: CoverageRow }) {
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/50 border border-gray-700/50">
      <div className="flex items-center gap-2">
        <span
          className={`w-2 h-2 rounded-full ${row.degraded ? 'bg-yellow-500' : 'bg-green-500'}`}
          title={row.degraded ? 'No recent activity observed' : 'Recently updated'}
        />
        <span className="text-sm text-gray-200 capitalize">{row.domain.replace(/_/g, ' ')}</span>
      </div>
      <div className="text-right">
        <div className="text-xs text-gray-400">{formatAge(row.age_seconds)}</div>
        {row.last_kind && <div className="text-[11px] text-gray-600">{row.last_kind}</div>}
      </div>
    </div>
  )
}

export default function WorldContext() {
  const [data, setData] = useState<WorldContextResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Mirrors `data` for the poll/visibility callbacks below, which close
  // over `load` once — this avoids re-creating the interval on every fetch
  // just to see a fresh `data` value.
  const dataRef = useRef<WorldContextResponse | null>(null)

  const load = useCallback(async () => {
    try {
      const result = await apiFetch('/api/world-context')
      // Bounded revision polling: only re-render when something actually
      // changed since the last successful fetch.
      if (!dataRef.current || result.revision !== dataRef.current.revision) {
        dataRef.current = result
        setData(result)
      }
      setError(null)
    } catch (e) {
      // A background poll must never blank out what David is currently
      // reading — only surface the error screen when there's nothing on
      // screen to preserve yet (the render guard below also checks this,
      // but skipping the state write keeps a transient blip from ever
      // being visible even for a frame).
      if (!dataRef.current) {
        setError(e instanceof Error ? e.message : 'Failed to load')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()

    // A quiet-but-healthy system should not look stale to David just
    // because nothing changed since the last poll — but the page should
    // still catch up promptly when something did. Bounded polling per
    // Phase 6 item 3, not a push channel (matches the iOS screen, which
    // has no event-stream transport to hook into either).
    let interval: ReturnType<typeof setInterval> | null = null
    const startPolling = () => {
      if (interval) return
      interval = setInterval(load, POLL_INTERVAL_MS)
    }
    const stopPolling = () => {
      if (interval) {
        clearInterval(interval)
        interval = null
      }
    }

    startPolling()

    // Page Visibility API — the web analogue of "screen focus" / "app
    // foreground": stop polling a background tab entirely, and refetch
    // immediately the moment it's visible again rather than waiting out
    // whatever was left of the interval.
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        load()
        startPolling()
      } else {
        stopPolling()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [load])

  if (loading && !data) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
  }

  if (error && !data) {
    return (
      <div className="p-6 text-center text-gray-400">
        <p className="mb-2">Couldn't load World Context.</p>
        <p className="text-sm text-gray-600">{error}</p>
        <button
          onClick={load}
          className="mt-4 px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-200"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">World Context</h1>
        <p className="text-sm text-gray-500 mt-1">
          What Sara currently understands about your world — read-only. As of{' '}
          {new Date(data.as_of).toLocaleTimeString()}, revision {data.revision}.
        </p>
      </div>

      {data.degraded_domains.length > 0 && (
        <div className="rounded-lg border border-yellow-700/40 bg-yellow-900/20 px-4 py-3 text-sm text-yellow-300">
          No recent activity observed for: {data.degraded_domains.join(', ')}. This may just mean
          nothing has happened there — not that anything is broken.
        </div>
      )}

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-2">
          Current Situation
        </h2>
        {data.current_situation.length === 0 ? (
          <p className="text-sm text-gray-600">Nothing currently active.</p>
        ) : (
          <ul className="space-y-2">
            {data.current_situation.map((line, i) => (
              <li
                key={i}
                className="text-sm text-gray-200 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2"
              >
                {line}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-2">
          Recent Developments &amp; Upcoming
        </h2>
        <pre className="text-sm text-gray-300 bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-3 whitespace-pre-wrap font-sans leading-relaxed">
          {data.brief || 'Nothing notable.'}
        </pre>
      </section>

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-2">
          Source Freshness
        </h2>
        {data.coverage.length === 0 ? (
          <p className="text-sm text-gray-600">No activity observed yet.</p>
        ) : (
          <div className="space-y-1">
            {data.coverage.map((row) => (
              <DomainRow key={row.domain} row={row} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

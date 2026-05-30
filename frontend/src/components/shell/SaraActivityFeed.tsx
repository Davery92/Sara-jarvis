import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

/**
 * SaraActivityFeed — "What Sara's been up to" (P2.1).
 *
 * Sweeps, focus changes, reflections, tool calls, and notify-David moments all
 * already happen in the ACS daemon, but they were invisible unless you opened the
 * ACS page. This dashboard card surfaces that autonomy so you can *see* Sara
 * working on your behalf — the Cortana "Notebook" idea. Self-contained (fetches
 * its own data), so it needs no prop-threading through the shell.
 */

interface Activity {
  id: string
  created_at: string
  kind: string
  summary: string
}

// Noise kinds we don't surface in a human-facing feed.
const HIDDEN_KINDS = new Set(['tick', 'external_event'])

const KIND_META: Record<string, { label: string; dot: string; text: string }> = {
  boot:           { label: 'woke up',   dot: 'bg-emerald-400', text: 'text-emerald-300' },
  shutdown:       { label: 'slept',     dot: 'bg-zinc-500',    text: 'text-zinc-400' },
  thought:        { label: 'thought',   dot: 'bg-indigo-400',  text: 'text-indigo-200' },
  reflection:     { label: 'reflected', dot: 'bg-violet-400',  text: 'text-violet-200' },
  focus_set:      { label: 'focused',   dot: 'bg-sky-400',     text: 'text-sky-200' },
  focus_clear:    { label: 'unfocused', dot: 'bg-sky-500',     text: 'text-sky-300' },
  notify_david:   { label: 'reached out', dot: 'bg-amber-400', text: 'text-amber-200' },
  inbox_pickup:   { label: 'picked up', dot: 'bg-cyan-400',    text: 'text-cyan-200' },
  inbox_complete: { label: 'finished',  dot: 'bg-emerald-400', text: 'text-emerald-300' },
  inbox_dismiss:  { label: 'dropped',   dot: 'bg-orange-400',  text: 'text-orange-200' },
  tool_call:      { label: 'used a tool', dot: 'bg-fuchsia-400', text: 'text-fuchsia-200' },
  tool_result:    { label: 'got result', dot: 'bg-fuchsia-400', text: 'text-fuchsia-300' },
  error:          { label: 'hit a snag', dot: 'bg-red-500',    text: 'text-red-300' },
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'now'
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function SaraActivityFeed() {
  const [items, setItems] = useState<Activity[]>([])
  const [loaded, setLoaded] = useState(false)

  const fetchActivity = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/activity?limit=40`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data: Activity[] = await res.json()
        setItems((data || []).filter((a) => !HIDDEN_KINDS.has(a.kind)).slice(0, 8))
      }
    } catch {
      /* keep last good */
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    fetchActivity()
    const t = setInterval(fetchActivity, 15000)
    return () => clearInterval(t)
  }, [fetchActivity])

  return (
    <div className="assistant-panel-muted rounded-2xl p-3">
      <div className="assistant-kicker mb-2">Proactivity</div>
      <h2 className="font-display text-sm font-semibold text-white mb-2">What Sara's been up to</h2>
      {!loaded ? (
        <p className="text-gray-500 text-xs">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-500 text-xs">Quiet lately — nothing to report.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((a) => {
            const meta = KIND_META[a.kind] || { label: a.kind.replace('_', ' '), dot: 'bg-zinc-500', text: 'text-zinc-300' }
            return (
              <li key={a.id} className="flex items-start gap-2">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-300 leading-tight">{a.summary}</p>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px]">
                    <span className={meta.text}>{meta.label}</span>
                    <span className="text-gray-600">·</span>
                    <span className="text-gray-500">{timeAgo(a.created_at)}</span>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

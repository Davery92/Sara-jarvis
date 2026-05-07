import { useEffect, useState, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface Interest {
  id: string
  topic: string
  display_name: string
  why: string | null
  weight: number
  last_acted_at: string | null
  last_updated_at: string
  source: string
  created_at: string
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
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

const SOURCE_BADGE: Record<string, string> = {
  reflection: 'bg-violet-500/15 text-violet-200 border-violet-500/30',
  external_event: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30',
  manual: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
}

export default function InterestsPanel() {
  const [interests, setInterests] = useState<Interest[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [, setTick] = useState(0)

  const fetchInterests = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/interests?limit=20`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Interest[] = await res.json()
      setInterests(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchInterests()
    const refresh = setInterval(fetchInterests, 15000)
    const reRender = setInterval(() => setTick((t) => t + 1), 1000)
    return () => { clearInterval(refresh); clearInterval(reRender) }
  }, [fetchInterests])

  const remove = async (id: string) => {
    if (!confirm('Remove this interest? Sara will stop seeding it.')) return
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/interests/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchInterests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete')
    }
  }

  const maxWeight = Math.max(1, ...interests.map((i) => i.weight))

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">Interests</h3>
        <span className="text-xs text-zinc-500">{interests.length} tracked</span>
      </div>

      {loading && <div className="text-zinc-500 text-sm italic">Loading…</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {!loading && interests.length === 0 && !error && (
        <div className="text-zinc-500 text-sm italic">
          nothing tracked yet — she'll seed these from her reflections
        </div>
      )}

      {interests.length > 0 && (
        <ul className="space-y-2">
          {interests.map((i) => {
            const pct = Math.round((i.weight / maxWeight) * 100)
            return (
              <li key={i.id} className="bg-gray-900/40 rounded p-2.5 border border-gray-800">
                <div className="flex items-start gap-2">
                  <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border font-medium shrink-0 mt-0.5 ${SOURCE_BADGE[i.source] || SOURCE_BADGE.reflection}`}>
                    {i.source.replace('_', ' ')}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm text-zinc-100 truncate">{i.display_name}</span>
                      <span className="text-[10px] text-zinc-500 ml-auto shrink-0">
                        weight {i.weight.toFixed(2)}
                      </span>
                    </div>
                    <div className="h-1 bg-gray-800 rounded mt-1 overflow-hidden">
                      <div className="h-full bg-violet-500/60" style={{ width: `${pct}%` }} />
                    </div>
                    {i.why && (
                      <div className="text-xs text-zinc-400 mt-1 italic line-clamp-2">{i.why}</div>
                    )}
                    <div className="text-[10px] text-zinc-600 mt-1 flex gap-3">
                      <span>last touched {timeAgo(i.last_acted_at)}</span>
                      <span>updated {timeAgo(i.last_updated_at)} ago</span>
                    </div>
                  </div>
                  <button
                    onClick={() => remove(i.id)}
                    className="text-[10px] text-zinc-600 hover:text-red-400 shrink-0 mt-0.5"
                    title="Remove"
                  >
                    ✕
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

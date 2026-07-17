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

const SOURCE_TEXT: Record<string, string> = {
  reflection: 'text-violet-300/80',
  external_event: 'text-slate-500',
  manual: 'text-amber-300/80',
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
    if (!confirm('Remove this interest? Note: her reflections can re-add it later. Use Block to veto a topic for good.')) return
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

  const block = async (id: string) => {
    if (!confirm('Block this topic? Sara will drop it permanently — re-adds and rephrasings are rejected.')) return
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/interests/${id}/block`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchInterests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to block')
    }
  }

  const maxWeight = Math.max(1, ...interests.map((i) => i.weight))

  return (
    <section className="pt-6">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Interests</h2>
        <span className="text-xs text-slate-500">{interests.length} tracked</span>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-rose-400">{error}</p>}

      {!loading && interests.length === 0 && !error && (
        <p className="text-sm text-slate-500">Nothing tracked yet — she'll seed these from her reflections.</p>
      )}

      {interests.length > 0 && (
        <ul className="space-y-1">
          {interests.map((i) => {
            const pct = Math.round((i.weight / maxWeight) * 100)
            return (
              <li key={i.id} className="group rounded-md px-2 py-2 transition-colors hover:bg-white/[0.04]">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="truncate text-[15px] text-slate-200">{i.display_name}</span>
                      <span className={`shrink-0 font-mono text-[10px] uppercase tracking-wide ${SOURCE_TEXT[i.source] || SOURCE_TEXT.reflection}`}>
                        {i.source.replace('_', ' ')}
                      </span>
                      <span className="ml-auto shrink-0 font-mono text-xs text-slate-500">
                        {i.weight.toFixed(2)}
                      </span>
                    </div>
                    <div className="mt-1.5 h-px overflow-hidden rounded bg-white/10">
                      <div className="h-full bg-slate-400/60" style={{ width: `${pct}%` }} />
                    </div>
                    {i.why && (
                      <div className="mt-1.5 line-clamp-2 text-xs text-slate-500">{i.why}</div>
                    )}
                    <div className="mt-1 flex gap-3 text-xs text-slate-500">
                      <span>last touched {timeAgo(i.last_acted_at)}</span>
                      <span>updated {timeAgo(i.last_updated_at)} ago</span>
                    </div>
                  </div>
                  <div className="mt-0.5 flex shrink-0 flex-col items-end gap-1.5">
                    <button
                      onClick={() => remove(i.id)}
                      className="text-xs text-slate-600 opacity-0 transition-all hover:text-rose-400 group-hover:opacity-100"
                      title="Remove (her reflections can re-add it)"
                    >
                      ✕
                    </button>
                    <button
                      onClick={() => block(i.id)}
                      className="text-[10px] uppercase tracking-wide text-slate-600 opacity-0 transition-all hover:text-rose-400 group-hover:opacity-100"
                      title="Veto this topic permanently — re-adds are rejected"
                    >
                      block
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

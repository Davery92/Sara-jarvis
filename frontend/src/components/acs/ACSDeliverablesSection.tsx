import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface Deliverable {
  id: string
  session_id?: string | null
  vmid?: number | null
  title: string
  description?: string | null
  kind: string
  ip?: string | null
  port?: number | null
  url?: string | null
  start_command?: string | null
  built_from?: string | null
  status: 'pending_review' | 'kept' | 'destroyed' | string
  created_at: string
  reviewed_at?: string | null
  auto_destroy_at?: string | null
  destroyed_at?: string | null
}

const STATUS_STYLES: Record<string, string> = {
  pending_review: 'bg-amber-900/30 text-amber-400 border-amber-800/50',
  kept: 'bg-emerald-900/30 text-emerald-400 border-emerald-800/50',
  destroyed: 'bg-gray-800 text-gray-500 border-gray-700',
}

function relTime(iso?: string | null): string {
  if (!iso) return '—'
  const diffMs = new Date(iso).getTime() - Date.now()
  const abs = Math.abs(diffMs)
  const mins = Math.round(abs / 60000)
  if (mins < 60) return diffMs > 0 ? `in ${mins}m` : `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 48) return diffMs > 0 ? `in ${hrs}h` : `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return diffMs > 0 ? `in ${days}d` : `${days}d ago`
}

export default function ACSDeliverablesSection() {
  const [items, setItems] = useState<Deliverable[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'pending_review' | 'kept' | 'destroyed'>('all')

  const fetchItems = useCallback(async () => {
    setLoading(true)
    try {
      const qs = filter === 'all' ? '' : `?status=${filter}`
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/deliverables${qs}`, {
        credentials: 'include',
      })
      if (!res.ok) {
        setError(`Failed to load: ${res.status}`)
        return
      }
      const data = await res.json()
      setItems(data.deliverables || [])
      setError(null)
    } catch (e) {
      setError(`Failed to load: ${e}`)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchItems() }, [fetchItems])

  const keep = async (id: string) => {
    if (busyId) return
    setBusyId(id)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/deliverables/${id}/keep`, {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) await fetchItems()
    } finally {
      setBusyId(null)
    }
  }

  const destroy = async (id: string) => {
    if (busyId) return
    if (!confirm('Destroy this LXC and mark the deliverable destroyed? This cannot be undone.')) return
    setBusyId(id)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/deliverables/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (res.ok) await fetchItems()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-400">
          UIs Sara has shipped to LXC containers for your review. Click the URL to open.
        </p>
        <div className="flex gap-1">
          {(['all', 'pending_review', 'kept', 'destroyed'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 text-xs rounded ${
                filter === f
                  ? 'bg-indigo-900/40 text-indigo-300 border border-indigo-700/50'
                  : 'text-gray-500 hover:text-gray-300 border border-transparent'
              }`}
            >
              {f === 'all' ? 'All' : f === 'pending_review' ? 'Pending' : f === 'kept' ? 'Kept' : 'Destroyed'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-gray-400 p-4">Loading...</div>
      ) : error ? (
        <div className="text-red-400 p-4">{error}</div>
      ) : items.length === 0 ? (
        <div className="text-gray-500 p-4 text-sm">No deliverables {filter !== 'all' ? `with status "${filter}"` : 'yet'}.</div>
      ) : (
        <div className="space-y-2">
          {items.map(d => {
            const isLive = d.status !== 'destroyed' && d.url
            return (
              <div
                key={d.id}
                className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-white font-medium truncate">{d.title}</h3>
                      <span
                        className={`text-xs px-2 py-0.5 rounded border ${STATUS_STYLES[d.status] || 'bg-gray-800 text-gray-400 border-gray-700'}`}
                      >
                        {d.status.replace('_', ' ')}
                      </span>
                      <span className="text-xs text-gray-500">
                        {d.kind} · vmid={d.vmid ?? '—'}
                      </span>
                    </div>
                    {d.description && (
                      <p className="text-sm text-gray-400 mt-1">{d.description}</p>
                    )}
                    <div className="mt-2 flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                      {isLive ? (
                        <a
                          href={d.url!}
                          target="_blank"
                          rel="noreferrer"
                          className="text-indigo-400 hover:text-indigo-300 font-mono"
                        >
                          {d.url} ↗
                        </a>
                      ) : (
                        <span className="text-gray-600 font-mono line-through">
                          {d.ip && d.port ? `http://${d.ip}:${d.port}` : '—'}
                        </span>
                      )}
                      <span>built {relTime(d.created_at)}</span>
                      {d.status === 'pending_review' && d.auto_destroy_at && (
                        <span className="text-amber-500/80">auto-destroys {relTime(d.auto_destroy_at)}</span>
                      )}
                      {d.status === 'kept' && d.reviewed_at && (
                        <span className="text-emerald-500/80">kept {relTime(d.reviewed_at)}</span>
                      )}
                      {d.status === 'destroyed' && d.destroyed_at && (
                        <span>destroyed {relTime(d.destroyed_at)}</span>
                      )}
                    </div>
                  </div>
                  {d.status !== 'destroyed' && (
                    <div className="flex gap-2 shrink-0">
                      {d.status !== 'kept' && (
                        <button
                          onClick={() => keep(d.id)}
                          disabled={busyId === d.id}
                          className="text-xs px-3 py-1.5 rounded bg-emerald-900/30 text-emerald-400 border border-emerald-800/50 hover:bg-emerald-900/50 disabled:opacity-50"
                        >
                          Keep
                        </button>
                      )}
                      <button
                        onClick={() => destroy(d.id)}
                        disabled={busyId === d.id}
                        className="text-xs px-3 py-1.5 rounded bg-red-900/30 text-red-400 border border-red-800/50 hover:bg-red-900/50 disabled:opacity-50"
                      >
                        Destroy
                      </button>
                    </div>
                  )}
                </div>
                {d.built_from && (
                  <div className="mt-2 text-xs text-gray-600 font-mono truncate">
                    built from: {d.built_from}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

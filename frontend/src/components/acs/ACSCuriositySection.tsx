import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface Curiosity {
  id: string
  topic: string
  reason?: string
  status: string
  priority: number | string
  source?: string
  created_at: string
}

export default function ACSCuriositySection() {
  const [items, setItems] = useState<Curiosity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newTopic, setNewTopic] = useState('')
  const [newReason, setNewReason] = useState('')
  const [newPriority, setNewPriority] = useState('normal')
  const [submitting, setSubmitting] = useState(false)

  const fetchCuriosities = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/curiosity`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setItems(Array.isArray(data) ? data : data.items || [])
        setError(null)
      } else {
        setError('Failed to load curiosities')
      }
    } catch {
      setError('Failed to load curiosities')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCuriosities() }, [fetchCuriosities])

  const addCuriosity = async () => {
    if (!newTopic.trim()) return
    setSubmitting(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/curiosity`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: newTopic.trim(), priority: newPriority === 'high' ? 0.9 : newPriority === 'low' ? 0.2 : 0.5 }),
      })
      if (res.ok) {
        setNewTopic('')
        setNewReason('')
        setNewPriority('normal')
        await fetchCuriosities()
      }
    } catch { /* ignore */ }
    finally { setSubmitting(false) }
  }

  const removeCuriosity = async (id: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/acs/curiosity/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      await fetchCuriosities()
    } catch { /* ignore */ }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>

  const grouped: Record<string, Curiosity[]> = { queued: [], exploring: [], explored: [] }
  items.forEach(item => {
    const key = grouped[item.status] ? item.status : 'queued'
    grouped[key].push(item)
  })

  return (
    <div className="space-y-4">
      {/* Add form */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3">Add Curiosity</h3>
        <div className="space-y-2">
          <input
            type="text"
            value={newTopic}
            onChange={e => setNewTopic(e.target.value)}
            placeholder="Topic to explore..."
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-indigo-500"
          />
          <input
            type="text"
            value={newReason}
            onChange={e => setNewReason(e.target.value)}
            placeholder="Why is this interesting? (optional)"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-indigo-500"
          />
          <div className="flex gap-2">
            <select
              value={newPriority}
              onChange={e => setNewPriority(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
            <button onClick={addCuriosity} disabled={submitting || !newTopic.trim()}
              className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white rounded-lg transition-colors">
              {submitting ? 'Adding...' : 'Add'}
            </button>
          </div>
        </div>
      </div>

      {/* Grouped lists */}
      {(['queued', 'exploring', 'explored'] as const).map(status => {
        const group = grouped[status] || []
        if (group.length === 0 && status !== 'queued') return null
        return (
          <div key={status}>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              {status} ({group.length})
            </h3>
            {group.length === 0 ? (
              <p className="text-sm text-gray-500">No curiosities queued yet.</p>
            ) : (
              <div className="space-y-2">
                {group.map(item => (
                  <div key={item.id} className="bg-gray-800/50 rounded-lg border border-gray-700 p-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-white font-medium text-sm">{item.topic}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          Number(item.priority) > 0.7 ? 'bg-red-900/30 text-red-400' :
                          Number(item.priority) < 0.3 ? 'bg-gray-700 text-gray-400' :
                          'bg-indigo-900/30 text-indigo-400'
                        }`}>
                          {typeof item.priority === 'number' ? item.priority.toFixed(1) : item.priority}
                        </span>
                        {item.source && <span className="text-xs text-gray-600">{item.source}</span>}
                      </div>
                      {item.reason && <p className="text-xs text-gray-400">{item.reason}</p>}
                    </div>
                    <button onClick={() => removeCuriosity(item.id)}
                      className="text-gray-600 hover:text-red-400 text-sm shrink-0 transition-colors">
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

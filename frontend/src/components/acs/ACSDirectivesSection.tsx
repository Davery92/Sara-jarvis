import { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../../config'

interface Directive {
  id: string
  directive_type: string
  content: string
  priority: string
  status: string
  source: string
  response?: string
  created_at: string
  expires_at?: string
}

const TYPE_OPTIONS = [
  { value: 'focus', label: 'Focus - prioritize this topic' },
  { value: 'stop', label: 'Stop - stop doing this immediately' },
  { value: 'redirect', label: 'Redirect - change course' },
  { value: 'context', label: 'Context - FYI information' },
  { value: 'question', label: 'Question - ask ACS something' },
]

const TYPE_COLORS: Record<string, string> = {
  stop: 'text-red-400',
  focus: 'text-emerald-400',
  redirect: 'text-amber-400',
  context: 'text-blue-400',
  question: 'text-purple-400',
}

const STATUS_BADGES: Record<string, string> = {
  pending: 'bg-amber-900/30 text-amber-400',
  acknowledged: 'bg-emerald-900/30 text-emerald-400',
  completed: 'bg-gray-700 text-gray-400',
  expired: 'bg-gray-700 text-gray-500',
}

export default function ACSDirectivesSection() {
  const [directives, setDirectives] = useState<Directive[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formType, setFormType] = useState('focus')
  const [formPriority, setFormPriority] = useState('normal')
  const [formContent, setFormContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // Two-click delete confirm: first click arms a directive, second click in
  // the same row commits. Auto-disarms after 4s so a stray click doesn't
  // leave the UI hanging in an armed state.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const confirmTimeoutRef = useRef<number | null>(null)

  const armDelete = (id: string) => {
    setConfirmingDeleteId(id)
    if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current)
    confirmTimeoutRef.current = window.setTimeout(() => {
      setConfirmingDeleteId(null)
      confirmTimeoutRef.current = null
    }, 4000)
  }

  const cancelDelete = () => {
    if (confirmTimeoutRef.current) {
      window.clearTimeout(confirmTimeoutRef.current)
      confirmTimeoutRef.current = null
    }
    setConfirmingDeleteId(null)
  }

  useEffect(() => {
    return () => {
      if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current)
    }
  }, [])

  const fetchDirectives = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/directives`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setDirectives(Array.isArray(data) ? data : data.directives || [])
        setError(null)
      } else {
        setError('Failed to load directives')
      }
    } catch {
      setError('Failed to load directives')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDirectives() }, [fetchDirectives])

  const createDirective = async () => {
    if (!formContent.trim()) return
    setSubmitting(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/directive`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          directive_type: formType,
          content: formContent.trim(),
          priority: formPriority,
          source: 'frontend',
        }),
      })
      if (res.ok) {
        setFormContent('')
        await fetchDirectives()
      }
    } catch { /* ignore */ }
    finally { setSubmitting(false) }
  }

  const deleteDirective = async (id: string) => {
    cancelDelete()
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/directive/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) {
        setError(`Failed to delete directive (${res.status})`)
        return
      }
      // Optimistic removal — backend soft-deletes (status='expired') and the
      // list endpoint now filters those out, so refetch will agree with this.
      setDirectives(prev => prev.filter(d => d.id !== id))
      setError(null)
      await fetchDirectives()
    } catch {
      setError('Failed to delete directive')
    }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>

  return (
    <div className="space-y-4">
      {/* Create form */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <h3 className="text-sm font-semibold text-white mb-3">New Directive</h3>
        <div className="space-y-2">
          <div className="flex gap-2">
            <select value={formType} onChange={e => setFormType(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
              {TYPE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <select value={formPriority} onChange={e => setFormPriority(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <textarea
            value={formContent}
            onChange={e => setFormContent(e.target.value)}
            placeholder="Directive content..."
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-500 resize-none focus:outline-none focus:border-indigo-500"
          />
          <button onClick={createDirective} disabled={submitting || !formContent.trim()}
            className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white rounded-lg transition-colors">
            {submitting ? 'Sending...' : 'Send Directive'}
          </button>
        </div>
      </div>

      {/* Directive list */}
      {directives.length === 0 ? (
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
          <p className="text-gray-400">No directives yet.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {directives.map(d => (
            <div key={d.id} className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-sm font-bold ${TYPE_COLORS[d.directive_type] || 'text-gray-400'}`}>
                      [{d.directive_type.toUpperCase()}]
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_BADGES[d.status] || STATUS_BADGES.pending}`}>
                      {d.status}
                    </span>
                    <span className={`text-xs ${d.priority === 'urgent' ? 'text-red-400' : 'text-gray-500'}`}>
                      {d.priority}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300">{d.content}</p>
                  {d.response && (
                    <p className="text-sm text-gray-500 italic mt-1">Response: {d.response}</p>
                  )}
                  <div className="text-xs text-gray-600 mt-2">
                    {d.source} - {new Date(d.created_at).toLocaleString()}
                    {d.expires_at && ` (expires ${new Date(d.expires_at).toLocaleString()})`}
                  </div>
                </div>
                {confirmingDeleteId === d.id ? (
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => deleteDirective(d.id)}
                      className="px-2 py-1 text-xs bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={cancelDelete}
                      className="px-2 py-1 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => armDelete(d.id)}
                    className="text-gray-600 hover:text-red-400 text-sm shrink-0 transition-colors"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

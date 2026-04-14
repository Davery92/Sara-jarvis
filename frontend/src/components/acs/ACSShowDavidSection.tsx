import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../../config'

interface ShowDavidItem {
  id: string
  category: string
  title: string
  content: string
  source_session_id?: string
  shown: boolean
  created_at: string
}

const CATEGORY_COLORS: Record<string, string> = {
  discovery: 'bg-emerald-900/30 text-emerald-400',
  insight: 'bg-indigo-900/30 text-indigo-400',
  connection: 'bg-amber-900/30 text-amber-400',
  question: 'bg-blue-900/30 text-blue-400',
  recommendation: 'bg-purple-900/30 text-purple-400',
}

export default function ACSShowDavidSection() {
  const [items, setItems] = useState<ShowDavidItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Default to ALL items, not just unshown. The morning wind-down task in
  // tasks/acs.py auto-marks every show_david item as shown=TRUE at 5 AM ET,
  // so filtering to unshown-only would make this section appear empty for
  // anything older than today.
  const [unshownOnly, setUnshownOnly] = useState(false)

  const fetchItems = useCallback(async () => {
    try {
      // Always pull ALL items from the backend; filter client-side via the toggle.
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/acs/show-david?unshown_only=false&limit=100`,
        { credentials: 'include' }
      )
      if (res.ok) {
        const data = await res.json()
        setItems(Array.isArray(data) ? data : data.items || [])
        setError(null)
      } else {
        setError('Failed to load items')
      }
    } catch {
      setError('Failed to load items')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchItems() }, [fetchItems])

  const markAsShown = async (id: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/acs/show-david/${id}/shown`, {
        method: 'POST',
        credentials: 'include',
      })
      await fetchItems()
    } catch { /* ignore */ }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>

  const unshown = items.filter(i => !i.shown)
  const shown = items.filter(i => i.shown)
  const displayItems = unshownOnly ? unshown : items

  if (items.length === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
        <p className="text-gray-400">No discoveries yet.</p>
        <p className="text-gray-500 text-sm mt-1">Sara will queue interesting findings here during autonomous sessions.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-400">
          {unshown.length} new
          {' · '}
          {items.length} total
        </div>
        <button onClick={() => setUnshownOnly(v => !v)}
          className="text-sm text-indigo-400 hover:text-indigo-300 transition-colors">
          {unshownOnly ? 'Show all' : 'New only'}
        </button>
      </div>

      <div className="space-y-3">
        {displayItems.map(item => (
          <div key={item.id} className={`bg-gray-800/50 rounded-lg border border-gray-700 p-4 ${item.shown ? 'opacity-60' : ''}`}>
            <div className="flex items-start justify-between gap-3 mb-2">
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${CATEGORY_COLORS[item.category] || 'bg-gray-700 text-gray-400'}`}>
                  {item.category}
                </span>
                <h3 className="text-white font-medium">{item.title}</h3>
              </div>
              {!item.shown && (
                <button onClick={() => markAsShown(item.id)}
                  className="text-xs text-gray-500 hover:text-emerald-400 shrink-0 transition-colors">
                  Mark shown
                </button>
              )}
            </div>
            <div className="prose prose-invert prose-sm max-w-none prose-headings:text-gray-200 prose-headings:mt-3 prose-headings:mb-1 prose-p:text-gray-300 prose-p:my-1 prose-strong:text-gray-200 prose-em:text-gray-300 prose-li:text-gray-300 prose-li:my-0.5 prose-code:text-amber-300 prose-code:bg-gray-900/60 prose-code:px-1 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-a:text-indigo-400 hover:prose-a:text-indigo-300 prose-blockquote:text-gray-400 prose-blockquote:border-gray-600">
              <ReactMarkdown>{item.content}</ReactMarkdown>
            </div>
            <div className="text-xs text-gray-600 mt-2">
              {new Date(item.created_at).toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

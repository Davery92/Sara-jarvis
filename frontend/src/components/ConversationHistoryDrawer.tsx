import { useState, useEffect, useCallback, useRef } from 'react'
import { History, Search, Plus, X, MessageSquare } from 'lucide-react'
import { APP_CONFIG } from '../config'

/**
 * ConversationHistoryDrawer — browse, search, and resume past conversations (P1.1).
 *
 * The chat already persists & resumes the *active* conversation; this adds the
 * missing half: seeing the full history and jumping between threads. Lists
 * /api/conversations/list and searches across all of them via
 * /api/conversations/search (both episode-backed, already on the server).
 */

interface ConversationSummary {
  conversation_id: string
  first_message: string
  message_count: number
  last_activity: string
  created_at: string
}

interface Props {
  open: boolean
  onClose: () => void
  currentConversationId: string | null
  onSelect: (conversationId: string) => void
  onNewChat: () => void
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'just now'
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function ConversationHistoryDrawer({
  open,
  onClose,
  currentConversationId,
  onSelect,
  onNewChat,
}: Props) {
  const [items, setItems] = useState<ConversationSummary[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadRecent = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/conversations/list?limit=50`, {
        credentials: 'include',
      })
      if (res.ok) setItems(await res.json())
    } catch {
      /* ignore — keep last list */
    } finally {
      setLoading(false)
    }
  }, [])

  // Load recent when the drawer opens.
  useEffect(() => {
    if (open) {
      setQuery('')
      loadRecent()
    }
  }, [open, loadRecent])

  // Debounced search.
  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const q = query.trim()
    if (q.length < 2) {
      setSearching(false)
      if (q.length === 0) loadRecent()
      return
    }
    setSearching(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(
          `${APP_CONFIG.apiUrl}/api/conversations/search?q=${encodeURIComponent(q)}&limit=30`,
          { credentials: 'include' }
        )
        if (res.ok) setItems(await res.json())
      } catch {
        /* ignore */
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, open, loadRecent])

  // Close on Escape.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Panel */}
      <div className="w-full max-w-sm bg-gray-900 border-l border-gray-700 flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <div className="flex items-center gap-2 text-gray-200">
            <History size={16} />
            <span className="text-sm font-semibold">Conversations</span>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white" title="Close">
            <X size={18} />
          </button>
        </div>

        {/* New chat */}
        <button
          onClick={() => { onNewChat(); onClose() }}
          className="m-3 flex items-center justify-center gap-2 rounded-md bg-teal-600 hover:bg-teal-500 px-3 py-2 text-sm text-white transition-colors"
        >
          <Plus size={16} /> New chat
        </button>

        {/* Search */}
        <div className="px-3 pb-2">
          <div className="flex items-center gap-2 rounded-md bg-gray-800 border border-gray-700 px-2.5 py-1.5">
            <Search size={14} className="text-gray-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search all conversations…"
              className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 focus:outline-none"
              autoFocus
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {(loading || searching) && (
            <div className="px-3 py-4 text-xs text-gray-500">
              {searching ? 'Searching…' : 'Loading…'}
            </div>
          )}
          {!loading && !searching && items.length === 0 && (
            <div className="px-3 py-4 text-xs text-gray-500 italic">
              {query.trim().length >= 2 ? 'No matches.' : 'No conversations yet.'}
            </div>
          )}
          <ul className="space-y-1">
            {items.map((c) => {
              const isCurrent = c.conversation_id === currentConversationId
              return (
                <li key={c.conversation_id}>
                  <button
                    onClick={() => { onSelect(c.conversation_id); onClose() }}
                    className={`w-full text-left rounded-md px-3 py-2 transition-colors border ${
                      isCurrent
                        ? 'bg-teal-500/10 border-teal-500/40'
                        : 'bg-gray-800/50 border-transparent hover:bg-gray-800 hover:border-gray-700'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <MessageSquare size={14} className="mt-0.5 shrink-0 text-gray-500" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-gray-100">
                          {c.first_message || 'Conversation'}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-gray-500">
                          <span>{timeAgo(c.last_activity)}</span>
                          <span>·</span>
                          <span>{c.message_count} msg{c.message_count === 1 ? '' : 's'}</span>
                          {isCurrent && <span className="text-teal-400">· current</span>}
                        </div>
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </div>
  )
}

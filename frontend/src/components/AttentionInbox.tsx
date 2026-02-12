import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import type { AttentionItem } from '../types/autonomy'

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  urgent: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  high: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  normal: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  low: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const STATUS_ICONS: Record<string, string> = {
  new: 'fiber_new',
  sent: 'send',
  read: 'done',
  archived: 'archive',
}

export default function AttentionInbox() {
  const [items, setItems] = useState<AttentionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const loadItems = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/attention?limit=50`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setItems(data.items || [])
      }
    } catch (err) {
      console.error('Failed to load attention items:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadItems()
    const interval = setInterval(loadItems, 30000)
    return () => clearInterval(interval)
  }, [loadItems])

  const markRead = async (id: string) => {
    await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/attention/${id}/read`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  const archiveItem = async (id: string) => {
    await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/attention/${id}/archive`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  const archiveAll = async () => {
    await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/attention/archive-all`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  if (loading) {
    return <div className="p-4 text-gray-400">Loading attention items...</div>
  }

  const unread = items.filter(i => i.status === 'new' || i.status === 'sent').length

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="material-icons text-teal-400">inbox</span>
          <h3 className="text-lg font-medium text-white">Attention Queue</h3>
          {unread > 0 && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-teal-500/20 text-teal-400">
              {unread} unread
            </span>
          )}
        </div>
        {items.length > 0 && (
          <button
            onClick={archiveAll}
            className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-white/5"
          >
            Archive all
          </button>
        )}
      </div>

      {items.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <span className="material-icons text-4xl mb-2 block">check_circle</span>
          No attention items
        </div>
      ) : (
        <div className="space-y-2">
          {items.map(item => (
            <div
              key={item.id}
              className={`rounded-lg border p-3 cursor-pointer transition-all ${
                item.status === 'new'
                  ? 'border-teal-500/30 bg-teal-500/5'
                  : 'border-white/10 bg-white/5'
              }`}
              onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${PRIORITY_COLORS[item.priority] || PRIORITY_COLORS.normal}`}>
                      {item.priority}
                    </span>
                    <span className="text-xs text-gray-500">{item.category}</span>
                    <span className="material-icons text-sm text-gray-500">
                      {STATUS_ICONS[item.status] || 'circle'}
                    </span>
                  </div>
                  <p className="text-sm text-white truncate">{item.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {new Date(item.created_at).toLocaleString()} &middot; {item.source}
                  </p>
                </div>
                <div className="flex gap-1 shrink-0">
                  {item.status === 'new' && (
                    <button
                      onClick={(e) => { e.stopPropagation(); markRead(item.id) }}
                      className="p-1 rounded hover:bg-white/10"
                      title="Mark read"
                    >
                      <span className="material-icons text-sm text-gray-400">done</span>
                    </button>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); archiveItem(item.id) }}
                    className="p-1 rounded hover:bg-white/10"
                    title="Archive"
                  >
                    <span className="material-icons text-sm text-gray-400">archive</span>
                  </button>
                </div>
              </div>

              {expandedId === item.id && item.body && (
                <div className="mt-2 pt-2 border-t border-white/10 text-sm text-gray-300 whitespace-pre-wrap">
                  {item.body}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

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
  completed: 'check_circle',
}

interface AttentionAction {
  id: string
  label: string
  kind: string
  target?: string
  prompt?: string
  url?: string
  default_minutes?: number
  minutes?: number
}

interface PendingInput {
  itemId: string
  action: AttentionAction
}

interface HITLReplyState {
  itemId: string
  message: string
  sending: boolean
}

interface AttentionInboxProps {
  onStartChat?: (prompt: string) => void
  onOpenNote?: (noteId: string) => void
}

const DAILY_REPORT_PREFIX = "Sara's Daily Report"

async function findDailyReportNoteId(item: AttentionItem): Promise<string | null> {
  // Notification title is "Sara's Daily Report — N sessions yesterday" (no date).
  // The actual *note* title is "Sara's Daily Report — YYYY-MM-DD". The date
  // lives in dedupe_key (e.g. "daily_report:2026-04-25"). Try keys in that
  // order, then fall back to a prefix search.
  try {
    let reportDate = ''
    const dedupeKey = item.dedupe_key || ''
    if (dedupeKey.startsWith('daily_report:')) {
      reportDate = dedupeKey.slice('daily_report:'.length).trim()
    }
    if (!reportDate) {
      const m = (item.title || '').match(/\b\d{4}-\d{2}-\d{2}\b/)
      if (m) reportDate = m[0]
    }

    const query = reportDate
      ? `${DAILY_REPORT_PREFIX} — ${reportDate}`
      : DAILY_REPORT_PREFIX

    const res = await fetch(
      `${APP_CONFIG.apiUrl}/notes/search?q=${encodeURIComponent(query)}`,
      { credentials: 'include' },
    )
    if (!res.ok) return null
    const data = await res.json()
    if (!Array.isArray(data) || data.length === 0) return null

    // Prefer exact title match for the resolved date
    if (reportDate) {
      const target = `${DAILY_REPORT_PREFIX} — ${reportDate}`.trim().toLowerCase()
      const exact = data.find((n: any) => (n.title || '').trim().toLowerCase() === target)
      if (exact?.id) return String(exact.id)
    }
    // Fall back to most-recent matching prefix
    const prefix = data.find((n: any) =>
      (n.title || '').trim().startsWith(DAILY_REPORT_PREFIX),
    )
    return prefix?.id ? String(prefix.id) : (data[0]?.id ? String(data[0].id) : null)
  } catch {
    return null
  }
}

// Quick-pick time helpers
function hoursFromNow(hours: number): string {
  return new Date(Date.now() + hours * 3600_000).toISOString()
}

function tomorrowAt9am(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(9, 0, 0, 0)
  return d.toISOString()
}

export default function AttentionInbox({ onStartChat, onOpenNote }: AttentionInboxProps) {
  const [items, setItems] = useState<AttentionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [pendingInput, setPendingInput] = useState<PendingInput | null>(null)
  const [customDateTime, setCustomDateTime] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const [hitlReply, setHitlReply] = useState<HITLReplyState | null>(null)

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const submitHitlReply = async (itemId: string, message: string) => {
    if (!message.trim()) return
    setHitlReply(prev => prev ? { ...prev, sending: true } : null)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/${itemId}/reply`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
      if (res.ok) {
        showToast('Reply sent to Sara')
        setHitlReply(null)
        loadItems()
      } else {
        showToast('Failed to send reply')
      }
    } catch (err) {
      console.error('HITL reply failed:', err)
      showToast('Failed to send reply')
    } finally {
      setHitlReply(prev => prev ? { ...prev, sending: false } : null)
    }
  }

  const isHitlRequest = (item: AttentionItem): boolean => {
    return item.payload?.type === 'human_input_request'
  }

  const loadItems = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention?limit=50`, {
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
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/${id}/read`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  const markEngaged = async (id: string) => {
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/${id}/engage`, {
      method: 'POST', credentials: 'include',
    })
  }

  const archiveItem = async (id: string) => {
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/${id}/archive`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  const archiveAll = async () => {
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/attention/archive-all`, {
      method: 'POST', credentials: 'include',
    })
    loadItems()
  }

  const getActions = (item: AttentionItem): AttentionAction[] => {
    const actions = item.payload?.actions
    return Array.isArray(actions) ? actions.filter((a): a is AttentionAction =>
      !!a && typeof a.id === 'string' && typeof a.label === 'string' && typeof a.kind === 'string'
    ) : []
  }

  const handleDirective = (directive?: { type?: string; target?: string; prompt?: string; url?: string }) => {
    if (!directive?.type) return
    if (directive.type === 'navigate' && directive.target) {
      window.dispatchEvent(new CustomEvent('navigate', { detail: { view: directive.target } }))
      return
    }
    if (directive.type === 'open_url' && directive.url) {
      window.open(directive.url, '_blank')
      return
    }
    if (directive.type === 'chat') {
      const prompt = directive.prompt || 'Help me work through this.'
      if (onStartChat) {
        onStartChat(prompt)
      } else {
        window.dispatchEvent(new CustomEvent('navigate', { detail: { view: 'chat' } }))
      }
    }
    if (directive.type === 'hitl_reply') {
      // Open inline reply for this item
      const itemId = (directive as any).item_id
      if (itemId) {
        setHitlReply({ itemId, message: '', sending: false })
        setExpandedId(itemId)
      }
    }
  }

  const runAction = async (itemId: string, action: AttentionAction, extraParams?: Record<string, any>) => {
    const busyKey = `${itemId}:${action.id}`
    setActionBusy(busyKey)
    try {
      const fetchOpts: RequestInit = {
        method: 'POST',
        credentials: 'include',
      }
      if (extraParams) {
        fetchOpts.headers = { 'Content-Type': 'application/json' }
        fetchOpts.body = JSON.stringify(extraParams)
      }
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/autonomy/attention/${itemId}/actions/${action.id}`,
        fetchOpts,
      )
      if (!res.ok) return
      const data = await res.json()
      handleDirective(data.directive)
      // Show confirmation toasts
      if (data.reminder) {
        const when = new Date(data.reminder.reminder_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
        showToast(`Reminder set for ${when}`)
      }
      if (data.calendar_event) {
        const when = new Date(data.calendar_event.start_time).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
        showToast(`Calendar event created for ${when}`)
      }
      if (data.status === 'completed') {
        showToast('Marked as done')
      }
      await loadItems()
    } finally {
      setActionBusy(null)
      setPendingInput(null)
    }
  }

  const handleActionClick = (e: React.MouseEvent, itemId: string, action: AttentionAction) => {
    e.stopPropagation()
    // HITL reply — open inline reply directly
    if (action.kind === 'hitl_reply') {
      setHitlReply({ itemId, message: '', sending: false })
      setExpandedId(itemId)
      return
    }
    // Actions that need user input
    if (action.kind === 'add_reminder') {
      setPendingInput({ itemId, action })
      setCustomDateTime('')
      return
    }
    if (action.kind === 'add_calendar') {
      setPendingInput({ itemId, action })
      setCustomDateTime('')
      return
    }
    runAction(itemId, action)
  }

  const handleQuickPick = (hours: number | 'tomorrow9am') => {
    if (!pendingInput) return
    const time = hours === 'tomorrow9am' ? tomorrowAt9am() : hoursFromNow(hours as number)
    if (pendingInput.action.kind === 'add_reminder') {
      runAction(pendingInput.itemId, pendingInput.action, { reminder_time: time })
    } else if (pendingInput.action.kind === 'add_calendar') {
      runAction(pendingInput.itemId, pendingInput.action, { start_time: time })
    }
  }

  const handleCustomTimeSubmit = () => {
    if (!pendingInput || !customDateTime) return
    const isoTime = new Date(customDateTime).toISOString()
    if (pendingInput.action.kind === 'add_reminder') {
      runAction(pendingInput.itemId, pendingInput.action, { reminder_time: isoTime })
    } else if (pendingInput.action.kind === 'add_calendar') {
      runAction(pendingInput.itemId, pendingInput.action, { start_time: isoTime })
    }
  }

  if (loading) {
    return <div className="p-4 text-gray-400">Loading attention items...</div>
  }

  const unread = items.filter(i => i.status === 'new' || i.status === 'sent').length

  return (
    <div className="space-y-3">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 px-4 py-2 bg-teal-600 text-white text-sm rounded-lg shadow-lg animate-fade-in">
          {toast}
        </div>
      )}

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
          {items.map(item => {
            const isCompleted = item.status === 'completed'
            const isHitl = isHitlRequest(item)
            return (
              <div
                key={item.id}
                className={`rounded-lg border p-3 cursor-pointer transition-all ${
                  isCompleted
                    ? 'border-green-500/20 bg-green-500/5 opacity-60'
                    : isHitl && item.status !== 'completed'
                      ? 'border-orange-500/40 bg-orange-500/10 animate-pulse-slow'
                      : item.status === 'new'
                        ? 'border-teal-500/30 bg-teal-500/5'
                        : 'border-white/10 bg-white/5'
                }`}
                onClick={() => {
                  const isExpanding = expandedId !== item.id
                  setExpandedId(isExpanding ? item.id : null)
                  if (isExpanding && (item.status === 'new' || item.status === 'sent')) {
                    markEngaged(item.id)
                  }
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs px-1.5 py-0.5 rounded border ${PRIORITY_COLORS[item.priority] || PRIORITY_COLORS.normal}`}>
                        {item.priority}
                      </span>
                      <span className="text-xs text-gray-500">{item.category}</span>
                      <span className={`material-icons text-sm ${isCompleted ? 'text-green-400' : 'text-gray-500'}`}>
                        {STATUS_ICONS[item.status] || 'circle'}
                      </span>
                    </div>
                    <p className={`text-sm truncate ${isCompleted ? 'text-gray-400 line-through' : 'text-white'}`}>{item.title}</p>
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
                    {!isCompleted && (
                      <button
                        onClick={(e) => { e.stopPropagation(); archiveItem(item.id) }}
                        className="p-1 rounded hover:bg-white/10"
                        title="Archive"
                      >
                        <span className="material-icons text-sm text-gray-400">archive</span>
                      </button>
                    )}
                  </div>
                </div>

                {expandedId === item.id && (
                  <>
                    {/* Daily-report shortcut — the daily-report notification's payload
                        doesn't carry the note_id, so look it up by title. */}
                    {item.title?.startsWith(DAILY_REPORT_PREFIX) && onOpenNote && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <button
                          onClick={async (e) => {
                            e.stopPropagation()
                            const noteId =
                              (item.payload as any)?.note_id ||
                              (await findDailyReportNoteId(item))
                            if (noteId) {
                              onOpenNote(noteId)
                            } else {
                              showToast("Couldn't find the report note")
                            }
                          }}
                          className="px-3 py-1.5 text-xs rounded border border-teal-500/30 text-teal-300 hover:bg-teal-500/10"
                        >
                          Open full report
                        </button>
                      </div>
                    )}
                    {item.body && (
                      <div className="mt-2 pt-2 border-t border-white/10 text-sm text-gray-300 whitespace-pre-wrap">
                        {item.body}
                      </div>
                    )}
                    {!isCompleted && getActions(item).length > 0 && (
                      <div className={`${item.body ? 'mt-3' : 'mt-2 pt-2 border-t border-white/10'} flex flex-wrap gap-2`}>
                        {getActions(item).map((action) => {
                          const busy = actionBusy === `${item.id}:${action.id}`
                          return (
                            <button
                              key={action.id}
                              onClick={(e) => handleActionClick(e, item.id, action)}
                              disabled={busy}
                              className={`px-2.5 py-1.5 text-xs rounded border disabled:opacity-50 ${
                                action.kind === 'complete'
                                  ? 'border-green-500/30 text-green-300 hover:bg-green-500/10'
                                  : 'border-teal-500/30 text-teal-300 hover:bg-teal-500/10'
                              }`}
                            >
                              {busy ? 'Working...' : action.label}
                            </button>
                          )
                        })}
                      </div>
                    )}

                    {/* Quick-pick time picker for add_reminder */}
                    {pendingInput && pendingInput.itemId === item.id && pendingInput.action.kind === 'add_reminder' && (
                      <div className="mt-2 pt-2 border-t border-white/10" onClick={(e) => e.stopPropagation()}>
                        <p className="text-xs text-gray-400 mb-2">Remind me in:</p>
                        <div className="flex flex-wrap gap-2">
                          <button onClick={() => handleQuickPick(1)} className="px-2.5 py-1 text-xs rounded bg-teal-500/20 text-teal-300 hover:bg-teal-500/30">1h</button>
                          <button onClick={() => handleQuickPick(3)} className="px-2.5 py-1 text-xs rounded bg-teal-500/20 text-teal-300 hover:bg-teal-500/30">3h</button>
                          <button onClick={() => handleQuickPick('tomorrow9am')} className="px-2.5 py-1 text-xs rounded bg-teal-500/20 text-teal-300 hover:bg-teal-500/30">Tomorrow 9am</button>
                          <div className="flex gap-1">
                            <input
                              type="datetime-local"
                              value={customDateTime}
                              onChange={(e) => setCustomDateTime(e.target.value)}
                              className="px-2 py-1 text-xs rounded bg-white/10 text-white border border-white/20"
                            />
                            <button
                              onClick={handleCustomTimeSubmit}
                              disabled={!customDateTime}
                              className="px-2 py-1 text-xs rounded bg-teal-500/20 text-teal-300 hover:bg-teal-500/30 disabled:opacity-30"
                            >
                              Set
                            </button>
                          </div>
                          <button onClick={() => setPendingInput(null)} className="px-2 py-1 text-xs rounded text-gray-400 hover:text-white">Cancel</button>
                        </div>
                      </div>
                    )}

                    {/* Calendar time picker for add_calendar */}
                    {pendingInput && pendingInput.itemId === item.id && pendingInput.action.kind === 'add_calendar' && (
                      <div className="mt-2 pt-2 border-t border-white/10" onClick={(e) => e.stopPropagation()}>
                        <p className="text-xs text-gray-400 mb-2">Schedule event:</p>
                        <div className="flex gap-2 items-center">
                          <input
                            type="datetime-local"
                            value={customDateTime}
                            onChange={(e) => setCustomDateTime(e.target.value)}
                            className="px-2 py-1 text-xs rounded bg-white/10 text-white border border-white/20"
                          />
                          <button
                            onClick={handleCustomTimeSubmit}
                            disabled={!customDateTime}
                            className="px-2.5 py-1 text-xs rounded bg-teal-500/20 text-teal-300 hover:bg-teal-500/30 disabled:opacity-30"
                          >
                            Create
                          </button>
                          <button onClick={() => setPendingInput(null)} className="px-2 py-1 text-xs rounded text-gray-400 hover:text-white">Cancel</button>
                        </div>
                      </div>
                    )}

                    {/* HITL inline reply */}
                    {isHitl && !isCompleted && (
                      <div className="mt-3 pt-3 border-t border-orange-500/20" onClick={(e) => e.stopPropagation()}>
                        {item.payload?.question && (
                          <div className="mb-2 px-3 py-2 rounded bg-orange-500/10 border border-orange-500/20">
                            <p className="text-xs text-orange-400 font-medium mb-1">Sara is asking:</p>
                            <p className="text-sm text-white">{item.payload.question}</p>
                          </div>
                        )}
                        <div className="flex gap-2">
                          <input
                            type="text"
                            placeholder="Type your reply..."
                            value={hitlReply?.itemId === item.id ? hitlReply.message : ''}
                            onChange={(e) => setHitlReply({ itemId: item.id, message: e.target.value, sending: false })}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !e.shiftKey && hitlReply?.message.trim()) {
                                e.preventDefault()
                                submitHitlReply(item.id, hitlReply.message)
                              }
                            }}
                            className="flex-1 px-3 py-2 text-sm rounded bg-white/10 text-white border border-orange-500/30 placeholder-gray-500 focus:outline-none focus:border-orange-400"
                            autoFocus={hitlReply?.itemId === item.id}
                          />
                          <button
                            onClick={() => hitlReply?.message.trim() && submitHitlReply(item.id, hitlReply.message)}
                            disabled={!hitlReply?.message.trim() || hitlReply?.sending}
                            className="px-3 py-2 text-sm rounded bg-orange-500/20 text-orange-300 hover:bg-orange-500/30 disabled:opacity-30 whitespace-nowrap"
                          >
                            {hitlReply?.sending ? 'Sending...' : 'Reply'}
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

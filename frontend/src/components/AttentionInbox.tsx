import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import type { AttentionItem } from '../types/autonomy'

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

interface FyiItem {
  id: string
  kind: string
  ref_id: string
  title: string
  body?: string | null
  priority: string
  source: string
  status: string
  unread: boolean
  created_at: string
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
  // The sidebar badge (compute_badge) counts needs-you + unread notifications,
  // but this screen used to only fetch /autonomy/attention (needs-you) — so
  // whenever there were unread notifications and zero pending attention items,
  // the badge said N while this screen said "nothing needs your attention."
  const [fyiItems, setFyiItems] = useState<FyiItem[]>([])
  const [fyiLoading, setFyiLoading] = useState(true)
  const [fyiBusy, setFyiBusy] = useState<string | null>(null)

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

  const loadFyi = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/assistant-inbox/unified?limit=50`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setFyiItems((data.fyi || []).filter((i: FyiItem) => i.unread))
      }
    } catch (err) {
      console.error('Failed to load FYI items:', err)
    } finally {
      setFyiLoading(false)
    }
  }, [])

  useEffect(() => {
    loadFyi()
    const interval = setInterval(loadFyi, 30000)
    return () => clearInterval(interval)
  }, [loadFyi])

  const fyiFeedback = async (item: FyiItem, action: 'read' | 'dismissed') => {
    if (item.kind !== 'notification') {
      setFyiItems(prev => prev.filter(i => i.id !== item.id))
      return
    }
    setFyiBusy(item.id)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/notifications/${item.ref_id}/feedback`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      if (res.ok) {
        setFyiItems(prev => prev.filter(i => i.id !== item.id))
      }
    } catch (err) {
      console.error('Failed to record notification feedback:', err)
    } finally {
      setFyiBusy(null)
    }
  }

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

  const rowBorder = (item: AttentionItem) => {
    if (item.status === 'completed') return 'border-transparent'
    if (isHitlRequest(item)) return 'border-orange-400/70'
    if (item.priority === 'critical' || item.priority === 'urgent') return 'border-rose-400/70'
    if (item.status === 'new' || item.status === 'sent') return 'border-amber-400/70'
    return 'border-transparent'
  }

  const miniButton =
    'rounded-md border border-white/10 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white disabled:opacity-50'
  const flatInput =
    'rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-slate-200 outline-none transition-colors focus:border-teal-300/30'

  if (loading) {
    return <p className="pt-2 text-sm text-slate-500">Loading…</p>
  }

  return (
    <div>
      {/* Toast */}
      {toast && (
        <div className="fixed right-4 top-4 z-50 rounded-md border-l-2 border-teal-300 bg-[#0c1626] px-4 py-2 text-sm text-slate-200 shadow-[0_8px_40px_rgba(2,8,23,0.6)]">
          {toast}
        </div>
      )}

      {items.length === 0 && !fyiLoading && fyiItems.length === 0 ? (
        <p className="pt-2 text-sm text-slate-500">Nothing needs your attention.</p>
      ) : items.length === 0 ? null : (
        <>
          <div className="flex justify-end pb-2">
            <button
              onClick={archiveAll}
              className="text-xs text-slate-500 transition-colors hover:text-teal-300"
            >
              Archive all
            </button>
          </div>

          <div className="space-y-1">
            {items.map(item => {
              const isCompleted = item.status === 'completed'
              const isHitl = isHitlRequest(item)
              return (
                <div
                  key={item.id}
                  className={`cursor-pointer border-l-2 px-3 py-2.5 transition-colors hover:bg-white/[0.04] ${rowBorder(item)} ${
                    isCompleted ? 'opacity-60' : ''
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
                    <div className="min-w-0 flex-1">
                      <p
                        className={`truncate text-[15px] ${
                          isCompleted ? 'text-slate-500 line-through' : 'text-slate-200'
                        }`}
                      >
                        {item.title}
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {item.priority !== 'normal' ? `${item.priority} · ` : ''}
                        {item.category} · {new Date(item.created_at).toLocaleString()} · {item.source}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-baseline gap-3 pt-0.5">
                      {item.status === 'new' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); markRead(item.id) }}
                          className="text-xs text-slate-500 transition-colors hover:text-slate-300"
                          title="Mark read"
                        >
                          Mark read
                        </button>
                      )}
                      {!isCompleted && (
                        <button
                          onClick={(e) => { e.stopPropagation(); archiveItem(item.id) }}
                          className="text-xs text-slate-500 transition-colors hover:text-slate-300"
                          title="Archive"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                  </div>

                  {expandedId === item.id && (
                    <>
                      {/* Daily-report shortcut — the daily-report notification's payload
                          doesn't carry the note_id, so look it up by title. */}
                      {item.title?.startsWith(DAILY_REPORT_PREFIX) && onOpenNote && (
                        <div className="mt-2 border-t border-white/8 pt-2">
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
                            className="text-xs text-teal-300/90 transition-colors hover:text-teal-200"
                          >
                            Open full report →
                          </button>
                        </div>
                      )}
                      {item.body && (
                        <div className="mt-2 whitespace-pre-wrap border-t border-white/8 pt-2 text-sm leading-relaxed text-slate-300">
                          {item.body}
                        </div>
                      )}
                      {!isCompleted && getActions(item).length > 0 && (
                        <div className={`${item.body ? 'mt-3' : 'mt-2 border-t border-white/8 pt-2'} flex flex-wrap gap-2`}>
                          {getActions(item).map((action) => {
                            const busy = actionBusy === `${item.id}:${action.id}`
                            return (
                              <button
                                key={action.id}
                                onClick={(e) => handleActionClick(e, item.id, action)}
                                disabled={busy}
                                className={miniButton}
                              >
                                {busy ? 'Working…' : action.label}
                              </button>
                            )
                          })}
                        </div>
                      )}

                      {/* Quick-pick time picker for add_reminder */}
                      {pendingInput && pendingInput.itemId === item.id && pendingInput.action.kind === 'add_reminder' && (
                        <div className="mt-2 border-t border-white/8 pt-2" onClick={(e) => e.stopPropagation()}>
                          <p className="mb-2 text-xs text-slate-500">Remind me in:</p>
                          <div className="flex flex-wrap items-center gap-2">
                            <button onClick={() => handleQuickPick(1)} className={miniButton}>1h</button>
                            <button onClick={() => handleQuickPick(3)} className={miniButton}>3h</button>
                            <button onClick={() => handleQuickPick('tomorrow9am')} className={miniButton}>Tomorrow 9am</button>
                            <div className="flex items-center gap-1">
                              <input
                                type="datetime-local"
                                value={customDateTime}
                                onChange={(e) => setCustomDateTime(e.target.value)}
                                className={flatInput}
                              />
                              <button
                                onClick={handleCustomTimeSubmit}
                                disabled={!customDateTime}
                                className={miniButton}
                              >
                                Set
                              </button>
                            </div>
                            <button
                              onClick={() => setPendingInput(null)}
                              className="text-xs text-slate-500 transition-colors hover:text-slate-300"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Calendar time picker for add_calendar */}
                      {pendingInput && pendingInput.itemId === item.id && pendingInput.action.kind === 'add_calendar' && (
                        <div className="mt-2 border-t border-white/8 pt-2" onClick={(e) => e.stopPropagation()}>
                          <p className="mb-2 text-xs text-slate-500">Schedule event:</p>
                          <div className="flex items-center gap-2">
                            <input
                              type="datetime-local"
                              value={customDateTime}
                              onChange={(e) => setCustomDateTime(e.target.value)}
                              className={flatInput}
                            />
                            <button
                              onClick={handleCustomTimeSubmit}
                              disabled={!customDateTime}
                              className={miniButton}
                            >
                              Create
                            </button>
                            <button
                              onClick={() => setPendingInput(null)}
                              className="text-xs text-slate-500 transition-colors hover:text-slate-300"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* HITL inline reply */}
                      {isHitl && !isCompleted && (
                        <div className="mt-3 border-t border-white/8 pt-3" onClick={(e) => e.stopPropagation()}>
                          {item.payload?.question && (
                            <div className="mb-2 border-l-2 border-orange-400/70 pl-3">
                              <p className="text-xs text-slate-500">Sara is asking</p>
                              <p className="mt-0.5 text-sm text-slate-200">{item.payload.question}</p>
                            </div>
                          )}
                          <div className="flex gap-2">
                            <input
                              type="text"
                              placeholder="Type your reply…"
                              value={hitlReply?.itemId === item.id ? hitlReply.message : ''}
                              onChange={(e) => setHitlReply({ itemId: item.id, message: e.target.value, sending: false })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey && hitlReply?.message.trim()) {
                                  e.preventDefault()
                                  submitHitlReply(item.id, hitlReply.message)
                                }
                              }}
                              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none transition-colors focus:border-teal-300/30"
                              autoFocus={hitlReply?.itemId === item.id}
                            />
                            <button
                              onClick={() => hitlReply?.message.trim() && submitHitlReply(item.id, hitlReply.message)}
                              disabled={!hitlReply?.message.trim() || hitlReply?.sending}
                              className="whitespace-nowrap rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
                            >
                              {hitlReply?.sending ? 'Sending…' : 'Reply'}
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
        </>
      )}

      {fyiItems.length > 0 && (
        <div className="mt-4">
          <p className="pb-2 text-xs uppercase tracking-wide text-slate-500">FYI</p>
          <div className="space-y-1">
            {fyiItems.map(item => (
              <div
                key={item.id}
                className="border-l-2 border-transparent px-3 py-2.5 transition-colors hover:bg-white/[0.04]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[15px] text-slate-300">{item.title}</p>
                    {item.body && (
                      <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{item.body}</p>
                    )}
                    <p className="mt-0.5 text-xs text-slate-600">
                      {item.source} · {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-baseline gap-3 pt-0.5">
                    <button
                      onClick={() => fyiFeedback(item, 'read')}
                      disabled={fyiBusy === item.id}
                      className="text-xs text-slate-500 transition-colors hover:text-slate-300 disabled:opacity-50"
                      title="Mark read"
                    >
                      Mark read
                    </button>
                    <button
                      onClick={() => fyiFeedback(item, 'dismissed')}
                      disabled={fyiBusy === item.id}
                      className="text-xs text-slate-500 transition-colors hover:text-slate-300 disabled:opacity-50"
                      title="Dismiss"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

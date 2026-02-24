import { useCallback, useEffect, useRef, useState } from 'react'
import { Flag, ChevronDown, ChevronUp, Eye, RotateCcw, X, Check, Loader2, Sparkles, MessageCircle, Send, Wifi } from 'lucide-react'
import { APP_CONFIG } from '../config'
import { useCanvasStore } from '../store/canvasStore'

interface MissionStep {
  id: string
  action_name: string
  description: string
  status: string
  error_message?: string
  result?: any
}

interface Mission {
  id: string
  title: string
  description?: string
  state: string
  source: string
  priority: string
  total_steps: number
  completed_steps: number
  current_step_index: number
  created_at: string
  completed_at?: string
  mission_metadata?: Record<string, any>
  steps?: MissionStep[]
}

interface FoundItem {
  type: 'email' | 'note' | 'attachment'
  id: string
  title: string
  download_url?: string
}

interface TaskDetail {
  id: string
  status: string
  result_note_id?: string
  output?: string
  mode?: string
  found_items?: FoundItem[]
  clarification_question?: string
}

const STATE_COLORS: Record<string, string> = {
  pending: 'text-gray-400',
  running: 'text-blue-400',
  awaiting_confirm: 'text-yellow-400',
  needs_clarification: 'text-orange-400',
  done: 'text-green-400',
  failed: 'text-red-400',
  cancelled: 'text-gray-500',
}

export default function MissionFeed() {
  const [missions, setMissions] = useState<Mission[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [justCompletedIds, setJustCompletedIds] = useState<Set<string>>(new Set())
  const [flashHeader, setFlashHeader] = useState(false)
  const [clarifyText, setClarifyText] = useState<Record<string, string>>({})
  const [sendingClarify, setSendingClarify] = useState<Record<string, boolean>>({})
  const [liveStatus, setLiveStatus] = useState<Record<string, { status: string; summary: string }>>({})
  const [wsConnected, setWsConnected] = useState(false)
  const prevStatesRef = useRef<Map<string, string>>(new Map())
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const openWindow = useCanvasStore((s) => s.openWindow)
  const openNoteWindow = useCanvasStore((s) => s.openNoteWindow)

  const fetchMissions = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions?limit=10`, {
        credentials: 'include',
      })
      if (!res.ok) return
      const data = await res.json()
      const newMissions: Mission[] = data.missions || []

      // Detect missions that just completed
      const prevStates = prevStatesRef.current
      const newlyCompleted: string[] = []
      for (const m of newMissions) {
        const prevState = prevStates.get(m.id)
        if (prevState && prevState !== 'done' && m.state === 'done') {
          newlyCompleted.push(m.id)
        }
      }

      // Update prev states
      const nextStates = new Map<string, string>()
      for (const m of newMissions) nextStates.set(m.id, m.state)
      prevStatesRef.current = nextStates

      setMissions(newMissions)

      // Handle newly completed missions
      if (newlyCompleted.length > 0) {
        setJustCompletedIds((prev) => {
          const next = new Set(prev)
          newlyCompleted.forEach((id) => next.add(id))
          return next
        })
        // Auto-expand the first completed mission and uncollapse the panel
        setExpandedId(newlyCompleted[0])
        setIsCollapsed(false)
        setFlashHeader(true)
        // Clear the flash after animation
        setTimeout(() => setFlashHeader(false), 3000)
        // Clear the "just completed" highlight after 10 seconds
        setTimeout(() => {
          setJustCompletedIds((prev) => {
            const next = new Set(prev)
            newlyCompleted.forEach((id) => next.delete(id))
            return next
          })
        }, 10000)
      }
    } catch {
      // silent
    }
  }, [])

  // WebSocket connection for real-time agent task progress events
  const connectWebSocket = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return

    try {
      const apiHost = new URL(APP_CONFIG.apiUrl).host
      const wsProtocol = APP_CONFIG.apiUrl.startsWith('https') ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${apiHost}/api/automation/stream`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'agent_task_progress' && data.data) {
            const { task_id, status, summary } = data.data
            setLiveStatus((prev) => ({
              ...prev,
              [task_id]: { status, summary },
            }))
            // Refresh missions on state changes
            fetchMissions()
          }
        } catch {
          // keepalive/pong messages
        }
      }

      ws.onclose = () => {
        wsRef.current = null
        setWsConnected(false)
        reconnectTimerRef.current = setTimeout(() => {
          connectWebSocket()
        }, 5000)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      // silent
    }
  }, [fetchMissions])

  useEffect(() => {
    fetchMissions()
    connectWebSocket()
    // Poll every 10s as fallback
    const interval = setInterval(fetchMissions, 10000)
    return () => {
      clearInterval(interval)
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [fetchMissions, connectWebSocket])

  // Keep WebSocket alive with pings
  useEffect(() => {
    const pingInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 25000)
    return () => clearInterval(pingInterval)
  }, [])

  // Auto-open results for newly completed missions
  const autoOpenedRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    for (const id of justCompletedIds) {
      if (autoOpenedRef.current.has(id)) continue
      autoOpenedRef.current.add(id)
      const mission = missions.find((m) => m.id === id)
      if (mission) {
        viewResult(mission)
      }
    }
  }, [justCompletedIds, missions])

  const fetchSteps = async (missionId: string) => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}`, {
        credentials: 'include',
      })
      if (!res.ok) return
      const detail = await res.json()
      setMissions((prev) =>
        prev.map((m) => (m.id === missionId ? { ...m, steps: detail.steps } : m))
      )
    } catch {
      // silent
    }
  }

  const retryMission = async (missionId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}/retry`, {
        method: 'POST',
        credentials: 'include',
      })
      fetchMissions()
    } catch {
      // silent
    }
  }

  const confirmMission = async (missionId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}/confirm`, {
        method: 'POST',
        credentials: 'include',
      })
      fetchMissions()
    } catch {
      // silent
    }
  }

  const cancelMission = async (missionId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}/cancel`, {
        method: 'POST',
        credentials: 'include',
      })
      fetchMissions()
    } catch {
      // silent
    }
  }

  const sendClarification = async (missionId: string) => {
    const text = clarifyText[missionId]?.trim()
    if (!text) return

    setSendingClarify((prev) => ({ ...prev, [missionId]: true }))
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}/action`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clarify', message: text }),
      })
      if (res.ok) {
        setClarifyText((prev) => ({ ...prev, [missionId]: '' }))
        fetchMissions()
      }
    } catch {
      // silent
    } finally {
      setSendingClarify((prev) => ({ ...prev, [missionId]: false }))
    }
  }

  const viewResult = async (mission: Mission) => {
    const taskId = mission.mission_metadata?.task_id
    if (!taskId) {
      openWindow('report', {
        title: mission.title,
        content: mission.description || 'No details available.',
      })
      return
    }

    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}`, {
        credentials: 'include',
      })
      if (!res.ok) return

      const task: TaskDetail = await res.json()

      // If the agent found specific items, open each in its own window
      if (task.found_items && task.found_items.length > 0) {
        // Always open the summary report first
        if (task.output) {
          openWindow('report', {
            title: mission.title.replace(/^Agent:\s*/, ''),
            content: task.output,
          })
        }

        // Open each found item in its own window
        for (const item of task.found_items.slice(0, 10)) {
          if (item.type === 'email') {
            openWindow('email', { emailId: item.id, initialQuery: '' }, {
              title: item.title || 'Email',
            })
          } else if (item.type === 'note') {
            try {
              const noteRes = await fetch(`${APP_CONFIG.apiUrl}/notes/${item.id}`, {
                credentials: 'include',
              })
              if (noteRes.ok) {
                const note = await noteRes.json()
                openNoteWindow(note.id, note.title || item.title, note.content || '')
              }
            } catch {
              openNoteWindow(item.id, item.title, '')
            }
          } else if (item.type === 'attachment' && item.download_url) {
            try {
              const attachRes = await fetch(`${APP_CONFIG.apiUrl}${item.download_url}`, {
                credentials: 'include',
              })
              if (attachRes.ok) {
                const blob = await attachRes.blob()
                const blobUrl = URL.createObjectURL(blob)
                const mimeType = attachRes.headers.get('Content-Type') || 'application/octet-stream'
                openWindow('fileviewer', {
                  filename: item.title || 'attachment',
                  content: blobUrl,
                  mimeType,
                  source: 'local' as const,
                }, { title: item.title || 'Attachment' })
              }
            } catch {
              openWindow('report', {
                title: item.title || 'Attachment',
                content: `Attachment: **${item.title}**\n\n[Download](${item.download_url})`,
              })
            }
          }
        }
        return
      }

      // No found_items -- fall back to result note or output
      if (task.result_note_id) {
        try {
          const noteRes = await fetch(`${APP_CONFIG.apiUrl}/notes/${task.result_note_id}`, {
            credentials: 'include',
          })
          if (noteRes.ok) {
            const note = await noteRes.json()
            openNoteWindow(note.id, note.title || 'Agent Result', note.content || '')
            return
          }
        } catch {
          // fall through
        }
      }

      if (task.output) {
        openWindow('report', {
          title: mission.title.replace(/^Agent:\s*/, ''),
          content: task.output,
        })
      }
    } catch {
      // silent
    }
  }

  // Helper to get live status for a mission
  const getLiveInfo = (mission: Mission) => {
    const taskId = mission.mission_metadata?.task_id
    if (taskId && liveStatus[taskId]) {
      return liveStatus[taskId]
    }
    return null
  }

  // Only show if there are missions
  const activeMissions = missions.filter((m) =>
    ['pending', 'running', 'awaiting_confirm', 'needs_clarification'].includes(m.state)
  )
  const recentDone = missions.filter((m) =>
    ['done', 'failed'].includes(m.state)
  ).slice(0, 3)

  const visible = [...activeMissions, ...recentDone]
  if (visible.length === 0) return null

  return (
    <div className="fixed top-6 right-6 z-50 w-[380px] max-w-[calc(100vw-2rem)] pointer-events-none">
      <div className={`bg-canvas-surface/90 backdrop-blur-md border rounded-xl shadow-xl pointer-events-auto transition-all duration-500 ${
        flashHeader ? 'border-teal-400 shadow-teal-500/30 shadow-lg' : 'border-canvas-border'
      }`}>
        {/* Header */}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="w-full flex items-center justify-between gap-2 p-3 text-xs uppercase tracking-wider text-canvas-muted hover:text-white transition-colors"
        >
          <div className="flex items-center gap-2">
            {flashHeader ? (
              <Sparkles size={14} className="text-teal-400 animate-pulse" />
            ) : (
              <Flag size={14} className="text-teal-400" />
            )}
            <span>{flashHeader ? 'Mission Complete!' : 'Missions'}</span>
            {activeMissions.length > 0 && (
              <span className="px-1.5 py-0.5 bg-teal-500/20 text-teal-400 rounded-full text-[10px]">
                {activeMissions.length}
              </span>
            )}
            {wsConnected && (
              <Wifi size={10} className="text-green-400" />
            )}
          </div>
          {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>

        {!isCollapsed && (
          <div className="px-3 pb-3 space-y-2 max-h-[60vh] overflow-y-auto">
            {visible.map((mission) => {
              const progress =
                mission.total_steps > 0
                  ? (mission.completed_steps / mission.total_steps) * 100
                  : 0
              const isExpanded = expandedId === mission.id
              const live = getLiveInfo(mission)
              const needsClarification = mission.state === 'needs_clarification' ||
                (mission.state === 'awaiting_confirm' && live?.status === 'needs_clarification')

              return (
                <div
                  key={mission.id}
                  className={`rounded-lg border overflow-hidden transition-all duration-700 ${
                    justCompletedIds.has(mission.id)
                      ? 'border-green-400/60 bg-green-500/10 shadow-sm shadow-green-500/20'
                      : needsClarification
                        ? 'border-orange-400/40 bg-orange-500/5'
                        : 'border-canvas-border bg-canvas-bg/70'
                  }`}
                >
                  {/* Mission row */}
                  <div
                    className="p-2.5 cursor-pointer hover:bg-canvas-elevated/50 transition-colors"
                    onClick={() => {
                      if (isExpanded) {
                        setExpandedId(null)
                      } else {
                        setExpandedId(mission.id)
                        if (!mission.steps) fetchSteps(mission.id)
                      }
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          {mission.state === 'running' && (
                            <Loader2 size={12} className="text-blue-400 animate-spin" />
                          )}
                          {needsClarification && (
                            <MessageCircle size={12} className="text-orange-400 animate-pulse" />
                          )}
                          <span
                            className={`text-[10px] uppercase font-medium ${STATE_COLORS[mission.state] || 'text-gray-400'}`}
                          >
                            {needsClarification ? 'needs input' : mission.state.replace('_', ' ')}
                          </span>
                          {mission.mission_metadata?.mode && (
                            <span className="text-[10px] text-gray-600">
                              {mission.mission_metadata.mode}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-white leading-tight truncate">
                          {mission.title.replace(/^Agent:\s*/, '')}
                        </p>

                        {/* Live status summary */}
                        {live && live.summary && mission.state === 'running' && (
                          <p className="text-[10px] text-blue-300/70 mt-0.5 truncate">
                            {live.summary}
                          </p>
                        )}

                        {/* Progress bar */}
                        {mission.total_steps > 0 && mission.state === 'running' && (
                          <div className="mt-1.5">
                            <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full bg-teal-500 transition-all duration-500"
                                style={{ width: `${progress}%` }}
                              />
                            </div>
                            <div className="text-[10px] text-gray-500 mt-0.5">
                              {mission.completed_steps}/{mission.total_steps} steps
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Action buttons */}
                      <div className="flex gap-1 shrink-0">
                        {mission.state === 'done' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              viewResult(mission)
                            }}
                            className="p-1 rounded hover:bg-teal-500/20 transition-colors"
                            title="View Result"
                          >
                            <Eye size={14} className="text-teal-400" />
                          </button>
                        )}
                        {mission.state === 'failed' && mission.source === 'agent_dispatch' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              retryMission(mission.id)
                            }}
                            className="p-1 rounded hover:bg-teal-500/20 transition-colors"
                            title="Retry"
                          >
                            <RotateCcw size={14} className="text-teal-400" />
                          </button>
                        )}
                        {mission.state === 'awaiting_confirm' && !needsClarification && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              confirmMission(mission.id)
                            }}
                            className="p-1 rounded hover:bg-green-500/20 transition-colors"
                            title="Confirm"
                          >
                            <Check size={14} className="text-green-400" />
                          </button>
                        )}
                        {['pending', 'running', 'awaiting_confirm', 'needs_clarification'].includes(mission.state) && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              cancelMission(mission.id)
                            }}
                            className="p-1 rounded hover:bg-red-500/20 transition-colors"
                            title="Cancel"
                          >
                            <X size={14} className="text-red-400" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Expanded steps + clarification */}
                  {isExpanded && (
                    <div className="px-2.5 pb-2.5 border-t border-canvas-border/50">
                      {mission.description && (
                        <p className="text-xs text-gray-400 mt-2 mb-1.5">{mission.description}</p>
                      )}

                      {/* Clarification input */}
                      {needsClarification && (
                        <div className="mt-2 mb-2 p-2 rounded-lg bg-orange-500/10 border border-orange-500/20">
                          <p className="text-[10px] text-orange-300 mb-1.5 flex items-center gap-1">
                            <MessageCircle size={10} />
                            Agent needs your input
                          </p>
                          {live?.summary && (
                            <p className="text-[10px] text-orange-200/80 mb-1.5">{live.summary}</p>
                          )}
                          <div className="flex gap-1.5">
                            <input
                              type="text"
                              value={clarifyText[mission.id] || ''}
                              onChange={(e) => setClarifyText((prev) => ({ ...prev, [mission.id]: e.target.value }))}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && !sendingClarify[mission.id]) {
                                  e.stopPropagation()
                                  sendClarification(mission.id)
                                }
                              }}
                              onClick={(e) => e.stopPropagation()}
                              placeholder="Type your response..."
                              className="flex-1 bg-black/20 border border-white/10 rounded px-2 py-1 text-[11px] text-white placeholder-gray-500 focus:outline-none focus:border-orange-500/40"
                            />
                            <button
                              onClick={(e) => { e.stopPropagation(); sendClarification(mission.id) }}
                              disabled={sendingClarify[mission.id] || !(clarifyText[mission.id]?.trim())}
                              className="p-1 rounded bg-orange-500/20 text-orange-300 hover:bg-orange-500/30 disabled:opacity-50 transition-colors"
                            >
                              {sendingClarify[mission.id] ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <Send size={12} />
                              )}
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Steps */}
                      {mission.steps ? (
                        <div className="space-y-0.5 mt-1.5">
                          {mission.steps.map((step) => (
                            <div key={step.id} className="flex items-start gap-1.5 text-xs py-0.5">
                              <div
                                className={`w-1.5 h-1.5 rounded-full shrink-0 mt-1.5 ${
                                  step.status === 'done'
                                    ? 'bg-green-400'
                                    : step.status === 'failed'
                                      ? 'bg-red-400'
                                      : step.status === 'running'
                                        ? 'bg-blue-400 animate-pulse'
                                        : 'bg-gray-600'
                                }`}
                              />
                              <div className="flex-1 min-w-0">
                                <span className="text-gray-300 truncate block">
                                  {step.description || step.action_name}
                                </span>
                                {step.error_message && (
                                  <span className="text-red-400 text-[10px] block truncate">
                                    {step.error_message}
                                  </span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500 mt-1.5">Loading steps...</p>
                      )}
                      <p className="text-[10px] text-gray-600 mt-2">
                        {new Date(mission.created_at).toLocaleString()}
                      </p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../config'
import type { Mission, MissionStep } from '../types/autonomy'

const STATE_COLORS: Record<string, string> = {
  pending: 'text-gray-400',
  running: 'text-blue-400',
  awaiting_confirm: 'text-yellow-400',
  needs_clarification: 'text-orange-400',
  done: 'text-green-400',
  failed: 'text-red-400',
  cancelled: 'text-gray-500',
}

const STATE_ICONS: Record<string, string> = {
  pending: 'hourglass_empty',
  running: 'play_circle',
  awaiting_confirm: 'help',
  needs_clarification: 'chat',
  done: 'check_circle',
  failed: 'error',
  cancelled: 'cancel',
}

export default function MissionPanel() {
  const [missions, setMissions] = useState<Mission[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<string | null>(null)
  const [clarifyText, setClarifyText] = useState<Record<string, string>>({})
  const [sendingClarify, setSendingClarify] = useState<Record<string, boolean>>({})
  const [liveStatus, setLiveStatus] = useState<Record<string, { status: string; summary: string }>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)

  const loadMissions = useCallback(async () => {
    try {
      const url = filter
        ? `${APP_CONFIG.apiUrl}/autonomy/missions?state=${filter}`
        : `${APP_CONFIG.apiUrl}/autonomy/missions`
      const res = await fetch(url, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setMissions(data.missions || [])
      }
    } catch (err) {
      console.error('Failed to load missions:', err)
    } finally {
      setLoading(false)
    }
  }, [filter])

  const loadMissionDetail = async (id: string) => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${id}`, {
        credentials: 'include',
      })
      if (res.ok) {
        const detail = await res.json()
        setMissions(prev =>
          prev.map(m => m.id === id ? { ...m, steps: detail.steps } : m)
        )
      }
    } catch (err) {
      console.error('Failed to load mission detail:', err)
    }
  }

  // WebSocket connection for real-time updates
  const connectWebSocket = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return

    try {
      const wsUrl = APP_CONFIG.apiUrl.replace('http', 'ws') + '/api/automation/stream'
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[MissionPanel] WebSocket connected')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'agent_task_progress' && data.data) {
            const { task_id, status, summary } = data.data
            setLiveStatus(prev => ({
              ...prev,
              [task_id]: { status, summary },
            }))
            // Refresh missions to pick up state changes
            loadMissions()
          }
        } catch {
          // keepalive or pong messages
        }
      }

      ws.onclose = () => {
        wsRef.current = null
        // Reconnect after 5 seconds
        reconnectTimerRef.current = window.setTimeout(() => {
          connectWebSocket()
        }, 5000)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch (err) {
      console.error('[MissionPanel] WebSocket error:', err)
    }
  }, [loadMissions])

  useEffect(() => {
    loadMissions()
    connectWebSocket()
    const interval = setInterval(loadMissions, 10000)
    return () => {
      clearInterval(interval)
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [loadMissions, connectWebSocket])

  // Send ping to keep WebSocket alive
  useEffect(() => {
    const pingInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 25000)
    return () => clearInterval(pingInterval)
  }, [])

  const confirmMission = async (id: string) => {
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${id}/confirm`, {
      method: 'POST', credentials: 'include',
    })
    loadMissions()
  }

  const cancelMission = async (id: string) => {
    await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${id}/cancel`, {
      method: 'POST', credentials: 'include',
    })
    loadMissions()
  }

  const retryMission = async (id: string) => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${id}/retry`, {
        method: 'POST', credentials: 'include',
      })
      if (res.ok) {
        loadMissions()
      } else {
        const data = await res.json()
        console.error('Retry failed:', data.detail)
      }
    } catch (err) {
      console.error('Failed to retry mission:', err)
    }
  }

  const sendClarification = async (missionId: string) => {
    const text = clarifyText[missionId]?.trim()
    if (!text) return

    setSendingClarify(prev => ({ ...prev, [missionId]: true }))
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/missions/${missionId}/action`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clarify', message: text }),
      })
      if (res.ok) {
        setClarifyText(prev => ({ ...prev, [missionId]: '' }))
        loadMissions()
      }
    } catch (err) {
      console.error('Failed to send clarification:', err)
    } finally {
      setSendingClarify(prev => ({ ...prev, [missionId]: false }))
    }
  }

  const toggleExpand = (id: string) => {
    if (expandedId === id) {
      setExpandedId(null)
    } else {
      setExpandedId(id)
      const mission = missions.find(m => m.id === id)
      if (mission && !mission.steps) {
        loadMissionDetail(id)
      }
    }
  }

  // Helper to get live status for a mission
  const getLiveInfo = (mission: Mission) => {
    const taskId = (mission as any).mission_metadata?.task_id || (mission.metadata as any)?.task_id
    if (taskId && liveStatus[taskId]) {
      return liveStatus[taskId]
    }
    return null
  }

  if (loading) {
    return <div className="p-4 text-gray-400">Loading missions...</div>
  }

  const filters = [
    { label: 'All', value: null },
    { label: 'Active', value: 'running' },
    { label: 'Pending', value: 'pending' },
    { label: 'Failed', value: 'failed' },
    { label: 'Done', value: 'done' },
  ]

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="material-icons text-teal-400">flag</span>
        <h3 className="text-lg font-medium text-white">Missions</h3>
        {wsRef.current && wsRef.current.readyState === WebSocket.OPEN && (
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" title="Live updates connected" />
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-1">
        {filters.map(f => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            className={`text-xs px-2 py-1 rounded ${
              filter === f.value
                ? 'bg-teal-500/20 text-teal-400'
                : 'text-gray-400 hover:bg-white/5'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {missions.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <span className="material-icons text-4xl mb-2 block">explore</span>
          No missions
        </div>
      ) : (
        <div className="space-y-2">
          {missions.map(mission => {
            const progress = mission.total_steps > 0
              ? (mission.completed_steps / mission.total_steps) * 100
              : 0
            const live = getLiveInfo(mission)
            const isRunning = mission.state === 'running'
            const needsClarification = mission.state === 'needs_clarification' ||
              (mission.state === 'awaiting_confirm' && live?.status === 'needs_clarification')

            return (
              <div
                key={mission.id}
                className={`rounded-lg border bg-white/5 p-3 cursor-pointer transition-all ${
                  isRunning ? 'border-blue-500/30' :
                  needsClarification ? 'border-orange-500/30' :
                  'border-white/10'
                }`}
                onClick={() => toggleExpand(mission.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {isRunning ? (
                        <span className="material-icons text-sm text-blue-400 animate-spin">autorenew</span>
                      ) : (
                        <span className={`material-icons text-sm ${STATE_COLORS[mission.state] || 'text-gray-400'}`}>
                          {STATE_ICONS[mission.state] || 'circle'}
                        </span>
                      )}
                      <span className="text-xs text-gray-500 capitalize">{mission.state.replace('_', ' ')}</span>
                      <span className="text-xs text-gray-600">{mission.source}</span>
                    </div>
                    <p className="text-sm text-white">{mission.title}</p>

                    {/* Live status summary */}
                    {live && live.summary && isRunning && (
                      <p className="text-xs text-blue-300/80 mt-1 truncate">
                        {live.summary}
                      </p>
                    )}

                    {/* Progress bar */}
                    {mission.total_steps > 0 && (
                      <div className="mt-2">
                        <div className="flex justify-between text-xs text-gray-500 mb-1">
                          <span>{mission.completed_steps}/{mission.total_steps} steps</span>
                          <span>{Math.round(progress)}%</span>
                        </div>
                        <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              mission.state === 'failed' ? 'bg-red-500' :
                              mission.state === 'done' ? 'bg-green-500' :
                              isRunning ? 'bg-teal-500 animate-pulse' : 'bg-teal-500'
                            }`}
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex gap-1 shrink-0">
                    {mission.state === 'failed' && mission.source === 'agent_dispatch' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); retryMission(mission.id) }}
                        className="p-1 rounded hover:bg-teal-500/20"
                        title="Retry"
                      >
                        <span className="material-icons text-sm text-teal-400">replay</span>
                      </button>
                    )}
                    {mission.state === 'awaiting_confirm' && !needsClarification && (
                      <button
                        onClick={(e) => { e.stopPropagation(); confirmMission(mission.id) }}
                        className="p-1 rounded hover:bg-green-500/20"
                        title="Confirm"
                      >
                        <span className="material-icons text-sm text-green-400">check</span>
                      </button>
                    )}
                    {['pending', 'running', 'awaiting_confirm', 'needs_clarification'].includes(mission.state) && (
                      <button
                        onClick={(e) => { e.stopPropagation(); cancelMission(mission.id) }}
                        className="p-1 rounded hover:bg-red-500/20"
                        title="Cancel"
                      >
                        <span className="material-icons text-sm text-red-400">close</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded: Steps + Clarification */}
                {expandedId === mission.id && (
                  <div className="mt-3 pt-3 border-t border-white/10">
                    {mission.description && (
                      <p className="text-xs text-gray-400 mb-2">{mission.description}</p>
                    )}

                    {/* Clarification input */}
                    {needsClarification && (
                      <div className="mb-3 p-2 rounded-lg bg-orange-500/10 border border-orange-500/20">
                        <p className="text-xs text-orange-300 mb-2 flex items-center gap-1">
                          <span className="material-icons text-xs">chat</span>
                          Agent needs clarification
                        </p>
                        {live?.summary && (
                          <p className="text-xs text-orange-200/80 mb-2">{live.summary}</p>
                        )}
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={clarifyText[mission.id] || ''}
                            onChange={(e) => setClarifyText(prev => ({ ...prev, [mission.id]: e.target.value }))}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !sendingClarify[mission.id]) {
                                e.stopPropagation()
                                sendClarification(mission.id)
                              }
                            }}
                            onClick={(e) => e.stopPropagation()}
                            placeholder="Type your response..."
                            className="flex-1 bg-black/20 border border-white/10 rounded px-2 py-1 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-orange-500/40"
                          />
                          <button
                            onClick={(e) => { e.stopPropagation(); sendClarification(mission.id) }}
                            disabled={sendingClarify[mission.id] || !(clarifyText[mission.id]?.trim())}
                            className="px-2 py-1 rounded bg-orange-500/20 text-orange-300 text-xs hover:bg-orange-500/30 disabled:opacity-50"
                          >
                            {sendingClarify[mission.id] ? 'Sending...' : 'Send'}
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Steps */}
                    {mission.steps ? (
                      <div className="space-y-1">
                        {mission.steps.map(step => (
                          <div
                            key={step.id}
                            className="flex items-start gap-2 text-xs py-1"
                          >
                            <span className={`material-icons text-xs mt-0.5 ${
                              step.status === 'done' ? 'text-green-400' :
                              step.status === 'failed' ? 'text-red-400' :
                              step.status === 'running' ? 'text-blue-400 animate-spin' :
                              'text-gray-500'
                            }`}>
                              {step.status === 'done' ? 'check_circle' :
                               step.status === 'failed' ? 'error' :
                               step.status === 'running' ? 'autorenew' :
                               'radio_button_unchecked'}
                            </span>
                            <div className="flex-1 min-w-0">
                              <span className="text-gray-300">{step.description || step.action_name}</span>
                              {step.error_message && (
                                <p className="text-red-400 text-xs mt-0.5 truncate">({step.error_message})</p>
                              )}
                              {step.result && step.status === 'done' && (
                                <p className="text-gray-500 text-xs mt-0.5 truncate">
                                  {typeof step.result === 'string' ? step.result : JSON.stringify(step.result).slice(0, 100)}
                                </p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-gray-500">Loading steps...</p>
                    )}

                    {/* Completion summary */}
                    {mission.state === 'done' && mission.description && (
                      <div className="mt-2 p-2 rounded bg-green-500/10 border border-green-500/20">
                        <p className="text-xs text-green-300">Completed</p>
                      </div>
                    )}

                    <p className="text-xs text-gray-600 mt-2">
                      Created {new Date(mission.created_at).toLocaleString()}
                    </p>
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

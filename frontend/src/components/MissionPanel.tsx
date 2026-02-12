import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import type { Mission } from '../types/autonomy'

const STATE_COLORS: Record<string, string> = {
  pending: 'text-gray-400',
  running: 'text-blue-400',
  awaiting_confirm: 'text-yellow-400',
  done: 'text-green-400',
  failed: 'text-red-400',
  cancelled: 'text-gray-500',
}

const STATE_ICONS: Record<string, string> = {
  pending: 'hourglass_empty',
  running: 'play_circle',
  awaiting_confirm: 'help',
  done: 'check_circle',
  failed: 'error',
  cancelled: 'cancel',
}

export default function MissionPanel() {
  const [missions, setMissions] = useState<Mission[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<string | null>(null)

  const loadMissions = useCallback(async () => {
    try {
      const url = filter
        ? `${APP_CONFIG.API_BASE_URL}/autonomy/missions?state=${filter}`
        : `${APP_CONFIG.API_BASE_URL}/autonomy/missions`
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
      const res = await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/missions/${id}`, {
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

  useEffect(() => {
    loadMissions()
    const interval = setInterval(loadMissions, 15000)
    return () => clearInterval(interval)
  }, [loadMissions])

  const confirmMission = async (id: string) => {
    await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/missions/${id}/confirm`, {
      method: 'POST', credentials: 'include',
    })
    loadMissions()
  }

  const cancelMission = async (id: string) => {
    await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/missions/${id}/cancel`, {
      method: 'POST', credentials: 'include',
    })
    loadMissions()
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

  if (loading) {
    return <div className="p-4 text-gray-400">Loading missions...</div>
  }

  const filters = [
    { label: 'All', value: null },
    { label: 'Active', value: 'running' },
    { label: 'Pending', value: 'pending' },
    { label: 'Done', value: 'done' },
  ]

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="material-icons text-teal-400">flag</span>
        <h3 className="text-lg font-medium text-white">Missions</h3>
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

            return (
              <div
                key={mission.id}
                className="rounded-lg border border-white/10 bg-white/5 p-3 cursor-pointer"
                onClick={() => toggleExpand(mission.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`material-icons text-sm ${STATE_COLORS[mission.state] || 'text-gray-400'}`}>
                        {STATE_ICONS[mission.state] || 'circle'}
                      </span>
                      <span className="text-xs text-gray-500 capitalize">{mission.state.replace('_', ' ')}</span>
                      <span className="text-xs text-gray-600">{mission.source}</span>
                    </div>
                    <p className="text-sm text-white">{mission.title}</p>

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
                              mission.state === 'done' ? 'bg-green-500' : 'bg-teal-500'
                            }`}
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex gap-1 shrink-0">
                    {mission.state === 'awaiting_confirm' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); confirmMission(mission.id) }}
                        className="p-1 rounded hover:bg-green-500/20"
                        title="Confirm"
                      >
                        <span className="material-icons text-sm text-green-400">check</span>
                      </button>
                    )}
                    {['pending', 'running', 'awaiting_confirm'].includes(mission.state) && (
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

                {/* Expanded: Steps */}
                {expandedId === mission.id && (
                  <div className="mt-3 pt-3 border-t border-white/10">
                    {mission.description && (
                      <p className="text-xs text-gray-400 mb-2">{mission.description}</p>
                    )}
                    {mission.steps ? (
                      <div className="space-y-1">
                        {mission.steps.map(step => (
                          <div
                            key={step.id}
                            className="flex items-center gap-2 text-xs py-1"
                          >
                            <span className={`material-icons text-xs ${
                              step.status === 'done' ? 'text-green-400' :
                              step.status === 'failed' ? 'text-red-400' :
                              step.status === 'running' ? 'text-blue-400' :
                              'text-gray-500'
                            }`}>
                              {step.status === 'done' ? 'check_circle' :
                               step.status === 'failed' ? 'error' :
                               step.status === 'running' ? 'play_circle' :
                               'radio_button_unchecked'}
                            </span>
                            <span className="text-gray-300">{step.description || step.action_name}</span>
                            {step.error_message && (
                              <span className="text-red-400 truncate ml-1">({step.error_message})</span>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-gray-500">Loading steps...</p>
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

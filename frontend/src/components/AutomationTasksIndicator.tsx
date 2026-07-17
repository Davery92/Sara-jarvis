import React, { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../config'

interface AutomationTask {
  id: string
  name: string
  original_intent: string
  description: string | null
  status: 'pending_confirmation' | 'active' | 'paused' | 'completed' | 'failed' | 'cancelled'
  schedule_type: string
  next_wake_at: string | null
  execution_count: number
  max_executions: number | null
  expires_at: string | null
  last_executed_at: string | null
  created_at: string
  consecutive_errors: number
  last_error: string | null
}

interface AutomationTasksIndicatorProps {
  onOpenAutomations?: () => void
}

export const AutomationTasksIndicator: React.FC<AutomationTasksIndicatorProps> = ({
  onOpenAutomations
}) => {
  const [tasks, setTasks] = useState<AutomationTask[]>([])
  const [isExpanded, setIsExpanded] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  // Fetch tasks
  const fetchTasks = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/tasks`, {
        credentials: 'include'
      })

      if (!response.ok) return

      const data = await response.json()
      setTasks(data || [])
    } catch (error) {
      console.error('Failed to fetch automation tasks:', error)
    }
  }, [])

  // Poll for tasks
  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 10000) // Poll every 10 seconds
    return () => clearInterval(interval)
  }, [fetchTasks])

  // Close panel when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setIsExpanded(false)
      }
    }

    if (isExpanded) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isExpanded])

  const activeTasks = tasks.filter(t => t.status === 'active')
  const pendingTasks = tasks.filter(t => t.status === 'pending_confirmation')
  const pausedTasks = tasks.filter(t => t.status === 'paused')
  const activeCount = activeTasks.length

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-400'
      case 'pending_confirmation': return 'text-yellow-400'
      case 'paused': return 'text-orange-400'
      case 'completed': return 'text-gray-400'
      case 'failed': return 'text-red-400'
      case 'cancelled': return 'text-gray-500'
      default: return 'text-gray-400'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active': return 'play_circle'
      case 'pending_confirmation': return 'pending'
      case 'paused': return 'pause_circle'
      case 'completed': return 'check_circle'
      case 'failed': return 'error'
      case 'cancelled': return 'cancel'
      default: return 'circle'
    }
  }

  const getScheduleIcon = (scheduleType: string) => {
    switch (scheduleType) {
      case 'interval': return 'update'
      case 'cron': return 'schedule'
      case 'one_time': return 'looks_one'
      case 'state_change': return 'sensors'
      default: return 'timer'
    }
  }

  const formatTime = (dateStr: string | null) => {
    if (!dateStr) return 'unknown'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`
    return date.toLocaleDateString()
  }

  const formatNextWake = (dateStr: string | null) => {
    if (!dateStr) return 'not scheduled'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = date.getTime() - now.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 0) return 'overdue'
    if (diffMins < 1) return 'now'
    if (diffMins < 60) return `in ${diffMins}m`
    if (diffMins < 1440) return `in ${Math.floor(diffMins / 60)}h`
    return date.toLocaleDateString()
  }

  const handleAction = async (taskId: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/tasks/${taskId}/${action}`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        fetchTasks()
      }
    } catch (error) {
      console.error(`Failed to ${action} automation:`, error)
    }
  }

  return (
    <div className="relative" ref={panelRef}>
      {/* Indicator Button */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`
          relative p-2 rounded-lg transition-colors
          ${activeCount > 0 ? 'text-green-400 hover:bg-green-500/20' : 'text-gray-400 hover:bg-gray-700'}
        `}
        title={activeCount > 0 ? `${activeCount} active automation${activeCount > 1 ? 's' : ''}` : 'Automations'}
      >
        {/* Icon */}
        <span className={`material-icons text-xl ${activeCount > 0 ? 'animate-pulse' : ''}`}>
          {activeCount > 0 ? 'auto_mode' : 'auto_mode'}
        </span>

        {/* Badge */}
        {activeCount > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-green-500 rounded-full text-white text-xs font-bold flex items-center justify-center">
            {activeCount}
          </span>
        )}
        {pendingTasks.length > 0 && activeCount === 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-yellow-500 rounded-full text-white text-xs font-bold flex items-center justify-center">
            {pendingTasks.length}
          </span>
        )}
      </button>

      {/* Expanded Panel */}
      {isExpanded && (
        <div className="absolute right-0 mt-2 w-96 min-w-[384px] bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 bg-gray-750 border-b border-gray-700">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <span className="material-icons text-lg text-green-400">auto_mode</span>
              Automations
            </h3>
          </div>

          {/* Task List */}
          <div className="max-h-96 overflow-y-auto">
            {/* Pending Confirmation */}
            {pendingTasks.length > 0 && (
              <div className="px-4 py-2 border-b border-gray-700/50">
                <p className="text-xs text-yellow-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <span className="material-icons text-xs">pending</span>
                  Awaiting Confirmation
                </p>
                {pendingTasks.map(task => (
                  <div
                    key={task.id}
                    className="py-2 border-b border-gray-700/30 last:border-0"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`material-icons text-sm ${getStatusColor(task.status)}`}>
                        {getStatusIcon(task.status)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-200 font-medium truncate">
                          {task.name}
                        </p>
                        <p className="text-xs text-gray-400 mt-0.5 truncate">
                          {task.original_intent}
                        </p>
                        <p className="text-xs text-yellow-400 mt-1">
                          Say "confirm" to Sara to activate
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Active Tasks */}
            {activeTasks.length > 0 && (
              <div className="px-4 py-2 border-b border-gray-700/50">
                <p className="text-xs text-green-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <span className="material-icons text-xs">play_circle</span>
                  Active
                </p>
                {activeTasks.map(task => (
                  <div
                    key={task.id}
                    className="py-2 border-b border-gray-700/30 last:border-0"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`material-icons text-sm ${getStatusColor(task.status)}`}>
                        {getScheduleIcon(task.schedule_type)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-200 font-medium truncate">
                          {task.name}
                        </p>
                        <div className="flex items-center gap-3 mt-1">
                          <p className="text-xs text-gray-500 flex items-center gap-1">
                            <span className="material-icons text-xs">sync</span>
                            {task.execution_count} runs
                          </p>
                          <p className="text-xs text-blue-400 flex items-center gap-1">
                            <span className="material-icons text-xs">schedule</span>
                            Next: {formatNextWake(task.next_wake_at)}
                          </p>
                        </div>
                        {task.last_error && (
                          <p className="text-xs text-red-400 mt-1 truncate">
                            Error: {task.last_error}
                          </p>
                        )}
                        {/* Quick Actions */}
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={() => handleAction(task.id, 'pause')}
                            className="text-xs text-orange-400 hover:text-orange-300 flex items-center gap-0.5"
                          >
                            <span className="material-icons text-xs">pause</span>
                            Pause
                          </button>
                          <button
                            onClick={() => handleAction(task.id, 'cancel')}
                            className="text-xs text-red-400 hover:text-red-300 flex items-center gap-0.5"
                          >
                            <span className="material-icons text-xs">cancel</span>
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Paused Tasks */}
            {pausedTasks.length > 0 && (
              <div className="px-4 py-2 bg-gray-850">
                <p className="text-xs text-orange-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <span className="material-icons text-xs">pause_circle</span>
                  Paused
                </p>
                {pausedTasks.map(task => (
                  <div
                    key={task.id}
                    className="py-2 border-b border-gray-700/30 last:border-0"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`material-icons text-sm ${getStatusColor(task.status)}`}>
                        {getStatusIcon(task.status)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-300 truncate">
                          {task.name}
                        </p>
                        <div className="flex gap-2 mt-1">
                          <button
                            onClick={() => handleAction(task.id, 'resume')}
                            className="text-xs text-green-400 hover:text-green-300 flex items-center gap-0.5"
                          >
                            <span className="material-icons text-xs">play_arrow</span>
                            Resume
                          </button>
                          <button
                            onClick={() => handleAction(task.id, 'cancel')}
                            className="text-xs text-red-400 hover:text-red-300 flex items-center gap-0.5"
                          >
                            <span className="material-icons text-xs">cancel</span>
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Empty State */}
            {tasks.length === 0 && (
              <div className="px-4 py-8 text-center">
                <span className="material-icons text-4xl text-gray-600 mb-2">auto_mode</span>
                <p className="text-gray-400 text-sm">No automations</p>
                <p className="text-gray-500 text-xs mt-1">
                  Ask Sara to create one, like "turn the heat on every 2 hours"
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          {tasks.length > 0 && (
            <div className="px-4 py-2 bg-gray-750 border-t border-gray-700">
              <button
                onClick={() => {
                  if (onOpenAutomations) {
                    onOpenAutomations()
                  }
                  setIsExpanded(false)
                }}
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                <span className="material-icons text-sm">settings</span>
                Manage Automations
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default AutomationTasksIndicator

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../config'
import { BackgroundTaskDetailDrawer } from './BackgroundTaskDetailDrawer'

interface BackgroundTask {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'needs_clarification'
  task_type: string
  original_query: string
  result_note_id: string | null
  workspace_folder_id: string | null
  clarification_question: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface BackgroundTasksIndicatorProps {
  onNavigateToWorkspace?: (noteId: string) => void
}

export const BackgroundTasksIndicator: React.FC<BackgroundTasksIndicatorProps> = ({
  onNavigateToWorkspace
}) => {
  const [tasks, setTasks] = useState<BackgroundTask[]>([])
  const [isExpanded, setIsExpanded] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // Fetch tasks
  const fetchTasks = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/background-tasks/recent?limit=10`, {
        credentials: 'include'
      })

      if (!response.ok) return

      const data = await response.json()
      setTasks(data.tasks || [])
    } catch (error) {
      console.error('Failed to fetch background tasks:', error)
    }
  }, [])

  // Poll for tasks
  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 5000) // Poll every 5 seconds
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

  const activeTasks = tasks.filter(t => t.status === 'pending' || t.status === 'running')
  const recentTasks = tasks.filter(t => t.status === 'completed' || t.status === 'failed')
  const activeCount = activeTasks.length

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'text-blue-400'
      case 'pending': return 'text-yellow-400'
      case 'completed': return 'text-green-400'
      case 'failed': return 'text-red-400'
      case 'needs_clarification': return 'text-orange-400'
      default: return 'text-gray-400'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running': return 'sync'
      case 'pending': return 'hourglass_empty'
      case 'completed': return 'check_circle'
      case 'failed': return 'error'
      case 'needs_clarification': return 'help'
      default: return 'circle'
    }
  }

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`
    return date.toLocaleDateString()
  }

  const truncateQuery = (query: string, maxLen = 50) => {
    return query.length > maxLen ? query.substring(0, maxLen) + '...' : query
  }

  return (
    <div className="relative" ref={panelRef}>
      {/* Indicator Button */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`
          relative p-2 rounded-lg transition-colors
          ${activeCount > 0 ? 'text-blue-400 hover:bg-blue-500/20' : 'text-gray-400 hover:bg-gray-700'}
        `}
        title={activeCount > 0 ? `${activeCount} active task${activeCount > 1 ? 's' : ''}` : 'Background tasks'}
      >
        {/* Icon */}
        <span className={`material-icons text-xl ${activeCount > 0 ? 'animate-pulse' : ''}`}>
          {activeCount > 0 ? 'sync' : 'pending_actions'}
        </span>

        {/* Badge */}
        {activeCount > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-blue-500 rounded-full text-white text-xs font-bold flex items-center justify-center">
            {activeCount}
          </span>
        )}
      </button>

      {/* Expanded Panel */}
      {isExpanded && (
        <div className="absolute right-0 mt-2 w-80 min-w-[320px] bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 bg-gray-750 border-b border-gray-700">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <span className="material-icons text-lg text-blue-400">auto_awesome</span>
              Background Tasks
            </h3>
          </div>

          {/* Task List */}
          <div className="max-h-80 overflow-y-auto">
            {/* Active Tasks */}
            {activeTasks.length > 0 && (
              <div className="px-4 py-2">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Active</p>
                {activeTasks.map(task => (
                  <button
                    key={task.id}
                    onClick={() => {
                      setSelectedTaskId(task.id)
                      setIsExpanded(false)
                    }}
                    className="w-full text-left py-2 border-b border-gray-700/50 last:border-0 cursor-pointer hover:bg-gray-700/40 rounded px-1 -mx-1 transition-colors"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`material-icons text-sm ${getStatusColor(task.status)} ${task.status === 'running' ? 'animate-spin' : ''}`}>
                        {getStatusIcon(task.status)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-200 truncate">
                          {truncateQuery(task.original_query)}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <p className="text-xs text-gray-500">
                            Started {formatTime(task.started_at || task.created_at)}
                          </p>
                          <span className="text-xs text-blue-400">Watch live</span>
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Recent Tasks */}
            {recentTasks.length > 0 && (
              <div className="px-4 py-2 bg-gray-850">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Recent</p>
                {recentTasks.slice(0, 5).map(task => (
                  <button
                    key={task.id}
                    onClick={() => {
                      setSelectedTaskId(task.id)
                      setIsExpanded(false)
                    }}
                    className="w-full text-left py-2 border-b border-gray-700/50 last:border-0 cursor-pointer hover:bg-gray-700/40 rounded px-1 -mx-1 transition-colors"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`material-icons text-sm ${getStatusColor(task.status)}`}>
                        {getStatusIcon(task.status)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-300 truncate">
                          {truncateQuery(task.original_query)}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <p className="text-xs text-gray-500">
                            {formatTime(task.completed_at || task.created_at)}
                          </p>
                          {task.status === 'completed' && (
                            <span className="text-xs text-green-500">View log</span>
                          )}
                          {task.status === 'failed' && (
                            <span className="text-xs text-red-400 truncate max-w-32">
                              {task.error_message || 'Failed'}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Empty State */}
            {tasks.length === 0 && (
              <div className="px-4 py-8 text-center">
                <span className="material-icons text-4xl text-gray-600 mb-2">auto_awesome</span>
                <p className="text-gray-400 text-sm">No background tasks yet</p>
                <p className="text-gray-500 text-xs mt-1">
                  Ask Sara to research something in the background
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          {tasks.length > 0 && (
            <div className="px-4 py-2 bg-gray-750 border-t border-gray-700">
              <button
                onClick={() => {
                  if (onNavigateToWorkspace) {
                    // Navigate to Agent Workspace folder
                    onNavigateToWorkspace('workspace')
                  }
                  setIsExpanded(false)
                }}
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                <span className="material-icons text-sm">folder_open</span>
                Open Agent Workspace
              </button>
            </div>
          )}
        </div>
      )}

      {/* Live execution log drawer */}
      {selectedTaskId && (
        <BackgroundTaskDetailDrawer
          taskId={selectedTaskId}
          onClose={() => setSelectedTaskId(null)}
          onOpenNote={onNavigateToWorkspace}
        />
      )}
    </div>
  )
}

export default BackgroundTasksIndicator

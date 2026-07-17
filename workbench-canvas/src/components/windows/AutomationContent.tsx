import { useState, useEffect, useCallback } from 'react'
import { AutomationWindowData } from '../../types'

interface AutomationTask {
  id: string
  name: string
  original_intent: string
  description: string | null
  status: string
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

interface ExecutionLog {
  id: number
  started_at: string
  completed_at: string | null
  step_executed: number
  action_primitive: string
  status: string
  result: Record<string, unknown> | null
  error_message: string | null
}

interface Props {
  data: AutomationWindowData
  onUpdate?: (data: Partial<AutomationWindowData>) => void
}

const API_URL = import.meta.env.VITE_API_URL || 'http://10.185.1.180:8000'

export default function AutomationContent({ data, onUpdate }: Props) {
  const [tasks, setTasks] = useState<AutomationTask[]>([])
  const [selectedTask, setSelectedTask] = useState<AutomationTask | null>(null)
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([])
  const [loading, setLoading] = useState(true)
  const [activeView, setActiveView] = useState<'list' | 'endpoints'>(data.initialTab || 'list')

  const fetchTasks = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/automation/tasks`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTasks(data || [])
      }
    } catch (error) {
      console.error('Failed to fetch automation tasks:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchExecutionLogs = async (taskId: string) => {
    try {
      const response = await fetch(`${API_URL}/api/automation/tasks/${taskId}/logs`, {
        credentials: 'include'
      })
      if (response.ok) {
        const logs = await response.json()
        setExecutionLogs(logs || [])
      }
    } catch (error) {
      console.error('Failed to fetch execution logs:', error)
    }
  }

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 15000)
    return () => clearInterval(interval)
  }, [fetchTasks])

  useEffect(() => {
    if (data.taskId && tasks.length > 0) {
      const task = tasks.find(t => t.id === data.taskId)
      if (task) {
        setSelectedTask(task)
        fetchExecutionLogs(task.id)
      }
    }
  }, [data.taskId, tasks])

  const handleAction = async (taskId: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      const response = await fetch(`${API_URL}/api/automation/tasks/${taskId}/${action}`, {
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-400 bg-green-500/20'
      case 'pending_confirmation': return 'text-yellow-400 bg-yellow-500/20'
      case 'paused': return 'text-orange-400 bg-orange-500/20'
      case 'completed': return 'text-gray-400 bg-gray-500/20'
      case 'failed': return 'text-red-400 bg-red-500/20'
      case 'cancelled': return 'text-gray-500 bg-gray-600/20'
      default: return 'text-gray-400 bg-gray-500/20'
    }
  }

  const formatTime = (dateStr: string | null) => {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 0) return 'in ' + Math.abs(diffMins) + 'm'
    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`
    return date.toLocaleDateString()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-400" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <span className="material-icons text-green-400">auto_mode</span>
          <h2 className="text-sm font-semibold text-white">Automations</h2>
        </div>
        <button
          onClick={fetchTasks}
          className="p-1.5 hover:bg-gray-700 rounded transition"
          title="Refresh"
        >
          <span className="material-icons text-gray-400 text-sm">refresh</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden flex">
        {/* Task List */}
        <div className="w-1/2 border-r border-gray-700 overflow-y-auto">
          {tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full py-8 text-center px-4">
              <span className="material-icons text-4xl text-gray-600 mb-2">auto_mode</span>
              <p className="text-sm text-gray-400">No automations</p>
              <p className="text-xs text-gray-500 mt-1">
                Create one by talking to Sara
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-700/50">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => {
                    setSelectedTask(task)
                    fetchExecutionLogs(task.id)
                  }}
                  className={`p-3 cursor-pointer transition ${
                    selectedTask?.id === task.id ? 'bg-gray-700/50' : 'hover:bg-gray-700/30'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-200 truncate flex-1">
                      {task.name}
                    </p>
                    <span className={`px-1.5 py-0.5 rounded text-xs ${getStatusColor(task.status)}`}>
                      {task.status.replace('_', ' ')}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                    <span>{task.execution_count} runs</span>
                    {task.status === 'active' && task.next_wake_at && (
                      <span className="text-blue-400">
                        Next: {formatTime(task.next_wake_at)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Task Details */}
        <div className="flex-1 overflow-y-auto p-4">
          {selectedTask ? (
            <>
              <div className="mb-4">
                <h3 className="text-lg font-semibold text-white">{selectedTask.name}</h3>
                <p className="text-sm text-gray-400 mt-1">{selectedTask.original_intent}</p>
                <span className={`inline-block mt-2 px-2 py-0.5 rounded text-xs ${getStatusColor(selectedTask.status)}`}>
                  {selectedTask.status.replace('_', ' ')}
                </span>
              </div>

              {/* Quick Actions */}
              <div className="flex gap-2 mb-4">
                {selectedTask.status === 'active' && (
                  <button
                    onClick={() => handleAction(selectedTask.id, 'pause')}
                    className="px-2 py-1 bg-orange-600/20 text-orange-400 rounded text-xs hover:bg-orange-600/30 flex items-center gap-1"
                  >
                    <span className="material-icons text-xs">pause</span>
                    Pause
                  </button>
                )}
                {(selectedTask.status === 'paused' || selectedTask.status === 'failed') && (
                  <button
                    onClick={() => handleAction(selectedTask.id, 'resume')}
                    className="px-2 py-1 bg-green-600/20 text-green-400 rounded text-xs hover:bg-green-600/30 flex items-center gap-1"
                  >
                    <span className="material-icons text-xs">play_arrow</span>
                    Resume
                  </button>
                )}
                {!['completed', 'cancelled'].includes(selectedTask.status) && (
                  <button
                    onClick={() => handleAction(selectedTask.id, 'cancel')}
                    className="px-2 py-1 bg-red-600/20 text-red-400 rounded text-xs hover:bg-red-600/30 flex items-center gap-1"
                  >
                    <span className="material-icons text-xs">cancel</span>
                    Cancel
                  </button>
                )}
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="bg-gray-700/30 rounded p-2">
                  <p className="text-xs text-gray-500">Executions</p>
                  <p className="text-lg font-semibold text-white">
                    {selectedTask.execution_count}
                    {selectedTask.max_executions && (
                      <span className="text-sm text-gray-400">/{selectedTask.max_executions}</span>
                    )}
                  </p>
                </div>
                <div className="bg-gray-700/30 rounded p-2">
                  <p className="text-xs text-gray-500">Schedule</p>
                  <p className="text-sm font-medium text-white capitalize">
                    {selectedTask.schedule_type.replace('_', ' ')}
                  </p>
                </div>
              </div>

              {/* Error */}
              {selectedTask.last_error && (
                <div className="bg-red-900/20 border border-red-500/30 rounded p-2 mb-4">
                  <p className="text-xs text-red-400 font-medium">Last Error</p>
                  <p className="text-xs text-gray-300 mt-1">{selectedTask.last_error}</p>
                </div>
              )}

              {/* Execution Logs */}
              <div>
                <h4 className="text-xs font-medium text-gray-400 uppercase mb-2">Recent Executions</h4>
                {executionLogs.length === 0 ? (
                  <p className="text-xs text-gray-500">No executions yet</p>
                ) : (
                  <div className="space-y-1">
                    {executionLogs.slice(0, 5).map((log) => (
                      <div
                        key={log.id}
                        className="flex items-center gap-2 p-2 bg-gray-700/30 rounded text-xs"
                      >
                        <span className={`material-icons text-xs ${
                          log.status === 'success' ? 'text-green-400' :
                          log.status === 'failed' ? 'text-red-400' : 'text-gray-400'
                        }`}>
                          {log.status === 'success' ? 'check' : log.status === 'failed' ? 'close' : 'pending'}
                        </span>
                        <span className="text-gray-300">{log.action_primitive}</span>
                        <span className="text-gray-500 ml-auto">{formatTime(log.started_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <span className="material-icons text-3xl text-gray-600 mb-2">touch_app</span>
              <p className="text-sm text-gray-500">Select an automation</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

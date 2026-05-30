import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'

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

interface NotificationBannerProps {
  onNavigateToWorkspace?: (noteId: string) => void
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void
}

interface TaskNotification {
  id: string
  task: BackgroundTask
  shown: boolean
  dismissed: boolean
}

export const NotificationBanner: React.FC<NotificationBannerProps> = ({
  onNavigateToWorkspace,
  onShowToast
}) => {
  const [notifications, setNotifications] = useState<TaskNotification[]>([])
  const [seenTaskIds, setSeenTaskIds] = useState<Set<string>>(() => {
    // Load from localStorage
    const stored = localStorage.getItem('seen_background_tasks')
    return stored ? new Set(JSON.parse(stored)) : new Set()
  })

  // Poll for completed background tasks
  const pollForTasks = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/background-tasks/recent?limit=10`, {
        credentials: 'include'
      })

      if (!response.ok) return

      const data = await response.json()
      const tasks: BackgroundTask[] = data.tasks || []

      // Find newly completed tasks that we haven't seen
      const newCompletedTasks = tasks.filter(task =>
        (task.status === 'completed' || task.status === 'failed') &&
        !seenTaskIds.has(task.id)
      )

      if (newCompletedTasks.length > 0) {
        // Add new notifications
        const newNotifications: TaskNotification[] = newCompletedTasks.map(task => ({
          id: `notif-${task.id}`,
          task,
          shown: true,
          dismissed: false
        }))

        setNotifications(prev => [...newNotifications, ...prev])

        // Mark as seen
        const newSeenIds = new Set(seenTaskIds)
        newCompletedTasks.forEach(task => newSeenIds.add(task.id))
        setSeenTaskIds(newSeenIds)
        localStorage.setItem('seen_background_tasks', JSON.stringify([...newSeenIds]))
      }
    } catch (error) {
      console.error('Failed to poll for background tasks:', error)
    }
  }, [seenTaskIds])

  // Set up polling interval
  useEffect(() => {
    // Initial poll
    pollForTasks()

    // Poll every 10 seconds
    const interval = setInterval(pollForTasks, 10000)

    return () => clearInterval(interval)
  }, [pollForTasks])

  // Auto-dismiss notifications after 8 seconds
  useEffect(() => {
    const timers: Array<ReturnType<typeof setTimeout>> = []

    notifications.forEach(notif => {
      if (notif.shown && !notif.dismissed) {
        const timer = setTimeout(() => {
          handleDismiss(notif.id)
        }, 8000)
        timers.push(timer)
      }
    })

    return () => timers.forEach(timer => clearTimeout(timer))
  }, [notifications])

  const handleDismiss = (notifId: string) => {
    setNotifications(prev =>
      prev.map(n => n.id === notifId ? { ...n, dismissed: true } : n)
    )

    // Remove from DOM after animation
    setTimeout(() => {
      setNotifications(prev => prev.filter(n => n.id !== notifId))
    }, 300)
  }

  const handleClick = (notification: TaskNotification) => {
    const task = notification.task

    if (task.status === 'completed' && task.result_note_id && onNavigateToWorkspace) {
      onNavigateToWorkspace(task.result_note_id)
    }

    handleDismiss(notification.id)
  }

  // Filter out dismissed notifications
  const activeNotifications = notifications.filter(n => !n.dismissed)

  if (activeNotifications.length === 0) {
    return null
  }

  return (
    <div className="fixed top-4 left-1/2 transform -translate-x-1/2 z-50 space-y-2 max-w-lg w-full min-w-[300px] px-4">
      {activeNotifications.map(notification => {
        const task = notification.task
        const isSuccess = task.status === 'completed'
        const queryPreview = task.original_query.length > 60
          ? task.original_query.substring(0, 60) + '...'
          : task.original_query

        return (
          <div
            key={notification.id}
            onClick={() => handleClick(notification)}
            className={`
              w-full p-4 rounded-lg shadow-lg cursor-pointer
              transform transition-all duration-300 ease-out
              ${notification.dismissed ? 'opacity-0 -translate-y-2' : 'opacity-100 translate-y-0'}
              ${isSuccess
                ? 'bg-green-900/95 border border-green-500/50 hover:bg-green-800/95'
                : 'bg-red-900/95 border border-red-500/50 hover:bg-red-800/95'
              }
            `}
          >
            <div className="flex items-start gap-3">
              {/* Icon */}
              <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                isSuccess ? 'bg-green-500/20' : 'bg-red-500/20'
              }`}>
                <span className={`material-icons text-lg ${
                  isSuccess ? 'text-green-400' : 'text-red-400'
                }`}>
                  {isSuccess ? 'check_circle' : 'error'}
                </span>
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-semibold ${
                    isSuccess ? 'text-green-300' : 'text-red-300'
                  }`}>
                    {isSuccess ? 'Research Complete' : 'Research Failed'}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(task.completed_at || task.created_at).toLocaleTimeString()}
                  </span>
                </div>
                <p className="text-sm text-gray-200 mt-1 truncate">
                  {queryPreview}
                </p>
                {isSuccess && (
                  <p className="text-xs text-green-400/80 mt-1">
                    Click to view results
                  </p>
                )}
                {!isSuccess && task.error_message && (
                  <p className="text-xs text-red-400/80 mt-1 truncate">
                    {task.error_message}
                  </p>
                )}
              </div>

              {/* Close button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleDismiss(notification.id)
                }}
                className="flex-shrink-0 p-1 hover:bg-white/10 rounded"
              >
                <span className="material-icons text-gray-400 text-sm">close</span>
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default NotificationBanner

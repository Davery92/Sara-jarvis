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
  dismissed: boolean
}

// Only surface results that just landed. Anything older is history — it lives
// in the background-tasks indicator, not in a banner replayed on every login.
const FRESH_WINDOW_MS = 30 * 60 * 1000
const VISIBLE_LIMIT = 3
const AUTO_DISMISS_MS = 12000

export const NotificationBanner: React.FC<NotificationBannerProps> = ({
  onNavigateToWorkspace,
}) => {
  const [notifications, setNotifications] = useState<TaskNotification[]>([])
  const [seenTaskIds, setSeenTaskIds] = useState<Set<string>>(() => {
    const stored = localStorage.getItem('seen_background_tasks')
    return stored ? new Set(JSON.parse(stored)) : new Set()
  })

  const pollForTasks = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/background-tasks/recent?limit=10`, {
        credentials: 'include'
      })

      if (!response.ok) return

      const data = await response.json()
      const tasks: BackgroundTask[] = data.tasks || []

      const unseenDone = tasks.filter(task =>
        (task.status === 'completed' || task.status === 'failed') &&
        !seenTaskIds.has(task.id)
      )
      if (unseenDone.length === 0) return

      // Everything unseen gets marked seen, but only fresh results get a banner.
      const now = Date.now()
      const fresh = unseenDone.filter(task => {
        const finished = new Date(task.completed_at || task.created_at).getTime()
        return now - finished < FRESH_WINDOW_MS
      })

      if (fresh.length > 0) {
        setNotifications(prev => [
          ...fresh.map(task => ({ id: `notif-${task.id}`, task, dismissed: false })),
          ...prev,
        ])
      }

      const newSeenIds = new Set(seenTaskIds)
      unseenDone.forEach(task => newSeenIds.add(task.id))
      setSeenTaskIds(newSeenIds)
      localStorage.setItem('seen_background_tasks', JSON.stringify([...newSeenIds]))
    } catch (error) {
      console.error('Failed to poll for background tasks:', error)
    }
  }, [seenTaskIds])

  useEffect(() => {
    pollForTasks()
    const interval = setInterval(pollForTasks, 10000)
    return () => clearInterval(interval)
  }, [pollForTasks])

  // Each notification dismisses itself on a fixed clock — timers are keyed by
  // id so one dismissal never resets the others.
  useEffect(() => {
    const timers = notifications
      .filter(n => !n.dismissed)
      .map(n => setTimeout(() => handleDismiss(n.id), AUTO_DISMISS_MS))
    return () => timers.forEach(clearTimeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notifications.map(n => n.id).join(',')])

  const handleDismiss = (notifId: string) => {
    setNotifications(prev =>
      prev.map(n => n.id === notifId ? { ...n, dismissed: true } : n)
    )
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

  const activeNotifications = notifications.filter(n => !n.dismissed).slice(0, VISIBLE_LIMIT)

  if (activeNotifications.length === 0) {
    return null
  }

  return (
    <div className="fixed left-1/2 top-4 z-50 w-full max-w-md -translate-x-1/2 space-y-2 px-4">
      {activeNotifications.map(notification => {
        const task = notification.task
        const isSuccess = task.status === 'completed'
        const queryPreview = task.original_query.length > 80
          ? task.original_query.substring(0, 80) + '…'
          : task.original_query

        return (
          <div
            key={notification.id}
            onClick={() => handleClick(notification)}
            className={`flex cursor-pointer items-start gap-2.5 rounded-xl border border-white/8 border-l-2 bg-[#0c1626]/95 py-2.5 pl-3 pr-2 shadow-[0_8px_30px_rgba(2,8,23,0.5)] backdrop-blur-xl transition-all duration-300 hover:border-white/15 ${
              isSuccess ? 'border-l-emerald-400/80' : 'border-l-rose-400/80'
            }`}
          >
            <span className={`material-icons mt-0.5 text-[16px] ${isSuccess ? 'text-emerald-300' : 'text-rose-300'}`}>
              {isSuccess ? 'check' : 'priority_high'}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] leading-snug text-slate-200">
                <span className={`font-medium ${isSuccess ? 'text-emerald-200' : 'text-rose-200'}`}>
                  {isSuccess ? 'Done:' : 'Couldn’t finish:'}
                </span>{' '}
                {queryPreview}
              </p>
              {isSuccess && task.result_note_id && (
                <p className="mt-0.5 text-xs text-slate-500">Click to open the result</p>
              )}
              {!isSuccess && task.error_message && (
                <p className="mt-0.5 truncate text-xs text-slate-500">{task.error_message}</p>
              )}
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleDismiss(notification.id)
              }}
              className="rounded-md p-1 text-slate-500 transition hover:bg-white/[0.06] hover:text-white"
              title="Dismiss"
            >
              <span className="material-icons text-[14px]">close</span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default NotificationBanner

import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import { AppView } from '../navigation/views'

interface DailyTask {
  id: string
  title: string
  priority: 'low' | 'normal' | 'high'
  is_completed: boolean
}

const PRIORITY_BAR: Record<string, string> = {
  high: 'bg-red-500',
  normal: 'bg-blue-500',
  low: 'bg-gray-600',
}

export default function DashboardTasks({ onNavigate }: { onNavigate: (view: AppView) => void }) {
  const [tasks, setTasks] = useState<DailyTask[]>([])
  const [loaded, setLoaded] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [adding, setAdding] = useState(false)

  const today = new Date().toISOString().split('T')[0]

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks?date_str=${today}`, {
        credentials: 'include',
      })
      if (res.ok) setTasks(await res.json())
    } catch (e) {
      console.error('Failed to fetch tasks:', e)
    } finally {
      setLoaded(true)
    }
  }, [today])

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const handleToggle = async (id: string) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, is_completed: !t.is_completed } : t))
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks/${id}/toggle`, {
        method: 'PATCH',
        credentials: 'include',
      })
    } catch {
      fetchTasks()
    }
  }

  const handleAdd = async () => {
    const title = newTitle.trim()
    if (!title) return
    setAdding(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, task_date: today }),
      })
      if (res.ok) {
        setNewTitle('')
        fetchTasks()
      }
    } catch (e) {
      console.error('Failed to add task:', e)
    } finally {
      setAdding(false)
    }
  }

  const completedCount = tasks.filter(t => t.is_completed).length
  const totalCount = tasks.length
  const pending = tasks.filter(t => !t.is_completed)
  const completed = tasks.filter(t => t.is_completed)

  if (!loaded) return null

  return (
    <div className="assistant-panel-soft rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Today's Tasks
          {totalCount > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              {completedCount}/{totalCount}
            </span>
          )}
        </h2>
        <button
          onClick={() => onNavigate('tasks')}
          className="text-gray-500 hover:text-teal-400 transition-colors"
        >
          <span className="material-icons text-sm">open_in_new</span>
        </button>
      </div>

      {/* Progress bar */}
      {totalCount > 0 && (
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden mb-4">
          <div
            className="h-full bg-green-500 rounded-full transition-all duration-300"
            style={{ width: `${(completedCount / totalCount) * 100}%` }}
          />
        </div>
      )}

      {/* Pending tasks */}
      {pending.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {pending.slice(0, 5).map(task => (
            <button
              key={task.id}
              onClick={() => handleToggle(task.id)}
              className="w-full flex items-center gap-2.5 py-1.5 px-2 -mx-2 rounded-lg hover:bg-gray-800/40 transition-colors text-left group"
            >
              <div className={`w-1 h-4 rounded-full flex-shrink-0 ${PRIORITY_BAR[task.priority]}`} />
              <span className="material-icons text-gray-600 group-hover:text-gray-400 transition-colors" style={{ fontSize: '18px' }}>
                radio_button_unchecked
              </span>
              <span className="text-sm text-gray-300 truncate">{task.title}</span>
            </button>
          ))}
          {pending.length > 5 && (
            <button
              onClick={() => onNavigate('tasks')}
              className="text-xs text-gray-500 hover:text-teal-400 transition-colors pl-8"
            >
              +{pending.length - 5} more
            </button>
          )}
        </div>
      )}

      {/* Completed tasks (collapsed) */}
      {completed.length > 0 && (
        <div className="space-y-1">
          {completed.slice(0, 3).map(task => (
            <button
              key={task.id}
              onClick={() => handleToggle(task.id)}
              className="w-full flex items-center gap-2.5 py-1 px-2 -mx-2 rounded-lg hover:bg-gray-800/40 transition-colors text-left group"
            >
              <div className="w-1 h-4 rounded-full flex-shrink-0 bg-transparent" />
              <span className="material-icons text-green-600" style={{ fontSize: '18px' }}>
                check_circle
              </span>
              <span className="text-sm text-gray-600 line-through truncate">{task.title}</span>
            </button>
          ))}
        </div>
      )}

      {/* Quick add */}
      <div className="flex gap-2 mt-3 pt-3 border-t border-gray-800">
        <input
          type="text"
          className="flex-1 bg-transparent text-sm text-white placeholder-gray-600 outline-none"
          placeholder="Add a task..."
          value={newTitle}
          onChange={e => setNewTitle(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
        />
        {newTitle.trim() && (
          <button
            onClick={handleAdd}
            disabled={adding}
            className="text-teal-400 hover:text-teal-300 transition-colors"
          >
            <span className="material-icons" style={{ fontSize: '20px' }}>add_circle</span>
          </button>
        )}
      </div>

      {/* Empty state */}
      {totalCount === 0 && (
        <p className="text-gray-600 text-sm text-center py-1">No tasks yet today</p>
      )}
    </div>
  )
}

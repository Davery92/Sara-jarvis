import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'

interface DailyTask {
  id: string
  title: string
  description?: string
  task_date: string
  priority: 'low' | 'normal' | 'high'
  is_completed: boolean
  completed_at?: string
  created_at: string
}

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-500/20 text-red-400 border-red-500/30',
  normal: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  low: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
}

const PRIORITY_BAR: Record<string, string> = {
  high: 'bg-red-500',
  normal: 'bg-blue-500',
  low: 'bg-zinc-600',
}

export default function TasksView() {
  const [tasks, setTasks] = useState<DailyTask[]>([])
  const [loading, setLoading] = useState(true)
  const [newTitle, setNewTitle] = useState('')
  const [newPriority, setNewPriority] = useState<'low' | 'normal' | 'high'>('normal')
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const today = new Date().toISOString().split('T')[0]

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks?date_str=${today}`, {
        credentials: 'include',
      })
      if (res.ok) {
        setTasks(await res.json())
      }
    } catch (e) {
      console.error('Failed to fetch tasks:', e)
    } finally {
      setLoading(false)
    }
  }, [today])

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const handleAdd = async () => {
    const title = newTitle.trim()
    if (!title) return
    setAdding(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, priority: newPriority, task_date: today }),
      })
      if (res.ok) {
        setNewTitle('')
        setNewPriority('normal')
        fetchTasks()
      }
    } catch (e) {
      console.error('Failed to create task:', e)
    } finally {
      setAdding(false)
    }
  }

  const handleToggle = async (id: string) => {
    // Optimistic update
    setTasks(prev =>
      prev.map(t =>
        t.id === id ? { ...t, is_completed: !t.is_completed } : t
      )
    )
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks/${id}/toggle`, {
        method: 'PATCH',
        credentials: 'include',
      })
    } catch (e) {
      fetchTasks() // revert on error
    }
  }

  const handleDelete = async (id: string) => {
    setTasks(prev => prev.filter(t => t.id !== id))
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
    } catch (e) {
      fetchTasks()
    }
  }

  const handleEdit = async (id: string) => {
    const title = editTitle.trim()
    if (!title) return
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks/${id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      setEditingId(null)
      fetchTasks()
    } catch (e) {
      console.error('Failed to update task:', e)
    }
  }

  const handleCarryOver = async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/daily-tasks/carry-over`, {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        const carried = await res.json()
        if (carried.length > 0) {
          fetchTasks()
        }
      }
    } catch (e) {
      console.error('Failed to carry over tasks:', e)
    }
  }

  const completedCount = tasks.filter(t => t.is_completed).length
  const totalCount = tasks.length
  const pendingTasks = tasks.filter(t => !t.is_completed)
  const completedTasks = tasks.filter(t => t.is_completed)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-500">
        <div className="animate-spin w-5 h-5 border-2 border-gray-500 border-t-transparent rounded-full mr-3" />
        Loading tasks...
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Daily Tasks</h1>
          <p className="text-sm text-gray-400 mt-1">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <button
          onClick={handleCarryOver}
          className="text-sm px-3 py-1.5 rounded-lg text-blue-400 hover:bg-blue-500/10 transition-colors"
        >
          Carry over
        </button>
      </div>

      {/* Progress bar */}
      {totalCount > 0 && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-gray-400">{completedCount}/{totalCount} completed</span>
            <span className="text-sm text-gray-500">{totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0}%</span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 rounded-full transition-all duration-300"
              style={{ width: `${totalCount > 0 ? (completedCount / totalCount) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Add task input */}
      <div className="flex gap-2 mb-6">
        <div className="flex items-center gap-1 bg-gray-800/50 rounded-lg px-2">
          {(['low', 'normal', 'high'] as const).map(p => (
            <button
              key={p}
              onClick={() => setNewPriority(p)}
              className={`w-3 h-3 rounded-full transition-all ${PRIORITY_BAR[p]} ${
                newPriority === p ? 'ring-2 ring-white/40 scale-125' : 'opacity-40'
              }`}
              title={p}
            />
          ))}
        </div>
        <input
          type="text"
          className="flex-1 bg-gray-800/50 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
          placeholder="Add a task..."
          value={newTitle}
          onChange={e => setNewTitle(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
        />
        <button
          onClick={handleAdd}
          disabled={!newTitle.trim() || adding}
          className="px-4 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium disabled:opacity-30 transition-colors"
        >
          {adding ? '...' : 'Add'}
        </button>
      </div>

      {/* Pending tasks */}
      {pendingTasks.length > 0 && (
        <div className="space-y-2 mb-6">
          {pendingTasks.map(task => (
            <div
              key={task.id}
              className="group flex items-center gap-3 bg-gray-800/40 border border-gray-700/50 rounded-lg px-4 py-3 hover:border-gray-600 transition-colors relative overflow-hidden"
            >
              <div className={`absolute left-0 top-0 bottom-0 w-1 ${PRIORITY_BAR[task.priority]}`} />
              <button
                onClick={() => handleToggle(task.id)}
                className="text-gray-500 hover:text-green-400 transition-colors flex-shrink-0"
              >
                <span className="material-icons text-xl">radio_button_unchecked</span>
              </button>
              {editingId === task.id ? (
                <input
                  autoFocus
                  className="flex-1 bg-transparent border-b border-blue-500 text-white outline-none py-0.5"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleEdit(task.id)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onBlur={() => handleEdit(task.id)}
                />
              ) : (
                <span
                  className="flex-1 text-gray-200 cursor-pointer"
                  onDoubleClick={() => { setEditingId(task.id); setEditTitle(task.title) }}
                >
                  {task.title}
                </span>
              )}
              {task.priority !== 'normal' && (
                <span className={`text-xs px-2 py-0.5 rounded-full border ${PRIORITY_COLORS[task.priority]}`}>
                  {task.priority}
                </span>
              )}
              <button
                onClick={() => handleDelete(task.id)}
                className="text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
              >
                <span className="material-icons text-lg">close</span>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Completed tasks */}
      {completedTasks.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-500 mb-2">Completed</h3>
          <div className="space-y-1">
            {completedTasks.map(task => (
              <div
                key={task.id}
                className="group flex items-center gap-3 px-4 py-2 rounded-lg hover:bg-gray-800/30 transition-colors"
              >
                <button
                  onClick={() => handleToggle(task.id)}
                  className="text-green-500 hover:text-gray-400 transition-colors flex-shrink-0"
                >
                  <span className="material-icons text-xl">check_circle</span>
                </button>
                <span className="flex-1 text-gray-500 line-through">{task.title}</span>
                <button
                  onClick={() => handleDelete(task.id)}
                  className="text-gray-700 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                >
                  <span className="material-icons text-lg">close</span>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {totalCount === 0 && (
        <div className="text-center py-16">
          <span className="material-icons text-5xl text-gray-700 mb-3 block">check_circle_outline</span>
          <p className="text-gray-400 text-lg">No tasks for today</p>
          <p className="text-gray-600 text-sm mt-1">Add one above or ask Sara in chat</p>
        </div>
      )}
    </div>
  )
}

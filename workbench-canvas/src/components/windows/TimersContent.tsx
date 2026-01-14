import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Timer, Plus, Pause, Play, X, Loader2 } from 'lucide-react'
import { timersApi, type Timer as TimerType } from '../../services/api'
import type { TimersWindowData } from '../../types'

interface TimersContentProps {
  data: TimersWindowData
  windowId: string
}

function formatTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function parseDuration(input: string): number | null {
  // Parse formats like "5m", "30s", "1h30m", "90" (assumes minutes)
  const hourMatch = input.match(/(\d+)\s*h/i)
  const minMatch = input.match(/(\d+)\s*m/i)
  const secMatch = input.match(/(\d+)\s*s/i)

  if (hourMatch || minMatch || secMatch) {
    const hours = hourMatch ? parseInt(hourMatch[1]) : 0
    const minutes = minMatch ? parseInt(minMatch[1]) : 0
    const seconds = secMatch ? parseInt(secMatch[1]) : 0
    return hours * 3600 + minutes * 60 + seconds
  }

  // Plain number - assume minutes
  const num = parseInt(input)
  if (!isNaN(num)) {
    return num * 60
  }

  return null
}

export default function TimersContent({ data }: TimersContentProps) {
  const queryClient = useQueryClient()
  const [newTimerName, setNewTimerName] = useState('')
  const [newTimerDuration, setNewTimerDuration] = useState('')
  const [showForm, setShowForm] = useState(false)

  // Fetch timers
  const { data: timers = [], isLoading, error } = useQuery({
    queryKey: ['timers'],
    queryFn: timersApi.list,
    refetchInterval: 1000, // Update every second for countdown
  })

  // Create timer mutation
  const createMutation = useMutation({
    mutationFn: ({ name, duration }: { name: string; duration: number }) =>
      timersApi.create(name, duration),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timers'] })
      setNewTimerName('')
      setNewTimerDuration('')
      setShowForm(false)
    },
  })

  // Pause mutation
  const pauseMutation = useMutation({
    mutationFn: timersApi.pause,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timers'] }),
  })

  // Resume mutation
  const resumeMutation = useMutation({
    mutationFn: timersApi.resume,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timers'] }),
  })

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: timersApi.cancel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timers'] }),
  })

  const handleCreateTimer = (e: React.FormEvent) => {
    e.preventDefault()
    const duration = parseDuration(newTimerDuration)
    if (!newTimerName.trim() || !duration) return
    createMutation.mutate({ name: newTimerName.trim(), duration })
  }

  const activeTimers = timers.filter(t => t.status === 'running' || t.status === 'paused')
  const completedTimers = timers.filter(t => t.status === 'completed').slice(0, 5)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading timers...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load timers
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-canvas-bg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Timer size={20} className="text-orange-500" />
          Timers
        </h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="p-2 rounded-lg bg-orange-500 hover:bg-orange-600 transition-colors"
        >
          <Plus size={18} className="text-white" />
        </button>
      </div>

      {/* New Timer Form */}
      {showForm && (
        <form onSubmit={handleCreateTimer} className="mb-4 p-3 bg-canvas-surface rounded-lg">
          <input
            type="text"
            placeholder="Timer name"
            value={newTimerName}
            onChange={(e) => setNewTimerName(e.target.value)}
            className="w-full mb-2 px-3 py-2 bg-canvas-elevated rounded border border-canvas-border text-white placeholder-canvas-muted focus:outline-none focus:border-orange-500"
          />
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Duration (e.g., 5m, 30s, 1h)"
              value={newTimerDuration}
              onChange={(e) => setNewTimerDuration(e.target.value)}
              className="flex-1 px-3 py-2 bg-canvas-elevated rounded border border-canvas-border text-white placeholder-canvas-muted focus:outline-none focus:border-orange-500"
            />
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 rounded text-white font-medium transition-colors"
            >
              {createMutation.isPending ? 'Creating...' : 'Start'}
            </button>
          </div>
        </form>
      )}

      {/* Active Timers */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {activeTimers.length === 0 && !showForm && (
          <div className="text-center text-canvas-muted py-8">
            <Timer size={48} className="mx-auto mb-4 opacity-30" />
            <p>No active timers</p>
            <p className="text-sm mt-1">Click + to create one</p>
          </div>
        )}

        {activeTimers.map((timer) => (
          <TimerCard
            key={timer.id}
            timer={timer}
            onPause={() => pauseMutation.mutate(timer.id)}
            onResume={() => resumeMutation.mutate(timer.id)}
            onCancel={() => cancelMutation.mutate(timer.id)}
            isPausing={pauseMutation.isPending}
            isResuming={resumeMutation.isPending}
          />
        ))}

        {/* Completed Timers */}
        {completedTimers.length > 0 && (
          <div className="mt-4 pt-4 border-t border-canvas-border">
            <h3 className="text-sm text-canvas-muted mb-2">Recently Completed</h3>
            {completedTimers.map((timer) => (
              <div
                key={timer.id}
                className="flex items-center justify-between py-2 px-3 mb-1 bg-canvas-surface/50 rounded text-sm"
              >
                <span className="text-canvas-muted">{timer.name}</span>
                <span className="text-green-500">Done</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TimerCard({
  timer,
  onPause,
  onResume,
  onCancel,
  isPausing,
  isResuming,
}: {
  timer: TimerType
  onPause: () => void
  onResume: () => void
  onCancel: () => void
  isPausing: boolean
  isResuming: boolean
}) {
  const isRunning = timer.status === 'running'
  const isPaused = timer.status === 'paused'
  const progress = ((timer.duration_seconds - timer.remaining_seconds) / timer.duration_seconds) * 100

  return (
    <div className="mb-3 p-4 bg-canvas-surface rounded-lg border border-canvas-border">
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-white">{timer.name}</span>
        <div className="flex items-center gap-1">
          {isRunning && (
            <button
              onClick={onPause}
              disabled={isPausing}
              className="p-1.5 rounded hover:bg-canvas-elevated transition-colors text-yellow-500"
              title="Pause"
            >
              <Pause size={16} />
            </button>
          )}
          {isPaused && (
            <button
              onClick={onResume}
              disabled={isResuming}
              className="p-1.5 rounded hover:bg-canvas-elevated transition-colors text-green-500"
              title="Resume"
            >
              <Play size={16} />
            </button>
          )}
          <button
            onClick={onCancel}
            className="p-1.5 rounded hover:bg-canvas-elevated transition-colors text-red-500"
            title="Cancel"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Time display */}
      <div className="text-3xl font-mono text-white mb-2">
        {formatTime(timer.remaining_seconds)}
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-canvas-elevated rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-1000 ${
            isRunning ? 'bg-orange-500' : 'bg-yellow-500'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Status */}
      <div className="mt-2 text-xs text-canvas-muted">
        {isRunning && 'Running'}
        {isPaused && 'Paused'}
      </div>
    </div>
  )
}

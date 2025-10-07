import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient, ShadowSession, ShadowSessionStatus } from '../api/client'
import { PlayIcon, PauseIcon, StopIcon, ClockIcon } from '@heroicons/react/24/outline'

export default function ShadowSessionPill() {
  const [timeElapsed, setTimeElapsed] = useState(0)

  // Poll for active session
  const { data: activeSession, isLoading } = useQuery({
    queryKey: ['shadow', 'active'],
    queryFn: () => apiClient.getActiveShadowSession(),
    refetchInterval: 5000, // Poll every 5 seconds
  })

  // Get session status if we have an active session
  const { data: status } = useQuery({
    queryKey: ['shadow', 'status', activeSession?.id],
    queryFn: () => apiClient.getShadowSessionStatus(activeSession!.id),
    enabled: !!activeSession,
    refetchInterval: 5000,
  })

  // Update time elapsed every second
  useEffect(() => {
    if (!status) return

    const interval = setInterval(() => {
      const seconds = Math.floor(
        (new Date().getTime() - new Date(status.started_at).getTime()) / 1000
      )
      setTimeElapsed(seconds)
    }, 1000)

    return () => clearInterval(interval)
  }, [status])

  const handlePause = async () => {
    if (!activeSession) return
    try {
      await apiClient.pauseShadowSession(activeSession.id)
    } catch (error) {
      console.error('Failed to pause session:', error)
    }
  }

  const handleResume = async () => {
    if (!activeSession) return
    try {
      await apiClient.resumeShadowSession(activeSession.id)
    } catch (error) {
      console.error('Failed to resume session:', error)
    }
  }

  const handleWrap = async () => {
    if (!activeSession) return
    try {
      await apiClient.wrapShadowSession(activeSession.id)
      // Show summary in chat or modal
    } catch (error) {
      console.error('Failed to wrap session:', error)
    }
  }

  if (isLoading || !activeSession || !status) return null

  const minutes = Math.floor(timeElapsed / 60)
  const seconds = timeElapsed % 60
  const timeStr = `${minutes}:${seconds.toString().padStart(2, '0')}`

  const remainingMinutes = status.time_remaining_seconds
    ? Math.floor(status.time_remaining_seconds / 60)
    : null

  const isPaused = activeSession.status === 'paused'
  const isExpired = status.time_remaining_seconds !== null && status.time_remaining_seconds < 0

  return (
    <div className="fixed bottom-28 right-6 z-50">
      <div className={`${isExpired ? 'bg-gradient-to-r from-red-600 to-orange-600 animate-pulse' : 'bg-gradient-to-r from-purple-600 to-indigo-600'} text-white rounded-full shadow-lg px-4 py-2 flex items-center space-x-3`}>
        <div className="flex items-center space-x-2">
          <div className={`w-2 h-2 rounded-full ${isPaused ? 'bg-yellow-400' : isExpired ? 'bg-red-400' : 'bg-green-400 animate-pulse'}`} />
          <span className="text-sm font-semibold">🕵️ {isExpired ? 'TIME\'S UP!' : 'Shadow Mode'}</span>
        </div>

        <div className="flex items-center space-x-1 text-xs">
          <ClockIcon className="w-4 h-4" />
          <span>{timeStr}</span>
          {remainingMinutes !== null && !isExpired && (
            <span className="text-purple-200">({remainingMinutes}m left)</span>
          )}
          {isExpired && (
            <span className="text-red-200 font-bold">WRAP NOW</span>
          )}
        </div>

        <div className="flex items-center space-x-1">
          <span className="text-xs">
            {status.note_counts.task}✅ {status.note_counts.decision}🎯 {status.note_counts.idea}💡
          </span>
        </div>

        <div className="flex items-center space-x-1">
          {isPaused ? (
            <button
              onClick={handleResume}
              className="p-1 hover:bg-purple-700 rounded transition"
              title="Resume"
            >
              <PlayIcon className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handlePause}
              className="p-1 hover:bg-purple-700 rounded transition"
              title="Pause"
            >
              <PauseIcon className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={handleWrap}
            className="p-1 hover:bg-purple-700 rounded transition"
            title="Wrap Session"
          >
            <StopIcon className="w-4 h-4" />
          </button>
        </div>

        {status.context && (
          <div className="text-xs text-purple-200 max-w-xs truncate">
            {status.context}
          </div>
        )}
      </div>
    </div>
  )
}

import { useEffect, useState, useRef } from 'react'

interface TimerData {
  id: string
  name: string
  remainingSeconds: number
}

export default function TimerFloat() {
  const [timer, setTimer] = useState<TimerData | null>(null)
  const [remaining, setRemaining] = useState(0)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    // Parse timer data from URL
    const params = new URLSearchParams(window.location.search)
    const data = params.get('data')
    if (data) {
      try {
        const parsed = JSON.parse(decodeURIComponent(data))
        setTimer(parsed)
        setRemaining(parsed.remainingSeconds)
      } catch (e) {
        console.error('Failed to parse timer data:', e)
      }
    }

    // Listen for timer updates from main process
    window.electronAPI?.onTimerUpdate((data) => {
      setRemaining(data.remainingSeconds)
    })
  }, [])

  // Countdown timer
  useEffect(() => {
    if (remaining <= 0) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      return
    }

    intervalRef.current = setInterval(() => {
      setRemaining(prev => {
        if (prev <= 1) {
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
          }
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [remaining > 0])

  const handleClose = () => {
    if (timer) {
      window.electronAPI?.closeTimer(timer.id)
    }
  }

  const formatTime = (seconds: number): string => {
    const hrs = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60

    if (hrs > 0) {
      return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const isExpired = remaining <= 0
  const isUrgent = remaining <= 60 && remaining > 0

  if (!timer) {
    return null
  }

  return (
    <div className={`w-full h-full rounded-xl border shadow-lg flex items-center gap-3 px-4 ${
      isExpired
        ? 'bg-red-900/90 border-red-600 animate-pulse'
        : isUrgent
          ? 'bg-orange-900/90 border-orange-600'
          : 'bg-gray-900/95 border-gray-700'
    }`}>
      {/* Timer icon */}
      <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${
        isExpired
          ? 'bg-red-600'
          : isUrgent
            ? 'bg-orange-600'
            : 'bg-indigo-600'
      }`}>
        <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>

      {/* Timer info */}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-400 truncate">{timer.name}</div>
        <div className={`text-xl font-mono font-bold ${
          isExpired
            ? 'text-red-300'
            : isUrgent
              ? 'text-orange-300'
              : 'text-white'
        }`}>
          {isExpired ? "Time's up!" : formatTime(remaining)}
        </div>
      </div>

      {/* Close button */}
      <button
        onClick={handleClose}
        className="text-gray-400 hover:text-white transition-colors p-1 hover:bg-gray-700/50 rounded"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

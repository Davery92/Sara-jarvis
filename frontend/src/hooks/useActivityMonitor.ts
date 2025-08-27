import { useState, useEffect, useCallback, useRef } from 'react'

export interface ActivityThresholds {
  quickSweep: number    // Short idle (20-30 min)
  standardSweep: number // Medium idle (2-3 h) 
  digestSweep: number   // Long idle (24h+)
}

export interface ActivityState {
  isIdle: boolean
  idleDuration: number
  lastActivity: Date
  currentThreshold: 'active' | 'quickSweep' | 'standardSweep' | 'digestSweep'
}

interface ActivityMonitorOptions {
  thresholds?: Partial<ActivityThresholds>
  onThresholdReached?: (threshold: keyof ActivityThresholds, duration: number) => void
  onActivityResume?: () => void
  enableLogging?: boolean
}

const DEFAULT_THRESHOLDS: ActivityThresholds = {
  quickSweep: 20 * 60 * 1000,      // 20 minutes
  standardSweep: 2 * 60 * 60 * 1000, // 2 hours  
  digestSweep: 24 * 60 * 60 * 1000   // 24 hours
}

export const useActivityMonitor = (options: ActivityMonitorOptions = {}) => {
  const {
    thresholds = {},
    onThresholdReached,
    onActivityResume,
    enableLogging = false
  } = options

  const finalThresholds = { ...DEFAULT_THRESHOLDS, ...thresholds }
  const [activityState, setActivityState] = useState<ActivityState>({
    isIdle: false,
    idleDuration: 0,
    lastActivity: new Date(),
    currentThreshold: 'active'
  })

  const lastActivityRef = useRef(new Date())
  const thresholdTriggeredRef = useRef(new Set<string>())
  const intervalRef = useRef<number>()

  const log = useCallback((message: string) => {
    if (enableLogging) {
      console.log(`[ActivityMonitor] ${message}`)
    }
  }, [enableLogging])

  const recordActivity = useCallback(() => {
    const now = new Date()
    const wasIdle = activityState.isIdle
    
    lastActivityRef.current = now
    thresholdTriggeredRef.current.clear()

    setActivityState({
      isIdle: false,
      idleDuration: 0,
      lastActivity: now,
      currentThreshold: 'active'
    })

    if (wasIdle && onActivityResume) {
      log('Activity resumed')
      onActivityResume()
    }
  }, [activityState.isIdle, onActivityResume, log])

  const updateIdleState = useCallback(() => {
    const now = new Date()
    const timeSinceActivity = now.getTime() - lastActivityRef.current.getTime()
    
    let currentThreshold: ActivityState['currentThreshold'] = 'active'
    let isIdle = false

    if (timeSinceActivity >= finalThresholds.digestSweep) {
      currentThreshold = 'digestSweep'
      isIdle = true
    } else if (timeSinceActivity >= finalThresholds.standardSweep) {
      currentThreshold = 'standardSweep' 
      isIdle = true
    } else if (timeSinceActivity >= finalThresholds.quickSweep) {
      currentThreshold = 'quickSweep'
      isIdle = true
    }

    setActivityState({
      isIdle,
      idleDuration: timeSinceActivity,
      lastActivity: lastActivityRef.current,
      currentThreshold
    })

    // Trigger threshold callbacks once per threshold
    if (isIdle && onThresholdReached && currentThreshold !== 'active') {
      const thresholdKey = currentThreshold as keyof ActivityThresholds
      if (!thresholdTriggeredRef.current.has(thresholdKey)) {
        thresholdTriggeredRef.current.add(thresholdKey)
        log(`Threshold reached: ${thresholdKey} (${Math.round(timeSinceActivity / 60000)}min idle)`)
        onThresholdReached(thresholdKey, timeSinceActivity)
      }
    }
  }, [finalThresholds, onThresholdReached, log])

  // Set up activity listeners
  useEffect(() => {
    const events = [
      'mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'
    ]

    const throttledRecordActivity = (() => {
      let timeout: number
      return () => {
        clearTimeout(timeout)
        timeout = window.setTimeout(recordActivity, 1000) // Throttle to once per second
      }
    })()

    events.forEach(event => {
      document.addEventListener(event, throttledRecordActivity, true)
    })

    return () => {
      events.forEach(event => {
        document.removeEventListener(event, throttledRecordActivity, true)
      })
    }
  }, [recordActivity])

  // Set up idle checking interval
  useEffect(() => {
    intervalRef.current = window.setInterval(updateIdleState, 30000) // Check every 30 seconds
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [updateIdleState])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [])

  return {
    activityState,
    recordActivity,
    thresholds: finalThresholds,
    // Utility functions
    getIdleMinutes: () => Math.round(activityState.idleDuration / 60000),
    getIdleHours: () => Math.round(activityState.idleDuration / 3600000),
    isActivelyUsing: () => !activityState.isIdle,
    getCurrentThreshold: () => activityState.currentThreshold
  }
}
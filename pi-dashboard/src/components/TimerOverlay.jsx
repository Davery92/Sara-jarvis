/**
 * TimerOverlay - Shows active timers as a floating overlay
 */

import { useState, useEffect, useCallback } from 'preact/hooks';

export function TimerOverlay({ timers, onTimerComplete }) {
  const [localTimers, setLocalTimers] = useState([]);

  // Update local timers when props change - sync with backend state
  useEffect(() => {
    // Get IDs of timers from backend
    const backendTimerIds = new Set(timers.map(t => t.id));

    // Remove any local timers that are no longer in backend (cancelled/completed)
    // and update existing ones with fresh data
    setLocalTimers(prevLocal => {
      // If backend has no timers, clear everything
      if (timers.length === 0) {
        return [];
      }

      // Build new timer list from backend, preserving local countdown for existing timers
      return timers.map(backendTimer => {
        const existingLocal = prevLocal.find(l => l.id === backendTimer.id);
        if (existingLocal) {
          // Keep local countdown if it's still valid, otherwise use backend value
          return {
            ...backendTimer,
            remainingSeconds: Math.min(existingLocal.remainingSeconds, backendTimer.remaining_seconds)
          };
        }
        // New timer from backend
        return {
          ...backendTimer,
          remainingSeconds: backendTimer.remaining_seconds
        };
      });
    });
  }, [timers]);

  // Countdown effect - update every second
  useEffect(() => {
    if (localTimers.length === 0) return;

    const interval = setInterval(() => {
      setLocalTimers(prev => {
        const updated = prev.map(timer => {
          const newRemaining = timer.remainingSeconds - 1;

          // Timer finished
          if (newRemaining <= 0) {
            onTimerComplete?.(timer);
            return null;
          }

          return {
            ...timer,
            remainingSeconds: newRemaining
          };
        }).filter(Boolean);

        return updated;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [localTimers.length, onTimerComplete]);

  if (localTimers.length === 0) return null;

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;

    if (mins >= 60) {
      const hours = Math.floor(mins / 60);
      const remainingMins = mins % 60;
      return `${hours}:${remainingMins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getTimerProgress = (timer) => {
    const totalSeconds = timer.duration_minutes * 60;
    const elapsed = totalSeconds - timer.remainingSeconds;
    return (elapsed / totalSeconds) * 100;
  };

  const getTimerColor = (timer) => {
    const remaining = timer.remainingSeconds;
    if (remaining <= 10) return 'var(--accent-red)';
    if (remaining <= 60) return 'var(--accent-yellow)';
    return 'var(--accent-green)';
  };

  return (
    <div class="timer-overlay">
      {localTimers.map((timer) => (
        <div key={timer.id} class="timer-card">
          <div class="timer-ring" style={{ '--progress': getTimerProgress(timer), '--color': getTimerColor(timer) }}>
            <svg viewBox="0 0 100 100">
              <circle class="timer-ring-bg" cx="50" cy="50" r="45" />
              <circle
                class="timer-ring-progress"
                cx="50"
                cy="50"
                r="45"
                style={{
                  strokeDasharray: `${2 * Math.PI * 45}`,
                  strokeDashoffset: `${2 * Math.PI * 45 * (1 - getTimerProgress(timer) / 100)}`
                }}
              />
            </svg>
            <div class="timer-time">
              {formatTime(timer.remainingSeconds)}
            </div>
          </div>
          <div class="timer-title">{timer.title}</div>
        </div>
      ))}
    </div>
  );
}

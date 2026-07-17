import React, { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import { Timer, timerService } from '../services/timer';
import { Alert, AppState } from 'react-native';
import { startTimerLiveActivity, endTimerLiveActivity } from '../services/liveActivity';

interface TimerContextType {
  activeTimer: Timer | null;
  startTimer: (title: string, durationSeconds: number) => Promise<void>;
  stopTimer: () => Promise<void>;
  refreshTimers: () => Promise<void>;
}

const TimerContext = createContext<TimerContextType | undefined>(undefined);

export function TimerProvider({ children }: { children: ReactNode }) {
  const [activeTimer, setActiveTimer] = useState<Timer | null>(null);
  const appStateRef = useRef(AppState.currentState);
  const liveActivityIdRef = useRef<string | null>(null);

  // Drive the Live Activity off the active-timer STATE so it covers timers created
  // either in-app (startTimer) or by Sara server-side (surfaced via refreshTimers).
  useEffect(() => {
    if (activeTimer) {
      const id = String(activeTimer.id);
      if (liveActivityIdRef.current !== id) {
        if (liveActivityIdRef.current) endTimerLiveActivity(liveActivityIdRef.current);
        const endMs = new Date(activeTimer.end_time).getTime();
        if (!isNaN(endMs) && endMs > Date.now()) {
          startTimerLiveActivity(id, activeTimer.title, endMs);
          liveActivityIdRef.current = id;
        }
      }
    } else if (liveActivityIdRef.current) {
      endTimerLiveActivity(liveActivityIdRef.current);
      liveActivityIdRef.current = null;
    }
  }, [activeTimer]);

  useEffect(() => {
    refreshTimers();

    // Only poll when app is in the foreground
    const interval = setInterval(() => {
      if (appStateRef.current === 'active') {
        refreshTimers();
      }
    }, 30000);

    const subscription = AppState.addEventListener('change', (nextState) => {
      if (appStateRef.current !== 'active' && nextState === 'active') {
        refreshTimers();
      }
      appStateRef.current = nextState;
    });

    return () => {
      clearInterval(interval);
      subscription.remove();
    };
  }, []);

  const refreshTimers = async () => {
    try {
      const timers = await timerService.getActiveTimers();
      if (timers.length > 0) {
        setActiveTimer(timers[0]);
      } else {
        setActiveTimer(null);
      }
    } catch (_) {
      // Silently ignore — this is a background poll, not a user-initiated action
    }
  };

  const startTimer = async (title: string, durationSeconds: number) => {
    try {
      const timer = await timerService.startTimer(title, durationSeconds);
      setActiveTimer(timer); // → effect starts the Live Activity
      const minutes = Math.floor(durationSeconds / 60);
      const seconds = durationSeconds % 60;
      const durationStr = seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
      Alert.alert('Timer Started', `${title} - ${durationStr}`);
    } catch (error) {
      console.error('Failed to start timer:', error);
      Alert.alert('Error', 'Failed to start timer');
    }
  };

  const stopTimer = async () => {
    if (!activeTimer) return;

    try {
      await timerService.stopTimer(activeTimer.id);
      setActiveTimer(null); // → effect ends the Live Activity
      Alert.alert('Timer Stopped', 'Timer has been stopped');
    } catch (error: any) {
      // If timer is already stopped (404), just hide the overlay without showing an error
      if (error?.response?.status === 404) {
        console.log('Timer already stopped, hiding overlay');
        setActiveTimer(null);
      } else {
        console.error('Failed to stop timer:', error);
        Alert.alert('Error', 'Failed to stop timer');
      }
    }
  };

  return (
    <TimerContext.Provider value={{ activeTimer, startTimer, stopTimer, refreshTimers }}>
      {children}
    </TimerContext.Provider>
  );
}

export function useTimer() {
  const context = useContext(TimerContext);
  if (context === undefined) {
    throw new Error('useTimer must be used within a TimerProvider');
  }
  return context;
}

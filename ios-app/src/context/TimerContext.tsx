import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { Timer, timerService } from '../services/timer';
import { Alert } from 'react-native';

interface TimerContextType {
  activeTimer: Timer | null;
  startTimer: (title: string, durationSeconds: number) => Promise<void>;
  stopTimer: () => Promise<void>;
  refreshTimers: () => Promise<void>;
}

const TimerContext = createContext<TimerContextType | undefined>(undefined);

export function TimerProvider({ children }: { children: ReactNode }) {
  const [activeTimer, setActiveTimer] = useState<Timer | null>(null);

  useEffect(() => {
    // Load any existing active timers
    refreshTimers();

    // Poll for active timers every 30 seconds
    const interval = setInterval(refreshTimers, 30000);
    return () => clearInterval(interval);
  }, []);

  const refreshTimers = async () => {
    try {
      const timers = await timerService.getActiveTimers();
      if (timers.length > 0) {
        // Show the first active timer
        setActiveTimer(timers[0]);
      } else {
        setActiveTimer(null);
      }
    } catch (error) {
      console.error('Failed to refresh timers:', error);
    }
  };

  const startTimer = async (title: string, durationSeconds: number) => {
    try {
      const timer = await timerService.startTimer(title, durationSeconds);
      setActiveTimer(timer);
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
      setActiveTimer(null);
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

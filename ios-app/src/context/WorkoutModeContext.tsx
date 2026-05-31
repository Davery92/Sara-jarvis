import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fitnessService, ActiveWorkoutSession, LogSetParams, RestTimerStatus } from '../services/fitness';
import { startEvent, updateEvent, endEvent } from '../services/eventActivity';

interface WorkoutModeContextType {
  // State
  session: ActiveWorkoutSession | null;
  isActive: boolean;
  isLoading: boolean;
  error: string | null;
  restTimer: RestTimerStatus | null;

  // Actions
  startWorkout: (templateId: string) => Promise<ActiveWorkoutSession | null>;
  logSet: (params: LogSetParams) => Promise<{ success: boolean; coaching_feedback?: string }>;
  skipExercise: () => Promise<void>;
  startRestTimer: (duration?: number) => Promise<void>;
  stopRestTimer: () => Promise<void>;
  completeWorkout: () => Promise<{ summary?: any }>;
  abandonWorkout: () => Promise<void>;
  refreshSession: () => Promise<void>;

  // Computed values
  currentExercise: ActiveWorkoutSession['workout_snapshot']['exercises'][0] | null;
  currentSetNumber: number;
  progress: { completed: number; total: number; percentage: number };
}

const WorkoutModeContext = createContext<WorkoutModeContextType | undefined>(undefined);

const STORAGE_KEY = '@active_workout_session_id';
const POLL_INTERVAL = 2000; // Poll every 2 seconds when active

export function WorkoutModeProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<ActiveWorkoutSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restTimer, setRestTimer] = useState<RestTimerStatus | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const restTimerIntervalRef = useRef<NodeJS.Timeout | null>(null);
  // Local timer tracking (independent of session refresh)
  const localTimerRef = useRef<{ startTime: number; duration: number } | null>(null);

  // Drive the workout Live Activity (count-up) off the active session.
  const workoutActivityRef = useRef<string | null>(null);
  useEffect(() => {
    const active = session && session.status === 'active';
    if (active) {
      const title = session.workout_snapshot?.name || 'Workout';
      const ex = session.workout_snapshot?.exercises?.[session.current_exercise_index];
      const subtitle = ex?.name || 'In progress';
      const startMsRaw = session.started_at ? new Date(session.started_at).getTime() : Date.now();
      const startMs = isNaN(startMsRaw) ? Date.now() : startMsRaw;
      if (workoutActivityRef.current !== session.id) {
        if (workoutActivityRef.current) endEvent(workoutActivityRef.current);
        startEvent(session.id, 'workout', title, subtitle, startMs);
        workoutActivityRef.current = session.id;
      } else {
        updateEvent(session.id, subtitle, startMs);
      }
    } else if (workoutActivityRef.current) {
      endEvent(workoutActivityRef.current);
      workoutActivityRef.current = null;
    }
  }, [session]);

  // Check for active session on mount
  useEffect(() => {
    checkActiveSession();
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (restTimerIntervalRef.current) clearInterval(restTimerIntervalRef.current);
    };
  }, []);

  // Start/stop polling based on active session
  useEffect(() => {
    if (session && session.status === 'active') {
      // Start polling for session updates
      pollIntervalRef.current = setInterval(refreshSession, POLL_INTERVAL);
      // Start rest timer countdown
      restTimerIntervalRef.current = setInterval(updateRestTimer, 1000);
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (restTimerIntervalRef.current) {
        clearInterval(restTimerIntervalRef.current);
        restTimerIntervalRef.current = null;
      }
    }

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (restTimerIntervalRef.current) clearInterval(restTimerIntervalRef.current);
    };
  }, [session?.id, session?.status]);

  const checkActiveSession = async () => {
    try {
      setIsLoading(true);
      const result = await fitnessService.getActiveWorkoutSession();
      setSession(result.session);
      if (result.session?.id) {
        await AsyncStorage.setItem(STORAGE_KEY, result.session.id);
      }
    } catch (err: any) {
      console.error('Failed to check active workout session:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const refreshSession = useCallback(async () => {
    try {
      const result = await fitnessService.getActiveWorkoutSession();
      console.log('[WorkoutMode] refreshSession result:', JSON.stringify(result));
      // Only update if we get a valid session back, or if we explicitly have no session
      // This prevents race conditions where polling returns null before state is synced
      if (result.session) {
        setSession(result.session);
      } else if (session && session.status === 'active') {
        // Don't overwrite an active local session with null from API
        // This can happen due to timing issues - wait for next poll
        console.log('[WorkoutMode] Ignoring null from API - local session still active');
      } else {
        setSession(null);
      }
    } catch (err) {
      console.error('Failed to refresh workout session:', err);
    }
  }, [session]);

  const updateRestTimer = useCallback(() => {
    // Use local ref for immediate timer updates (avoids stale closure issues)
    if (localTimerRef.current) {
      const { startTime, duration } = localTimerRef.current;
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      const remaining = Math.max(0, duration - elapsed);

      if (remaining > 0) {
        setRestTimer({
          is_active: true,
          remaining_seconds: remaining,
          total_seconds: duration,
        });
      } else {
        // Timer finished
        setRestTimer({ is_active: false, remaining_seconds: 0, total_seconds: duration });
        localTimerRef.current = null;
      }
      return;
    }

    // Fallback to session data (for resuming app with active timer)
    if (session?.rest_timer_started_at && session?.rest_timer_duration_seconds) {
      const startTime = new Date(session.rest_timer_started_at).getTime();
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      const remaining = Math.max(0, session.rest_timer_duration_seconds - elapsed);

      if (remaining > 0) {
        // Sync local ref with session data
        localTimerRef.current = { startTime, duration: session.rest_timer_duration_seconds };
        setRestTimer({
          is_active: true,
          remaining_seconds: remaining,
          total_seconds: session.rest_timer_duration_seconds,
        });
      } else {
        setRestTimer(null);
      }
    }
  }, [session?.rest_timer_started_at, session?.rest_timer_duration_seconds]);

  const startWorkout = async (templateId: string): Promise<ActiveWorkoutSession | null> => {
    try {
      setIsLoading(true);
      setError(null);
      const result = await fitnessService.startWorkoutSession(templateId);
      setSession(result.session);
      if (result.session?.id) {
        await AsyncStorage.setItem(STORAGE_KEY, result.session.id);
      }
      return result.session;
    } catch (err: any) {
      console.error('Failed to start workout:', err);
      setError(err.message);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  const logSet = async (params: LogSetParams) => {
    try {
      setError(null);
      const result = await fitnessService.logWorkoutSet(params);
      // Refresh session to get updated state
      await refreshSession();
      return {
        success: result.success,
        coaching_feedback: result.coaching_feedback,
      };
    } catch (err: any) {
      console.error('Failed to log set:', err);
      setError(err.message);
      return { success: false };
    }
  };

  const skipExercise = async () => {
    try {
      setError(null);
      await fitnessService.skipExercise();
      await refreshSession();
    } catch (err: any) {
      console.error('Failed to skip exercise:', err);
      setError(err.message);
    }
  };

  const startRestTimer = async (duration?: number) => {
    try {
      const defaultDuration = duration || 120;
      // Set local ref for immediate countdown (avoids stale closure issues)
      localTimerRef.current = {
        startTime: Date.now(),
        duration: defaultDuration,
      };
      // Immediately show the timer
      setRestTimer({
        is_active: true,
        remaining_seconds: defaultDuration,
        total_seconds: defaultDuration,
      });
      // Persist to backend (non-blocking)
      fitnessService.manageRestTimer('start', defaultDuration).catch(err => {
        console.error('Failed to persist rest timer:', err);
      });
    } catch (err: any) {
      console.error('Failed to start rest timer:', err);
      localTimerRef.current = null;
      setRestTimer(null);
    }
  };

  const stopRestTimer = async () => {
    try {
      localTimerRef.current = null;
      setRestTimer(null);
      await fitnessService.manageRestTimer('stop');
    } catch (err: any) {
      console.error('Failed to stop rest timer:', err);
    }
  };

  const completeWorkout = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const result = await fitnessService.completeWorkoutSession();
      setSession(null);
      await AsyncStorage.removeItem(STORAGE_KEY);
      return { summary: result.summary };
    } catch (err: any) {
      console.error('Failed to complete workout:', err);
      setError(err.message);
      return {};
    } finally {
      setIsLoading(false);
    }
  };

  const abandonWorkout = async () => {
    try {
      setIsLoading(true);
      setError(null);
      await fitnessService.abandonWorkoutSession();
      setSession(null);
      await AsyncStorage.removeItem(STORAGE_KEY);
    } catch (err: any) {
      console.error('Failed to abandon workout:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // Computed values
  const currentExercise = session?.workout_snapshot?.exercises?.[session.current_exercise_index] || null;
  const currentSetNumber = (session?.current_set_index || 0) + 1;

  const totalSets = session?.workout_snapshot?.exercises?.reduce((acc, ex) => acc + ex.sets, 0) || 0;
  const completedSets = session?.total_sets_completed || 0;
  const progress = {
    completed: completedSets,
    total: totalSets,
    percentage: totalSets > 0 ? Math.round((completedSets / totalSets) * 100) : 0,
  };

  const value: WorkoutModeContextType = {
    session,
    isActive: session?.status === 'active',
    isLoading,
    error,
    restTimer,
    startWorkout,
    logSet,
    skipExercise,
    startRestTimer,
    stopRestTimer,
    completeWorkout,
    abandonWorkout,
    refreshSession,
    currentExercise,
    currentSetNumber,
    progress,
  };

  return (
    <WorkoutModeContext.Provider value={value}>
      {children}
    </WorkoutModeContext.Provider>
  );
}

export function useWorkoutMode() {
  const context = useContext(WorkoutModeContext);
  if (context === undefined) {
    throw new Error('useWorkoutMode must be used within a WorkoutModeProvider');
  }
  return context;
}

export default WorkoutModeContext;

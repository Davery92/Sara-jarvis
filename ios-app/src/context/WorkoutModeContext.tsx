import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fitnessService, ActiveWorkoutSession, LogSetParams, RestTimerStatus } from '../services/fitness';
import { startEvent, updateEvent, endEvent } from '../services/eventActivity';
import { watchWorkout } from '../services/watchWorkout';
import { workoutCoordinator } from '../services/workoutCoordinator';
import { workoutCoaching } from '../services/workoutCoaching';
import type { CoachingEvent, LiveMetrics, WorkoutProposal } from '../services/workoutContracts';

/**
 * Quiet device state for Workout Mode (plan §9.3).
 *
 * Shown only when it tells David something he can act on. "Watch tracking" and
 * a heart rate are reassurance; transport vocabulary in a normal success state
 * is noise that trains him to ignore the one message that matters.
 */
export interface WatchWorkoutStatus {
  /** The Watch has a live HealthKit session mirrored here. */
  tracking: boolean;
  heartRate: number | null;
  activeEnergyKcal: number | null;
  /** Commands issued but not yet durably accepted. */
  pending: number;
  reconnecting: boolean;
}

interface WorkoutModeContextType {
  // State
  session: ActiveWorkoutSession | null;
  isActive: boolean;
  isLoading: boolean;
  error: string | null;
  restTimer: RestTimerStatus | null;

  // Cross-device (Apple Watch) — additive; nothing below is removed.
  watch: WatchWorkoutStatus;
  /** Sara's recommendation awaiting a decision. Never applied on its own. */
  pendingProposal: WorkoutProposal | null;
  /** The coaching sentence currently being said, for the on-screen line (§9.5). */
  coaching: CoachingEvent | null;
  approveProposal: (proposalId: string) => Promise<void>;
  rejectProposal: (proposalId: string) => Promise<void>;
  /** Retry bringing the Watch into a phone-started workout (§4.3). */
  retryWatch: () => Promise<void>;

  // Actions
  startWorkout: (templateId: string) => Promise<ActiveWorkoutSession | null>;
  logSet: (params: LogSetParams) => Promise<{
    success: boolean;
    coaching_feedback?: string;
    rest_seconds?: number;
    pr?: { is_pr: boolean; estimated_1rm?: number; previous_best?: number | null } | null;
  }>;
  skipExercise: () => Promise<void>;
  selectExercise: (exerciseIndex: number) => Promise<void>;
  setVariant: (exerciseIndex: number, variant: string | null) => Promise<void>;
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

  // ── Cross-device state (§9.2, §9.3, §9.5) ───────────────────────────────
  const [watch, setWatch] = useState<WatchWorkoutStatus>({
    tracking: false, heartRate: null, activeEnergyKcal: null, pending: 0, reconnecting: false,
  });
  const [pendingProposal, setPendingProposal] = useState<WorkoutProposal | null>(null);
  const [coaching, setCoaching] = useState<CoachingEvent | null>(null);

  // Mirror/metrics/queue depth all feed one status object so the UI has a
  // single thing to render rather than three racing booleans.
  useEffect(() => {
    const unsubMirror = watchWorkout.onMirrorState((state) => {
      setWatch(prev => ({
        ...prev,
        tracking: state.mirroring && state.state === 'running',
        reconnecting: state.mirroring && state.state !== 'running',
      }));
    });
    const unsubMetrics = watchWorkout.onLiveMetrics((metrics: LiveMetrics | null) => {
      setWatch(prev => ({
        ...prev,
        heartRate: metrics?.heart_rate ?? null,
        activeEnergyKcal: metrics?.active_energy_kcal ?? null,
      }));
    });
    const unsubCoordinator = workoutCoordinator.subscribe((state) => {
      setWatch(prev => ({ ...prev, pending: state.pendingCount }));
      setPendingProposal(state.projection?.pending_proposal ?? null);
    });
    const unsubCoaching = workoutCoaching.onDisplay(setCoaching);
    return () => {
      unsubMirror();
      unsubMetrics();
      unsubCoordinator();
      unsubCoaching();
    };
  }, []);

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

  /**
   * Push the canonical state out to the Watch and keep the coordinator's copy
   * current after a phone-originated change (§4.4).
   *
   * `sync` is what actually re-reads the projection — the legacy endpoints
   * return their own older shape — and `broadcast` is a no-op when no Watch is
   * mirrored, so this is safe to call unconditionally.
   */
  const syncWatch = useCallback(async () => {
    try {
      const state = await workoutCoordinator.sync();
      await watchWorkout.broadcast(state.projection);
    } catch {
      // Best effort: the phone workout is unaffected by a Watch that isn't
      // listening.
    }
  }, []);

  // Coaching runs for the length of the workout and stops with it, so a
  // sentence about the last set can never arrive after the summary (§10.4).
  const coachingActiveRef = useRef(false);
  useEffect(() => {
    const active = session?.status === 'active';
    if (active && !coachingActiveRef.current) {
      coachingActiveRef.current = true;
      void fitnessService
        .v2Policy()
        .then(({ policy }) => workoutCoaching.start(policy))
        .catch(() => workoutCoaching.start());
    } else if (!active && coachingActiveRef.current) {
      coachingActiveRef.current = false;
      workoutCoaching.stop();
    }
  }, [session?.status]);

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
      // Bring the Watch into the same workout so David doesn't have to start
      // Apple's Workout app by hand (§4.3). Deliberately not awaited and never
      // fatal: the backend session already exists, so a Watch that won't wake
      // costs heart rate, not the workout.
      void watchWorkout.launchWatch('strength');
      void syncWatch();
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
      // The set is durable; the Watch needs the new cursor and set count now,
      // not on its next poll.
      void syncWatch();
      // Sara may recommend a change off the back of this set — surfaced as
      // Approve / Keep current, never applied (§9.5, §11.2).
      if ((result as any).proposal) {
        setPendingProposal((result as any).proposal as WorkoutProposal);
      }
      return {
        success: result.success,
        coaching_feedback: result.coaching_feedback,
        rest_seconds: result.next_set?.rest_seconds,
        pr: result.pr ?? null,
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
      void syncWatch();
    } catch (err: any) {
      console.error('Failed to skip exercise:', err);
      setError(err.message);
    }
  };

  const selectExercise = async (exerciseIndex: number) => {
    try {
      setError(null);
      // Optimistically move the cursor so the UI responds instantly; the next
      // poll / refresh reconciles current_set_index from the backend.
      setSession(prev => prev ? { ...prev, current_exercise_index: exerciseIndex } : prev);
      await fitnessService.selectExercise(exerciseIndex);
      await refreshSession();
      void syncWatch();
    } catch (err: any) {
      console.error('Failed to select exercise:', err);
      setError(err.message);
      await refreshSession();
    }
  };

  const setVariant = async (exerciseIndex: number, variant: string | null) => {
    try {
      setError(null);
      await fitnessService.setExerciseVariant(exerciseIndex, variant);
      await refreshSession();
      void syncWatch();
    } catch (err: any) {
      console.error('Failed to set exercise variant:', err);
      setError(err.message);
    }
  };

  const startRestTimer = async (duration?: number) => {
    try {
      const defaultDuration = duration || 120;
      const startedAt = Date.now();
      // Set local ref for immediate countdown (avoids stale closure issues)
      localTimerRef.current = {
        startTime: startedAt,
        duration: defaultDuration,
      };
      // Immediately show the timer
      setRestTimer({
        is_active: true,
        remaining_seconds: defaultDuration,
        total_seconds: defaultDuration,
      });
      // Keep the session's timer fields in sync too, so the resume-fallback in
      // updateRestTimer can never resurrect a stale (pre-log) countdown after a
      // refreshSession races in with the old backend timer. This is what made
      // logging a set mid-countdown fail to reset the timer.
      setSession(prev => prev ? {
        ...prev,
        rest_timer_started_at: new Date(startedAt).toISOString(),
        rest_timer_duration_seconds: defaultDuration,
      } : prev);
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
      // Both devices end together: leaving the Watch's HealthKit session
      // running would keep burning battery and recording a workout that Sara
      // has already closed (§4.5 step 7).
      await watchWorkout.endWatchWorkout('completed on phone');
      workoutCoordinator.reset();
      return { summary: result.summary };
    } catch (err: any) {
      console.error('Failed to complete workout:', err);
      setError(err.message);
      // David tried to end the workout — even though the server call failed,
      // the Live Activity must not keep ticking as if it's still in progress
      // (the session-effect's endEvent only fires when `session` clears,
      // which doesn't happen on this error path).
      if (workoutActivityRef.current) {
        endEvent(workoutActivityRef.current);
        workoutActivityRef.current = null;
      }
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
      // Abandonment is broadcast, not inferred — the Watch must stop tracking
      // a workout whose sets have just been deleted (§4.6).
      await watchWorkout.endWatchWorkout('abandoned on phone');
      workoutCoordinator.reset();
    } catch (err: any) {
      console.error('Failed to abandon workout:', err);
      setError(err.message);
      if (workoutActivityRef.current) {
        endEvent(workoutActivityRef.current);
        workoutActivityRef.current = null;
      }
    } finally {
      setIsLoading(false);
    }
  };

  // ── Approval boundary (§11.3) ───────────────────────────────────────────

  /**
   * Approve or reject exactly one recommendation.
   *
   * Both go through the coordinator's idempotent command path, so a tap lost
   * in flight resolves once when it replays. The proposal is cleared locally
   * either way — and coaching is told to stop talking about it, because
   * "I recommend dropping to 60" spoken after the answer is worse than
   * silence (§10.4).
   */
  const resolveProposal = useCallback(async (proposalId: string, approve: boolean) => {
    workoutCoaching.markProposalResolved(proposalId);
    setPendingProposal(null);
    try {
      await workoutCoordinator.resolveProposal(proposalId, approve, 'phone');
      await refreshSession();
      await syncWatch();
    } catch (err: any) {
      console.error('Failed to resolve proposal:', err);
      setError(err.message);
    }
  }, [refreshSession, syncWatch]);

  const approveProposal = useCallback(
    (proposalId: string) => resolveProposal(proposalId, true), [resolveProposal]
  );
  const rejectProposal = useCallback(
    (proposalId: string) => resolveProposal(proposalId, false), [resolveProposal]
  );

  /** Ask the Watch again after a failed launch — §4.3's "Retry Watch". */
  const retryWatch = useCallback(async () => {
    await watchWorkout.launchWatch('strength');
  }, []);

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
    watch,
    pendingProposal,
    coaching,
    approveProposal,
    rejectProposal,
    retryWatch,
    startWorkout,
    logSet,
    skipExercise,
    selectExercise,
    setVariant,
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

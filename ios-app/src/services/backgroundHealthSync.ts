/**
 * Background Health Sync Service
 *
 * Registers and handles iOS Background App Refresh for health data sync.
 * Syncs granular health metrics every 15 minutes to enable proactive health monitoring.
 *
 * Uses:
 * - expo-background-fetch for background task scheduling
 * - expo-task-manager for task definition
 */

import { Platform } from 'react-native';
import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import { healthKitService } from './healthKit';
import { healthSyncService } from './healthSync';
import { apiClient } from './api';
import AsyncStorage from '@react-native-async-storage/async-storage';

const HEALTH_SYNC_TASK = 'HEALTH_SYNC_BACKGROUND_TASK';
const BACKGROUND_SYNC_KEY = '@sara_background_health_sync';
const BACKGROUND_SYNC_COUNT_KEY = '@sara_background_sync_count';
const LAST_WORKOUT_SYNC_KEY = '@sara_last_workout_sync';
// One-time deep backfill so older watch workouts (before the app first synced)
// get ingested too — the HR meld is retroactive, so this lights up past sessions.
const WORKOUT_BACKFILL_KEY = '@sara_workout_backfill_done_v1';
const WORKOUT_BACKFILL_DAYS = 365;

// Types for granular health metrics
interface HealthMetric {
  metric_type: string;
  value: number;
  recorded_at: string;
  source?: string;
  metadata?: Record<string, any>;
}

interface BatchMetricsPayload {
  metrics: HealthMetric[];
  daily_recovery?: {
    hrv?: number;
    resting_hr?: number;
    sleep_hours?: number;
  };
}

/**
 * Reduce a sample array to roughly `target` evenly-spaced picks.
 * If the array is already smaller than target, returns it unchanged.
 */
function decimateSamples<T>(samples: T[], target: number): T[] {
  if (samples.length <= target) return samples;
  const step = samples.length / target;
  const out: T[] = [];
  for (let i = 0; i < target; i++) {
    out.push(samples[Math.floor(i * step)]);
  }
  return out;
}

/**
 * Drop metrics with non-finite or null values + invalid recorded_at.
 * NaN/Infinity get JSON-stringified as null, which the backend rejects.
 */
function sanitizeMetrics(metrics: HealthMetric[]): HealthMetric[] {
  return metrics.filter((m) => {
    if (m.value == null || !Number.isFinite(m.value)) return false;
    if (!m.recorded_at || typeof m.recorded_at !== 'string') return false;
    if (!m.metric_type) return false;
    return true;
  });
}

/**
 * Collect granular health metrics from HealthKit
 */
async function collectHealthMetrics(): Promise<HealthMetric[]> {
  const now = new Date();
  const metrics: HealthMetric[] = [];

  try {
    // Initialize HealthKit if needed
    if (!healthKitService.isHealthKitAvailable()) {
      await healthKitService.initialize();
    }

    if (!healthKitService.isHealthKitAvailable()) {
      console.log('[BackgroundHealth] HealthKit not available');
      return [];
    }

    // 1. Resting Heart Rate
    const restingHR = await healthKitService.getRestingHeartRate();
    if (restingHR !== null) {
      metrics.push({
        metric_type: 'resting_hr',
        value: restingHR,
        recorded_at: now.toISOString(),
        source: 'apple_health',
      });
    }

    // 2. HRV — sync all samples in last 4h with context tag.
    //    Morning samples (5-8 AM) get a stable canonical 6 AM row + flag for downstream
    //    consumers that want a single daily HRV; daytime/evening samples are tagged so
    //    they can be filtered by the analysis layer rather than thrown away here.
    const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000);
    const hour = now.getHours();
    const hrvSamples = await healthKitService.getHRVSamples(fourHoursAgo, now);
    for (const sample of hrvSamples) {
      const sampleHour = new Date(sample.startDate).getHours();
      const context = sampleHour >= 0 && sampleHour < 4
        ? 'sleep'
        : sampleHour >= 4 && sampleHour < 10
          ? 'morning'
          : sampleHour >= 10 && sampleHour < 17
            ? 'day'
            : 'evening';
      metrics.push({
        metric_type: 'hrv',
        value: sample.value,
        recorded_at: sample.startDate,
        source: 'apple_health',
        metadata: { context },
      });
    }
    // Canonical morning HRV row (6 AM stamped) so daily aggregates have a stable key
    if (hour >= 5 && hour < 8 && hrvSamples.length > 0) {
      const morningSamples = hrvSamples.filter((s) => {
        const h = new Date(s.startDate).getHours();
        return h >= 4 && h < 10;
      });
      if (morningSamples.length > 0) {
        const avgMorning = Math.round(
          morningSamples.reduce((sum, s) => sum + s.value, 0) / morningSamples.length
        );
        const hrvRecordedAt = new Date(now);
        hrvRecordedAt.setHours(6, 0, 0, 0);
        metrics.push({
          metric_type: 'hrv_morning',
          value: avgMorning,
          recorded_at: hrvRecordedAt.toISOString(),
          source: 'apple_health',
          metadata: { morning_reading: true, sample_count: morningSamples.length },
        });
      }
    }

    // 3. Heart rate samples from last 4 hours.
    //    Decimate large series to ~120 samples to avoid payload bloat while preserving
    //    enough density to detect spikes/drops (≈1 sample/2min over 4h).
    const hrSamples = await healthKitService.getHeartRateSamples(fourHoursAgo, now);
    const hrSelected = decimateSamples(hrSamples, 120);
    for (const sample of hrSelected) {
      metrics.push({
        metric_type: 'heart_rate',
        value: sample.value,
        recorded_at: sample.startDate,
        source: 'apple_health',
      });
    }

    // 4. Sleep last night — full stage breakdown (morning sync only).
    //    Emits sleep_hours + per-stage minutes + bedtime/wake-time so the
    //    analysis layer can compute deep%, REM%, sleep efficiency, etc.
    if (hour >= 5 && hour <= 12) {
      const sleepBreakdown = await healthKitService.getSleepStagesBreakdown();
      const sleepRecordedAt = new Date(now);
      sleepRecordedAt.setHours(6, 0, 0, 0);
      const stampIso = sleepRecordedAt.toISOString();

      if (sleepBreakdown.totalAsleepHours > 0) {
        metrics.push({
          metric_type: 'sleep_hours',
          value: sleepBreakdown.totalAsleepHours,
          recorded_at: stampIso,
          source: 'apple_health',
          metadata: {
            stages_minutes: sleepBreakdown.stages,
            bedtime: sleepBreakdown.bedtime,
            wake_time: sleepBreakdown.wakeTime,
            in_bed_hours: sleepBreakdown.totalInBedHours,
          },
        });

        // Individual stage rows for trend queries that don't want to JSON-extract
        const stageMetrics: Array<[string, number]> = [
          ['sleep_deep_min', sleepBreakdown.stages.asleep_deep],
          ['sleep_rem_min', sleepBreakdown.stages.asleep_rem],
          ['sleep_core_min', sleepBreakdown.stages.asleep_core],
          ['sleep_awake_min', sleepBreakdown.stages.awake],
        ];
        for (const [type, value] of stageMetrics) {
          if (value > 0) {
            metrics.push({
              metric_type: type,
              value,
              recorded_at: stampIso,
              source: 'apple_health',
            });
          }
        }
      }
    }

    // 5. Steps today
    const steps = await healthKitService.getStepsToday();
    if (steps > 0) {
      metrics.push({
        metric_type: 'steps',
        value: steps,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true },
      });
    }

    // 6. Active energy today
    const activeEnergy = await healthKitService.getActiveEnergyToday();
    if (activeEnergy > 0) {
      metrics.push({
        metric_type: 'active_energy',
        value: activeEnergy,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true, unit: 'kcal' },
      });
    }

    // 7. Weight
    const weight = await healthKitService.getLatestWeight();
    if (weight !== null) {
      metrics.push({
        metric_type: 'weight',
        value: weight,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { unit: 'lb' },
      });
    }

    // 8. Vitals — SpO2, respiratory rate, body temp (all opportunistic; null is fine)
    const [spo2, respRate, bodyTemp] = await Promise.all([
      healthKitService.getLatestSpO2(),
      healthKitService.getLatestRespiratoryRate(),
      healthKitService.getLatestBodyTemp(),
    ]);
    if (spo2) {
      metrics.push({
        metric_type: 'spo2',
        value: spo2.value,
        recorded_at: spo2.recordedAt,
        source: 'apple_health',
        metadata: { unit: 'percent' },
      });
    }
    if (respRate) {
      metrics.push({
        metric_type: 'respiratory_rate',
        value: respRate.value,
        recorded_at: respRate.recordedAt,
        source: 'apple_health',
        metadata: { unit: 'breaths_per_min' },
      });
    }
    if (bodyTemp) {
      metrics.push({
        metric_type: 'body_temp',
        value: bodyTemp.value,
        recorded_at: bodyTemp.recordedAt,
        source: 'apple_health',
        metadata: { unit: 'degF' },
      });
    }

    // 9. Cardiovascular — VO2 max, walking HR avg, HR recovery (Watch-derived; periodic)
    const [vo2, walkingHR, hrRecovery] = await Promise.all([
      healthKitService.getLatestVO2Max(),
      healthKitService.getWalkingHRAvg(),
      healthKitService.getLatestHRRecovery(),
    ]);
    if (vo2) {
      metrics.push({
        metric_type: 'vo2_max',
        value: vo2.value,
        recorded_at: vo2.recordedAt,
        source: 'apple_health',
        metadata: { unit: 'ml_kg_min' },
      });
    }
    if (walkingHR) {
      metrics.push({
        metric_type: 'walking_hr_avg',
        value: walkingHR.value,
        recorded_at: walkingHR.recordedAt,
        source: 'apple_health',
      });
    }
    if (hrRecovery) {
      metrics.push({
        metric_type: 'hr_recovery_1min',
        value: hrRecovery.value,
        recorded_at: hrRecovery.recordedAt,
        source: 'apple_health',
      });
    }

    // 10. Activity rings — stand minutes, exercise minutes, flights climbed, mindful minutes
    const [standMin, exerciseMin, flights, mindfulMin] = await Promise.all([
      healthKitService.getStandMinutesToday(),
      healthKitService.getExerciseMinutesToday(),
      healthKitService.getFlightsClimbedToday(),
      healthKitService.getMindfulMinutesToday(),
    ]);
    if (standMin > 0) {
      metrics.push({
        metric_type: 'stand_minutes',
        value: standMin,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true },
      });
    }
    if (exerciseMin > 0) {
      metrics.push({
        metric_type: 'exercise_minutes',
        value: exerciseMin,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true },
      });
    }
    if (flights > 0) {
      metrics.push({
        metric_type: 'flights_climbed',
        value: flights,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true },
      });
    }
    if (mindfulMin > 0) {
      metrics.push({
        metric_type: 'mindful_minutes',
        value: mindfulMin,
        recorded_at: now.toISOString(),
        source: 'apple_health',
        metadata: { cumulative: true },
      });
    }

    console.log(`[BackgroundHealth] Collected ${metrics.length} health metrics`);
    return metrics;

  } catch (error) {
    console.log('[BackgroundHealth] Error collecting metrics:', error);
    return metrics;
  }
}

/**
 * Sync HealthKit workouts to backend.
 *
 * Tracks its own cursor (last successful workout-sync timestamp) and queries
 * workouts since that cursor minus a 1h overlap to catch late-arriving samples.
 * Backend dedupes on (user_id, source, external_id).
 */
async function syncWorkoutsToBackend(): Promise<{ count: number; success: boolean }> {
  try {
    if (!healthKitService.isHealthKitAvailable()) return { count: 0, success: false };

    const cursorStr = await AsyncStorage.getItem(LAST_WORKOUT_SYNC_KEY);
    const backfillDone = await AsyncStorage.getItem(WORKOUT_BACKFILL_KEY);
    const now = new Date();
    // One-time deep backfill of older watch workouts; then cursor minus 1h
    // overlap; falling back to 7 days if there's somehow no cursor. The backend
    // dedupes on (user_id, source, external_id), so re-ingesting is harmless.
    let since: Date;
    if (!backfillDone) {
      since = new Date(now.getTime() - WORKOUT_BACKFILL_DAYS * 24 * 60 * 60 * 1000);
    } else if (cursorStr) {
      since = new Date(parseInt(cursorStr, 10) - 60 * 60 * 1000);
    } else {
      since = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    }

    const workouts = await healthKitService.getWorkoutsForSync(since, now);
    if (workouts.length === 0) {
      // Still mark the backfill done so we don't re-scan a year every run.
      if (!backfillDone) await AsyncStorage.setItem(WORKOUT_BACKFILL_KEY, '1');
      return { count: 0, success: true };
    }

    await apiClient.post('/api/health/workouts/batch', { workouts });
    await AsyncStorage.setItem(LAST_WORKOUT_SYNC_KEY, now.getTime().toString());
    if (!backfillDone) await AsyncStorage.setItem(WORKOUT_BACKFILL_KEY, '1');
    console.log(`[BackgroundHealth] Synced ${workouts.length} workouts since ${since.toISOString()}`);
    return { count: workouts.length, success: true };
  } catch (error) {
    console.log('[BackgroundHealth] Workout sync error:', error);
    return { count: 0, success: false };
  }
}

/**
 * Send metrics to backend
 */
async function syncMetricsToBackend(metrics: HealthMetric[]): Promise<boolean> {
  metrics = sanitizeMetrics(metrics);
  if (metrics.length === 0) {
    console.log('[BackgroundHealth] No metrics to sync');
    return true;
  }

  try {
    const payload: BatchMetricsPayload = { metrics };

    // Include daily recovery for backward compatibility
    const hrv = metrics.find(m => m.metric_type === 'hrv')?.value;
    const restingHr = metrics.find(m => m.metric_type === 'resting_hr')?.value;
    const sleepHours = metrics.find(m => m.metric_type === 'sleep_hours')?.value;

    if (hrv || restingHr || sleepHours) {
      payload.daily_recovery = { hrv, resting_hr: restingHr, sleep_hours: sleepHours };
    }

    await apiClient.post('/api/health/metrics/batch', payload);
    console.log(`[BackgroundHealth] Successfully synced ${metrics.length} metrics`);
    return true;

  } catch (error) {
    console.log('[BackgroundHealth] Error syncing to backend:', error);
    return false;
  }
}

/**
 * Record sync for debugging
 */
async function recordSyncAttempt(success: boolean, metricCount: number): Promise<void> {
  try {
    const now = new Date().toISOString();
    await AsyncStorage.setItem(BACKGROUND_SYNC_KEY, JSON.stringify({
      lastSync: now,
      success,
      metricCount,
    }));

    const countStr = await AsyncStorage.getItem(BACKGROUND_SYNC_COUNT_KEY);
    const count = countStr ? parseInt(countStr, 10) : 0;
    await AsyncStorage.setItem(BACKGROUND_SYNC_COUNT_KEY, (count + 1).toString());
  } catch (error) {
    console.log('[BackgroundHealth] Error recording sync:', error);
  }
}

// Define the background task
TaskManager.defineTask(HEALTH_SYNC_TASK, async () => {
  console.log('[BackgroundHealth] Background task starting...');

  try {
    const metrics = await collectHealthMetrics();
    const success = await syncMetricsToBackend(metrics);

    // Sync HealthKit workouts (Apple Watch runs/walks/etc.) — separate stream
    // from David's manually-logged strength sessions.
    try {
      await syncWorkoutsToBackend();
    } catch (e) {
      console.log('[BackgroundHealth] Workout sync error (non-fatal):', e);
    }

    // Also update daily_recovery_log (HRV/HR/sleep/weight aggregate) so the
    // recovery view stays current without depending on the user opening the app.
    try {
      await healthSyncService.forceSync();
    } catch (e) {
      console.log('[BackgroundHealth] Recovery sync error (non-fatal):', e);
    }

    await recordSyncAttempt(success, metrics.length);

    if (success && metrics.length > 0) {
      return BackgroundFetch.BackgroundFetchResult.NewData;
    } else if (success) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    } else {
      return BackgroundFetch.BackgroundFetchResult.Failed;
    }

  } catch (error) {
    console.log('[BackgroundHealth] Background task error:', error);
    await recordSyncAttempt(false, 0);
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

/**
 * Register the background health sync task
 */
export async function registerBackgroundHealthSync(): Promise<boolean> {
  if (Platform.OS !== 'ios') {
    console.log('[BackgroundHealth] Background fetch only supported on iOS');
    return false;
  }

  try {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(HEALTH_SYNC_TASK);
    if (isRegistered) {
      console.log('[BackgroundHealth] Task already registered');
      return true;
    }

    await BackgroundFetch.registerTaskAsync(HEALTH_SYNC_TASK, {
      minimumInterval: 15 * 60, // 15 minutes
      stopOnTerminate: false,
      startOnBoot: true,
    });

    console.log('[BackgroundHealth] Background health sync registered');
    return true;

  } catch (error) {
    console.log('[BackgroundHealth] Failed to register background task:', error);
    return false;
  }
}

/**
 * Unregister the background health sync task
 */
export async function unregisterBackgroundHealthSync(): Promise<boolean> {
  try {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(HEALTH_SYNC_TASK);
    if (!isRegistered) {
      return true;
    }

    await BackgroundFetch.unregisterTaskAsync(HEALTH_SYNC_TASK);
    console.log('[BackgroundHealth] Background health sync unregistered');
    return true;

  } catch (error) {
    console.log('[BackgroundHealth] Failed to unregister background task:', error);
    return false;
  }
}

/**
 * Check background fetch status
 */
export async function getBackgroundFetchStatus(): Promise<{
  status: number;
  statusName: string;
  isRegistered: boolean;
  lastSync?: string;
  syncCount?: number;
}> {
  let lastSync: string | undefined;
  let syncCount: number | undefined;

  try {
    const syncData = await AsyncStorage.getItem(BACKGROUND_SYNC_KEY);
    if (syncData) {
      const parsed = JSON.parse(syncData);
      lastSync = parsed.lastSync;
    }
    const countStr = await AsyncStorage.getItem(BACKGROUND_SYNC_COUNT_KEY);
    if (countStr) {
      syncCount = parseInt(countStr, 10);
    }
  } catch {}

  const status = await BackgroundFetch.getStatusAsync();

  const statusNames: Record<number, string> = {
    [BackgroundFetch.BackgroundFetchStatus.Denied]: 'Denied',
    [BackgroundFetch.BackgroundFetchStatus.Restricted]: 'Restricted',
    [BackgroundFetch.BackgroundFetchStatus.Available]: 'Available',
  };

  const isRegistered = await TaskManager.isTaskRegisteredAsync(HEALTH_SYNC_TASK);

  return {
    status,
    statusName: statusNames[status] || 'Unknown',
    isRegistered,
    lastSync,
    syncCount,
  };
}

/**
 * Convert a daily history row into the metric_type rows the backend expects.
 * Stamps daily metrics at noon local time on the given date so cumulative
 * upserts dedupe per (user_id, metric_type, recorded_at).
 */
function dailyRowToMetrics(row: Awaited<ReturnType<typeof healthKitService.getDailyHistory>>[0]): HealthMetric[] {
  const metrics: HealthMetric[] = [];
  // Anchor cumulative metrics at noon local on that date for stable dedup.
  const noon = new Date(`${row.date}T12:00:00`);
  const noonIso = noon.toISOString();

  if (row.steps > 0) metrics.push({ metric_type: 'steps', value: row.steps, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true } });
  if (row.active_energy > 0) metrics.push({ metric_type: 'active_energy', value: row.active_energy, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true, unit: 'kcal' } });
  if (row.stand_minutes > 0) metrics.push({ metric_type: 'stand_minutes', value: row.stand_minutes, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true } });
  if (row.exercise_minutes > 0) metrics.push({ metric_type: 'exercise_minutes', value: row.exercise_minutes, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true } });
  if (row.flights_climbed > 0) metrics.push({ metric_type: 'flights_climbed', value: row.flights_climbed, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true } });
  if (row.mindful_minutes > 0) metrics.push({ metric_type: 'mindful_minutes', value: row.mindful_minutes, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, cumulative: true } });

  if (row.resting_hr != null) metrics.push({ metric_type: 'resting_hr', value: row.resting_hr, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true } });
  if (row.weight_lb != null) metrics.push({ metric_type: 'weight', value: row.weight_lb, recorded_at: noonIso, source: 'apple_health', metadata: { backfill: true, unit: 'lb' } });

  // HRV — full sample series for the day (so anomaly direction is meaningful)
  for (const s of row.hrv_samples) {
    metrics.push({ metric_type: 'hrv', value: s.value, recorded_at: s.startDate, source: 'apple_health', metadata: { backfill: true } });
  }

  // Sleep — total + per-stage rows stamped at 6 AM on the date for dedup
  if (row.sleep && row.sleep.total_asleep_hours > 0) {
    const sleepStamp = new Date(`${row.date}T06:00:00`).toISOString();
    metrics.push({
      metric_type: 'sleep_hours', value: row.sleep.total_asleep_hours,
      recorded_at: sleepStamp, source: 'apple_health',
      metadata: {
        backfill: true,
        stages_minutes: row.sleep.stages,
        bedtime: row.sleep.bedtime,
        wake_time: row.sleep.wake_time,
      },
    });
    const stages = row.sleep.stages;
    const stageRows: Array<[string, number]> = [
      ['sleep_deep_min', stages.asleep_deep],
      ['sleep_rem_min', stages.asleep_rem],
      ['sleep_core_min', stages.asleep_core],
      ['sleep_awake_min', stages.awake],
    ];
    for (const [type, value] of stageRows) {
      if (value > 0) {
        metrics.push({ metric_type: type, value, recorded_at: sleepStamp, source: 'apple_health', metadata: { backfill: true } });
      }
    }
  }

  return metrics;
}

/**
 * One-time historical backfill of the last `daysBack` days of HealthKit data.
 *
 * Pulls daily-aggregated metrics + all workouts in the window, batches them to
 * the backend, and reports counts. Backend dedups via the existing unique
 * indexes (health_metric uses (user_id, metric_type, recorded_at);
 * external_workout uses (user_id, source, external_id)) so re-running is safe.
 */
export type BackfillProgress = {
  phase: 'init' | 'metrics' | 'workouts' | 'done';
  dayIndex: number;
  totalDays: number;
  metricsInserted: number;
  workoutsInserted: number;
  message: string;
};

/**
 * Race a promise against a timeout so a single hung HealthKit query can't lock the loop.
 */
function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`${label} timeout after ${ms}ms`)), ms);
    p.then(
      (v) => { clearTimeout(t); resolve(v); },
      (e) => { clearTimeout(t); reject(e); },
    );
  });
}

export async function backfillHistoricalData(
  daysBack: number = 90,
  onProgress?: (p: BackfillProgress) => void,
): Promise<{
  success: boolean;
  daysProcessed: number;
  metricsInserted: number;
  metricsDuplicate: number;
  workoutsInserted: number;
  workoutsDuplicate: number;
  message: string;
}> {
  console.log(`[BackgroundHealth] Starting backfill of last ${daysBack} days...`);

  if (Platform.OS !== 'ios') {
    return { success: false, daysProcessed: 0, metricsInserted: 0, metricsDuplicate: 0, workoutsInserted: 0, workoutsDuplicate: 0, message: 'iOS only' };
  }

  if (!healthKitService.isHealthKitAvailable()) {
    const ok = await healthKitService.initialize();
    if (!ok) {
      return { success: false, daysProcessed: 0, metricsInserted: 0, metricsDuplicate: 0, workoutsInserted: 0, workoutsDuplicate: 0, message: 'HealthKit unavailable' };
    }
  }

  const now = new Date();
  const start = new Date(now); start.setDate(start.getDate() - daysBack); start.setHours(0, 0, 0, 0);

  let totalMetricsInserted = 0;
  let totalMetricsDuplicate = 0;
  let totalDays = 0;

  // Walk DAY BY DAY with per-day POST so the user sees forward progress and a
  // single hung HealthKit query (or slow sleep-merge) can't hold the whole
  // loop hostage. Each per-day query is wrapped with a 30s timeout.
  onProgress?.({ phase: 'init', dayIndex: 0, totalDays: daysBack, metricsInserted: 0, workoutsInserted: 0, message: 'Reading HealthKit history…' });

  for (let i = 0; i < daysBack; i++) {
    const dayStart = new Date(start); dayStart.setDate(start.getDate() + i);
    const dayEnd = new Date(dayStart); dayEnd.setHours(23, 59, 59, 999);

    let dailyRows: Awaited<ReturnType<typeof healthKitService.getDailyHistory>> = [];
    try {
      dailyRows = await withTimeout(
        healthKitService.getDailyHistory(dayStart, dayEnd),
        30_000,
        `getDailyHistory ${dayStart.toDateString()}`,
      );
    } catch (e) {
      console.log(`[Backfill] day ${i + 1}/${daysBack} HK error:`, e);
    }

    totalDays += dailyRows.length;
    const rawMetrics: HealthMetric[] = [];
    for (const row of dailyRows) {
      rawMetrics.push(...dailyRowToMetrics(row));
    }
    const metrics = sanitizeMetrics(rawMetrics);

    if (metrics.length > 0) {
      try {
        const resp = await apiClient.post<{
          inserted_count: number; duplicate_count: number;
        }>('/api/health/metrics/batch', { metrics });
        totalMetricsInserted += resp.inserted_count || 0;
        totalMetricsDuplicate += resp.duplicate_count || 0;
      } catch (e) {
        console.log(`[Backfill] day ${i + 1} POST failed:`, e);
      }
    }

    // Update progress every day so the UI shows movement.
    onProgress?.({
      phase: 'metrics',
      dayIndex: i + 1,
      totalDays: daysBack,
      metricsInserted: totalMetricsInserted,
      workoutsInserted: 0,
      message: `Day ${i + 1}/${daysBack} · +${totalMetricsInserted} metrics`,
    });
  }

  // Workouts — one sweep at the end (cheap relative to per-day metrics)
  let workoutsInserted = 0;
  let workoutsDuplicate = 0;
  try {
    onProgress?.({
      phase: 'workouts',
      dayIndex: daysBack,
      totalDays: daysBack,
      metricsInserted: totalMetricsInserted,
      workoutsInserted: 0,
      message: 'Fetching workouts…',
    });

    const workouts = await withTimeout(
      healthKitService.getWorkoutsForSync(start, now),
      60_000,
      'getWorkoutsForSync',
    );
    console.log(`[Backfill] Found ${workouts.length} workouts in HealthKit history`);

    for (let i = 0; i < workouts.length; i += 50) {
      const slice = workouts.slice(i, i + 50);
      try {
        const resp = await apiClient.post<{
          inserted_count: number; duplicate_count: number;
        }>('/api/health/workouts/batch', { workouts: slice });
        workoutsInserted += resp.inserted_count || 0;
        workoutsDuplicate += resp.duplicate_count || 0;
      } catch (e) {
        console.log('[Backfill] workout chunk POST failed:', e);
      }
    }
    if (workouts.length > 0) {
      await AsyncStorage.setItem(LAST_WORKOUT_SYNC_KEY, now.getTime().toString());
    }
  } catch (e) {
    console.log('[Backfill] workout sweep error:', e);
  }

  onProgress?.({
    phase: 'done',
    dayIndex: daysBack,
    totalDays: daysBack,
    metricsInserted: totalMetricsInserted,
    workoutsInserted,
    message: `Done · ${totalMetricsInserted} metrics · ${workoutsInserted} workouts`,
  });

  return {
    success: true,
    daysProcessed: totalDays,
    metricsInserted: totalMetricsInserted,
    metricsDuplicate: totalMetricsDuplicate,
    workoutsInserted,
    workoutsDuplicate,
    message: `Backfilled ${totalDays} days: ${totalMetricsInserted} new metrics, ${workoutsInserted} new workouts`,
  };
}

/**
 * Manually trigger a sync (for testing or on-demand)
 */
export async function triggerManualSync(): Promise<{
  success: boolean;
  metricCount: number;
  workoutCount: number;
  message: string;
}> {
  console.log('[BackgroundHealth] Manual sync triggered');

  try {
    const metrics = await collectHealthMetrics();
    const success = await syncMetricsToBackend(metrics);
    const workoutResult = await syncWorkoutsToBackend();
    await recordSyncAttempt(success, metrics.length);

    return {
      success: success && workoutResult.success,
      metricCount: metrics.length,
      workoutCount: workoutResult.count,
      message: success
        ? `Synced ${metrics.length} metrics, ${workoutResult.count} workouts`
        : 'Failed to sync metrics',
    };

  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return {
      success: false,
      metricCount: 0,
      workoutCount: 0,
      message,
    };
  }
}

export const BACKGROUND_HEALTH_TASK_NAME = HEALTH_SYNC_TASK;

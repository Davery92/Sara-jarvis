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
import { apiClient } from './api';
import AsyncStorage from '@react-native-async-storage/async-storage';

const HEALTH_SYNC_TASK = 'HEALTH_SYNC_BACKGROUND_TASK';
const BACKGROUND_SYNC_KEY = '@sara_background_health_sync';
const BACKGROUND_SYNC_COUNT_KEY = '@sara_background_sync_count';

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

    // 2. HRV from morning only (5-8 AM) - Watch readings during day are inaccurate
    const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000);
    const hour = now.getHours();
    if (hour >= 5 && hour < 8) {
      const hrvSamples = await healthKitService.getHRVSamples(fourHoursAgo, now);
      if (hrvSamples.length > 0) {
        // Take only the most recent morning reading
        const morningHRV = hrvSamples[0];
        const hrvRecordedAt = new Date(now);
        hrvRecordedAt.setHours(6, 0, 0, 0); // Standardize to 6 AM
        metrics.push({
          metric_type: 'hrv',
          value: morningHRV.value,
          recorded_at: hrvRecordedAt.toISOString(),
          source: 'apple_health',
          metadata: { morning_reading: true },
        });
      }
    }

    // 3. Heart rate samples from last 4 hours
    const hrSamples = await healthKitService.getHeartRateSamples(fourHoursAgo, now);
    for (const sample of hrSamples.slice(0, 10)) {
      metrics.push({
        metric_type: 'heart_rate',
        value: sample.value,
        recorded_at: sample.startDate,
        source: 'apple_health',
      });
    }

    // 4. Sleep from last night (morning only)
    if (hour >= 5 && hour <= 12) {
      const sleepHours = await healthKitService.getLastNightSleepHours();
      if (sleepHours > 0) {
        const sleepRecordedAt = new Date(now);
        sleepRecordedAt.setHours(6, 0, 0, 0);
        metrics.push({
          metric_type: 'sleep_hours',
          value: sleepHours,
          recorded_at: sleepRecordedAt.toISOString(),
          source: 'apple_health',
        });
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
        metadata: { unit: 'kg' },
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
 * Send metrics to backend
 */
async function syncMetricsToBackend(metrics: HealthMetric[]): Promise<boolean> {
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
 * Manually trigger a sync (for testing or on-demand)
 */
export async function triggerManualSync(): Promise<{
  success: boolean;
  metricCount: number;
  message: string;
}> {
  console.log('[BackgroundHealth] Manual sync triggered');

  try {
    const metrics = await collectHealthMetrics();
    const success = await syncMetricsToBackend(metrics);
    await recordSyncAttempt(success, metrics.length);

    return {
      success,
      metricCount: metrics.length,
      message: success
        ? `Synced ${metrics.length} health metrics`
        : 'Failed to sync metrics',
    };

  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return {
      success: false,
      metricCount: 0,
      message,
    };
  }
}

export const BACKGROUND_HEALTH_TASK_NAME = HEALTH_SYNC_TASK;

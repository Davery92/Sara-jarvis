/**
 * Health Sync Service
 * Orchestrates automatic syncing of HealthKit data to Sara's recovery log
 * Handles bidirectional weight sync and debouncing
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { healthKitService } from './healthKit';
import { apiClient } from './api';
import { fitnessService } from './fitness';

const LAST_SYNC_KEY = '@sara_health_last_sync';
const SYNC_DEBOUNCE_MS = 4 * 60 * 60 * 1000; // 4 hours in milliseconds

interface SyncRecoveryPayload {
  hrv?: number;
  resting_hr?: number;
  sleep_hours?: number;
  weight?: number;
  weight_unit?: string;
  weight_timestamp?: string;
  apple_health_weight?: number;
  apple_health_weight_timestamp?: string;
}

interface SyncResult {
  success: boolean;
  message: string;
  recoveryUpdated: boolean;
  weightAction?: 'pushed_to_apple_health' | 'pulled_from_apple_health' | 'no_change';
}

class HealthSyncService {
  /**
   * Check if sync is needed (respects 4-hour debounce)
   */
  async shouldSync(): Promise<boolean> {
    try {
      const lastSyncStr = await AsyncStorage.getItem(LAST_SYNC_KEY);
      if (!lastSyncStr) {
        return true; // Never synced before
      }

      const lastSync = parseInt(lastSyncStr, 10);
      const now = Date.now();
      const timeSinceLastSync = now - lastSync;

      if (timeSinceLastSync >= SYNC_DEBOUNCE_MS) {
        return true;
      }

      const hoursRemaining = ((SYNC_DEBOUNCE_MS - timeSinceLastSync) / (1000 * 60 * 60)).toFixed(1);
      console.log(`[HealthSync] Skipping sync - last sync was ${hoursRemaining}h ago (debounce: 4h)`);
      return false;
    } catch (error) {
      console.log('[HealthSync] Error checking last sync time:', error);
      return true; // Sync on error
    }
  }

  /**
   * Record sync timestamp
   */
  private async recordSyncTime(): Promise<void> {
    try {
      await AsyncStorage.setItem(LAST_SYNC_KEY, Date.now().toString());
    } catch (error) {
      console.log('[HealthSync] Error recording sync time:', error);
    }
  }

  /**
   * Main sync function - called on app open
   * Syncs HealthKit data to recovery log and handles bidirectional weight
   */
  async performSync(): Promise<SyncResult> {
    console.log('[HealthSync] Starting health sync...');

    try {
      // Check debounce
      const shouldRun = await this.shouldSync();
      if (!shouldRun) {
        return {
          success: true,
          message: 'Sync skipped (debounced)',
          recoveryUpdated: false,
        };
      }

      // Initialize HealthKit if needed
      const healthKitAvailable = healthKitService.isHealthKitAvailable();
      if (!healthKitAvailable) {
        const initialized = await healthKitService.initialize();
        if (!initialized) {
          return {
            success: false,
            message: 'HealthKit not available',
            recoveryUpdated: false,
          };
        }
      }

      // Gather health data in parallel
      const [hrv, restingHR, sleepHours, appleHealthWeight] = await Promise.all([
        healthKitService.getLatestHRV(),
        healthKitService.getRestingHeartRate(),
        healthKitService.getLastNightSleepHours(),
        healthKitService.getLatestWeightWithTimestamp(),
      ]);

      console.log('[HealthSync] Collected data:', { hrv, restingHR, sleepHours, appleHealthWeight });

      // Build payload for backend
      const payload: SyncRecoveryPayload = {};

      if (hrv !== null) payload.hrv = hrv;
      if (restingHR !== null) payload.resting_hr = restingHR;
      if (sleepHours > 0) payload.sleep_hours = sleepHours;

      // Handle bidirectional weight sync
      let weightAction: SyncResult['weightAction'] = 'no_change';

      if (appleHealthWeight) {
        payload.apple_health_weight = appleHealthWeight.weight;
        payload.apple_health_weight_timestamp = appleHealthWeight.timestamp.toISOString();
      }

      // Get Sara's latest weight for comparison
      try {
        const saraWeight = await this.getSaraLatestWeight();
        if (saraWeight) {
          payload.weight = saraWeight.weight;
          payload.weight_unit = saraWeight.unit;
          payload.weight_timestamp = saraWeight.timestamp;

          // Compare timestamps for bidirectional sync
          if (appleHealthWeight && saraWeight) {
            const saraTime = new Date(saraWeight.timestamp).getTime();
            const appleTime = appleHealthWeight.timestamp.getTime();

            if (saraTime > appleTime) {
              // Sara is newer - push to Apple Health
              const weightInKg = saraWeight.unit === 'lbs'
                ? saraWeight.weight * 0.453592
                : saraWeight.weight;

              const pushed = await healthKitService.saveWeight(weightInKg, new Date(saraWeight.timestamp));
              if (pushed) {
                weightAction = 'pushed_to_apple_health';
                console.log('[HealthSync] Pushed Sara weight to Apple Health');
              }
            } else if (appleTime > saraTime) {
              weightAction = 'pulled_from_apple_health';
              console.log('[HealthSync] Apple Health weight is newer - will update Sara');
            }
          }
        }
      } catch (error) {
        console.log('[HealthSync] Error getting Sara weight:', error);
      }

      // Send to backend
      const response = await apiClient.post<{ success: boolean; recovery_log?: any }>(
        '/api/health/sync-recovery',
        payload
      );

      // Record sync time
      await this.recordSyncTime();

      console.log('[HealthSync] Sync completed successfully');

      return {
        success: true,
        message: 'Health data synced to recovery log',
        recoveryUpdated: response.success,
        weightAction,
      };

    } catch (error) {
      console.log('[HealthSync] Sync failed:', error);
      return {
        success: false,
        message: error instanceof Error ? error.message : 'Sync failed',
        recoveryUpdated: false,
      };
    }
  }

  /**
   * Get Sara's latest weight from recovery log
   */
  private async getSaraLatestWeight(): Promise<{ weight: number; unit: string; timestamp: string } | null> {
    try {
      // Get recent recovery logs to find latest weight
      const recentLogs = await fitnessService.getRecoveryLogs();

      // Find most recent log with weight
      for (const log of recentLogs) {
        if (log.body_weight) {
          return {
            weight: log.body_weight,
            unit: log.weight_unit || 'lbs',
            timestamp: log.updated_at || log.created_at || log.log_date,
          };
        }
      }

      return null;
    } catch (error) {
      console.log('[HealthSync] Error fetching Sara weight:', error);
      return null;
    }
  }

  /**
   * Force sync (ignores debounce)
   */
  async forceSync(): Promise<SyncResult> {
    // Clear last sync time to bypass debounce
    await AsyncStorage.removeItem(LAST_SYNC_KEY);
    return this.performSync();
  }

  /**
   * Get time until next sync is allowed
   */
  async getTimeUntilNextSync(): Promise<number> {
    try {
      const lastSyncStr = await AsyncStorage.getItem(LAST_SYNC_KEY);
      if (!lastSyncStr) return 0;

      const lastSync = parseInt(lastSyncStr, 10);
      const now = Date.now();
      const timeSinceLastSync = now - lastSync;
      const remaining = SYNC_DEBOUNCE_MS - timeSinceLastSync;

      return remaining > 0 ? remaining : 0;
    } catch {
      return 0;
    }
  }
}

export const healthSyncService = new HealthSyncService();
export default healthSyncService;

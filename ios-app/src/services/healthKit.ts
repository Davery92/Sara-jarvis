import { Platform } from 'react-native';

// Types for health data
export interface HealthData {
  steps?: number;
  distance?: number;
  activeEnergy?: number;
  heartRate?: number;
  heartRateVariability?: number;
  restingHeartRate?: number;
  sleepAnalysis?: SleepData[];
  weight?: number;
  bodyFat?: number;
  workout?: WorkoutData[];
}

export interface SleepData {
  value: string;
  startDate: string;
  endDate: string;
}

export interface WorkoutData {
  activityType: string;
  duration: number;
  calories: number;
  distance?: number;
  startDate: string;
  endDate: string;
}

// HealthKit type identifiers (strings)
const HK_IDENTIFIERS = {
  stepCount: 'HKQuantityTypeIdentifierStepCount',
  distanceWalkingRunning: 'HKQuantityTypeIdentifierDistanceWalkingRunning',
  activeEnergyBurned: 'HKQuantityTypeIdentifierActiveEnergyBurned',
  heartRate: 'HKQuantityTypeIdentifierHeartRate',
  restingHeartRate: 'HKQuantityTypeIdentifierRestingHeartRate',
  heartRateVariability: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
  bodyMass: 'HKQuantityTypeIdentifierBodyMass',
  bodyFatPercentage: 'HKQuantityTypeIdentifierBodyFatPercentage',
  sleepAnalysis: 'HKCategoryTypeIdentifierSleepAnalysis',
};

class HealthKitService {
  private isAvailable: boolean = false;
  private isInitialized: boolean = false;
  private healthkit: any = null;

  /**
   * Initialize HealthKit
   */
  async initialize(): Promise<boolean> {
    if (Platform.OS !== 'ios') {
      console.log('[HealthKit] Not available on this platform');
      return false;
    }

    try {
      console.log('[HealthKit] Loading @kingstinct/react-native-healthkit...');

      const healthkitModule = require('@kingstinct/react-native-healthkit');
      this.healthkit = healthkitModule;

      console.log('[HealthKit] Module loaded, checking availability...');

      // Check if HealthKit is available on this device
      const isAvailable = await healthkitModule.isHealthDataAvailable();
      console.log('[HealthKit] isHealthDataAvailable:', isAvailable);

      if (!isAvailable) {
        console.log('[HealthKit] HealthKit not available on this device');
        this.isAvailable = false;
        return false;
      }

      // Request authorization using string identifiers
      const readPermissions = [
        HK_IDENTIFIERS.stepCount,
        HK_IDENTIFIERS.distanceWalkingRunning,
        HK_IDENTIFIERS.activeEnergyBurned,
        HK_IDENTIFIERS.heartRate,
        HK_IDENTIFIERS.restingHeartRate,
        HK_IDENTIFIERS.heartRateVariability,
        HK_IDENTIFIERS.bodyMass,
        HK_IDENTIFIERS.bodyFatPercentage,
        HK_IDENTIFIERS.sleepAnalysis,
      ];

      const writePermissions = [
        HK_IDENTIFIERS.activeEnergyBurned,
        HK_IDENTIFIERS.distanceWalkingRunning,
        HK_IDENTIFIERS.bodyMass,
      ];

      console.log('[HealthKit] Requesting authorization...');

      await healthkitModule.requestAuthorization({
        toRead: readPermissions,
        toShare: writePermissions,
      });
      console.log('[HealthKit] Authorization requested successfully');

      this.isAvailable = true;
      this.isInitialized = true;
      return true;

    } catch (error: any) {
      console.log('[HealthKit] Initialization failed');
      console.log('[HealthKit] Error:', error?.message || error);
      this.isAvailable = false;
      this.isInitialized = false;
      return false;
    }
  }

  /**
   * Check if HealthKit is available
   */
  isHealthKitAvailable(): boolean {
    return this.isAvailable && this.isInitialized;
  }

  /**
   * Get steps for today
   */
  async getStepsToday(): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;

    try {
      const now = new Date();
      const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      console.log('[HealthKit] Querying steps from', startOfDay.toISOString(), 'to', now.toISOString());

      const result = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.stepCount, {
        limit: 0, // 0 = unlimited
        filter: {
          date: {
            startDate: startOfDay,
            endDate: now,
          }
        }
      });

      console.log('[HealthKit] Steps query returned', result?.length || 0, 'samples');
      if (result?.length > 0) {
        console.log('[HealthKit] First sample:', JSON.stringify(result[0]));
      }

      // Sum all step samples
      const totalSteps = result.reduce((sum: number, sample: any) => sum + (sample.quantity || 0), 0);
      console.log('[HealthKit] Total steps:', totalSteps);
      return Math.round(totalSteps);
    } catch (error) {
      console.log('[HealthKit] Error getting steps:', error);
      return 0;
    }
  }

  /**
   * Get distance walked/run today (in meters)
   */
  async getDistanceToday(): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;

    try {
      const now = new Date();
      const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      const result = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.distanceWalkingRunning, {
        limit: 0,
        filter: {
          date: {
            startDate: startOfDay,
            endDate: now,
          }
        }
      });

      const totalDistance = result.reduce((sum: number, sample: any) => sum + (sample.quantity || 0), 0);
      return totalDistance;
    } catch (error) {
      console.log('[HealthKit] Error getting distance:', error);
      return 0;
    }
  }

  /**
   * Get active energy burned today (kcal)
   */
  async getActiveEnergyToday(): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;

    try {
      const now = new Date();
      const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      const result = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.activeEnergyBurned, {
        limit: 0,
        filter: {
          date: {
            startDate: startOfDay,
            endDate: now,
          }
        }
      });

      const totalEnergy = result.reduce((sum: number, sample: any) => sum + (sample.quantity || 0), 0);
      return Math.round(totalEnergy);
    } catch (error) {
      console.log('[HealthKit] Error getting active energy:', error);
      return 0;
    }
  }

  /**
   * Get latest heart rate
   */
  async getLatestHeartRate(): Promise<number | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.heartRate);
      return result?.quantity ? Math.round(result.quantity) : null;
    } catch (error) {
      console.log('[HealthKit] Error getting heart rate:', error);
      return null;
    }
  }

  /**
   * Get heart rate samples
   */
  async getHeartRateSamples(startDate: Date, endDate: Date): Promise<any[]> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const result = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.heartRate, {
        limit: 0,
        filter: {
          date: {
            startDate: startDate,
            endDate: endDate,
          }
        }
      });

      return result.map((sample: any) => ({
        value: sample.quantity,
        startDate: sample.startDate,
        endDate: sample.endDate,
      }));
    } catch (error) {
      console.log('[HealthKit] Error getting heart rate samples:', error);
      return [];
    }
  }

  /**
   * Get resting heart rate
   */
  async getRestingHeartRate(): Promise<number | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.restingHeartRate);
      return result?.quantity ? Math.round(result.quantity) : null;
    } catch (error) {
      console.log('[HealthKit] Error getting resting heart rate:', error);
      return null;
    }
  }

  /**
   * Get latest HRV (Heart Rate Variability) in milliseconds
   * Queries the last 24 hours to get a recent reading
   */
  async getLatestHRV(): Promise<number | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      // Query HRV samples from the last 24 hours to ensure we get a recent reading
      const now = new Date();
      const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);

      const samples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.heartRateVariability, {
        from: yesterday,
        to: now,
        limit: 10,
        ascending: false, // Most recent first
      });

      if (samples && samples.length > 0) {
        const latest = samples[0];
        console.log('[HealthKit] HRV sample:', JSON.stringify({
          quantity: latest.quantity,
          unit: latest.unit,
          startDate: latest.startDate,
          endDate: latest.endDate,
        }));
        // HRV SDNN is in milliseconds, values typically 20-200ms
        // Some HealthKit implementations may return in seconds (0.019 = 19ms)
        let hrv = latest.quantity;
        // If value is very small (< 1), it's likely in seconds - convert to ms
        if (hrv < 1) {
          hrv = hrv * 1000;
        }
        return Math.round(hrv);
      }

      console.log('[HealthKit] No HRV samples found in last 24 hours');
      return null;
    } catch (error) {
      console.log('[HealthKit] Error getting HRV:', error);
      return null;
    }
  }

  /**
   * Get HRV samples over a time range for trend analysis
   * Returns samples sorted by start date (most recent first)
   */
  async getHRVSamples(startDate: Date, endDate: Date): Promise<Array<{value: number, startDate: string, endDate: string}>> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const samples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.heartRateVariability, {
        from: startDate,
        to: endDate,
        limit: 0,
        ascending: false, // Most recent first
      });

      return samples.map((sample: any) => {
        // HRV SDNN values - convert from seconds to ms if needed
        let hrv = sample.quantity;
        if (hrv < 1) {
          hrv = hrv * 1000;
        }
        return {
          value: Math.round(hrv),
          startDate: sample.startDate,
          endDate: sample.endDate,
        };
      });
    } catch (error) {
      console.log('[HealthKit] Error getting HRV samples:', error);
      return [];
    }
  }

  /**
   * Get sleep samples
   */
  async getSleepSamples(startDate: Date, endDate: Date): Promise<SleepData[]> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const result = await this.healthkit.queryCategorySamples(HK_IDENTIFIERS.sleepAnalysis, {
        limit: 0,
        filter: {
          date: {
            startDate: startDate,
            endDate: endDate,
          }
        }
      });

      return result.map((sample: any) => ({
        value: sample.value,
        startDate: sample.startDate,
        endDate: sample.endDate,
      }));
    } catch (error) {
      console.log('[HealthKit] Error getting sleep samples:', error);
      return [];
    }
  }

  /**
   * Get latest weight
   */
  async getLatestWeight(): Promise<number | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.bodyMass);
      return result?.quantity || null;
    } catch (error) {
      console.log('[HealthKit] Error getting weight:', error);
      return null;
    }
  }

  /**
   * Get latest weight with timestamp for bidirectional sync
   * Returns weight in kg and the timestamp
   */
  async getLatestWeightWithTimestamp(): Promise<{ weight: number; timestamp: Date } | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.bodyMass);
      if (result?.quantity && result?.startDate) {
        return {
          weight: result.quantity, // kg
          timestamp: new Date(result.startDate),
        };
      }
      return null;
    } catch (error) {
      console.log('[HealthKit] Error getting weight with timestamp:', error);
      return null;
    }
  }

  /**
   * Save weight to Apple Health
   * @param weightKg Weight in kilograms
   * @param date Date of the measurement
   */
  async saveWeight(weightKg: number, date: Date = new Date()): Promise<boolean> {
    if (!this.isAvailable || !this.healthkit) return false;

    try {
      await this.healthkit.saveQuantitySample(
        HK_IDENTIFIERS.bodyMass,
        'kg',
        weightKg,
        date,
        date
      );
      console.log('[HealthKit] Weight saved successfully:', weightKg, 'kg');
      return true;
    } catch (error) {
      console.log('[HealthKit] Error saving weight:', error);
      return false;
    }
  }

  /**
   * Get workout samples
   */
  async getWorkoutSamples(startDate: Date, endDate: Date): Promise<WorkoutData[]> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const result = await this.healthkit.queryWorkoutSamples({
        limit: 0,
        filter: {
          date: {
            startDate: startDate,
            endDate: endDate,
          }
        }
      });

      return result.map((workout: any) => ({
        activityType: workout.workoutActivityType || 'Unknown',
        duration: workout.duration || 0,
        calories: workout.totalEnergyBurned || 0,
        distance: workout.totalDistance,
        startDate: workout.startDate,
        endDate: workout.endDate,
      }));
    } catch (error) {
      console.log('[HealthKit] Error getting workouts:', error);
      return [];
    }
  }

  /**
   * Calculate total sleep hours from sleep samples
   * Filters for actual sleep stages, merges overlapping intervals, and calculates duration
   * @param samples Array of sleep samples from getSleepSamples()
   */
  calculateSleepHours(samples: SleepData[]): number {
    if (!samples || samples.length === 0) return 0;

    // Sleep analysis values that count as actual sleep (not just "in bed")
    // Values: 0 = inBed, 1 = asleepUnspecified, 2 = awake, 3 = asleepCore, 4 = asleepDeep, 5 = asleepREM
    const sleepValues = ['1', '3', '4', '5', 'asleepUnspecified', 'asleepCore', 'asleepDeep', 'asleepREM'];

    // Collect all sleep intervals (filtering out inBed and awake)
    const intervals: { start: number; end: number }[] = [];

    for (const sample of samples) {
      const value = String(sample.value);
      if (sleepValues.includes(value) || value.toLowerCase().includes('asleep')) {
        const start = new Date(sample.startDate).getTime();
        const end = new Date(sample.endDate).getTime();
        if (end > start) {
          intervals.push({ start, end });
        }
      }
    }

    if (intervals.length === 0) return 0;

    // Sort intervals by start time
    intervals.sort((a, b) => a.start - b.start);

    // Merge overlapping intervals to avoid double-counting from multiple sources
    const merged: { start: number; end: number }[] = [];
    let current = intervals[0];

    for (let i = 1; i < intervals.length; i++) {
      if (intervals[i].start <= current.end) {
        // Overlapping - extend current interval
        current.end = Math.max(current.end, intervals[i].end);
      } else {
        // No overlap - save current and start new
        merged.push(current);
        current = intervals[i];
      }
    }
    merged.push(current);

    // Calculate total duration from merged intervals
    const totalMs = merged.reduce((sum, interval) => sum + (interval.end - interval.start), 0);

    // Convert to hours with 2 decimal places for accuracy (e.g., 7.07 for 7h 4m)
    const hours = totalMs / (1000 * 60 * 60);
    return Math.round(hours * 100) / 100;
  }

  /**
   * Get last night's sleep hours
   * Queries sleep data from 6pm yesterday to 12pm today
   */
  async getLastNightSleepHours(): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;

    try {
      const now = new Date();
      // Start from 6pm yesterday
      const startDate = new Date(now);
      startDate.setDate(startDate.getDate() - 1);
      startDate.setHours(18, 0, 0, 0);

      // End at 12pm today
      const endDate = new Date(now);
      endDate.setHours(12, 0, 0, 0);

      const samples = await this.getSleepSamples(startDate, endDate);
      return this.calculateSleepHours(samples);
    } catch (error) {
      console.log('[HealthKit] Error getting last night sleep:', error);
      return 0;
    }
  }

  /**
   * Get comprehensive health data for today
   */
  async getTodayHealthData(): Promise<HealthData> {
    if (!this.isAvailable) {
      return {};
    }

    const [steps, distance, activeEnergy, heartRate, restingHeartRate, hrv, weight] =
      await Promise.all([
        this.getStepsToday(),
        this.getDistanceToday(),
        this.getActiveEnergyToday(),
        this.getLatestHeartRate(),
        this.getRestingHeartRate(),
        this.getLatestHRV(),
        this.getLatestWeight(),
      ]);

    return {
      steps,
      distance,
      activeEnergy,
      heartRate: heartRate || undefined,
      restingHeartRate: restingHeartRate || undefined,
      heartRateVariability: hrv || undefined,
      weight: weight || undefined,
    };
  }

  /**
   * Get health data for a date range
   */
  async getHealthDataForRange(startDate: Date, endDate: Date): Promise<HealthData> {
    if (!this.isAvailable) {
      return {};
    }

    const [sleepAnalysis, workout] = await Promise.all([
      this.getSleepSamples(startDate, endDate),
      this.getWorkoutSamples(startDate, endDate),
    ]);

    return {
      sleepAnalysis,
      workout,
    };
  }

  /**
   * Get daily step stats for the last N days
   */
  async getDailyStats(days: number = 7): Promise<any[]> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const stats: any[] = [];
      const today = new Date();

      for (let i = 0; i < days; i++) {
        const date = new Date(today);
        date.setDate(date.getDate() - i);
        const startOfDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const endOfDay = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59);

        const result = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.stepCount, {
          limit: 0,
          filter: {
            date: {
              startDate: startOfDay,
              endDate: endOfDay,
            }
          }
        });

        const totalSteps = result.reduce((sum: number, sample: any) => sum + (sample.quantity || 0), 0);

        stats.push({
          date: startOfDay.toISOString().split('T')[0],
          steps: Math.round(totalSteps),
          distance: 0,
        });
      }

      return stats.reverse();
    } catch (error) {
      console.log('[HealthKit] Error getting daily stats:', error);
      return [];
    }
  }

  /**
   * Save a workout to HealthKit
   */
  async saveWorkout(
    activityType: string,
    startDate: Date,
    endDate: Date,
    calories: number,
    distance?: number
  ): Promise<boolean> {
    if (!this.isAvailable || !this.healthkit) return false;

    try {
      // saveWorkoutSample signature: (workoutActivityType, quantities[], startDate, endDate, totals?, metadata?)
      const totals: any = {
        activeEnergyBurned: { unit: 'kcal', quantity: calories },
      };
      if (distance !== undefined) {
        totals.distance = { unit: 'm', quantity: distance };
      }

      await this.healthkit.saveWorkoutSample(
        activityType,
        [], // quantities array - empty for simple workouts
        startDate,
        endDate,
        totals
      );
      console.log('[HealthKit] Workout saved successfully');
      return true;
    } catch (error) {
      console.log('[HealthKit] Error saving workout:', error);
      return false;
    }
  }
}

// Export singleton instance
export const healthKitService = new HealthKitService();
export default healthKitService;

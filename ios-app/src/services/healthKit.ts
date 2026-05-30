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
  // Existing
  stepCount: 'HKQuantityTypeIdentifierStepCount',
  distanceWalkingRunning: 'HKQuantityTypeIdentifierDistanceWalkingRunning',
  activeEnergyBurned: 'HKQuantityTypeIdentifierActiveEnergyBurned',
  heartRate: 'HKQuantityTypeIdentifierHeartRate',
  restingHeartRate: 'HKQuantityTypeIdentifierRestingHeartRate',
  heartRateVariability: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
  bodyMass: 'HKQuantityTypeIdentifierBodyMass',
  bodyFatPercentage: 'HKQuantityTypeIdentifierBodyFatPercentage',
  sleepAnalysis: 'HKCategoryTypeIdentifierSleepAnalysis',
  // Vitals (Phase 1 additions)
  oxygenSaturation: 'HKQuantityTypeIdentifierOxygenSaturation',
  respiratoryRate: 'HKQuantityTypeIdentifierRespiratoryRate',
  bodyTemperature: 'HKQuantityTypeIdentifierBodyTemperature',
  // Cardiovascular
  vo2Max: 'HKQuantityTypeIdentifierVO2Max',
  walkingHeartRateAverage: 'HKQuantityTypeIdentifierWalkingHeartRateAverage',
  heartRateRecoveryOneMinute: 'HKQuantityTypeIdentifierHeartRateRecoveryOneMinute',
  // Activity
  appleStandTime: 'HKQuantityTypeIdentifierAppleStandTime',
  appleExerciseTime: 'HKQuantityTypeIdentifierAppleExerciseTime',
  flightsClimbed: 'HKQuantityTypeIdentifierFlightsClimbed',
  mindfulSession: 'HKCategoryTypeIdentifierMindfulSession',
  // Workouts — needed in read permissions for queryWorkoutSamples to return anything
  workoutType: 'HKWorkoutTypeIdentifier',
};

// Sleep stage values per Apple HealthKit spec
// 0=inBed, 1=asleepUnspecified, 2=awake, 3=asleepCore, 4=asleepDeep, 5=asleepREM
const SLEEP_STAGE_MAP: Record<string, string> = {
  '0': 'in_bed',
  '1': 'asleep_unspecified',
  '2': 'awake',
  '3': 'asleep_core',
  '4': 'asleep_deep',
  '5': 'asleep_rem',
  inBed: 'in_bed',
  asleepUnspecified: 'asleep_unspecified',
  awake: 'awake',
  asleepCore: 'asleep_core',
  asleepDeep: 'asleep_deep',
  asleepREM: 'asleep_rem',
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
        // Phase 1 additions
        HK_IDENTIFIERS.oxygenSaturation,
        HK_IDENTIFIERS.respiratoryRate,
        HK_IDENTIFIERS.bodyTemperature,
        HK_IDENTIFIERS.vo2Max,
        HK_IDENTIFIERS.walkingHeartRateAverage,
        HK_IDENTIFIERS.heartRateRecoveryOneMinute,
        HK_IDENTIFIERS.appleStandTime,
        HK_IDENTIFIERS.appleExerciseTime,
        HK_IDENTIFIERS.flightsClimbed,
        HK_IDENTIFIERS.mindfulSession,
        HK_IDENTIFIERS.workoutType,
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

      // Use filter.date shape — the from/to keys are silently ignored by the
      // @kingstinct lib and would return latest-globally regardless of window.
      const samples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.heartRateVariability, {
        limit: 10,
        ascending: false,
        filter: { date: { startDate: yesterday, endDate: now } },
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
        limit: 0,
        ascending: false, // Most recent first
        filter: { date: { startDate, endDate } },
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
   * Get latest weight (in pounds)
   */
  async getLatestWeight(): Promise<number | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.bodyMass, 'lb');
      return result?.quantity || null;
    } catch (error) {
      console.log('[HealthKit] Error getting weight:', error);
      return null;
    }
  }

  /**
   * Get latest weight with timestamp for bidirectional sync
   * Returns weight in lbs and the timestamp
   */
  async getLatestWeightWithTimestamp(): Promise<{ weight: number; timestamp: Date } | null> {
    if (!this.isAvailable || !this.healthkit) return null;

    try {
      const result = await this.healthkit.getMostRecentQuantitySample(HK_IDENTIFIERS.bodyMass, 'lb');
      if (result?.quantity && result?.startDate) {
        return {
          weight: result.quantity, // lbs
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
   * @param weightLb Weight in pounds
   * @param date Date of the measurement
   */
  async saveWeight(weightLb: number, date: Date = new Date()): Promise<boolean> {
    if (!this.isAvailable || !this.healthkit) return false;

    try {
      await this.healthkit.saveQuantitySample(
        HK_IDENTIFIERS.bodyMass,
        'lb',
        weightLb,
        date,
        date
      );
      console.log('[HealthKit] Weight saved successfully:', weightLb, 'lb');
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

  // =====================================================
  // Phase 1: Richer health reads
  // =====================================================

  /** Most-recent quantity sample helper that returns null cleanly. */
  private async _latestQuantity(identifier: string, unit?: string): Promise<{ value: number; startDate: string } | null> {
    if (!this.isAvailable || !this.healthkit) return null;
    try {
      const result = unit
        ? await this.healthkit.getMostRecentQuantitySample(identifier, unit)
        : await this.healthkit.getMostRecentQuantitySample(identifier);
      if (result?.quantity == null) return null;
      return { value: result.quantity, startDate: result.startDate };
    } catch (error) {
      console.log(`[HealthKit] Error getting ${identifier}:`, error);
      return null;
    }
  }

  /** Sum quantity samples between two dates. */
  private async _sumQuantity(identifier: string, start: Date, end: Date): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;
    try {
      const result = await this.healthkit.queryQuantitySamples(identifier, {
        limit: 0,
        filter: { date: { startDate: start, endDate: end } },
      });
      return result.reduce((sum: number, s: any) => sum + (s.quantity || 0), 0);
    } catch (error) {
      console.log(`[HealthKit] Error summing ${identifier}:`, error);
      return 0;
    }
  }

  /** Latest blood-oxygen percentage (0-1 from HK; we return percent 0-100). */
  async getLatestSpO2(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.oxygenSaturation);
    if (!r) return null;
    // HK returns fraction (0-1); convert to percent
    const percent = r.value <= 1 ? r.value * 100 : r.value;
    return { value: Math.round(percent * 10) / 10, recordedAt: r.startDate };
  }

  /** Latest respiratory rate in breaths per minute. */
  async getLatestRespiratoryRate(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.respiratoryRate);
    if (!r) return null;
    return { value: Math.round(r.value * 10) / 10, recordedAt: r.startDate };
  }

  /** Latest body temperature in Fahrenheit. */
  async getLatestBodyTemp(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.bodyTemperature, 'degF');
    if (!r) return null;
    return { value: Math.round(r.value * 10) / 10, recordedAt: r.startDate };
  }

  /** Latest VO2 max in mL/(kg·min). */
  async getLatestVO2Max(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.vo2Max);
    if (!r) return null;
    return { value: Math.round(r.value * 10) / 10, recordedAt: r.startDate };
  }

  /** Latest walking heart rate average in bpm. */
  async getWalkingHRAvg(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.walkingHeartRateAverage);
    if (!r) return null;
    return { value: Math.round(r.value), recordedAt: r.startDate };
  }

  /** Latest 1-minute heart-rate recovery in bpm (post-workout drop). */
  async getLatestHRRecovery(): Promise<{ value: number; recordedAt: string } | null> {
    const r = await this._latestQuantity(HK_IDENTIFIERS.heartRateRecoveryOneMinute);
    if (!r) return null;
    return { value: Math.round(r.value), recordedAt: r.startDate };
  }

  /** Stand minutes today (from Apple Stand Time). */
  async getStandMinutesToday(): Promise<number> {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round(await this._sumQuantity(HK_IDENTIFIERS.appleStandTime, startOfDay, now));
  }

  /** Exercise (cardio) minutes today. */
  async getExerciseMinutesToday(): Promise<number> {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round(await this._sumQuantity(HK_IDENTIFIERS.appleExerciseTime, startOfDay, now));
  }

  /** Flights climbed today. */
  async getFlightsClimbedToday(): Promise<number> {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round(await this._sumQuantity(HK_IDENTIFIERS.flightsClimbed, startOfDay, now));
  }

  /** Mindful minutes today (from category samples; sum durations). */
  async getMindfulMinutesToday(): Promise<number> {
    if (!this.isAvailable || !this.healthkit) return 0;
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    try {
      const samples = await this.healthkit.queryCategorySamples(HK_IDENTIFIERS.mindfulSession, {
        limit: 0,
        filter: { date: { startDate: startOfDay, endDate: now } },
      });
      const totalMs = samples.reduce((sum: number, s: any) => {
        const start = new Date(s.startDate).getTime();
        const end = new Date(s.endDate).getTime();
        return sum + Math.max(0, end - start);
      }, 0);
      return Math.round(totalMs / 60000);
    } catch (error) {
      console.log('[HealthKit] Error getting mindful sessions:', error);
      return 0;
    }
  }

  /**
   * Sleep stage breakdown for last night (6pm yesterday → noon today).
   *
   * Returns per-stage minutes and bedtime/wake-time. Intervals are merged
   * within each stage to dedupe across sources (Watch + iPhone + 3rd party).
   */
  async getSleepStagesBreakdown(): Promise<{
    stages: Record<string, number>; // stage -> minutes
    bedtime: string | null;
    wakeTime: string | null;
    totalAsleepHours: number;
    totalInBedHours: number;
  }> {
    const now = new Date();
    const startDate = new Date(now);
    startDate.setDate(startDate.getDate() - 1);
    startDate.setHours(18, 0, 0, 0);
    const endDate = new Date(now);
    endDate.setHours(12, 0, 0, 0);

    const samples = await this.getSleepSamples(startDate, endDate);
    const stages: Record<string, number> = {
      asleep_deep: 0, asleep_rem: 0, asleep_core: 0,
      asleep_unspecified: 0, awake: 0, in_bed: 0,
    };

    if (!samples.length) {
      return { stages, bedtime: null, wakeTime: null, totalAsleepHours: 0, totalInBedHours: 0 };
    }

    // Group by stage, then merge overlapping intervals per stage
    const byStage: Record<string, { start: number; end: number }[]> = {};
    let earliestAsleep: number | null = null;
    let latestAsleep: number | null = null;

    for (const sample of samples) {
      const stageKey = SLEEP_STAGE_MAP[String(sample.value)] || String(sample.value).toLowerCase();
      const start = new Date(sample.startDate).getTime();
      const end = new Date(sample.endDate).getTime();
      if (end <= start) continue;
      (byStage[stageKey] ||= []).push({ start, end });

      if (stageKey.startsWith('asleep')) {
        earliestAsleep = earliestAsleep === null ? start : Math.min(earliestAsleep, start);
        latestAsleep = latestAsleep === null ? end : Math.max(latestAsleep, end);
      }
    }

    for (const [stageKey, intervals] of Object.entries(byStage)) {
      intervals.sort((a, b) => a.start - b.start);
      let total = 0;
      let cur = intervals[0];
      for (let i = 1; i < intervals.length; i++) {
        if (intervals[i].start <= cur.end) cur.end = Math.max(cur.end, intervals[i].end);
        else { total += cur.end - cur.start; cur = intervals[i]; }
      }
      total += cur.end - cur.start;
      stages[stageKey] = Math.round(total / 60000);
    }

    const asleepMinutes = stages.asleep_deep + stages.asleep_rem + stages.asleep_core + stages.asleep_unspecified;
    const inBedMinutes = stages.in_bed; // inBed is reported separately, not summed with asleep

    return {
      stages,
      bedtime: earliestAsleep ? new Date(earliestAsleep).toISOString() : null,
      wakeTime: latestAsleep ? new Date(latestAsleep).toISOString() : null,
      totalAsleepHours: Math.round((asleepMinutes / 60) * 100) / 100,
      totalInBedHours: Math.round((inBedMinutes / 60) * 100) / 100,
    };
  }

  /**
   * Get HR samples within a time window. Returns all samples (no cap).
   * Caller decides whether to decimate.
   */
  async getHeartRateSamplesAll(startDate: Date, endDate: Date): Promise<Array<{ value: number; startDate: string; endDate: string }>> {
    return this.getHeartRateSamples(startDate, endDate);
  }

  /**
   * Get workouts with full metadata for backend ingestion (Phase 2).
   *
   * For each workout, fetches HR samples within its time range and computes
   * avg/max/min HR. HR zone bucketing is left to the backend (which knows
   * the user's max HR from VO2max / age).
   */
  async getWorkoutsForSync(startDate: Date, endDate: Date): Promise<Array<{
    external_id: string;
    activity_type: string;
    started_at: string;
    ended_at: string;
    duration_seconds: number;
    total_energy_kcal: number | null;
    total_distance_m: number | null;
    avg_heart_rate: number | null;
    max_heart_rate: number | null;
    min_heart_rate: number | null;
    workout_metadata: Record<string, any>;
  }>> {
    if (!this.isAvailable || !this.healthkit) return [];

    try {
      const result = await this.healthkit.queryWorkoutSamples({
        limit: 0,
        filter: { date: { startDate, endDate } },
      });

      const out = [];
      for (const w of result) {
        const wStart = new Date(w.startDate);
        const wEnd = new Date(w.endDate);
        const durationS = Math.round((wEnd.getTime() - wStart.getTime()) / 1000);

        // HR stats within workout window
        let avgHR: number | null = null;
        let maxHR: number | null = null;
        let minHR: number | null = null;
        try {
          const hrSamples = await this.getHeartRateSamples(wStart, wEnd);
          if (hrSamples.length > 0) {
            const values = hrSamples.map((s: any) => s.value).filter((v: any) => v > 0);
            if (values.length > 0) {
              avgHR = Math.round(values.reduce((a: number, b: number) => a + b, 0) / values.length);
              maxHR = Math.round(Math.max(...values));
              minHR = Math.round(Math.min(...values));
            }
          }
        } catch (e) {
          // HR fetch is best-effort; workout still gets logged
        }

        out.push({
          external_id: w.uuid || w.id || `${w.startDate}-${w.workoutActivityType}`,
          activity_type: String(w.workoutActivityType || 'unknown'),
          started_at: wStart.toISOString(),
          ended_at: wEnd.toISOString(),
          duration_seconds: durationS,
          total_energy_kcal: w.totalEnergyBurned ?? null,
          total_distance_m: w.totalDistance ?? null,
          avg_heart_rate: avgHR,
          max_heart_rate: maxHR,
          min_heart_rate: minHR,
          workout_metadata: {
            indoor: w.metadata?.HKIndoorWorkout ?? null,
            device: w.device?.name ?? null,
            source_name: w.sourceRevision?.source?.name ?? null,
          },
        });
      }
      return out;
    } catch (error) {
      console.log('[HealthKit] Error getting workouts for sync:', error);
      return [];
    }
  }

  /**
   * Get HRV samples within a window — for sleep-quality analysis and backfill.
   *
   * Uses the {filter:{date:{startDate,endDate}}} query shape, NOT {from,to},
   * because the @kingstinct HealthKit lib silently ignores the from/to keys
   * and returns the latest samples globally. That bug invisibly worked for
   * "now-ish" queries but returned wrong data for historical backfill.
   */
  async getHRVInWindow(startDate: Date, endDate: Date): Promise<Array<{ value: number; startDate: string }>> {
    if (!this.isAvailable || !this.healthkit) return [];
    try {
      const samples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.heartRateVariability, {
        limit: 0,
        ascending: true,
        filter: { date: { startDate, endDate } },
      });
      return samples
        .filter((s: any) => s.startDate)
        .filter((s: any) => {
          // Reject samples whose actual timestamp falls outside the window —
          // belt-and-suspenders in case the lib ignores the filter too.
          const t = new Date(s.startDate).getTime();
          return t >= startDate.getTime() && t <= endDate.getTime();
        })
        .map((s: any) => {
          let v = s.quantity;
          if (v < 1) v = v * 1000;
          return { value: Math.round(v), startDate: s.startDate };
        })
        .filter((s: { value: number }) => Number.isFinite(s.value) && s.value > 0);
    } catch (error) {
      console.log('[HealthKit] Error getting HRV in window:', error);
      return [];
    }
  }

  /**
   * Daily-aggregated history for a date range — used by the historical backfill.
   *
   * Returns one row per day with the metrics that make sense as daily aggregates:
   *   - steps, active_energy, stand_min, exercise_min, flights, mindful_min
   *     (sums per day)
   *   - resting_hr, hrv (averages per day; HRV may have multiple samples)
   *   - weight (latest reading per day, if any)
   *   - sleep stage breakdown (one entry per night; computed for the
   *     6 PM previous → noon current window)
   *
   * Returns null entries for days with no data — caller filters.
   */
  async getDailyHistory(startDate: Date, endDate: Date): Promise<Array<{
    date: string; // YYYY-MM-DD in local time
    steps: number;
    active_energy: number;
    stand_minutes: number;
    exercise_minutes: number;
    flights_climbed: number;
    mindful_minutes: number;
    resting_hr: number | null;
    hrv_avg: number | null;
    hrv_samples: Array<{ value: number; startDate: string }>;
    weight_lb: number | null;
    sleep: {
      total_asleep_hours: number;
      stages: Record<string, number>;
      bedtime: string | null;
      wake_time: string | null;
    } | null;
  }>> {
    if (!this.isAvailable || !this.healthkit) return [];

    const out: any[] = [];
    const cur = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
    const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());

    while (cur <= end) {
      const dayStart = new Date(cur);
      const dayEnd = new Date(cur);
      dayEnd.setHours(23, 59, 59, 999);

      const dateStr = `${dayStart.getFullYear()}-${String(dayStart.getMonth() + 1).padStart(2, '0')}-${String(dayStart.getDate()).padStart(2, '0')}`;

      try {
        const [steps, activeEnergy, standMin, exerciseMin, flights, mindfulMin] = await Promise.all([
          this._sumQuantity(HK_IDENTIFIERS.stepCount, dayStart, dayEnd),
          this._sumQuantity(HK_IDENTIFIERS.activeEnergyBurned, dayStart, dayEnd),
          this._sumQuantity(HK_IDENTIFIERS.appleStandTime, dayStart, dayEnd),
          this._sumQuantity(HK_IDENTIFIERS.appleExerciseTime, dayStart, dayEnd),
          this._sumQuantity(HK_IDENTIFIERS.flightsClimbed, dayStart, dayEnd),
          (async () => {
            try {
              const samples = await this.healthkit.queryCategorySamples(HK_IDENTIFIERS.mindfulSession, {
                limit: 0,
                filter: { date: { startDate: dayStart, endDate: dayEnd } },
              });
              const totalMs = samples.reduce((sum: number, s: any) => {
                const a = new Date(s.startDate).getTime();
                const b = new Date(s.endDate).getTime();
                return sum + Math.max(0, b - a);
              }, 0);
              return Math.round(totalMs / 60000);
            } catch { return 0; }
          })(),
        ]);

        // Resting HR — take latest sample for the day if any
        let restingHR: number | null = null;
        try {
          const rhrSamples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.restingHeartRate, {
            limit: 0,
            filter: { date: { startDate: dayStart, endDate: dayEnd } },
          });
          if (rhrSamples?.length) {
            restingHR = Math.round(rhrSamples[rhrSamples.length - 1].quantity);
          }
        } catch { /* ignore */ }

        // HRV samples for the day (raw + avg)
        const hrvSamples = await this.getHRVInWindow(dayStart, dayEnd);
        const hrvAvg = hrvSamples.length
          ? Math.round(hrvSamples.reduce((s, x) => s + x.value, 0) / hrvSamples.length)
          : null;

        // Weight — latest sample
        let weightLb: number | null = null;
        try {
          const wSamples = await this.healthkit.queryQuantitySamples(HK_IDENTIFIERS.bodyMass, {
            limit: 0,
            unit: 'lb',
            filter: { date: { startDate: dayStart, endDate: dayEnd } },
          });
          if (wSamples?.length) {
            weightLb = wSamples[wSamples.length - 1].quantity;
          }
        } catch { /* ignore */ }

        // Sleep for the night ENDING on this day (6pm prior → noon current)
        const sleepStart = new Date(cur); sleepStart.setDate(sleepStart.getDate() - 1); sleepStart.setHours(18, 0, 0, 0);
        const sleepEnd = new Date(cur); sleepEnd.setHours(12, 0, 0, 0);
        let sleep: any = null;
        try {
          const samples = await this.getSleepSamples(sleepStart, sleepEnd);
          if (samples.length) {
            const stages: Record<string, number> = {
              asleep_deep: 0, asleep_rem: 0, asleep_core: 0,
              asleep_unspecified: 0, awake: 0, in_bed: 0,
            };
            const byStage: Record<string, { start: number; end: number }[]> = {};
            let earliest: number | null = null;
            let latest: number | null = null;

            for (const s of samples) {
              const stage = SLEEP_STAGE_MAP[String(s.value)] || String(s.value).toLowerCase();
              const a = new Date(s.startDate).getTime();
              const b = new Date(s.endDate).getTime();
              if (b <= a) continue;
              (byStage[stage] ||= []).push({ start: a, end: b });
              if (stage.startsWith('asleep')) {
                earliest = earliest === null ? a : Math.min(earliest, a);
                latest = latest === null ? b : Math.max(latest, b);
              }
            }
            for (const [k, intervals] of Object.entries(byStage)) {
              intervals.sort((x, y) => x.start - y.start);
              let total = 0;
              let curIv = intervals[0];
              for (let i = 1; i < intervals.length; i++) {
                if (intervals[i].start <= curIv.end) curIv.end = Math.max(curIv.end, intervals[i].end);
                else { total += curIv.end - curIv.start; curIv = intervals[i]; }
              }
              total += curIv.end - curIv.start;
              stages[k] = Math.round(total / 60000);
            }
            const asleepMin = stages.asleep_deep + stages.asleep_rem + stages.asleep_core + stages.asleep_unspecified;
            sleep = {
              total_asleep_hours: Math.round((asleepMin / 60) * 100) / 100,
              stages,
              bedtime: earliest ? new Date(earliest).toISOString() : null,
              wake_time: latest ? new Date(latest).toISOString() : null,
            };
          }
        } catch { /* ignore */ }

        out.push({
          date: dateStr,
          steps: Math.round(steps),
          active_energy: Math.round(activeEnergy),
          stand_minutes: Math.round(standMin),
          exercise_minutes: Math.round(exerciseMin),
          flights_climbed: Math.round(flights),
          mindful_minutes: mindfulMin,
          resting_hr: restingHR,
          hrv_avg: hrvAvg,
          hrv_samples: hrvSamples,
          weight_lb: weightLb,
          sleep,
        });
      } catch (e) {
        console.log(`[HealthKit] Daily history error for ${dateStr}:`, e);
      }

      cur.setDate(cur.getDate() + 1);
    }
    return out;
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

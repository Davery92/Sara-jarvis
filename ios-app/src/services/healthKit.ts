import { Platform } from 'react-native';

// NOTE: This is a mock HealthKit service for Expo compatibility
// Real HealthKit requires a native build (not Expo Go)
// To use real HealthKit, build a standalone iOS app with expo-health-connect

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

class HealthKitService {
  private isAvailable: boolean = false;
  private isInitialized: boolean = false;

  /**
   * Initialize HealthKit (mock for Expo)
   */
  async initialize(): Promise<boolean> {
    if (Platform.OS !== 'ios') {
      console.log('[HealthKit] Not available on this platform');
      return false;
    }

    console.log('[HealthKit] Mock service initialized (Expo stub)');
    console.log('[HealthKit] Build a standalone app for real HealthKit data');

    this.isAvailable = true;
    this.isInitialized = true;
    return true;
  }

  /**
   * Check if HealthKit is available
   */
  isHealthKitAvailable(): boolean {
    return this.isAvailable && this.isInitialized;
  }

  /**
   * Get mock steps for today
   */
  async getStepsToday(): Promise<number> {
    if (!this.isAvailable) return 0;
    return Promise.resolve(Math.floor(Math.random() * 3000) + 7000); // 7000-10000
  }

  /**
   * Get mock distance (in meters)
   */
  async getDistanceToday(): Promise<number> {
    if (!this.isAvailable) return 0;
    return Promise.resolve(Math.floor(Math.random() * 2000) + 5000); // 5-7 km
  }

  /**
   * Get mock active energy (kcal)
   */
  async getActiveEnergyToday(): Promise<number> {
    if (!this.isAvailable) return 0;
    return Promise.resolve(Math.floor(Math.random() * 200) + 300); // 300-500 kcal
  }

  /**
   * Get mock heart rate
   */
  async getLatestHeartRate(): Promise<number | null> {
    if (!this.isAvailable) return null;
    return Promise.resolve(Math.floor(Math.random() * 20) + 65); // 65-85 bpm
  }

  /**
   * Get mock heart rate samples
   */
  async getHeartRateSamples(startDate: Date, endDate: Date): Promise<any[]> {
    if (!this.isAvailable) return [];

    const samples = [];
    for (let i = 0; i < 5; i++) {
      samples.push({
        value: Math.floor(Math.random() * 20) + 65,
        startDate: new Date(Date.now() - i * 3600000).toISOString(),
      });
    }
    return Promise.resolve(samples);
  }

  /**
   * Get mock resting heart rate
   */
  async getRestingHeartRate(): Promise<number | null> {
    if (!this.isAvailable) return null;
    return Promise.resolve(Math.floor(Math.random() * 10) + 55); // 55-65 bpm
  }

  /**
   * Get mock sleep data
   */
  async getSleepSamples(startDate: Date, endDate: Date): Promise<SleepData[]> {
    if (!this.isAvailable) return [];

    return Promise.resolve([
      {
        value: 'ASLEEP',
        startDate: new Date(Date.now() - 28800000).toISOString(), // 8 hours ago
        endDate: new Date().toISOString(),
      },
    ]);
  }

  /**
   * Get mock weight
   */
  async getLatestWeight(): Promise<number | null> {
    if (!this.isAvailable) return null;
    return Promise.resolve(75.5); // kg
  }

  /**
   * Get mock workouts
   */
  async getWorkoutSamples(startDate: Date, endDate: Date): Promise<WorkoutData[]> {
    if (!this.isAvailable) return [];

    return Promise.resolve([
      {
        activityType: 'Running',
        duration: 1800, // 30 minutes
        calories: 250,
        distance: 5000, // 5km
        startDate: new Date(Date.now() - 7200000).toISOString(),
        endDate: new Date(Date.now() - 5400000).toISOString(),
      },
    ]);
  }

  /**
   * Get comprehensive mock health data for today
   */
  async getTodayHealthData(): Promise<HealthData> {
    if (!this.isAvailable) {
      return {};
    }

    const [steps, distance, activeEnergy, heartRate, restingHeartRate, weight] =
      await Promise.all([
        this.getStepsToday(),
        this.getDistanceToday(),
        this.getActiveEnergyToday(),
        this.getLatestHeartRate(),
        this.getRestingHeartRate(),
        this.getLatestWeight(),
      ]);

    return {
      steps,
      distance,
      activeEnergy,
      heartRate: heartRate || undefined,
      restingHeartRate: restingHeartRate || undefined,
      weight: weight || undefined,
    };
  }

  /**
   * Get mock health data for a date range
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
   * Get daily stats for the last N days (mock data)
   */
  async getDailyStats(days: number = 7): Promise<any[]> {
    if (!this.isAvailable) return [];

    const stats: any[] = [];
    const today = new Date();

    for (let i = 0; i < days; i++) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);

      stats.push({
        date: date.toISOString().split('T')[0],
        steps: Math.floor(Math.random() * 5000) + 5000, // 5000-10000
        distance: Math.floor(Math.random() * 3000) + 4000, // 4-7 km
      });
    }

    return stats.reverse(); // Return oldest to newest
  }
}

// Export singleton instance
export const healthKitService = new HealthKitService();
export default healthKitService;

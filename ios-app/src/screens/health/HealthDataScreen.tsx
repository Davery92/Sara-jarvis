import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Platform,
  Alert,
} from 'react-native';
import { MainTabScreenProps } from '../../types/navigation';
import { useToast } from '../../context/ToastContext';
import { colors, fontSizes, spacing } from '../../styles/theme';
import healthKitService, { HealthData } from '../../services/healthKit';
import apiClient from '../../services/api';
import { backfillHistoricalData, BackfillProgress } from '../../services/backgroundHealthSync';

type Props = MainTabScreenProps<'Health'>;

export default function HealthDataScreen({ navigation }: Props) {
  const { showToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [healthKitAvailable, setHealthKitAvailable] = useState(false);
  const [todayData, setTodayData] = useState<HealthData>({});
  const [weeklyStats, setWeeklyStats] = useState<any[]>([]);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const [sleepHours, setSleepHours] = useState<number | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillStatus, setBackfillStatus] = useState<string | null>(null);

  useEffect(() => {
    initializeHealthKit();
  }, []);

  const initializeHealthKit = async () => {
    setLoading(true);
    try {
      if (Platform.OS !== 'ios') {
        showToast('warning', 'Apple Health is only available on iOS devices.');
        setLoading(false);
        return;
      }

      const available = await healthKitService.initialize();
      setHealthKitAvailable(available);

      if (available) {
        await loadHealthData();
      } else {
        showToast('warning', 'Please enable HealthKit permissions in Settings to use this feature.');
      }
    } catch (error) {
      console.error('Error initializing HealthKit:', error);
      showToast('error', 'Failed to initialize HealthKit');
    } finally {
      setLoading(false);
    }
  };

  const loadHealthData = async () => {
    try {
      const [today, stats, sleep] = await Promise.all([
        healthKitService.getTodayHealthData(),
        healthKitService.getDailyStats(7),
        healthKitService.getLastNightSleepHours(),
      ]);

      setTodayData(today);
      setWeeklyStats(stats);
      setSleepHours(sleep > 0 ? sleep : null);
    } catch (error) {
      console.error('Error loading health data:', error);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadHealthData();
    setRefreshing(false);
  };

  const syncToBackend = async () => {
    if (!healthKitAvailable) {
      showToast('error', 'HealthKit is not available');
      return;
    }

    setSyncing(true);
    try {
      // Get comprehensive health data
      const today = new Date();
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);

      const [todayHealth, rangeHealth, weekStats] = await Promise.all([
        healthKitService.getTodayHealthData(),
        healthKitService.getHealthDataForRange(yesterday, today),
        healthKitService.getDailyStats(7),
      ]);

      // Combine all data
      const healthPayload = {
        timestamp: new Date().toISOString(),
        today: todayHealth,
        sleep: rangeHealth.sleepAnalysis || [],
        workouts: rangeHealth.workout || [],
        weeklyStats: weekStats,
      };

      // Send to backend
      await apiClient.post('/api/health/sync', healthPayload);

      setLastSyncTime(new Date().toLocaleTimeString());
      showToast('success', 'Health data synced successfully!');
    } catch (error) {
      console.error('Error syncing health data:', error);
      showToast('error', 'Failed to sync health data to server');
    } finally {
      setSyncing(false);
    }
  };

  const runBackfill = (days: number) => {
    Alert.alert(
      `Backfill ${days} days?`,
      `This pulls ${days} days of HealthKit history (steps, sleep, HRV, workouts, etc.) into Sara. ` +
        `Existing rows are deduplicated server-side, so it's safe to run more than once. ` +
        `On a slow connection this can take a couple minutes.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: `Pull ${days} days`,
          style: 'default',
          onPress: async () => {
            setBackfilling(true);
            setBackfillStatus('Reading HealthKit history…');
            try {
              const result = await backfillHistoricalData(days, (p: BackfillProgress) => {
                setBackfillStatus(p.message);
              });
              setBackfillStatus(result.message);
              if (result.success) {
                // Show already-synced counts too, so "0 new" doesn't read as "nothing synced".
                const workoutsTotal = result.workoutsInserted + result.workoutsDuplicate;
                const workoutsPart = result.workoutsInserted > 0
                  ? `${result.workoutsInserted} new workouts`
                  : `${workoutsTotal} workouts (all already synced)`;
                showToast(
                  'success',
                  `Backfilled ${result.daysProcessed} days · ${result.metricsInserted} new metrics · ${workoutsPart}`,
                );
              } else {
                showToast('error', result.message || 'Backfill failed');
              }
            } catch (e) {
              const msg = e instanceof Error ? e.message : 'Unknown error';
              setBackfillStatus(`Failed: ${msg}`);
              showToast('error', msg);
            } finally {
              setBackfilling(false);
            }
          },
        },
      ],
    );
  };

  const formatDistance = (meters: number): string => {
    const km = meters / 1000;
    return `${km.toFixed(2)} km`;
  };

  const formatCalories = (kcal: number): string => {
    return `${Math.round(kcal)} kcal`;
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>Initializing HealthKit...</Text>
      </View>
    );
  }

  if (!healthKitAvailable) {
    return (
      <View style={styles.container}>
        <View style={styles.unavailableContainer}>
          <Text style={styles.unavailableIcon}>⚕️</Text>
          <Text style={styles.unavailableTitle}>HealthKit Not Available</Text>
          <Text style={styles.unavailableText}>
            Please enable HealthKit permissions in your iPhone Settings to access health data.
          </Text>
          <TouchableOpacity
            style={styles.retryButton}
            onPress={initializeHealthKit}
          >
            <Text style={styles.retryButtonText}>Retry</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={handleRefresh}
          tintColor={colors.primary}
        />
      }
    >
      {/* Sync Section */}
      <View style={styles.section}>
        <View style={styles.syncHeader}>
          <View>
            <Text style={styles.sectionTitle}>Apple Health Sync</Text>
            {lastSyncTime && (
              <Text style={styles.syncTime}>Last synced: {lastSyncTime}</Text>
            )}
          </View>
          <TouchableOpacity
            style={[styles.syncButton, syncing && styles.syncButtonDisabled]}
            onPress={syncToBackend}
            disabled={syncing}
          >
            {syncing ? (
              <ActivityIndicator size="small" color={colors.background} />
            ) : (
              <Text style={styles.syncButtonText}>Sync Now</Text>
            )}
          </TouchableOpacity>
        </View>

        {/* Historical Backfill */}
        <View style={styles.backfillRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.backfillLabel}>Historical Backfill</Text>
            <Text style={styles.backfillHint}>
              {backfillStatus
                ? backfillStatus
                : 'Pull HealthKit history into Sara. Safe to re-run.'}
            </Text>
          </View>
          <View style={styles.backfillButtonRow}>
            <TouchableOpacity
              style={[styles.backfillButton, backfilling && styles.syncButtonDisabled]}
              onPress={() => runBackfill(90)}
              disabled={backfilling}
            >
              {backfilling ? (
                <ActivityIndicator size="small" color={colors.background} />
              ) : (
                <Text style={styles.backfillButtonText}>90 days</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.backfillButton, backfilling && styles.syncButtonDisabled]}
              onPress={() => runBackfill(365)}
              disabled={backfilling}
            >
              <Text style={styles.backfillButtonText}>1 year</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {/* Today's Summary */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Today's Summary</Text>
        <View style={styles.statsGrid}>
          <View style={styles.statCard}>
            <Text style={styles.statIcon}>👟</Text>
            <Text style={styles.statValue}>{todayData.steps?.toLocaleString() || '0'}</Text>
            <Text style={styles.statLabel}>Steps</Text>
          </View>

          <View style={styles.statCard}>
            <Text style={styles.statIcon}>🏃</Text>
            <Text style={styles.statValue}>
              {todayData.distance ? formatDistance(todayData.distance) : '0 km'}
            </Text>
            <Text style={styles.statLabel}>Distance</Text>
          </View>

          <View style={styles.statCard}>
            <Text style={styles.statIcon}>🔥</Text>
            <Text style={styles.statValue}>
              {todayData.activeEnergy ? formatCalories(todayData.activeEnergy) : '0 kcal'}
            </Text>
            <Text style={styles.statLabel}>Active Energy</Text>
          </View>

          <View style={styles.statCard}>
            <Text style={styles.statIcon}>❤️</Text>
            <Text style={styles.statValue}>
              {todayData.heartRate ? Math.round(todayData.heartRate) : '--'}
            </Text>
            <Text style={styles.statLabel}>Heart Rate</Text>
          </View>
        </View>
      </View>

      {/* Body Metrics */}
      {(todayData.weight || todayData.restingHeartRate) && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Body Metrics</Text>
          <View style={styles.metricsContainer}>
            {todayData.weight && (
              <View style={styles.metricRow}>
                <Text style={styles.metricLabel}>⚖️ Weight</Text>
                <Text style={styles.metricValue}>{todayData.weight.toFixed(1)} lbs</Text>
              </View>
            )}
            {todayData.restingHeartRate && (
              <View style={styles.metricRow}>
                <Text style={styles.metricLabel}>💓 Resting HR</Text>
                <Text style={styles.metricValue}>{Math.round(todayData.restingHeartRate)} bpm</Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Last Night's Sleep */}
      {sleepHours != null && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Last Night's Sleep</Text>
          <View style={styles.metricsContainer}>
            <View style={styles.metricRow}>
              <Text style={styles.metricLabel}>🌙 Total Sleep</Text>
              <Text style={styles.metricValue}>
                {Math.floor(sleepHours)}h {Math.round((sleepHours % 1) * 60)}m
              </Text>
            </View>
          </View>
        </View>
      )}

      {/* Weekly Trend */}
      {weeklyStats.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>7-Day Trend</Text>
          <View style={styles.trendContainer}>
            {weeklyStats.map((stat, index) => {
              const date = new Date(stat.date);
              const dayName = date.toLocaleDateString('en-US', { weekday: 'short' });
              const isToday = stat.date === new Date().toISOString().split('T')[0];

              return (
                <View key={index} style={styles.trendDay}>
                  <Text style={[styles.trendDayName, isToday && styles.trendDayToday]}>
                    {dayName}
                  </Text>
                  <View style={styles.trendBar}>
                    <View
                      style={[
                        styles.trendBarFill,
                        { height: `${Math.min((stat.steps / 10000) * 100, 100)}%` },
                        isToday && styles.trendBarToday,
                      ]}
                    />
                  </View>
                  <Text style={styles.trendSteps}>
                    {(stat.steps / 1000).toFixed(1)}k
                  </Text>
                </View>
              );
            })}
          </View>
          <Text style={styles.trendFooter}>Steps per day (goal: 10k)</Text>
        </View>
      )}

      {/* Info Section */}
      <View style={styles.section}>
        <View style={styles.infoCard}>
          <Text style={styles.infoIcon}>ℹ️</Text>
          <Text style={styles.infoText}>
            Sara syncs with Apple Health to provide personalized insights and track your wellness journey.
            Your health data is private and secure.
          </Text>
        </View>
      </View>

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centered: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: spacing.md,
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },
  unavailableContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  unavailableIcon: {
    fontSize: 64,
    marginBottom: spacing.lg,
  },
  unavailableTitle: {
    fontSize: fontSizes.xl,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  unavailableText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: spacing.xl,
  },
  retryButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: 8,
  },
  retryButtonText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  section: {
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
  },
  syncHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  syncTime: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  syncButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: 8,
    minWidth: 100,
    alignItems: 'center',
  },
  syncButtonDisabled: {
    opacity: 0.6,
  },
  syncButtonText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  backfillRow: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  backfillLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
  },
  backfillHint: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  backfillButtonRow: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  backfillButton: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: 8,
    minWidth: 70,
    alignItems: 'center',
  },
  backfillButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginHorizontal: -spacing.xs,
  },
  statCard: {
    width: '50%',
    padding: spacing.xs,
  },
  statCardInner: {
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  statIcon: {
    fontSize: 32,
    marginBottom: spacing.sm,
  },
  statValue: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  statLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  metricsContainer: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  metricLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  metricValue: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.primary,
  },
  trendContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    height: 120,
    marginBottom: spacing.sm,
  },
  trendDay: {
    flex: 1,
    alignItems: 'center',
    marginHorizontal: 2,
  },
  trendDayName: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginBottom: spacing.xs,
  },
  trendDayToday: {
    color: colors.primary,
    fontWeight: '700',
  },
  trendBar: {
    flex: 1,
    width: '100%',
    backgroundColor: colors.border,
    borderRadius: 4,
    justifyContent: 'flex-end',
    overflow: 'hidden',
  },
  trendBarFill: {
    width: '100%',
    backgroundColor: colors.primary,
    opacity: 0.7,
  },
  trendBarToday: {
    opacity: 1,
  },
  trendSteps: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  trendFooter: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
  },
  infoCard: {
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  infoIcon: {
    fontSize: 24,
    marginRight: spacing.md,
  },
  infoText: {
    flex: 1,
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    lineHeight: 20,
  },
});

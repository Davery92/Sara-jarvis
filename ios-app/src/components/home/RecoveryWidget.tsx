import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { fitnessService, RecoveryLog } from '../../services/fitness';
import { getLocalDateString, formatSleepHours } from '../../utils/dateUtils';

export default function RecoveryWidget() {
  const [recovery, setRecovery] = useState<RecoveryLog | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTodayRecovery();
  }, []);

  const fetchTodayRecovery = async () => {
    try {
      setLoading(true);
      const logs = await fitnessService.getRecoveryLogs();
      const today = getLocalDateString();
      // Find today's log
      const todayLog = logs.find((log) => log.log_date === today);
      setRecovery(todayLog || null);
    } catch (error) {
      console.error('Failed to fetch recovery logs:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>❤️</Text>
          <Text style={styles.title}>Recovery</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>❤️</Text>
        <Text style={styles.title}>Recovery</Text>
      </View>

      {!recovery ? (
        <Text style={styles.emptyText}>No recovery data today</Text>
      ) : (
        <View style={styles.recoveryCard}>
          <View style={styles.metricsRow}>
            {recovery.sleep_hours !== null && recovery.sleep_hours !== undefined && (
              <View style={styles.metric}>
                <Text style={styles.metricLabel}>Sleep</Text>
                <Text style={styles.metricValue}>{formatSleepHours(recovery.sleep_hours)}</Text>
              </View>
            )}
            {recovery.hrv !== null && recovery.hrv !== undefined && (
              <View style={styles.metric}>
                <Text style={styles.metricLabel}>HRV</Text>
                <Text style={styles.metricValue}>{recovery.hrv}</Text>
              </View>
            )}
            {recovery.soreness_level !== null && recovery.soreness_level !== undefined && (
              <View style={styles.metric}>
                <Text style={styles.metricLabel}>Soreness</Text>
                <Text style={styles.metricValue}>{recovery.soreness_level}/10</Text>
              </View>
            )}
            {recovery.body_weight !== null && recovery.body_weight !== undefined && (
              <View style={styles.metric}>
                <Text style={styles.metricLabel}>Weight</Text>
                <Text style={styles.metricValue}>
                  {recovery.body_weight} {recovery.weight_unit || 'lbs'}
                </Text>
              </View>
            )}
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    margin: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  icon: {
    fontSize: 20,
    marginRight: spacing.xs,
  },
  title: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginLeft: spacing.xs,
  },
  loader: {
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  recoveryCard: {
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
  },
  metricsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  metric: {
    minWidth: '30%',
  },
  metricLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginBottom: 4,
  },
  metricValue: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
});

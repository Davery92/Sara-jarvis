import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { RecoveryLog } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { parseLocalDateString, formatSleepHours } from '../../utils/dateUtils';

interface RecoveryCardProps {
  log: RecoveryLog;
  onPress?: (log: RecoveryLog) => void;
  onLongPress?: (log: RecoveryLog) => void;
}

export default function RecoveryCard({ log, onPress, onLongPress }: RecoveryCardProps) {
  // Parse YYYY-MM-DD date string correctly (avoiding UTC timezone shift)
  const dateObj = log.log_date
    ? parseLocalDateString(log.log_date)
    : new Date(log.logged_at || new Date());
  const date = dateObj.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });

  const getMetricColor = (value: number, max: number = 10): string => {
    const percentage = value / max;
    if (percentage >= 0.7) return colors.success;
    if (percentage >= 0.4) return colors.warning;
    return colors.error;
  };

  const renderMetricBar = (label: string, value: number | undefined, max: number = 10, inverted: boolean = false) => {
    if (value === undefined || value === null) return null;

    const percentage = (value / max) * 100;
    const color = inverted
      ? getMetricColor(max - value, max)  // For soreness (lower is better)
      : getMetricColor(value, max);

    return (
      <View style={styles.metric}>
        <View style={styles.metricHeader}>
          <Text style={styles.metricLabel}>{label}</Text>
          <Text style={styles.metricValue}>{value}/{max}</Text>
        </View>
        <View style={styles.barContainer}>
          <View
            style={[
              styles.barFill,
              { width: `${percentage}%`, backgroundColor: color },
            ]}
          />
        </View>
      </View>
    );
  };

  const renderMetricValue = (label: string, value: number | undefined, unit: string = '') => {
    if (value === undefined || value === null) return null;

    return (
      <View style={styles.metricRow}>
        <Text style={styles.metricLabel}>{label}</Text>
        <Text style={styles.metricValue}>{value}{unit}</Text>
      </View>
    );
  };

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress?.(log)}
      onLongPress={() => onLongPress?.(log)}
      activeOpacity={0.7}
    >
      <View style={styles.header}>
        <Text style={styles.emoji}>💤</Text>
        <View>
          <Text style={styles.title}>Recovery Metrics</Text>
          <Text style={styles.date}>{date}</Text>
        </View>
      </View>

      {log.sleep_hours !== undefined && log.sleep_hours !== null && (
        <View style={styles.sleepCard}>
          <Text style={styles.sleepEmoji}>😴</Text>
          <Text style={styles.sleepHours}>{formatSleepHours(log.sleep_hours)}</Text>
          <Text style={styles.sleepLabel}>Sleep</Text>
        </View>
      )}

      <View style={styles.metrics}>
        {renderMetricValue('HRV', log.hrv, ' ms')}
        {renderMetricValue('Heart Rate', log.heart_rate, ' bpm')}
        {renderMetricValue('Body Weight', log.body_weight, ` ${log.weight_unit || 'lbs'}`)}
        {renderMetricBar('Soreness', log.soreness_level, 10, true)}
      </View>

      {log.notes && <Text style={styles.notes}>{log.notes}</Text>}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  emoji: {
    fontSize: fontSizes.xl,
    marginRight: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  date: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  sleepCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  sleepEmoji: {
    fontSize: 48,
    marginBottom: spacing.xs,
  },
  sleepHours: {
    color: colors.primary,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  sleepLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  metrics: {
    gap: spacing.md,
  },
  metric: {
    marginBottom: spacing.sm,
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
    paddingVertical: spacing.xs,
  },
  metricHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.xs,
  },
  metricLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  metricValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  barContainer: {
    height: 8,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: borderRadius.sm,
  },
  notes: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
    marginTop: spacing.sm,
  },
});

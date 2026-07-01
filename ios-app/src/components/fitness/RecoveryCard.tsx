import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { RecoveryLog } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
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

  const renderMetricValue = (
    label: string,
    value: number | undefined,
    unit: string = '',
    icon?: keyof typeof Ionicons.glyphMap,
  ) => {
    if (value === undefined || value === null) return null;

    return (
      <View style={styles.metricRow}>
        <View style={styles.metricLabelRow}>
          {icon && <Ionicons name={icon} size={14} color={colors.textSecondary} style={styles.metricIcon} />}
          <Text style={styles.metricLabel}>{label}</Text>
        </View>
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
        <View style={styles.headerIcon}>
          <Ionicons name="bed-outline" size={18} color={colors.accent} />
        </View>
        <View>
          <Text style={styles.title}>Recovery Metrics</Text>
          <Text style={styles.date}>{date}</Text>
        </View>
      </View>

      {log.sleep_hours !== undefined && log.sleep_hours !== null && (
        <View style={styles.sleepCard}>
          <Ionicons name="moon" size={22} color={colors.accent} style={styles.sleepIcon} />
          <View>
            <Text style={styles.sleepHours}>{formatSleepHours(log.sleep_hours)}</Text>
            <Text style={styles.sleepLabel}>Sleep</Text>
          </View>
        </View>
      )}

      <View style={styles.metrics}>
        {renderMetricValue('HRV', log.hrv, ' ms', 'pulse')}
        {renderMetricValue('Heart Rate', log.heart_rate, ' bpm', 'heart')}
        {renderMetricValue('Body Weight', log.body_weight, ` ${log.weight_unit || 'lbs'}`, 'scale')}
        {renderMetricBar('Soreness', log.soreness_level, 10, true)}
      </View>

      {log.notes && <Text style={styles.notes}>{log.notes}</Text>}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  headerIcon: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.actionSoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  date: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  sleepCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  sleepIcon: {
    marginRight: spacing.md,
  },
  sleepHours: {
    color: colors.accent,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
  },
  sleepLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  metrics: {
    gap: spacing.xs,
  },
  metric: {
    marginBottom: spacing.sm,
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.xs,
  },
  metricHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.xs,
  },
  metricLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  metricIcon: {
    marginRight: spacing.xs,
  },
  metricLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
  },
  metricValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  barContainer: {
    height: 8,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.full,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: borderRadius.full,
  },
  notes: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
    marginTop: spacing.sm,
  },
});

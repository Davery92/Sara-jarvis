// RecoveryScoreCard — the recovery hero from the dashboard mockup: a big readiness
// score with label + "vs avg" delta on the left, and a 2x2 grid of sub-metrics
// (Sleep / HRV / RHR / Weight) on the right. Score color follows the readiness band.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import Card from './Card';
import { RecoveryLog } from '../../../services/fitness';
import { RecoveryScore, formatSleep } from '../../../utils/recovery';
import { colors, spacing, fontSizes, fontWeights } from '../../../styles/theme';

interface RecoveryScoreCardProps {
  score: RecoveryScore | null;
  log: RecoveryLog | null;
  delta?: number | null;        // score vs window average
  onPress?: () => void;
}

const SCORE_COLOR: Record<RecoveryScore['color'], string> = {
  success: colors.success,
  primary: colors.primary,
  warning: colors.warning,
  error: colors.error,
};

export default function RecoveryScoreCard({ score, log, delta, onPress }: RecoveryScoreCardProps) {
  const scoreColor = score ? SCORE_COLOR[score.color] : colors.textMuted;

  const metrics = [
    { label: 'Sleep', value: formatSleep(log?.sleep_hours) ?? '—' },
    { label: 'HRV', value: log?.hrv != null ? `${Math.round(log.hrv)} ms` : '—' },
    { label: 'RHR', value: log?.heart_rate != null ? `${Math.round(log.heart_rate)} bpm` : '—' },
    {
      label: 'Weight',
      value: log?.body_weight != null ? `${log.body_weight.toFixed(1)} ${log.weight_unit || 'lbs'}` : '—',
    },
  ];

  return (
    <Card onPress={onPress}>
      <View style={styles.row}>
        {/* Score column */}
        <View style={styles.scoreCol}>
          <Text style={styles.scoreLabel}>RECOVERY SCORE</Text>
          <Text style={[styles.scoreValue, { color: scoreColor }]}>
            {score ? score.score : '--'}
          </Text>
          <Text style={[styles.scoreBand, { color: scoreColor }]}>
            {score ? score.label : 'No data'}
          </Text>
          {delta != null && Number.isFinite(delta) && Math.round(delta) !== 0 ? (
            <View style={styles.deltaRow}>
              <Ionicons
                name={delta >= 0 ? 'arrow-up' : 'arrow-down'}
                size={11}
                color={delta >= 0 ? colors.success : colors.error}
              />
              <Text style={[styles.deltaText, { color: delta >= 0 ? colors.success : colors.error }]}>
                {Math.abs(Math.round(delta))} vs avg
              </Text>
            </View>
          ) : null}
        </View>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Metrics grid */}
        <View style={styles.metricsGrid}>
          {metrics.map(m => (
            <View key={m.label} style={styles.metricCell}>
              <Text style={styles.metricLabel}>{m.label}</Text>
              <Text style={styles.metricValue}>{m.value}</Text>
            </View>
          ))}
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  scoreCol: {
    justifyContent: 'center',
    paddingRight: spacing.md,
    minWidth: 96,
  },
  scoreLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
  },
  scoreValue: {
    fontSize: 44,
    fontWeight: fontWeights.bold,
    lineHeight: 48,
    marginTop: 2,
  },
  scoreBand: {
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  deltaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    gap: 2,
  },
  deltaText: {
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
  },
  divider: {
    width: 1,
    backgroundColor: colors.divider,
    marginVertical: spacing.xs,
  },
  metricsGrid: {
    flex: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingLeft: spacing.md,
  },
  metricCell: {
    width: '50%',
    paddingVertical: spacing.xs + 2,
  },
  metricLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  metricValue: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    marginTop: 1,
  },
});

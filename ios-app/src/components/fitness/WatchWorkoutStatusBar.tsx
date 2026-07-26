import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * Quiet device state for Workout Mode (plan §9.3).
 *
 * Deliberately restrained. In the normal case — Watch tracking, heart rate
 * flowing — this is one thin line with a heart rate on it, because that is
 * reassurance David reads at a glance. It says nothing about mirrors,
 * envelopes or sessions: transport vocabulary in a success state is noise,
 * and noise is how you train someone to ignore the one message that matters.
 *
 * It only becomes assertive when there is something to do: reconnecting,
 * commands still waiting to sync, or a Watch that never woke and can be
 * retried (§4.3 partial success).
 */
export default function WatchWorkoutStatusBar() {
  const { watch, retryWatch, isActive } = useWorkoutMode();

  if (!isActive) return null;

  // Nothing to say: no Watch involved in this workout at all.
  if (!watch.tracking && !watch.reconnecting && watch.pending === 0) {
    return (
      <TouchableOpacity style={styles.row} onPress={retryWatch} hitSlop={8}>
        <Ionicons name="watch-outline" size={13} color={colors.textSecondary} />
        <Text style={styles.muted}>Not tracking on Watch</Text>
        <Text style={styles.action}>Retry</Text>
      </TouchableOpacity>
    );
  }

  if (watch.reconnecting) {
    return (
      <View style={styles.row}>
        <ActivityIndicator size="small" color={colors.textSecondary} />
        <Text style={styles.muted}>Reconnecting to Watch…</Text>
      </View>
    );
  }

  return (
    <View style={styles.row}>
      <Ionicons name="watch" size={13} color={colors.success} />
      <Text style={styles.muted}>Watch tracking</Text>

      {watch.heartRate != null && (
        <>
          <Ionicons name="heart" size={13} color="#ef4444" style={styles.gap} />
          <Text style={styles.metric}>{Math.round(watch.heartRate)}</Text>
        </>
      )}

      {watch.activeEnergyKcal != null && (
        <Text style={[styles.metric, styles.gap]}>{Math.round(watch.activeEnergyKcal)} kcal</Text>
      )}

      {watch.pending > 0 && (
        <Text style={styles.pending}>{watch.pending} syncing</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.xs,
  },
  muted: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  metric: {
    fontSize: fontSizes.xs,
    color: colors.text,
    fontWeight: fontWeights.semibold,
    fontVariant: ['tabular-nums'],
  },
  gap: {
    marginLeft: spacing.sm,
  },
  pending: {
    marginLeft: 'auto',
    fontSize: fontSizes.xs,
    color: colors.warning,
  },
  action: {
    marginLeft: 'auto',
    fontSize: fontSizes.xs,
    color: colors.primary,
    fontWeight: fontWeights.semibold,
  },
});

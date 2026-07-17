import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface TimerCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export default function TimerCard({ card }: TimerCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No active timers</Text>
      ) : (
        items.map((timer: any, index: number) => {
          const remaining = timer.remaining_seconds ?? 0;
          const duration = timer.duration_seconds ?? 1;
          const progress = duration > 0 ? Math.max(0, Math.min(1, 1 - remaining / duration)) : 0;
          const isFinished = remaining <= 0;

          return (
            <View key={timer.id ?? index} style={styles.timerRow}>
              <View style={styles.timerInfo}>
                <Text style={styles.timerTitle} numberOfLines={1}>
                  {timer.title}
                </Text>
                <View style={styles.progressBarBackground}>
                  <View style={[styles.progressBarFill, { width: `${progress * 100}%` }]} />
                </View>
              </View>
              <Text style={[styles.timeDisplay, isFinished && styles.timeFinished]}>
                {isFinished ? 'Done' : formatRemaining(remaining)}
              </Text>
            </View>
          );
        })
      )}

      {card.summary ? (
        <Text style={styles.summary}>{card.summary}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
  timerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  timerInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  timerTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  progressBarBackground: {
    height: 4,
    backgroundColor: colors.surfaceLight,
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: 4,
    backgroundColor: colors.primary,
    borderRadius: 2,
  },
  timeDisplay: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.primary,
    fontVariant: ['tabular-nums'],
    minWidth: 60,
    textAlign: 'right',
  },
  timeFinished: {
    color: colors.success,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});

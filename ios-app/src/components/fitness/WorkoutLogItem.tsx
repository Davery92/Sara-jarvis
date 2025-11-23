import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { WorkoutLog } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface WorkoutLogItemProps {
  log: WorkoutLog;
  onPress?: (log: WorkoutLog) => void;
  onLongPress?: (log: WorkoutLog) => void;
}

export default function WorkoutLogItem({ log, onPress, onLongPress }: WorkoutLogItemProps) {
  const workoutEmoji = {
    cardio: '🏃',
    strength: '💪',
    yoga: '🧘',
    sports: '⚽',
    cycling: '🚴',
    swimming: '🏊',
    walking: '🚶',
  }[log.workout_type?.toLowerCase() || ''] || '🏋️';

  const time = new Date(log.logged_at).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });

  const intensityColor = {
    low: colors.success,
    moderate: colors.warning,
    high: colors.error,
  }[log.intensity?.toLowerCase() || ''] || colors.textSecondary;

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress?.(log)}
      onLongPress={() => onLongPress?.(log)}
      activeOpacity={0.7}
    >
      <View style={styles.header}>
        <View style={styles.workoutInfo}>
          <Text style={styles.emoji}>{workoutEmoji}</Text>
          <View>
            <Text style={styles.workoutType}>{log.workout_type}</Text>
            <Text style={styles.time}>{time}</Text>
          </View>
        </View>
        {log.intensity && (
          <View style={[styles.intensityBadge, { backgroundColor: intensityColor }]}>
            <Text style={styles.intensityText}>{log.intensity}</Text>
          </View>
        )}
      </View>

      <View style={styles.stats}>
        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Duration</Text>
          <Text style={styles.statValue}>{log.duration_minutes} min</Text>
        </View>
        {log.calories_burned && (
          <View style={styles.statItem}>
            <Text style={styles.statLabel}>Calories</Text>
            <Text style={styles.statValue}>{log.calories_burned} cal</Text>
          </View>
        )}
      </View>

      {log.exercises && log.exercises.length > 0 && (
        <View style={styles.exercises}>
          <Text style={styles.exercisesTitle}>Exercises:</Text>
          {log.exercises.map((exercise, index) => (
            <Text key={index} style={styles.exerciseItem}>
              • {exercise.name}
              {exercise.sets && exercise.reps && ` - ${exercise.sets}x${exercise.reps}`}
              {exercise.weight && ` @ ${exercise.weight}lb`}
              {exercise.duration_minutes && ` - ${exercise.duration_minutes}min`}
            </Text>
          ))}
        </View>
      )}

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
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  workoutInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  emoji: {
    fontSize: fontSizes.xl,
    marginRight: spacing.sm,
  },
  workoutType: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  time: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  intensityBadge: {
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  intensityText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  stats: {
    flexDirection: 'row',
    gap: spacing.lg,
    marginBottom: spacing.sm,
  },
  statItem: {
    flex: 1,
  },
  statLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginBottom: 2,
  },
  statValue: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  exercises: {
    marginBottom: spacing.sm,
  },
  exercisesTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  exerciseItem: {
    color: colors.text,
    fontSize: fontSizes.sm,
    marginBottom: 2,
    paddingLeft: spacing.sm,
  },
  notes: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

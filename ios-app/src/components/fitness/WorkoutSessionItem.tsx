import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

export interface WorkoutSet {
  id: string;
  exercise_id: string;
  set_index: number;
  weight: number;
  reps: number;
  rpe?: number;
  notes?: string;
  session_time?: string;
  created_at: string;
}

export interface WorkoutSession {
  id: string;
  title: string;
  phase?: string;
  week?: number;
  day_of_week?: string;
  duration_min?: number;
  status: string;
  session_date?: string;
  created_at: string;
  exercises: WorkoutSet[];
}

interface WorkoutSessionItemProps {
  session: WorkoutSession;
  onPress?: (session: WorkoutSession) => void;
  onLongPress?: (session: WorkoutSession) => void;
}

export default function WorkoutSessionItem({ session, onPress, onLongPress }: WorkoutSessionItemProps) {
  // Use session_time from first exercise if available, otherwise fall back to session_date or created_at
  const firstExercise = session.exercises[0];
  const dateString = firstExercise?.session_time || session.session_date || session.created_at;
  const dateToUse = dateString.includes('T') ? dateString : `${dateString}T12:00:00`;
  const date = new Date(dateToUse);

  const dateStr = date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const timeStr = date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });

  // Group exercises by exercise_id
  const exerciseGroups: { [key: string]: WorkoutSet[] } = {};
  session.exercises.forEach((set) => {
    if (!exerciseGroups[set.exercise_id]) {
      exerciseGroups[set.exercise_id] = [];
    }
    exerciseGroups[set.exercise_id].push(set);
  });

  const totalSets = session.exercises.length;
  const exerciseCount = Object.keys(exerciseGroups).length;
  const exerciseList = Object.keys(exerciseGroups).join(', ');

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress?.(session)}
      onLongPress={() => onLongPress?.(session)}
      activeOpacity={0.7}
    >
      <View style={styles.header}>
        <View style={styles.workoutInfo}>
          <Text style={styles.emoji}>💪</Text>
          <View style={styles.headerText}>
            <Text style={styles.date}>{dateStr}</Text>
            <Text style={styles.time}>{timeStr}</Text>
          </View>
        </View>
        <View style={styles.chevron}>
          <Text style={styles.chevronText}>›</Text>
        </View>
      </View>

      <View style={styles.summary}>
        <Text style={styles.summaryText}>
          {exerciseCount} {exerciseCount === 1 ? 'exercise' : 'exercises'} • {totalSets} {totalSets === 1 ? 'set' : 'sets'}
        </Text>
        <Text style={styles.exerciseList} numberOfLines={1}>{exerciseList}</Text>
      </View>
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
    marginBottom: spacing.xs,
  },
  workoutInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  emoji: {
    fontSize: fontSizes.xl,
    marginRight: spacing.sm,
  },
  headerText: {
    flex: 1,
  },
  date: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  time: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  chevron: {
    paddingLeft: spacing.sm,
  },
  chevronText: {
    color: colors.textSecondary,
    fontSize: 24,
    fontWeight: '300',
  },
  summary: {
    marginTop: spacing.xs,
  },
  summaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  exerciseList: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
});

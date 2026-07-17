import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

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
  // Melded from the Apple Watch workout that overlapped this session.
  heart_rate?: {
    activity?: string;
    avg_heart_rate?: number;
    max_heart_rate?: number;
    min_heart_rate?: number;
    calories?: number;
    distance_m?: number | null;
    duration_min?: number | null;
  } | null;
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
          <View style={styles.iconBadge}>
            <Ionicons name="barbell" size={18} color={colors.accent} />
          </View>
          <View style={styles.headerText}>
            <Text style={styles.date}>{dateStr}</Text>
            <Text style={styles.time}>{timeStr}</Text>
          </View>
        </View>
        <View style={styles.chevron}>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
        </View>
      </View>

      <View style={styles.summary}>
        <Text style={styles.summaryText}>
          {exerciseCount} {exerciseCount === 1 ? 'exercise' : 'exercises'} • {totalSets} {totalSets === 1 ? 'set' : 'sets'}
        </Text>
        <Text style={styles.exerciseList} numberOfLines={1}>{exerciseList}</Text>
        {session.heart_rate?.avg_heart_rate ? (
          <View style={styles.hrRow}>
            <Ionicons name="heart" size={12} color="#ff5a3a" />
            <Text style={styles.hrText}>
              {session.heart_rate.avg_heart_rate} avg
              {session.heart_rate.max_heart_rate ? ` · ${session.heart_rate.max_heart_rate} max bpm` : ' bpm'}
              {session.heart_rate.calories ? ` · ${session.heart_rate.calories} cal` : ''}
              {session.heart_rate.distance_m ? ` · ${(session.heart_rate.distance_m / 1609.34).toFixed(2)} mi` : ''}
            </Text>
          </View>
        ) : null}
      </View>
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
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  workoutInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  iconBadge: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  headerText: {
    flex: 1,
  },
  date: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  time: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  chevron: {
    paddingLeft: spacing.sm,
  },
  summary: {
    marginTop: spacing.xs,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  summaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  exerciseList: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
  },
  hrRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 4,
  },
  hrText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
  },
});

import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { fitnessService, WorkoutSession } from '../../services/fitness';
import { getLocalDateString } from '../../utils/dateUtils';

export default function RecentWorkoutsWidget() {
  const [session, setSession] = useState<WorkoutSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRecentWorkout();
  }, []);

  const fetchRecentWorkout = async () => {
    try {
      setLoading(true);
      const today = getLocalDateString();
      const sessions = await fitnessService.getWorkoutSessions(today, today);
      if (sessions.length > 0) {
        setSession(sessions[0]);
      }
    } catch (error) {
      console.error('Failed to fetch workout sessions:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>💪</Text>
          <Text style={styles.title}>Recent Workout</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>💪</Text>
        <Text style={styles.title}>Recent Workout</Text>
      </View>

      {!session ? (
        <Text style={styles.emptyText}>No workouts logged today</Text>
      ) : (
        <View style={styles.workoutCard}>
          <Text style={styles.workoutTitle} numberOfLines={1}>
            {session.title}
          </Text>
          <View style={styles.workoutStats}>
            <Text style={styles.statText}>
              {session.exercises.length} exercises
            </Text>
            {session.duration_min && (
              <Text style={styles.statText}>• {session.duration_min} min</Text>
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
  workoutCard: {
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
  },
  workoutTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  workoutStats: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statText: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginRight: spacing.sm,
  },
});

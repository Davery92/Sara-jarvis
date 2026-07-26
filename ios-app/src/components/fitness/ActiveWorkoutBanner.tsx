import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * Active-workout entry point (plan §9.2).
 *
 * When David starts a workout on his wrist, the phone must not force itself to
 * the foreground — he is mid-set and a hijacked screen is worse than useless.
 * But the moment he *does* open Sara, the workout has to be one obvious tap
 * away rather than something to go looking for.
 *
 * So: a banner, not a modal. It states which surface is tracking, because
 * "Workout active on Watch" answers the question he actually has ("did it pick
 * that up?"), and tapping it opens Workout Mode with the full phone controls
 * intact.
 */
export default function ActiveWorkoutBanner() {
  const navigation = useNavigation<any>();
  const { isActive, session, watch } = useWorkoutMode();

  if (!isActive) return null;

  const name = session?.workout_snapshot?.template_name || 'Workout';
  const label = watch.tracking ? 'Workout active on Watch' : 'Workout in progress';

  return (
    <TouchableOpacity
      style={styles.banner}
      onPress={() => navigation.navigate('WorkoutMode' as any)}
      activeOpacity={0.8}
    >
      <Ionicons
        name={watch.tracking ? 'watch' : 'barbell'}
        size={18}
        color={colors.primary}
      />
      <View style={styles.text}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.name} numberOfLines={1}>
          {name}
          {watch.heartRate != null ? ` · ${Math.round(watch.heartRate)} bpm` : ''}
        </Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={colors.textSecondary} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  text: {
    flex: 1,
  },
  label: {
    fontSize: fontSizes.xs,
    color: colors.primary,
    fontWeight: fontWeights.semibold,
  },
  name: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
});

import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, Switch, ActivityIndicator } from 'react-native';
import { fitnessService } from '../../services/fitness';
import { workoutCoordinator } from '../../services/workoutCoordinator';
import type { WorkoutPolicy } from '../../services/workoutContracts';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * Standing bounded approvals for workouts (plan §6.9, §11.1).
 *
 * These are not ordinary preferences. Each switch is David granting Sara
 * permission to act inside a boundary without asking again — "you may start a
 * rest timer", "you may speak up during a set". That framing matters: it is
 * exactly what makes the rest of the approval model workable, because without
 * it Sara would have to ask before every rest timer, and an assistant that
 * asks constantly gets ignored.
 *
 * What no switch here can do is widen the boundary. Changing a target weight,
 * reordering exercises, altering a program — those always need their own
 * approval, whatever is toggled on this screen (§11.2). The wording is chosen
 * to say so out loud rather than leave it implied.
 *
 * Every change goes through the `set_policy` command, so the approval is
 * durable and attributable rather than a silent config write (§2.4).
 */
export default function WorkoutCoachingSection() {
  const [policy, setPolicy] = useState<WorkoutPolicy | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fitnessService
      .v2Policy()
      .then(({ policy }) => setPolicy(policy))
      .catch(() => setPolicy(null));
  }, []);

  const update = useCallback(async (key: keyof WorkoutPolicy, value: boolean) => {
    if (!policy) return;
    const next = { ...policy, [key]: value };
    // Optimistic: a switch that lags feels broken. The command is idempotent,
    // so a failure just leaves the previous value in place on the next read.
    setPolicy(next);
    setSaving(true);
    try {
      await workoutCoordinator.issue('set_policy', { policy: { [key]: value } });
      const { policy: confirmed } = await fitnessService.v2Policy();
      setPolicy(confirmed);
    } catch {
      setPolicy(policy);
    } finally {
      setSaving(false);
    }
  }, [policy]);

  if (!policy) return null;

  const rows: Array<{ key: keyof WorkoutPolicy; label: string; description: string }> = [
    {
      key: 'auto_start_rest_after_set',
      label: 'Start rest automatically',
      description: `Begins the timer when you log a set, within ${policy.rest_range_seconds[0]}–${policy.rest_range_seconds[1]}s.`,
    },
    {
      key: 'adaptive_rest_enabled',
      label: 'Adapt rest to effort',
      description: 'Longer after a hard set, shorter after an easy one — inside the same range.',
    },
    {
      key: 'speak_routine_coaching',
      label: 'Speak coaching',
      description: 'Short prompts through your AirPods. Music ducks for the sentence, then returns.',
    },
    {
      key: 'speak_prs',
      label: 'Speak personal records',
      description: 'Say something when you hit a new best.',
    },
    {
      key: 'speak_proposals',
      label: 'Speak suggestions',
      description: 'Read recommendations aloud. You still approve them by hand.',
    },
  ];

  return (
    <View style={styles.section}>
      <View style={styles.titleRow}>
        <Text style={styles.sectionTitle}>Workout Coaching</Text>
        {saving && <ActivityIndicator size="small" color={colors.textSecondary} />}
      </View>

      {rows.map(({ key, label, description }) => (
        <View key={key} style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.label}>{label}</Text>
            <Text style={styles.description}>{description}</Text>
          </View>
          <Switch
            value={Boolean(policy[key])}
            onValueChange={(value) => update(key, value)}
            trackColor={{ false: colors.background, true: colors.primary }}
          />
        </View>
      ))}

      <Text style={styles.footnote}>
        These let Sara act without asking each time. Changing a weight, an exercise or your
        program still needs your approval.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    color: colors.text,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    gap: spacing.md,
  },
  rowText: {
    flex: 1,
  },
  label: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  description: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  footnote: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    fontStyle: 'italic',
  },
});

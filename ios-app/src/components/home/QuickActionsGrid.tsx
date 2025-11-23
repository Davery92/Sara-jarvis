import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Props {
  onLogFood: () => void;
  onLogWorkout: () => void;
  onLogRecovery: () => void;
  onQuickNote: () => void;
  onStartTimer: () => void;
}

export default function QuickActionsGrid({
  onLogFood,
  onLogWorkout,
  onLogRecovery,
  onQuickNote,
  onStartTimer,
}: Props) {
  const actions = [
    { icon: '🍽️', label: 'Log Food', onPress: onLogFood, color: colors.success },
    { icon: '💪', label: 'Log Workout', onPress: onLogWorkout, color: colors.primary },
    { icon: '❤️', label: 'Log Recovery', onPress: onLogRecovery, color: '#ef4444' },
    { icon: '📝', label: 'Quick Note', onPress: onQuickNote, color: '#a855f7' },
    { icon: '⏱️', label: 'Start Timer', onPress: onStartTimer, color: '#f59e0b' },
    { icon: '➕', label: 'More', onPress: () => {}, color: colors.textMuted },
  ];

  return (
    <View style={styles.container}>
      <View style={styles.grid}>
        {actions.map((action, index) => (
            <TouchableOpacity
              key={index}
              style={styles.actionButton}
              onPress={action.onPress}
              activeOpacity={0.7}
            >
              <View style={[styles.iconContainer, { backgroundColor: action.color }]}>
                <Text style={styles.iconText}>{action.icon}</Text>
              </View>
              <Text style={styles.actionLabel}>{action.label}</Text>
            </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  actionButton: {
    width: '30%',
    alignItems: 'center',
    padding: spacing.sm,
  },
  iconContainer: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  iconText: {
    fontSize: 24,
  },
  actionLabel: {
    fontSize: fontSizes.xs,
    color: colors.text,
    textAlign: 'center',
  },
});

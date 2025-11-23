import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { FoodLog } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface FoodLogItemProps {
  log: FoodLog;
  onPress?: (log: FoodLog) => void;
  onLongPress?: (log: FoodLog) => void;
}

export default function FoodLogItem({ log, onPress, onLongPress }: FoodLogItemProps) {
  const mealTypeEmoji = {
    breakfast: '🌅',
    lunch: '🌞',
    dinner: '🌙',
    snack: '🍎',
  }[log.meal_type?.toLowerCase() || ''] || '🍽️';

  const time = new Date(log.logged_at).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });

  const hasMacros = log.calories || log.protein || log.carbs || log.fat;

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress?.(log)}
      onLongPress={() => onLongPress?.(log)}
      activeOpacity={0.7}
    >
      <View style={styles.header}>
        <View style={styles.mealInfo}>
          <Text style={styles.emoji}>{mealTypeEmoji}</Text>
          <View>
            <Text style={styles.mealType}>{log.meal_type}</Text>
            <Text style={styles.time}>{time}</Text>
          </View>
        </View>
        {log.calories && (
          <View style={styles.caloriesBadge}>
            <Text style={styles.caloriesText}>{log.calories} cal</Text>
          </View>
        )}
      </View>

      <Text style={styles.foodName}>
        {log.food_name} ({log.quantity} {log.unit})
      </Text>

      {hasMacros && (
        <View style={styles.macros}>
          {log.protein !== undefined && (
            <View style={styles.macroItem}>
              <Text style={styles.macroLabel}>P</Text>
              <Text style={styles.macroValue}>{log.protein}g</Text>
            </View>
          )}
          {log.carbs !== undefined && (
            <View style={styles.macroItem}>
              <Text style={styles.macroLabel}>C</Text>
              <Text style={styles.macroValue}>{log.carbs}g</Text>
            </View>
          )}
          {log.fat !== undefined && (
            <View style={styles.macroItem}>
              <Text style={styles.macroLabel}>F</Text>
              <Text style={styles.macroValue}>{log.fat}g</Text>
            </View>
          )}
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
  mealInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  emoji: {
    fontSize: fontSizes.xl,
    marginRight: spacing.sm,
  },
  mealType: {
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
  caloriesBadge: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  caloriesText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  foodName: {
    color: colors.text,
    fontSize: fontSizes.md,
    marginBottom: spacing.sm,
  },
  macros: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  macroItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  macroLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  macroValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  notes: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

// MacroRings — the four-ring macro summary from the mockups (Calories / Protein /
// Carbs / Fat). Each ring shows current value in the center, goal underneath, and
// the macro label below. Fills proportionally to goal and tints per-macro.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Ring from './Ring';
import { colors, fontSizes, fontWeights } from '../../../styles/theme';

export interface MacroData {
  calories: number;
  protein: number;
  carbs: number;
  fats: number;
}

interface MacroRingsProps {
  totals: MacroData;
  goals: MacroData;
  size?: number;
  compact?: boolean;   // smaller rings + tighter spacing (dashboard summary)
}

export default function MacroRings({ totals, goals, size, compact }: MacroRingsProps) {
  const ringSize = size ?? (compact ? 64 : 72);
  const stroke = compact ? 6 : 7;

  const items = [
    { key: 'calories', label: 'Calories', value: totals.calories, goal: goals.calories, unit: '', color: colors.fitness.calories },
    { key: 'protein', label: 'Protein', value: totals.protein, goal: goals.protein, unit: 'g', color: colors.fitness.protein },
    { key: 'carbs', label: 'Carbs', value: totals.carbs, goal: goals.carbs, unit: 'g', color: colors.fitness.carbs },
    { key: 'fats', label: 'Fat', value: totals.fats, goal: goals.fats, unit: 'g', color: colors.fitness.fats },
  ] as const;

  return (
    <View style={styles.row}>
      {items.map(item => {
        const progress = item.goal > 0 ? item.value / item.goal : 0;
        return (
          <View key={item.key} style={styles.col}>
            <Ring size={ringSize} strokeWidth={stroke} progress={progress} color={item.color}>
              <Text style={[styles.value, compact && styles.valueCompact]} numberOfLines={1}>
                {Math.round(item.value)}
              </Text>
              <Text style={styles.goal} numberOfLines={1}>
                /{Math.round(item.goal)}{item.unit}
              </Text>
            </Ring>
            <Text style={styles.label}>{item.label}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  col: {
    alignItems: 'center',
    flex: 1,
  },
  value: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
  },
  valueCompact: {
    fontSize: fontSizes.sm,
  },
  goal: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 1,
  },
  label: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: 6,
  },
});

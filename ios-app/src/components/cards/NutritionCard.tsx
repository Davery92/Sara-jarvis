import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface NutritionCardProps {
  card: any;
  onAction: (action: any) => void;
}

export default function NutritionCard({ card }: NutritionCardProps) {
  const items = card.items || [];
  const summaryData = card.summary_data;

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {summaryData && (
        <View style={styles.macroRow}>
          {summaryData.calories != null && (
            <View style={styles.macroBadge}>
              <Text style={[styles.macroValue, { color: colors.fitness.calories }]}>
                {Math.round(summaryData.calories)}
              </Text>
              <Text style={styles.macroLabel}>cal</Text>
            </View>
          )}
          {summaryData.protein != null && (
            <View style={styles.macroBadge}>
              <Text style={[styles.macroValue, { color: colors.fitness.protein }]}>
                {Math.round(summaryData.protein)}g
              </Text>
              <Text style={styles.macroLabel}>protein</Text>
            </View>
          )}
          {summaryData.carbs != null && (
            <View style={styles.macroBadge}>
              <Text style={[styles.macroValue, { color: colors.fitness.carbs }]}>
                {Math.round(summaryData.carbs)}g
              </Text>
              <Text style={styles.macroLabel}>carbs</Text>
            </View>
          )}
          {summaryData.fats != null && (
            <View style={styles.macroBadge}>
              <Text style={[styles.macroValue, { color: colors.fitness.fats }]}>
                {Math.round(summaryData.fats)}g
              </Text>
              <Text style={styles.macroLabel}>fats</Text>
            </View>
          )}
        </View>
      )}

      {items.length === 0 && !summaryData ? (
        <Text style={styles.emptyText}>No meals logged</Text>
      ) : (
        items.map((meal: any, index: number) => (
          <View key={meal.id ?? index} style={styles.mealRow}>
            <View style={styles.mealInfo}>
              <Text style={styles.mealName} numberOfLines={1}>
                {meal.food_name || meal.title || meal.name}
              </Text>
              {meal.meal_type ? (
                <Text style={styles.mealType}>{meal.meal_type}</Text>
              ) : null}
            </View>
            {meal.calories != null && (
              <Text style={styles.calories}>{Math.round(meal.calories)} cal</Text>
            )}
          </View>
        ))
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
  macroRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
  },
  macroBadge: {
    alignItems: 'center',
  },
  macroValue: {
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  macroLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  mealRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  mealInfo: {
    flex: 1,
    marginRight: spacing.sm,
  },
  mealName: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  mealType: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  calories: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.fitness.calories,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});

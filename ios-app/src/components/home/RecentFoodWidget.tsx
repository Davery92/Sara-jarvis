import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { fitnessService, FoodLog } from '../../services/fitness';

export default function RecentFoodWidget() {
  const [foodLogs, setFoodLogs] = useState<FoodLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRecentFood();
  }, []);

  const fetchRecentFood = async () => {
    try {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];
      const logs = await fitnessService.getFoodLogs(today, today);

      // Filter to only show food logged today (in case API returns other dates)
      const todayLogs = logs.filter((log) => {
        const logDate = new Date(log.logged_at || log.created_at).toISOString().split('T')[0];
        return logDate === today;
      });

      setFoodLogs(todayLogs.slice(0, 3)); // Show last 3 items from today
    } catch (error) {
      console.error('Failed to fetch food logs:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>🍽️</Text>
          <Text style={styles.title}>Recent Food</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>🍽️</Text>
        <Text style={styles.title}>Recent Food</Text>
      </View>

      {foodLogs.length === 0 ? (
        <Text style={styles.emptyText}>No meals logged today</Text>
      ) : (
        foodLogs.map((log) => (
          <View key={log.id} style={styles.foodCard}>
            <View style={styles.foodInfo}>
              <Text style={styles.foodName} numberOfLines={1}>
                {log.food_name}
              </Text>
              <Text style={styles.foodDetails}>
                {log.meal_type} • {log.quantity} {log.unit}
              </Text>
            </View>
            {log.calories && (
              <Text style={styles.calories}>{Math.round(log.calories)} cal</Text>
            )}
          </View>
        ))
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
  foodCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  foodInfo: {
    flex: 1,
    marginRight: spacing.sm,
  },
  foodName: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginBottom: 2,
  },
  foodDetails: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  calories: {
    fontSize: fontSizes.sm,
    color: colors.success,
    fontWeight: '600',
  },
});

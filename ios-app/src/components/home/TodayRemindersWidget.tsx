import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';

interface DailyTask {
  id: string;
  title: string;
  priority: string;
  is_completed: boolean;
}

export default function TodayRemindersWidget() {
  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [loading, setLoading] = useState(true);
  const navigation = useNavigation();

  useEffect(() => {
    fetchTasks();
  }, []);

  const fetchTasks = async () => {
    try {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];
      const data = await apiClient.getDailyTasks(today);
      setTasks(data);
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleTask = async (id: string) => {
    try {
      await apiClient.toggleDailyTask(id);
      setTasks((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, is_completed: !t.is_completed } : t
        )
      );
    } catch (error) {
      console.error('Failed to toggle task:', error);
    }
  };

  const completedCount = tasks.filter((t) => t.is_completed).length;
  const totalCount = tasks.length;
  const displayTasks = tasks.filter((t) => !t.is_completed).slice(0, 3);

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>{'\u2705'}</Text>
          <Text style={styles.title}>Today's Tasks</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => (navigation as any).navigate('DailyTasks')}
      activeOpacity={0.8}
    >
      <View style={styles.header}>
        <Text style={styles.icon}>{'\u2705'}</Text>
        <Text style={styles.title}>Today's Tasks</Text>
        {totalCount > 0 && (
          <Text style={styles.counter}>{completedCount}/{totalCount}</Text>
        )}
      </View>

      {totalCount === 0 ? (
        <Text style={styles.emptyText}>No tasks for today</Text>
      ) : (
        <>
          {displayTasks.map((task) => (
            <TouchableOpacity
              key={task.id}
              style={styles.taskCard}
              onPress={() => toggleTask(task.id)}
              activeOpacity={0.7}
            >
              <Text style={styles.checkbox}>{'\u2B1C'}</Text>
              <Text style={styles.taskText} numberOfLines={1}>
                {task.title}
              </Text>
              {task.priority === 'high' && (
                <Text style={styles.highBadge}>!</Text>
              )}
            </TouchableOpacity>
          ))}
          {tasks.filter((t) => !t.is_completed).length > 3 && (
            <Text style={styles.moreText}>
              +{tasks.filter((t) => !t.is_completed).length - 3} more
            </Text>
          )}
          {totalCount > 0 && (
            <View style={styles.progressBar}>
              <View
                style={[
                  styles.progressFill,
                  { width: `${(completedCount / totalCount) * 100}%` },
                ]}
              />
            </View>
          )}
        </>
      )}
    </TouchableOpacity>
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
    flex: 1,
  },
  counter: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontWeight: '600',
  },
  checkbox: {
    fontSize: 20,
    marginRight: spacing.md,
  },
  loader: {
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  taskCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  taskText: {
    fontSize: fontSizes.md,
    color: colors.text,
    flex: 1,
  },
  highBadge: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
    color: colors.error,
    marginLeft: spacing.xs,
  },
  moreText: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.xs,
  },
  progressBar: {
    height: 3,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginTop: spacing.sm,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.success,
    borderRadius: 2,
  },
});

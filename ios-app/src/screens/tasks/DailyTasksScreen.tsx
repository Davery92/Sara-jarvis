import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  TextInput,
  FlatList,
  ActivityIndicator,
  Alert,
  RefreshControl,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import { SkeletonList } from '../../components/SkeletonLoader';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface DailyTask {
  id: string;
  title: string;
  description?: string;
  task_date: string;
  priority: 'low' | 'normal' | 'high';
  is_completed: boolean;
  completed_at?: string;
  created_at: string;
}

const PRIORITY_COLORS = {
  high: colors.error,
  normal: colors.primary,
  low: colors.textMuted,
};

const PRIORITY_LABELS = {
  high: 'High',
  normal: 'Normal',
  low: 'Low',
};

export default function DailyTasksScreen() {
  const { showToast } = useToast();
  const [tasks, setTasks] = useState<DailyTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newPriority, setNewPriority] = useState<'low' | 'normal' | 'high'>('normal');
  const [adding, setAdding] = useState(false);

  const today = new Date().toISOString().split('T')[0];

  const fetchTasks = async () => {
    try {
      const data = await apiClient.getDailyTasks(today);
      setTasks(data);
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useFocusEffect(
    useCallback(() => {
      fetchTasks();
    }, [])
  );

  const handleRefresh = () => {
    setRefreshing(true);
    fetchTasks();
  };

  const handleAdd = async () => {
    const title = newTitle.trim();
    if (!title) return;

    setAdding(true);
    try {
      await apiClient.createDailyTask({ title, priority: newPriority, task_date: today });
      setNewTitle('');
      setNewPriority('normal');
      await fetchTasks();
    } catch (error) {
      showToast('error', 'Failed to create task');
    } finally {
      setAdding(false);
    }
  };

  const handleToggle = async (id: string) => {
    try {
      await apiClient.toggleDailyTask(id);
      setTasks((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, is_completed: !t.is_completed } : t
        )
      );
    } catch (error) {
      showToast('error', 'Failed to toggle task');
    }
  };

  const handleDelete = (id: string, title: string) => {
    Alert.alert('Delete Task', `Delete "${title}"?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.deleteDailyTask(id);
            setTasks((prev) => prev.filter((t) => t.id !== id));
          } catch (error) {
            showToast('error', 'Failed to delete task');
          }
        },
      },
    ]);
  };

  const handleCarryOver = async () => {
    try {
      const carried = await apiClient.carryOverTasks();
      if (carried.length > 0) {
        showToast('success', `${carried.length} task(s) moved from yesterday`);
        await fetchTasks();
      } else {
        showToast('info', 'No incomplete tasks from yesterday');
      }
    } catch (error) {
      showToast('error', 'Failed to carry over tasks');
    }
  };

  const completedCount = tasks.filter((t) => t.is_completed).length;
  const totalCount = tasks.length;

  const renderTask = ({ item }: { item: DailyTask }) => (
    <TouchableOpacity
      style={styles.taskCard}
      onPress={() => handleToggle(item.id)}
      onLongPress={() => handleDelete(item.id, item.title)}
      activeOpacity={0.7}
    >
      <View style={[styles.priorityBar, { backgroundColor: PRIORITY_COLORS[item.priority] }]} />
      <Text style={styles.checkbox}>{item.is_completed ? '\u2705' : '\u2B1C'}</Text>
      <View style={styles.taskContent}>
        <Text
          style={[styles.taskTitle, item.is_completed && styles.completedText]}
          numberOfLines={2}
        >
          {item.title}
        </Text>
        {item.description ? (
          <Text style={styles.taskDescription} numberOfLines={1}>
            {item.description}
          </Text>
        ) : null}
      </View>
      {!item.is_completed && item.priority !== 'normal' && (
        <View style={[styles.priorityBadge, { backgroundColor: PRIORITY_COLORS[item.priority] + '20' }]}>
          <Text style={[styles.priorityText, { color: PRIORITY_COLORS[item.priority] }]}>
            {PRIORITY_LABELS[item.priority]}
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );

  if (loading) {
    return (
      <View style={styles.container}>
        <SkeletonList count={6} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header stats */}
      <View style={styles.header}>
        <Text style={styles.dateText}>
          {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </Text>
        <View style={styles.statsRow}>
          <Text style={styles.statsText}>
            {completedCount}/{totalCount} done
          </Text>
          <TouchableOpacity onPress={handleCarryOver} style={styles.carryOverButton}>
            <Text style={styles.carryOverText}>Carry over</Text>
          </TouchableOpacity>
        </View>
        {totalCount > 0 && (
          <View style={styles.progressBar}>
            <View
              style={[
                styles.progressFill,
                { width: `${totalCount > 0 ? (completedCount / totalCount) * 100 : 0}%` },
              ]}
            />
          </View>
        )}
      </View>

      {/* Task list */}
      <FlatList
        data={tasks}
        keyExtractor={(item) => item.id}
        renderItem={renderTask}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyIcon}>{"\\u2705"}</Text>
            <Text style={styles.emptyText}>No tasks for today</Text>
            <Text style={styles.emptySubtext}>Add a task below or ask Sara</Text>
          </View>
        }
      />

      {/* Add task input */}
      <View style={styles.addContainer}>
        <View style={styles.prioritySelector}>
          {(['low', 'normal', 'high'] as const).map((p) => (
            <TouchableOpacity
              key={p}
              style={[
                styles.priorityOption,
                newPriority === p && { backgroundColor: PRIORITY_COLORS[p] + '30' },
              ]}
              onPress={() => setNewPriority(p)}
            >
              <View style={[styles.priorityDot, { backgroundColor: PRIORITY_COLORS[p] }]} />
            </TouchableOpacity>
          ))}
        </View>
        <TextInput
          style={styles.input}
          placeholder="Add a task..."
          placeholderTextColor={colors.textMuted}
          value={newTitle}
          onChangeText={setNewTitle}
          onSubmitEditing={handleAdd}
          returnKeyType="done"
        />
        <TouchableOpacity
          style={[styles.addButton, !newTitle.trim() && styles.addButtonDisabled]}
          onPress={handleAdd}
          disabled={!newTitle.trim() || adding}
        >
          {adding ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text style={styles.addButtonText}>+</Text>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  header: {
    padding: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  dateText: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.xs,
  },
  statsText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  carryOverButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  carryOverText: {
    fontSize: fontSizes.sm,
    color: colors.primary,
  },
  progressBar: {
    height: 4,
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
  listContent: {
    padding: spacing.md,
    paddingBottom: 100,
  },
  taskCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
  },
  priorityBar: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 3,
    borderTopLeftRadius: borderRadius.md,
    borderBottomLeftRadius: borderRadius.md,
  },
  checkbox: {
    fontSize: 22,
    marginRight: spacing.md,
    marginLeft: spacing.xs,
  },
  taskContent: {
    flex: 1,
  },
  taskTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  completedText: {
    textDecorationLine: 'line-through',
    color: colors.textMuted,
  },
  taskDescription: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  priorityBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    marginLeft: spacing.sm,
  },
  priorityText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xl * 2,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyText: {
    fontSize: fontSizes.lg,
    color: colors.text,
    fontWeight: '600',
  },
  emptySubtext: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  addContainer: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    paddingBottom: spacing.lg,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  prioritySelector: {
    flexDirection: 'row',
    marginRight: spacing.sm,
    gap: 4,
  },
  priorityOption: {
    width: 28,
    height: 28,
    borderRadius: borderRadius.full,
    justifyContent: 'center',
    alignItems: 'center',
  },
  priorityDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  input: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: fontSizes.md,
    color: colors.text,
  },
  addButton: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.full,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.sm,
  },
  addButtonDisabled: {
    opacity: 0.4,
  },
  addButtonText: {
    fontSize: 24,
    color: '#fff',
    fontWeight: '600',
    lineHeight: 26,
  },
});

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  ScrollView,
  Animated,
  Easing,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService } from '../services/backgroundTasks';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';

interface BackgroundTasksIndicatorProps {
  onNavigateToNote?: (noteId: string) => void;
}

export default function BackgroundTasksIndicator({
  onNavigateToNote,
}: BackgroundTasksIndicatorProps) {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [showPanel, setShowPanel] = useState(false);
  const spinValue = useState(new Animated.Value(0))[0];

  // Subscribe to task updates
  useEffect(() => {
    const unsubscribe = backgroundTaskService.subscribe(setTasks);

    return () => {
      unsubscribe();
    };
  }, []);

  // Spinning animation for active tasks
  useEffect(() => {
    const activeCount = tasks.filter(t =>
      t.status === 'pending' || t.status === 'running'
    ).length;

    if (activeCount > 0) {
      const spin = Animated.loop(
        Animated.timing(spinValue, {
          toValue: 1,
          duration: 2000,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      );
      spin.start();

      return () => spin.stop();
    } else {
      spinValue.setValue(0);
    }
  }, [tasks, spinValue]);

  const activeTasks = tasks.filter(t => t.status === 'pending' || t.status === 'running');
  const recentTasks = tasks.filter(t => t.status === 'completed' || t.status === 'failed');
  const activeCount = activeTasks.length;

  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return colors.primary;
      case 'pending': return colors.warning;
      case 'completed': return colors.success;
      case 'failed': return colors.error;
      case 'needs_clarification': return '#f97316'; // orange
      default: return colors.textMuted;
    }
  };

  const getStatusEmoji = (status: string) => {
    switch (status) {
      case 'running': return '🔄';
      case 'pending': return '⏳';
      case 'completed': return '✅';
      case 'failed': return '❌';
      case 'needs_clarification': return '❓';
      default: return '⚪';
    }
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  const truncateQuery = (query: string, maxLen = 50) => {
    return query.length > maxLen ? query.substring(0, maxLen) + '...' : query;
  };

  const handleTaskPress = (task: BackgroundTask) => {
    if (task.status === 'completed' && task.result_note_id && onNavigateToNote) {
      onNavigateToNote(task.result_note_id);
      setShowPanel(false);
    }
  };

  // Don't render if no tasks at all
  if (tasks.length === 0) {
    return null;
  }

  return (
    <>
      {/* Indicator Button */}
      <TouchableOpacity
        style={styles.indicatorButton}
        onPress={() => setShowPanel(true)}
      >
        <Animated.View style={activeCount > 0 ? { transform: [{ rotate: spin }] } : undefined}>
          <Text style={styles.indicatorIcon}>
            {activeCount > 0 ? '🔄' : '📋'}
          </Text>
        </Animated.View>
        {activeCount > 0 && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{activeCount}</Text>
          </View>
        )}
      </TouchableOpacity>

      {/* Tasks Panel Modal */}
      <Modal
        visible={showPanel}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowPanel(false)}
      >
        <SafeAreaView style={styles.modalContainer} edges={['top', 'left', 'right']}>
          {/* Header */}
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowPanel(false)}>
              <Text style={styles.closeButton}>Close</Text>
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Background Tasks</Text>
            <View style={{ width: 50 }} />
          </View>

          <ScrollView style={styles.scrollView}>
            {/* Active Tasks */}
            {activeTasks.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Active</Text>
                {activeTasks.map(task => (
                  <View key={task.id} style={styles.taskItem}>
                    <Text style={styles.taskIcon}>{getStatusEmoji(task.status)}</Text>
                    <View style={styles.taskContent}>
                      <Text style={styles.taskQuery}>{truncateQuery(task.original_query)}</Text>
                      <Text style={styles.taskMeta}>
                        Started {formatTime(task.started_at || task.created_at)}
                      </Text>
                    </View>
                  </View>
                ))}
              </View>
            )}

            {/* Recent Tasks */}
            {recentTasks.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Recent</Text>
                {recentTasks.slice(0, 5).map(task => (
                  <TouchableOpacity
                    key={task.id}
                    style={[
                      styles.taskItem,
                      task.status === 'completed' && task.result_note_id && styles.taskClickable
                    ]}
                    onPress={() => handleTaskPress(task)}
                    disabled={!(task.status === 'completed' && task.result_note_id)}
                  >
                    <Text style={styles.taskIcon}>{getStatusEmoji(task.status)}</Text>
                    <View style={styles.taskContent}>
                      <Text style={styles.taskQuery}>{truncateQuery(task.original_query)}</Text>
                      <View style={styles.taskMetaRow}>
                        <Text style={styles.taskMeta}>
                          {formatTime(task.completed_at || task.created_at)}
                        </Text>
                        {task.status === 'completed' && task.result_note_id && (
                          <Text style={styles.viewResult}>View result</Text>
                        )}
                        {task.status === 'failed' && task.error_message && (
                          <Text style={styles.errorText} numberOfLines={1}>
                            {task.error_message}
                          </Text>
                        )}
                      </View>
                    </View>
                  </TouchableOpacity>
                ))}
              </View>
            )}

            {/* Empty State */}
            {tasks.length === 0 && (
              <View style={styles.emptyState}>
                <Text style={styles.emptyIcon}>🔮</Text>
                <Text style={styles.emptyTitle}>No background tasks</Text>
                <Text style={styles.emptySubtitle}>
                  Ask Sara to research something in the background
                </Text>
              </View>
            )}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  indicatorButton: {
    padding: spacing.sm,
    marginRight: spacing.xs,
    position: 'relative',
  },
  indicatorIcon: {
    fontSize: 24,
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    backgroundColor: colors.primary,
    borderRadius: 10,
    minWidth: 18,
    height: 18,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: 'bold',
  },
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
  },
  closeButton: {
    fontSize: fontSizes.md,
    color: colors.primary,
  },
  scrollView: {
    flex: 1,
  },
  section: {
    padding: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.sm,
  },
  taskItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  taskClickable: {
    opacity: 1,
  },
  taskIcon: {
    fontSize: 20,
    marginRight: spacing.sm,
  },
  taskContent: {
    flex: 1,
  },
  taskQuery: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginBottom: 4,
  },
  taskMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  taskMeta: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  viewResult: {
    fontSize: fontSizes.sm,
    color: colors.success,
  },
  errorText: {
    fontSize: fontSizes.sm,
    color: colors.error,
    flex: 1,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
    marginTop: spacing.xl * 2,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptySubtitle: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
    textAlign: 'center',
  },
});

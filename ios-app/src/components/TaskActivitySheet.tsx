/**
 * TaskActivitySheet
 *
 * The detail view behind the floating task pill: everything Sara has running or
 * recently finished, from every dispatch path (chat handoffs, agent/host
 * dispatch, code mode, research plans). Adapted from the old
 * BackgroundTasksIndicator, which had this list but was imported by nothing.
 *
 * Failures show their real error text, and anything the server marks
 * `cancellable` gets a Cancel button that actually revokes the worker.
 */

import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  ScrollView,
  ActivityIndicator,
  Alert,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService } from '../services/backgroundTasks';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';

interface TaskActivitySheetProps {
  visible: boolean;
  tasks: BackgroundTask[];
  onClose: () => void;
  onNavigateToNote?: (noteId: string) => void;
}

const ACTIVE_STATUSES = ['pending', 'running', 'needs_clarification'];

function statusColor(status: string): string {
  switch (status) {
    case 'running': return colors.primary;
    case 'pending': return colors.warning;
    case 'completed': return colors.success;
    case 'failed': return colors.error;
    case 'needs_clarification': return colors.hues.orange;
    default: return colors.textMuted;
  }
}

function statusEmoji(status: string): string {
  switch (status) {
    case 'running': return '🔄';
    case 'pending': return '⏳';
    case 'completed': return '✅';
    case 'failed': return '❌';
    case 'needs_clarification': return '❓';
    default: return '⚪';
  }
}

function kindLabel(task: BackgroundTask): string {
  if (task.task_type === 'research_plan') {
    return task.origin === 'sara_internal' ? "Sara's own research" : 'Research';
  }
  return (task.task_type || 'task').replace(/_/g, ' ');
}

function formatTime(dateStr?: string | null): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '';
  const diffMins = Math.floor((Date.now() - date.getTime()) / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return date.toLocaleDateString();
}

function elapsed(task: BackgroundTask): string {
  const start = Date.parse(task.started_at || task.created_at || '');
  if (isNaN(start)) return '';
  const end = task.completed_at ? Date.parse(task.completed_at) : Date.now();
  const secs = Math.max(0, Math.floor((end - start) / 1000));
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

export default function TaskActivitySheet({
  visible,
  tasks,
  onClose,
  onNavigateToNote,
}: TaskActivitySheetProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);

  const activeTasks = tasks.filter(t => ACTIVE_STATUSES.includes(t.status));
  const recentTasks = tasks.filter(t => !ACTIVE_STATUSES.includes(t.status));

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await backgroundTaskService.fetchTasks();
    } finally {
      setRefreshing(false);
    }
  }, []);

  const confirmCancel = useCallback((task: BackgroundTask) => {
    Alert.alert(
      'Cancel this task?',
      `"${task.original_query}" will be stopped.`,
      [
        { text: 'Keep running', style: 'cancel' },
        {
          text: 'Cancel task',
          style: 'destructive',
          onPress: async () => {
            setCancelling(task.id);
            try {
              const ok = await backgroundTaskService.cancelTask(task.id);
              if (!ok) Alert.alert('Could not cancel', 'The task did not stop. Try again.');
            } finally {
              setCancelling(null);
            }
          },
        },
      ],
    );
  }, []);

  const openResult = useCallback((task: BackgroundTask) => {
    if (task.status === 'completed' && task.result_note_id && onNavigateToNote) {
      onNavigateToNote(task.result_note_id);
      onClose();
    }
  }, [onNavigateToNote, onClose]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.modalContainer} edges={['top', 'left', 'right']}>
        <View style={styles.modalHeader}>
          <TouchableOpacity onPress={onClose}>
            <Text style={styles.closeButton}>Close</Text>
          </TouchableOpacity>
          <Text style={styles.modalTitle}>Sara's Tasks</Text>
          <View style={{ width: 50 }} />
        </View>

        <ScrollView
          style={styles.scrollView}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.primary} />
          }
        >
          {activeTasks.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Active</Text>
              {activeTasks.map(task => (
                <View key={task.id} style={styles.taskItem}>
                  <Text style={styles.taskIcon}>{statusEmoji(task.status)}</Text>
                  <View style={styles.taskContent}>
                    <Text style={styles.taskKind}>{kindLabel(task)}</Text>
                    <Text style={styles.taskQuery} numberOfLines={2}>{task.original_query}</Text>
                    {!!task.status_label && (
                      <Text style={[styles.taskStep, { color: statusColor(task.status) }]}>
                        {task.status_label}
                      </Text>
                    )}
                    <Text style={styles.taskMeta}>
                      Running {elapsed(task)} · started {formatTime(task.started_at || task.created_at)}
                    </Text>
                  </View>
                  {task.cancellable && (
                    <TouchableOpacity
                      style={styles.cancelButton}
                      onPress={() => confirmCancel(task)}
                      disabled={cancelling === task.id}
                    >
                      {cancelling === task.id
                        ? <ActivityIndicator size="small" color={colors.error} />
                        : <Text style={styles.cancelButtonText}>Cancel</Text>}
                    </TouchableOpacity>
                  )}
                </View>
              ))}
            </View>
          )}

          {recentTasks.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Recent</Text>
              {recentTasks.slice(0, 8).map(task => (
                <TouchableOpacity
                  key={task.id}
                  style={styles.taskItem}
                  onPress={() => openResult(task)}
                  disabled={!(task.status === 'completed' && task.result_note_id)}
                >
                  <Text style={styles.taskIcon}>{statusEmoji(task.status)}</Text>
                  <View style={styles.taskContent}>
                    <Text style={styles.taskKind}>{kindLabel(task)}</Text>
                    <Text style={styles.taskQuery} numberOfLines={2}>{task.original_query}</Text>
                    <Text style={styles.taskMeta}>
                      {formatTime(task.completed_at || task.created_at)}
                      {elapsed(task) ? ` · took ${elapsed(task)}` : ''}
                    </Text>
                    {task.status === 'completed' && task.result_note_id && (
                      <Text style={styles.viewResult}>View result note →</Text>
                    )}
                    {task.status === 'failed' && !!task.error_message && (
                      <Text style={styles.errorText} numberOfLines={4}>
                        {task.error_message}
                      </Text>
                    )}
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          )}

          {tasks.length === 0 && (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>🔮</Text>
              <Text style={styles.emptyTitle}>Nothing running</Text>
              <Text style={styles.emptySubtitle}>
                Ask Sara to research something in the background and it'll show up here.
              </Text>
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
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
  taskIcon: {
    fontSize: 20,
    marginRight: spacing.sm,
  },
  taskContent: {
    flex: 1,
  },
  taskKind: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textTransform: 'capitalize',
    marginBottom: 2,
  },
  taskQuery: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginBottom: 4,
  },
  taskStep: {
    fontSize: fontSizes.sm,
    marginBottom: 4,
  },
  taskMeta: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  viewResult: {
    fontSize: fontSizes.sm,
    color: colors.success,
    marginTop: 4,
  },
  errorText: {
    fontSize: fontSizes.sm,
    color: colors.error,
    marginTop: 4,
  },
  cancelButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.error,
    marginLeft: spacing.sm,
  },
  cancelButtonText: {
    fontSize: fontSizes.sm,
    color: colors.error,
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

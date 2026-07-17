/**
 * AssistantInboxScreen — the Inbox tab.
 *
 * Two-pivot triage view backed by /api/assistant-inbox/unified:
 *  - "Needs you": active attention items (incl. HITL questions) and task
 *    clarifications. Every card is actionable in place — reply inline,
 *    archive, run quick actions, open the related note, discuss in chat.
 *  - "FYI": notifications, running/recent background work, unread captures.
 *    Tap to expand (marks read), swipe-free clear-all.
 *
 * The server dedupes (a notification tied to an active attention item only
 * shows once) and owns the badge formula, so the count here, the tab badge,
 * and the app icon badge all mean the same thing.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  DeviceEventEmitter,
  Linking,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { AppStackParamList } from '../../navigation/AppNavigator';
import apiClient from '../../services/api';
import { assistantAnalytics } from '../../services/assistantAnalytics';
import { navigateToChat, navigateToNoteEditor } from '../../services/navigation';
import { borderRadius, colors, fontSizes, spacing } from '../../styles/theme';

type InboxNavigationProp = NativeStackNavigationProp<AppStackParamList, 'AssistantInbox'>;

interface UnifiedItem {
  id: string;
  kind: 'attention' | 'task_clarification' | 'notification' | 'task' | 'capture';
  ref_id: string;
  title: string;
  body: string | null;
  priority: string;
  source: string;
  status: string;
  unread: boolean;
  created_at: string | null;
  is_hitl: boolean;
  actions: Array<{ id: string; label: string }>;
  payload: Record<string, any>;
}

function formatRelativeTime(isoString: string | null): string {
  if (!isoString) return '';
  const diffMs = Date.now() - new Date(isoString).getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));
  if (diffMinutes < 1) return 'now';
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d`;
  return new Date(isoString).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function hoursFromNow(hours: number): string {
  return new Date(Date.now() + hours * 3600_000).toISOString();
}

function tomorrow9am(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return d.toISOString();
}

const KIND_ICONS: Record<UnifiedItem['kind'], React.ComponentProps<typeof Ionicons>['name']> = {
  attention: 'alert-circle-outline',
  task_clarification: 'help-circle-outline',
  notification: 'notifications-outline',
  task: 'construct-outline',
  capture: 'bookmark-outline',
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: colors.error,
  urgent: colors.error,
  high: colors.warning,
  normal: colors.primary,
  low: colors.textMuted,
};

export default function AssistantInboxScreen() {
  const navigation = useNavigation<InboxNavigationProp>();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [needsYou, setNeedsYou] = useState<UnifiedItem[]>([]);
  const [fyi, setFyi] = useState<UnifiedItem[]>([]);
  const [counts, setCounts] = useState({ needs_you: 0, fyi_unread: 0, badge: 0 });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const appStateRef = useRef(AppState.currentState);
  const lastOpenedAtRef = useRef(0);

  const load = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const data = await apiClient.getUnifiedInbox();
      setNeedsYou(data.needs_you || []);
      setFyi(data.fyi || []);
      setCounts(data.counts || { needs_you: 0, fyi_unread: 0, badge: 0 });
    } catch (error) {
      console.error('[AssistantInbox] Failed to load:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const reloadAndSync = useCallback(() => {
    load(false);
    DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
  }, [load]);

  useFocusEffect(
    useCallback(() => {
      const now = Date.now();
      if (now - lastOpenedAtRef.current > 15000) {
        lastOpenedAtRef.current = now;
        assistantAnalytics.track('assistant.inbox_opened', {
          focus: 'unified',
          has_waiting_items: needsYou.length > 0,
        });
      }
      load(needsYou.length === 0 && fyi.length === 0);

      const appStateSubscription = AppState.addEventListener('change', (nextState) => {
        const wasBackgrounded = appStateRef.current.match(/inactive|background/);
        appStateRef.current = nextState;
        if (wasBackgrounded && nextState === 'active') {
          load(false);
        }
      });
      return () => appStateSubscription.remove();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [load]),
  );

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    load(false);
  }, [load]);

  // ── Item actions ──────────────────────────────────────────────────────

  const handleExpand = useCallback((item: UnifiedItem) => {
    const expanding = expandedId !== item.id;
    setExpandedId(expanding ? item.id : null);
    // Expanding an unread FYI notification marks it read.
    if (expanding && item.kind === 'notification' && item.unread) {
      apiClient.markNotificationRead(item.ref_id).then(() => {
        setFyi((prev) =>
          prev.map((i) => (i.id === item.id ? { ...i, unread: false, status: 'read' } : i)),
        );
        DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
      }).catch(() => {});
    }
    // Expanding an unread attention item marks it read (still needs you,
    // but stops counting toward the badge).
    if (expanding && item.kind === 'attention' && item.unread) {
      apiClient.markAttentionRead(item.ref_id).then(() => {
        setNeedsYou((prev) =>
          prev.map((i) => (i.id === item.id ? { ...i, unread: false, status: 'read' } : i)),
        );
        DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
      }).catch(() => {});
    }
  }, [expandedId]);

  const handleArchiveAttention = useCallback(async (item: UnifiedItem) => {
    setBusyId(item.id);
    try {
      await apiClient.archiveAttentionItem(item.ref_id);
      setNeedsYou((prev) => prev.filter((i) => i.id !== item.id));
      DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
    } catch {
      Alert.alert('Error', 'Could not archive that item.');
    } finally {
      setBusyId(null);
    }
  }, []);

  const handleReply = useCallback(async (item: UnifiedItem) => {
    const message = (replyDrafts[item.id] || '').trim();
    if (!message) return;
    setBusyId(item.id);
    try {
      if (item.kind === 'task_clarification') {
        await apiClient.post(`/api/background-tasks/${item.ref_id}/clarify`, { response: message });
      } else {
        await apiClient.replyToAttentionItem(item.ref_id, message);
      }
      setReplyDrafts((prev) => ({ ...prev, [item.id]: '' }));
      setNeedsYou((prev) => prev.filter((i) => i.id !== item.id));
      reloadAndSync();
    } catch {
      Alert.alert('Error', 'Could not send your reply.');
    } finally {
      setBusyId(null);
    }
  }, [replyDrafts, reloadAndSync]);

  // Act on the server's post-action directive. Check-ins return
  // {type:'chat', prompt:'Help me handle this: …'} for "Reply to Sara" — open
  // chat seeded with that prompt. (Previously only result.note_id was checked,
  // so "Reply to Sara" silently did nothing.)
  const handleAttentionDirective = useCallback((directive?: {
    type?: string;
    prompt?: string;
    url?: string;
    note_id?: string;
    note_title?: string;
    note_preview?: string;
    title?: string;
  }) => {
    if (!directive?.type) return;
    if (directive.type === 'chat') {
      if (directive.note_id) {
        navigateToChat({
          noteContext: {
            id: directive.note_id,
            title: directive.note_title || directive.title || 'Shared note',
            prompt: directive.prompt,
            preview: directive.note_preview,
          },
        });
        return;
      }
      navigateToChat({
        heartbeat: {
          title: directive.title || 'Attention item',
          message: directive.prompt || 'Help me handle this.',
          priority: 'normal',
        },
      });
      return;
    }
    if (directive.type === 'open_url' && directive.url) {
      Linking.openURL(directive.url).catch(() => {});
    }
  }, []);

  const runAttentionAction = useCallback(async (
    item: UnifiedItem,
    actionId: string,
    params?: Record<string, any>,
  ) => {
    setBusyId(item.id);
    try {
      const result = await apiClient.runAttentionAction(item.ref_id, actionId, params);
      if (result?.directive) {
        handleAttentionDirective(result.directive);
      } else if (result?.note_id) {
        navigateToNoteEditor(result.note_id);
      }
      reloadAndSync();
    } catch {
      Alert.alert('Error', 'That action failed — try again from chat.');
    } finally {
      setBusyId(null);
    }
  }, [reloadAndSync, handleAttentionDirective]);

  const handleQuickAction = useCallback((item: UnifiedItem, action: { id: string; label: string }) => {
    if (action.id === 'remind_me') {
      Alert.alert('Remind me', 'When should I remind you?', [
        { text: '1 hour', onPress: () => runAttentionAction(item, action.id, { reminder_time: hoursFromNow(1) }) },
        { text: '3 hours', onPress: () => runAttentionAction(item, action.id, { reminder_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(item, action.id, { reminder_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
      return;
    }
    if (action.id === 'add_to_calendar') {
      Alert.alert('Add to calendar', 'When should this event be?', [
        { text: 'In 1 hour', onPress: () => runAttentionAction(item, action.id, { start_time: hoursFromNow(1) }) },
        { text: 'In 3 hours', onPress: () => runAttentionAction(item, action.id, { start_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(item, action.id, { start_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
      return;
    }
    runAttentionAction(item, action.id);
  }, [runAttentionAction]);

  const handleDiscuss = useCallback((item: UnifiedItem) => {
    navigateToChat({
      notification: {
        id: item.ref_id,
        title: item.title,
        message: item.body || '',
        category: item.payload?.category || item.kind,
        item_type: item.kind,
      },
    });
  }, []);

  const handleClearFyi = useCallback(async () => {
    try {
      await Promise.allSettled([
        apiClient.markAllNotificationsRead(),
        apiClient.markAllInboxRead(),
      ]);
      reloadAndSync();
    } catch {
      Alert.alert('Error', 'Could not clear updates right now.');
    }
  }, [reloadAndSync]);

  const handleItemPress = useCallback((item: UnifiedItem) => {
    if (item.kind === 'capture') {
      navigation.navigate('Inbox', { tab: 'content' });
      return;
    }
    if (item.kind === 'task' && item.payload?.note_id) {
      navigateToNoteEditor(item.payload.note_id);
      return;
    }
    handleExpand(item);
  }, [handleExpand, navigation]);

  // ── Rendering ─────────────────────────────────────────────────────────

  const renderCard = (item: UnifiedItem, section: 'needs_you' | 'fyi') => {
    const expanded = expandedId === item.id;
    const busy = busyId === item.id;
    const accent = PRIORITY_COLORS[item.priority] || colors.primary;
    const needsReplyBox = item.is_hitl || item.kind === 'task_clarification';

    return (
      <TouchableOpacity
        key={item.id}
        style={[styles.card, item.unread && styles.cardUnread]}
        activeOpacity={0.85}
        onPress={() => handleItemPress(item)}
      >
        <View style={styles.cardHeader}>
          <Ionicons
            name={KIND_ICONS[item.kind]}
            size={16}
            color={section === 'needs_you' ? accent : colors.textMuted}
            style={styles.cardIcon}
          />
          <Text style={styles.cardTitle} numberOfLines={expanded ? undefined : 2}>
            {item.title}
          </Text>
          {item.unread && <View style={[styles.unreadDot, { backgroundColor: accent }]} />}
          <Text style={styles.cardTime}>{formatRelativeTime(item.created_at)}</Text>
        </View>

        {!!item.body && (
          <Text style={styles.cardBody} numberOfLines={expanded ? undefined : 2}>
            {item.body}
          </Text>
        )}

        <View style={styles.cardMetaRow}>
          <Text style={styles.cardSource}>{item.source}</Text>
          {item.kind === 'task' && item.status === 'running' && (
            <View style={styles.runningPill}>
              <ActivityIndicator size="small" color={colors.primary} />
              <Text style={styles.runningText}>working</Text>
            </View>
          )}
          {item.kind === 'task' && item.status === 'failed' && (
            <Text style={styles.failedText}>failed</Text>
          )}
        </View>

        {/* Inline reply for HITL questions and task clarifications */}
        {needsReplyBox && (
          <View style={styles.replyRow}>
            <TextInput
              style={styles.replyInput}
              value={replyDrafts[item.id] || ''}
              onChangeText={(text) => setReplyDrafts((prev) => ({ ...prev, [item.id]: text }))}
              placeholder="Answer Sara..."
              placeholderTextColor={colors.textMuted}
              multiline
              editable={!busy}
            />
            <TouchableOpacity
              style={[styles.replySend, !(replyDrafts[item.id] || '').trim() && styles.replySendDisabled]}
              onPress={() => handleReply(item)}
              disabled={busy || !(replyDrafts[item.id] || '').trim()}
            >
              {busy ? (
                <ActivityIndicator size="small" color={colors.text} />
              ) : (
                <Ionicons name="send" size={16} color={colors.text} />
              )}
            </TouchableOpacity>
          </View>
        )}

        {/* Action row */}
        {section === 'needs_you' && (
          <View style={styles.actionRow}>
            {item.kind === 'attention' && !item.is_hitl &&
              item.actions.map((action) => (
                <TouchableOpacity
                  key={action.id}
                  style={styles.actionChip}
                  onPress={() => handleQuickAction(item, action)}
                  disabled={busy}
                >
                  <Text style={styles.actionChipText}>{action.label}</Text>
                </TouchableOpacity>
              ))}
            {!!item.payload?.note_id && (
              <TouchableOpacity
                style={styles.actionChip}
                onPress={() => navigateToNoteEditor(item.payload.note_id)}
              >
                <Text style={styles.actionChipText}>Open note</Text>
              </TouchableOpacity>
            )}
            <TouchableOpacity style={styles.actionChip} onPress={() => handleDiscuss(item)}>
              <Text style={styles.actionChipText}>Discuss</Text>
            </TouchableOpacity>
            {item.kind === 'attention' && (
              <TouchableOpacity
                style={[styles.actionChip, styles.actionChipDone]}
                onPress={() => handleArchiveAttention(item)}
                disabled={busy}
              >
                <Text style={[styles.actionChipText, styles.actionChipDoneText]}>Done</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        {section === 'fyi' && expanded && item.kind === 'notification' && (
          <View style={styles.actionRow}>
            <TouchableOpacity style={styles.actionChip} onPress={() => handleDiscuss(item)}>
              <Text style={styles.actionChipText}>Discuss</Text>
            </TouchableOpacity>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.loadingContainer} edges={['top', 'bottom']}>
        <ActivityIndicator size="large" color={colors.primary} />
      </SafeAreaView>
    );
  }

  const subtitle =
    counts.needs_you > 0
      ? `${counts.needs_you} thing${counts.needs_you === 1 ? '' : 's'} need${counts.needs_you === 1 ? 's' : ''} you`
      : counts.fyi_unread > 0
        ? `Nothing needs you — ${counts.fyi_unread} unread update${counts.fyi_unread === 1 ? '' : 's'}`
        : 'All clear';

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
      >
        <View style={styles.header}>
          <Text style={styles.title}>Inbox</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>

        {/* Needs you */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Needs you</Text>
          {counts.needs_you > 0 && (
            <View style={styles.countPill}>
              <Text style={styles.countPillText}>{counts.needs_you}</Text>
            </View>
          )}
        </View>
        {needsYou.length === 0 ? (
          <Text style={styles.emptyText}>Nothing needs you right now.</Text>
        ) : (
          needsYou.map((item) => renderCard(item, 'needs_you'))
        )}

        {/* FYI */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>FYI</Text>
          {counts.fyi_unread > 0 && (
            <TouchableOpacity style={styles.clearButton} onPress={handleClearFyi}>
              <Text style={styles.clearButtonText}>Mark all read</Text>
            </TouchableOpacity>
          )}
        </View>
        {fyi.length === 0 ? (
          <Text style={styles.emptyText}>No recent updates.</Text>
        ) : (
          fyi.map((item) => renderCard(item, 'fyi'))
        )}

        {/* Compact links to the detail surfaces */}
        <View style={styles.linksRow}>
          <TouchableOpacity onPress={() => navigation.navigate('Notifications')}>
            <Text style={styles.linkText}>All notifications</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => navigation.navigate('Inbox', { tab: 'content' })}>
            <Text style={styles.linkText}>Captures</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => navigation.navigate('AgentTasks')}>
            <Text style={styles.linkText}>Agent tasks</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => navigation.navigate('ACS')}>
            <Text style={styles.linkText}>ACS</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  content: {
    padding: spacing.md,
    paddingBottom: spacing.xl * 2,
  },
  header: {
    marginBottom: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    gap: spacing.sm,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  countPill: {
    backgroundColor: colors.warning + '28',
    borderRadius: borderRadius.full,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  countPillText: {
    color: colors.warning,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
  clearButton: {
    marginLeft: 'auto',
  },
  clearButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardUnread: {
    borderColor: 'rgba(130, 151, 182, 0.38)',
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
  },
  cardIcon: {
    marginTop: 2,
  },
  cardTitle: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
  },
  cardTime: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  cardBody: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
    lineHeight: 19,
  },
  cardMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.xs,
    gap: spacing.sm,
  },
  cardSource: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  runningPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  runningText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
  },
  failedText: {
    color: colors.error,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  replyRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  replyInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.text,
    fontSize: fontSizes.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    maxHeight: 96,
  },
  replySend: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  replySendDisabled: {
    opacity: 0.4,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  actionChip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
  },
  actionChipText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  actionChipDone: {
    borderColor: colors.success + '60',
    backgroundColor: colors.success + '14',
  },
  actionChipDoneText: {
    color: colors.success,
  },
  linksRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
    marginTop: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  linkText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
});

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useBackgroundTasks } from '../../context/BackgroundTasksContext';
import type { BackgroundTask } from '../../types/api';
import type { AppStackParamList } from '../../navigation/AppNavigator';
import apiClient from '../../services/api';
import { assistantAnalytics } from '../../services/assistantAnalytics';
import { navigateToChat } from '../../services/navigation';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';

type AssistantInboxFocus = 'all' | 'waiting' | 'in_progress' | 'new' | 'done' | 'archived';
type AssistantInboxNavigationProp = NativeStackNavigationProp<AppStackParamList, 'AssistantInbox'>;
type AssistantInboxRouteProp = RouteProp<AppStackParamList, 'AssistantInbox'>;
type ItemState = Exclude<AssistantInboxFocus, 'all'>;

interface AttentionItem {
  id: string;
  title: string;
  body: string | null;
  priority: 'low' | 'normal' | 'high' | 'urgent' | 'critical';
  status: 'new' | 'sent' | 'read' | 'archived' | 'dropped';
  created_at: string;
}

interface InboxItem {
  id: string;
  title: string | null;
  description: string | null;
  status: string;
  shared_at: string;
  original_url: string | null;
}

interface NotificationItem {
  id: string;
  title: string;
  message: string;
  category: string;
  priority: string;
  source: string;
  item_type: string;
  created_at: string;
  read_at: string | null;
  engaged: boolean;
}

interface Mission {
  id: string;
  title: string;
  description: string | null;
  state: string;
  source: string;
  created_at: string;
  completed_at: string | null;
}

interface ACSDirective {
  id: string;
  directive_type: string;
  content: string;
  priority: string;
  status: string;
  source: string;
  response?: string;
  created_at: string;
}

interface ACSSnapshot {
  state: string;
  daily_plan?: string;
  directives?: ACSDirective[];
  latest_note?: {
    created_at: string;
  };
  last_session?: {
    mode: string;
    ended_at: string;
  };
  live_session?: {
    id: string;
    mode: string;
    turns: number;
    elapsed_minutes: number;
  };
}

interface UnifiedItem {
  id: string;
  state: ItemState;
  kind: 'attention' | 'task' | 'mission' | 'notification' | 'content' | 'acs';
  title: string;
  summary: string;
  timestamp: string;
  sourceLabel: string;
  cta: string;
  color: string;
  onPress: () => void;
}

const STATE_META: Record<ItemState, { label: string; description: string; color: string }> = {
  waiting: {
    label: 'Waiting on you',
    description: 'Clarifications, queued attention items, and pending decisions.',
    color: colors.warning,
  },
  in_progress: {
    label: 'In progress',
    description: 'Tasks Sara is running or background work that is still moving.',
    color: colors.primary,
  },
  new: {
    label: 'New',
    description: 'Fresh signals, captures, and discoveries Sara surfaced recently.',
    color: colors.secondary,
  },
  done: {
    label: 'Done',
    description: 'Completed or closed-out work worth reviewing once.',
    color: colors.success,
  },
  archived: {
    label: 'Archived',
    description: 'Seen, sorted, or tucked away so the active inbox stays calm.',
    color: colors.textMuted,
  },
};

const KIND_LABELS: Record<UnifiedItem['kind'], string> = {
  attention: 'Attention',
  task: 'Task',
  mission: 'Mission',
  notification: 'Notification',
  content: 'Capture',
  acs: 'ACS',
};

const DETAIL_FEEDS: Array<{
  key: string;
  label: string;
  description: string;
  onPress: (navigation: AssistantInboxNavigationProp) => void;
}> = [
  {
    key: 'attention',
    label: 'Attention Queue',
    description: 'Directives, reminders, and items that still need a response.',
    onPress: (navigation) => navigation.navigate('Inbox', { tab: 'attention' }),
  },
  {
    key: 'content',
    label: 'Captured Content',
    description: 'Links, text, and clips you have shared into Sara.',
    onPress: (navigation) => navigation.navigate('Inbox', { tab: 'content' }),
  },
  {
    key: 'notifications',
    label: 'Notifications',
    description: 'Recent nudges, discoveries, and alerts from Sara.',
    onPress: (navigation) => navigation.navigate('Notifications'),
  },
  {
    key: 'tasks',
    label: 'Agent Tasks',
    description: 'Detailed mission state, clarifications, and task outcomes.',
    onPress: (navigation) => navigation.navigate('AgentTasks'),
  },
  {
    key: 'acs',
    label: 'ACS',
    description: 'Autonomous cognition sessions, directives, and deliverables.',
    onPress: (navigation) => navigation.navigate('ACS'),
  },
];

function formatRelativeTime(isoString: string | null): string {
  if (!isoString) return 'Recently';
  const diffMs = Date.now() - new Date(isoString).getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));

  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Date(isoString).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function sortByTimestamp<T extends { created_at?: string | null; completed_at?: string | null; discovered_at?: string | null; shared_at?: string | null }>(
  items: T[],
): T[] {
  return [...items].sort((a, b) => {
    const aTime = new Date(a.completed_at || a.discovered_at || a.shared_at || a.created_at || 0).getTime();
    const bTime = new Date(b.completed_at || b.discovered_at || b.shared_at || b.created_at || 0).getTime();
    return bTime - aTime;
  });
}

function mapBackgroundTaskState(task: BackgroundTask): ItemState {
  if (task.status === 'needs_clarification') return 'waiting';
  if (task.status === 'pending' || task.status === 'running') return 'in_progress';
  return 'done';
}

function mapMissionState(state: string): ItemState {
  if (state === 'needs_clarification' || state === 'awaiting_confirm') return 'waiting';
  if (state === 'pending' || state === 'running') return 'in_progress';
  return 'done';
}

function mapAttentionState(status: AttentionItem['status']): ItemState {
  if (status === 'new' || status === 'sent') return 'waiting';
  if (status === 'read') return 'done';
  return 'archived';
}

function mapDirectiveState(status: string): ItemState {
  const normalized = status.toLowerCase();
  if (normalized === 'completed' || normalized === 'done') {
    return 'done';
  }
  if (normalized === 'dismissed' || normalized === 'archived') {
    return 'archived';
  }
  if (normalized === 'new' || normalized === 'queued') {
    return 'new';
  }
  return 'waiting';
}

function mapContentState(status: string): ItemState {
  const normalized = status.toLowerCase();
  if (normalized === 'unread') return 'new';
  if (normalized === 'read') return 'done';
  return 'archived';
}

export default function AssistantInboxScreen() {
  const navigation = useNavigation<AssistantInboxNavigationProp>();
  const route = useRoute<AssistantInboxRouteProp>();
  const { tasks, refreshTasks } = useBackgroundTasks();

  const [focus, setFocus] = useState<AssistantInboxFocus>(route.params?.focus || 'all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
  const [acsSnapshot, setAcsSnapshot] = useState<ACSSnapshot | null>(null);
  const [contentUnread, setContentUnread] = useState(0);
  const lastInboxOpenedAtRef = useRef(0);
  const hasWaitingItemsRef = useRef(false);

  useEffect(() => {
    if (route.params?.focus) {
      setFocus(route.params.focus);
    }
  }, [route.params?.focus]);

  useEffect(() => {
    hasWaitingItemsRef.current = attentionItems.some(
      (item) => mapAttentionState(item.status) === 'waiting',
    );
  }, [attentionItems]);

  const loadAssistantActivity = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      await refreshTasks();
      const [
        attentionResult,
        notificationsResult,
        missionsResult,
        inboxResult,
        inboxStatsResult,
        acsSnapshotResult,
      ] = await Promise.allSettled([
        apiClient.getAttentionItems(undefined, 12),
        apiClient.get('/api/notifications?limit=20'),
        apiClient.getMissions(),
        apiClient.getInboxItems(undefined, 12),
        apiClient.getInboxStats(),
        apiClient.get('/api/acs/snapshot'),
      ]);

      if (attentionResult.status === 'fulfilled') {
        setAttentionItems(sortByTimestamp(attentionResult.value || []));
      }
      if (notificationsResult.status === 'fulfilled') {
        setNotifications(sortByTimestamp((notificationsResult.value as any)?.notifications || []));
      }
      if (missionsResult.status === 'fulfilled') {
        setMissions(sortByTimestamp(missionsResult.value || []));
      }
      if (inboxResult.status === 'fulfilled') {
        setInboxItems(sortByTimestamp(inboxResult.value || []));
      }
      if (inboxStatsResult.status === 'fulfilled') {
        setContentUnread(inboxStatsResult.value?.unread || 0);
      }
      if (acsSnapshotResult.status === 'fulfilled') {
        setAcsSnapshot((acsSnapshotResult.value as ACSSnapshot) || null);
      }
    } catch (error) {
      console.error('Failed to load assistant inbox:', error);
      Alert.alert('Error', 'Unable to load assistant activity right now.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [refreshTasks]);

  useFocusEffect(
    useCallback(() => {
      const now = Date.now();
      if (now - lastInboxOpenedAtRef.current > 15000) {
        lastInboxOpenedAtRef.current = now;
        assistantAnalytics.track('assistant.inbox_opened', {
          focus,
          has_waiting_items: hasWaitingItemsRef.current,
        });
      }
      loadAssistantActivity();
    }, [focus, loadAssistantActivity]),
  );

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    loadAssistantActivity(false);
  }, [loadAssistantActivity]);

  const unifiedItems = useMemo<UnifiedItem[]>(() => {
    const items: UnifiedItem[] = [];

    attentionItems.forEach((item) => {
      items.push({
        id: `attention-${item.id}`,
        state: mapAttentionState(item.status),
        kind: 'attention',
        title: item.title,
        summary: item.body || 'Sara flagged this for follow-up.',
        timestamp: item.created_at,
        sourceLabel: 'Autonomy',
        cta: 'Open queue',
        color: STATE_META[mapAttentionState(item.status)].color,
        onPress: () => navigation.navigate('Inbox', { tab: 'attention' }),
      });
    });

    tasks.forEach((task) => {
      const taskState = mapBackgroundTaskState(task);
      items.push({
        id: `task-${task.id}`,
        state: taskState,
        kind: 'task',
        title: task.original_query,
        summary:
          task.status === 'needs_clarification'
            ? (task.clarification_question || 'Sara needs a little more input before continuing.')
            : (task.error_message || 'Background work is still underway.'),
        timestamp: task.completed_at || task.started_at || task.created_at,
        sourceLabel: 'Background task',
        cta: 'Open tasks',
        color: STATE_META[taskState].color,
        onPress: () => navigation.navigate('AgentTasks'),
      });
    });

    missions.forEach((mission) => {
      const missionState = mapMissionState(mission.state);
      items.push({
        id: `mission-${mission.id}`,
        state: missionState,
        kind: 'mission',
        title: mission.title.replace(/^Agent:\s*/, ''),
        summary: mission.description || 'Agent work associated with Sara autonomy.',
        timestamp: mission.completed_at || mission.created_at,
        sourceLabel: mission.source || 'Mission',
        cta: 'Open tasks',
        color: STATE_META[missionState].color,
        onPress: () => navigation.navigate('AgentTasks'),
      });
    });

    notifications.forEach((item) => {
      const notificationState: ItemState = !item.read_at && !item.engaged ? 'new' : 'archived';

        items.push({
          id: `notification-${item.id}`,
          state: notificationState,
          kind: 'notification',
          title: item.title,
          summary: item.message || 'Sara sent a new update.',
          timestamp: item.created_at,
          sourceLabel: item.source || item.category || 'Notification',
          cta: notificationState === 'new' ? 'Chat with Sara' : 'Review notification',
          color: STATE_META[notificationState].color,
          onPress: () => {
            if (notificationState === 'new') {
              navigateToChat({
                notification: {
                  id: item.id,
                  title: item.title,
                  message: item.message || '',
                  category: item.category,
                  item_type: item.item_type,
                },
              });
              return;
            }
            navigation.navigate('Notifications');
          },
        });
    });

    inboxItems.forEach((item) => {
        const contentState = mapContentState(item.status);
        items.push({
          id: `content-${item.id}`,
          state: contentState,
          kind: 'content',
          title: item.title || 'Captured item',
          summary: item.description || item.original_url || 'New content waiting in your captured inbox.',
          timestamp: item.shared_at,
          sourceLabel: 'Captured content',
          cta: contentState === 'new' ? 'Open content' : 'Review content',
          color: STATE_META[contentState].color,
          onPress: () => navigation.navigate('Inbox', { tab: 'content' }),
        });
    });

    if (acsSnapshot?.live_session) {
      items.push({
        id: `acs-live-${acsSnapshot.live_session.id}`,
        state: 'in_progress',
        kind: 'acs',
        title: `ACS is active in ${acsSnapshot.live_session.mode}`,
        summary: `Live autonomy session with ${acsSnapshot.live_session.turns} turns over ${Math.round(acsSnapshot.live_session.elapsed_minutes)} minutes.`,
        timestamp: acsSnapshot.latest_note?.created_at || new Date().toISOString(),
        sourceLabel: 'ACS live',
        cta: 'Open ACS',
        color: STATE_META.in_progress.color,
        onPress: () => navigation.navigate('ACS'),
      });
    }

    if (acsSnapshot?.daily_plan) {
      items.push({
        id: 'acs-plan',
        state: 'in_progress',
        kind: 'acs',
        title: 'Today’s ACS plan',
        summary: acsSnapshot.daily_plan,
        timestamp: acsSnapshot.latest_note?.created_at || acsSnapshot.last_session?.ended_at || new Date().toISOString(),
        sourceLabel: 'ACS plan',
        cta: 'Open ACS',
        color: STATE_META.in_progress.color,
        onPress: () => navigation.navigate('ACS'),
      });
    }

    (acsSnapshot?.directives || []).forEach((directive) => {
      const directiveState = mapDirectiveState(directive.status);
      items.push({
        id: `acs-directive-${directive.id}`,
        state: directiveState,
        kind: 'acs',
        title: directive.content,
        summary: `${directive.directive_type} directive from ${directive.source || 'ACS'}.`,
        timestamp: directive.created_at,
        sourceLabel: 'ACS directive',
        cta: 'Open ACS',
        color: STATE_META[directiveState].color,
        onPress: () => navigation.navigate('ACS'),
      });
    });

    return items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [acsSnapshot, attentionItems, inboxItems, missions, navigation, notifications, tasks]);

  const groupedItems = useMemo<Record<ItemState, UnifiedItem[]>>(() => ({
    waiting: unifiedItems.filter((item) => item.state === 'waiting'),
    in_progress: unifiedItems.filter((item) => item.state === 'in_progress'),
    new: unifiedItems.filter((item) => item.state === 'new'),
    done: unifiedItems.filter((item) => item.state === 'done'),
    archived: unifiedItems.filter((item) => item.state === 'archived'),
  }), [unifiedItems]);

  const stateCounts = useMemo(() => ({
    waiting: groupedItems.waiting.length,
    in_progress: groupedItems.in_progress.length,
    new: groupedItems.new.length,
    done: groupedItems.done.length,
    archived: groupedItems.archived.length,
  }), [groupedItems]);

  const highlightedSections = useMemo(() => {
    const sectionOrder: ItemState[] = ['waiting', 'in_progress', 'new', 'done', 'archived'];

    if (focus !== 'all') {
      return [
        {
          state: focus,
          items: groupedItems[focus],
        },
      ];
    }

    return sectionOrder
      .filter((state) => state !== 'archived' || groupedItems.archived.length > 0)
      .map((state) => ({
      state,
      items: groupedItems[state].slice(0, state === 'archived' ? 3 : 4),
    }));
  }, [focus, groupedItems]);

  const introText = useMemo(() => {
    if (stateCounts.waiting > 0) {
      return `Sara has ${stateCounts.waiting} item${stateCounts.waiting === 1 ? '' : 's'} waiting on you right now.`;
    }
    if (stateCounts.in_progress > 0) {
      return `Sara is actively working on ${stateCounts.in_progress} background item${stateCounts.in_progress === 1 ? '' : 's'}.`;
    }
    if (stateCounts.new > 0) {
      return `${stateCounts.new} new signal${stateCounts.new === 1 ? '' : 's'} came in across captures and notifications.`;
    }
    return 'Everything is relatively calm. Use this screen to review assistant activity in one place.';
  }, [stateCounts]);

  if (loading) {
    return (
      <SafeAreaView style={styles.loadingContainer} edges={['bottom']}>
        <ActivityIndicator size="large" color={colors.primary} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
          />
        }
      >
        <View style={styles.hero}>
          <Text style={styles.eyebrow}>Assistant activity</Text>
          <Text style={styles.title}>Inbox</Text>
          <Text style={styles.subtitle}>{introText}</Text>
          <Text style={styles.helperText}>
            Captures, delegated work, and notifications are grouped by what you should do next.
          </Text>
        </View>

        <View style={styles.summaryGrid}>
          {(['waiting', 'in_progress', 'new', 'done', 'archived'] as ItemState[]).map((state) => {
            const meta = STATE_META[state];
            const isActive = focus === state;
            return (
              <TouchableOpacity
                key={state}
                style={[
                  styles.summaryCard,
                  { borderColor: meta.color + '30' },
                  isActive && { backgroundColor: meta.color + '18' },
                ]}
                onPress={() => setFocus((current) => (current === state ? 'all' : state))}
                activeOpacity={0.85}
              >
                <Text style={[styles.summaryLabel, { color: meta.color }]}>{meta.label}</Text>
                <Text style={styles.summaryCount}>{stateCounts[state]}</Text>
                <Text style={styles.summaryDescription}>{meta.description}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.filterRow}
        >
          {(['all', 'waiting', 'in_progress', 'new', 'done', 'archived'] as AssistantInboxFocus[]).map((option) => {
            const active = focus === option;
            const label = option === 'all' ? 'All activity' : STATE_META[option].label;
            return (
              <TouchableOpacity
                key={option}
                style={[styles.filterChip, active && styles.filterChipActive]}
                onPress={() => setFocus(option)}
              >
                <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>
                  {label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {highlightedSections.map(({ state, items }) => {
          const meta = STATE_META[state];
          return (
            <View key={state} style={styles.section}>
              <View style={styles.sectionHeader}>
                <View>
                  <Text style={styles.sectionTitle}>{meta.label}</Text>
                  <Text style={styles.sectionDescription}>{meta.description}</Text>
                </View>
                <View style={[styles.sectionCountPill, { backgroundColor: meta.color + '18' }]}>
                  <Text style={[styles.sectionCountText, { color: meta.color }]}>
                    {groupedItems[state].length}
                  </Text>
                </View>
              </View>

              {items.length > 0 ? (
                <View style={styles.sectionCard}>
                  {items.map((item, index) => (
                    <TouchableOpacity
                      key={item.id}
                      style={[
                        styles.activityRow,
                        index < items.length - 1 && styles.activityRowBorder,
                      ]}
                      onPress={() => {
                        assistantAnalytics.track('assistant.inbox_item_opened', {
                          kind: item.kind,
                          state: item.state,
                          source_label: item.sourceLabel,
                          cta: item.cta,
                        });
                        item.onPress();
                      }}
                      activeOpacity={0.8}
                    >
                      <View style={[styles.activityDot, { backgroundColor: item.color }]} />
                      <View style={styles.activityCopy}>
                        <View style={styles.activityMetaRow}>
                          <Text style={styles.kindLabel}>{KIND_LABELS[item.kind]}</Text>
                          <Text style={styles.metaSeparator}>•</Text>
                          <Text style={styles.sourceLabel}>{item.sourceLabel}</Text>
                          <Text style={styles.metaSeparator}>•</Text>
                          <Text style={styles.timeLabel}>{formatRelativeTime(item.timestamp)}</Text>
                        </View>
                        <Text style={styles.activityTitle} numberOfLines={2}>
                          {item.title}
                        </Text>
                        <Text style={styles.activitySummary} numberOfLines={2}>
                          {item.summary}
                        </Text>
                      </View>
                      <Text style={styles.ctaLabel}>{item.cta}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              ) : (
                <View style={styles.emptySection}>
                  <Text style={styles.emptySectionText}>Nothing here right now.</Text>
                </View>
              )}
            </View>
          );
        })}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Detailed feeds</Text>
          <Text style={styles.sectionDescription}>
            Open the older dedicated views when you want deeper controls or more context.
          </Text>

          <View style={styles.feedGrid}>
            {DETAIL_FEEDS.map((feed) => (
              <TouchableOpacity
                key={feed.key}
                style={styles.feedCard}
                onPress={() => {
                  assistantAnalytics.track('assistant.inbox_item_opened', {
                    kind: 'detail_feed',
                    state: focus,
                    source_label: feed.label,
                    cta: 'Open feed',
                  });
                  feed.onPress(navigation);
                }}
                activeOpacity={0.82}
              >
                <Text style={styles.feedLabel}>{feed.label}</Text>
                <Text style={styles.feedDescription}>{feed.description}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        <View style={styles.footerCard}>
          <Text style={styles.footerTitle}>Captured content</Text>
          <Text style={styles.footerDescription}>
            {contentUnread > 0
              ? `${contentUnread} unread capture${contentUnread === 1 ? '' : 's'} still waiting for review.`
              : 'No unread captures at the moment.'}
          </Text>
          <View style={styles.footerActions}>
            <TouchableOpacity
              style={styles.footerButton}
              onPress={() => {
                assistantAnalytics.track('assistant.inbox_item_opened', {
                  kind: 'content',
                  state: contentUnread > 0 ? 'new' : 'done',
                  source_label: 'Captured content',
                  cta: 'Open content inbox',
                });
                navigation.navigate('Inbox', { tab: 'content' });
              }}
            >
              <Text style={styles.footerButtonText}>Open content inbox</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.footerButton, styles.footerButtonSecondary]}
              onPress={() => {
                assistantAnalytics.track('assistant.inbox_item_opened', {
                  kind: 'assistant_sort',
                  state: focus,
                  source_label: 'Assistant inbox review',
                  cta: 'Ask Sara to sort it',
                });
                navigateToChat({
                  heartbeat: {
                    title: 'Assistant inbox review',
                    message: 'Help me review what matters most in my assistant inbox.',
                    priority: 'normal',
                  },
                });
              }}
            >
              <Text style={[styles.footerButtonText, styles.footerButtonTextSecondary]}>
                Ask Sara to sort it
              </Text>
            </TouchableOpacity>
          </View>
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
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  hero: {
    marginBottom: spacing.lg,
    padding: spacing.lg,
    borderRadius: borderRadius.xl,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    ...shadows.sm,
  },
  eyebrow: {
    color: colors.assistant.passive,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.xs,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  subtitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
    marginTop: spacing.sm,
  },
  helperText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.sm,
  },
  summaryGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  summaryCard: {
    width: '48%',
    minWidth: 150,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    ...shadows.sm,
  },
  summaryLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  summaryCount: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginTop: spacing.sm,
  },
  summaryDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  filterRow: {
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  filterChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    backgroundColor: colors.assistant.panelMuted,
  },
  filterChipActive: {
    borderColor: colors.assistant.borderStrong,
    backgroundColor: colors.assistant.actionSoft,
  },
  filterChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  filterChipTextActive: {
    color: colors.primary,
  },
  section: {
    marginTop: spacing.md,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
    gap: spacing.md,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  sectionDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: 2,
  },
  sectionCountPill: {
    minWidth: 34,
    height: 34,
    borderRadius: borderRadius.full,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
  },
  sectionCountText: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  sectionCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    overflow: 'hidden',
    ...shadows.sm,
  },
  activityRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
  },
  activityRowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
  },
  activityDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginTop: 6,
  },
  activityCopy: {
    flex: 1,
  },
  activityMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  kindLabel: {
    color: colors.assistant.passive,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  sourceLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  timeLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  metaSeparator: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  activityTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginTop: spacing.xs,
  },
  activitySummary: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  ctaLabel: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    marginTop: 2,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.actionSoft,
    overflow: 'hidden',
  },
  emptySection: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.lg,
  },
  emptySectionText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  feedGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  feedCard: {
    width: '48%',
    minWidth: 150,
    backgroundColor: colors.assistant.panelMuted,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
  },
  feedLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  feedDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  footerCard: {
    marginTop: spacing.lg,
    padding: spacing.lg,
    borderRadius: borderRadius.xl,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    ...shadows.sm,
  },
  footerTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  footerDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.sm,
  },
  footerActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  footerButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.primary,
  },
  footerButtonSecondary: {
    backgroundColor: colors.assistant.panelMuted,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  footerButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  footerButtonTextSecondary: {
    color: colors.assistant.passive,
  },
});

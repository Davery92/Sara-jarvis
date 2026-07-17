import React, { useState, useCallback } from 'react';
import {
  DeviceEventEmitter,
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  RefreshControl,
  ActivityIndicator,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import apiClient from '../../services/api';
import notesService from '../../services/notes';
import { navigateToChat, navigateToInbox, navigateToNoteEditor } from '../../services/navigation';
import { colors, spacing, borderRadius, fontSizes, shadows } from '../../styles/theme';

interface Notification {
  id: string;
  title: string;
  message: string;
  category: string;
  priority: string;
  source: string;
  topic?: string | null;
  item_type: string; // 'notification' | 'acs_discovery'
  created_at: string;
  read_at: string | null;
  dismissed_at: string | null;
  engaged: boolean;
  response_text: string | null;
}

const CATEGORY_META: Record<string, { emoji: string; label: string }> = {
  discovery: { emoji: '🔬', label: 'Discovery' },
  insight: { emoji: '💡', label: 'Insight' },
  acs_discovery: { emoji: '🔬', label: 'Discovery' },
  acs_request: { emoji: '🤔', label: 'Needs Help' },
  checkin: { emoji: '👋', label: 'Check-in' },
  health: { emoji: '❤️', label: 'Health' },
  fitness: { emoji: '💪', label: 'Fitness' },
  wellness: { emoji: '🧘', label: 'Wellness' },
  calendar: { emoji: '📅', label: 'Calendar' },
  schedule: { emoji: '📅', label: 'Schedule' },
  reminder: { emoji: '⏰', label: 'Reminder' },
  timer: { emoji: '⏱️', label: 'Timer' },
  home: { emoji: '🏠', label: 'Home' },
  security: { emoji: '🔒', label: 'Security' },
  email: { emoji: '📧', label: 'Email' },
  weather: { emoji: '🌤️', label: 'Weather' },
  general: { emoji: '💬', label: 'General' },
  learning: { emoji: '📚', label: 'Learning' },
  chat_response: { emoji: '💬', label: 'Chat' },
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: colors.error,
  urgent: colors.hues.orange,
  high: colors.warning,
  normal: colors.primary,
  low: colors.textMuted,
};

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDays = Math.floor(diffHr / 24);

  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatFullDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export default function NotificationsScreen() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [total, setTotal] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<string | null>(null);

  const loadNotifications = useCallback(async (filter?: string | null) => {
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (filter) params.append('category', filter);

      const data: any = await apiClient.get(`/api/notifications?${params}`);
      setNotifications(data.notifications || []);
      setTotal(data.total || 0);
    } catch (error) {
      console.error('Failed to load notifications:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      loadNotifications(activeFilter);
    }, [activeFilter])
  );

  const handleRefresh = () => {
    setRefreshing(true);
    loadNotifications(activeFilter);
  };

  const handleMarkAllSeen = async () => {
    const unreadNotifications = notifications.filter(
      (item) => !item.read_at && !item.engaged && !item.dismissed_at,
    );
    try {
      await apiClient.markAllNotificationsRead();
    } catch {
      try {
        await Promise.all(
          unreadNotifications.map((item) => apiClient.markNotificationRead(item.id, item.item_type)),
        );
      } catch {
        setRefreshing(false);
        return;
      }
    }
    setRefreshing(true);
    loadNotifications(activeFilter);
    DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
  };

  const handleTap = async (notification: Notification) => {
    const isExpanding = expandedId !== notification.id;
    setExpandedId(isExpanding ? notification.id : null);

    // Mark as read when expanding
    if (isExpanding && !notification.engaged) {
      try {
        await apiClient.markNotificationRead(notification.id, notification.item_type);
        setNotifications((prev) =>
          prev.map((n) =>
            n.id === notification.id ? { ...n, read_at: new Date().toISOString(), engaged: true } : n
          )
        );
        DeviceEventEmitter.emit('assistantInboxBadgeRefresh');
      } catch {}
    }
  };

  const handleChat = (notification: Notification) => {
    navigateToChat({
      notification: {
        id: notification.id,
        title: notification.title,
        message: notification.message || '',
        category: notification.category,
        item_type: notification.item_type,
      },
    });
  };

  const handleOpenFullReport = async (notification: Notification) => {
    try {
      const note = await notesService.findDailyReportNote({
        title: notification.title,
        topic: notification.topic,
      });
      if (note?.id) {
        navigateToNoteEditor(note.id);
      }
    } catch {}
  };

  // Build category counts from current data
  const categories = React.useMemo(() => {
    const counts: Record<string, number> = {};
    notifications.forEach((n) => {
      const key = n.category || 'general';
      counts[key] = (counts[key] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [notifications]);

  const unreadCount = React.useMemo(
    () => notifications.filter((item) => !item.read_at && !item.engaged && !item.dismissed_at).length,
    [notifications],
  );
  const discoveryCount = React.useMemo(
    () =>
      notifications.filter(
        (item) =>
          item.item_type === 'acs_discovery' ||
          item.category === 'acs_discovery' ||
          item.category === 'discovery',
      ).length,
    [notifications],
  );
  const repliedCount = React.useMemo(
    () => notifications.filter((item) => Boolean(item.response_text)).length,
    [notifications],
  );
  const heroSummary = React.useMemo(() => {
    if (activeFilter) {
      const meta = CATEGORY_META[activeFilter] || { label: activeFilter };
      return `Showing ${notifications.length} ${meta.label.toLowerCase()} notification${notifications.length === 1 ? '' : 's'} from your history.`;
    }
    if (unreadCount > 0) {
      return `${unreadCount} still feel fresh. Use Inbox to decide what needs action now, and use this screen when you want the full history.`;
    }
    return 'This is Sara’s notification history: nudges, alerts, and discoveries after they have already landed.';
  }, [activeFilter, notifications.length, unreadCount]);

  const renderNotification = ({ item }: { item: Notification }) => {
    const meta = CATEGORY_META[item.category] || { emoji: '🔔', label: item.category };
    const isUnread = !item.read_at && !item.engaged && !item.dismissed_at;
    const isExpanded = expandedId === item.id;
    const priorityColor = PRIORITY_COLORS[item.priority] || colors.textMuted;
    const isACS = item.item_type === 'acs_discovery';
    const isDailyReport = item.title.startsWith("Sara's Daily Report");

    return (
      <TouchableOpacity
        style={[
          styles.notificationCard,
          isUnread && styles.unreadCard,
          isExpanded && styles.expandedCard,
        ]}
        onPress={() => handleTap(item)}
        activeOpacity={0.7}
      >
        {/* Header row */}
        <View style={styles.cardHeader}>
          <View style={styles.categoryRow}>
            <Text style={styles.emoji}>{meta.emoji}</Text>
            <Text style={styles.categoryLabel}>{meta.label}</Text>
            {isACS && <View style={styles.acsBadge}><Text style={styles.acsBadgeText}>ACS</Text></View>}
            {isUnread && <View style={[styles.unreadDot, { backgroundColor: priorityColor }]} />}
          </View>
          <Text style={styles.time}>{formatTime(item.created_at)}</Text>
        </View>

        {/* Title */}
        <Text style={[styles.title, isUnread && styles.titleUnread]} numberOfLines={isExpanded ? undefined : 2}>
          {item.title}
        </Text>

        {/* Collapsed preview */}
        {!isExpanded && item.message ? (
          <Text style={styles.preview} numberOfLines={2}>
            {item.message}
          </Text>
        ) : null}

        {/* Expanded content */}
        {isExpanded && (
          <View style={styles.expandedContent}>
            {item.message ? (
              <ScrollView style={styles.messageScroll} nestedScrollEnabled>
                <Text style={styles.fullMessage}>{item.message}</Text>
              </ScrollView>
            ) : null}

            <Text style={styles.fullDate}>{formatFullDate(item.created_at)}</Text>

            <View style={styles.metaRow}>
              <View style={[styles.priorityBadge, { backgroundColor: priorityColor + '20' }]}>
                <Text style={[styles.priorityText, { color: priorityColor }]}>{item.priority}</Text>
              </View>
              <Text style={styles.sourceText}>{item.source}</Text>
            </View>

            {item.response_text ? (
              <View style={styles.replyContainer}>
                <Text style={styles.replyLabel}>Your reply:</Text>
                <Text style={styles.replyText}>{item.response_text}</Text>
              </View>
            ) : null}

            <View style={styles.actionRow}>
              {isDailyReport ? (
                <TouchableOpacity
                  style={[styles.chatButton, styles.reportButton]}
                  onPress={() => handleOpenFullReport(item)}
                >
                  <Text style={styles.reportButtonText}>Open Full Report</Text>
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity style={styles.chatButton} onPress={() => handleChat(item)}>
                <Text style={styles.chatButtonText}>Chat with Sara about this</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: 40 }} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.header}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>History</Text>
          <Text style={styles.headerTitle}>Notifications</Text>
          <Text style={styles.headerSubtitle}>{heroSummary}</Text>

          <View style={styles.heroStatsRow}>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Fresh</Text>
              <Text style={styles.heroStatValue}>{unreadCount}</Text>
              <Text style={styles.heroStatMeta}>not yet reviewed</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Discoveries</Text>
              <Text style={styles.heroStatValue}>{discoveryCount}</Text>
              <Text style={styles.heroStatMeta}>ACS or surfaced signals</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Replies</Text>
              <Text style={styles.heroStatValue}>{repliedCount}</Text>
              <Text style={styles.heroStatMeta}>with your response</Text>
            </View>
          </View>

          <View style={styles.heroActions}>
            <TouchableOpacity
              style={styles.headerButton}
              onPress={() => navigateToInbox({ focus: 'new' })}
            >
              <Text style={styles.headerButtonText}>Open Inbox</Text>
            </TouchableOpacity>
            {unreadCount > 0 ? (
              <TouchableOpacity
                style={[styles.headerButton, styles.headerButtonSecondary]}
                onPress={handleMarkAllSeen}
              >
                <Text style={[styles.headerButtonText, styles.headerButtonTextSecondary]}>
                  Mark All Seen
                </Text>
              </TouchableOpacity>
            ) : null}
            {activeFilter ? (
              <TouchableOpacity
                style={[styles.headerButton, styles.headerButtonSecondary]}
                onPress={() => {
                  setActiveFilter(null);
                  setExpandedId(null);
                  setLoading(true);
                  loadNotifications(null);
                }}
              >
                <Text style={[styles.headerButtonText, styles.headerButtonTextSecondary]}>Clear Filter</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>
      </View>

      {/* Filter chips */}
      <FlatList
        horizontal
        data={[['all', total] as [string, number], ...categories]}
        keyExtractor={(item) => item[0]}
        showsHorizontalScrollIndicator={false}
        style={styles.filterList}
        contentContainerStyle={styles.filterContent}
        renderItem={({ item: [cat, count] }) => {
          const isActive = cat === 'all' ? !activeFilter : activeFilter === cat;
          const meta = CATEGORY_META[cat] || { emoji: '🔔', label: cat };
          return (
            <TouchableOpacity
              style={[styles.filterChip, isActive && styles.filterChipActive]}
              onPress={() => {
                const newFilter = cat === 'all' ? null : cat;
                setActiveFilter(newFilter);
                setExpandedId(null);
                setLoading(true);
                loadNotifications(newFilter);
              }}
            >
              <Text style={[styles.filterChipText, isActive && styles.filterChipTextActive]}>
                {cat === 'all' ? `All (${count})` : `${meta.emoji} ${meta.label} (${count})`}
              </Text>
            </TouchableOpacity>
          );
        }}
      />

      <FlatList
        data={notifications}
        keyExtractor={(item) => item.id}
        renderItem={renderNotification}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyEmoji}>🔔</Text>
            <Text style={styles.emptyText}>No notifications</Text>
            <Text style={styles.emptySubtext}>Sara's messages and discoveries will appear here</Text>
          </View>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  heroCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    padding: spacing.lg,
    ...shadows.sm,
  },
  heroEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  headerTitle: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  headerSubtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  heroStatsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
    flexWrap: 'wrap',
  },
  heroStatCard: {
    flex: 1,
    minWidth: 96,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
    gap: 2,
  },
  heroStatLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  heroStatValue: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  heroStatMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 16,
  },
  heroActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  headerButton: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
  },
  headerButtonSecondary: {
    backgroundColor: colors.assistant.panelRaised,
    borderColor: colors.assistant.border,
  },
  headerButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  headerButtonTextSecondary: {
    color: colors.textSecondary,
  },
  filterList: {
    flexGrow: 0,
    minHeight: 60,
  },
  filterContent: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    gap: spacing.sm,
    alignItems: 'center',
  },
  filterChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surface,
    marginRight: spacing.sm,
  },
  filterChipActive: {
    backgroundColor: colors.primary,
  },
  filterChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  filterChipTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xl,
  },
  notificationCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  unreadCard: {
    borderColor: colors.assistant.borderStrong,
  },
  expandedCard: {
    borderColor: colors.primary,
    borderWidth: 1,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  categoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  emoji: {
    fontSize: fontSizes.md,
  },
  categoryLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '700',
  },
  acsBadge: {
    backgroundColor: colors.secondary + '30',
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: borderRadius.sm,
  },
  acsBadgeText: {
    color: colors.secondary,
    fontSize: 10,
    fontWeight: '700',
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginLeft: spacing.xs,
  },
  time: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  title: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    marginBottom: spacing.xs,
  },
  titleUnread: {
    color: colors.text,
    fontWeight: '600',
  },
  preview: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    lineHeight: 18,
  },
  expandedContent: {
    marginTop: spacing.sm,
  },
  messageScroll: {
    maxHeight: 400,
    marginBottom: spacing.sm,
  },
  fullMessage: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 22,
  },
  fullDate: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: spacing.sm,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  priorityBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  priorityText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  sourceText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  replyContainer: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  replyLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: 2,
  },
  replyText: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  chatButton: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm + 2,
    alignItems: 'center',
  },
  reportButton: {
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
  },
  chatButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  reportButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  emptyContainer: {
    alignItems: 'center',
    paddingTop: 80,
  },
  emptyEmoji: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyText: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  emptySubtext: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
});

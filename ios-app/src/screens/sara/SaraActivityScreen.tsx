import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SimpleMarkdown from '../../components/chat/SimpleMarkdown';

type TabType = 'activity' | 'attention' | 'missions';
type FilterType = 'all' | 'heartbeat' | 'notification' | 'journal';

const ACTIVITY_ICONS: Record<string, string> = {
  heartbeat: '\uD83E\uDDE0',
  notification: '\uD83D\uDD14',
  journal: '\uD83D\uDCD6',
  observation: '\uD83D\uDC41',
  action: '\u26A1',
  sweep: '\uD83D\uDD0D',
};

const TYPE_COLORS: Record<string, string> = {
  heartbeat: colors.info,
  notification: colors.warning,
  journal: colors.success,
  observation: colors.accent,
  action: colors.primary,
};

function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')   // **bold**
    .replace(/\*(.+?)\*/g, '$1')       // *italic*
    .replace(/__(.+?)__/g, '$1')       // __bold__
    .replace(/_(.+?)_/g, '$1')         // _italic_
    .replace(/`(.+?)`/g, '$1')         // `code`
    .replace(/^#{1,3}\s+/gm, '')       // headers
    .replace(/^[-*]\s+/gm, '• ')       // list items
    .replace(/^\d+\.\s+/gm, '')        // numbered lists
    .trim();
}

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export default function SaraActivityScreen() {
  const [tab, setTab] = useState<TabType>('activity');
  const [activities, setActivities] = useState<any[]>([]);
  const [attentionItems, setAttentionItems] = useState<any[]>([]);
  const [missions, setMissions] = useState<any[]>([]);
  const [attentionCount, setAttentionCount] = useState(0);
  const [filter, setFilter] = useState<FilterType>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadActivities = useCallback(async () => {
    try {
      const data = await apiClient.get('/api/sara/activity?hours=24&limit=50');
      const items = Array.isArray(data) ? data : (data as any)?.activities || [];
      setActivities(items);
    } catch {
      setActivities([]);
    }
  }, []);

  const loadAttention = useCallback(async () => {
    try {
      const data = await apiClient.get('/autonomy/attention?limit=50');
      setAttentionItems((data as any)?.items || []);
    } catch { setAttentionItems([]); }
  }, []);

  const loadMissions = useCallback(async () => {
    try {
      const data = await apiClient.get('/autonomy/missions');
      setMissions((data as any)?.missions || []);
    } catch { setMissions([]); }
  }, []);

  const loadAttentionCount = useCallback(async () => {
    try {
      const data = await apiClient.get('/autonomy/attention/count');
      setAttentionCount((data as any)?.unread || 0);
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => {
    loadActivities();
    loadAttentionCount();
  }, [loadActivities, loadAttentionCount]);

  useEffect(() => {
    if (tab === 'attention') loadAttention();
    if (tab === 'missions') loadMissions();
  }, [tab, loadAttention, loadMissions]);

  const handleRefresh = async () => {
    setRefreshing(true);
    if (tab === 'activity') await loadActivities();
    else if (tab === 'attention') { await loadAttention(); await loadAttentionCount(); }
    else if (tab === 'missions') await loadMissions();
    setRefreshing(false);
  };

  const markAttentionRead = async (id: string) => {
    try {
      await apiClient.post(`/autonomy/attention/${id}/read`);
      loadAttention();
      loadAttentionCount();
    } catch { /* best-effort */ }
  };

  const archiveAttention = async (id: string) => {
    try {
      await apiClient.post(`/autonomy/attention/${id}/archive`);
      loadAttention();
      loadAttentionCount();
    } catch { /* best-effort */ }
  };

  const filteredActivities = filter === 'all'
    ? activities
    : activities.filter(a => a.type === filter);

  const filters: { key: FilterType; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'heartbeat', label: 'Heartbeat' },
    { key: 'notification', label: 'Notifications' },
    { key: 'journal', label: 'Journal' },
  ];

  const renderItem = ({ item }: { item: any }) => {
    const isExpanded = expandedId === (item.id || item.timestamp);
    const icon = ACTIVITY_ICONS[item.type] || '\u2022';
    const typeColor = TYPE_COLORS[item.type] || colors.textMuted;

    return (
      <TouchableOpacity
        style={styles.activityItem}
        onPress={() => setExpandedId(isExpanded ? null : (item.id || item.timestamp))}
        activeOpacity={0.7}
      >
        <View style={styles.itemRow}>
          <Text style={styles.itemIcon}>{icon}</Text>
          <View style={styles.itemContent}>
            <View style={styles.itemHeader}>
              <View style={[styles.typeBadge, { backgroundColor: typeColor + '20' }]}>
                <Text style={[styles.typeBadgeText, { color: typeColor }]}>{item.type}</Text>
              </View>
              <Text style={styles.itemTime}>
                {item.timestamp ? formatTime(item.timestamp) : ''}
              </Text>
            </View>
            <Text style={styles.itemSummary} numberOfLines={isExpanded ? undefined : 2}>
              {stripMarkdown(item.summary || item.description || item.type)}
            </Text>
          </View>
          <Text style={styles.timeAgo}>
            {item.timestamp ? timeAgo(item.timestamp) : ''}
          </Text>
        </View>
        {isExpanded && item.details && (
          <View style={styles.expandedDetail}>
            <SimpleMarkdown style={styles.detailText}>
              {typeof item.details === 'string'
                ? item.details
                : item.details.full_content
                  || item.details.message
                  || item.details.observations
                  || JSON.stringify(item.details, null, 2)}
            </SimpleMarkdown>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  const tabs: { key: TabType; label: string; badge?: number }[] = [
    { key: 'activity', label: 'Activity' },
    { key: 'attention', label: 'Attention', badge: attentionCount },
    { key: 'missions', label: 'Missions' },
  ];

  const renderAttentionItem = ({ item }: { item: any }) => {
    const priorityColor = item.priority === 'critical' ? '#ef4444'
      : item.priority === 'urgent' ? '#f97316'
      : item.priority === 'high' ? '#eab308'
      : colors.textMuted;
    return (
      <View style={styles.activityItem}>
        <View style={styles.itemRow}>
          <View style={[styles.typeBadge, { backgroundColor: priorityColor + '20' }]}>
            <Text style={[styles.typeBadgeText, { color: priorityColor }]}>{item.priority}</Text>
          </View>
          <View style={styles.itemContent}>
            <Text style={styles.itemSummary} numberOfLines={2}>{item.title}</Text>
            {item.body && <Text style={styles.detailText} numberOfLines={2}>{item.body}</Text>}
          </View>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {item.status === 'new' && (
              <TouchableOpacity onPress={() => markAttentionRead(item.id)}>
                <Text style={{ color: colors.primary, fontSize: fontSizes.xs }}>Read</Text>
              </TouchableOpacity>
            )}
            <TouchableOpacity onPress={() => archiveAttention(item.id)}>
              <Text style={{ color: colors.textMuted, fontSize: fontSizes.xs }}>Archive</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    );
  };

  const renderMissionItem = ({ item }: { item: any }) => {
    const stateColor = item.state === 'done' ? colors.success
      : item.state === 'running' ? colors.info
      : item.state === 'failed' ? '#ef4444'
      : colors.textMuted;
    const progress = item.total_steps > 0 ? (item.completed_steps / item.total_steps) : 0;
    return (
      <View style={styles.activityItem}>
        <View style={styles.itemHeader}>
          <View style={[styles.typeBadge, { backgroundColor: stateColor + '20' }]}>
            <Text style={[styles.typeBadgeText, { color: stateColor }]}>{item.state}</Text>
          </View>
          <Text style={styles.itemTime}>{item.source}</Text>
        </View>
        <Text style={styles.itemSummary}>{item.title}</Text>
        {item.total_steps > 0 && (
          <View style={{ marginTop: 8 }}>
            <Text style={styles.detailText}>{item.completed_steps}/{item.total_steps} steps ({Math.round(progress * 100)}%)</Text>
            <View style={{ height: 4, backgroundColor: colors.border, borderRadius: 2, marginTop: 4 }}>
              <View style={{ height: 4, backgroundColor: stateColor, borderRadius: 2, width: `${progress * 100}%` as any }} />
            </View>
          </View>
        )}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Tab Bar */}
      <View style={styles.filterBar}>
        {tabs.map(t => (
          <TouchableOpacity
            key={t.key}
            style={[styles.filterChip, tab === t.key && styles.filterChipActive]}
            onPress={() => setTab(t.key)}
          >
            <Text style={[styles.filterText, tab === t.key && styles.filterTextActive]}>
              {t.label}{t.badge ? ` (${t.badge})` : ''}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === 'activity' && (
        <>
          {/* Activity Filter Bar */}
          <View style={styles.filterBar}>
            {filters.map(f => (
              <TouchableOpacity
                key={f.key}
                style={[styles.filterChip, filter === f.key && styles.filterChipActive]}
                onPress={() => setFilter(f.key)}
              >
                <Text style={[styles.filterText, filter === f.key && styles.filterTextActive]}>
                  {f.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <FlatList
            data={filteredActivities}
            renderItem={renderItem}
            keyExtractor={(item, i) => item.id || `${item.timestamp}-${i}`}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
            }
            contentContainerStyle={styles.listContent}
            ListEmptyComponent={
              <View style={styles.emptyContainer}>
                <Text style={styles.emptyText}>
                  {filter === 'all' ? 'No recent activity' : `No ${filter} activity`}
                </Text>
              </View>
            }
          />
        </>
      )}

      {tab === 'attention' && (
        <FlatList
          data={attentionItems}
          renderItem={renderAttentionItem}
          keyExtractor={(item) => item.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
          }
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>No attention items</Text>
            </View>
          }
        />
      )}

      {tab === 'missions' && (
        <FlatList
          data={missions}
          renderItem={renderMissionItem}
          keyExtractor={(item) => item.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
          }
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>No missions</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  filterBar: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  filterChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
  },
  filterChipActive: {
    backgroundColor: colors.primary,
  },
  filterText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  filterTextActive: {
    color: colors.text,
  },
  listContent: {
    padding: spacing.md,
    gap: spacing.sm,
  },
  activityItem: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  itemRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  itemIcon: {
    fontSize: 20,
    marginTop: 2,
  },
  itemContent: {
    flex: 1,
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: 4,
  },
  typeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  typeBadgeText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  itemTime: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  itemSummary: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  timeAgo: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  expandedDetail: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  detailText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  detailActions: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    marginTop: 4,
  },
  detailMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  emptyContainer: {
    padding: spacing.xxl,
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
  },
});

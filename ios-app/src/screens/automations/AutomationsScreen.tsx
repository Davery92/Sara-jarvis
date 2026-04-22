import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import { colors, spacing, borderRadius, fontSizes, shadows } from '../../styles/theme';

// --- Types ---

interface AutomationTask {
  id: string;
  name: string;
  description: string | null;
  status: string;
  execution_count: number;
  next_wake_at: string | null;
  created_at: string;
}

interface AutomationStats {
  total: number;
  active: number;
  executions_24h: number;
}

interface StandingOrder {
  id: string;
  description: string;
  trigger_type: string;
  status: string;
  execution_count: number;
  last_executed_at: string | null;
  created_at: string;
}

type TabType = 'automations' | 'standing_orders';

// --- Helpers ---

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '--';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = date.getTime() - now.getTime();
  const absDiffMs = Math.abs(diffMs);
  const isPast = diffMs < 0;

  const minutes = Math.floor(absDiffMs / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  let label: string;
  if (minutes < 1) {
    label = 'just now';
    return label;
  } else if (minutes < 60) {
    label = `${minutes}m`;
  } else if (hours < 24) {
    label = `${hours}h ${minutes % 60}m`;
  } else {
    label = `${days}d`;
  }

  return isPast ? `${label} ago` : `in ${label}`;
}

function getStatusColor(status: string): string {
  switch (status.toLowerCase()) {
    case 'active':
    case 'running':
      return colors.success;
    case 'paused':
    case 'suspended':
      return colors.warning;
    case 'failed':
    case 'error':
      return colors.error;
    default:
      return colors.textMuted;
  }
}

function getTriggerColor(triggerType: string): string {
  switch (triggerType.toLowerCase()) {
    case 'event':
      return colors.info;
    case 'schedule':
    case 'cron':
      return colors.accent;
    case 'pattern':
      return colors.secondary;
    default:
      return colors.textMuted;
  }
}

// --- Component ---

export default function AutomationsScreen() {
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState<TabType>('automations');
  const [tasks, setTasks] = useState<AutomationTask[]>([]);
  const [stats, setStats] = useState<AutomationStats | null>(null);
  const [orders, setOrders] = useState<StandingOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAutomations = useCallback(async () => {
    try {
      const [tasksRes, statsRes] = await Promise.all([
        apiClient.get<any>('/api/automation/tasks'),
        apiClient.get<any>('/api/automation/stats'),
      ]);
      setTasks(tasksRes?.tasks ?? (Array.isArray(tasksRes) ? tasksRes : []));
      setStats(statsRes ?? null);
    } catch (err: any) {
      showToast('error', err?.message || 'Failed to load automations');
    }
  }, []);

  const fetchStandingOrders = useCallback(async () => {
    try {
      const res = await apiClient.get<any>('/api/standing-orders');
      setOrders(res?.orders ?? (Array.isArray(res) ? res : []));
    } catch (err: any) {
      showToast('error', err?.message || 'Failed to load standing orders');
    }
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    // Fetch both tabs in parallel so data is ready when user switches
    await Promise.allSettled([fetchAutomations(), fetchStandingOrders()]);
    setLoading(false);
  }, [fetchAutomations, fetchStandingOrders]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.allSettled([fetchAutomations(), fetchStandingOrders()]);
    setRefreshing(false);
  }, [fetchAutomations, fetchStandingOrders]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const activeAutomationCount = useMemo(() => {
    if (stats?.active != null) return stats.active;
    return tasks.filter((task) => ['active', 'running'].includes(task.status.toLowerCase())).length;
  }, [stats, tasks]);
  const standingOrderCount = useMemo(() => orders.length, [orders]);
  const heroSummary = useMemo(() => {
    if (activeAutomationCount > 0) {
      return `${activeAutomationCount} automation${activeAutomationCount === 1 ? '' : 's'} are active right now. Use this screen to pause, resume, and inspect background routines.`;
    }
    if (standingOrderCount > 0) {
      return `${standingOrderCount} standing order${standingOrderCount === 1 ? '' : 's'} are configured, but nothing is actively running right now.`;
    }
    return 'Recurring assistant routines and standing orders live here once Sara starts automating work for you.';
  }, [activeAutomationCount, standingOrderCount]);

  const handleTaskAction = useCallback(
    (task: AutomationTask) => {
      const isPaused = task.status.toLowerCase() === 'paused';
      Alert.alert(task.name, task.description || 'No description', [
        {
          text: isPaused ? 'Resume' : 'Pause',
          onPress: async () => {
            try {
              const endpoint = isPaused
                ? `/api/automation/tasks/${task.id}/resume`
                : `/api/automation/tasks/${task.id}/pause`;
              await apiClient.post(endpoint);
              await fetchAutomations();
            } catch (err: any) {
              showToast('error', err?.message || 'Action failed');
            }
          },
        },
        {
          text: 'Cancel Task',
          style: 'destructive',
          onPress: () => {
            Alert.alert(
              'Cancel Task',
              `Are you sure you want to cancel "${task.name}"?`,
              [
                { text: 'No', style: 'cancel' },
                {
                  text: 'Yes, Cancel',
                  style: 'destructive',
                  onPress: async () => {
                    try {
                      await apiClient.post(`/api/automation/tasks/${task.id}/pause`);
                      await fetchAutomations();
                    } catch (err: any) {
                      showToast('error', err?.message || 'Cancel failed');
                    }
                  },
                },
              ],
            );
          },
        },
        { text: 'Dismiss', style: 'cancel' },
      ]);
    },
    [fetchAutomations],
  );

  // --- Renderers ---

  const renderStatsBar = () => {
    if (!stats) return null;
    return (
      <View style={styles.statsBar}>
        <View style={styles.statItem}>
          <Text style={styles.statValue}>{stats.total}</Text>
          <Text style={styles.statLabel}>Total</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={[styles.statValue, { color: colors.success }]}>
            {stats.active}
          </Text>
          <Text style={styles.statLabel}>Active</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={[styles.statValue, { color: colors.info }]}>
            {stats.executions_24h}
          </Text>
          <Text style={styles.statLabel}>Runs (24h)</Text>
        </View>
      </View>
    );
  };

  const renderTaskItem = ({ item }: { item: AutomationTask }) => {
    const statusColor = getStatusColor(item.status);
    return (
      <TouchableOpacity
        style={styles.card}
        onPress={() => handleTaskAction(item)}
        activeOpacity={0.7}
      >
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            {item.name}
          </Text>
          <View style={[styles.badge, { backgroundColor: statusColor + '22' }]}>
            <Text style={[styles.badgeText, { color: statusColor }]}>
              {item.status}
            </Text>
          </View>
        </View>
        {item.description ? (
          <Text style={styles.cardDescription} numberOfLines={1}>
            {item.description}
          </Text>
        ) : null}
        <View style={styles.cardFooter}>
          <Text style={styles.cardMeta}>
            {item.execution_count} runs
          </Text>
          <Text style={styles.cardMeta}>
            Next: {formatRelativeTime(item.next_wake_at)}
          </Text>
        </View>
      </TouchableOpacity>
    );
  };

  const renderOrderItem = ({ item }: { item: StandingOrder }) => {
    const statusColor = getStatusColor(item.status);
    const triggerColor = getTriggerColor(item.trigger_type);
    return (
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={[styles.badge, { backgroundColor: triggerColor + '22' }]}>
            <Text style={[styles.badgeText, { color: triggerColor }]}>
              {item.trigger_type}
            </Text>
          </View>
          <View style={[styles.badge, { backgroundColor: statusColor + '22' }]}>
            <Text style={[styles.badgeText, { color: statusColor }]}>
              {item.status}
            </Text>
          </View>
        </View>
        <Text style={styles.cardDescription} numberOfLines={2}>
          {item.description}
        </Text>
        <View style={styles.cardFooter}>
          <Text style={styles.cardMeta}>
            {item.execution_count} runs
          </Text>
          <Text style={styles.cardMeta}>
            Last: {formatRelativeTime(item.last_executed_at)}
          </Text>
        </View>
      </View>
    );
  };

  const renderEmpty = () => {
    if (loading) return null;
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>
          {activeTab === 'automations'
            ? 'No automations found'
            : 'No standing orders found'}
        </Text>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.header}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Recurring Work</Text>
          <Text style={styles.heroTitle}>Automations</Text>
          <Text style={styles.heroSubtitle}>{heroSummary}</Text>

          <View style={styles.heroStatsRow}>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Active</Text>
              <Text style={styles.heroStatValue}>{activeAutomationCount}</Text>
              <Text style={styles.heroStatMeta}>running now</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Runs</Text>
              <Text style={styles.heroStatValue}>{stats?.executions_24h ?? 0}</Text>
              <Text style={styles.heroStatMeta}>last 24 hours</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Standing</Text>
              <Text style={styles.heroStatValue}>{standingOrderCount}</Text>
              <Text style={styles.heroStatMeta}>long-lived instructions</Text>
            </View>
          </View>
        </View>
      </View>

      <View style={styles.tabBar}>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'automations' && styles.tabActive]}
          onPress={() => setActiveTab('automations')}
        >
          <Text
            style={[
              styles.tabText,
              activeTab === 'automations' && styles.tabTextActive,
            ]}
          >
            Automations
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[
            styles.tab,
            activeTab === 'standing_orders' && styles.tabActive,
          ]}
          onPress={() => setActiveTab('standing_orders')}
        >
          <Text
            style={[
              styles.tabText,
              activeTab === 'standing_orders' && styles.tabTextActive,
            ]}
          >
            Standing Orders
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      {loading && !refreshing ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : activeTab === 'automations' ? (
        <FlatList
          data={tasks}
          keyExtractor={(item) => item.id}
          renderItem={renderTaskItem}
          ListHeaderComponent={renderStatsBar}
          ListEmptyComponent={renderEmpty}
          contentContainerStyle={styles.listContent}
          onRefresh={onRefresh}
          refreshing={refreshing}
        />
      ) : (
        <FlatList
          data={orders}
          keyExtractor={(item) => String(item.id)}
          renderItem={renderOrderItem}
          ListEmptyComponent={renderEmpty}
          contentContainerStyle={styles.listContent}
          onRefresh={onRefresh}
          refreshing={refreshing}
        />
      )}
    </SafeAreaView>
  );
}

// --- Styles ---

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
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.xs,
  },
  heroTitle: {
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    color: colors.text,
  },
  heroSubtitle: {
    marginTop: spacing.xs,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  heroStatsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  heroStatCard: {
    flex: 1,
    minWidth: 96,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
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
    marginTop: 2,
  },
  heroStatMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 16,
    marginTop: 2,
  },
  tabBar: {
    flexDirection: 'row',
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    padding: spacing.xs,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm + 2,
    alignItems: 'center',
    borderRadius: borderRadius.lg,
  },
  tabActive: {
    backgroundColor: colors.assistant.actionSoft,
  },
  tabText: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  tabTextActive: {
    color: colors.primary,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xl,
  },
  statsBar: {
    flexDirection: 'row',
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.lg,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    justifyContent: 'space-around',
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  statItem: {
    alignItems: 'center',
  },
  statValue: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
  },
  statLabel: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  statDivider: {
    width: 1,
    height: 28,
    backgroundColor: colors.assistant.border,
  },
  card: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    ...shadows.sm,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  cardTitle: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    flex: 1,
    marginRight: spacing.sm,
  },
  cardDescription: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  cardMeta: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.full,
  },
  badgeText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  emptyContainer: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
});

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  RefreshControl,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import apiClient from '../../services/api';
import { navigateToChat } from '../../services/navigation';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SimpleMarkdown from '../../components/chat/SimpleMarkdown';

type TabType = 'mind' | 'activity' | 'attention' | 'missions';
type FilterType = 'all' | 'heartbeat' | 'notification' | 'journal';

interface WorkingMemoryData {
  activity_state?: string;
  room?: string;
  interruptibility?: number;
  mood?: string;
  sara_focus?: string;
  sara_emotional_tone?: string;
  sara_curiosities?: string;
  sara_deliberation_count_today?: number;
  observation_count?: number;
  salience_high_water?: number;
  last_heartbeat_watching_for?: string;
  quiet_mode?: boolean;
  hours_since_last_chat?: number;
  next_event_title?: string;
  next_event_minutes_away?: number;
  notifications_sent_today?: number;
  error?: string;
}

interface DeliberationEntry {
  source: string;
  thought: string | null;
  handoff_note: string | null;
  watching_for: string | null;
  actions_taken: any;
  duration_seconds: number | null;
  run_at: string | null;
  created_at: string | null;
}

interface ObservationEntry {
  id: string;
  timestamp: string;
  source: string;
  description: string;
  salience: number;
  category: string;
}

interface AttentionAction {
  id: string;
  label: string;
  kind: string;
  target?: string;
  prompt?: string;
  url?: string;
  default_minutes?: number;
}

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
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/^#{1,3}\s+/gm, '')
    .replace(/^[-*]\s+/gm, '\u2022 ')
    .replace(/^\d+\.\s+/gm, '')
    .trim();
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
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

function formatActions(actions: any): string[] {
  if (!actions) return [];
  if (typeof actions === 'string') {
    try {
      const parsed = JSON.parse(actions);
      if (Array.isArray(parsed)) return parsed.map(String);
      return [actions];
    } catch {
      return actions.split(',').map((s: string) => s.trim()).filter(Boolean);
    }
  }
  if (Array.isArray(actions)) return actions.map(String);
  return [];
}

function emotionColor(tone: string | undefined): string {
  if (!tone) return colors.textMuted;
  const lower = tone.toLowerCase();
  if (lower.includes('calm') || lower.includes('content')) return colors.success;
  if (lower.includes('curious') || lower.includes('engaged')) return colors.info;
  if (lower.includes('concern') || lower.includes('worry')) return colors.warning;
  if (lower.includes('warm') || lower.includes('caring')) return colors.hues.rose;
  if (lower.includes('focused')) return colors.secondary;
  return colors.accent;
}

function salienceColor(salience: number): string {
  if (salience >= 0.8) return colors.error;
  if (salience >= 0.5) return colors.hues.amber;
  if (salience >= 0.3) return colors.info;
  return colors.textMuted;
}

export default function SaraActivityScreen() {
  const navigation = useNavigation<any>();
  const [tab, setTab] = useState<TabType>('mind');
  const [activities, setActivities] = useState<any[]>([]);
  const [attentionItems, setAttentionItems] = useState<any[]>([]);
  const [missions, setMissions] = useState<any[]>([]);
  const [attentionCount, setAttentionCount] = useState(0);
  const [filter, setFilter] = useState<FilterType>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Mind tab data
  const [workingMemory, setWorkingMemory] = useState<WorkingMemoryData | null>(null);
  const [deliberations, setDeliberations] = useState<DeliberationEntry[]>([]);
  const [observations, setObservations] = useState<ObservationEntry[]>([]);
  const [accumulatedSalience, setAccumulatedSalience] = useState(0);
  const [expandedThoughtIdx, setExpandedThoughtIdx] = useState<number | null>(null);
  const [attentionActionBusy, setAttentionActionBusy] = useState<string | null>(null);

  const loadMindData = useCallback(async () => {
    try {
      const [memData, delibData, obsData] = await Promise.all([
        apiClient.get('/autonomy/working-memory').catch(() => null),
        apiClient.get('/autonomy/deliberation-history?hours=24&limit=10').catch(() => ({ entries: [] })),
        apiClient.get('/autonomy/observations?limit=10').catch(() => ({ observations: [], accumulated_salience: 0 })),
      ]);
      if (memData && !(memData as any).error) setWorkingMemory(memData as WorkingMemoryData);
      setDeliberations((delibData as any)?.entries || []);
      setObservations((obsData as any)?.observations || []);
      setAccumulatedSalience((obsData as any)?.accumulated_salience || 0);
    } catch {
      // best-effort
    }
  }, []);

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
    loadMindData();
    loadAttentionCount();
    // Auto-refresh mind data every 30s
    const interval = setInterval(loadMindData, 30000);
    return () => clearInterval(interval);
  }, [loadMindData, loadAttentionCount]);

  useEffect(() => {
    if (tab === 'activity') loadActivities();
    if (tab === 'attention') loadAttention();
    if (tab === 'missions') loadMissions();
  }, [tab, loadActivities, loadAttention, loadMissions]);

  const handleRefresh = async () => {
    setRefreshing(true);
    if (tab === 'mind') await loadMindData();
    else if (tab === 'activity') await loadActivities();
    else if (tab === 'attention') { await loadAttention(); await loadAttentionCount(); }
    else if (tab === 'missions') await loadMissions();
    setRefreshing(false);
  };

  const markAttentionRead = async (id: string) => {
    try {
      await apiClient.markAttentionRead(id);
      loadAttention();
      loadAttentionCount();
    } catch { /* best-effort */ }
  };

  const markAttentionEngaged = async (id: string) => {
    try {
      await apiClient.engageAttentionItem(id);
      loadAttentionCount();
    } catch { /* best-effort */ }
  };

  const archiveAttention = async (id: string) => {
    try {
      await apiClient.archiveAttentionItem(id);
      loadAttention();
      loadAttentionCount();
    } catch { /* best-effort */ }
  };

  const getAttentionActions = (item: any): AttentionAction[] => {
    const actions = item?.payload?.actions;
    if (!Array.isArray(actions)) return [];
    return actions.filter((action): action is AttentionAction =>
      !!action &&
      typeof action.id === 'string' &&
      typeof action.label === 'string' &&
      typeof action.kind === 'string'
    );
  };

  const handleAttentionDirective = (directive?: { type?: string; target?: string; prompt?: string; url?: string }) => {
    if (!directive?.type) return;
    if (directive.type === 'navigate') {
      const target = (directive.target || '').toLowerCase();
      if (target === 'calendar') {
        navigation.navigate('Calendar');
      } else if (target === 'inbox') {
        navigation.navigate('AssistantInbox');
      } else {
        navigation.navigate('AssistantInbox', { focus: 'waiting' });
      }
      return;
    }

    if (directive.type === 'open_url' && directive.url) {
      const { Linking } = require('react-native');
      Linking.openURL(directive.url).catch(() => {
        Alert.alert('Error', 'Failed to open URL');
      });
      return;
    }

    if (directive.type === 'chat') {
      navigateToChat({
        heartbeat: {
          title: 'Attention item',
          message: directive.prompt || 'Help me handle this.',
          priority: 'normal',
        },
      });
    }
  };

  const runAttentionAction = async (itemId: string, action: AttentionAction, params?: Record<string, any>) => {
    const busyKey = `${itemId}:${action.id}`;
    setAttentionActionBusy(busyKey);
    try {
      const result = await apiClient.runAttentionAction(itemId, action.id, params);
      handleAttentionDirective(result?.directive);
      if (result?.reminder?.title && result?.reminder?.reminder_time) {
        const when = new Date(result.reminder.reminder_time).toLocaleTimeString('en-US', {
          hour: 'numeric',
          minute: '2-digit',
        });
        Alert.alert('Reminder set', `${result.reminder.title} at ${when}`);
      }
      if (result?.calendar_event) {
        const when = new Date(result.calendar_event.start_time).toLocaleString('en-US', {
          dateStyle: 'short',
          timeStyle: 'short',
        });
        Alert.alert('Event created', `${result.calendar_event.title} at ${when}`);
      }
      if (result?.status === 'completed') {
        Alert.alert('Done', 'Item marked as completed.');
      }
      await loadAttention();
      await loadAttentionCount();
    } catch {
      Alert.alert('Action failed', 'Could not run that attention action.');
    } finally {
      setAttentionActionBusy(null);
    }
  };

  const showTimePicker = (itemId: string, action: AttentionAction) => {
    const hoursFromNow = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();
    const tomorrow9am = () => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      return d.toISOString();
    };

    if (action.kind === 'add_reminder') {
      Alert.alert('Remind me', 'When should I remind you?', [
        { text: '1 hour', onPress: () => runAttentionAction(itemId, action, { reminder_time: hoursFromNow(1) }) },
        { text: '3 hours', onPress: () => runAttentionAction(itemId, action, { reminder_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(itemId, action, { reminder_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
    } else if (action.kind === 'add_calendar') {
      Alert.alert('Add to calendar', 'When should this event be?', [
        { text: 'In 1 hour', onPress: () => runAttentionAction(itemId, action, { start_time: hoursFromNow(1) }) },
        { text: 'In 3 hours', onPress: () => runAttentionAction(itemId, action, { start_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(itemId, action, { start_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
    }
  };

  const handleAttentionActionPress = (itemId: string, action: AttentionAction) => {
    if (action.kind === 'add_reminder' || action.kind === 'add_calendar') {
      showTimePicker(itemId, action);
    } else {
      runAttentionAction(itemId, action);
    }
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
    { key: 'mind', label: 'Mind' },
    { key: 'activity', label: 'Activity' },
    { key: 'attention', label: 'Attention', badge: attentionCount },
    { key: 'missions', label: 'Missions' },
  ];

  const renderAttentionItem = ({ item }: { item: any }) => {
    const isCompleted = item.status === 'completed';
    const priorityColor = item.priority === 'critical' ? colors.error
      : item.priority === 'urgent' ? colors.hues.orange
      : item.priority === 'high' ? colors.hues.amber
      : colors.textMuted;
    const actions = getAttentionActions(item);
    return (
      <TouchableOpacity
        style={[styles.activityItem, isCompleted && { opacity: 0.6, borderLeftWidth: 3, borderLeftColor: colors.success }]}
        activeOpacity={0.85}
        onPress={() => {
          if (item.status === 'new' || item.status === 'sent') {
            markAttentionEngaged(item.id);
          }
        }}
      >
        <View style={styles.itemRow}>
          <View style={[styles.typeBadge, { backgroundColor: priorityColor + '20' }]}>
            <Text style={[styles.typeBadgeText, { color: priorityColor }]}>{item.priority}</Text>
          </View>
          <View style={styles.itemContent}>
            <Text style={[styles.itemSummary, isCompleted && { textDecorationLine: 'line-through', color: colors.textMuted }]} numberOfLines={2}>
              {isCompleted ? '\u2705 ' : ''}{item.title}
            </Text>
            {item.body && <Text style={styles.detailText} numberOfLines={2}>{item.body}</Text>}
            {!isCompleted && actions.length > 0 && (
              <View style={styles.attentionActionsRow}>
                {actions.map((action) => {
                  const busy = attentionActionBusy === `${item.id}:${action.id}`;
                  const isComplete = action.kind === 'complete';
                  return (
                    <TouchableOpacity
                      key={action.id}
                      style={[styles.attentionActionChip, isComplete && { borderColor: colors.success + '66', backgroundColor: colors.success + '14' }]}
                      disabled={busy}
                      onPress={() => handleAttentionActionPress(item.id, action)}
                    >
                      <Text style={[styles.attentionActionText, isComplete && { color: colors.success }]}>
                        {busy ? 'Working...' : action.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            )}
          </View>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {item.status === 'new' && (
              <TouchableOpacity onPress={() => markAttentionRead(item.id)}>
                <Text style={{ color: colors.primary, fontSize: fontSizes.xs }}>Read</Text>
              </TouchableOpacity>
            )}
            {!isCompleted && (
              <TouchableOpacity onPress={() => archiveAttention(item.id)}>
                <Text style={{ color: colors.textMuted, fontSize: fontSizes.xs }}>Archive</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  const renderMissionItem = ({ item }: { item: any }) => {
    const stateColor = item.state === 'done' ? colors.success
      : item.state === 'running' ? colors.info
      : item.state === 'failed' ? colors.error
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

  // ── Mind Tab Content ──────────────────────────────────────

  const renderMindTab = () => {
    const eColor = emotionColor(workingMemory?.sara_emotional_tone);
    const recentActions = deliberations
      .filter(d => formatActions(d.actions_taken).length > 0)
      .slice(0, 3)
      .flatMap(d => formatActions(d.actions_taken).map(a => ({ action: a, time: d.created_at })))
      .slice(0, 5);

    return (
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
      >
        {/* Focus + Emotional State */}
        <View style={styles.activityItem}>
          <View style={styles.itemHeader}>
            <Text style={{ fontSize: 16 }}>{'\uD83C\uDFAF'}</Text>
            <Text style={styles.sectionLabel}>Current Focus</Text>
          </View>
          <Text style={styles.itemSummary}>
            {workingMemory?.sara_focus || 'No specific focus right now'}
          </Text>
        </View>

        <View style={styles.activityItem}>
          <View style={styles.itemHeader}>
            <View style={[styles.emotionDot, { backgroundColor: eColor }]} />
            <Text style={styles.sectionLabel}>Emotional Tone</Text>
          </View>
          <Text style={[styles.itemSummary, { color: eColor }]}>
            {workingMemory?.sara_emotional_tone || 'Unknown'}
          </Text>
        </View>

        {/* Watching For */}
        {workingMemory?.last_heartbeat_watching_for ? (
          <View style={styles.activityItem}>
            <View style={styles.itemHeader}>
              <Text style={{ fontSize: 16 }}>{'\uD83D\uDC41'}</Text>
              <Text style={styles.sectionLabel}>Watching For</Text>
            </View>
            <Text style={styles.detailText}>
              {workingMemory.last_heartbeat_watching_for}
            </Text>
          </View>
        ) : null}

        {/* Stats Row */}
        <View style={styles.statsRow}>
          <View style={styles.statCard}>
            <Text style={styles.statValue}>{workingMemory?.sara_deliberation_count_today ?? 0}</Text>
            <Text style={styles.statLabel}>Deliberations</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={styles.statValue}>{workingMemory?.notifications_sent_today ?? 0}</Text>
            <Text style={styles.statLabel}>Notifications</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={styles.statValue}>{workingMemory?.observation_count ?? 0}</Text>
            <Text style={styles.statLabel}>Observations</Text>
          </View>
        </View>

        {/* Recent Thoughts */}
        {deliberations.length > 0 && (
          <>
            <View style={[styles.itemHeader, { marginTop: spacing.md, marginBottom: spacing.sm }]}>
              <Text style={{ fontSize: 16 }}>{'\uD83E\uDDE0'}</Text>
              <Text style={styles.sectionLabel}>Recent Thoughts</Text>
            </View>
            {deliberations.slice(0, 5).map((d, i) => {
              const isThoughtExpanded = expandedThoughtIdx === i;
              const actions = formatActions(d.actions_taken);
              const sourceColor = d.source === 'deliberation' ? colors.secondary
                : d.source === 'consolidation' ? colors.info
                : colors.textMuted;

              return (
                <TouchableOpacity
                  key={i}
                  style={styles.activityItem}
                  onPress={() => setExpandedThoughtIdx(isThoughtExpanded ? null : i)}
                  activeOpacity={0.7}
                >
                  <View style={styles.itemHeader}>
                    <View style={[styles.typeBadge, { backgroundColor: sourceColor + '20' }]}>
                      <Text style={[styles.typeBadgeText, { color: sourceColor }]}>{d.source}</Text>
                    </View>
                    {actions.length > 0 && (
                      <Text style={{ color: colors.success, fontSize: fontSizes.xs }}>
                        {'\u26A1'} {actions.length} action{actions.length > 1 ? 's' : ''}
                      </Text>
                    )}
                    <Text style={styles.itemTime}>{timeAgo(d.created_at)}</Text>
                  </View>
                  <Text style={styles.itemSummary} numberOfLines={isThoughtExpanded ? undefined : 3}>
                    {d.thought || 'No thought recorded'}
                  </Text>
                  {isThoughtExpanded && (
                    <View style={styles.expandedDetail}>
                      {d.handoff_note ? (
                        <View style={{ marginBottom: spacing.sm }}>
                          <Text style={styles.miniLabel}>Handoff Note</Text>
                          <Text style={styles.detailText}>{d.handoff_note}</Text>
                        </View>
                      ) : null}
                      {d.watching_for ? (
                        <View style={{ marginBottom: spacing.sm }}>
                          <Text style={styles.miniLabel}>Now Watching For</Text>
                          <Text style={styles.detailText}>{d.watching_for}</Text>
                        </View>
                      ) : null}
                      {actions.length > 0 ? (
                        <View>
                          <Text style={styles.miniLabel}>Actions Taken</Text>
                          {actions.map((a, j) => (
                            <Text key={j} style={[styles.detailText, { color: colors.success }]}>
                              {'\u2713'} {a}
                            </Text>
                          ))}
                        </View>
                      ) : null}
                    </View>
                  )}
                </TouchableOpacity>
              );
            })}
          </>
        )}

        {/* Observations */}
        {observations.length > 0 && (
          <>
            <View style={[styles.itemHeader, { marginTop: spacing.md, marginBottom: spacing.sm }]}>
              <Text style={{ fontSize: 16 }}>{'\uD83D\uDC41'}</Text>
              <Text style={styles.sectionLabel}>
                Observations (salience: {accumulatedSalience.toFixed(1)}/2.0)
              </Text>
            </View>
            {observations.slice(0, 5).map((obs) => (
              <View key={obs.id} style={styles.activityItem}>
                <View style={styles.itemHeader}>
                  <View style={[styles.salienceDot, { backgroundColor: salienceColor(obs.salience) }]} />
                  <Text style={[styles.typeBadgeText, { color: salienceColor(obs.salience) }]}>
                    {obs.salience.toFixed(2)}
                  </Text>
                  <Text style={styles.itemTime}>{obs.source}</Text>
                  <Text style={styles.itemTime}>{timeAgo(obs.timestamp)}</Text>
                </View>
                <Text style={styles.detailText} numberOfLines={2}>{obs.description}</Text>
              </View>
            ))}
          </>
        )}

        {/* Recent Actions */}
        {recentActions.length > 0 && (
          <>
            <View style={[styles.itemHeader, { marginTop: spacing.md, marginBottom: spacing.sm }]}>
              <Text style={{ fontSize: 16 }}>{'\u26A1'}</Text>
              <Text style={styles.sectionLabel}>Recent Actions</Text>
            </View>
            {recentActions.map((a, i) => (
              <View key={i} style={styles.activityItem}>
                <View style={styles.itemRow}>
                  <Text style={{ color: colors.success, fontSize: fontSizes.sm }}>{'\u2713'}</Text>
                  <Text style={[styles.detailText, { flex: 1 }]}>{a.action}</Text>
                  <Text style={styles.itemTime}>{timeAgo(a.time)}</Text>
                </View>
              </View>
            ))}
          </>
        )}

        <View style={{ height: spacing.xxl }} />
      </ScrollView>
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

      {tab === 'mind' && renderMindTab()}

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
    marginBottom: spacing.sm,
  },
  itemRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'flex-start',
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
  attentionActionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: spacing.sm,
  },
  attentionActionChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.primary + '66',
    backgroundColor: colors.primary + '14',
  },
  attentionActionText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
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
  // Mind tab specific styles
  sectionLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  emotionDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  salienceDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  miniLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    marginBottom: 2,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  statValue: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
});

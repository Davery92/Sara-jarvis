import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';

interface ActivityEntry {
  id: string;
  created_at: string;
  kind: string;
  summary: string;
  body?: string | null;
  tags: string[];
  metadata: Record<string, any>;
}

interface DaemonStatus {
  state: string;
  version: string;
  pid: number | null;
  hostname: string | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
  last_tick_summary: string | null;
  is_alive: boolean;
  seconds_since_heartbeat: number | null;
}

interface Focus {
  topic: string | null;
  why: string | null;
  set_at: string | null;
  updated_at: string | null;
}

interface ACSSnapshot {
  daemon_status: DaemonStatus;
  focus: Focus;
  recent_activity: ActivityEntry[];
}

const KIND_EMOJI: Record<string, string> = {
  thought: '💭',
  reflection: '🪞',
  focus_set: '🎯',
  focus_clear: '⏹',
  notify_david: '📣',
  inbox_pickup: '📥',
  inbox_complete: '✅',
  inbox_dismiss: '🗑',
  tool_call: '🔧',
  tool_result: '📦',
  external_event: '🌐',
  error: '⚠️',
};

const STATE_CONFIG: Record<string, { label: string; color: string; emoji: string }> = {
  boot: { label: 'Starting', color: colors.warning, emoji: '🚀' },
  idle: { label: 'Idle', color: colors.textMuted, emoji: '⏸️' },
  working: { label: 'Active', color: colors.success, emoji: '⚡' },
  sleeping: { label: 'Resting', color: colors.textMuted, emoji: '💤' },
  error: { label: 'Error', color: colors.warning, emoji: '⚠️' },
  never_started: { label: 'Not started', color: colors.textMuted, emoji: '⏸️' },
};

function timeAgo(dateStr: string | null | undefined): string {
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

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '…';
}

function formatActivity(entry: ActivityEntry): string {
  const emoji = KIND_EMOJI[entry.kind] || '•';
  return `${emoji} ${entry.summary || entry.kind}`;
}

export default function ACSStatusCard() {
  const [snapshot, setSnapshot] = useState<ACSSnapshot | null>(null);
  const [liveActivity, setLiveActivity] = useState<ActivityEntry[]>([]);
  const [latestThought, setLatestThought] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const navigation = useNavigation<any>();
  const [loading, setLoading] = useState(true);

  const fetchSnapshot = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/v2/snapshot');
      setSnapshot(data as ACSSnapshot);
    } catch {
      // graceful degradation
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll snapshot
  useEffect(() => {
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, 30_000); // 30s
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  // Seed the live feed + latest thought from the snapshot's recent activity
  // so the card isn't empty until the first SSE tick lands.
  useEffect(() => {
    if (!snapshot?.recent_activity?.length) return;
    setLiveActivity(prev => (prev.length ? prev : snapshot.recent_activity.slice(0, 10)));
    const lastThought = snapshot.recent_activity.find(a => a.kind === 'thought');
    if (lastThought) setLatestThought(lastThought.summary);
  }, [snapshot?.recent_activity]);

  // SSE: only worth holding open while the daemon is actually alive.
  useEffect(() => {
    if (!snapshot?.daemon_status?.is_alive) {
      return;
    }

    let cancelled = false;

    async function connectSSE() {
      const token = await apiClient.getAuthToken();
      if (!token || cancelled) return;

      try {
        const url = `${apiClient.baseURL}/api/acs/v2/stream`;
        const response = await fetch(url, {
          headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
        });

        if (!response.ok || !response.body) return;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const entry = JSON.parse(line.slice(6)) as Partial<ActivityEntry>;
                if (!entry.kind) continue; // "hello" ping frame, no activity payload
                if (entry.kind === 'thought' && entry.summary) {
                  setLatestThought(entry.summary);
                }
                setLiveActivity(prev => [entry as ActivityEntry, ...prev].slice(0, 10));
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      } catch {
        // reconnect handled by snapshot poll
      }
    }

    connectSSE();
    return () => { cancelled = true; };
  }, [snapshot?.daemon_status?.is_alive]);

  if (loading) {
    return (
      <View style={styles.card}>
        <ActivityIndicator color={colors.textMuted} size="small" />
      </View>
    );
  }

  if (!snapshot) return null;

  const status = snapshot.daemon_status;
  const stateConfig = STATE_CONFIG[status.state] || STATE_CONFIG.idle;
  const isLive = status.is_alive;
  const focus = snapshot.focus;

  return (
    <TouchableOpacity
      style={[styles.card, isLive && styles.cardLive]}
      activeOpacity={0.7}
      onPress={() => setExpanded(e => !e)}
    >
      {/* Header row */}
      <View style={styles.header}>
        <View style={styles.stateRow}>
          <Text style={styles.stateEmoji}>{stateConfig.emoji}</Text>
          <Text style={[styles.stateLabel, { color: stateConfig.color }]}>
            {stateConfig.label}
          </Text>
          {isLive ? (
            <View style={styles.liveBadge}>
              <View style={styles.liveDot} />
              <Text style={styles.liveText}>online</Text>
            </View>
          ) : (
            <Text style={styles.lastSession}>
              {status.last_heartbeat_at ? `last seen ${timeAgo(status.last_heartbeat_at)}` : 'never connected'}
            </Text>
          )}
        </View>
        <Text style={styles.chevron}>{expanded ? '▲' : '▼'}</Text>
      </View>

      {/* Latest thought — always visible when live */}
      {isLive && latestThought ? (
        <Text style={styles.thoughtText} numberOfLines={2}>
          {'💭'} {latestThought}
        </Text>
      ) : null}

      {/* Current focus (always visible) */}
      {focus?.topic && (
        <TouchableOpacity
          style={styles.planButton}
          activeOpacity={0.6}
          onPress={() => navigation.navigate('DailyPlan')}
        >
          <Text style={styles.planButtonText} numberOfLines={1}>
            {'🎯'} {focus.topic}
          </Text>
          <Text style={styles.planChevron}>{'›'}</Text>
        </TouchableOpacity>
      )}

      {/* Expanded section */}
      {expanded && (
        <View style={styles.expandedSection}>
          {/* Focus reason */}
          {focus?.why ? (
            <Text style={styles.previewText}>{truncate(focus.why, 200)}</Text>
          ) : null}

          {/* Recent activity feed */}
          {liveActivity.length > 0 && (
            <View style={styles.liveSection}>
              <Text style={styles.sectionLabel}>{'⚡'} Recent Activity</Text>
              {liveActivity.slice(0, 5).map((entry, i) => (
                <Text key={entry.id || i} style={styles.liveEventText} numberOfLines={1}>
                  {formatActivity(entry)}
                </Text>
              ))}
            </View>
          )}

          {!isLive && status.last_tick_summary && (
            <View style={styles.sessionSection}>
              <Text style={styles.sectionLabel}>Last Tick</Text>
              <Text style={styles.sessionDetail}>{status.last_tick_summary}</Text>
            </View>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardLive: {
    borderColor: colors.success + '60',
    backgroundColor: colors.surface,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  stateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    gap: 6,
  },
  stateEmoji: {
    fontSize: 14,
  },
  stateLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.success + '15',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    gap: 4,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.success,
  },
  liveText: {
    fontSize: 11,
    color: colors.success,
    fontWeight: '600',
  },
  lastSession: {
    fontSize: 11,
    color: colors.textMuted,
    marginLeft: 4,
  },
  chevron: {
    fontSize: 10,
    color: colors.textMuted,
  },
  thoughtText: {
    fontSize: 13,
    color: colors.text,
    fontStyle: 'italic',
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  planButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
    paddingVertical: 6,
  },
  planButtonText: {
    fontSize: 13,
    color: colors.hues.indigo,
    fontWeight: '600',
  },
  planChevron: {
    fontSize: 18,
    color: colors.hues.indigo,
  },
  expandedSection: {
    marginTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
  },
  previewText: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
    marginBottom: spacing.md,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textMuted,
    marginBottom: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  liveSection: {
    marginBottom: spacing.md,
  },
  liveEventText: {
    fontSize: 12,
    color: colors.textSecondary,
    paddingVertical: 2,
  },
  sessionSection: {
    marginBottom: spacing.xs,
  },
  sessionDetail: {
    fontSize: 12,
    color: colors.textSecondary,
  },
});

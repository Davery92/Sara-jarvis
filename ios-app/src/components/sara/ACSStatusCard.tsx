import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  emotional_state?: string;
  daily_plan?: string;
  directives?: ACSDirective[];
  latest_note?: {
    title: string;
    preview: string;
    created_at: string;
    folder?: string;
  };
  latest_journal?: {
    snippet: string;
    updated_at: string;
  };
  last_session?: {
    mode: string;
    turns: number;
    notes_created: number;
    started_at: string;
    ended_at: string;
    end_reason: string;
  };
  live_session?: {
    id: string;
    mode: string;
    turns: number;
    notes_created: number;
    elapsed_minutes: number;
  };
}

interface LiveEvent {
  type: string;
  mode?: string;
  turn?: number;
  tool?: string;
  notes_created?: number;
  summary?: string;
  [key: string]: any;
}

const MODE_EMOJI: Record<string, string> = {
  exploration: '\uD83D\uDD2D',
  consolidation: '\uD83D\uDD17',
  reflection: '\uD83E\uDE9E',
  research: '\uD83D\uDCDA',
  learning: '\uD83C\uDF93',
};

const STATE_CONFIG: Record<string, { label: string; color: string; emoji: string }> = {
  autonomous: { label: 'Active', color: colors.success, emoji: '\u26A1' },
  cooldown: { label: 'Resting', color: colors.textMuted, emoji: '\uD83D\uDCA4' },
  conversational: { label: 'Chatting', color: colors.info, emoji: '\uD83D\uDCAC' },
  idle: { label: 'Idle', color: colors.textMuted, emoji: '\u23F8\uFE0F' },
  pausing: { label: 'Pausing', color: colors.warning, emoji: '\u23F8\uFE0F' },
  paused: { label: 'Paused', color: colors.warning, emoji: '\u23F8\uFE0F' },
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
  return text.slice(0, max).trimEnd() + '\u2026';
}

export default function ACSStatusCard() {
  const [snapshot, setSnapshot] = useState<ACSSnapshot | null>(null);
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [latestThought, setLatestThought] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const navigation = useNavigation<any>();
  const [loading, setLoading] = useState(true);
  const eventSourceRef = useRef<any>(null);

  const fetchSnapshot = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/snapshot');
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

  // SSE for live session
  useEffect(() => {
    if (!snapshot?.live_session) {
      setLiveEvents([]);
      setLatestThought(null);
      return;
    }

    let cancelled = false;

    async function connectSSE() {
      const token = await apiClient.getAuthToken();
      if (!token || cancelled) return;

      try {
        const url = `${apiClient.baseURL}/api/acs/live?token=${encodeURIComponent(token)}`;
        const response = await fetch(url, {
          headers: { Accept: 'text/event-stream' },
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
                const event = JSON.parse(line.slice(6)) as LiveEvent;
                if (event.type === 'thought' && event.text) {
                  setLatestThought(event.text as string);
                } else if (event.type && event.type !== 'status' && event.type !== 'thought') {
                  setLiveEvents(prev => [event, ...prev].slice(0, 10));
                }
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
  }, [snapshot?.live_session?.id]);

  if (loading) {
    return (
      <View style={styles.card}>
        <ActivityIndicator color={colors.textMuted} size="small" />
      </View>
    );
  }

  if (!snapshot) return null;

  const stateConfig = STATE_CONFIG[snapshot.state] || STATE_CONFIG.idle;
  const isLive = !!snapshot.live_session;

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
          {isLive && snapshot.live_session && (
            <View style={styles.liveBadge}>
              <View style={styles.liveDot} />
              <Text style={styles.liveText}>
                {MODE_EMOJI[snapshot.live_session.mode] || ''}{' '}
                {snapshot.live_session.mode} — turn {snapshot.live_session.turns},{' '}
                {Math.round(snapshot.live_session.elapsed_minutes)}m
              </Text>
            </View>
          )}
          {!isLive && snapshot.last_session && (
            <Text style={styles.lastSession}>
              {MODE_EMOJI[snapshot.last_session.mode] || ''}{' '}
              {snapshot.last_session.mode} {timeAgo(snapshot.last_session.ended_at)}
            </Text>
          )}
        </View>
        <Text style={styles.chevron}>{expanded ? '\u25B2' : '\u25BC'}</Text>
      </View>

      {/* Latest thought — always visible when live */}
      {isLive && latestThought ? (
        <Text style={styles.thoughtText} numberOfLines={2}>
          {'\uD83D\uDCAD'} {latestThought}
        </Text>
      ) : null}

      {/* Latest note preview (always visible) */}
      {snapshot.latest_note && (
        <View style={styles.noteRow}>
          <Text style={styles.noteIcon}>{'\uD83D\uDDD2'}</Text>
          <View style={styles.noteContent}>
            <Text style={styles.noteTitle} numberOfLines={1}>
              {snapshot.latest_note.title}
            </Text>
            <Text style={styles.noteMeta}>
              {snapshot.latest_note.folder ? `${snapshot.latest_note.folder} \u00B7 ` : ''}
              {timeAgo(snapshot.latest_note.created_at)}
            </Text>
          </View>
        </View>
      )}

      {/* Daily Plan */}
      {snapshot.daily_plan ? (
        <TouchableOpacity
          style={styles.planButton}
          activeOpacity={0.6}
          onPress={() => navigation.navigate('DailyPlan')}
        >
          <Text style={styles.planButtonText}>{'\uD83D\uDCCB'} Today's Plan</Text>
          <Text style={styles.planChevron}>{'\u203A'}</Text>
        </TouchableOpacity>
      ) : null}

      {/* Expanded section */}
      {expanded && (
        <View style={styles.expandedSection}>
          {/* Note preview text */}
          {snapshot.latest_note?.preview ? (
            <Text style={styles.previewText}>
              {truncate(snapshot.latest_note.preview, 200)}
            </Text>
          ) : null}

          {/* Latest journal */}
          {snapshot.latest_journal && (
            <View style={styles.journalSection}>
              <Text style={styles.sectionLabel}>{'\uD83D\uDCD6'} Latest Journal</Text>
              <Text style={styles.journalText}>
                {truncate(snapshot.latest_journal.snippet, 250)}
              </Text>
              <Text style={styles.journalTime}>
                {timeAgo(snapshot.latest_journal.updated_at)}
              </Text>
            </View>
          )}

          {/* Live events feed */}
          {isLive && liveEvents.length > 0 && (
            <View style={styles.liveSection}>
              <Text style={styles.sectionLabel}>{'\u26A1'} Live Activity</Text>
              {liveEvents.slice(0, 5).map((event, i) => (
                <Text key={i} style={styles.liveEventText}>
                  {formatLiveEvent(event)}
                </Text>
              ))}
            </View>
          )}

          {/* Last session summary */}
          {!isLive && snapshot.last_session && (
            <View style={styles.sessionSection}>
              <Text style={styles.sectionLabel}>Last Session</Text>
              <Text style={styles.sessionDetail}>
                {snapshot.last_session.mode} \u00B7{' '}
                {snapshot.last_session.turns} turns \u00B7{' '}
                {snapshot.last_session.notes_created} notes \u00B7{' '}
                {snapshot.last_session.end_reason}
              </Text>
            </View>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

function formatLiveEvent(event: LiveEvent): string {
  switch (event.type) {
    case 'turn_starting':
      return `\u25B6 Starting turn ${event.turn || '?'}`;
    case 'turn_completed':
      return `\u2705 Turn ${event.turn || '?'} done${event.notes_created ? ` (${event.notes_created} notes)` : ''}`;
    case 'tool_call':
      return `\uD83D\uDD27 Using ${event.tool || 'tool'}`;
    case 'mode_selected':
      return `${MODE_EMOJI[event.mode || ''] || '\uD83C\uDFAF'} Mode: ${event.mode}`;
    case 'session_ended':
      return `\u23F9 Session ended: ${event.summary || event.end_reason || ''}`;
    case 'human_input_requested':
      return '\uD83D\uDE4B Waiting for your input';
    default:
      return `${event.type}`;
  }
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
  noteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.sm,
    gap: 8,
  },
  noteIcon: {
    fontSize: 14,
  },
  noteContent: {
    flex: 1,
  },
  noteTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
  },
  noteMeta: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 1,
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
  journalSection: {
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
  journalText: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
    fontStyle: 'italic',
  },
  journalTime: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 2,
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

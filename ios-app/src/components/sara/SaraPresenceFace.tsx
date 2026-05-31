import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SaraOrb from './SaraOrb';

/**
 * SaraPresenceFace — the first-person, Jarvis/Cortana face of the ACS.
 *
 * The daemon already thinks in first person (a `thought` body IS Sara's
 * thinking, a `reflection` carries a verdict). This view stops rendering that
 * as a telemetry log and instead lets Sara *address David* — current mood,
 * what she's making of things right now, what's on her mind, and a stream of
 * her recent thinking in her own voice. The raw console lives behind
 * "Under the hood".
 */

// ─── Types (subset of /api/sara/status + /api/acs/v2) ───

interface SaraStatus {
  emotional_state: string;
  watching_for: string[];
  latest_thought: string | null;
  last_action: string | null;
  hours_since_last_chat: number | null;
}

interface DaemonStatus {
  state: string;
  is_alive: boolean;
  last_tick_summary: string | null;
  seconds_since_heartbeat: number | null;
}

interface Focus {
  topic: string | null;
  why: string | null;
  set_at: string | null;
}

interface Activity {
  id: string;
  created_at: string;
  kind: string;
  summary: string;
  body: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

type Verdict = 'productive' | 'looping' | 'drifting' | 'idle';

// ─── Helpers ────────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 45_000) return 'just now';
  const m = Math.floor(ms / 60_000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return 'Late night, David';
  if (h < 12) return 'Good morning, David';
  if (h < 17) return 'Good afternoon, David';
  if (h < 22) return 'Good evening, David';
  return 'Winding down, David';
}

// How Sara feels → a soft accent + a word she'd use.
const MOOD: Record<string, { word: string; color: string }> = {
  curious: { word: 'curious', color: '#5fe0d4' },
  calm: { word: 'calm', color: '#7bd3ff' },
  content: { word: 'content', color: '#7bd3ff' },
  focused: { word: 'focused', color: '#8b8df9' },
  alert: { word: 'alert', color: '#f5c542' },
  concerned: { word: 'concerned', color: '#f59e0b' },
  protective: { word: 'watchful', color: '#f59e0b' },
  excited: { word: 'excited', color: '#e879f9' },
  proud: { word: 'proud', color: '#e879f9' },
  reflective: { word: 'reflective', color: '#a78bfa' },
  attentive: { word: 'attentive', color: '#5fe0d4' },
  tired: { word: 'a little tired', color: '#94a3b8' },
  sleeping: { word: 'resting', color: '#94a3b8' },
  neutral: { word: 'here', color: '#8aa0b4' },
};

function mood(state: string | undefined) {
  return MOOD[(state || 'neutral').toLowerCase()] || MOOD.neutral;
}

const VERDICT_LABEL: Record<Verdict, { text: string; color: string }> = {
  productive: { text: 'Making progress', color: '#34d399' },
  looping: { text: 'Going in circles', color: '#f59e0b' },
  drifting: { text: 'Drifting a bit', color: '#fb923c' },
  idle: { text: 'Quiet for now', color: '#94a3b8' },
};

function verdictOf(a: Activity): Verdict | null {
  const m = (a.metadata?.verdict as string) || a.tags?.find((t) =>
    ['productive', 'looping', 'drifting', 'idle'].includes(t),
  );
  return (m as Verdict) || null;
}

/** Render one activity entry as Sara speaking. */
function narrate(a: Activity): { text: string; prefix?: string } | null {
  const body = (a.body || '').trim();
  const summary = (a.summary || '').trim();
  switch (a.kind) {
    case 'thought':
      return { text: body || summary };
    case 'reflection':
      return { prefix: 'Stepping back —', text: body || summary };
    case 'focus_set':
      return { prefix: 'I turned my attention to', text: summary };
    case 'notify_david':
      return { prefix: 'I reached out:', text: summary };
    case 'inbox_complete':
      return { prefix: 'Finished what you asked:', text: summary };
    default:
      return null;
  }
}

const NARRATABLE = new Set([
  'thought',
  'reflection',
  'focus_set',
  'notify_david',
  'inbox_complete',
]);

/** Pull title + message out of a notify_david activity body. */
function parseNotice(a: Activity): { title: string; message: string } {
  const body = a.body || '';
  const titleM = body.match(/Title:\s*([\s\S]*?)\n\nBody:/);
  const bodyM = body.match(/Body:\s*([\s\S]*?)(?:\n\nWhy:|$)/);
  const fallbackTitle = (a.summary || '').replace(/^.*?David:\s*/, '').trim();
  return {
    title: (titleM?.[1] || fallbackTitle || 'Something came up').trim(),
    message: (bodyM?.[1] || '').trim(),
  };
}

const NOTICE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

// ─── Component ──────────────────────────────────────────

export default function SaraPresenceFace({
  onOpenConsole,
}: {
  onOpenConsole: () => void;
}) {
  const navigation = useNavigation<any>();
  const [status, setStatus] = useState<SaraStatus | null>(null);
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dismissedNotices, setDismissedNotices] = useState<Set<string>>(new Set());

  const fetchAll = useCallback(async () => {
    try {
      const [s, d, f, a] = await Promise.all([
        apiClient.get<SaraStatus>('/api/sara/status').catch(() => null),
        apiClient.get<DaemonStatus>('/api/acs/v2/daemon-status').catch(() => null),
        apiClient.get<Focus>('/api/acs/v2/focus').catch(() => null),
        apiClient.get<Activity[]>('/api/acs/v2/activity?limit=40').catch(() => []),
      ]);
      if (s) setStatus(s);
      if (d) setDaemon(d);
      if (f) setFocus(f);
      if (a) setActivity(a);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
  }, [fetchAll]);

  if (loading && !status && !daemon) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  const m = mood(status?.emotional_state);
  const alive = !!daemon?.is_alive;
  const resting =
    alive && ['idle', 'sleeping', 'reflecting'].includes((daemon?.state || '').toLowerCase());

  // Most recent reflection verdict (her read on how it's going).
  const lastReflection = activity.find((a) => a.kind === 'reflection');
  const verdict = lastReflection ? verdictOf(lastReflection) : null;

  // Her current line — the freshest thing she's thinking.
  const currentLine =
    status?.latest_thought ||
    activity.find((a) => a.kind === 'thought')?.body ||
    daemon?.last_tick_summary ||
    "I'm here, keeping an eye on things.";

  const watching = (status?.watching_for || []).filter(Boolean).slice(0, 4);

  // Her most recent unprompted reach-out — the "Hey, I noticed…" moment.
  // Elevated out of the stream into its own card while it's fresh + unseen.
  const notice = activity.find(
    (a) =>
      a.kind === 'notify_david' &&
      !dismissedNotices.has(a.id) &&
      Date.now() - new Date(a.created_at).getTime() < NOTICE_MAX_AGE_MS,
  );
  const parsedNotice = notice ? parseNotice(notice) : null;

  // Narration stream — her recent thinking, in her voice. Skip the entry
  // that's currently elevated as the reach-out card, to avoid duplication.
  const stream = activity
    .filter((a) => NARRATABLE.has(a.kind) && a.id !== notice?.id)
    .slice(0, 12);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />
      }
    >
      {/* ── Header: orb + greeting + mood ── */}
      <View style={styles.header}>
        <SaraOrb size={72} />
        <View style={styles.headerCopy}>
          <Text style={styles.greeting}>{greeting()}</Text>
          <View style={styles.moodRow}>
            <View style={[styles.statusDot, { backgroundColor: alive ? m.color : '#6b7280' }]} />
            <Text style={styles.moodText}>
              {alive ? `Feeling ${m.word}` : 'Asleep right now'}
            </Text>
          </View>
        </View>
      </View>

      {/* ── She reached out: elevated unprompted notice ── */}
      {notice && parsedNotice ? (
        <View style={styles.noticeCard}>
          <View style={styles.noticeHeader}>
            <View style={styles.noticePulse} />
            <Text style={styles.noticeEyebrow}>Sara reached out · {timeAgo(notice.created_at)}</Text>
          </View>
          <Text style={styles.noticeTitle}>{parsedNotice.title}</Text>
          {parsedNotice.message ? (
            <Text style={styles.noticeMessage}>{parsedNotice.message}</Text>
          ) : null}
          <View style={styles.noticeActions}>
            <TouchableOpacity
              style={styles.noticeFollowBtn}
              activeOpacity={0.85}
              onPress={() => navigation.navigate('Chat')}
            >
              <Text style={styles.noticeFollowText}>Follow up</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.noticeDismissBtn}
              activeOpacity={0.7}
              onPress={() =>
                setDismissedNotices((prev) => new Set(prev).add(notice.id))
              }
            >
              <Text style={styles.noticeDismissText}>Got it</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}

      {/* ── Right now: her current thought ── */}
      <View style={[styles.heroCard, { borderColor: m.color + '55' }]}>
        <Text style={styles.heroEyebrow}>Right now</Text>
        <Text style={styles.heroText}>{currentLine}</Text>
        {verdict ? (
          <View style={styles.verdictRow}>
            <View style={[styles.verdictDot, { backgroundColor: VERDICT_LABEL[verdict].color }]} />
            <Text style={[styles.verdictText, { color: VERDICT_LABEL[verdict].color }]}>
              {VERDICT_LABEL[verdict].text}
            </Text>
          </View>
        ) : null}
      </View>

      {/* ── Resting note ── */}
      {resting ? (
        <View style={styles.restCard}>
          <Text style={styles.restText}>
            Resting between thoughts — I’ll surface if something needs you.
          </Text>
        </View>
      ) : null}

      {/* ── On my mind ── */}
      {watching.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>On my mind</Text>
          <View style={styles.chipWrap}>
            {watching.map((w, i) => (
              <View key={i} style={styles.chip}>
                <Text style={styles.chipText}>{w}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {/* ── What I'm focused on ── */}
      {focus?.topic ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>What I’m focused on</Text>
          <View style={styles.focusCard}>
            <Text style={styles.focusTopic}>{focus.topic}</Text>
            {focus.why ? <Text style={styles.focusWhy}>{focus.why}</Text> : null}
          </View>
        </View>
      ) : null}

      {/* ── Recent thinking, in her voice ── */}
      {stream.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Lately I’ve been thinking</Text>
          <View style={styles.stream}>
            {stream.map((a, i) => {
              const n = narrate(a);
              if (!n) return null;
              const v = a.kind === 'reflection' ? verdictOf(a) : null;
              return (
                <View
                  key={a.id}
                  style={[styles.streamItem, i < stream.length - 1 && styles.streamItemBorder]}
                >
                  <Text style={styles.streamText}>
                    {n.prefix ? <Text style={styles.streamPrefix}>{n.prefix} </Text> : null}
                    {n.text}
                  </Text>
                  <View style={styles.streamMeta}>
                    <Text style={styles.streamTime}>{timeAgo(a.created_at)}</Text>
                    {v ? (
                      <Text style={[styles.streamVerdict, { color: VERDICT_LABEL[v].color }]}>
                        {VERDICT_LABEL[v].text.toLowerCase()}
                      </Text>
                    ) : null}
                  </View>
                </View>
              );
            })}
          </View>
        </View>
      ) : null}

      {/* ── Actions ── */}
      <View style={styles.actions}>
        <TouchableOpacity
          style={styles.primaryBtn}
          activeOpacity={0.85}
          onPress={() => navigation.navigate('Chat')}
        >
          <Text style={styles.primaryBtnText}>Talk to her</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.secondaryBtn} activeOpacity={0.85} onPress={onOpenConsole}>
          <Text style={styles.secondaryBtnText}>Under the hood</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.lg, paddingBottom: spacing.xl * 2 },
  centerFill: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  headerCopy: { flex: 1, gap: 4 },
  greeting: { color: colors.text, fontSize: fontSizes.xl, fontWeight: '700' },
  moodRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  moodText: { color: colors.textSecondary, fontSize: fontSizes.sm },

  noticeCard: {
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.accent + '88',
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  noticeHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm },
  noticePulse: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.accent },
  noticeEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  noticeTitle: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700', lineHeight: 22 },
  noticeMessage: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 21,
    marginTop: 6,
  },
  noticeActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  noticeFollowBtn: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: 9,
    paddingHorizontal: spacing.lg,
  },
  noticeFollowText: { color: '#fff', fontSize: fontSizes.sm, fontWeight: '700' },
  noticeDismissBtn: {
    borderRadius: borderRadius.md,
    paddingVertical: 9,
    paddingHorizontal: spacing.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  noticeDismissText: { color: colors.textSecondary, fontSize: fontSizes.sm, fontWeight: '600' },

  heroCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  heroEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
  },
  heroText: { color: colors.text, fontSize: fontSizes.lg, lineHeight: 26 },
  verdictRow: { flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: spacing.md },
  verdictDot: { width: 7, height: 7, borderRadius: 4 },
  verdictText: { fontSize: fontSizes.sm, fontWeight: '600' },

  restCard: {
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  restText: { color: colors.textSecondary, fontSize: fontSizes.sm, fontStyle: 'italic' },

  section: { marginBottom: spacing.lg },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
  },

  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  chipText: { color: colors.text, fontSize: fontSizes.sm },

  focusCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
  },
  focusTopic: { color: colors.text, fontSize: fontSizes.md, fontWeight: '600' },
  focusWhy: { color: colors.textSecondary, fontSize: fontSizes.sm, marginTop: 4, lineHeight: 19 },

  stream: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    overflow: 'hidden',
  },
  streamItem: { padding: spacing.md },
  streamItemBorder: { borderBottomWidth: 1, borderBottomColor: colors.assistant.border },
  streamText: { color: colors.text, fontSize: fontSizes.sm, lineHeight: 21 },
  streamPrefix: { color: colors.textMuted, fontStyle: 'italic' },
  streamMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: 6 },
  streamTime: { color: colors.textMuted, fontSize: fontSizes.xs },
  streamVerdict: { fontSize: fontSizes.xs, fontWeight: '600' },

  actions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.sm },
  primaryBtn: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  primaryBtnText: { color: '#fff', fontSize: fontSizes.md, fontWeight: '700' },
  secondaryBtn: {
    flex: 1,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  secondaryBtnText: { color: colors.textSecondary, fontSize: fontSizes.md, fontWeight: '600' },
});

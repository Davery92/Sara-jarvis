import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

/**
 * THE SYSTEM — god-view hub (iOS).
 * Mirrors the web SystemDashboard: world snapshot, Sara's mind, active work,
 * background hum, attention-balance meter, promotions, and the thought stream.
 * Fetches GET /api/system/overview.
 */

const DOMAIN_COLOR: Record<string, string> = {
  work: colors.accent,
  comms: colors.hues.cyan,
  calendar: colors.hues.sky,
  health: colors.hues.rose,
  home: colors.warning,
  goals: colors.hues.violet,
  people: colors.hues.rose,
  learning: colors.hues.emerald,
  meta: colors.textMuted,
};

function timeAgo(iso?: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const Stat: React.FC<{ label: string; value: any }> = ({ label, value }) => (
  <View style={styles.stat}>
    <Text style={styles.statLabel}>{label}</Text>
    <Text style={styles.statValue} numberOfLines={1}>
      {value === null || value === undefined || value === '' ? '—' : String(value)}
    </Text>
  </View>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <View style={styles.card}>
    <Text style={styles.kicker}>{title}</Text>
    {children}
  </View>
);

export default function SystemScreen() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await apiClient.get<any>('/api/system/overview');
      setData(d);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  if (loading && !data) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  const world = data?.world?.world || {};
  const fg = data?.world?.foreground || {};
  const bg = world.background || {};
  const activeWork = world.foreground?.active_work || [];
  const nextEvent = world.foreground?.next_event;
  const balance = data?.balance || {};
  const dist = (balance.distribution || []).filter((d: any) => d.count > 0);
  const maxPct = Math.max(1, ...dist.map((d: any) => d.pct));
  const promotions = data?.promotions?.items || [];
  const stream = data?.stream?.items || [];

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.pad}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {/* RIGHT NOW */}
        <Section title="RIGHT NOW">
          <View style={styles.statGrid}>
            <Stat label="Activity" value={fg.activity_state} />
            <Stat label="Interruptibility" value={fg.interruptibility != null ? `${Math.round(fg.interruptibility * 100)}%` : null} />
            <Stat label="Next event" value={nextEvent ? nextEvent.title : null} />
            <Stat label="Observations" value={fg.observation_count} />
          </View>
        </Section>

        {/* SARA'S MIND */}
        <Section title="SARA'S MIND">
          <View style={styles.statGrid}>
            <Stat label="Focus" value={fg.sara_focus} />
            <Stat
              label="Mood"
              value={fg.sara_emotional_tone
                ? `${fg.sara_emotional_tone}${fg.sara_emotional_intensity != null ? ` · ${Math.round(fg.sara_emotional_intensity * 100)}%` : ''}`
                : null}
            />
            <Stat label="Watching for" value={fg.last_heartbeat_watching_for} />
          </View>
        </Section>

        {/* ACTIVE WORK */}
        {activeWork.length > 0 && (
          <Section title="ACTIVE WORK">
            {activeWork.map((w: any, i: number) => (
              <View key={i} style={styles.lineRow}>
                <Text style={styles.lineText} numberOfLines={1}>{w.summary}</Text>
                <Text style={styles.lineMeta}>{w.branch || ''} · {timeAgo(w.at)}</Text>
              </View>
            ))}
          </Section>
        )}

        {/* BACKGROUND (subconscious) */}
        <Section title="BACKGROUND · SUBCONSCIOUS">
          <View style={styles.statGrid}>
            <Stat label="Home / 24h" value={bg.home?.events_24h} />
            <Stat label="Health / 24h" value={bg.health?.metrics_24h} />
            <Stat label="Resting HR" value={bg.health?.latest?.resting_hr ? `${bg.health.latest.resting_hr} bpm` : null} />
            <Stat label="Sleep" value={bg.health?.latest?.sleep_hours != null ? `${bg.health.latest.sleep_hours}h` : null} />
          </View>
          <Text style={styles.note}>
            {(bg.ambient_event_rate_24h ?? 0)} ambient signals / 24h — baselined, surfaced only on anomaly.
          </Text>
        </Section>

        {/* ATTENTION BALANCE */}
        <Section title="ATTENTION BALANCE · 7 DAYS">
          {balance.skew_warning ? (
            <Text style={styles.warn}>Lopsided — {balance.top_domain} is over half of what reached you.</Text>
          ) : null}
          {dist.length === 0 ? (
            <Text style={styles.empty}>Nothing surfaced in this window.</Text>
          ) : (
            dist.map((d: any) => (
              <View key={d.domain} style={styles.barRow}>
                <Text style={styles.barLabel}>{d.domain}</Text>
                <View style={styles.barTrack}>
                  <View style={[styles.barFill, { width: `${(d.pct / maxPct) * 100}%`, backgroundColor: DOMAIN_COLOR[d.domain] || colors.textMuted }]} />
                </View>
                <Text style={styles.barPct}>{d.pct}%</Text>
              </View>
            ))
          )}
        </Section>

        {/* PROMOTED TO ATTENTION */}
        {promotions.length > 0 && (
          <Section title="PROMOTED TO ATTENTION">
            {promotions.slice(0, 10).map((p: any, i: number) => (
              <View key={i} style={styles.lineRow}>
                <View style={styles.promoLeft}>
                  <View style={[styles.dot, { backgroundColor: DOMAIN_COLOR[p.domain] || colors.textMuted }]} />
                  <Text style={styles.lineText} numberOfLines={1}>{p.description}</Text>
                </View>
                <Text style={[styles.lineMeta, p.reason === 'override' ? { color: colors.hues.rose } : p.reason === 'exploration' ? { color: colors.hues.violet } : { color: colors.accent }]}>
                  {p.reason}
                </Text>
              </View>
            ))}
          </Section>
        )}

        {/* THOUGHT STREAM */}
        <Section title="THOUGHT STREAM">
          {stream.length === 0 ? (
            <Text style={styles.empty}>No recent thoughts.</Text>
          ) : (
            stream.slice(0, 15).map((it: any) => (
              <View key={`${it.kind}-${it.id}`} style={styles.thought}>
                <Text style={styles.thoughtMeta}>{(it.subtype || it.kind || '').toUpperCase()} · {timeAgo(it.at)}{it.notifications_sent ? ` · ${it.notifications_sent} notified` : ''}</Text>
                <Text style={styles.thoughtText}>{it.text}</Text>
              </View>
            ))
          )}
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background },
  pad: { padding: spacing.md, paddingBottom: spacing.xxl },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  kicker: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.2,
    color: colors.accent,
    marginBottom: spacing.sm,
  },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', marginHorizontal: -spacing.xs / 2 },
  stat: {
    width: '50%',
    paddingHorizontal: spacing.xs / 2,
    paddingVertical: spacing.xs,
  },
  statLabel: { fontSize: 11, color: colors.textMuted },
  statValue: { fontSize: fontSizes.sm, color: colors.text, marginTop: 2 },
  lineRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 },
  promoLeft: { flexDirection: 'row', alignItems: 'center', flex: 1, marginRight: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.sm },
  lineText: { flex: 1, fontSize: fontSizes.sm, color: colors.textSecondary },
  lineMeta: { fontSize: 11, color: colors.textMuted, marginLeft: spacing.sm },
  barRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 4 },
  barLabel: { width: 72, fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginRight: spacing.sm, textTransform: 'capitalize' },
  barTrack: { flex: 1, height: 10, backgroundColor: colors.surfaceLight, borderRadius: borderRadius.full, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: borderRadius.full },
  barPct: { width: 48, fontSize: 11, color: colors.textMuted, textAlign: 'right' },
  thought: { borderLeftWidth: 2, borderLeftColor: colors.assistant.passiveSoft, paddingLeft: spacing.sm, marginBottom: spacing.sm },
  thoughtMeta: { fontSize: 10, color: colors.textMuted, marginBottom: 2 },
  thoughtText: { fontSize: fontSizes.sm, color: colors.textSecondary, lineHeight: 19 },
  note: { fontSize: 11, color: colors.textMuted, marginTop: spacing.sm, fontStyle: 'italic' },
  warn: { fontSize: fontSizes.sm, color: colors.warning, marginBottom: spacing.sm },
  empty: { fontSize: fontSizes.sm, color: colors.textMuted, fontStyle: 'italic' },
  error: { fontSize: fontSizes.sm, color: colors.error, marginBottom: spacing.sm },
});

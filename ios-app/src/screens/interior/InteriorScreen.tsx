import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, RefreshControl, ActivityIndicator, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

/**
 * INTERIOR (iOS) — SINGULAR_SARA_MASTER_PLAN §U7/§U8.
 * Mirrors the web Interior page: same diagnostics endpoints, same sections
 * (kernel state, world, body, active intents, contradictions, recent
 * attention decisions, recent actions, bodies, recent events). Widgets and
 * Live Activities are meant to be projections of this same canonical state
 * (§U8) — this screen is the manual/pull-to-refresh version of that.
 */

interface SelfState {
  kernel_state: string;
  wake_reason: string | null;
  open_concerns: string[];
}
interface WorldState {
  summary: string | null;
  active_calendar_events: number;
  open_threads: number;
}
interface ContextSnapshot {
  self_state: SelfState;
  world_state: WorldState;
}
interface BodyComponent {
  name: string;
  label: string | null;
  status: 'ok' | 'degraded' | 'unknown';
  impact: string | null;
}
interface BodyState {
  healthy: boolean;
  components: BodyComponent[];
}
interface Intent {
  intent_id: string;
  kind: string;
  origin: string;
  status: string;
  next_step: string | null;
}
interface IntentGraph {
  total: number;
  intents: Intent[];
}
interface TruthViolation {
  severity: string;
  description: string;
}
interface TruthAudit {
  violation_count: number;
  violations: TruthViolation[];
}
interface AttentionLogItem {
  outbound_intent_id: string;
  subject: string;
  created_at: string;
  decision: string;
}
interface ActionReceipt {
  action_id: string;
  action_type: string;
  permission_tier: string;
  status: string;
}
interface BodyCapability {
  name: string;
  kind: string;
  version: string | null;
  alive: boolean;
}

const Section: React.FC<{ title: string; subtitle?: string; children: React.ReactNode }> = ({ title, subtitle, children }) => (
  <View style={styles.card}>
    <Text style={styles.kicker}>{title}</Text>
    {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
    {children}
  </View>
);

const Dot: React.FC<{ ok: boolean }> = ({ ok }) => (
  <View style={[styles.dot, { backgroundColor: ok ? colors.success : colors.error }]} />
);

async function safeGet<T>(path: string): Promise<T | null> {
  try {
    return await apiClient.get<T>(path);
  } catch {
    return null;
  }
}

export default function InteriorScreen() {
  const [context, setContext] = useState<ContextSnapshot | null>(null);
  const [bodyState, setBodyState] = useState<BodyState | null>(null);
  const [intentGraph, setIntentGraph] = useState<IntentGraph | null>(null);
  const [truthAudit, setTruthAudit] = useState<TruthAudit | null>(null);
  const [attentionLog, setAttentionLog] = useState<AttentionLogItem[]>([]);
  const [actionReceipts, setActionReceipts] = useState<ActionReceipt[]>([]);
  const [bodyCapabilities, setBodyCapabilities] = useState<BodyCapability[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const [ctx, body, intents, audit, attention, actions, caps] = await Promise.all([
      safeGet<ContextSnapshot>('/api/diagnostics/context-snapshot'),
      safeGet<BodyState>('/api/diagnostics/body-state'),
      safeGet<IntentGraph>('/api/diagnostics/intent-graph'),
      safeGet<TruthAudit>('/api/diagnostics/truth-audit'),
      safeGet<{ items: AttentionLogItem[] }>('/api/diagnostics/attention-log?limit=6'),
      safeGet<{ receipts: ActionReceipt[] }>('/api/diagnostics/action-receipts?limit=6'),
      safeGet<{ bodies: BodyCapability[] }>('/api/diagnostics/body-capabilities'),
    ]);
    setContext(ctx);
    setBodyState(body);
    setIntentGraph(intents);
    setTruthAudit(audit);
    setAttentionLog(attention?.items || []);
    setActionReceipts(actions?.receipts || []);
    setBodyCapabilities(caps?.bodies || []);
    setLoading(false);
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

  if (loading && !context) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  const self = context?.self_state;
  const world = context?.world_state;
  const degraded = bodyState?.components.filter((c) => c.status === 'degraded') || [];
  const openIntents = intentGraph?.intents.slice(0, 6) || [];

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.pad}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      >
        <Section title="KERNEL STATE">
          <Text style={styles.bigValue}>{self?.kernel_state || 'unknown'}</Text>
          <Text style={styles.subtitle}>{self?.wake_reason ? `woke: ${self.wake_reason.replace(/_/g, ' ')}` : 'resting'}</Text>
          {self?.open_concerns.map((c, i) => (
            <Text key={i} style={styles.warn}>⚠ {c}</Text>
          ))}
        </Section>

        <Section title="WORLD">
          <Text style={styles.lineText}>{world?.summary || '—'}</Text>
          <View style={styles.statGrid}>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{world?.active_calendar_events ?? '—'}</Text>
              <Text style={styles.statLabel}>calendar today</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{world?.open_threads ?? '—'}</Text>
              <Text style={styles.statLabel}>open threads</Text>
            </View>
          </View>
        </Section>

        <Section title="BODY">
          <View style={styles.lineRow}>
            <Dot ok={!!bodyState?.healthy} />
            <Text style={styles.bigValueSmall}>{bodyState?.healthy ? 'Healthy' : 'Degraded'}</Text>
          </View>
          {degraded.length === 0 ? (
            <Text style={styles.empty}>Nothing degraded</Text>
          ) : (
            degraded.map((c) => (
              <Text key={c.name} style={styles.warn}>{c.label || c.name}{c.impact ? ` — ${c.impact}` : ''}</Text>
            ))
          )}
        </Section>

        <Section title="ACTIVE INTENTS" subtitle={`${intentGraph?.total ?? 0} open across every source`}>
          {openIntents.length === 0 ? (
            <Text style={styles.empty}>Nothing open</Text>
          ) : (
            openIntents.map((i) => (
              <View key={i.intent_id} style={styles.lineRow}>
                <Text style={[styles.originTag, i.origin === 'sara' ? styles.originSara : styles.originDavid]}>{i.origin}</Text>
                <Text style={styles.lineText} numberOfLines={1}>{i.next_step || i.kind}</Text>
              </View>
            ))
          )}
        </Section>

        <Section title="CONTRADICTIONS" subtitle="impossible state combinations, scanned live">
          {!truthAudit || truthAudit.violation_count === 0 ? (
            <Text style={styles.empty}>None found</Text>
          ) : (
            <>
              {truthAudit.violations.slice(0, 5).map((v, i) => (
                <Text key={i} style={styles.warn}>{v.description}</Text>
              ))}
              {truthAudit.violation_count > 5 && (
                <Text style={styles.note}>+{truthAudit.violation_count - 5} more — {truthAudit.violation_count} total</Text>
              )}
            </>
          )}
        </Section>

        <Section title="RECENT ATTENTION DECISIONS">
          {attentionLog.length === 0 ? (
            <Text style={styles.empty}>No decisions recorded yet</Text>
          ) : (
            attentionLog.map((a) => (
              <View key={a.outbound_intent_id} style={styles.lineRow}>
                <Text style={styles.lineText} numberOfLines={1}>{a.subject}</Text>
                <Text style={styles.lineMeta}>{a.decision.replace(/_/g, ' ')}</Text>
              </View>
            ))
          )}
        </Section>

        <Section title="RECENT ACTIONS">
          {actionReceipts.length === 0 ? (
            <Text style={styles.empty}>No actions recorded yet</Text>
          ) : (
            actionReceipts.map((a) => (
              <View key={a.action_id} style={styles.lineRow}>
                <Text style={styles.lineText}>{a.action_type.replace(/_/g, ' ')}</Text>
                <Text style={styles.lineMeta}>{a.status}</Text>
              </View>
            ))
          )}
        </Section>

        <Section title="BODIES">
          {bodyCapabilities.length === 0 ? (
            <Text style={styles.empty}>No bodies have reported in yet</Text>
          ) : (
            bodyCapabilities.map((b) => (
              <View key={b.name} style={styles.lineRow}>
                <Dot ok={b.alive} />
                <Text style={styles.lineText}>{b.name} · {b.kind}</Text>
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
  kicker: { fontSize: 11, fontWeight: '700', letterSpacing: 1.2, color: colors.accent, marginBottom: spacing.sm },
  subtitle: { fontSize: 11, color: colors.textMuted, marginBottom: spacing.xs },
  bigValue: { fontSize: 22, fontWeight: '700', color: colors.text, textTransform: 'capitalize' },
  bigValueSmall: { fontSize: fontSizes.md, fontWeight: '600', color: colors.text, marginLeft: spacing.sm },
  statGrid: { flexDirection: 'row', marginTop: spacing.sm },
  stat: { marginRight: spacing.lg },
  statLabel: { fontSize: 11, color: colors.textMuted },
  statValue: { fontSize: 20, fontWeight: '700', color: colors.text },
  lineRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 4 },
  lineText: { flex: 1, fontSize: fontSizes.sm, color: colors.textSecondary },
  lineMeta: { fontSize: 11, color: colors.textMuted, marginLeft: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.sm },
  warn: { fontSize: fontSizes.sm, color: colors.warning, marginTop: 2 },
  note: { fontSize: 11, color: colors.textMuted, marginTop: spacing.xs, fontStyle: 'italic' },
  empty: { fontSize: fontSizes.sm, color: colors.textMuted, fontStyle: 'italic' },
  originTag: {
    fontSize: 10, fontWeight: '700', paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: borderRadius.full, marginRight: spacing.sm, overflow: 'hidden',
  },
  originDavid: { backgroundColor: 'rgba(56, 189, 248, 0.16)', color: colors.hues.sky },
  originSara: { backgroundColor: 'rgba(167, 139, 250, 0.16)', color: colors.hues.violet },
});

import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  StyleSheet,
  Text,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RouteProp, useRoute, useNavigation } from '@react-navigation/native';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

// Tap-to-context screen for narrator (System AI) broadcasts. iOS truncates
// long push bodies in the collapsed banner — even long-press has limits.
// This screen always shows the full title, body, subtitle, trigger context,
// and severity styling, so any push body length is readable.

interface SystemEvent {
  id: string;
  user_id: string;
  type: string;
  title: string;
  body: string;
  subtitle: string | null;
  severity: string;
  trigger_name: string;
  trigger_context: Record<string, any>;
  ttl_seconds: number;
  sound: string | null;
  delivered_to: string[];
  suppressed: boolean;
  suppression_reason: string | null;
  created_at: string;
}

interface RouteParams {
  eventId: string;
  // Optional pre-loaded payload so the screen renders instantly when push
  // tap supplies the body in `extra_push_data`. We refresh from the API
  // anyway to pull the full trigger_context.
  prefill?: Partial<SystemEvent>;
}

// Severity → accent. Mirrors the desktop popup and webapp ticker so the
// same broadcast feels consistent across surfaces.
const SEVERITY_ACCENTS: Record<string, { color: string; tint: string; label: string }> = {
  roast:       { color: '#f87171', tint: 'rgba(248, 113, 113, 0.12)', label: 'ROAST' },
  observation: { color: '#94a3b8', tint: 'rgba(148, 163, 184, 0.10)', label: 'OBSERVATION' },
  achievement: { color: '#fbbf24', tint: 'rgba(251, 191, 36, 0.14)', label: 'ACHIEVEMENT' },
  patch_note:  { color: '#60a5fa', tint: 'rgba(96, 165, 250, 0.12)', label: 'PATCH NOTES' },
  sponsored:   { color: '#d946ef', tint: 'rgba(217, 70, 239, 0.12)', label: 'SPONSORED' },
  grudging:    { color: '#cbd5e1', tint: 'rgba(203, 213, 225, 0.10)', label: 'GRUDGING' },
  deflected:   { color: '#86efac', tint: 'rgba(134, 239, 172, 0.10)', label: 'NOTED' },
};

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 45) return 'just now';
  if (sec < 90) return '1 minute ago';
  if (sec < 3600) return `${Math.round(sec / 60)} minutes ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} hours ago`;
  return `${Math.round(sec / 86400)} days ago`;
}

export default function SystemEventDetailScreen() {
  const route = useRoute<RouteProp<{ params: RouteParams }, 'params'>>();
  const navigation = useNavigation();
  const { eventId, prefill } = route.params || ({} as RouteParams);

  const [event, setEvent] = useState<SystemEvent | null>(() => {
    if (!prefill) return null;
    // Build a partial event from prefill so the screen renders immediately.
    return {
      id: eventId,
      user_id: '',
      type: prefill.severity || 'observation',
      title: prefill.title || 'System Broadcast',
      body: prefill.body || '',
      subtitle: prefill.subtitle ?? null,
      severity: prefill.severity || 'observation',
      trigger_name: prefill.trigger_name || '',
      trigger_context: prefill.trigger_context || {},
      ttl_seconds: 30,
      sound: null,
      delivered_to: [],
      suppressed: false,
      suppression_reason: null,
      created_at: new Date().toISOString(),
    } as SystemEvent;
  });
  const [loading, setLoading] = useState<boolean>(!prefill);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!eventId) {
      setError('Missing event id');
      setLoading(false);
      return;
    }
    try {
      const data = await apiClient.get<SystemEvent>(`/api/narrator/events/${eventId}`);
      setEvent(data);
      setError(null);
    } catch (e: any) {
      console.warn('[SystemEventDetail] load failed:', e?.message);
      // If we have a prefill, keep showing it; otherwise surface the error.
      if (!event) setError('Could not load event. It may have been cleared.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [eventId, event]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  if (loading && !event) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} />
        </View>
      </SafeAreaView>
    );
  }

  if (error && !event) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.button} onPress={() => navigation.goBack()}>
            <Text style={styles.buttonText}>Back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (!event) {
    return <SafeAreaView style={styles.safe} />;
  }

  const accent = SEVERITY_ACCENTS[event.severity] || SEVERITY_ACCENTS.observation;
  const ctxKeys = Object.keys(event.trigger_context || {});

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
      >
        <View style={[styles.header, { backgroundColor: accent.tint, borderColor: accent.color + '55' }]}>
          <View style={[styles.severityStripe, { backgroundColor: accent.color }]} />
          <View style={styles.headerInner}>
            <View style={styles.metaRow}>
              <Text style={[styles.severityLabel, { color: accent.color }]}>{accent.label}</Text>
              <Text style={styles.metaDot}>·</Text>
              <Text style={styles.metaText}>{event.trigger_name}</Text>
            </View>
            <Text style={styles.title} accessibilityRole="header">{event.title}</Text>
            {!!event.subtitle && <Text style={styles.subtitle}>{event.subtitle}</Text>}
            <Text style={styles.timestamp}>{relativeTime(event.created_at)}</Text>
          </View>
        </View>

        <View style={styles.bodyCard}>
          <Text style={styles.body} selectable>{event.body}</Text>
        </View>

        {event.suppressed && (
          <View style={styles.suppressedCard}>
            <Text style={styles.suppressedLabel}>SILENT</Text>
            <Text style={styles.suppressedText}>
              The System chose not to broadcast this one.
              {event.suppression_reason ? ` Reason: ${event.suppression_reason}.` : ''}
            </Text>
          </View>
        )}

        {ctxKeys.length > 0 && (
          <View style={styles.contextCard}>
            <Text style={styles.contextHeader}>Trigger context</Text>
            {ctxKeys.map((k) => (
              <View key={k} style={styles.contextRow}>
                <Text style={styles.contextKey}>{k}</Text>
                <Text style={styles.contextValue} selectable>
                  {formatValue(event.trigger_context[k])}
                </Text>
              </View>
            ))}
          </View>
        )}

        {event.delivered_to.length > 0 && (
          <View style={styles.deliveredCard}>
            <Text style={styles.contextHeader}>Delivered to</Text>
            <View style={styles.chipRow}>
              {event.delivered_to.map((d, i) => (
                <View key={i} style={styles.chip}>
                  <Text style={styles.chipText}>{d}</Text>
                </View>
              ))}
            </View>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function formatValue(v: any): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { flex: 1 },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  errorText: { color: colors.textSecondary, fontSize: fontSizes.md, marginBottom: spacing.md, textAlign: 'center' },
  button: { backgroundColor: colors.primary, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: borderRadius.md },
  buttonText: { color: colors.text, fontWeight: '600' },

  header: {
    position: 'relative',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    paddingLeft: spacing.md + 6,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  severityStripe: {
    position: 'absolute',
    left: 0, top: 8, bottom: 8,
    width: 4,
    borderTopRightRadius: 2,
    borderBottomRightRadius: 2,
  },
  headerInner: {},
  metaRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.xs },
  severityLabel: { fontSize: 11, fontWeight: '800', letterSpacing: 1.4 },
  metaDot: { color: colors.textMuted, marginHorizontal: spacing.xs },
  metaText: { color: colors.textMuted, fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase' },
  title: { color: colors.text, fontSize: 22, fontWeight: '800', lineHeight: 28, letterSpacing: 0.5 },
  subtitle: { color: colors.textSecondary, fontSize: fontSizes.md, fontStyle: 'italic', marginTop: spacing.xs },
  timestamp: { color: colors.textMuted, fontSize: fontSizes.xs, marginTop: spacing.sm },

  bodyCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  body: { color: colors.text, fontSize: fontSizes.md, lineHeight: 24 },

  suppressedCard: {
    backgroundColor: 'rgba(148, 163, 184, 0.06)',
    borderRadius: borderRadius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(148, 163, 184, 0.2)',
    marginBottom: spacing.md,
  },
  suppressedLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '700', letterSpacing: 1.5, marginBottom: spacing.xs },
  suppressedText: { color: colors.textSecondary, fontSize: fontSizes.sm, lineHeight: 20 },

  contextCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  contextHeader: { color: colors.textSecondary, fontSize: 11, fontWeight: '700', letterSpacing: 1.2, textTransform: 'uppercase', marginBottom: spacing.sm },
  contextRow: { marginBottom: spacing.sm },
  contextKey: { color: colors.textMuted, fontSize: 11, fontFamily: 'Menlo', marginBottom: 2 },
  contextValue: { color: colors.text, fontSize: fontSizes.sm, fontFamily: 'Menlo', lineHeight: 20 },

  deliveredCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  chip: { backgroundColor: colors.surfaceLight, paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: borderRadius.sm },
  chipText: { color: colors.textSecondary, fontSize: 11, fontFamily: 'Menlo' },
});

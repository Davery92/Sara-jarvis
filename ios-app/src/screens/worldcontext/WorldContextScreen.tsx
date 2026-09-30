import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
  AppState,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

// Read-only World Context screen (living-world-context plan, Phase 6).
// Same maintained snapshot as the web page and chat itself —
// backend/app/routes/world_context.py — never source reconciliation or a
// model call triggered by opening this screen.
//
// Freshness (living-world-context plan, Turn 3 follow-up): React Native has
// no native EventSource (see useSaraPresence.ts's own note on this), so
// this follows the app's established bounded-polling convention rather than
// an event transport — refetch on focus, on app foreground, and on a
// bounded interval while visible; stopped entirely once hidden or
// backgrounded (mirrors AssistantInboxScreen's focus+AppState pattern).

const POLL_INTERVAL_MS = 20000;

interface CoverageRow {
  domain: string;
  last_kind: string | null;
  last_event_sequence: number | null;
  updated_at: string | null;
  age_seconds: number | null;
  degraded: boolean;
}

interface WorldContextResponse {
  as_of: string;
  revision: number;
  last_event_sequence: number;
  current_situation: string[];
  brief: string;
  coverage: CoverageRow[];
  degraded_domains: string[];
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return 'unknown';
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function WorldContextScreen() {
  const [data, setData] = useState<WorldContextResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Mirrored outside state so `load` (called from a setInterval closure
  // and an AppState listener, not just render) always sees the latest
  // value without needing to be re-created on every fetch.
  const dataRef = useRef<WorldContextResponse | null>(null);
  const appStateRef = useRef(AppState.currentState);

  const load = useCallback(async (opts: { showSpinner?: boolean; manual?: boolean } = {}) => {
    const { showSpinner = false, manual = false } = opts;
    if (showSpinner) setLoading(true);
    if (manual) setRefreshing(true);
    try {
      const result = await apiClient.get<WorldContextResponse>('/api/world-context');
      // Bounded revision polling: only touch state (and re-render) when
      // something actually changed since the last successful fetch.
      if (!dataRef.current || result.revision !== dataRef.current.revision) {
        dataRef.current = result;
        setData(result);
      }
      setError(null);
    } catch (err) {
      // A background poll or a flaky connection must never blank out
      // what David is currently reading — only surface the error screen
      // when there's nothing on screen to preserve yet.
      if (!dataRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      // Quiet refresh if we already have something on screen (e.g.
      // returning from another tab) — spinner only on a true first load.
      load({ showSpinner: !dataRef.current });

      let pollTimer: ReturnType<typeof setInterval> | null = null;
      const startPolling = () => {
        if (pollTimer) return;
        pollTimer = setInterval(() => load(), POLL_INTERVAL_MS);
      };
      const stopPolling = () => {
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      };

      startPolling();

      const appStateSubscription = AppState.addEventListener('change', (nextState) => {
        const wasBackgrounded = appStateRef.current.match(/inactive|background/);
        const isNowBackgrounded = nextState.match(/inactive|background/);
        appStateRef.current = nextState;
        if (wasBackgrounded && nextState === 'active') {
          load();
          startPolling();
        } else if (isNowBackgrounded) {
          stopPolling();
        }
      });

      // Runs on blur (navigated away) as well as unmount — polling and
      // the AppState listener both stop the moment this screen isn't
      // what's visible, not just when the app itself backgrounds.
      return () => {
        stopPolling();
        appStateSubscription.remove();
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [load]),
  );

  const handleRefresh = () => {
    // Convenience only, per the plan — polling/focus/foreground already
    // keep this current, so a manual pull never needs to be the only way.
    load({ manual: true });
  };

  if (loading && !data) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>Loading world context...</Text>
      </View>
    );
  }

  if (error && !data) {
    return (
      <View style={styles.loadingContainer}>
        <Text style={styles.errorText}>Couldn't load World Context.</Text>
        <Text style={styles.errorDetail}>{error}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={() => load({ showSpinner: true })}>
          <Text style={styles.retryButtonText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!data) return null;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.primary} />
        }
      >
        <Text style={styles.subtitle}>
          What Sara currently understands about your world — read-only. As of{' '}
          {new Date(data.as_of).toLocaleTimeString()}, revision {data.revision}.
        </Text>

        {data.degraded_domains.length > 0 && (
          <View style={styles.warningCard}>
            <Text style={styles.warningText}>
              No recent activity observed for: {data.degraded_domains.join(', ')}. This may just
              mean nothing has happened there — not that anything is broken.
            </Text>
          </View>
        )}

        <Text style={styles.sectionHeader}>CURRENT SITUATION</Text>
        {data.current_situation.length === 0 ? (
          <Text style={styles.emptyText}>Nothing currently active.</Text>
        ) : (
          data.current_situation.map((line, i) => (
            <View key={i} style={styles.factCard}>
              <Text style={styles.factText}>{line}</Text>
            </View>
          ))
        )}

        <Text style={styles.sectionHeader}>RECENT DEVELOPMENTS &amp; UPCOMING</Text>
        <View style={styles.briefCard}>
          <Text style={styles.briefText}>{data.brief || 'Nothing notable.'}</Text>
        </View>

        <Text style={styles.sectionHeader}>SOURCE FRESHNESS</Text>
        {data.coverage.length === 0 ? (
          <Text style={styles.emptyText}>No activity observed yet.</Text>
        ) : (
          data.coverage.map((row) => (
            <View key={row.domain} style={styles.coverageRow}>
              <View style={styles.coverageLeft}>
                <View
                  style={[
                    styles.dot,
                    { backgroundColor: row.degraded ? colors.warning : colors.success },
                  ]}
                />
                <Text style={styles.coverageDomain}>{row.domain.replace(/_/g, ' ')}</Text>
              </View>
              <View style={styles.coverageRight}>
                <Text style={styles.coverageAge}>{formatAge(row.age_seconds)}</Text>
                {row.last_kind && <Text style={styles.coverageKind}>{row.last_kind}</Text>}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollContent: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
    padding: spacing.xl,
  },
  loadingText: {
    color: colors.textMuted,
    marginTop: spacing.md,
    fontSize: fontSizes.sm,
  },
  errorText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    marginBottom: spacing.xs,
  },
  errorDetail: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  retryButton: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  retryButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginBottom: spacing.md,
    lineHeight: 20,
  },
  warningCard: {
    backgroundColor: 'rgba(251, 191, 36, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.3)',
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  warningText: {
    color: colors.warning,
    fontSize: fontSizes.sm,
    lineHeight: 18,
  },
  sectionHeader: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.5,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
  factCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  factText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  briefCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  briefText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  coverageRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.xs,
  },
  coverageLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  coverageDomain: {
    color: colors.text,
    fontSize: fontSizes.sm,
    textTransform: 'capitalize',
  },
  coverageRight: {
    alignItems: 'flex-end',
  },
  coverageAge: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  coverageKind: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 2,
  },
});

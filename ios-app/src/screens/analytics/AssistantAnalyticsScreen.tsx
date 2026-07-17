import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import apiClient from '../../services/api';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';

type SummaryWindowDays = 7 | 30;

interface AssistantAnalyticsSummary {
  window_days: number;
  available?: boolean;
  note?: string | null;
  metrics: {
    daily_assistant_usage_days: number;
    chat_opens: number;
    inbox_opens: number;
    notification_to_chat_opens: number;
    suggested_action_completions: number;
    voice_usage: {
      hold_to_talk_starts: number;
      hands_free_enabled: number;
      voice_message_sends: number;
    };
  };
  event_counts: Record<string, number>;
}

const WINDOW_OPTIONS: SummaryWindowDays[] = [7, 30];

function createEmptySummary(windowDays: number, note?: string): AssistantAnalyticsSummary {
  return {
    window_days: windowDays,
    available: false,
    note: note || 'Analytics backend is unavailable right now. Showing an empty summary.',
    metrics: {
      daily_assistant_usage_days: 0,
      chat_opens: 0,
      inbox_opens: 0,
      notification_to_chat_opens: 0,
      suggested_action_completions: 0,
      voice_usage: {
        hold_to_talk_starts: 0,
        hands_free_enabled: 0,
        voice_message_sends: 0,
      },
    },
    event_counts: {},
  };
}

function formatEventLabel(eventType: string): string {
  return eventType
    .replace(/^assistant\./, '')
    .split('_')
    .join(' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function AssistantAnalyticsScreen() {
  const [windowDays, setWindowDays] = useState<SummaryWindowDays>(7);
  const [summary, setSummary] = useState<AssistantAnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const disabledUntilRef = useRef(0);

  const loadSummary = useCallback(async (showLoading = true) => {
    if (Date.now() < disabledUntilRef.current) {
      setSummary((current) => current || createEmptySummary(
        windowDays,
        'Assistant analytics is temporarily unavailable from the current backend. Showing placeholders for now.',
      ));
      setLoading(false);
      setRefreshing(false);
      return;
    }

    if (showLoading) setLoading(true);
    try {
      const result = await apiClient.get<AssistantAnalyticsSummary>(
        `/api/assistant-analytics/summary?days=${windowDays}`,
      );
      disabledUntilRef.current = 0;
      setSummary(result);
    } catch {
      disabledUntilRef.current = Date.now() + 60_000;
      setSummary(
        createEmptySummary(
          windowDays,
          'Assistant analytics is not reachable from the current backend yet. Showing placeholders for now.',
        ),
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [windowDays]);

  useFocusEffect(
    useCallback(() => {
      loadSummary();
    }, [loadSummary]),
  );

  const statCards = useMemo(() => {
    if (!summary) return [];

    return [
      {
        key: 'usage',
        label: 'Active days',
        value: `${summary.metrics.daily_assistant_usage_days}/${summary.window_days}`,
        description: 'Days with a real assistant message sent.',
        tone: colors.assistant.action,
      },
      {
        key: 'notification',
        label: 'Notification to chat',
        value: summary.metrics.notification_to_chat_opens.toString(),
        description: 'Notification-origin chat handoffs opened.',
        tone: colors.assistant.alert,
      },
      {
        key: 'suggested',
        label: 'Suggested actions',
        value: summary.metrics.suggested_action_completions.toString(),
        description: 'Suggested next steps that turned into messages.',
        tone: colors.assistant.passive,
      },
      {
        key: 'voice',
        label: 'Voice messages',
        value: summary.metrics.voice_usage.voice_message_sends.toString(),
        description: 'Voice replies sent across hold-to-talk and hands-free.',
        tone: colors.success,
      },
    ];
  }, [summary]);

  const detailedRows = useMemo(() => {
    if (!summary) return [];

    return [
      {
        key: 'chat_opens',
        label: 'Chat opens',
        value: summary.metrics.chat_opens,
      },
      {
        key: 'inbox_opens',
        label: 'Inbox opens',
        value: summary.metrics.inbox_opens,
      },
      {
        key: 'hold_to_talk',
        label: 'Hold-to-talk starts',
        value: summary.metrics.voice_usage.hold_to_talk_starts,
      },
      {
        key: 'hands_free',
        label: 'Hands-free enabled',
        value: summary.metrics.voice_usage.hands_free_enabled,
      },
    ];
  }, [summary]);

  if (loading && !summary) {
    return (
      <SafeAreaView style={styles.loadingContainer} edges={['bottom']}>
        <ActivityIndicator size="large" color={colors.primary} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              loadSummary(false);
            }}
            tintColor={colors.primary}
          />
        }
      >
        <View style={styles.hero}>
          <View style={styles.heroIconWrap}>
            <Ionicons name="analytics-outline" size={18} color={colors.assistant.action} />
          </View>
          <Text style={styles.heroEyebrow}>Phase 6</Text>
          <Text style={styles.heroTitle}>Assistant usage</Text>
          <Text style={styles.heroBody}>
            This is the first readout for whether the redesign is actually changing behavior, not just looking better.
          </Text>
        </View>

        {summary?.note ? (
          <View style={styles.noticeCard}>
            <Ionicons
              name={summary.available ? 'information-circle-outline' : 'cloud-offline-outline'}
              size={16}
              color={summary.available ? colors.assistant.passive : colors.warning}
            />
            <Text style={styles.noticeText}>{summary.note}</Text>
          </View>
        ) : null}

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.windowRow}
        >
          {WINDOW_OPTIONS.map((option) => {
            const active = option === windowDays;
            return (
              <TouchableOpacity
                key={option}
                style={[styles.windowChip, active && styles.windowChipActive]}
                onPress={() => setWindowDays(option)}
                activeOpacity={0.82}
              >
                <Text style={[styles.windowChipText, active && styles.windowChipTextActive]}>
                  Last {option} days
                </Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        <View style={styles.statGrid}>
          {statCards.map((card) => (
            <View key={card.key} style={[styles.statCard, { borderColor: `${card.tone}33` }]}>
              <Text style={[styles.statLabel, { color: card.tone }]}>{card.label}</Text>
              <Text style={styles.statValue}>{card.value}</Text>
              <Text style={styles.statDescription}>{card.description}</Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Core signals</Text>
          <View style={styles.sectionCard}>
            {detailedRows.map((row, index) => (
              <View
                key={row.key}
                style={[styles.detailRow, index < detailedRows.length - 1 && styles.detailRowBorder]}
              >
                <Text style={styles.detailLabel}>{row.label}</Text>
                <Text style={styles.detailValue}>{row.value}</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Recorded events</Text>
          <Text style={styles.sectionDescription}>
            Raw event counts from the assistant instrumentation window.
          </Text>
          <View style={styles.sectionCard}>
            {Object.entries(summary?.event_counts || {}).length > 0 ? (
              Object.entries(summary?.event_counts || {}).map(([eventType, count], index, rows) => (
                <View
                  key={eventType}
                  style={[styles.detailRow, index < rows.length - 1 && styles.detailRowBorder]}
                >
                  <Text style={styles.detailLabel}>{formatEventLabel(eventType)}</Text>
                  <Text style={styles.detailValue}>{count}</Text>
                </View>
              ))
            ) : (
              <View style={styles.emptyState}>
                <Text style={styles.emptyStateText}>No assistant events recorded yet.</Text>
              </View>
            )}
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  hero: {
    padding: spacing.lg,
    borderRadius: borderRadius.xl,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    ...shadows.sm,
  },
  heroIconWrap: {
    width: 32,
    height: 32,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.actionSoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  heroEyebrow: {
    color: colors.assistant.passive,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.xs,
  },
  heroTitle: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginBottom: spacing.sm,
  },
  heroBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  windowRow: {
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  noticeCard: {
    marginTop: spacing.md,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelMuted,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  noticeText: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  windowChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    backgroundColor: colors.assistant.panelMuted,
  },
  windowChipActive: {
    borderColor: colors.assistant.borderStrong,
    backgroundColor: colors.assistant.actionSoft,
  },
  windowChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  windowChipTextActive: {
    color: colors.primary,
  },
  statGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  statCard: {
    width: '48%',
    minWidth: 150,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    ...shadows.sm,
  },
  statLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  statValue: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginTop: spacing.sm,
  },
  statDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  section: {
    marginTop: spacing.lg,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  sectionDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginBottom: spacing.sm,
  },
  sectionCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    overflow: 'hidden',
    ...shadows.sm,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    padding: spacing.md,
  },
  detailRowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
  },
  detailLabel: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  detailValue: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  emptyState: {
    padding: spacing.lg,
    alignItems: 'center',
  },
  emptyStateText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
});

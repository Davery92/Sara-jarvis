import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { calendarService, CalendarEvent } from '../../services/calendar';
import apiClient from '../../services/api';
import { weatherService, WeatherData } from '../../services/weather';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';

interface SaraOverviewPanelProps {
  onPrompt: (prompt: string) => void;
  onOpenCalendar: () => void;
  onOpenTasks: () => void;
  onOpenInbox: () => void;
}

interface DailyTask {
  id: string;
  title: string;
  is_completed: boolean;
}

interface OverviewState {
  totalTasks: number;
  openTasks: number;
  nextEvent: CalendarEvent | null;
  inboxUnread: number;
  weather: WeatherData | null;
}

function formatEventTime(dateString: string): string {
  return new Date(dateString).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function findNextEvent(events: CalendarEvent[]): CalendarEvent | null {
  const now = Date.now();
  const sorted = [...events].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  );
  return sorted.find((event) => new Date(event.end_time).getTime() >= now) || sorted[0] || null;
}

export default function SaraOverviewPanel({
  onPrompt,
  onOpenCalendar,
  onOpenTasks,
  onOpenInbox,
}: SaraOverviewPanelProps) {
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<OverviewState>({
    totalTasks: 0,
    openTasks: 0,
    nextEvent: null,
    inboxUnread: 0,
    weather: null,
  });

  const loadOverview = useCallback(async () => {
    try {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];

      const [tasksResult, eventsResult, weatherResult, inboxStatsResult, attentionResult] =
        await Promise.allSettled([
          apiClient.getDailyTasks(today) as Promise<DailyTask[]>,
          calendarService.getEvents(today, today),
          weatherService.getCurrentWeather(),
          apiClient.getInboxStats(),
          apiClient.getAttentionCount(),
        ]);

      const tasks =
        tasksResult.status === 'fulfilled' && Array.isArray(tasksResult.value)
          ? tasksResult.value
          : [];
      const events =
        eventsResult.status === 'fulfilled' && Array.isArray(eventsResult.value)
          ? eventsResult.value
          : [];
      const weather = weatherResult.status === 'fulfilled' ? weatherResult.value : null;
      const inboxUnread =
        (inboxStatsResult.status === 'fulfilled' ? inboxStatsResult.value?.unread || 0 : 0) +
        (attentionResult.status === 'fulfilled' ? attentionResult.value?.unread || 0 : 0);

      setOverview({
        totalTasks: tasks.length,
        openTasks: tasks.filter((task) => !task.is_completed).length,
        nextEvent: findNextEvent(events),
        inboxUnread,
        weather: weather || null,
      });
    } catch (error) {
      console.error('[SaraOverview] Failed to load overview:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOverview();
    const interval = setInterval(loadOverview, 60_000);
    return () => clearInterval(interval);
  }, [loadOverview]);

  const summaryText = useMemo(() => {
    if (loading) {
      return 'Loading your day...';
    }

    if (overview.openTasks > 0 && overview.nextEvent) {
      return `${overview.openTasks} open tasks and your next event starts at ${formatEventTime(
        overview.nextEvent.start_time
      )}.`;
    }

    if (overview.openTasks > 0) {
      return `${overview.openTasks} open tasks are waiting for you.`;
    }

    if (overview.nextEvent) {
      return `Your next event is ${overview.nextEvent.title} at ${formatEventTime(
        overview.nextEvent.start_time
      )}.`;
    }

    if (overview.inboxUnread > 0) {
      return `${overview.inboxUnread} items still need attention.`;
    }

    return 'The surface is clear. Use Sara to plan, triage, or capture what matters next.';
  }, [loading, overview]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Text style={styles.title}>Today</Text>
          <Text style={styles.subtitle}>{summaryText}</Text>
        </View>
        <TouchableOpacity style={styles.refreshButton} onPress={loadOverview} disabled={loading}>
          {loading ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Text style={styles.refreshButtonText}>Refresh</Text>
          )}
        </TouchableOpacity>
      </View>

      <View style={styles.summaryGrid}>
        <TouchableOpacity style={[styles.summaryCard, styles.summaryCardAction]} activeOpacity={0.8} onPress={onOpenTasks}>
          <Text style={styles.summaryLabel}>Tasks</Text>
          <Text style={styles.summaryValue}>
            {overview.openTasks > 0 ? overview.openTasks : 'Clear'}
          </Text>
          <Text style={styles.summaryMeta}>
            {overview.totalTasks > 0 ? `${overview.totalTasks} planned today` : 'No tasks yet'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity style={[styles.summaryCard, styles.summaryCardPassive]} activeOpacity={0.8} onPress={onOpenCalendar}>
          <Text style={styles.summaryLabel}>Next Up</Text>
          <Text style={styles.summaryValue} numberOfLines={1}>
            {overview.nextEvent ? formatEventTime(overview.nextEvent.start_time) : 'Open'}
          </Text>
          <Text style={styles.summaryMeta} numberOfLines={2}>
            {overview.nextEvent ? overview.nextEvent.title : 'No events on the calendar'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.summaryCard,
            overview.inboxUnread > 0 ? styles.summaryCardAlert : styles.summaryCardPassive,
          ]}
          activeOpacity={0.8}
          onPress={onOpenInbox}
        >
          <Text style={styles.summaryLabel}>Inbox</Text>
          <Text style={styles.summaryValue}>
            {overview.inboxUnread > 0 ? overview.inboxUnread : 'Quiet'}
          </Text>
          <Text style={styles.summaryMeta}>
            {overview.inboxUnread > 0 ? 'Items need attention' : 'Nothing urgent right now'}
          </Text>
        </TouchableOpacity>

        <View style={[styles.summaryCard, styles.summaryCardNeutral]}>
          <Text style={styles.summaryLabel}>Weather</Text>
          <Text style={styles.summaryValue}>
            {overview.weather ? `${overview.weather.temperature}°` : '—'}
          </Text>
          <Text style={styles.summaryMeta} numberOfLines={2}>
            {overview.weather
              ? `${weatherService.getWeatherEmoji(overview.weather.condition)} ${overview.weather.description}`
              : 'Weather unavailable'}
          </Text>
        </View>
      </View>

      <View style={styles.actionsRow}>
        <TouchableOpacity
          style={[styles.actionChip, styles.actionChipPrimary]}
          onPress={() =>
            onPrompt(
              'Look at my tasks, calendar, inbox, and current context. Give me a short plan for today.'
            )
          }
        >
          <Text style={styles.actionChipText}>Plan My Day</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionChip, styles.actionChipSecondary]}
          onPress={() =>
            onPrompt(
              'Based on my tasks, calendar, and recent activity, what should I focus on next?'
            )
          }
        >
          <Text style={[styles.actionChipText, styles.actionChipTextSecondary]}>What Matters Now?</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionChip, styles.actionChipSecondary]}
          onPress={() => onPrompt('Review my inbox and attention queue, then tell me what is worth acting on.')}
        >
          <Text style={[styles.actionChipText, styles.actionChipTextSecondary]}>Review Inbox</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionChip, styles.actionChipSecondary]}
          onPress={() => onPrompt('Help me close out today well. What should I wrap up before tonight?')}
        >
          <Text style={[styles.actionChipText, styles.actionChipTextSecondary]}>Close Today</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    gap: spacing.md,
    ...shadows.sm,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  headerCopy: {
    flex: 1,
    gap: spacing.xs,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  refreshButton: {
    minWidth: 72,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: colors.assistant.panelMuted,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  refreshButtonText: {
    color: colors.assistant.passive,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  summaryGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  summaryCard: {
    width: '48%',
    minHeight: 96,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelMuted,
    gap: spacing.xs,
  },
  summaryCardAction: {
    backgroundColor: colors.assistant.actionSoft,
  },
  summaryCardPassive: {
    backgroundColor: colors.assistant.passiveSoft,
  },
  summaryCardAlert: {
    backgroundColor: colors.assistant.alertSoft,
  },
  summaryCardNeutral: {
    backgroundColor: colors.assistant.panelRaised,
  },
  summaryLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  summaryValue: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  summaryMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 16,
  },
  actionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  actionChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
  },
  actionChipPrimary: {
    borderColor: colors.assistant.action,
    backgroundColor: colors.assistant.action,
  },
  actionChipSecondary: {
    borderColor: colors.assistant.border,
    backgroundColor: colors.assistant.panelMuted,
  },
  actionChipText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  actionChipTextSecondary: {
    color: colors.assistant.passive,
  },
});

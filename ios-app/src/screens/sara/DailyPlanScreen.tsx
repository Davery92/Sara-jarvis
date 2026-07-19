import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';

interface ActivityEntry {
  id: string;
  created_at: string;
  kind: string;
  summary: string;
  body?: string | null;
}

interface Focus {
  topic: string | null;
  why: string | null;
  set_at: string | null;
  updated_at: string | null;
}

interface ACSSnapshot {
  focus: Focus;
  recent_activity: ActivityEntry[];
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const diffMins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

export default function DailyPlanScreen() {
  const [snapshot, setSnapshot] = useState<ACSSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchSnapshot = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/v2/snapshot');
      setSnapshot(data as ACSSnapshot);
    } catch {
      // graceful degradation
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
  }, [fetchSnapshot]);

  const onRefresh = () => {
    setRefreshing(true);
    fetchSnapshot();
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const focus = snapshot?.focus;
  const activity = snapshot?.recent_activity || [];

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.textMuted}
          />
        }
      >
        {focus?.topic ? (
          <View style={styles.focusCard}>
            <Text style={styles.focusLabel}>{'🎯'} Currently Focused On</Text>
            <Text style={styles.focusTopic}>{focus.topic}</Text>
            {focus.why ? <Text style={styles.focusWhy}>{focus.why}</Text> : null}
            {focus.set_at ? (
              <Text style={styles.focusTime}>since {timeAgo(focus.set_at)}</Text>
            ) : null}
          </View>
        ) : (
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyEmoji}>{'🎯'}</Text>
            <Text style={styles.emptyTitle}>No Active Focus</Text>
            <Text style={styles.emptySubtitle}>
              Sara hasn't set a focus for herself right now.
            </Text>
          </View>
        )}

        {activity.length > 0 && (
          <View style={styles.activitySection}>
            <Text style={styles.sectionLabel}>Recent Activity</Text>
            {activity.map(entry => (
              <View key={entry.id} style={styles.activityRow}>
                <Text style={styles.activitySummary}>{entry.summary || entry.kind}</Text>
                <Text style={styles.activityTime}>{timeAgo(entry.created_at)}</Text>
              </View>
            ))}
          </View>
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing.xl * 2,
  },
  focusCard: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  focusLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  focusTopic: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  focusWhy: {
    fontSize: 14,
    color: colors.textSecondary,
    lineHeight: 20,
  },
  focusTime: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  emptyContainer: {
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 60,
    paddingBottom: spacing.lg,
  },
  emptyEmoji: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptySubtitle: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
    textAlign: 'center',
  },
  activitySection: {
    marginTop: spacing.md,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  activityRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  activitySummary: {
    flex: 1,
    fontSize: 13,
    color: colors.text,
    marginRight: spacing.sm,
  },
  activityTime: {
    fontSize: 11,
    color: colors.textMuted,
  },
});

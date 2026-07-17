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
import Markdown from 'react-native-markdown-display';
import { colors, spacing, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';

interface ACSSnapshot {
  daily_plan?: string;
}

export default function DailyPlanScreen() {
  const [plan, setPlan] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchPlan = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/snapshot');
      setPlan((data as ACSSnapshot).daily_plan || null);
    } catch {
      // graceful degradation
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchPlan();
  }, [fetchPlan]);

  const onRefresh = () => {
    setRefreshing(true);
    fetchPlan();
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

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
        {plan ? (
          <Markdown style={markdownStyles}>{plan}</Markdown>
        ) : (
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyEmoji}>{'\uD83D\uDCCB'}</Text>
            <Text style={styles.emptyTitle}>No Plan Yet</Text>
            <Text style={styles.emptySubtitle}>
              Sara generates a new plan each morning at 7 AM.
            </Text>
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
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 100,
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
});

const markdownStyles = {
  body: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 24,
  },
  heading2: {
    fontSize: fontSizes.xl,
    fontWeight: '600' as const,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  heading3: {
    fontSize: fontSizes.lg,
    fontWeight: '600' as const,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  paragraph: {
    marginBottom: spacing.sm,
    color: colors.text,
  },
  strong: {
    fontWeight: 'bold' as const,
    color: colors.text,
  },
  listItem: {
    color: colors.text,
  },
  code_inline: {
    color: colors.primary,
    backgroundColor: 'transparent',
    fontSize: 14,
    fontFamily: undefined,
  },
  code_block: {
    color: colors.text,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 8,
    padding: spacing.sm,
    fontSize: 13,
  },
  fence: {
    color: colors.text,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 8,
    padding: spacing.sm,
    fontSize: 13,
  },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.md,
  },
};

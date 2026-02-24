import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  Linking,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';

interface IntelligenceItem {
  id: string;
  source: string;
  source_category: string;
  title: string;
  summary: string | null;
  url: string | null;
  novelty_score: number;
  relevance_score: number;
  discovered_at: string | null;
  dismissed: boolean;
}

type CategoryFilter = 'all' | 'ai_research' | 'local_ai' | 'broader_tech';

const SOURCE_LABELS: Record<string, string> = {
  arxiv_cs_ai: 'arXiv AI',
  arxiv_cs_cl: 'arXiv CL',
  arxiv_cs_lg: 'arXiv ML',
  openai_blog: 'OpenAI',
  anthropic_blog: 'Anthropic',
  google_ai_blog: 'Google AI',
  meta_ai_blog: 'Meta AI',
  huggingface_papers: 'HF Papers',
  r_locallama: 'r/LocalLLaMA',
  r_machinelearning: 'r/ML',
  r_programming: 'r/prog',
  ollama_releases: 'Ollama',
  llamacpp_releases: 'llama.cpp',
  exllamav2_releases: 'ExLlamaV2',
  vllm_releases: 'vLLM',
  hackernews: 'HN',
  ars_technica: 'Ars',
  techcrunch: 'TC',
  krebs_on_security: 'Krebs',
  the_record: 'Record',
};

const CATEGORY_COLORS: Record<string, string> = {
  ai_research: '#10b981',
  local_ai: '#6366f1',
  broader_tech: '#f59e0b',
};

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function scoreColor(score: number): string {
  if (score >= 0.8) return '#10b981';
  if (score >= 0.6) return '#14b8a6';
  if (score >= 0.4) return '#eab308';
  return '#6b7280';
}

export default function IntelligenceScreen() {
  const [items, setItems] = useState<IntelligenceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [category, setCategory] = useState<CategoryFilter>('all');

  const loadFeed = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const params: Record<string, string> = { limit: '50', offset: '0' };
      if (category !== 'all') params.source_category = category;

      const queryStr = new URLSearchParams(params).toString();
      const response = await apiClient.get(`/api/intelligence/feed?${queryStr}`);
      setItems(response?.items || []);
    } catch (err) {
      console.error('Failed to load intelligence feed:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [category]);

  useEffect(() => {
    loadFeed();
  }, [loadFeed]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadFeed(false);
  };

  const handleDismiss = async (itemId: string) => {
    try {
      await apiClient.post(`/api/intelligence/${itemId}/dismiss`);
      setItems(prev => prev.filter(i => i.id !== itemId));
    } catch (err) {
      console.error('Failed to dismiss:', err);
    }
  };

  const handleDigDeeper = async (itemId: string) => {
    try {
      await apiClient.post(`/api/intelligence/${itemId}/dig-deeper`);
      Alert.alert('Research Dispatched', 'A deep research agent has been dispatched to investigate this topic.');
    } catch (err) {
      Alert.alert('Error', 'Failed to dispatch research agent.');
    }
  };

  const handleOpenUrl = (url: string | null) => {
    if (url) {
      Linking.openURL(url);
    }
  };

  const categories: { key: CategoryFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'ai_research', label: 'AI Research' },
    { key: 'local_ai', label: 'Local AI' },
    { key: 'broader_tech', label: 'Tech' },
  ];

  const renderItem = ({ item }: { item: IntelligenceItem }) => {
    const catColor = CATEGORY_COLORS[item.source_category] || colors.textSecondary;

    return (
      <TouchableOpacity
        style={styles.card}
        onPress={() => handleOpenUrl(item.url)}
        activeOpacity={0.7}
      >
        <View style={styles.cardHeader}>
          <View style={[styles.sourceTag, { backgroundColor: catColor + '20' }]}>
            <Text style={[styles.sourceText, { color: catColor }]}>
              {SOURCE_LABELS[item.source] || item.source}
            </Text>
          </View>
          <View style={styles.scores}>
            <Text style={[styles.scoreText, { color: scoreColor(item.novelty_score) }]}>
              N{(item.novelty_score * 100).toFixed(0)}
            </Text>
            <Text style={[styles.scoreText, { color: scoreColor(item.relevance_score) }]}>
              R{(item.relevance_score * 100).toFixed(0)}
            </Text>
          </View>
          <Text style={styles.timeText}>{timeAgo(item.discovered_at)}</Text>
        </View>

        <Text style={styles.title} numberOfLines={3}>
          {item.title}
        </Text>

        {item.summary && (
          <Text style={styles.summary} numberOfLines={2}>
            {item.summary}
          </Text>
        )}

        <View style={styles.actions}>
          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => handleDigDeeper(item.id)}
          >
            <Text style={styles.digDeeperText}>Dig Deeper</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.dismissButton}
            onPress={() => handleDismiss(item.id)}
          >
            <Text style={styles.dismissText}>Dismiss</Text>
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Intelligence Feed</Text>
      </View>

      {/* Category Filter Pills */}
      <View style={styles.filterRow}>
        {categories.map(cat => (
          <TouchableOpacity
            key={cat.key}
            style={[
              styles.filterPill,
              category === cat.key && styles.filterPillActive,
            ]}
            onPress={() => setCategory(cat.key)}
          >
            <Text
              style={[
                styles.filterPillText,
                category === cat.key && styles.filterPillTextActive,
              ]}
            >
              {cat.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Feed */}
      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <FlatList
          data={items}
          renderItem={renderItem}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={colors.primary}
            />
          }
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>No intelligence items</Text>
              <Text style={styles.emptySubtext}>Pull to refresh or wait for the next scan</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  headerTitle: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
  },
  filterRow: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    gap: spacing.xs,
  },
  filterPill: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  filterPillActive: {
    backgroundColor: colors.primary + '20',
    borderColor: colors.primary,
  },
  filterPillText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  filterPillTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xl,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  sourceTag: {
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  sourceText: {
    fontSize: 10,
    fontWeight: '600',
  },
  scores: {
    flexDirection: 'row',
    gap: 4,
  },
  scoreText: {
    fontSize: 10,
    fontFamily: 'monospace',
    fontWeight: '600',
  },
  timeText: {
    fontSize: 10,
    color: colors.textSecondary,
    marginLeft: 'auto',
  },
  title: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    lineHeight: 20,
  },
  summary: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginTop: spacing.xs,
    lineHeight: 18,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  actionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    backgroundColor: '#4f46e520',
  },
  digDeeperText: {
    fontSize: fontSizes.sm,
    color: '#818cf8',
    fontWeight: '600',
  },
  dismissButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surface,
  },
  dismissText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xl * 2,
  },
  emptyText: {
    fontSize: fontSizes.lg,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  emptySubtext: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
});

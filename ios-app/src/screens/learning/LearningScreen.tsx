import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';
import { Ionicons } from '@expo/vector-icons';
import { navigateToChat } from '../../services/navigation';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Topic {
  id: string;
  user_id: string;
  parent_id: string | null;
  title: string;
  description: string | null;
  status: string;
  mastery_level: number;
  priority: number;
  created_at: string;
  updated_at: string;
}

interface ReviewItem {
  id: string;
  topic_id: string | null;
  source_id: string | null;
  concept: string | null;
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_at: string | null;
  last_reviewed_at: string | null;
}

interface ReviewQueue {
  due_count: number;
  items: ReviewItem[];
}

interface NextSession {
  topic_id: string;
  topic_title: string;
  suggested_duration: number;
  focus_areas: string[];
  reason: string;
}

type TabMode = 'topics' | 'review';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BASE = apiClient.baseURL || 'http://10.185.1.180:8000';

async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function statusColor(status: string): string {
  switch (status) {
    case 'active':
      return colors.success;
    case 'completed':
      return colors.primary;
    case 'paused':
      return colors.warning;
    default:
      return colors.textMuted;
  }
}

function priorityLabel(priority: number): string {
  if (priority >= 8) return 'High';
  if (priority >= 5) return 'Med';
  return 'Low';
}

function priorityColor(priority: number): string {
  if (priority >= 8) return colors.error;
  if (priority >= 5) return colors.warning;
  return colors.textMuted;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LearningScreen() {
  const [tab, setTab] = useState<TabMode>('topics');
  const [topics, setTopics] = useState<Topic[]>([]);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueue>({ due_count: 0, items: [] });
  const [nextSession, setNextSession] = useState<NextSession | null>(null);
  const [expandedTopicId, setExpandedTopicId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Topic name lookup for review items
  const topicNameMap = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const t of topics) {
      map[t.id] = t.title;
    }
    return map;
  }, [topics]);

  const loadData = useCallback(async () => {
    try {
      const [topicsData, reviewData, sessionData] = await Promise.allSettled([
        fetchJSON<Topic[]>('/api/learn/topics?include_all=true'),
        fetchJSON<ReviewQueue>('/api/learn/review-queue'),
        fetchJSON<NextSession>('/api/learn/path/next-session'),
      ]);

      if (topicsData.status === 'fulfilled') {
        setTopics(topicsData.value);
      }
      if (reviewData.status === 'fulfilled') {
        setReviewQueue(reviewData.value);
      }
      if (sessionData.status === 'fulfilled') {
        setNextSession(sessionData.value);
      } else {
        setNextSession(null);
      }
    } catch (error) {
      console.error('Failed to load learning data:', error);
      Alert.alert('Error', 'Failed to load learning data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    loadData();
  }, [loadData]);

  // ------ Grouped topics: active first, then completed, then paused ------
  const groupedTopics = React.useMemo(() => {
    const order: Record<string, number> = { active: 0, paused: 1, completed: 2 };
    return [...topics].sort((a, b) => {
      const oa = order[a.status] ?? 3;
      const ob = order[b.status] ?? 3;
      if (oa !== ob) return oa - ob;
      return b.priority - a.priority;
    });
  }, [topics]);

  // ------ Renderers ------

  const renderNextSessionCard = () => {
    if (!nextSession) return null;
    return (
      <View style={styles.nextSessionCard}>
        <Text style={styles.nextSessionLabel}>Next Session</Text>
        <Text style={styles.nextSessionTitle}>{nextSession.topic_title}</Text>
        <View style={styles.nextSessionMeta}>
          <Text style={styles.nextSessionDuration}>
            {nextSession.suggested_duration} min
          </Text>
          {nextSession.focus_areas && nextSession.focus_areas.length > 0 && (
            <Text style={styles.nextSessionFocus} numberOfLines={1}>
              Focus: {nextSession.focus_areas.join(', ')}
            </Text>
          )}
        </View>
        {nextSession.reason ? (
          <Text style={styles.nextSessionReason} numberOfLines={2}>
            {nextSession.reason}
          </Text>
        ) : null}
      </View>
    );
  };

  const openLearningPrompt = () => {
    const message = reviewQueue.due_count > 0
      ? `Help me work through my ${reviewQueue.due_count} due learning review${reviewQueue.due_count === 1 ? '' : 's'} and tell me what to study first.`
      : nextSession
        ? `Help me plan a ${nextSession.suggested_duration}-minute study session for ${nextSession.topic_title}.`
        : 'Help me decide what to learn next and suggest a focused study session.';

    navigateToChat({
      quickReply: {
        title: 'Learning',
        message,
        nudgeType: 'learning_focus',
      },
    });
  };

  const renderLearningGuideCard = () => {
    const primaryTitle = reviewQueue.due_count > 0
      ? `Best next move: review ${reviewQueue.due_count} due item${reviewQueue.due_count === 1 ? '' : 's'}`
      : nextSession
        ? `Best next move: continue ${nextSession.topic_title}`
        : 'Best next move: pick a learning direction';

    const detail = reviewQueue.due_count > 0
      ? 'Clear what is already due first, then continue with a focused study session.'
      : nextSession
        ? `${nextSession.suggested_duration} minutes is enough to keep momentum without turning this into a big project.`
        : 'Start with one topic that matters now, then let Sara turn it into a study path.';

    return (
      <View style={styles.guideCard}>
        <View style={styles.guideHeader}>
          <View style={styles.guideIcon}>
            <Ionicons name="school-outline" size={18} color={colors.accent} />
          </View>
          <View style={styles.guideCopy}>
            <Text style={styles.guideEyebrow}>What can I do next?</Text>
            <Text style={styles.guideTitle}>{primaryTitle}</Text>
            <Text style={styles.guideBody}>{detail}</Text>
          </View>
        </View>

        <View style={styles.guideActions}>
          <TouchableOpacity
            style={[styles.guideButton, styles.guideButtonPrimary]}
            onPress={() => setTab(reviewQueue.due_count > 0 ? 'review' : 'topics')}
          >
            <Text style={styles.guideButtonPrimaryText}>
              {reviewQueue.due_count > 0 ? 'Open Reviews' : 'Open Topics'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.guideButton, styles.guideButtonSecondary]}
            onPress={openLearningPrompt}
          >
            <Text style={styles.guideButtonSecondaryText}>Ask Sara</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  };

  const renderProgressBar = (mastery: number) => {
    const pct = Math.min(Math.max(mastery, 0), 100);
    return (
      <View style={styles.progressBarTrack}>
        <View
          style={[
            styles.progressBarFill,
            {
              width: `${pct}%`,
              backgroundColor: pct >= 80 ? colors.success : pct >= 40 ? colors.warning : colors.primary,
            },
          ]}
        />
      </View>
    );
  };

  const renderTopicItem = ({ item }: { item: Topic }) => {
    const expanded = expandedTopicId === item.id;
    return (
      <TouchableOpacity
        style={styles.topicCard}
        activeOpacity={0.7}
        onPress={() => setExpandedTopicId(expanded ? null : item.id)}
      >
        {/* Header row */}
        <View style={styles.topicHeader}>
          <View style={styles.topicTitleRow}>
            <Text style={styles.topicTitle} numberOfLines={1}>
              {item.title}
            </Text>
            <View style={[styles.statusBadge, { backgroundColor: statusColor(item.status) + '22' }]}>
              <Text style={[styles.statusBadgeText, { color: statusColor(item.status) }]}>
                {item.status}
              </Text>
            </View>
          </View>

          {/* Priority */}
          <View style={styles.priorityRow}>
            <View style={[styles.priorityDot, { backgroundColor: priorityColor(item.priority) }]} />
            <Text style={[styles.priorityText, { color: priorityColor(item.priority) }]}>
              {priorityLabel(item.priority)}
            </Text>
          </View>
        </View>

        {/* Description */}
        {item.description ? (
          <Text style={styles.topicDescription} numberOfLines={expanded ? undefined : 1}>
            {item.description}
          </Text>
        ) : null}

        {/* Mastery progress */}
        <View style={styles.masteryRow}>
          <Text style={styles.masteryLabel}>Mastery</Text>
          <Text style={styles.masteryValue}>{Math.round(item.mastery_level)}%</Text>
        </View>
        {renderProgressBar(item.mastery_level)}

        {/* Expanded detail */}
        {expanded && (
          <View style={styles.expandedSection}>
            <Text style={styles.expandedDetail}>
              Priority: {item.priority}/10
            </Text>
            <Text style={styles.expandedDetail}>
              Updated: {new Date(item.updated_at).toLocaleDateString()}
            </Text>
            {item.parent_id && (
              <Text style={styles.expandedDetail}>
                Sub-topic of: {topicNameMap[item.parent_id] || item.parent_id}
              </Text>
            )}
          </View>
        )}
      </TouchableOpacity>
    );
  };

  const renderReviewItem = ({ item }: { item: ReviewItem }) => {
    const topicName = item.topic_id ? topicNameMap[item.topic_id] || 'Unknown Topic' : 'General';
    return (
      <View style={styles.reviewCard}>
        <View style={styles.reviewHeader}>
          <Text style={styles.reviewConcept} numberOfLines={2}>
            {item.concept || topicName}
          </Text>
          <Text style={styles.reviewReps}>
            {item.repetitions} rep{item.repetitions !== 1 ? 's' : ''}
          </Text>
        </View>
        <Text style={styles.reviewTopic} numberOfLines={1}>
          {topicName}
        </Text>
        {item.next_review_at && (
          <Text style={styles.reviewDue}>
            Due: {new Date(item.next_review_at).toLocaleDateString()}
          </Text>
        )}
        <TouchableOpacity
          style={styles.startReviewButton}
          onPress={() => {
            Alert.alert('Start Review', `Review: ${item.concept || topicName}`);
          }}
        >
          <Text style={styles.startReviewButtonText}>Start Review</Text>
        </TouchableOpacity>
      </View>
    );
  };

  // ------ Loading state ------

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  // ------ Main render ------

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      {/* Tab bar */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={[styles.tabButton, tab === 'topics' && styles.tabButtonActive]}
          onPress={() => setTab('topics')}
        >
          <Text style={[styles.tabButtonText, tab === 'topics' && styles.tabButtonTextActive]}>
            Topics
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tabButton, tab === 'review' && styles.tabButtonActive]}
          onPress={() => setTab('review')}
        >
          <Text style={[styles.tabButtonText, tab === 'review' && styles.tabButtonTextActive]}>
            Review
          </Text>
          {reviewQueue.due_count > 0 && (
            <View style={styles.reviewBadge}>
              <Text style={styles.reviewBadgeText}>{reviewQueue.due_count}</Text>
            </View>
          )}
        </TouchableOpacity>
      </View>

      {/* Topics tab */}
      {tab === 'topics' && (
        <FlatList
          data={groupedTopics}
          renderItem={renderTopicItem}
          keyExtractor={(item) => item.id}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          ListHeaderComponent={
            <>
              {renderLearningGuideCard()}
              {renderNextSessionCard()}
            </>
          }
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                No learning topics yet. Ask Sara to suggest a study path or create one from the web app.
              </Text>
            </View>
          }
          contentContainerStyle={styles.listContent}
        />
      )}

      {/* Review tab */}
      {tab === 'review' && (
        <FlatList
          data={reviewQueue.items}
          renderItem={renderReviewItem}
          keyExtractor={(item) => item.id}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          ListHeaderComponent={
            <>
              {renderLearningGuideCard()}
              {reviewQueue.due_count > 0 ? (
                <View style={styles.reviewSummary}>
                  <Text style={styles.reviewSummaryText}>
                    {reviewQueue.due_count} item{reviewQueue.due_count !== 1 ? 's' : ''} due for review
                  </Text>
                </View>
              ) : null}
            </>
          }
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                No reviews due right now. Open Topics or ask Sara what to study next.
              </Text>
            </View>
          }
          contentContainerStyle={styles.listContent}
        />
      )}
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

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
  listContent: {
    paddingBottom: 100,
  },

  guideCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  guideHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  guideIcon: {
    width: 34,
    height: 34,
    borderRadius: borderRadius.full,
    backgroundColor: `${colors.accent}1a`,
    justifyContent: 'center',
    alignItems: 'center',
  },
  guideCopy: {
    flex: 1,
  },
  guideEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  guideTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  guideBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  guideActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  guideButton: {
    flex: 1,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  guideButtonPrimary: {
    backgroundColor: colors.primary,
  },
  guideButtonSecondary: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  guideButtonPrimaryText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  guideButtonSecondaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },

  // Tab bar
  tabBar: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
  },
  tabButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surface,
  },
  tabButtonActive: {
    backgroundColor: colors.primary,
  },
  tabButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  tabButtonTextActive: {
    color: colors.text,
  },
  reviewBadge: {
    backgroundColor: colors.error,
    borderRadius: borderRadius.full,
    minWidth: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.xs,
    paddingHorizontal: 6,
  },
  reviewBadgeText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },

  // Next session card
  nextSessionCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
    borderLeftWidth: 3,
    borderLeftColor: colors.accent,
  },
  nextSessionLabel: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  nextSessionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  nextSessionMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  nextSessionDuration: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  nextSessionFocus: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    flex: 1,
  },
  nextSessionReason: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },

  // Topic cards
  topicCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  topicHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: spacing.xs,
  },
  topicTitleRow: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginRight: spacing.sm,
  },
  topicTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    flexShrink: 1,
  },
  statusBadge: {
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  statusBadgeText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  priorityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  priorityDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  priorityText: {
    fontSize: fontSizes.xs,
    fontWeight: '500',
  },
  topicDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.sm,
  },
  masteryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  masteryLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  masteryValue: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  progressBarTrack: {
    height: 6,
    backgroundColor: colors.surfaceLight,
    borderRadius: 3,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: 6,
    borderRadius: 3,
  },
  expandedSection: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceLight,
  },
  expandedDetail: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginBottom: 4,
  },

  // Review cards
  reviewCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  reviewHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: spacing.xs,
  },
  reviewConcept: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    flex: 1,
    marginRight: spacing.sm,
  },
  reviewReps: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  reviewTopic: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  reviewDue: {
    color: colors.warning,
    fontSize: fontSizes.xs,
    marginBottom: spacing.sm,
  },
  startReviewButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  startReviewButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  reviewSummary: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  reviewSummaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },

  // Empty state
  emptyContainer: {
    padding: spacing.xl,
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
  },
});

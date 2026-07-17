import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Animated,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { SaraBriefResponse, BriefSection, SuggestedAction } from '../../types/cards';
import apiClient from '../../services/api';

const EMOTION_EMOJI: Record<string, string> = {
  curious: '🤔', calm: '😌', alert: '⚡', concerned: '😟',
  happy: '😊', focused: '🎯', neutral: '😐', reflective: '🪞',
  attentive: '👀', energetic: '💫',
};

const SECTION_ICONS: Record<string, string> = {
  weather: '☀️',
  fitness: '🍽️',
  threads: '💬',
  learning: '📚',
};

interface SaraFullStatus {
  emotional_state: string;
  watching_for?: string;
  latest_thought?: string;
  last_action?: string;
  pending_observations: number;
  hours_since_last_chat?: number;
  pkg_facts_count: number;
}

interface IntelligentBriefProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onAction: (action: SuggestedAction) => void;
}

export default function IntelligentBrief({ collapsed, onToggleCollapse, onAction }: IntelligentBriefProps) {
  const [brief, setBrief] = useState<SaraBriefResponse | null>(null);
  const [saraStatus, setSaraStatus] = useState<SaraFullStatus | null>(null);
  const [statusExpanded, setStatusExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const heightAnim = useRef(new Animated.Value(1)).current;

  const fetchBrief = useCallback(async () => {
    try {
      const [briefData, statusData] = await Promise.allSettled([
        apiClient.get<SaraBriefResponse>('/api/sara/brief'),
        apiClient.get<SaraFullStatus>('/api/sara/status'),
      ]);
      if (briefData.status === 'fulfilled') setBrief(briefData.value);
      if (statusData.status === 'fulfilled') setSaraStatus(statusData.value as SaraFullStatus);
    } catch (e) {
      // Graceful degradation
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBrief();
    const interval = setInterval(fetchBrief, 5 * 60 * 1000); // Every 5 min
    return () => clearInterval(interval);
  }, [fetchBrief]);

  useEffect(() => {
    Animated.timing(heightAnim, {
      toValue: collapsed ? 0 : 1,
      duration: 250,
      useNativeDriver: false,
    }).start();
  }, [collapsed]);

  if (loading && !brief) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="small" color={colors.primary} />
      </View>
    );
  }

  if (!brief) return null;

  const status = saraStatus || brief.sara_status;
  const emoji = EMOTION_EMOJI[status?.emotional_state] || '🤖';

  const maxHeight = heightAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0, 500],
  });

  const opacity = heightAnim.interpolate({
    inputRange: [0, 0.5, 1],
    outputRange: [0, 0, 1],
  });

  return (
    <View style={styles.container}>
      {/* Header row: tap greeting to collapse/expand brief, tap emoji for Sara details */}
      <View style={styles.header}>
        <TouchableOpacity style={styles.headerLeft} onPress={onToggleCollapse} activeOpacity={0.7}>
          <Text style={styles.greeting}>{brief.greeting}</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.headerRight}
          onPress={() => setStatusExpanded(!statusExpanded)}
          activeOpacity={0.7}
        >
          <Text style={styles.emoji}>{emoji}</Text>
          <Ionicons
            name={statusExpanded ? 'chevron-up' : 'chevron-down'}
            size={14}
            color="rgba(255,255,255,0.3)"
          />
        </TouchableOpacity>
      </View>

      {/* Sara's current thought */}
      {statusExpanded && saraStatus && saraStatus.latest_thought && (
        <View style={styles.statusDetails}>
          <Text style={styles.statusThought}>{saraStatus.latest_thought}</Text>
        </View>
      )}

      {/* Collapsible sections */}
      <Animated.View style={{ maxHeight, opacity, overflow: 'hidden' }}>
        <View style={styles.sections}>
          {brief.brief_sections
            .filter((section) => section.type !== 'calendar')
            .map((section, i) => (
              <BriefSectionRow key={`${section.type}-${i}`} section={section} onAction={onAction} />
            ))}
        </View>
      </Animated.View>
    </View>
  );
}

function BriefSectionRow({ section, onAction }: { section: BriefSection; onAction: (a: SuggestedAction) => void }) {
  const icon = SECTION_ICONS[section.type] || '📌';

  let label = '';
  let detail = '';

  switch (section.type) {
    case 'fitness': {
      const cal = section.data?.calories_today || 0;
      const goal = section.data?.goal || 2200;
      const lastMeal = section.data?.last_meal_ago_hours;
      label = `${cal} / ${goal} cal`;
      detail = lastMeal ? `Last meal ${lastMeal}h ago` : 'No meals logged yet';
      break;
    }
    case 'threads': {
      const open = section.data?.open || 0;
      const topics = section.data?.topics || [];
      label = `${open} open thread${open !== 1 ? 's' : ''}`;
      detail = topics.slice(0, 2).join(', ');
      break;
    }
    case 'learning': {
      const reviews = section.data?.reviews_due || 0;
      label = `${reviews} review${reviews !== 1 ? 's' : ''} due`;
      break;
    }
    case 'weather': {
      const temp = section.data?.temp || section.data?.temperature;
      const cond = section.data?.conditions || '';
      label = temp ? `${temp}° ${cond}` : cond;
      break;
    }
    default:
      label = section.type;
  }

  return (
    <TouchableOpacity
      style={styles.sectionRow}
      onPress={() => {
        const messages: Record<string, string> = {
          fitness: "How's my nutrition today?",
          threads: "What threads should I follow up on?",
          learning: "What learning reviews are due?",
          weather: "What's the weather?",
        };
        const msg = messages[section.type];
        if (msg) onAction({ label: section.type, message: msg });
      }}
    >
      <Text style={styles.sectionIcon}>{icon}</Text>
      <Text style={styles.sectionLabel}>{label}</Text>
      {detail ? <Text style={styles.sectionDetail} numberOfLines={1}>{detail}</Text> : null}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  loadingContainer: {
    padding: spacing.md,
    alignItems: 'center',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
  },
  headerLeft: {
    flex: 1,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  greeting: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  emoji: { fontSize: 20 },
  statusDetails: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    gap: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(255,255,255,0.06)',
    marginBottom: 4,
  },
  statusThought: {
    color: 'rgba(255,255,255,0.55)',
    fontSize: 13,
    lineHeight: 19,
    fontStyle: 'italic',
  },
  statusDetail: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
    lineHeight: 18,
  },
  statusMetrics: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 2,
  },
  statusMetric: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
  },
  sections: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    gap: 6,
  },
  sectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  sectionIcon: {
    fontSize: 14,
    width: 22,
    textAlign: 'center',
  },
  sectionLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  sectionDetail: {
    flex: 1,
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textAlign: 'right',
  },
});

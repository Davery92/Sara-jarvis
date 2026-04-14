import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  Alert,
  ScrollView,
  Modal,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

// --- Types ---

interface PKGFact {
  type: string;
  pkg_id: string;
  confidence: number;
  source: string;
  first_learned: string;
  last_confirmed: string;
  times_confirmed: number;
  [key: string]: any;
}

interface PKGStats {
  total: number;
  by_type: Record<string, number>;
  confidence_distribution: {
    high: number;
    medium: number;
    low: number;
  };
}

interface PKGSummary {
  summary: string;
  total: number;
  highlights: Array<{ type: string; text: string; confidence: number }>;
}

const CATEGORIES = [
  'All', 'Person', 'Preference', 'Routine', 'Goal',
  'Interest', 'Health', 'Place', 'Fact',
] as const;
type Category = (typeof CATEGORIES)[number];

const CATEGORY_EMOJI: Record<string, string> = {
  All: '🔮',
  Person: '👤',
  Preference: '❤️',
  Routine: '🕐',
  Goal: '🎯',
  Interest: '💡',
  Health: '🏥',
  Place: '📍',
  Fact: '📋',
};

const PROP_TEMPLATES: Record<string, string[]> = {
  Person: ['name', 'relationship_to_david', 'notes'],
  Preference: ['domain', 'key', 'value', 'strength'],
  Routine: ['activity', 'typical_time', 'day_of_week', 'frequency'],
  Goal: ['description', 'status', 'deadline'],
  Interest: ['topic', 'depth', 'notes'],
  Health: ['metric', 'current_value', 'trend'],
  Place: ['name', 'place_type', 'significance', 'address'],
  Fact: ['subject', 'predicate', 'object', 'category'],
};

// --- Helpers ---

const SKIP_KEYS = new Set([
  'type', 'pkg_id', 'confidence', 'source', 'first_learned', 'last_confirmed',
  'times_confirmed', 'version', 'superseded_by', 'dedup_key',
]);

function getFactDisplayName(fact: PKGFact): string {
  const t = fact.type;
  if (t === 'Person') return fact.name || 'Unknown Person';
  if (t === 'Preference') return `${fact.domain || ''}: ${fact.key || ''} = ${fact.value || ''}`;
  if (t === 'Routine') return fact.activity || 'Unknown Routine';
  if (t === 'Goal') return fact.description || 'Unknown Goal';
  if (t === 'Interest') return fact.topic || 'Unknown Interest';
  if (t === 'Health') return `${fact.metric || ''}: ${fact.current_value || fact.value || ''}`;
  if (t === 'Place') return `${fact.name || 'Unknown'} (${fact.place_type || fact.type || ''})`;
  if (t === 'Fact') return `${fact.subject || ''} ${fact.predicate || ''} ${fact.object || ''}`;
  return fact.name || fact.topic || fact.description || 'Unknown';
}

function getFactProperties(fact: PKGFact): Array<{ key: string; value: string }> {
  return Object.entries(fact)
    .filter(([k, v]) => !SKIP_KEYS.has(k) && v != null && v !== '')
    .map(([k, v]) => ({ key: k.replace(/_/g, ' '), value: String(v) }));
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return '#4ade80';
  if (c >= 0.5) return '#facc15';
  return '#f87171';
}

function confidenceLabel(c: number): string {
  if (c >= 0.8) return 'High';
  if (c >= 0.5) return 'Medium';
  return 'Low';
}

function formatDate(iso: string): string {
  if (!iso) return 'Unknown';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso;
  }
}

// --- Component ---

export default function KnowledgeScreen() {
  const { showToast } = useToast();
  const [activeCategory, setActiveCategory] = useState<Category>('All');
  const [facts, setFacts] = useState<PKGFact[]>([]);
  const [stats, setStats] = useState<PKGStats | null>(null);
  const [summary, setSummary] = useState<PKGSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [addType, setAddType] = useState<string>('Fact');
  const [addProps, setAddProps] = useState<Record<string, string>>({});
  const [addConfidence, setAddConfidence] = useState(0.9);

  const loadData = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (activeCategory !== 'All') params.set('category', activeCategory);
      if (searchQuery.trim()) params.set('search', searchQuery.trim());
      params.set('limit', '100');

      const [browseData, statsData, summaryData] = await Promise.all([
        apiClient.get<{ facts: PKGFact[]; total: number }>(`/api/pkg/browse?${params}`),
        apiClient.get<PKGStats>('/api/pkg/stats'),
        apiClient.get<PKGSummary>('/api/pkg/summary'),
      ]);

      setFacts(browseData.facts || []);
      setStats(statsData);
      setSummary(summaryData);
    } catch (err) {
      console.error('Failed to load PKG data:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeCategory, searchQuery]);

  useEffect(() => {
    setLoading(true);
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  const handleDelete = (fact: PKGFact) => {
    Alert.alert(
      'Delete Fact',
      `Remove "${getFactDisplayName(fact)}" from your knowledge graph?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await apiClient.delete(`/api/pkg/${fact.pkg_id}`);
              loadData();
            } catch {
              showToast('error', 'Failed to delete fact');
            }
          },
        },
      ]
    );
  };

  const handleEdit = (fact: PKGFact) => {
    const properties = getFactProperties(fact);
    // Use Alert.prompt for simple single-value edits (iOS only),
    // or build a more complete inline editing approach
    Alert.alert(
      'Edit Fact',
      `${getFactDisplayName(fact)}\n\nConfidence: ${Math.round(fact.confidence * 100)}%`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Set High Confidence',
          onPress: async () => {
            try {
              await apiClient.patch(`/api/pkg/${fact.pkg_id}`, { confidence: 0.95 });
              loadData();
            } catch {
              showToast('error', 'Failed to update');
            }
          },
        },
        {
          text: 'Set Low Confidence',
          style: 'destructive',
          onPress: async () => {
            try {
              await apiClient.patch(`/api/pkg/${fact.pkg_id}`, { confidence: 0.3 });
              loadData();
            } catch {
              showToast('error', 'Failed to update');
            }
          },
        },
      ]
    );
  };

  const handleReextract = async () => {
    try {
      await apiClient.post('/api/pkg/reextract');
      showToast('info', 'PKG re-extraction has been queued. New facts will appear shortly.');
    } catch {
      showToast('error', 'Failed to queue re-extraction');
    }
  };

  const handleAdd = async () => {
    const filledProps: Record<string, string> = {};
    for (const [k, v] of Object.entries(addProps)) {
      if (v.trim()) filledProps[k] = v.trim();
    }
    if (Object.keys(filledProps).length === 0) {
      showToast('error', 'Please fill in at least one property');
      return;
    }
    try {
      await apiClient.post('/api/pkg/node', {
        fact_type: addType,
        properties: filledProps,
        confidence: addConfidence,
      });
      setShowAddModal(false);
      setAddProps({});
      loadData();
      showToast('success', 'Fact added to knowledge graph');
    } catch {
      showToast('error', 'Failed to add fact');
    }
  };

  const renderCategoryPill = ({ item }: { item: Category }) => {
    const count = item === 'All' ? stats?.total : stats?.by_type?.[item];
    const isActive = activeCategory === item;
    return (
      <TouchableOpacity
        style={[styles.pill, isActive && styles.pillActive]}
        onPress={() => setActiveCategory(item)}
      >
        <Text style={styles.pillEmoji}>{CATEGORY_EMOJI[item]}</Text>
        <Text style={[styles.pillText, isActive && styles.pillTextActive]}>{item}</Text>
        {count != null && count > 0 && (
          <Text style={styles.pillCount}>({count})</Text>
        )}
      </TouchableOpacity>
    );
  };

  const renderFact = ({ item }: { item: PKGFact }) => {
    const isExpanded = expandedId === item.pkg_id;
    const props = getFactProperties(item);

    return (
      <TouchableOpacity
        style={styles.factCard}
        onPress={() => setExpandedId(isExpanded ? null : item.pkg_id)}
        onLongPress={() => handleDelete(item)}
        activeOpacity={0.7}
      >
        <View style={styles.factHeader}>
          <Text style={styles.factEmoji}>{CATEGORY_EMOJI[item.type] || '📋'}</Text>
          <View style={styles.factHeaderText}>
            <Text style={styles.factName} numberOfLines={isExpanded ? undefined : 1}>
              {getFactDisplayName(item)}
            </Text>
            <Text style={styles.factMeta}>
              {item.type} {'\u00B7'} {(item.source || '').replace(/_/g, ' ')}
            </Text>
          </View>
          <View style={[styles.confidenceBadge, { borderColor: confidenceColor(item.confidence) }]}>
            <Text style={[styles.confidenceText, { color: confidenceColor(item.confidence) }]}>
              {Math.round(item.confidence * 100)}%
            </Text>
          </View>
        </View>

        {isExpanded && (
          <View style={styles.factExpanded}>
            {props.map(({ key, value }) => (
              <View key={key} style={styles.propRow}>
                <Text style={styles.propKey}>{key}:</Text>
                <Text style={styles.propValue}>{value}</Text>
              </View>
            ))}

            <View style={styles.factTimeline}>
              <Text style={styles.timelineText}>
                Learned: {formatDate(item.first_learned)}
              </Text>
              <Text style={styles.timelineText}>
                Confirmed: {formatDate(item.last_confirmed)} ({item.times_confirmed || 1}x)
              </Text>
              <Text style={[styles.timelineText, { color: confidenceColor(item.confidence) }]}>
                {confidenceLabel(item.confidence)} confidence
              </Text>
            </View>

            <View style={styles.factActions}>
              <TouchableOpacity style={styles.actionButton} onPress={() => handleEdit(item)}>
                <Text style={styles.actionButtonText}>Edit</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.actionButton, styles.deleteButton]}
                onPress={() => handleDelete(item)}
              >
                <Text style={[styles.actionButtonText, styles.deleteButtonText]}>Delete</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  if (loading && facts.length === 0) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>Loading knowledge...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Summary */}
      {summary && (
        <View style={styles.summaryCard}>
          <Text style={styles.summaryText}>{summary.summary}</Text>
        </View>
      )}

      {/* Search */}
      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search knowledge..."
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={setSearchQuery}
          returnKeyType="search"
        />
        <TouchableOpacity style={styles.addButton} onPress={() => setShowAddModal(true)}>
          <Text style={styles.addButtonText}>+ Add</Text>
        </TouchableOpacity>
      </View>

      {/* Category pills */}
      <FlatList
        horizontal
        data={[...CATEGORIES]}
        renderItem={renderCategoryPill}
        keyExtractor={(item) => item}
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.pillsContainer}
        style={styles.pillsList}
      />

      {/* Action buttons */}
      <View style={styles.actionsRow}>
        <TouchableOpacity style={styles.reextractButton} onPress={handleReextract}>
          <Text style={styles.reextractButtonText}>Re-extract from Conversations</Text>
        </TouchableOpacity>
      </View>

      {/* Fact list */}
      <FlatList
        data={facts}
        renderItem={renderFact}
        keyExtractor={(item) => item.pkg_id}
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
            <Text style={styles.emptyEmoji}>🔍</Text>
            <Text style={styles.emptyText}>
              {searchQuery
                ? `No facts matching "${searchQuery}"`
                : activeCategory !== 'All'
                ? `No ${activeCategory} facts yet`
                : 'No knowledge yet. Keep chatting with Sara!'}
            </Text>
          </View>
        }
      />

      {/* Add Modal */}
      <Modal
        visible={showAddModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowAddModal(false)}
      >
        <SafeAreaView style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowAddModal(false)}>
              <Text style={styles.modalCancel}>Cancel</Text>
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Add Knowledge</Text>
            <TouchableOpacity onPress={handleAdd}>
              <Text style={styles.modalSave}>Save</Text>
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.modalBody}>
            {/* Type selector */}
            <Text style={styles.modalLabel}>Type</Text>
            <View style={styles.typeGrid}>
              {CATEGORIES.filter((c) => c !== 'All').map((cat) => (
                <TouchableOpacity
                  key={cat}
                  style={[styles.typeChip, addType === cat && styles.typeChipActive]}
                  onPress={() => {
                    setAddType(cat);
                    setAddProps({});
                  }}
                >
                  <Text style={styles.typeChipEmoji}>{CATEGORY_EMOJI[cat]}</Text>
                  <Text style={[styles.typeChipText, addType === cat && styles.typeChipTextActive]}>
                    {cat}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Property fields */}
            <Text style={styles.modalLabel}>Properties</Text>
            {(PROP_TEMPLATES[addType] || ['key', 'value']).map((field) => (
              <View key={field} style={styles.fieldRow}>
                <Text style={styles.fieldLabel}>{field.replace(/_/g, ' ')}</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={addProps[field] || ''}
                  onChangeText={(v) => setAddProps({ ...addProps, [field]: v })}
                  placeholder={`Enter ${field.replace(/_/g, ' ')}...`}
                  placeholderTextColor={colors.textMuted}
                />
              </View>
            ))}

            {/* Confidence */}
            <Text style={styles.modalLabel}>
              Confidence: {Math.round(addConfidence * 100)}%
            </Text>
            <View style={styles.confidenceButtons}>
              {[0.5, 0.7, 0.8, 0.9, 0.95].map((val) => (
                <TouchableOpacity
                  key={val}
                  style={[
                    styles.confBtn,
                    addConfidence === val && styles.confBtnActive,
                  ]}
                  onPress={() => setAddConfidence(val)}
                >
                  <Text
                    style={[
                      styles.confBtnText,
                      addConfidence === val && styles.confBtnTextActive,
                    ]}
                  >
                    {Math.round(val * 100)}%
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </ScrollView>
        </SafeAreaView>
      </Modal>
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
  loadingText: {
    color: colors.textMuted,
    marginTop: spacing.md,
    fontSize: fontSizes.sm,
  },

  // Summary
  summaryCard: {
    margin: spacing.md,
    marginBottom: spacing.xs,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  summaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },

  // Search
  searchRow: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  searchInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  addButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
  },
  addButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },

  // Category pills
  pillsList: {
    maxHeight: 50,
  },
  pillsContainer: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  pillActive: {
    backgroundColor: 'rgba(13, 127, 242, 0.15)',
    borderColor: colors.primary,
  },
  pillEmoji: {
    fontSize: 14,
  },
  pillText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  pillTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  pillCount: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },

  // Actions
  actionsRow: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  reextractButton: {
    backgroundColor: 'rgba(139, 92, 246, 0.15)',
    borderWidth: 1,
    borderColor: 'rgba(139, 92, 246, 0.3)',
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  reextractButtonText: {
    color: '#a78bfa',
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },

  // Fact list
  listContent: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xxl,
  },
  factCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
    overflow: 'hidden',
  },
  factHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    gap: spacing.sm,
  },
  factEmoji: {
    fontSize: 20,
  },
  factHeaderText: {
    flex: 1,
    minWidth: 0,
  },
  factName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '500',
  },
  factMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  confidenceBadge: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  confidenceText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },

  // Expanded
  factExpanded: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.md,
  },
  propRow: {
    flexDirection: 'row',
    marginBottom: 4,
  },
  propKey: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    width: 100,
    textTransform: 'capitalize',
  },
  propValue: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    flex: 1,
  },
  factTimeline: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 2,
  },
  timelineText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  factActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  actionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  actionButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  deleteButton: {
    borderColor: 'rgba(248, 113, 113, 0.3)',
  },
  deleteButtonText: {
    color: '#f87171',
  },

  // Empty
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyEmoji: {
    fontSize: 40,
    marginBottom: spacing.md,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
    paddingHorizontal: spacing.xl,
  },

  // Modal
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalCancel: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  modalTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  modalSave: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  modalBody: {
    flex: 1,
    padding: spacing.md,
  },
  modalLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: spacing.sm,
    marginTop: spacing.md,
  },
  typeGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  typeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  typeChipActive: {
    backgroundColor: 'rgba(13, 127, 242, 0.15)',
    borderColor: colors.primary,
  },
  typeChipEmoji: {
    fontSize: 14,
  },
  typeChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  typeChipTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  fieldRow: {
    marginBottom: spacing.sm,
  },
  fieldLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textTransform: 'capitalize',
    marginBottom: 4,
  },
  fieldInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  confidenceButtons: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  confBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  confBtnActive: {
    backgroundColor: 'rgba(13, 127, 242, 0.15)',
    borderColor: colors.primary,
  },
  confBtnText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  confBtnTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
});

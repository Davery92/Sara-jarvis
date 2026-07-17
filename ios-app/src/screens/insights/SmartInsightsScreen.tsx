import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { apiClient } from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import Markdown from 'react-native-markdown-display';

type ViewTab = 'reports' | 'suggestions' | 'patterns';

export default function SmartInsightsScreen() {
  const [view, setView] = useState<ViewTab>('reports');
  const [reports, setReports] = useState<any[]>([]);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [patterns, setPatterns] = useState<any[]>([]);
  const [selectedReport, setSelectedReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadAllData();
  }, []);

  const loadAllData = async () => {
    setLoading(true);
    await Promise.all([
      loadReports(),
      loadSuggestions(),
      loadPatterns()
    ]);
    setLoading(false);
  };

  const loadReports = async () => {
    try {
      const data = await apiClient.getIntelligenceReports();
      setReports(data);
      if (data.length > 0 && !selectedReport) {
        setSelectedReport(data[0]);
      }
    } catch (error) {
      console.error('Failed to load reports:', error);
    }
  };

  const loadSuggestions = async () => {
    try {
      const data = await apiClient.getProactiveSuggestions();
      setSuggestions(data);
    } catch (error) {
      console.error('Failed to load suggestions:', error);
    }
  };

  const loadPatterns = async () => {
    try {
      const data = await apiClient.getDetectedPatterns();
      setPatterns(data);
    } catch (error) {
      console.error('Failed to load patterns:', error);
    }
  };

  const generateReport = async (type: 'weekly' | 'monthly' | 'quarterly') => {
    setGenerating(true);
    try {
      const newReport = await apiClient.generateIntelligenceReport(type);
      setReports(prev => [newReport, ...prev]);
      setSelectedReport(newReport);
    } catch (error) {
      console.error('Failed to generate report:', error);
    } finally {
      setGenerating(false);
    }
  };

  const updateSuggestionStatus = async (suggestionId: string, status: 'accepted' | 'dismissed') => {
    try {
      await apiClient.updateSuggestionStatus(suggestionId, status);
      setSuggestions(prev => prev.map(s =>
        s.id === suggestionId ? { ...s, status } : s
      ));
    } catch (error) {
      console.error('Failed to update suggestion:', error);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric'
    });
  };

  const getPriorityColor = (priority: string) => {
    const colors_map = {
      high: colors.error,
      medium: colors.warning,
      low: colors.info
    };
    return colors_map[priority as keyof typeof colors_map] || colors_map.low;
  };

  const getReportIcon = (type: string) => {
    const icons = {
      weekly: '📅',
      monthly: '📊',
      quarterly: '📈'
    };
    return icons[type as keyof typeof icons] || '📄';
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          onPress={() => setView('reports')}
          style={[styles.tab, view === 'reports' && styles.tabActive]}
        >
          <Text style={[styles.tabText, view === 'reports' && styles.tabTextActive]}>
            Reports
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setView('suggestions')}
          style={[styles.tab, view === 'suggestions' && styles.tabActive]}
        >
          <Text style={[styles.tabText, view === 'suggestions' && styles.tabTextActive]}>
            Suggestions
          </Text>
          {suggestions.filter(s => s.status === 'pending').length > 0 && (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>
                {suggestions.filter(s => s.status === 'pending').length}
              </Text>
            </View>
          )}
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setView('patterns')}
          style={[styles.tab, view === 'patterns' && styles.tabActive]}
        >
          <Text style={[styles.tabText, view === 'patterns' && styles.tabTextActive]}>
            Patterns
          </Text>
        </TouchableOpacity>
      </View>

      {/* Reports View */}
      {view === 'reports' && (
        <ScrollView style={styles.content}>
          <View style={styles.generateButtons}>
            <TouchableOpacity
              onPress={() => generateReport('weekly')}
              disabled={generating}
              style={[styles.generateButton, { backgroundColor: colors.surfaceLight }]}
            >
              <Text style={styles.generateButtonIcon}>📅</Text>
              <Text style={styles.generateButtonText}>Weekly</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => generateReport('monthly')}
              disabled={generating}
              style={[styles.generateButton, { backgroundColor: colors.surfaceLight }]}
            >
              <Text style={styles.generateButtonIcon}>📊</Text>
              <Text style={styles.generateButtonText}>Monthly</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => generateReport('quarterly')}
              disabled={generating}
              style={[styles.generateButton, { backgroundColor: colors.surfaceLight }]}
            >
              <Text style={styles.generateButtonIcon}>📈</Text>
              <Text style={styles.generateButtonText}>Quarterly</Text>
            </TouchableOpacity>
          </View>

          {selectedReport && (
            <View style={styles.reportContent}>
              <View style={styles.reportHeader}>
                <Text style={styles.reportIcon}>{getReportIcon(selectedReport.report_type)}</Text>
                <View>
                  <Text style={styles.reportType}>{selectedReport.report_type.toUpperCase()}</Text>
                  <Text style={styles.reportDate}>
                    {formatDate(selectedReport.period_start)} - {formatDate(selectedReport.period_end)}
                  </Text>
                </View>
              </View>

              {selectedReport.summary && (
                <View style={styles.summaryBox}>
                  <Text style={styles.summaryText}>{selectedReport.summary}</Text>
                </View>
              )}

              {selectedReport.insights && selectedReport.insights.length > 0 && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Key Insights</Text>
                  {selectedReport.insights.map((insight: string, idx: number) => (
                    <View key={idx} style={styles.insightItem}>
                      <Text style={styles.insightIcon}>💡</Text>
                      <Text style={styles.insightText}>{insight}</Text>
                    </View>
                  ))}
                </View>
              )}

              {selectedReport.recommendations && selectedReport.recommendations.length > 0 && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Recommendations</Text>
                  {selectedReport.recommendations.map((rec: string, idx: number) => (
                    <View key={idx} style={styles.recItem}>
                      <Text style={styles.recIcon}>✓</Text>
                      <Text style={styles.recText}>{rec}</Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          )}
        </ScrollView>
      )}

      {/* Suggestions View */}
      {view === 'suggestions' && (
        <ScrollView style={styles.content}>
          {suggestions.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>✨</Text>
              <Text style={styles.emptyText}>No suggestions</Text>
            </View>
          ) : (
            suggestions.map((suggestion) => (
              <View
                key={suggestion.id}
                style={[
                  styles.suggestionCard,
                  suggestion.status !== 'pending' && styles.suggestionCardInactive
                ]}
              >
                <View style={[
                  styles.priorityBadge,
                  { backgroundColor: getPriorityColor(suggestion.priority) }
                ]}>
                  <Text style={styles.priorityText}>{suggestion.priority.toUpperCase()}</Text>
                </View>
                <Text style={styles.suggestionTitle}>{suggestion.title}</Text>
                <Text style={styles.suggestionDescription}>{suggestion.description}</Text>
                <View style={styles.suggestionFooter}>
                  <Text style={styles.confidenceText}>
                    {(suggestion.confidence * 100).toFixed(0)}% confident
                  </Text>
                  {suggestion.status === 'pending' && (
                    <View style={styles.suggestionActions}>
                      <TouchableOpacity
                        onPress={() => updateSuggestionStatus(suggestion.id, 'accepted')}
                        style={[styles.suggestionButton, styles.acceptButton]}
                      >
                        <Text style={styles.suggestionButtonText}>Accept</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={() => updateSuggestionStatus(suggestion.id, 'dismissed')}
                        style={[styles.suggestionButton, styles.dismissButton]}
                      >
                        <Text style={styles.suggestionButtonText}>Dismiss</Text>
                      </TouchableOpacity>
                    </View>
                  )}
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}

      {/* Patterns View */}
      {view === 'patterns' && (
        <ScrollView style={styles.content}>
          {patterns.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>🔍</Text>
              <Text style={styles.emptyText}>No patterns detected yet</Text>
            </View>
          ) : (
            patterns.map((pattern) => (
              <View key={pattern.id} style={styles.patternCard}>
                <View style={styles.patternHeader}>
                  <Text style={styles.patternIcon}>🔄</Text>
                  <Text style={styles.patternType}>{pattern.pattern_type}</Text>
                </View>
                <Text style={styles.patternTitle}>{pattern.title}</Text>
                <Text style={styles.patternDescription}>{pattern.description}</Text>
                <View style={styles.patternFooter}>
                  <Text style={styles.patternMeta}>
                    {(pattern.confidence * 100).toFixed(0)}% confidence
                  </Text>
                  <Text style={styles.patternMeta}>
                    {pattern.occurrences} occurrences
                  </Text>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </View>
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
  tabs: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.md,
    alignItems: 'center',
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
    position: 'relative',
  },
  tabActive: {
    borderBottomColor: colors.primary,
  },
  tabText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
    fontWeight: '500',
  },
  tabTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  badge: {
    position: 'absolute',
    top: 8,
    right: '30%',
    backgroundColor: colors.error,
    borderRadius: 10,
    paddingHorizontal: 6,
    paddingVertical: 2,
    minWidth: 20,
    alignItems: 'center',
  },
  badgeText: {
    color: colors.text,
    fontSize: 10,
    fontWeight: 'bold',
  },
  content: {
    flex: 1,
    padding: spacing.lg,
  },
  generateButtons: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  generateButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.md,
    borderRadius: borderRadius.md,
    gap: spacing.xs,
  },
  generateButtonIcon: {
    fontSize: 16,
  },
  generateButtonText: {
    color: colors.text,
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },
  reportContent: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
  },
  reportHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  reportIcon: {
    fontSize: 32,
  },
  reportType: {
    fontSize: fontSizes.lg,
    fontWeight: 'bold',
    color: colors.text,
  },
  reportDate: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  summaryBox: {
    backgroundColor: `${colors.primary}15`,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderLeftWidth: 4,
    borderLeftColor: colors.primary,
    marginBottom: spacing.md,
  },
  summaryText: {
    color: colors.text,
    lineHeight: 20,
  },
  section: {
    marginTop: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  insightItem: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
    padding: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
  },
  insightIcon: {
    fontSize: 16,
  },
  insightText: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  recItem: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
    padding: spacing.sm,
    backgroundColor: `${colors.success}15`,
    borderRadius: borderRadius.sm,
    borderLeftWidth: 2,
    borderLeftColor: colors.success,
  },
  recIcon: {
    color: colors.success,
    fontSize: 16,
  },
  recText: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  suggestionCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 2,
    borderColor: colors.primary,
  },
  suggestionCardInactive: {
    borderColor: colors.border,
    opacity: 0.6,
  },
  priorityBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.sm,
  },
  priorityText: {
    color: colors.text,
    fontSize: 10,
    fontWeight: 'bold',
  },
  suggestionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  suggestionDescription: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    lineHeight: 20,
    marginBottom: spacing.md,
  },
  suggestionFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  confidenceText: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  suggestionActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  suggestionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  acceptButton: {
    backgroundColor: colors.success,
  },
  dismissButton: {
    backgroundColor: colors.textMuted,
  },
  suggestionButtonText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  patternCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  patternHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  patternIcon: {
    fontSize: 20,
  },
  patternType: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  patternTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  patternDescription: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    lineHeight: 20,
    marginBottom: spacing.md,
  },
  patternFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  patternMeta: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyIcon: {
    fontSize: 64,
    marginBottom: spacing.md,
  },
  emptyText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },
});

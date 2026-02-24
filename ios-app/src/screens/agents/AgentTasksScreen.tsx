import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import apiClient from '../../services/api';
import { colors, spacing, fontSizes, borderRadius } from '../../styles/theme';

interface MissionStep {
  id: string;
  action_name: string;
  description: string | null;
  status: string;
  error_message: string | null;
}

interface Mission {
  id: string;
  title: string;
  description: string | null;
  state: string;
  source: string;
  priority: string;
  total_steps: number;
  completed_steps: number;
  current_step_index: number;
  created_at: string;
  completed_at: string | null;
  mission_metadata?: Record<string, any>;
  steps?: MissionStep[];
}

const STATE_CONFIG: Record<string, { color: string; icon: string; label: string }> = {
  pending: { color: colors.textMuted, icon: '...', label: 'Pending' },
  running: { color: colors.info, icon: '', label: 'Running' },
  awaiting_confirm: { color: colors.warning, icon: '?', label: 'Awaiting Confirm' },
  needs_clarification: { color: '#f97316', icon: '!', label: 'Needs Input' },
  done: { color: colors.success, icon: '', label: 'Completed' },
  failed: { color: colors.error, icon: 'X', label: 'Failed' },
  cancelled: { color: colors.textMuted, icon: '-', label: 'Cancelled' },
};

export default function AgentTasksScreen() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [clarifyText, setClarifyText] = useState<Record<string, string>>({});
  const [sendingClarify, setSendingClarify] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState<string | null>(null);

  const loadMissions = useCallback(async () => {
    try {
      const result = await apiClient.getMissions(filter || undefined);
      setMissions(result || []);
    } catch (error) {
      console.error('Failed to load missions:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  // Refresh on screen focus
  useFocusEffect(
    useCallback(() => {
      loadMissions();
      // Auto-refresh every 10 seconds
      const interval = setInterval(loadMissions, 10000);
      return () => clearInterval(interval);
    }, [loadMissions])
  );

  const loadMissionDetail = async (missionId: string) => {
    try {
      const detail = await apiClient.getMission(missionId);
      setMissions((prev) =>
        prev.map((m) => (m.id === missionId ? { ...m, steps: detail.steps } : m))
      );
    } catch (error) {
      console.error('Failed to load mission detail:', error);
    }
  };

  const handleExpand = (missionId: string) => {
    if (expandedId === missionId) {
      setExpandedId(null);
    } else {
      setExpandedId(missionId);
      const mission = missions.find((m) => m.id === missionId);
      if (mission && !mission.steps) {
        loadMissionDetail(missionId);
      }
    }
  };

  const handleConfirm = async (missionId: string) => {
    try {
      await apiClient.confirmMission(missionId);
      loadMissions();
    } catch (error) {
      Alert.alert('Error', 'Failed to confirm mission');
    }
  };

  const handleCancel = async (missionId: string) => {
    Alert.alert('Cancel Mission', 'Are you sure you want to cancel this mission?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Yes, Cancel',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.cancelMission(missionId);
            loadMissions();
          } catch (error) {
            Alert.alert('Error', 'Failed to cancel mission');
          }
        },
      },
    ]);
  };

  const handleSendClarification = async (missionId: string) => {
    const text = clarifyText[missionId]?.trim();
    if (!text) return;

    setSendingClarify((prev) => ({ ...prev, [missionId]: true }));
    try {
      await apiClient.post(`/autonomy/missions/${missionId}/action`, {
        action: 'clarify',
        message: text,
      });
      setClarifyText((prev) => ({ ...prev, [missionId]: '' }));
      loadMissions();
    } catch (error) {
      Alert.alert('Error', 'Failed to send clarification');
    } finally {
      setSendingClarify((prev) => ({ ...prev, [missionId]: false }));
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    loadMissions();
  };

  const filters = [
    { label: 'All', value: null },
    { label: 'Active', value: 'running' },
    { label: 'Done', value: 'done' },
    { label: 'Failed', value: 'failed' },
  ];

  const renderStatusIcon = (state: string) => {
    const config = STATE_CONFIG[state] || STATE_CONFIG.pending;

    if (state === 'running') {
      return <ActivityIndicator size="small" color={config.color} />;
    }

    return (
      <View style={[styles.statusDot, { backgroundColor: config.color }]}>
        {config.icon ? (
          <Text style={styles.statusDotText}>{config.icon}</Text>
        ) : null}
      </View>
    );
  };

  const renderStep = (step: MissionStep) => {
    const isRunning = step.status === 'running';
    const isDone = step.status === 'done';
    const isFailed = step.status === 'failed';

    return (
      <View key={step.id} style={styles.stepRow}>
        <View
          style={[
            styles.stepDot,
            isDone && styles.stepDotDone,
            isFailed && styles.stepDotFailed,
            isRunning && styles.stepDotRunning,
          ]}
        />
        <View style={styles.stepContent}>
          <Text style={styles.stepText}>
            {step.description || step.action_name}
          </Text>
          {step.error_message && (
            <Text style={styles.stepError}>{step.error_message}</Text>
          )}
        </View>
      </View>
    );
  };

  const renderMission = (mission: Mission) => {
    const config = STATE_CONFIG[mission.state] || STATE_CONFIG.pending;
    const isExpanded = expandedId === mission.id;
    const progress =
      mission.total_steps > 0
        ? (mission.completed_steps / mission.total_steps) * 100
        : 0;
    const needsClarification =
      mission.state === 'needs_clarification' ||
      mission.state === 'awaiting_confirm';

    return (
      <TouchableOpacity
        key={mission.id}
        style={[
          styles.missionCard,
          mission.state === 'running' && styles.missionCardRunning,
          needsClarification && styles.missionCardClarification,
        ]}
        onPress={() => handleExpand(mission.id)}
        activeOpacity={0.7}
      >
        {/* Header row */}
        <View style={styles.missionHeader}>
          {renderStatusIcon(mission.state)}
          <View style={styles.missionInfo}>
            <Text style={[styles.missionState, { color: config.color }]}>
              {config.label}
            </Text>
            <Text style={styles.missionTitle} numberOfLines={isExpanded ? 0 : 2}>
              {mission.title.replace(/^Agent:\s*/, '')}
            </Text>
          </View>
        </View>

        {/* Progress bar */}
        {mission.total_steps > 0 && (
          <View style={styles.progressContainer}>
            <View style={styles.progressBar}>
              <View
                style={[
                  styles.progressFill,
                  { width: `${progress}%` },
                  mission.state === 'done' && styles.progressDone,
                  mission.state === 'failed' && styles.progressFailed,
                ]}
              />
            </View>
            <Text style={styles.progressText}>
              {mission.completed_steps}/{mission.total_steps}
            </Text>
          </View>
        )}

        {/* Expanded content */}
        {isExpanded && (
          <View style={styles.expandedContent}>
            {mission.description && (
              <Text style={styles.missionDescription}>{mission.description}</Text>
            )}

            {/* Clarification input */}
            {needsClarification && (
              <View style={styles.clarifyContainer}>
                <Text style={styles.clarifyLabel}>
                  {mission.state === 'needs_clarification'
                    ? 'Agent needs your input:'
                    : 'Awaiting your confirmation:'}
                </Text>
                <View style={styles.clarifyInputRow}>
                  <TextInput
                    style={styles.clarifyInput}
                    value={clarifyText[mission.id] || ''}
                    onChangeText={(text) =>
                      setClarifyText((prev) => ({ ...prev, [mission.id]: text }))
                    }
                    placeholder="Type your response..."
                    placeholderTextColor={colors.textMuted}
                    returnKeyType="send"
                    onSubmitEditing={() => handleSendClarification(mission.id)}
                  />
                  <TouchableOpacity
                    style={[
                      styles.clarifyButton,
                      (!clarifyText[mission.id]?.trim() || sendingClarify[mission.id]) &&
                        styles.clarifyButtonDisabled,
                    ]}
                    onPress={() => handleSendClarification(mission.id)}
                    disabled={!clarifyText[mission.id]?.trim() || sendingClarify[mission.id]}
                  >
                    {sendingClarify[mission.id] ? (
                      <ActivityIndicator size="small" color={colors.text} />
                    ) : (
                      <Text style={styles.clarifyButtonText}>Send</Text>
                    )}
                  </TouchableOpacity>
                </View>
              </View>
            )}

            {/* Steps */}
            {mission.steps ? (
              <View style={styles.stepsContainer}>
                {mission.steps.map(renderStep)}
              </View>
            ) : (
              <ActivityIndicator
                size="small"
                color={colors.textMuted}
                style={{ marginVertical: spacing.sm }}
              />
            )}

            {/* Action buttons */}
            <View style={styles.actionRow}>
              {mission.state === 'awaiting_confirm' && (
                <TouchableOpacity
                  style={[styles.actionButton, styles.confirmButton]}
                  onPress={() => handleConfirm(mission.id)}
                >
                  <Text style={styles.actionButtonText}>Confirm</Text>
                </TouchableOpacity>
              )}
              {['pending', 'running', 'awaiting_confirm', 'needs_clarification'].includes(
                mission.state
              ) && (
                <TouchableOpacity
                  style={[styles.actionButton, styles.cancelButton]}
                  onPress={() => handleCancel(mission.id)}
                >
                  <Text style={styles.cancelButtonText}>Cancel</Text>
                </TouchableOpacity>
              )}
            </View>

            <Text style={styles.timestamp}>
              Created {new Date(mission.created_at).toLocaleString()}
            </Text>
          </View>
        )}
      </TouchableOpacity>
    );
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
      {/* Filter tabs */}
      <View style={styles.filterRow}>
        {filters.map((f) => (
          <TouchableOpacity
            key={f.label}
            style={[styles.filterTab, filter === f.value && styles.filterTabActive]}
            onPress={() => setFilter(f.value)}
          >
            <Text
              style={[
                styles.filterTabText,
                filter === f.value && styles.filterTabTextActive,
              ]}
            >
              {f.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />
        }
      >
        {missions.length === 0 ? (
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyIcon}>{'(agent)'}</Text>
            <Text style={styles.emptyText}>No agent tasks</Text>
            <Text style={styles.emptySubtext}>
              Agent tasks dispatched from chat will appear here
            </Text>
          </View>
        ) : (
          missions.map(renderMission)
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
  filterRow: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.xs,
    backgroundColor: colors.surface,
  },
  filterTab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
  },
  filterTabActive: {
    backgroundColor: colors.primary + '33',
  },
  filterTabText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  filterTabTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.md,
  },
  missionCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  missionCardRunning: {
    borderColor: colors.info + '40',
  },
  missionCardClarification: {
    borderColor: '#f97316' + '40',
  },
  missionHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  statusDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 2,
  },
  statusDotText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
  missionInfo: {
    flex: 1,
  },
  missionState: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  missionTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '500',
    lineHeight: 22,
  },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  progressBar: {
    flex: 1,
    height: 4,
    backgroundColor: colors.surfaceLight,
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 2,
  },
  progressDone: {
    backgroundColor: colors.success,
  },
  progressFailed: {
    backgroundColor: colors.error,
  },
  progressText: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    minWidth: 30,
    textAlign: 'right',
  },
  expandedContent: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  missionDescription: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
    lineHeight: 20,
  },
  clarifyContainer: {
    backgroundColor: '#f97316' + '15',
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: '#f97316' + '30',
  },
  clarifyLabel: {
    fontSize: fontSizes.sm,
    color: '#f97316',
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  clarifyInputRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  clarifyInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: fontSizes.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  clarifyButton: {
    backgroundColor: '#f97316',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  clarifyButtonDisabled: {
    opacity: 0.5,
  },
  clarifyButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  stepsContainer: {
    marginBottom: spacing.sm,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: spacing.xs,
    gap: spacing.sm,
  },
  stepDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.textMuted,
    marginTop: 5,
  },
  stepDotDone: {
    backgroundColor: colors.success,
  },
  stepDotFailed: {
    backgroundColor: colors.error,
  },
  stepDotRunning: {
    backgroundColor: colors.info,
  },
  stepContent: {
    flex: 1,
  },
  stepText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    lineHeight: 18,
  },
  stepError: {
    fontSize: fontSizes.xs,
    color: colors.error,
    marginTop: 2,
  },
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  actionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  confirmButton: {
    backgroundColor: colors.success + '33',
  },
  cancelButton: {
    backgroundColor: colors.error + '20',
  },
  actionButtonText: {
    color: colors.success,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  cancelButtonText: {
    color: colors.error,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  timestamp: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyIcon: {
    fontSize: fontSizes.xxl,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: fontSizes.lg,
    color: colors.textSecondary,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  emptySubtext: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
    paddingHorizontal: spacing.xl,
  },
});

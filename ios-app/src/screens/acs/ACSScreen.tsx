import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  FlatList,
  TextInput,
  RefreshControl,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SimpleMarkdown from '../../components/chat/SimpleMarkdown';

// ─── Types ───────────────────────────────────────────

type TabType = 'status' | 'plan' | 'interests' | 'curiosity' | 'directives' | 'sessions' | 'show-david' | 'self-model';

interface ACSSnapshot {
  state: string;
  emotional_state?: string;
  daily_plan?: string;
  live_session?: {
    id: string;
    mode: string;
    turns: number;
    notes_created: number;
    elapsed_minutes: number;
  };
  last_session?: {
    mode: string;
    turns: number;
    notes_created: number;
    started_at: string;
    ended_at: string;
    end_reason: string;
  };
}

interface InterestNode {
  id: string;
  label: string;
  description?: string;
  fascination: number;
  depth: number;
  confidence: number;
  status: string;
  source: string;
}

interface CuriosityItem {
  id: string;
  topic: string;
  question?: string;
  source?: string;
  created_at?: string;
}

interface Directive {
  id: string;
  directive_type: string;
  content: string;
  priority: string;
  status: string;
  source: string;
  response?: string;
  created_at: string;
}

interface SessionSummary {
  id: string;
  cognitive_mode: string;
  state: string;
  turns_completed: number;
  notes_created: number;
  duration_minutes?: number;
  duration_seconds?: number;
  outcome_type?: string;
  artifact_summary?: string;
  started_at: string;
  ended_at?: string;
  context_summary?: string;
}

interface SessionDetail {
  context_summary?: string;
  token_usage?: number | Record<string, number>;
  engagement_score?: number;
  model_id?: string;
  error_log?: string | null;
  notes?: Array<{ id: string; title: string; folder?: string; created_at: string }>;
  interest_nodes_created?: number;
  interest_nodes_updated?: number;
  interest_edges_created?: number;
  outcome_type?: string;
  artifact_summary?: string;
  outbound_messages?: number;
  suppressed_messages?: number;
}

interface ShowDavidItem {
  id: string;
  category: string;
  title: string;
  content: string;
  shown: boolean;
  created_at: string;
}

interface SelfModelVersion {
  content: Record<string, any>;
  version: number;
  created_at: string;
}

// ─── Constants ───────────────────────────────────────

const TABS: { key: TabType; label: string; icon: string }[] = [
  { key: 'status', label: 'Status', icon: '\u26A1' },
  { key: 'plan', label: 'Plan', icon: '\uD83D\uDCCB' },
  { key: 'interests', label: 'Interests', icon: '\uD83E\uDDE0' },
  { key: 'curiosity', label: 'Curiosity', icon: '\uD83D\uDD2D' },
  { key: 'directives', label: 'Directives', icon: '\uD83C\uDFAF' },
  { key: 'sessions', label: 'Sessions', icon: '\uD83D\uDCC4' },
  { key: 'show-david', label: 'Show David', icon: '\uD83D\uDCA1' },
  { key: 'self-model', label: 'Self', icon: '\uD83E\uDE9E' },
];

const STATE_CONFIG: Record<string, { label: string; color: string }> = {
  autonomous: { label: 'Autonomous', color: colors.success },
  cooldown: { label: 'Cooldown', color: colors.textMuted },
  conversational: { label: 'Conversational', color: colors.info },
  pausing: { label: 'Pausing', color: colors.warning },
  paused: { label: 'Paused', color: colors.warning },
  idle: { label: 'Idle', color: colors.textMuted },
};

const DIRECTIVE_TYPES = ['focus', 'stop', 'context', 'redirect', 'question'];

// ─── Helpers ─────────────────────────────────────────

function formatDuration(seconds?: number, minutes?: number): string {
  if ((!seconds || seconds <= 0) && minutes && minutes > 0) {
    seconds = minutes * 60;
  }
  if (!seconds) return '--';
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function formatTokenUsage(tokenUsage?: number | Record<string, number>): string {
  if (tokenUsage == null) return '--';
  if (typeof tokenUsage === 'number') return tokenUsage.toLocaleString();
  const total = Object.values(tokenUsage).reduce((sum, value) => {
    return sum + (typeof value === 'number' ? value : 0);
  }, 0);
  return total.toLocaleString();
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

// ─── Main Component ──────────────────────────────────

export default function ACSScreen() {
  const [activeTab, setActiveTab] = useState<TabType>('status');
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    // Each tab handles its own data refresh via key prop or internal effect
    // We just trigger re-render
    setTimeout(() => setRefreshing(false), 500);
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Tab bar */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabBar}
        contentContainerStyle={styles.tabBarContent}
      >
        {TABS.map((tab) => (
          <TouchableOpacity
            key={tab.key}
            style={[styles.tab, activeTab === tab.key && styles.tabActive]}
            onPress={() => setActiveTab(tab.key)}
          >
            <Text style={styles.tabIcon}>{tab.icon}</Text>
            <Text style={[styles.tabLabel, activeTab === tab.key && styles.tabLabelActive]}>
              {tab.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Tab content */}
      {activeTab === 'status' && <StatusTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'plan' && <PlanTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'interests' && <InterestsTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'curiosity' && <CuriosityTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'directives' && <DirectivesTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'sessions' && <SessionsTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'show-david' && <ShowDavidTab refreshing={refreshing} onRefresh={onRefresh} />}
      {activeTab === 'self-model' && <SelfModelTab refreshing={refreshing} onRefresh={onRefresh} />}
    </SafeAreaView>
  );
}

// ─── Status Tab ──────────────────────────────────────

function StatusTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [snapshot, setSnapshot] = useState<ACSSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchSnapshot = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/snapshot');
      setSnapshot(data as ACSSnapshot);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, 15_000);
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  useEffect(() => {
    if (refreshing) fetchSnapshot();
  }, [refreshing, fetchSnapshot]);

  const handleAction = async (action: 'start' | 'pause' | 'resume') => {
    setActionLoading(true);
    try {
      if (action === 'start') {
        await apiClient.post('/api/acs/start');
      } else if (action === 'pause') {
        await apiClient.post('/api/acs/pause');
      } else if (action === 'resume') {
        await apiClient.post('/api/acs/resume');
      }
      await fetchSnapshot();
    } catch (err: any) {
      Alert.alert('Error', err?.message || 'Action failed');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!snapshot) {
    return (
      <ScrollView
        style={styles.tabContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      >
        <Text style={styles.emptyText}>Unable to load ACS status</Text>
      </ScrollView>
    );
  }

  const stateConfig = STATE_CONFIG[snapshot.state] || STATE_CONFIG.idle;
  const isLive = !!snapshot.live_session;

  return (
    <ScrollView
      style={styles.tabContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
    >
      {/* State card */}
      <View style={styles.card}>
        <View style={styles.stateHeader}>
          <View style={[styles.stateDot, { backgroundColor: stateConfig.color }]} />
          <Text style={[styles.stateText, { color: stateConfig.color }]}>{stateConfig.label}</Text>
        </View>

        {snapshot.emotional_state && (
          <Text style={styles.emotionalState}>Emotional state: {snapshot.emotional_state}</Text>
        )}

        {/* Action buttons */}
        <View style={styles.actionRow}>
          {snapshot.state === 'idle' && (
            <TouchableOpacity
              style={[styles.actionBtn, styles.actionBtnPrimary]}
              onPress={() => handleAction('start')}
              disabled={actionLoading}
            >
              {actionLoading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.actionBtnText}>Start Session</Text>
              )}
            </TouchableOpacity>
          )}
          {(snapshot.state === 'cooldown' || snapshot.state === 'conversational') && (
            <TouchableOpacity
              style={[styles.actionBtn, styles.actionBtnPrimary]}
              onPress={() => handleAction('resume')}
              disabled={actionLoading}
            >
              {actionLoading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.actionBtnText}>Resume</Text>
              )}
            </TouchableOpacity>
          )}
          {snapshot.state === 'autonomous' && (
            <TouchableOpacity
              style={[styles.actionBtn, styles.actionBtnWarning]}
              onPress={() => handleAction('pause')}
              disabled={actionLoading}
            >
              {actionLoading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.actionBtnText}>Pause</Text>
              )}
            </TouchableOpacity>
          )}
          {snapshot.state === 'paused' && (
            <TouchableOpacity
              style={[styles.actionBtn, styles.actionBtnPrimary]}
              onPress={() => handleAction('resume')}
              disabled={actionLoading}
            >
              {actionLoading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.actionBtnText}>Resume</Text>
              )}
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* Live session card */}
      {isLive && snapshot.live_session && (
        <View style={[styles.card, styles.liveCard]}>
          <View style={styles.liveBadge}>
            <View style={styles.liveDot} />
            <Text style={styles.liveLabel}>Live Session</Text>
          </View>
          <View style={styles.sessionDetails}>
            <DetailRow label="Mode" value={snapshot.live_session.mode} />
            <DetailRow label="Turns" value={String(snapshot.live_session.turns)} />
            <DetailRow label="Notes Created" value={String(snapshot.live_session.notes_created)} />
            <DetailRow label="Elapsed" value={`${Math.round(snapshot.live_session.elapsed_minutes)}m`} />
          </View>
        </View>
      )}

      {/* Last session card */}
      {!isLive && snapshot.last_session && (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Last Session</Text>
          <View style={styles.sessionDetails}>
            <DetailRow label="Mode" value={snapshot.last_session.mode} />
            <DetailRow label="Turns" value={String(snapshot.last_session.turns)} />
            <DetailRow label="Notes" value={String(snapshot.last_session.notes_created)} />
            <DetailRow label="Ended" value={timeAgo(snapshot.last_session.ended_at)} />
            <DetailRow label="Reason" value={snapshot.last_session.end_reason} />
          </View>
        </View>
      )}
    </ScrollView>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

// ─── Plan Tab ────────────────────────────────────────

function PlanTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [plan, setPlan] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchPlan = useCallback(async () => {
    try {
      const data = await apiClient.get<ACSSnapshot>('/api/acs/snapshot');
      setPlan((data as ACSSnapshot).daily_plan || null);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlan();
  }, [fetchPlan]);

  useEffect(() => {
    if (refreshing) fetchPlan();
  }, [refreshing, fetchPlan]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.tabContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
    >
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Daily Plan</Text>
        {plan ? (
          <SimpleMarkdown>{plan}</SimpleMarkdown>
        ) : (
          <Text style={styles.emptyText}>No plan generated yet</Text>
        )}
      </View>
    </ScrollView>
  );
}

// ─── Interests Tab ───────────────────────────────────

function InterestsTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [nodes, setNodes] = useState<InterestNode[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchInterests = useCallback(async () => {
    try {
      const data = await apiClient.get<{ nodes: InterestNode[] }>('/api/acs/interest-graph');
      const resp = data as any;
      setNodes(resp?.nodes || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInterests();
  }, [fetchInterests]);

  useEffect(() => {
    if (refreshing) fetchInterests();
  }, [refreshing, fetchInterests]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  const renderNode = ({ item }: { item: InterestNode }) => (
    <View style={styles.card}>
      <View style={styles.interestHeader}>
        <Text style={styles.interestLabel}>{item.label}</Text>
        <Text style={[styles.statusBadge, { color: item.status === 'active' ? colors.success : colors.textMuted }]}>
          {item.status}
        </Text>
      </View>
      {item.description ? (
        <Text style={styles.interestDesc} numberOfLines={2}>{item.description}</Text>
      ) : null}
      <View style={styles.barsContainer}>
        <ProgressBar label="Fascination" value={item.fascination} color={colors.secondary} />
        <ProgressBar label="Depth" value={item.depth} color={colors.info} />
        <ProgressBar label="Confidence" value={item.confidence} color={colors.success} />
      </View>
      <Text style={styles.sourceText}>Source: {item.source}</Text>
    </View>
  );

  return (
    <FlatList
      data={nodes}
      keyExtractor={(item) => item.id}
      renderItem={renderNode}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      ListEmptyComponent={<Text style={styles.emptyText}>No interests tracked yet</Text>}
    />
  );
}

function ProgressBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={styles.progressRow}>
      <Text style={styles.progressLabel}>{label}</Text>
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${Math.min(value, 100)}%`, backgroundColor: color }]} />
      </View>
      <Text style={styles.progressValue}>{value}</Text>
    </View>
  );
}

// ─── Curiosity Tab ───────────────────────────────────

function CuriosityTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [items, setItems] = useState<CuriosityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [newTopic, setNewTopic] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchCuriosity = useCallback(async () => {
    try {
      const data = await apiClient.get<any>('/api/acs/curiosity');
      const resp = data as any;
      setItems(Array.isArray(resp) ? resp : resp?.items || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCuriosity();
  }, [fetchCuriosity]);

  useEffect(() => {
    if (refreshing) fetchCuriosity();
  }, [refreshing, fetchCuriosity]);

  const handleAdd = async () => {
    if (!newTopic.trim()) return;
    setSubmitting(true);
    try {
      await apiClient.post('/api/acs/curiosity', { topic: newTopic.trim() });
      setNewTopic('');
      await fetchCuriosity();
    } catch (err: any) {
      Alert.alert('Error', err?.message || 'Failed to add curiosity');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/acs/curiosity/${id}`);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (err: any) {
      Alert.alert('Error', err?.message || 'Failed to delete');
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <FlatList
      data={items}
      keyExtractor={(item) => item.id}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      ListHeaderComponent={
        <View style={styles.addForm}>
          <TextInput
            style={styles.textInput}
            placeholder="Add a curiosity topic..."
            placeholderTextColor={colors.textMuted}
            value={newTopic}
            onChangeText={setNewTopic}
            onSubmitEditing={handleAdd}
            returnKeyType="send"
          />
          <TouchableOpacity
            style={[styles.addBtn, (!newTopic.trim() || submitting) && styles.addBtnDisabled]}
            onPress={handleAdd}
            disabled={!newTopic.trim() || submitting}
          >
            {submitting ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Text style={styles.addBtnText}>Add</Text>
            )}
          </TouchableOpacity>
        </View>
      }
      renderItem={({ item }) => (
        <View style={styles.card}>
          <View style={styles.curiosityRow}>
            <View style={styles.curiosityContent}>
              <Text style={styles.curiosityTopic}>{item.topic}</Text>
              {item.question ? (
                <Text style={styles.curiosityQuestion}>{item.question}</Text>
              ) : null}
              <Text style={styles.curiosityMeta}>
                {item.source ? `${item.source} \u00B7 ` : ''}{timeAgo(item.created_at)}
              </Text>
            </View>
            <TouchableOpacity
              style={styles.deleteBtn}
              onPress={() => handleDelete(item.id)}
            >
              <Text style={styles.deleteBtnText}>\u2715</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
      ListEmptyComponent={<Text style={styles.emptyText}>No curiosity items yet</Text>}
    />
  );
}

// ─── Directives Tab ──────────────────────────────────

function DirectivesTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [directives, setDirectives] = useState<Directive[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formType, setFormType] = useState('focus');
  const [formContent, setFormContent] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchDirectives = useCallback(async () => {
    try {
      const data = await apiClient.get<{ directives: Directive[] }>('/api/acs/directives');
      const resp = data as any;
      setDirectives(resp?.directives || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDirectives();
  }, [fetchDirectives]);

  useEffect(() => {
    if (refreshing) fetchDirectives();
  }, [refreshing, fetchDirectives]);

  const handleCreate = async () => {
    if (!formContent.trim()) return;
    setSubmitting(true);
    try {
      await apiClient.post('/api/acs/directive', {
        directive_type: formType,
        content: formContent.trim(),
        priority: 'normal',
        source: 'ios',
      });
      setFormContent('');
      setShowForm(false);
      await fetchDirectives();
    } catch (err: any) {
      Alert.alert('Error', err?.message || 'Failed to create directive');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <FlatList
      data={directives}
      keyExtractor={(item) => item.id}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      ListHeaderComponent={
        <View>
          {!showForm ? (
            <TouchableOpacity style={styles.newDirectiveBtn} onPress={() => setShowForm(true)}>
              <Text style={styles.newDirectiveBtnText}>+ New Directive</Text>
            </TouchableOpacity>
          ) : (
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>New Directive</Text>
              {/* Type picker */}
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.typePicker}>
                {DIRECTIVE_TYPES.map((t) => (
                  <TouchableOpacity
                    key={t}
                    style={[styles.typeChip, formType === t && styles.typeChipActive]}
                    onPress={() => setFormType(t)}
                  >
                    <Text style={[styles.typeChipText, formType === t && styles.typeChipTextActive]}>
                      {t}
                    </Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <TextInput
                style={[styles.textInput, styles.textInputMultiline]}
                placeholder="What should Sara do?"
                placeholderTextColor={colors.textMuted}
                value={formContent}
                onChangeText={setFormContent}
                multiline
                numberOfLines={3}
              />
              <View style={styles.formActions}>
                <TouchableOpacity style={styles.cancelBtn} onPress={() => setShowForm(false)}>
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.addBtn, (!formContent.trim() || submitting) && styles.addBtnDisabled]}
                  onPress={handleCreate}
                  disabled={!formContent.trim() || submitting}
                >
                  {submitting ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Text style={styles.addBtnText}>Create</Text>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>
      }
      renderItem={({ item }) => (
        <View style={styles.card}>
          <View style={styles.directiveHeader}>
            <View style={styles.directiveTypeBadge}>
              <Text style={styles.directiveTypeText}>{item.directive_type}</Text>
            </View>
            <Text style={[
              styles.directiveStatus,
              { color: item.status === 'completed' ? colors.success : item.status === 'active' ? colors.info : colors.textMuted },
            ]}>
              {item.status}
            </Text>
          </View>
          <Text style={styles.directiveContent}>{item.content}</Text>
          {item.response ? (
            <Text style={styles.directiveResponse}>{item.response}</Text>
          ) : null}
          <Text style={styles.directiveMeta}>
            {item.source} \u00B7 {item.priority} \u00B7 {timeAgo(item.created_at)}
          </Text>
        </View>
      )}
      ListEmptyComponent={<Text style={styles.emptyText}>No directives yet</Text>}
    />
  );
}

// ─── Sessions Tab ────────────────────────────────────

function SessionsTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<SessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchSessions = useCallback(async () => {
    try {
      const data = await apiClient.get<{ sessions: SessionSummary[] }>('/api/acs/sessions?limit=20');
      const resp = data as any;
      setSessions(resp?.sessions || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  useEffect(() => {
    if (refreshing) fetchSessions();
  }, [refreshing, fetchSessions]);

  const toggleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedId(id);
    setExpandedDetail(null);
    setDetailLoading(true);
    try {
      const [detailData, notesData] = await Promise.all([
        apiClient.get<any>(`/api/acs/sessions/${id}`),
        apiClient.get<any>(`/api/acs/sessions/${id}/notes`).catch(() => ({ notes: [] })),
      ]);
      const resp = detailData as any;
      const notesResp = notesData as any;
      setExpandedDetail({
        context_summary: resp?.context_summary || resp?.summary || undefined,
        token_usage: resp?.token_usage,
        engagement_score: resp?.engagement_score,
        model_id: resp?.model_id,
        error_log: resp?.error_log,
        interest_nodes_created: resp?.interest_nodes_created,
        interest_nodes_updated: resp?.interest_nodes_updated,
        interest_edges_created: resp?.interest_edges_created,
        outcome_type: resp?.outcome_type,
        artifact_summary: resp?.artifact_summary,
        outbound_messages: resp?.outbound_messages,
        suppressed_messages: resp?.suppressed_messages,
        notes: Array.isArray(notesResp) ? notesResp : notesResp?.notes || [],
      });
    } catch {
      setExpandedDetail({ context_summary: 'Failed to load details' });
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  const stateColor = (state: string) => {
    if (state === 'completed' || state === 'ended') return colors.success;
    if (state === 'active' || state === 'running' || state === 'autonomous') return colors.info;
    if (state === 'pausing') return colors.warning;
    if (state === 'failed') return colors.error;
    return colors.textMuted;
  };

  return (
    <FlatList
      data={sessions}
      keyExtractor={(item) => item.id}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      renderItem={({ item }) => (
        <TouchableOpacity style={styles.card} onPress={() => toggleExpand(item.id)} activeOpacity={0.7}>
          <View style={styles.sessionHeader}>
            <Text style={styles.sessionMode}>{item.cognitive_mode}</Text>
            <Text style={[styles.sessionState, { color: stateColor(item.state) }]}>{item.state}</Text>
          </View>
          <View style={styles.sessionStats}>
            <Text style={styles.sessionStat}>{item.turns_completed} turns</Text>
            <Text style={styles.sessionStatDot}>{'\u00B7'}</Text>
            <Text style={styles.sessionStat}>{item.notes_created} notes</Text>
            <Text style={styles.sessionStatDot}>{'\u00B7'}</Text>
            <Text style={styles.sessionStat}>{formatDuration(item.duration_seconds, item.duration_minutes)}</Text>
          </View>
          <Text style={styles.sessionTime}>{timeAgo(item.started_at)}</Text>

          {expandedId === item.id && (
            <View style={styles.sessionExpanded}>
              {detailLoading ? (
                <ActivityIndicator color={colors.textMuted} size="small" />
              ) : expandedDetail ? (
                <View>
                  {/* Stats grid */}
                  {(expandedDetail.token_usage != null || expandedDetail.engagement_score != null || expandedDetail.model_id) && (
                    <View style={styles.sessionDetailGrid}>
                      {expandedDetail.model_id ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Model</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.model_id}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.token_usage != null ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Tokens</Text>
                          <Text style={styles.sessionDetailValue}>{formatTokenUsage(expandedDetail.token_usage)}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.engagement_score != null ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Engagement</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.engagement_score}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.interest_nodes_created ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Nodes +</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.interest_nodes_created}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.interest_edges_created ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Edges +</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.interest_edges_created}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.outbound_messages != null ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Shared</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.outbound_messages}</Text>
                        </View>
                      ) : null}
                      {expandedDetail.suppressed_messages != null ? (
                        <View style={styles.sessionDetailCell}>
                          <Text style={styles.sessionDetailLabel}>Suppressed</Text>
                          <Text style={styles.sessionDetailValue}>{expandedDetail.suppressed_messages}</Text>
                        </View>
                      ) : null}
                    </View>
                  )}

                  {/* Summary */}
                  {expandedDetail.context_summary ? (
                    <View style={{ marginTop: spacing.sm }}>
                      <SimpleMarkdown>{expandedDetail.context_summary}</SimpleMarkdown>
                    </View>
                  ) : null}

                  {expandedDetail.artifact_summary ? (
                    <View style={{ marginTop: spacing.sm }}>
                      <Text style={styles.sectionTitle}>Outcome</Text>
                      <Text style={styles.interestDesc}>{expandedDetail.artifact_summary}</Text>
                    </View>
                  ) : null}

                  {/* Error log */}
                  {expandedDetail.error_log ? (
                    <View style={styles.errorLogBox}>
                      <Text style={styles.errorLogText}>{expandedDetail.error_log}</Text>
                    </View>
                  ) : null}

                  {/* Notes */}
                  {expandedDetail.notes && expandedDetail.notes.length > 0 ? (
                    <View style={{ marginTop: spacing.sm }}>
                      <Text style={styles.sectionTitle}>Notes Created</Text>
                      {expandedDetail.notes.map((note) => (
                        <View key={note.id} style={styles.noteItem}>
                          <Text style={styles.noteItemTitle}>{note.title}</Text>
                          <Text style={styles.noteItemMeta}>
                            {note.folder ? `${note.folder} \u00B7 ` : ''}{timeAgo(note.created_at)}
                          </Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                </View>
              ) : null}
            </View>
          )}
        </TouchableOpacity>
      )}
      ListEmptyComponent={<Text style={styles.emptyText}>No sessions recorded yet</Text>}
    />
  );
}

// ─── Show David Tab ─────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  discovery: '#10b981',
  insight: '#6366f1',
  connection: '#f59e0b',
  question: '#3b82f6',
};

function ShowDavidTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [items, setItems] = useState<ShowDavidItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const fetchItems = useCallback(async () => {
    try {
      const data = await apiClient.get<{ items: ShowDavidItem[]; count: number }>('/api/acs/show-david');
      const resp = data as any;
      setItems(resp?.items || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  useEffect(() => {
    if (refreshing) fetchItems();
  }, [refreshing, fetchItems]);

  const markShown = async (id: string) => {
    try {
      await apiClient.post(`/api/acs/show-david/${id}/shown`, {});
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, shown: true } : i)));
    } catch (err: any) {
      Alert.alert('Error', err?.message || 'Failed to mark as shown');
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  const filtered = showAll ? items : items.filter((i) => !i.shown);

  return (
    <FlatList
      data={filtered}
      keyExtractor={(item) => item.id}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      ListHeaderComponent={
        <TouchableOpacity
          style={styles.showAllToggle}
          onPress={() => setShowAll(!showAll)}
        >
          <Text style={styles.showAllToggleText}>
            {showAll ? 'Show unread only' : `Show all (${items.length})`}
          </Text>
        </TouchableOpacity>
      }
      renderItem={({ item }) => {
        const catColor = CATEGORY_COLORS[item.category] || colors.textMuted;
        return (
          <View style={[styles.card, !item.shown && styles.showDavidCardUnshown]}>
            <View style={styles.showDavidHeader}>
              <View style={[styles.categoryBadge, { backgroundColor: catColor + '20' }]}>
                <Text style={[styles.categoryBadgeText, { color: catColor }]}>
                  {item.category}
                </Text>
              </View>
              <Text style={styles.curiosityMeta}>{timeAgo(item.created_at)}</Text>
            </View>
            <Text style={styles.showDavidTitle}>{item.title}</Text>
            <Text style={styles.showDavidContent}>{item.content}</Text>
            {!item.shown && (
              <TouchableOpacity
                style={styles.markShownBtn}
                onPress={() => markShown(item.id)}
              >
                <Text style={styles.markShownBtnText}>Mark Shown</Text>
              </TouchableOpacity>
            )}
          </View>
        );
      }}
      ListEmptyComponent={
        <Text style={styles.emptyText}>
          {showAll ? 'No items yet' : 'All caught up!'}
        </Text>
      }
    />
  );
}

// ─── Self Model Tab ─────────────────────────────────

function SelfModelTab({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  const [model, setModel] = useState<SelfModelVersion | null>(null);
  const [history, setHistory] = useState<SelfModelVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [showHistory, setShowHistory] = useState(false);

  const fetchModel = useCallback(async () => {
    try {
      const [modelData, historyData] = await Promise.all([
        apiClient.get<{ model: SelfModelVersion }>('/api/acs/self-model'),
        apiClient.get<{ history: SelfModelVersion[] }>('/api/acs/self-model/history').catch(() => ({ history: [] })),
      ]);
      const modelResp = (modelData as any)?.model;
      const historyResp = historyData as any;
      if (modelResp && typeof modelResp === 'object') {
        // API may return {content, version, created_at} or raw content dict
        const hasContentKey = modelResp.content && typeof modelResp.content === 'object' && !Array.isArray(modelResp.content);
        setModel({
          content: hasContentKey ? modelResp.content : modelResp,
          version: modelResp.version ?? 0,
          created_at: modelResp.created_at || '',
        });
      } else {
        setModel(null);
      }
      const histItems = historyResp?.history || [];
      setHistory(histItems.map((h: any) => ({
        content: h?.content && typeof h.content === 'object' ? h.content : {},
        version: h?.version ?? 0,
        created_at: h?.created_at || '',
      })));
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModel();
  }, [fetchModel]);

  useEffect(() => {
    if (refreshing) fetchModel();
  }, [refreshing, fetchModel]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!model) {
    return (
      <ScrollView
        style={styles.tabContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
      >
        <Text style={styles.emptyText}>No self-model available yet</Text>
      </ScrollView>
    );
  }

  const renderValue = (value: any): React.ReactNode => {
    if (value == null) return <Text style={styles.selfModelValue}>--</Text>;
    if (Array.isArray(value)) {
      return (
        <View style={styles.selfModelList}>
          {value.map((item, i) => (
            <View key={i} style={styles.selfModelListItem}>
              <Text style={styles.selfModelBullet}>{'\u2022'}</Text>
              <Text style={styles.selfModelValue}>
                {typeof item === 'object' ? JSON.stringify(item) : String(item)}
              </Text>
            </View>
          ))}
        </View>
      );
    }
    if (typeof value === 'object') {
      return (
        <View style={styles.selfModelNested}>
          {Object.entries(value).map(([k, v]) => (
            <View key={k} style={styles.selfModelRow}>
              <Text style={styles.selfModelNestedKey}>{k}:</Text>
              {renderValue(v)}
            </View>
          ))}
        </View>
      );
    }
    return <Text style={styles.selfModelValue}>{String(value)}</Text>;
  };

  return (
    <ScrollView
      style={styles.tabContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />}
    >
      {/* Header */}
      <View style={styles.card}>
        <View style={styles.selfModelHeader}>
          <Text style={styles.sectionTitle}>Self-Model</Text>
          <Text style={styles.selfModelVersion}>
            v{model.version} {'\u00B7'} {timeAgo(model.created_at)}
          </Text>
        </View>
      </View>

      {/* Content */}
      <View style={styles.card}>
        {Object.entries(model.content || {}).map(([key, value]) => (
          <View key={key} style={styles.selfModelSection}>
            <Text style={styles.selfModelKey}>{key.replace(/_/g, ' ')}</Text>
            {renderValue(value)}
          </View>
        ))}
      </View>

      {/* History */}
      {history.length > 0 && (
        <View style={styles.card}>
          <TouchableOpacity onPress={() => setShowHistory(!showHistory)}>
            <Text style={styles.sectionTitle}>
              History ({history.length}) {showHistory ? '\u25B2' : '\u25BC'}
            </Text>
          </TouchableOpacity>
          {showHistory && history.map((ver, i) => (
            <View key={i} style={styles.historyItem}>
              <Text style={styles.historyVersion}>v{ver.version}</Text>
              <Text style={styles.historyDate}>{timeAgo(ver.created_at)}</Text>
            </View>
          ))}
        </View>
      )}

      <View style={{ height: spacing.xxl }} />
    </ScrollView>
  );
}

// ─── Styles ──────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  tabBar: {
    flexGrow: 0,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tabBarContent: {
    paddingHorizontal: spacing.sm,
    gap: spacing.xs,
    paddingVertical: spacing.sm,
  },
  tab: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
    gap: 4,
  },
  tabActive: {
    backgroundColor: colors.primary + '20',
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  tabIcon: {
    fontSize: 14,
  },
  tabLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontWeight: '600',
  },
  tabLabelActive: {
    color: colors.primary,
  },
  tabContent: {
    flex: 1,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xxl,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  liveCard: {
    borderColor: colors.success + '60',
  },
  sectionTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },

  // Status tab
  stateHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  stateDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  stateText: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  emotionalState: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  actionBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    minWidth: 100,
    alignItems: 'center',
  },
  actionBtnPrimary: {
    backgroundColor: colors.primary,
  },
  actionBtnWarning: {
    backgroundColor: colors.warning,
  },
  actionBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: fontSizes.sm,
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: spacing.sm,
  },
  liveDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.success,
  },
  liveLabel: {
    fontSize: fontSizes.sm,
    color: colors.success,
    fontWeight: '700',
  },
  sessionDetails: {
    gap: 4,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  detailLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  detailValue: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
  },

  // Plan tab
  planText: {
    fontSize: fontSizes.sm,
    color: colors.text,
    lineHeight: 22,
  },
  emptyText: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.xl,
  },

  // Interests tab
  interestHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  interestLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '700',
    flex: 1,
  },
  statusBadge: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  interestDesc: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  barsContainer: {
    gap: 6,
    marginTop: spacing.xs,
  },
  progressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  progressLabel: {
    fontSize: 11,
    color: colors.textMuted,
    width: 80,
  },
  progressTrack: {
    flex: 1,
    height: 6,
    backgroundColor: colors.surfaceLight,
    borderRadius: 3,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 3,
  },
  progressValue: {
    fontSize: 11,
    color: colors.textSecondary,
    width: 28,
    textAlign: 'right',
  },
  sourceText: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },

  // Curiosity tab
  addForm: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  textInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  textInputMultiline: {
    minHeight: 80,
    textAlignVertical: 'top',
    marginBottom: spacing.sm,
  },
  addBtn: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    justifyContent: 'center',
    alignItems: 'center',
    minWidth: 60,
  },
  addBtnDisabled: {
    opacity: 0.5,
  },
  addBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: fontSizes.sm,
  },
  curiosityRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  curiosityContent: {
    flex: 1,
  },
  curiosityTopic: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
  curiosityQuestion: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginTop: 2,
    fontStyle: 'italic',
  },
  curiosityMeta: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 4,
  },
  deleteBtn: {
    padding: spacing.sm,
    marginLeft: spacing.sm,
  },
  deleteBtnText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },

  // Directives tab
  newDirectiveBtn: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.primary + '40',
    borderStyle: 'dashed',
    padding: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  newDirectiveBtnText: {
    color: colors.primary,
    fontWeight: '700',
    fontSize: fontSizes.sm,
  },
  typePicker: {
    flexGrow: 0,
    marginBottom: spacing.sm,
  },
  typeChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surfaceLight,
    marginRight: spacing.xs,
  },
  typeChipActive: {
    backgroundColor: colors.primary + '30',
    borderWidth: 1,
    borderColor: colors.primary,
  },
  typeChipText: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontWeight: '600',
  },
  typeChipTextActive: {
    color: colors.primary,
  },
  formActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
  },
  cancelBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  cancelBtnText: {
    color: colors.textMuted,
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },
  directiveHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  directiveTypeBadge: {
    backgroundColor: colors.secondary + '20',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  directiveTypeText: {
    fontSize: fontSizes.xs,
    color: colors.secondary,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  directiveStatus: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  directiveContent: {
    fontSize: fontSizes.sm,
    color: colors.text,
    lineHeight: 20,
    marginBottom: spacing.xs,
  },
  directiveResponse: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontStyle: 'italic',
    lineHeight: 20,
    marginBottom: spacing.xs,
    paddingLeft: spacing.sm,
    borderLeftWidth: 2,
    borderLeftColor: colors.border,
  },
  directiveMeta: {
    fontSize: 11,
    color: colors.textMuted,
  },

  // Sessions tab
  sessionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  sessionMode: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '700',
    textTransform: 'capitalize',
  },
  sessionState: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  sessionStats: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  sessionStat: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  sessionStatDot: {
    color: colors.textMuted,
  },
  sessionTime: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 4,
  },
  sessionExpanded: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sessionSummary: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    lineHeight: 20,
  },
  sessionDetailGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  sessionDetailCell: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    minWidth: 80,
  },
  sessionDetailLabel: {
    fontSize: 10,
    color: colors.textMuted,
    textTransform: 'uppercase',
    fontWeight: '600',
  },
  sessionDetailValue: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '700',
    marginTop: 2,
  },
  errorLogBox: {
    backgroundColor: '#7f1d1d20',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: '#ef444440',
  },
  errorLogText: {
    fontSize: fontSizes.xs,
    color: '#fca5a5',
    fontFamily: 'monospace',
  },
  noteItem: {
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  noteItemTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
  },
  noteItemMeta: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 2,
  },

  // Show David tab
  showAllToggle: {
    alignSelf: 'flex-end',
    marginBottom: spacing.sm,
  },
  showAllToggleText: {
    fontSize: fontSizes.xs,
    color: colors.primary,
    fontWeight: '600',
  },
  showDavidCardUnshown: {
    borderColor: colors.primary + '40',
  },
  showDavidHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  categoryBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  categoryBadgeText: {
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  showDavidTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  showDavidContent: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    lineHeight: 20,
  },
  markShownBtn: {
    alignSelf: 'flex-start',
    marginTop: spacing.sm,
    backgroundColor: colors.primary + '20',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
  },
  markShownBtnText: {
    fontSize: fontSizes.xs,
    color: colors.primary,
    fontWeight: '700',
  },

  // Self-Model tab
  selfModelHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  selfModelVersion: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  selfModelSection: {
    marginBottom: spacing.md,
  },
  selfModelKey: {
    fontSize: fontSizes.sm,
    color: colors.primary,
    fontWeight: '700',
    textTransform: 'capitalize',
    marginBottom: spacing.xs,
  },
  selfModelValue: {
    fontSize: fontSizes.sm,
    color: colors.text,
    lineHeight: 20,
  },
  selfModelList: {
    gap: 4,
  },
  selfModelListItem: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  selfModelBullet: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  selfModelNested: {
    paddingLeft: spacing.sm,
    borderLeftWidth: 2,
    borderLeftColor: colors.border,
    gap: spacing.xs,
  },
  selfModelNestedKey: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontWeight: '600',
  },
  selfModelRow: {
    marginBottom: 4,
  },
  historyItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  historyVersion: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
  },
  historyDate: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
});

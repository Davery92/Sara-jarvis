import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  TextInput,
  RefreshControl,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

// ─── Types — match /api/acs/v2 ───────────────────────

type TabType = 'mind' | 'interests' | 'tools';

interface DaemonStatus {
  state: string;
  version: string;
  pid: number | null;
  hostname: string | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
  last_tick_summary: string | null;
  is_alive: boolean;
  seconds_since_heartbeat: number | null;
}

interface Focus {
  topic: string | null;
  why: string | null;
  set_at: string | null;
  updated_at: string | null;
}

type Urgency = 'low' | 'normal' | 'high';

interface InboxItem {
  id: string;
  created_at: string;
  created_by: string;
  urgency: Urgency;
  prompt: string;
  context: string | null;
  status: 'queued' | 'in_progress' | 'done' | 'dismissed';
  picked_up_at: string | null;
  completed_at: string | null;
  completion_summary: string | null;
}

interface Activity {
  id: string;
  created_at: string;
  kind: string;
  summary: string;
  body: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

interface Interest {
  id: string;
  topic: string;
  display_name: string;
  why: string | null;
  weight: number;
  last_acted_at: string | null;
  last_updated_at: string;
  source: string;
  created_at: string;
}

interface ToolVersion {
  id: string;
  version: number;
  notes: string | null;
  created_at: string;
}

interface ToolVersionFull extends ToolVersion {
  code: string;
}

interface Tool {
  id: string;
  name: string;
  description: string;
  args_schema: Record<string, unknown>;
  enabled: boolean;
  active_version: ToolVersion | null;
  latest_version: ToolVersion | null;
  invocation_count_24h: number;
  last_invocation_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Invocation {
  id: string;
  tool_id: string;
  version_id: string;
  args: Record<string, unknown>;
  result: unknown;
  error: string | null;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
}

// ─── Helpers ─────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return 'just now';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function uptime(startedAt: string | null | undefined): string {
  if (!startedAt) return '—';
  const ms = Date.now() - new Date(startedAt).getTime();
  if (ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

const KIND_LABEL: Record<string, string> = {
  boot: 'boot',
  shutdown: 'shutdown',
  tick: 'tick',
  thought: 'thought',
  reflection: 'reflect',
  focus_set: 'focus',
  focus_clear: 'unfocus',
  notify_david: 'notified',
  inbox_pickup: 'pickup',
  inbox_complete: 'done',
  inbox_dismiss: 'dismiss',
  tool_call: 'tool',
  tool_result: 'result',
  external_event: 'event',
  error: 'error',
};

const KIND_COLOR: Record<string, string> = {
  boot: '#10b981',
  shutdown: '#71717a',
  tick: '#52525b',
  thought: '#818cf8',
  reflection: '#a78bfa',
  focus_set: '#38bdf8',
  focus_clear: '#38bdf8',
  notify_david: '#f59e0b',
  inbox_pickup: '#22d3ee',
  inbox_complete: '#10b981',
  inbox_dismiss: '#fb923c',
  tool_call: '#e879f9',
  tool_result: '#e879f9',
  external_event: '#a1a1aa',
  error: '#ef4444',
};

const URGENCY_COLOR: Record<Urgency, string> = {
  high: '#ef4444',
  normal: '#a1a1aa',
  low: '#71717a',
};

const SOURCE_COLOR: Record<string, string> = {
  reflection: '#a78bfa',
  external_event: '#a1a1aa',
  manual: '#f59e0b',
};

// ─── Main Component ──────────────────────────────────

export default function ACSScreen() {
  const [activeTab, setActiveTab] = useState<TabType>('mind');
  const [refreshing, setRefreshing] = useState(false);
  const [, setTick] = useState(0);

  // Re-render once a second so timeAgo refreshes
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.tabBar}>
        {(['mind', 'interests', 'tools'] as TabType[]).map((t) => (
          <TouchableOpacity
            key={t}
            style={[styles.tab, activeTab === t && styles.tabActive]}
            onPress={() => setActiveTab(t)}
          >
            <Text
              style={[
                styles.tabLabel,
                activeTab === t && styles.tabLabelActive,
              ]}
            >
              {t === 'mind' ? 'Mind' : t === 'interests' ? 'Interests' : 'Tools'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {activeTab === 'mind' && (
        <MindTab refreshing={refreshing} setRefreshing={setRefreshing} />
      )}
      {activeTab === 'interests' && (
        <InterestsTab refreshing={refreshing} setRefreshing={setRefreshing} />
      )}
      {activeTab === 'tools' && (
        <ToolsTab refreshing={refreshing} setRefreshing={setRefreshing} />
      )}
    </SafeAreaView>
  );
}

// ─── Mind tab ────────────────────────────────────────

function MindTab({
  refreshing,
  setRefreshing,
}: {
  refreshing: boolean;
  setRefreshing: (b: boolean) => void;
}) {
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newPrompt, setNewPrompt] = useState('');
  const [newUrgency, setNewUrgency] = useState<Urgency>('normal');
  const [submitting, setSubmitting] = useState(false);
  const [expandedActivity, setExpandedActivity] = useState<Set<string>>(
    new Set(),
  );

  const fetchAll = useCallback(async () => {
    try {
      const [d, f, i, a] = await Promise.all([
        apiClient.get<DaemonStatus>('/api/acs/v2/daemon-status'),
        apiClient.get<Focus>('/api/acs/v2/focus'),
        apiClient.get<InboxItem[]>('/api/acs/v2/inbox?limit=20'),
        apiClient.get<Activity[]>('/api/acs/v2/activity?limit=50'),
      ]);
      setDaemon(d);
      setFocus(f);
      setInbox(i);
      setActivity(a);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const refresh = setInterval(fetchAll, 8000);
    return () => clearInterval(refresh);
  }, [fetchAll]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
  }, [fetchAll, setRefreshing]);

  const submitInbox = async () => {
    const text = newPrompt.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    try {
      await apiClient.post('/api/acs/v2/inbox', {
        prompt: text,
        urgency: newUrgency,
        created_by: 'david_ios',
      });
      setNewPrompt('');
      setNewUrgency('normal');
      await fetchAll();
    } catch (e: any) {
      Alert.alert('Could not queue', e?.message || 'request failed');
    } finally {
      setSubmitting(false);
    }
  };

  const toggleActivity = (id: string) => {
    setExpandedActivity((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading && !daemon) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  const liveness = livenessLabel(daemon);

  return (
    <ScrollView
      style={styles.tabContent}
      contentContainerStyle={styles.tabContentPad}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.textMuted}
        />
      }
    >
      {/* Liveness card */}
      <View style={styles.card}>
        <View style={styles.row}>
          <View style={styles.rowStart}>
            <View
              style={[
                styles.dot,
                { backgroundColor: liveness.color },
              ]}
            />
            <Text style={[styles.livenessText, { color: liveness.color }]}>
              {liveness.text}
            </Text>
            {daemon?.version ? (
              <Text style={styles.metaDim}>v{daemon.version}</Text>
            ) : null}
          </View>
          <Text style={styles.metaDim}>
            heartbeat {timeAgo(daemon?.last_heartbeat_at)}
          </Text>
        </View>
        <View style={styles.statsGrid}>
          <Stat label="host" value={daemon?.hostname || '—'} />
          <Stat label="pid" value={daemon?.pid != null ? String(daemon.pid) : '—'} />
          <Stat label="uptime" value={uptime(daemon?.started_at)} />
          <Stat
            label="last tick"
            value={daemon?.last_tick_summary || '—'}
            numberOfLines={1}
          />
        </View>
      </View>

      {/* Focus card */}
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.cardTitle}>Current focus</Text>
          {focus?.set_at ? (
            <Text style={styles.metaDim}>set {timeAgo(focus.set_at)}</Text>
          ) : null}
        </View>
        {focus?.topic ? (
          <>
            <Text style={styles.focusTopic}>{focus.topic}</Text>
            {focus.why ? (
              <Text style={styles.focusWhy}>{focus.why}</Text>
            ) : null}
          </>
        ) : (
          <Text style={styles.empty}>between things</Text>
        )}
      </View>

      {/* Queue */}
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.cardTitle}>Queue</Text>
          <Text style={styles.metaDim}>{inbox.length} active</Text>
        </View>

        <View style={styles.formRow}>
          <TextInput
            value={newPrompt}
            onChangeText={setNewPrompt}
            placeholder="Queue something for Sara…"
            placeholderTextColor={colors.textMuted}
            style={styles.input}
            multiline
          />
          <View style={styles.urgencyRow}>
            {(['low', 'normal', 'high'] as Urgency[]).map((u) => (
              <TouchableOpacity
                key={u}
                onPress={() => setNewUrgency(u)}
                style={[
                  styles.urgencyPill,
                  newUrgency === u && styles.urgencyPillActive,
                ]}
              >
                <Text
                  style={[
                    styles.urgencyPillText,
                    newUrgency === u && styles.urgencyPillTextActive,
                  ]}
                >
                  {u}
                </Text>
              </TouchableOpacity>
            ))}
            <TouchableOpacity
              onPress={submitInbox}
              disabled={!newPrompt.trim() || submitting}
              style={[
                styles.queueBtn,
                (!newPrompt.trim() || submitting) && styles.queueBtnDisabled,
              ]}
            >
              <Text style={styles.queueBtnText}>
                {submitting ? '…' : 'Queue'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>

        {inbox.length === 0 ? (
          <Text style={styles.empty}>empty — nothing queued for her</Text>
        ) : (
          inbox.map((item) => (
            <View key={item.id} style={styles.inboxItem}>
              <View style={styles.rowStart}>
                <Badge
                  text={item.urgency}
                  color={URGENCY_COLOR[item.urgency]}
                />
                <Badge
                  text={
                    item.status === 'in_progress' ? 'in progress' : 'queued'
                  }
                  color={item.status === 'in_progress' ? '#22d3ee' : '#71717a'}
                />
                <Text style={[styles.metaDim, { marginLeft: 'auto' }]}>
                  {timeAgo(item.created_at)}
                </Text>
              </View>
              <Text style={styles.inboxPrompt}>{item.prompt}</Text>
              {item.context ? (
                <Text style={styles.inboxContext}>{item.context}</Text>
              ) : null}
              <Text style={styles.inboxMeta}>
                id={item.id.slice(0, 8)} · from {item.created_by}
              </Text>
            </View>
          ))
        )}
      </View>

      {/* Activity */}
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.cardTitle}>Activity</Text>
          <Text style={styles.metaDim}>last {activity.length}</Text>
        </View>
        {activity.length === 0 ? (
          <Text style={styles.empty}>no activity yet</Text>
        ) : (
          activity.map((a) => {
            const expanded = expandedActivity.has(a.id);
            const hasBody = !!a.body && a.body.trim().length > 0;
            const color = KIND_COLOR[a.kind] || '#a1a1aa';
            return (
              <TouchableOpacity
                key={a.id}
                activeOpacity={hasBody ? 0.6 : 1}
                onPress={() => hasBody && toggleActivity(a.id)}
                style={styles.activityRow}
              >
                <View style={styles.activityHeader}>
                  <Badge text={KIND_LABEL[a.kind] || a.kind} color={color} />
                  <Text style={[styles.metaDim, styles.activityTime]}>
                    {timeAgo(a.created_at)}
                  </Text>
                  <Text style={styles.activitySummary} numberOfLines={2}>
                    {a.summary}
                  </Text>
                  {hasBody ? (
                    <Text style={styles.activityChevron}>
                      {expanded ? '▾' : '▸'}
                    </Text>
                  ) : null}
                </View>
                {expanded && hasBody ? (
                  <Text style={styles.activityBody}>{a.body}</Text>
                ) : null}
              </TouchableOpacity>
            );
          })
        )}
      </View>

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </ScrollView>
  );
}

function livenessLabel(d: DaemonStatus | null): { text: string; color: string } {
  if (!d) return { text: 'unknown', color: colors.textMuted };
  if (d.state === 'never_started')
    return { text: 'never started', color: colors.textMuted };
  if (!d.is_alive) return { text: 'dead', color: colors.error };
  if (d.state === 'thinking') return { text: 'thinking', color: '#818cf8' };
  if (d.state === 'reflecting') return { text: 'reflecting', color: '#a78bfa' };
  return { text: 'alive', color: colors.success };
}

// ─── Interests tab ───────────────────────────────────

function InterestsTab({
  refreshing,
  setRefreshing,
}: {
  refreshing: boolean;
  setRefreshing: (b: boolean) => void;
}) {
  const [interests, setInterests] = useState<Interest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await apiClient.get<Interest[]>(
        '/api/acs/v2/interests?limit=20',
      );
      setInterests(data);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const id = setInterval(fetch, 15000);
    return () => clearInterval(id);
  }, [fetch]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetch();
    setRefreshing(false);
  }, [fetch, setRefreshing]);

  const remove = (item: Interest) => {
    Alert.alert(
      'Remove interest?',
      `"${item.display_name}" — Sara will stop seeding it.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: async () => {
            try {
              await apiClient.delete(`/api/acs/v2/interests/${item.id}`);
              await fetch();
            } catch (e: any) {
              Alert.alert('Failed', e?.message || 'request failed');
            }
          },
        },
      ],
    );
  };

  const maxWeight = Math.max(1, ...interests.map((i) => i.weight));

  if (loading && interests.length === 0) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.tabContent}
      contentContainerStyle={styles.tabContentPad}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.textMuted}
        />
      }
    >
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.cardTitle}>Interests</Text>
          <Text style={styles.metaDim}>{interests.length} tracked</Text>
        </View>

        {error ? <Text style={styles.errorText}>{error}</Text> : null}

        {interests.length === 0 && !error ? (
          <Text style={styles.empty}>
            nothing tracked yet — she'll seed these from her reflections
          </Text>
        ) : (
          interests.map((i) => {
            const pct = Math.round((i.weight / maxWeight) * 100);
            return (
              <View key={i.id} style={styles.interestItem}>
                <View style={styles.rowStart}>
                  <Badge
                    text={i.source.replace('_', ' ')}
                    color={SOURCE_COLOR[i.source] || '#a78bfa'}
                  />
                  <Text style={styles.interestName} numberOfLines={1}>
                    {i.display_name}
                  </Text>
                  <Text style={[styles.metaDim, { marginLeft: 'auto' }]}>
                    weight {i.weight.toFixed(2)}
                  </Text>
                </View>
                <View style={styles.weightBarTrack}>
                  <View
                    style={[styles.weightBarFill, { width: `${pct}%` }]}
                  />
                </View>
                {i.why ? (
                  <Text style={styles.interestWhy} numberOfLines={2}>
                    {i.why}
                  </Text>
                ) : null}
                <View style={styles.row}>
                  <Text style={styles.metaDim}>
                    touched {timeAgo(i.last_acted_at)} · updated{' '}
                    {timeAgo(i.last_updated_at)}
                  </Text>
                  <TouchableOpacity onPress={() => remove(i)}>
                    <Text style={styles.removeBtn}>Remove</Text>
                  </TouchableOpacity>
                </View>
              </View>
            );
          })
        )}
      </View>
    </ScrollView>
  );
}

// ─── Tools tab ───────────────────────────────────────

function ToolsTab({
  refreshing,
  setRefreshing,
}: {
  refreshing: boolean;
  setRefreshing: (b: boolean) => void;
}) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, ToolVersionFull[]>>(
    {},
  );
  const [invocations, setInvocations] = useState<Record<string, Invocation[]>>(
    {},
  );
  const [busy, setBusy] = useState<string | null>(null);

  const fetchTools = useCallback(async () => {
    try {
      const data = await apiClient.get<Tool[]>('/api/acs/v2/user_tools');
      setTools(data);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTools();
    const id = setInterval(fetchTools, 15000);
    return () => clearInterval(id);
  }, [fetchTools]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchTools();
    setRefreshing(false);
  }, [fetchTools, setRefreshing]);

  const fetchDetails = useCallback(async (name: string) => {
    try {
      const [v, inv] = await Promise.all([
        apiClient.get<ToolVersionFull[]>(
          `/api/acs/v2/user_tools/${name}/versions`,
        ),
        apiClient.get<Invocation[]>(
          `/api/acs/v2/user_tools/${name}/invocations?limit=10`,
        ),
      ]);
      setVersions((p) => ({ ...p, [name]: v }));
      setInvocations((p) => ({ ...p, [name]: inv }));
    } catch (e: any) {
      setError(e?.message || 'Failed to load details');
    }
  }, []);

  const toggle = (name: string) => {
    if (expanded === name) {
      setExpanded(null);
    } else {
      setExpanded(name);
      if (!versions[name]) fetchDetails(name);
    }
  };

  const enable = async (name: string) => {
    setBusy(name);
    try {
      await apiClient.post(`/api/acs/v2/user_tools/${name}/enable`);
      await fetchTools();
    } catch (e: any) {
      Alert.alert('Failed', e?.message || 'request failed');
    } finally {
      setBusy(null);
    }
  };

  const disable = async (name: string) => {
    setBusy(name);
    try {
      await apiClient.post(`/api/acs/v2/user_tools/${name}/disable`);
      await fetchTools();
    } catch (e: any) {
      Alert.alert('Failed', e?.message || 'request failed');
    } finally {
      setBusy(null);
    }
  };

  const remove = (name: string) => {
    Alert.alert(
      `Delete tool "${name}"?`,
      'This removes all versions and the invocation log.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            setBusy(name);
            try {
              await apiClient.delete(`/api/acs/v2/user_tools/${name}`);
              await fetchTools();
            } catch (e: any) {
              Alert.alert('Failed', e?.message || 'request failed');
            } finally {
              setBusy(null);
            }
          },
        },
      ],
    );
  };

  if (loading && tools.length === 0) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  const pending = tools.filter((t) => !t.enabled);
  const active = tools.filter((t) => t.enabled);

  const renderTool = (t: Tool) => {
    const isExpanded = expanded === t.name;
    const activeVersion = t.active_version?.version;
    const v = versions[t.name] || [];
    const inv = invocations[t.name] || [];
    return (
      <View key={t.id} style={styles.toolItem}>
        <View style={styles.toolHeader}>
          <View
            style={[
              styles.toolDot,
              { backgroundColor: t.enabled ? colors.success : colors.warning },
            ]}
          />
          <View style={{ flex: 1 }}>
            <View style={styles.rowStart}>
              <Text style={styles.toolName}>{t.name}</Text>
              <Text style={styles.metaDim}>
                v{activeVersion ?? '?'}
              </Text>
              {t.latest_version &&
              t.latest_version.version !== activeVersion ? (
                <Text style={styles.toolLatestWarn}>
                  (latest v{t.latest_version.version})
                </Text>
              ) : null}
              <Text style={[styles.metaDim, { marginLeft: 'auto' }]}>
                {t.invocation_count_24h}/24h
              </Text>
            </View>
            <Text style={styles.toolDesc}>{t.description}</Text>
          </View>
        </View>

        <View style={styles.toolActions}>
          {t.enabled ? (
            <TouchableOpacity
              style={styles.btn}
              disabled={busy === t.name}
              onPress={() => disable(t.name)}
            >
              <Text style={styles.btnText}>Disable</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              style={[styles.btn, styles.btnSuccess]}
              disabled={busy === t.name}
              onPress={() => enable(t.name)}
            >
              <Text style={[styles.btnText, styles.btnTextOnSuccess]}>
                Enable
              </Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity
            style={styles.btn}
            onPress={() => toggle(t.name)}
          >
            <Text style={styles.btnText}>
              {isExpanded ? 'Hide' : 'Details'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.btn}
            onPress={() => remove(t.name)}
          >
            <Text style={[styles.btnText, { color: colors.error }]}>
              Delete
            </Text>
          </TouchableOpacity>
        </View>

        {isExpanded ? (
          <View style={styles.toolDetails}>
            <Text style={styles.detailHeader}>Args schema</Text>
            <Text style={styles.codeBlock} selectable>
              {JSON.stringify(t.args_schema, null, 2)}
            </Text>

            <Text style={styles.detailHeader}>Versions ({v.length})</Text>
            {v.map((ver) => (
              <View key={ver.id} style={styles.versionBlock}>
                <View style={styles.rowStart}>
                  <Text style={styles.versionLabel}>v{ver.version}</Text>
                  {ver.version === activeVersion ? (
                    <Text style={styles.activeBadge}>ACTIVE</Text>
                  ) : null}
                  <Text style={[styles.metaDim, { marginLeft: 'auto' }]}>
                    {timeAgo(ver.created_at)}
                  </Text>
                </View>
                {ver.notes ? (
                  <Text style={styles.versionNotes}>"{ver.notes}"</Text>
                ) : null}
                <Text style={styles.codeBlock} selectable>
                  {ver.code}
                </Text>
              </View>
            ))}

            <Text style={styles.detailHeader}>
              Recent invocations ({inv.length})
            </Text>
            {inv.length === 0 ? (
              <Text style={styles.empty}>no calls yet</Text>
            ) : (
              inv.map((iv) => (
                <View key={iv.id} style={styles.invocationBlock}>
                  <View style={styles.rowStart}>
                    <Badge
                      text={iv.error ? 'error' : 'ok'}
                      color={iv.error ? colors.error : colors.success}
                    />
                    <Text style={styles.metaDim}>
                      {timeAgo(iv.started_at)}
                    </Text>
                    {iv.duration_ms != null ? (
                      <Text style={[styles.metaDim, { marginLeft: 'auto' }]}>
                        {iv.duration_ms}ms
                      </Text>
                    ) : null}
                  </View>
                  <Text style={styles.codeBlock} selectable>
                    args: {JSON.stringify(iv.args)}
                  </Text>
                  {iv.error ? (
                    <Text
                      style={[styles.codeBlock, { color: colors.error }]}
                      selectable
                    >
                      {iv.error}
                    </Text>
                  ) : null}
                  {iv.result !== null && iv.result !== undefined ? (
                    <Text style={styles.codeBlock} selectable>
                      → {JSON.stringify(iv.result)}
                    </Text>
                  ) : null}
                </View>
              ))
            )}
          </View>
        ) : null}
      </View>
    );
  };

  return (
    <ScrollView
      style={styles.tabContent}
      contentContainerStyle={styles.tabContentPad}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.textMuted}
        />
      }
    >
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.cardTitle}>Tools</Text>
          <Text style={styles.metaDim}>
            {active.length} active
            {pending.length > 0 ? ` · ${pending.length} pending` : ''}
          </Text>
        </View>

        {error ? <Text style={styles.errorText}>{error}</Text> : null}

        {pending.length > 0 ? (
          <>
            <Text style={styles.sectionHeader}>Pending review</Text>
            {pending.map(renderTool)}
          </>
        ) : null}

        {active.length > 0 ? (
          <>
            {pending.length > 0 ? (
              <Text style={styles.sectionHeader}>Active</Text>
            ) : null}
            {active.map(renderTool)}
          </>
        ) : null}

        {tools.length === 0 && !error ? (
          <Text style={styles.empty}>
            no user tools yet — Sara will propose these as she works
          </Text>
        ) : null}
      </View>
    </ScrollView>
  );
}

// ─── Small bits ──────────────────────────────────────

function Stat({
  label,
  value,
  numberOfLines = 1,
}: {
  label: string;
  value: string;
  numberOfLines?: number;
}) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue} numberOfLines={numberOfLines}>
        {value}
      </Text>
    </View>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <View style={[styles.badge, { borderColor: color + '60', backgroundColor: color + '20' }]}>
      <Text style={[styles.badgeText, { color }]}>{text}</Text>
    </View>
  );
}

// ─── Styles ──────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centerFill: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabBar: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm + 2,
    alignItems: 'center',
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  tabActive: {
    borderBottomColor: colors.primary,
  },
  tabLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    fontWeight: '600',
  },
  tabLabelActive: {
    color: colors.text,
  },
  tabContent: {
    flex: 1,
  },
  tabContentPad: {
    padding: spacing.md,
    paddingBottom: spacing.xl,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '700',
    color: colors.text,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  rowStart: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flex: 1,
  },
  metaDim: {
    fontSize: 11,
    color: colors.textMuted,
  },
  empty: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    fontStyle: 'italic',
    paddingVertical: spacing.sm,
  },
  errorText: {
    color: colors.error,
    fontSize: fontSizes.sm,
    paddingVertical: spacing.xs,
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  livenessText: {
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  stat: {
    width: '48%',
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
  },
  statLabel: {
    fontSize: 10,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  statValue: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
    marginTop: 2,
  },
  focusTopic: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginTop: spacing.xs,
  },
  focusWhy: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontStyle: 'italic',
    marginTop: 4,
  },
  formRow: {
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: fontSizes.sm,
    minHeight: 40,
    maxHeight: 120,
  },
  urgencyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  urgencyPill: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
  },
  urgencyPillActive: {
    backgroundColor: colors.primary + '30',
    borderColor: colors.primary,
  },
  urgencyPillText: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    fontWeight: '600',
  },
  urgencyPillTextActive: {
    color: colors.text,
  },
  queueBtn: {
    marginLeft: 'auto',
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: borderRadius.md,
  },
  queueBtnDisabled: {
    backgroundColor: colors.surfaceLight,
  },
  queueBtnText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  inboxItem: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.xs,
    borderWidth: 1,
    borderColor: colors.border,
  },
  inboxPrompt: {
    fontSize: fontSizes.sm,
    color: colors.text,
    marginTop: 6,
  },
  inboxContext: {
    fontSize: 12,
    color: colors.textSecondary,
    fontStyle: 'italic',
    marginTop: 2,
  },
  inboxMeta: {
    fontSize: 10,
    color: colors.textMuted,
    marginTop: 4,
  },
  activityRow: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    marginBottom: 4,
  },
  activityHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
  },
  activityTime: {
    width: 36,
    marginTop: 2,
  },
  activitySummary: {
    flex: 1,
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  activityChevron: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  activityBody: {
    color: colors.textSecondary,
    fontSize: 12,
    marginTop: 6,
    paddingLeft: 36,
  },
  badge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  interestItem: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.xs,
    borderWidth: 1,
    borderColor: colors.border,
  },
  interestName: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '500',
    flex: 1,
  },
  interestWhy: {
    fontSize: 12,
    color: colors.textSecondary,
    fontStyle: 'italic',
    marginTop: 4,
  },
  weightBarTrack: {
    height: 3,
    backgroundColor: colors.surfaceLight,
    borderRadius: 2,
    marginTop: 4,
    overflow: 'hidden',
  },
  weightBarFill: {
    height: '100%',
    backgroundColor: '#a78bfa',
  },
  removeBtn: {
    fontSize: 11,
    color: colors.error,
    fontWeight: '600',
  },
  toolItem: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  toolHeader: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  toolDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
  },
  toolName: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontFamily: 'Menlo',
    fontWeight: '600',
  },
  toolLatestWarn: {
    fontSize: 10,
    color: colors.warning,
  },
  toolDesc: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 2,
  },
  toolActions: {
    flexDirection: 'row',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  btn: {
    backgroundColor: colors.surfaceLight,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
    borderRadius: borderRadius.sm,
  },
  btnSuccess: {
    backgroundColor: colors.success,
  },
  btnText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '600',
  },
  btnTextOnSuccess: {
    color: '#fff',
  },
  toolDetails: {
    marginTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  detailHeader: {
    fontSize: 10,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '700',
    marginTop: spacing.sm,
    marginBottom: 4,
  },
  codeBlock: {
    backgroundColor: '#000',
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: 'Menlo',
    padding: spacing.sm,
    borderRadius: borderRadius.sm,
    marginTop: 4,
  },
  versionBlock: {
    backgroundColor: colors.background,
    padding: spacing.sm,
    borderRadius: borderRadius.sm,
    marginTop: 4,
  },
  versionLabel: {
    fontSize: 12,
    fontFamily: 'Menlo',
    color: colors.text,
    fontWeight: '600',
  },
  activeBadge: {
    fontSize: 9,
    color: colors.success,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  versionNotes: {
    fontSize: 11,
    color: colors.textSecondary,
    fontStyle: 'italic',
    marginTop: 2,
  },
  invocationBlock: {
    backgroundColor: colors.background,
    padding: spacing.sm,
    borderRadius: borderRadius.sm,
    marginTop: 4,
  },
  sectionHeader: {
    fontSize: 10,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '700',
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
});

import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, Dimensions, Alert, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import Ring from '../../components/fitness/ui/Ring';
import StatTile from '../../components/fitness/ui/StatTile';
import TrendChart from '../../components/fitness/ui/TrendChart';
import SegmentedTabs, { SegmentOption } from '../../components/fitness/ui/SegmentedTabs';
import CardioLogModal from '../../components/fitness/CardioLogModal';
import TabataPresetEditor from '../../components/fitness/TabataPresetEditor';
import {
  cardioService, CardioStats, CardioSettings, CardioLog, TabataPreset, activityMeta, tabataTotalSeconds,
} from '../../services/cardio';

type Tab = 'dashboard' | 'log' | 'timers';
const TABS: SegmentOption<Tab>[] = [
  { key: 'dashboard', label: 'This Week' },
  { key: 'log', label: 'Log' },
  { key: 'timers', label: 'Tabata' },
];

const W = Dimensions.get('window').width;

export default function CardioScreen() {
  const navigation = useNavigation<any>();
  const [tab, setTab] = useState<Tab>('dashboard');
  const [stats, setStats] = useState<CardioStats | null>(null);
  const [settings, setSettings] = useState<CardioSettings | null>(null);
  const [logs, setLogs] = useState<CardioLog[]>([]);
  const [presets, setPresets] = useState<TabataPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [logModal, setLogModal] = useState(false);
  const [logInitial, setLogInitial] = useState<any>(null);
  const [editorVisible, setEditorVisible] = useState(false);
  const [editorPreset, setEditorPreset] = useState<TabataPreset | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, cfg, l, p] = await Promise.all([
        cardioService.getStats(0),
        cardioService.getSettings(),
        cardioService.getLogs(),
        cardioService.getPresets(),
      ]);
      setStats(s); setSettings(cfg); setLogs(l.logs); setPresets(p);
    } catch (e) {
      // leave prior state; surface nothing intrusive
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const openMenuLog = (activity: string, minutes: number, title: string) => {
    setLogInitial({ activity_type: activity, duration_minutes: minutes, title });
    setLogModal(true);
  };

  const deleteLog = (log: CardioLog) => {
    Alert.alert('Delete session?', `${activityMeta(log.activity_type).label} · ${log.duration_minutes} min`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => { try { await cardioService.deleteLog(log.id); load(); } catch {} },
      },
    ]);
  };

  const startPreset = (preset: TabataPreset) => {
    navigation.navigate('TabataTimer', { preset });
  };

  if (loading && !stats) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Cardio</Text>
        <View style={{ width: 26 }} />
      </View>

      <View style={styles.tabsWrap}>
        <SegmentedTabs options={TABS} value={tab} onChange={setTab} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
      >
        {tab === 'dashboard' && stats && (
          <DashboardView stats={stats} logs={logs} onDeleteLog={deleteLog} />
        )}

        {tab === 'log' && settings && (
          <LogView settings={settings} onPick={openMenuLog} onCustom={() => { setLogInitial(null); setLogModal(true); }} />
        )}

        {tab === 'timers' && (
          <TimersView
            presets={presets}
            onStart={startPreset}
            onEdit={(p) => { setEditorPreset(p); setEditorVisible(true); }}
            onNew={() => { setEditorPreset(null); setEditorVisible(true); }}
          />
        )}
      </ScrollView>

      <CardioLogModal
        visible={logModal}
        initial={logInitial}
        onClose={() => setLogModal(false)}
        onSaved={load}
      />
      <TabataPresetEditor
        visible={editorVisible}
        preset={editorPreset}
        onClose={() => setEditorVisible(false)}
        onSaved={(p) => { setPresets(prev => {
          const i = prev.findIndex(x => x.id === p.id);
          if (i >= 0) { const c = [...prev]; c[i] = p; return c; }
          return [...prev, p];
        }); }}
        onDeleted={(id) => setPresets(prev => prev.filter(x => x.id !== id))}
        onStart={(cfg) => { setEditorVisible(false); setTimeout(() => navigation.navigate('TabataTimer', { preset: cfg }), 250); }}
      />
    </View>
  );
}

// --------------------------------------------------------------------------- //
function DashboardView({ stats, logs, onDeleteLog }: {
  stats: CardioStats; logs: CardioLog[]; onDeleteLog: (l: CardioLog) => void;
}) {
  const pct = Math.min(stats.total_minutes / (stats.target_min || 1), 1);
  const maxAct = Math.max(1, ...stats.by_activity.map(a => a.minutes));
  const trendVals = stats.trend.map(t => t.minutes);
  const stepsPct = stats.steps_today != null && stats.steps_floor
    ? Math.min(stats.steps_today / stats.steps_floor, 1) : 0;

  return (
    <View style={{ gap: spacing.md }}>
      {/* Weekly dose hero */}
      <View style={styles.hero}>
        <Ring size={168} strokeWidth={14} progress={pct} color={colors.accent} trackColor="rgba(94,234,212,0.14)">
          <Text style={styles.heroValue}>{Math.round(stats.total_minutes)}</Text>
          <Text style={styles.heroUnit}>min</Text>
        </Ring>
        <View style={styles.heroMeta}>
          <Text style={styles.heroTarget}>Target {stats.target_min}–{stats.target_max} min/wk</Text>
          <Text style={styles.heroRemain}>
            {stats.total_minutes >= stats.target_min
              ? '✓ Weekly dose hit — nice.'
              : `${Math.max(0, Math.round(stats.target_min - stats.total_minutes))} min to the floor`}
          </Text>
          <Text style={styles.heroCount}>{stats.session_count} session{stats.session_count === 1 ? '' : 's'} logged</Text>
        </View>
      </View>

      {/* Steps floor + sessions */}
      <View style={styles.statRow}>
        <View style={styles.stepsCard}>
          <View style={styles.stepsHead}>
            <Ionicons name="footsteps" size={16} color={colors.fitness.carbs} />
            <Text style={styles.stepsLabel}>Steps today</Text>
          </View>
          <Text style={styles.stepsValue}>
            {stats.steps_today != null ? stats.steps_today.toLocaleString() : '—'}
            <Text style={styles.stepsFloor}> / {stats.steps_floor.toLocaleString()}</Text>
          </Text>
          <View style={styles.stepsBarTrack}>
            <View style={[styles.stepsBarFill, { width: `${stepsPct * 100}%`, backgroundColor: stepsPct >= 1 ? colors.success : colors.fitness.carbs }]} />
          </View>
        </View>
      </View>

      {/* By activity */}
      {stats.by_activity.length > 0 && (
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>By activity</Text>
          <View style={{ gap: spacing.sm, marginTop: spacing.sm }}>
            {stats.by_activity.map(a => {
              const m = activityMeta(a.activity_type);
              return (
                <View key={a.activity_type} style={styles.actRow}>
                  <Ionicons name={m.icon as any} size={16} color={m.color} style={{ width: 22 }} />
                  <Text style={styles.actLabel}>{m.label}</Text>
                  <View style={styles.actBarTrack}>
                    <View style={[styles.actBarFill, { width: `${(a.minutes / maxAct) * 100}%`, backgroundColor: m.color }]} />
                  </View>
                  <Text style={styles.actMin}>{Math.round(a.minutes)}m</Text>
                </View>
              );
            })}
          </View>
        </View>
      )}

      {/* Trend */}
      {trendVals.some(v => v > 0) && (
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>8-week trend</Text>
          <View style={{ marginTop: spacing.sm, alignItems: 'center' }}>
            <TrendChart
              data={trendVals}
              width={W - spacing.md * 2 - spacing.md * 2}
              height={120}
              color={colors.accent}
              min={0}
            />
          </View>
        </View>
      )}

      {/* Recent */}
      <View style={styles.panel}>
        <Text style={styles.panelTitle}>This week</Text>
        {logs.length === 0 ? (
          <Text style={styles.empty}>No sessions yet this week. Log one from the Log tab.</Text>
        ) : (
          <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
            {logs.map(l => {
              const m = activityMeta(l.activity_type);
              return (
                <TouchableOpacity key={l.id} style={styles.logRow} onLongPress={() => onDeleteLog(l)}>
                  <View style={[styles.logIcon, { backgroundColor: `${m.color}1A` }]}>
                    <Ionicons name={m.icon as any} size={16} color={m.color} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.logTitle}>{l.title || m.label}</Text>
                    <Text style={styles.logSub}>
                      {l.session_date}{l.zone ? ` · ${l.zone}` : ''}{l.source === 'tabata' ? ' · tabata' : ''}
                    </Text>
                  </View>
                  <Text style={styles.logMin}>{Math.round(l.duration_minutes)}m</Text>
                </TouchableOpacity>
              );
            })}
            <Text style={styles.hint}>Long-press a session to delete.</Text>
          </View>
        )}
      </View>
    </View>
  );
}

// --------------------------------------------------------------------------- //
function LogView({ settings, onPick, onCustom }: {
  settings: CardioSettings; onPick: (a: string, m: number, t: string) => void; onCustom: () => void;
}) {
  return (
    <View style={{ gap: spacing.md }}>
      <Text style={styles.sectionHint}>The density-engine menu — tap to log. Fragments count fully.</Text>
      <View style={styles.menuGrid}>
        {settings.menu.map(item => {
          const m = activityMeta(item.key);
          return (
            <TouchableOpacity key={item.key} style={styles.menuCard} onPress={() => onPick(item.key, item.worth_minutes, item.label)}>
              <View style={[styles.menuIcon, { backgroundColor: `${m.color}1A` }]}>
                <Ionicons name={m.icon as any} size={20} color={m.color} />
              </View>
              <Text style={styles.menuLabel}>{item.label}</Text>
              <Text style={styles.menuWorth}>{item.worth_minutes} min</Text>
              <Text style={styles.menuNote} numberOfLines={2}>{item.note}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <TouchableOpacity style={styles.customBtn} onPress={onCustom}>
        <Ionicons name="create-outline" size={18} color={colors.accent} />
        <Text style={styles.customBtnText}>Custom entry</Text>
      </TouchableOpacity>
    </View>
  );
}

// --------------------------------------------------------------------------- //
function TimersView({ presets, onStart, onEdit, onNew }: {
  presets: TabataPreset[]; onStart: (p: TabataPreset) => void; onEdit: (p: TabataPreset) => void; onNew: () => void;
}) {
  return (
    <View style={{ gap: spacing.md }}>
      <TouchableOpacity style={styles.newTimerBtn} onPress={onNew}>
        <Ionicons name="add" size={20} color={colors.background} />
        <Text style={styles.newTimerText}>New interval timer</Text>
      </TouchableOpacity>
      <Text style={styles.sectionHint}>Fully adjustable — set any work/rest, rounds, sets. E.g. 1-minute work intervals.</Text>
      {presets.map(p => {
        const total = Math.round(tabataTotalSeconds(p) / 60);
        const color = p.color || colors.accent;
        return (
          <TouchableOpacity key={p.id} style={[styles.timerCard, { borderLeftColor: color }]} onPress={() => onStart(p)}>
            <View style={{ flex: 1 }}>
              <Text style={styles.timerName}>{p.name}</Text>
              <Text style={styles.timerSpec}>
                {p.sets > 1 ? `${p.sets}×` : ''}{p.rounds} rounds · {p.work_seconds}s / {p.rest_seconds}s · ~{total} min
              </Text>
            </View>
            <TouchableOpacity onPress={() => onEdit(p)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }} style={styles.timerEdit}>
              <Ionicons name="create-outline" size={20} color={colors.textSecondary} />
            </TouchableOpacity>
            <View style={[styles.playPill, { backgroundColor: color }]}>
              <Ionicons name="play" size={18} color={colors.background} />
            </View>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, paddingTop: 52 },
  center: { alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.md, paddingBottom: spacing.sm,
  },
  headerTitle: { color: colors.text, fontSize: fontSizes.xl, fontWeight: '800' },
  tabsWrap: { paddingHorizontal: spacing.md, paddingBottom: spacing.sm },
  scroll: { padding: spacing.md, paddingBottom: spacing.xxl },

  hero: {
    backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg, flexDirection: 'row', alignItems: 'center', gap: spacing.lg,
  },
  heroValue: { color: colors.text, fontSize: 40, fontWeight: '800', fontVariant: ['tabular-nums'] },
  heroUnit: { color: colors.textMuted, fontSize: fontSizes.sm, marginTop: -6 },
  heroMeta: { flex: 1, gap: 4 },
  heroTarget: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  heroRemain: { color: colors.accent, fontSize: fontSizes.sm, fontWeight: '600' },
  heroCount: { color: colors.textSecondary, fontSize: fontSizes.sm },

  statRow: { flexDirection: 'row', gap: spacing.md },
  stepsCard: {
    flex: 1, backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, gap: spacing.xs,
  },
  stepsHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  stepsLabel: { color: colors.textSecondary, fontSize: fontSizes.sm },
  stepsValue: { color: colors.text, fontSize: fontSizes.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  stepsFloor: { color: colors.textMuted, fontSize: fontSizes.sm, fontWeight: '400' },
  stepsBarTrack: { height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden' },
  stepsBarFill: { height: 6, borderRadius: 3 },

  panel: {
    backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
  },
  panelTitle: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  actRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  actLabel: { color: colors.textSecondary, fontSize: fontSizes.sm, width: 74 },
  actBarTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.06)', overflow: 'hidden' },
  actBarFill: { height: 8, borderRadius: 4 },
  actMin: { color: colors.text, fontSize: fontSizes.sm, fontWeight: '600', width: 40, textAlign: 'right', fontVariant: ['tabular-nums'] },

  empty: { color: colors.textMuted, fontSize: fontSizes.sm, marginTop: spacing.sm },
  hint: { color: colors.textMuted, fontSize: fontSizes.xs, marginTop: spacing.xs, fontStyle: 'italic' },
  logRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs },
  logIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  logTitle: { color: colors.text, fontSize: fontSizes.sm, fontWeight: '600' },
  logSub: { color: colors.textMuted, fontSize: fontSizes.xs, marginTop: 1 },
  logMin: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700', fontVariant: ['tabular-nums'] },

  sectionHint: { color: colors.textSecondary, fontSize: fontSizes.sm },
  menuGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  menuCard: {
    width: (W - spacing.md * 2 - spacing.sm) / 2,
    backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, gap: 4,
  },
  menuIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', marginBottom: spacing.xs },
  menuLabel: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  menuWorth: { color: colors.accent, fontSize: fontSizes.sm, fontWeight: '600' },
  menuNote: { color: colors.textMuted, fontSize: fontSizes.xs, lineHeight: 15 },
  customBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.accent,
    backgroundColor: colors.assistant.actionSoft,
  },
  customBtnText: { color: colors.accent, fontSize: fontSizes.md, fontWeight: '700' },

  newTimerBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, borderRadius: borderRadius.full, backgroundColor: colors.accent,
  },
  newTimerText: { color: colors.background, fontSize: fontSizes.md, fontWeight: '700' },
  timerCard: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border,
    borderLeftWidth: 4, padding: spacing.md,
  },
  timerName: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  timerSpec: { color: colors.textSecondary, fontSize: fontSizes.sm, marginTop: 2 },
  timerEdit: { padding: spacing.xs },
  playPill: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
});

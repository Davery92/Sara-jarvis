import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, ScrollView, RefreshControl, ActivityIndicator, StyleSheet,
  TouchableOpacity, Modal, TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as ExpoClipboard from 'expo-clipboard';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * MACHINES — fleet health for every Linux box David owns (FLEET_DESIGN.md §7.2).
 * Mirrors the web MachinesDashboard, phone-shaped: fleet summary → host cards
 * (status, CPU/mem/disk bars, alert badges) → tap for detail (snapshot, alerts,
 * read-only diag). Pull to refresh. "Add machine" shows the enroll one-liner.
 */

type Alert = { rule: string; severity: string; detail: any; fired_at?: string };
type Headline = {
  cpu_pct?: number; mem_pct?: number; disk_max_pct?: number; load1?: number;
  cpu_count?: number; temp_max_c?: number; uptime_seconds?: number; os?: string; arch?: string;
};
type HostCard = {
  id: string; name: string; hostname: string; transport: string; has_agent: boolean;
  online: boolean; last_report_seconds_ago?: number; agent_version?: string;
  headline?: Headline | null; alerts: Alert[];
};

function timeAgo(secs?: number): string {
  if (secs == null) return 'never';
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
function uptimeStr(secs?: number): string {
  if (!secs) return '—';
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  if (d > 0) return `${d}d ${h}h`;
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
function barColor(pct?: number): string {
  if (pct == null) return colors.textMuted;
  if (pct >= 95) return colors.error;
  if (pct >= 85) return colors.warning;
  return colors.success;
}
function alertText(a: Alert): string {
  const d = a.detail || {};
  if (a.rule.startsWith('disk')) return `${d.mount || 'disk'} ${d.pct}%`;
  if (a.rule === 'mem_pressure') return `mem ${d.pct}%`;
  if (a.rule === 'load_high') return `load ${d.load1}`;
  if (a.rule === 'temp_high') return `${d.temp_c}°C`;
  if (a.rule === 'unit_failed') return `${d.count} failed unit(s)`;
  return a.rule.replace(/_/g, ' ');
}

const Bar: React.FC<{ label: string; pct?: number }> = ({ label, pct }) => (
  <View style={styles.barRow}>
    <Text style={styles.barLabel}>{label}</Text>
    <View style={styles.barTrack}>
      <View style={[styles.barFill, { width: `${Math.min(100, pct ?? 0)}%`, backgroundColor: barColor(pct) }]} />
    </View>
    <Text style={styles.barPct}>{pct == null ? '—' : `${Math.round(pct)}%`}</Text>
  </View>
);

const StatusDot: React.FC<{ host: HostCard }> = ({ host }) => {
  if (!host.has_agent) return <Text style={{ color: colors.textMuted }}>◌</Text>;
  return <Text style={{ color: host.online ? colors.success : colors.error }}>●</Text>;
};

const HostCardView: React.FC<{ host: HostCard; onPress: () => void }> = ({ host, onPress }) => {
  const h = host.headline || {};
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.7}>
      <View style={styles.cardHeader}>
        <View style={styles.rowCenter}>
          <StatusDot host={host} />
          <Text style={styles.cardName}>{host.name}</Text>
        </View>
        <Text style={styles.muted}>{timeAgo(host.last_report_seconds_ago)}</Text>
      </View>
      {!!h.os && <Text style={styles.cardOs} numberOfLines={1}>{h.os}{h.arch ? ` · ${h.arch}` : ''}</Text>}
      {host.has_agent ? (
        <View style={styles.bars}>
          <Bar label="CPU" pct={h.cpu_pct} />
          <Bar label="MEM" pct={h.mem_pct} />
          <Bar label="DISK" pct={h.disk_max_pct} />
          <View style={styles.cardFooter}>
            <Text style={styles.muted}>load {h.load1 ?? '—'}{h.cpu_count ? `/${h.cpu_count}c` : ''}</Text>
            <Text style={styles.muted}>{h.temp_max_c ? `${Math.round(h.temp_max_c)}°C` : ''}</Text>
            <Text style={styles.muted}>up {uptimeStr(h.uptime_seconds)}</Text>
          </View>
        </View>
      ) : (
        <Text style={styles.muted}>SSH-only — no fleet agent.</Text>
      )}
      {host.alerts.length > 0 && (
        <View style={styles.badgeRow}>
          {host.alerts.map((a, i) => (
            <View key={i} style={[styles.badge, a.severity === 'high' ? styles.badgeCrit : styles.badgeWarn]}>
              <Text style={[styles.badgeText, { color: a.severity === 'high' ? colors.error : colors.warning }]}>
                ⚠ {alertText(a)}
              </Text>
            </View>
          ))}
        </View>
      )}
    </TouchableOpacity>
  );
};

const COMMON = ['df -h', 'free -m', 'uptime', 'ps aux --sort -pcpu', 'systemctl --failed', 'du -sh /var/log'];

const DiagConsole: React.FC<{ hostName: string }> = ({ hostName }) => {
  const [cmd, setCmd] = useState('df -h');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const run = async () => {
    setRunning(true); setResult(null);
    try {
      const r = await apiClient.post<any>(`/api/fleet/hosts/${encodeURIComponent(hostName)}/diag`,
        { command: cmd, requested_by: 'ios' });
      setResult(r);
    } catch (e: any) {
      setResult({ status: 'error', message: e?.response?.data?.detail || String(e) });
    } finally { setRunning(false); }
  };
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Read-only diagnostics</Text>
      <View style={styles.chipRow}>
        {COMMON.map((c) => (
          <TouchableOpacity key={c} style={styles.chip} onPress={() => setCmd(c)}>
            <Text style={styles.chipText}>{c}</Text>
          </TouchableOpacity>
        ))}
      </View>
      <View style={styles.rowCenter}>
        <TextInput value={cmd} onChangeText={setCmd} style={styles.input}
          autoCapitalize="none" autoCorrect={false} placeholder="df -h" placeholderTextColor={colors.textMuted} />
        <TouchableOpacity style={styles.runBtn} onPress={run} disabled={running}>
          <Text style={styles.runBtnText}>{running ? '…' : 'Run'}</Text>
        </TouchableOpacity>
      </View>
      {result && (
        <View style={styles.output}>
          {result.status === 'done' || result.stdout ? (
            <Text style={styles.mono}>{result.stdout || '(no output)'}</Text>
          ) : (
            <Text style={[styles.mono, { color: colors.error }]}>
              {result.reason || result.denied_reason || result.message || `status: ${result.status}`}
            </Text>
          )}
        </View>
      )}
    </View>
  );
};

const DetailModal: React.FC<{ name: string; onClose: () => void }> = ({ name, onClose }) => {
  const [detail, setDetail] = useState<any>(null);
  useEffect(() => {
    apiClient.get<any>(`/api/fleet/hosts/${encodeURIComponent(name)}`).then(setDetail).catch(() => setDetail({ error: true }));
  }, [name]);
  const snap = detail?.snapshot || {};
  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.modal} edges={['top', 'bottom']}>
        <View style={styles.modalHeader}>
          <Text style={styles.modalTitle}>{name}</Text>
          <TouchableOpacity onPress={onClose}><Ionicons name="close" size={26} color={colors.textSecondary} /></TouchableOpacity>
        </View>
        <ScrollView contentContainerStyle={{ padding: spacing.md }}>
          {!detail ? <ActivityIndicator color={colors.accent} /> : (
            <>
              <Text style={styles.muted}>
                {snap.os} · {snap.arch} · report {timeAgo(detail.last_report_seconds_ago)}
                {detail.agent_version ? ` · v${detail.agent_version}` : ''}
              </Text>
              {detail.open_alerts?.length > 0 && (
                <View style={[styles.section, { borderColor: colors.warning }]}>
                  <Text style={[styles.sectionTitle, { color: colors.warning }]}>Open alerts</Text>
                  {detail.open_alerts.map((a: Alert, i: number) => (
                    <Text key={i} style={styles.bodyText}>• ⚠ {alertText(a)}</Text>
                  ))}
                </View>
              )}
              {snap.disks?.length > 0 && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Disks</Text>
                  {snap.disks.map((d: any, i: number) => (
                    <View key={i} style={{ marginBottom: spacing.xs }}>
                      <Text style={styles.bodyText}>{d.mount}</Text>
                      <Bar label="" pct={d.used_pct} />
                    </View>
                  ))}
                </View>
              )}
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Snapshot</Text>
                <Text style={styles.bodyText}>load: {snap.load1 ?? '—'} / {snap.cpu_count ?? '?'} cores</Text>
                <Text style={styles.bodyText}>memory: {snap.mem?.used_pct ?? '—'}%</Text>
                <Text style={styles.bodyText}>iface: {snap.net?.default_iface || '—'}</Text>
                <Text style={styles.bodyText}>sessions: {snap.sessions ?? '—'}</Text>
                {snap.reboot_required && <Text style={[styles.bodyText, { color: colors.warning }]}>reboot required</Text>}
                {snap.updates_pending != null && <Text style={styles.bodyText}>{snap.updates_pending} updates pending</Text>}
                {snap.gpu?.length > 0 && <Text style={styles.bodyText}>gpu: {snap.gpu[0].name} {snap.gpu[0].util_pct}%</Text>}
              </View>
              {!!(snap.top_cpu?.length) && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Top CPU</Text>
                  <Text style={styles.mono}>{snap.top_cpu.join('\n')}</Text>
                </View>
              )}
              <DiagConsole hostName={name} />
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
};

const AddMachineModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [data, setData] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    apiClient.get<any>('/api/fleet/enroll-command').then(setData).catch(() => setData({ error: true }));
  }, []);
  const copy = async () => { if (data?.command) { await ExpoClipboard.setStringAsync(data.command); setCopied(true); setTimeout(() => setCopied(false), 1500); } };
  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.modal} edges={['top', 'bottom']}>
        <View style={styles.modalHeader}>
          <Text style={styles.modalTitle}>Add a machine</Text>
          <TouchableOpacity onPress={onClose}><Ionicons name="close" size={26} color={colors.textSecondary} /></TouchableOpacity>
        </View>
        <ScrollView contentContainerStyle={{ padding: spacing.md }}>
          <Text style={styles.muted}>Run this on any Linux box (as root). It installs the agent, enrolls it, and starts reporting. The card appears here within a minute.</Text>
          {!data ? <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.md }} /> : data.error ? (
            <Text style={[styles.bodyText, { color: colors.error }]}>Couldn't load the enroll command.</Text>
          ) : (
            <>
              {!data.configured && (
                <View style={[styles.section, { borderColor: colors.warning }]}>
                  <Text style={[styles.bodyText, { color: colors.warning }]}>FLEET_ENROLL_SECRET isn't set in the backend .env yet — the command below is a template.</Text>
                </View>
              )}
              <View style={styles.output}><Text style={styles.mono}>{data.command}</Text></View>
              <TouchableOpacity style={styles.copyBtn} onPress={copy}>
                <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={16} color="#fff" />
                <Text style={styles.copyBtnText}>{copied ? 'Copied' : 'Copy command'}</Text>
              </TouchableOpacity>
              <View style={{ marginTop: spacing.md }}>
                <Text style={styles.muted}>• --name &lt;handle&gt; overrides the hostname.</Text>
                <Text style={styles.muted}>• Uninstall: … | sudo bash -s -- --uninstall</Text>
                <Text style={styles.muted}>• No passwordless sudo (Jetson)? Run inside sudo -i.</Text>
              </View>
            </>
          )}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
};

export default function MachinesScreen() {
  const [overview, setOverview] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openHost, setOpenHost] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get<any>('/api/fleet/overview');
      setOverview(r);
    } catch (e) {
      setOverview({ hosts: [], summary: { total: 0, online: 0, alerts: 0 } });
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const s = overview?.summary;
  const hosts: HostCard[] = overview?.hosts || [];

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.topBar}>
        <View>
          <Text style={styles.title}>Machines</Text>
          {s && (
            <Text style={styles.muted}>
              {s.total} machine{s.total === 1 ? '' : 's'} · {s.online} online
              {s.alerts > 0 ? ` · ${s.alerts} alert${s.alerts === 1 ? '' : 's'}` : ' · all green'}
            </Text>
          )}
        </View>
        <TouchableOpacity style={styles.addBtn} onPress={() => setShowAdd(true)}>
          <Ionicons name="add" size={18} color="#fff" />
          <Text style={styles.addBtnText}>Add</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.xl }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.md }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.accent} />}
        >
          {hosts.length === 0 ? (
            <View style={styles.empty}>
              <Text style={{ fontSize: 32 }}>🖥️</Text>
              <Text style={styles.emptyTitle}>No machines yet</Text>
              <Text style={styles.muted}>Install the fleet agent on a box to see it here.</Text>
              <TouchableOpacity style={[styles.addBtn, { marginTop: spacing.md }]} onPress={() => setShowAdd(true)}>
                <Ionicons name="add" size={18} color="#fff" />
                <Text style={styles.addBtnText}>Add machine</Text>
              </TouchableOpacity>
            </View>
          ) : (
            hosts.map((h) => <HostCardView key={h.id} host={h} onPress={() => setOpenHost(h.name)} />)
          )}
        </ScrollView>
      )}

      {openHost && <DetailModal name={openHost} onClose={() => setOpenHost(null)} />}
      {showAdd && <AddMachineModal onClose={() => setShowAdd(false)} />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  title: { color: colors.text, fontSize: fontSizes.xl, fontWeight: fontWeights.bold },
  muted: { color: colors.textMuted, fontSize: fontSizes.xs, marginTop: 2 },
  addBtn: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.primary, borderRadius: borderRadius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  addBtnText: { color: '#fff', fontSize: fontSizes.sm, fontWeight: fontWeights.semibold, marginLeft: 4 },
  card: { backgroundColor: colors.surface, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  rowCenter: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardName: { color: colors.text, fontSize: fontSizes.md, fontWeight: fontWeights.semibold },
  cardOs: { color: colors.textSecondary, fontSize: fontSizes.xs, marginTop: 2 },
  bars: { marginTop: spacing.sm, gap: 6 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  barLabel: { color: colors.textMuted, fontSize: 11, width: 34 },
  barTrack: { flex: 1, height: 6, borderRadius: 3, backgroundColor: colors.surfaceLight, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: 3 },
  barPct: { color: colors.textSecondary, fontSize: 11, width: 36, textAlign: 'right' },
  cardFooter: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: spacing.sm },
  badge: { borderRadius: borderRadius.sm, paddingHorizontal: 6, paddingVertical: 2 },
  badgeCrit: { backgroundColor: 'rgba(251,113,133,0.15)' },
  badgeWarn: { backgroundColor: 'rgba(251,191,36,0.15)' },
  badgeText: { fontSize: 10, fontWeight: fontWeights.medium },
  empty: { alignItems: 'center', paddingVertical: spacing.xxl, gap: 6 },
  emptyTitle: { color: colors.text, fontSize: fontSizes.md, fontWeight: fontWeights.semibold, marginTop: spacing.sm },
  modal: { flex: 1, backgroundColor: colors.background },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { color: colors.text, fontSize: fontSizes.lg, fontWeight: fontWeights.bold },
  section: { backgroundColor: colors.surface, borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginTop: spacing.md },
  sectionTitle: { color: colors.textSecondary, fontSize: fontSizes.xs, fontWeight: fontWeights.semibold, marginBottom: spacing.xs, textTransform: 'uppercase' },
  bodyText: { color: colors.text, fontSize: fontSizes.sm, marginBottom: 2 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: spacing.sm },
  chip: { backgroundColor: colors.surfaceLight, borderRadius: borderRadius.sm, paddingHorizontal: 8, paddingVertical: 3 },
  chipText: { color: colors.textSecondary, fontSize: 11, fontFamily: 'monospace' },
  input: { flex: 1, backgroundColor: colors.background, borderRadius: borderRadius.sm, borderWidth: 1, borderColor: colors.border, color: colors.text, paddingHorizontal: spacing.sm, paddingVertical: 6, fontFamily: 'monospace', fontSize: fontSizes.sm },
  runBtn: { backgroundColor: colors.primary, borderRadius: borderRadius.sm, paddingHorizontal: spacing.md, paddingVertical: 8, marginLeft: spacing.sm },
  runBtnText: { color: '#fff', fontWeight: fontWeights.semibold },
  output: { backgroundColor: colors.background, borderRadius: borderRadius.sm, padding: spacing.sm, marginTop: spacing.sm },
  mono: { color: colors.textSecondary, fontFamily: 'monospace', fontSize: 11 },
  copyBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: colors.primary, borderRadius: borderRadius.md, paddingVertical: spacing.sm, marginTop: spacing.sm },
  copyBtnText: { color: '#fff', fontWeight: fontWeights.semibold },
});

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  TextInput,
  Switch,
  ScrollView,
  Alert,
} from 'react-native';
import { apiClient, ScheduledJob, SchedulePatch } from '../../services/api';
import { colors, spacing, fontSizes, borderRadius } from '../../styles/theme';

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: 'Every 5 minutes', value: '*/5 * * * *' },
  { label: 'Every 15 minutes', value: '*/15 * * * *' },
  { label: 'Every 30 minutes', value: '*/30 * * * *' },
  { label: 'Hourly', value: '0 * * * *' },
  { label: 'Daily 5 AM', value: '0 5 * * *' },
  { label: 'Daily 6 AM', value: '0 6 * * *' },
  { label: 'Daily 7 AM', value: '0 7 * * *' },
  { label: 'Daily 9 AM', value: '0 9 * * *' },
  { label: 'Daily 11 PM', value: '0 23 * * *' },
  { label: 'Daily midnight', value: '0 0 * * *' },
  { label: 'Sundays 3 AM', value: '0 3 * * 0' },
];

function formatRelative(iso: string | null): string {
  if (!iso) return 'Never';
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function statusColor(status: string | null): string {
  if (status === 'success') return colors.success;
  if (status === 'error') return colors.error;
  return colors.textMuted;
}

interface EditModalProps {
  job: ScheduledJob;
  visible: boolean;
  onClose: () => void;
  onSave: (patch: SchedulePatch) => Promise<void>;
}

function EditModal({ job, visible, onClose, onSave }: EditModalProps) {
  const [kind, setKind] = useState<'cron' | 'interval'>(job.schedule_kind);
  const [cronExpr, setCronExpr] = useState(job.cron_expr ?? '');
  const [intervalSec, setIntervalSec] = useState(String(job.interval_seconds ?? 60));
  const [enabled, setEnabled] = useState(job.enabled);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setKind(job.schedule_kind);
    setCronExpr(job.cron_expr ?? '');
    setIntervalSec(String(job.interval_seconds ?? 60));
    setEnabled(job.enabled);
  }, [job]);

  const handleSave = async () => {
    setSaving(true);
    const patch: SchedulePatch = { enabled, schedule_kind: kind };
    if (kind === 'cron') {
      patch.cron_expr = cronExpr.trim();
      patch.interval_seconds = null;
    } else {
      const n = Number(intervalSec);
      if (!n || n <= 0) {
        Alert.alert('Invalid interval', 'Interval must be a positive number of seconds.');
        setSaving(false);
        return;
      }
      patch.interval_seconds = n;
      patch.cron_expr = null;
    }
    try {
      await onSave(patch);
      onClose();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message || 'Save failed';
      Alert.alert('Save failed', String(detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <ScrollView style={styles.modal} contentContainerStyle={{ padding: spacing.md }}>
        <Text style={styles.modalTitle}>{job.display_name}</Text>
        <Text style={styles.modalTaskName}>{job.task_name}</Text>
        {job.description && <Text style={styles.modalDescription}>{job.description}</Text>}

        <View style={[styles.settingRow, { marginTop: spacing.md }]}>
          <Text style={styles.settingLabel}>Enabled</Text>
          <Switch
            value={enabled}
            onValueChange={setEnabled}
            trackColor={{ false: colors.background, true: colors.primary }}
          />
        </View>

        <Text style={[styles.fieldLabel, { marginTop: spacing.md }]}>Schedule kind</Text>
        <View style={styles.kindRow}>
          <TouchableOpacity
            style={[styles.kindButton, kind === 'cron' && styles.kindButtonActive]}
            onPress={() => setKind('cron')}
          >
            <Text style={[styles.kindButtonText, kind === 'cron' && styles.kindButtonTextActive]}>Cron</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.kindButton, kind === 'interval' && styles.kindButtonActive]}
            onPress={() => setKind('interval')}
          >
            <Text style={[styles.kindButtonText, kind === 'interval' && styles.kindButtonTextActive]}>Interval</Text>
          </TouchableOpacity>
        </View>

        {kind === 'cron' ? (
          <>
            <Text style={[styles.fieldLabel, { marginTop: spacing.md }]}>
              Cron expression (5 fields)
            </Text>
            <TextInput
              value={cronExpr}
              onChangeText={setCronExpr}
              placeholder="0 6 * * *"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Text style={[styles.fieldLabel, { marginTop: spacing.sm }]}>Presets</Text>
            <View style={styles.presetGrid}>
              {CRON_PRESETS.map((p) => (
                <TouchableOpacity
                  key={p.value}
                  style={styles.presetChip}
                  onPress={() => setCronExpr(p.value)}
                >
                  <Text style={styles.presetChipText}>{p.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.hint}>Times interpreted in {job.timezone}.</Text>
          </>
        ) : (
          <>
            <Text style={[styles.fieldLabel, { marginTop: spacing.md }]}>Interval (seconds)</Text>
            <TextInput
              value={intervalSec}
              onChangeText={setIntervalSec}
              keyboardType="number-pad"
              style={styles.input}
            />
            <Text style={styles.hint}>
              {Number(intervalSec) >= 3600
                ? `≈ ${(Number(intervalSec) / 3600).toFixed(2)} hours`
                : Number(intervalSec) >= 60
                ? `≈ ${(Number(intervalSec) / 60).toFixed(1)} minutes`
                : `${intervalSec} seconds`}
            </Text>
          </>
        )}

        <View style={styles.modalButtonRow}>
          <TouchableOpacity style={[styles.modalButton, styles.modalButtonCancel]} onPress={onClose}>
            <Text style={styles.modalButtonText}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.modalButton, styles.modalButtonSave]}
            onPress={handleSave}
            disabled={saving}
          >
            <Text style={[styles.modalButtonText, styles.modalButtonTextSave]}>
              {saving ? 'Saving…' : 'Save'}
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </Modal>
  );
}

export default function SchedulesSection() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [showSystem, setShowSystem] = useState(false);
  const [editing, setEditing] = useState<ScheduledJob | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiClient.listSchedules();
      setJobs(data);
    } catch (e) {
      console.error('Failed to load schedules', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const { visible, hiddenSystem, byCategory } = useMemo(() => {
    let hidden = 0;
    const visibleJobs: ScheduledJob[] = [];
    for (const j of jobs) {
      if (j.visibility === 'system' && !showSystem) {
        hidden += 1;
        continue;
      }
      visibleJobs.push(j);
    }
    const cats = new Map<string, ScheduledJob[]>();
    for (const j of visibleJobs) {
      if (!cats.has(j.category)) cats.set(j.category, []);
      cats.get(j.category)!.push(j);
    }
    return {
      visible: visibleJobs,
      hiddenSystem: hidden,
      byCategory: Array.from(cats.entries()).sort(([a], [b]) => a.localeCompare(b)),
    };
  }, [jobs, showSystem]);

  const handleRunNow = async (job: ScheduledJob) => {
    try {
      const result = await apiClient.runScheduleNow(job.key);
      Alert.alert('Dispatched', `${job.display_name}\nTask: ${result.task_id.slice(0, 8)}…`);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message || 'Failed';
      Alert.alert('Run now failed', String(detail));
    }
  };

  const handleSave = async (patch: SchedulePatch) => {
    if (!editing) return;
    await apiClient.updateSchedule(editing.key, patch);
    await load();
  };

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Scheduled Jobs</Text>
      <Text style={styles.settingHint}>
        Edit when Sara's background tasks run. Changes take effect within ~60 seconds.
      </Text>

      {loading && jobs.length === 0 ? (
        <ActivityIndicator size="small" color={colors.primary} style={{ marginTop: spacing.md }} />
      ) : (
        <>
          {byCategory.map(([category, catJobs]) => (
            <View key={category} style={{ marginTop: spacing.md }}>
              <Text style={styles.categoryHeader}>{category.toUpperCase()}</Text>
              {catJobs.map((job) => {
                const isExpanded = expandedKey === job.key;
                return (
                  <View
                    key={job.key}
                    style={[styles.jobCard, !job.enabled && styles.jobCardDisabled]}
                  >
                    <TouchableOpacity
                      style={styles.jobHeader}
                      onPress={() => setExpandedKey(isExpanded ? null : job.key)}
                    >
                      <View style={styles.jobHeaderLeft}>
                        <View style={styles.jobTitleRow}>
                          <View
                            style={[
                              styles.statusDot,
                              { backgroundColor: statusColor(job.last_status) },
                            ]}
                          />
                          <Text style={styles.jobName} numberOfLines={1}>
                            {job.display_name}
                          </Text>
                          {job.visibility === 'system' && (
                            <Text style={styles.systemBadge}>SYSTEM</Text>
                          )}
                          {!job.enabled && <Text style={styles.disabledBadge}>OFF</Text>}
                        </View>
                        <Text style={styles.jobMeta} numberOfLines={1}>
                          {job.human_readable} · last {formatRelative(job.last_run_at)}
                        </Text>
                      </View>
                    </TouchableOpacity>

                    {isExpanded && (
                      <View style={styles.jobBody}>
                        {job.description && <Text style={styles.jobDescription}>{job.description}</Text>}
                        <Text style={styles.jobTaskName}>
                          {job.task_name}
                          {job.queue ? ` · queue: ${job.queue}` : ''}
                        </Text>
                        {job.last_error && (
                          <Text style={styles.jobError}>err: {job.last_error}</Text>
                        )}
                        <View style={styles.jobActions}>
                          <TouchableOpacity
                            style={[styles.actionButton, styles.actionButtonRun]}
                            onPress={() => handleRunNow(job)}
                          >
                            <Text style={[styles.actionButtonText, { color: colors.primary }]}>Run now</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[styles.actionButton, styles.actionButtonEdit]}
                            onPress={() => setEditing(job)}
                            disabled={!job.editable}
                          >
                            <Text style={styles.actionButtonText}>Edit</Text>
                          </TouchableOpacity>
                        </View>
                      </View>
                    )}
                  </View>
                );
              })}
            </View>
          ))}

          {hiddenSystem > 0 && !showSystem && (
            <TouchableOpacity onPress={() => setShowSystem(true)} style={{ marginTop: spacing.md }}>
              <Text style={styles.toggleLink}>
                Show {hiddenSystem} internal job{hiddenSystem !== 1 ? 's' : ''} (watchers, pollers, heartbeats)
              </Text>
            </TouchableOpacity>
          )}
          {showSystem && (
            <TouchableOpacity onPress={() => setShowSystem(false)} style={{ marginTop: spacing.md }}>
              <Text style={styles.toggleLink}>Hide internal jobs</Text>
            </TouchableOpacity>
          )}
        </>
      )}

      {editing && (
        <EditModal
          job={editing}
          visible={!!editing}
          onClose={() => setEditing(null)}
          onSave={handleSave}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  settingHint: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  categoryHeader: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontWeight: '600',
    letterSpacing: 1,
    marginBottom: spacing.xs,
  },
  jobCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.xs,
  },
  jobCardDisabled: {
    opacity: 0.5,
  },
  jobHeader: {
    padding: spacing.sm,
  },
  jobHeaderLeft: {
    flex: 1,
  },
  jobTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  jobName: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '500',
    flexShrink: 1,
  },
  systemBadge: {
    fontSize: 9,
    color: colors.textMuted,
    backgroundColor: colors.surfaceLight,
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: 3,
    fontWeight: '700',
  },
  disabledBadge: {
    fontSize: 9,
    color: colors.warning,
    backgroundColor: colors.surfaceLight,
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: 3,
    fontWeight: '700',
  },
  jobMeta: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  jobBody: {
    padding: spacing.sm,
    paddingTop: 0,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  jobDescription: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  jobTaskName: {
    fontSize: 10,
    color: colors.textMuted,
    fontFamily: 'Menlo',
    marginTop: spacing.xs,
  },
  jobError: {
    fontSize: fontSizes.xs,
    color: colors.error,
    marginTop: spacing.xs,
  },
  jobActions: {
    flexDirection: 'row',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  actionButton: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  actionButtonRun: {
    borderColor: colors.primary,
  },
  actionButtonEdit: {
    backgroundColor: colors.surfaceLight,
  },
  actionButtonText: {
    fontSize: fontSizes.xs,
    color: colors.text,
    fontWeight: '500',
  },
  toggleLink: {
    fontSize: fontSizes.xs,
    color: colors.primary,
    textAlign: 'center',
  },
  // ── Modal styles ─────
  modal: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
  },
  modalTaskName: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontFamily: 'Menlo',
    marginTop: 2,
  },
  modalDescription: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  settingLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  fieldLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  kindRow: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  kindButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  kindButtonActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  kindButtonText: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  kindButtonTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    color: colors.text,
    fontSize: fontSizes.sm,
    fontFamily: 'Menlo',
  },
  presetGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  presetChip: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  presetChipText: {
    fontSize: fontSizes.xs,
    color: colors.text,
  },
  hint: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  modalButtonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  modalButton: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    alignItems: 'center',
  },
  modalButtonCancel: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modalButtonSave: {
    backgroundColor: colors.primary,
  },
  modalButtonText: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '500',
  },
  modalButtonTextSave: {
    color: '#fff',
    fontWeight: '600',
  },
});

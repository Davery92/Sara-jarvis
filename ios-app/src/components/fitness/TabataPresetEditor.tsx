import React, { useEffect, useState } from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import {
  cardioService, TabataPreset, tabataTotalSeconds,
} from '../../services/cardio';

interface Props {
  visible: boolean;
  preset: TabataPreset | null;   // null = create new
  onClose: () => void;
  onSaved: (p: TabataPreset) => void;
  onDeleted: (id: string) => void;
  onStart: (configLike: TabataPreset) => void;
}

const COLORS = ['#ef4444', '#f59e0b', '#06b6d4', '#8b5cf6', '#34d399', '#38bdf8', '#fb7185'];
const ACTIVITIES: { key: string; label: string }[] = [
  { key: 'tabata', label: 'Tabata' },
  { key: 'kb_swings', label: 'KB swings' },
  { key: 'run', label: 'Run/row/bike' },
  { key: 'other', label: 'Other' },
];

function fmtMMSS(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// A labeled +/- stepper with quick chips. Value is in seconds (or a plain count).
function Stepper({
  label, value, onChange, min, max, step, quick, unit,
}: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; quick?: number[]; unit?: string;
}) {
  const set = (v: number) => onChange(Math.max(min, Math.min(max, v)));
  return (
    <View style={styles.stepperWrap}>
      <View style={styles.stepperHead}>
        <Text style={styles.stepperLabel}>{label}</Text>
        <Text style={styles.stepperValue}>
          {unit === 'sec' && value >= 60 ? fmtMMSS(value) : value}{unit ? <Text style={styles.stepperUnit}> {unit}</Text> : null}
        </Text>
      </View>
      <View style={styles.stepperRow}>
        <TouchableOpacity style={styles.stepBtn} onPress={() => set(value - step)}>
          <Ionicons name="remove" size={22} color={colors.text} />
        </TouchableOpacity>
        <View style={styles.chipRow}>
          {(quick ?? []).map(q => (
            <TouchableOpacity
              key={q}
              style={[styles.chip, value === q && styles.chipActive]}
              onPress={() => set(q)}
            >
              <Text style={[styles.chipText, value === q && styles.chipTextActive]}>
                {unit === 'sec' && q >= 60 ? fmtMMSS(q) : q}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        <TouchableOpacity style={styles.stepBtn} onPress={() => set(value + step)}>
          <Ionicons name="add" size={22} color={colors.text} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function TabataPresetEditor({
  visible, preset, onClose, onSaved, onDeleted, onStart,
}: Props) {
  const [name, setName] = useState('Custom timer');
  const [activity, setActivity] = useState('tabata');
  const [color, setColor] = useState(COLORS[0]);
  const [prepare, setPrepare] = useState(10);
  const [work, setWork] = useState(20);
  const [rest, setRest] = useState(10);
  const [rounds, setRounds] = useState(8);
  const [sets, setSets] = useState(1);
  const [restSet, setRestSet] = useState(60);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!visible) return;
    if (preset) {
      setName(preset.name);
      setActivity(preset.activity_type || 'tabata');
      setColor(preset.color || COLORS[0]);
      setPrepare(preset.prepare_seconds);
      setWork(preset.work_seconds);
      setRest(preset.rest_seconds);
      setRounds(preset.rounds);
      setSets(preset.sets);
      setRestSet(preset.rest_between_sets_seconds);
    } else {
      setName('Custom timer'); setActivity('tabata'); setColor(COLORS[0]);
      setPrepare(10); setWork(20); setRest(10); setRounds(8); setSets(1); setRestSet(60);
    }
  }, [visible, preset]);

  const asConfig = (): TabataPreset => ({
    id: preset?.id || 'draft',
    name: name.trim() || 'Custom timer',
    activity_type: activity,
    color,
    prepare_seconds: prepare,
    work_seconds: work,
    rest_seconds: rest,
    rounds,
    sets,
    rest_between_sets_seconds: restSet,
    is_built_in: preset?.is_built_in || false,
    sort_order: preset?.sort_order || 0,
  });

  const totalMin = Math.round((tabataTotalSeconds(asConfig()) / 60) * 10) / 10;

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        name: name.trim() || 'Custom timer',
        activity_type: activity,
        color,
        prepare_seconds: prepare,
        work_seconds: work,
        rest_seconds: rest,
        rounds,
        sets,
        rest_between_sets_seconds: restSet,
      };
      const saved = preset && preset.id !== 'draft'
        ? await cardioService.updatePreset(preset.id, body)
        : await cardioService.createPreset(body);
      onSaved(saved);
      onClose();
    } catch {
      Alert.alert('Save failed', 'Could not save this timer. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const remove = () => {
    if (!preset || preset.id === 'draft') return;
    Alert.alert('Delete timer?', `"${preset.name}" will be removed.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => {
          try { await cardioService.deletePreset(preset.id); onDeleted(preset.id); onClose(); }
          catch { Alert.alert('Delete failed', 'Try again.'); }
        },
      },
    ]);
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose}><Text style={styles.headerCancel}>Cancel</Text></TouchableOpacity>
          <Text style={styles.headerTitle}>{preset && preset.id !== 'draft' ? 'Edit timer' : 'New timer'}</Text>
          <TouchableOpacity onPress={save} disabled={saving}>
            <Text style={[styles.headerSave, saving && { opacity: 0.5 }]}>Save</Text>
          </TouchableOpacity>
        </View>

        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          {/* Name */}
          <Text style={styles.fieldLabel}>Name</Text>
          <TextInput
            style={styles.nameInput}
            value={name}
            onChangeText={setName}
            placeholder="Custom timer"
            placeholderTextColor={colors.textMuted}
          />

          {/* Activity */}
          <Text style={styles.fieldLabel}>Logs as</Text>
          <View style={styles.rowWrap}>
            {ACTIVITIES.map(a => (
              <TouchableOpacity
                key={a.key}
                style={[styles.pill, activity === a.key && styles.pillActive]}
                onPress={() => setActivity(a.key)}
              >
                <Text style={[styles.pillText, activity === a.key && styles.pillTextActive]}>{a.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Color */}
          <Text style={styles.fieldLabel}>Color</Text>
          <View style={styles.rowWrap}>
            {COLORS.map(c => (
              <TouchableOpacity key={c} onPress={() => setColor(c)}
                style={[styles.swatch, { backgroundColor: c }, color === c && styles.swatchActive]} />
            ))}
          </View>

          {/* Intervals — adjust freely */}
          <View style={styles.divider} />
          <Stepper label="Prepare" value={prepare} onChange={setPrepare} min={0} max={60} step={5}
            quick={[0, 5, 10, 15]} unit="sec" />
          <Stepper label="Work" value={work} onChange={setWork} min={5} max={600} step={5}
            quick={[20, 30, 45, 60]} unit="sec" />
          <Stepper label="Rest" value={rest} onChange={setRest} min={0} max={600} step={5}
            quick={[10, 15, 30, 60]} unit="sec" />
          <Stepper label="Rounds" value={rounds} onChange={setRounds} min={1} max={50} step={1}
            quick={[6, 8, 10, 12]} />
          <Stepper label="Sets" value={sets} onChange={setSets} min={1} max={20} step={1}
            quick={[1, 2, 3, 4]} />
          {sets > 1 && (
            <Stepper label="Rest between sets" value={restSet} onChange={setRestSet} min={0} max={600} step={10}
              quick={[30, 60, 90, 120]} unit="sec" />
          )}

          {/* Summary */}
          <View style={[styles.summary, { borderColor: `${color}55` }]}>
            <Text style={styles.summaryLine}>
              {sets > 1 ? `${sets} sets × ` : ''}{rounds} rounds · {work}s work / {rest}s rest
            </Text>
            <Text style={[styles.summaryTotal, { color }]}>≈ {totalMin} min total</Text>
          </View>

          <View style={styles.actionsRow}>
            <TouchableOpacity style={[styles.startBtn, { backgroundColor: color }]} onPress={() => onStart(asConfig())}>
              <Ionicons name="play" size={18} color={colors.background} />
              <Text style={styles.startBtnText}>Start now</Text>
            </TouchableOpacity>
            {preset && preset.id !== 'draft' && (
              <TouchableOpacity style={styles.deleteBtn} onPress={remove}>
                <Ionicons name="trash-outline" size={20} color={colors.error} />
              </TouchableOpacity>
            )}
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerCancel: { color: colors.textSecondary, fontSize: fontSizes.md },
  headerTitle: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  headerSave: { color: colors.accent, fontSize: fontSizes.md, fontWeight: '700' },
  body: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.sm },
  fieldLabel: {
    color: colors.accent, fontSize: fontSizes.xs, fontWeight: '700',
    textTransform: 'uppercase', letterSpacing: 0.5, marginTop: spacing.md, marginBottom: spacing.xs,
  },
  nameInput: {
    backgroundColor: colors.surface, borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md, color: colors.text, fontSize: fontSizes.md,
  },
  rowWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  pill: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.full,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  pillActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.accent },
  pillText: { color: colors.textSecondary, fontSize: fontSizes.sm },
  pillTextActive: { color: colors.accent, fontWeight: '700' },
  swatch: { width: 34, height: 34, borderRadius: 17, borderWidth: 2, borderColor: 'transparent' },
  swatchActive: { borderColor: colors.text },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.md },
  stepperWrap: { marginBottom: spacing.md },
  stepperHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: spacing.xs },
  stepperLabel: { color: colors.text, fontSize: fontSizes.md, fontWeight: '600' },
  stepperValue: { color: colors.text, fontSize: fontSizes.lg, fontWeight: '700', fontVariant: ['tabular-nums'] },
  stepperUnit: { color: colors.textMuted, fontSize: fontSizes.sm, fontWeight: '400' },
  stepperRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  stepBtn: {
    width: 44, height: 44, borderRadius: borderRadius.md, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center',
  },
  chipRow: { flex: 1, flexDirection: 'row', justifyContent: 'center', gap: spacing.xs, flexWrap: 'wrap' },
  chip: {
    paddingHorizontal: spacing.sm, paddingVertical: 6, borderRadius: borderRadius.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, minWidth: 40, alignItems: 'center',
  },
  chipActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.accent },
  chipText: { color: colors.textSecondary, fontSize: fontSizes.sm, fontVariant: ['tabular-nums'] },
  chipTextActive: { color: colors.accent, fontWeight: '700' },
  summary: {
    backgroundColor: colors.surface, borderRadius: borderRadius.md, borderWidth: 1,
    padding: spacing.md, marginTop: spacing.md, alignItems: 'center', gap: 4,
  },
  summaryLine: { color: colors.textSecondary, fontSize: fontSizes.sm },
  summaryTotal: { fontSize: fontSizes.lg, fontWeight: '800' },
  actionsRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md, alignItems: 'center' },
  startBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, borderRadius: borderRadius.full,
  },
  startBtnText: { color: colors.background, fontSize: fontSizes.md, fontWeight: '700' },
  deleteBtn: {
    width: 50, height: 50, borderRadius: borderRadius.md, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.assistant.errorSoft, borderWidth: 1, borderColor: colors.error,
  },
});

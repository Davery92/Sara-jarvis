import React, { useEffect, useState } from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { cardioService, activityMeta } from '../../services/cardio';

interface Props {
  visible: boolean;
  onClose: () => void;
  onSaved: () => void;
  initial?: { activity_type?: string; duration_minutes?: number; title?: string } | null;
}

const ACTIVITY_KEYS = ['walk', 'ruck', 'kb_swings', 'coaching', 'commute', 'run', 'row', 'bike', 'other'];
const ZONES = [
  { key: 'zone2', label: 'Zone 2' },
  { key: 'mixed', label: 'Mixed' },
  { key: 'hard', label: 'Hard' },
];

export default function CardioLogModal({ visible, onClose, onSaved, initial }: Props) {
  const [activity, setActivity] = useState('walk');
  const [duration, setDuration] = useState(30);
  const [distance, setDistance] = useState('');
  const [avgHr, setAvgHr] = useState('');
  const [zone, setZone] = useState<string | null>(null);
  const [rpe, setRpe] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setActivity(initial?.activity_type || 'walk');
    setDuration(initial?.duration_minutes ?? 30);
    setDistance(''); setAvgHr(''); setZone(null); setRpe(null); setNotes('');
  }, [visible, initial]);

  const save = async () => {
    if (duration <= 0) { Alert.alert('Duration needed', 'Set a duration greater than 0.'); return; }
    setSaving(true);
    try {
      await cardioService.createLog({
        activity_type: activity,
        title: initial?.title || '',
        duration_minutes: duration,
        distance_miles: distance ? parseFloat(distance) : null,
        avg_hr: avgHr ? parseInt(avgHr, 10) : null,
        zone,
        rpe,
        notes,
        source: 'manual',
      });
      onSaved();
      onClose();
    } catch {
      Alert.alert('Save failed', 'Could not log this session. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose}><Text style={styles.cancel}>Cancel</Text></TouchableOpacity>
          <Text style={styles.title}>Log cardio</Text>
          <TouchableOpacity onPress={save} disabled={saving}>
            <Text style={[styles.save, saving && { opacity: 0.5 }]}>Save</Text>
          </TouchableOpacity>
        </View>

        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Activity</Text>
          <View style={styles.wrap}>
            {ACTIVITY_KEYS.map(k => {
              const m = activityMeta(k);
              const on = activity === k;
              return (
                <TouchableOpacity key={k} style={[styles.actChip, on && { borderColor: m.color, backgroundColor: `${m.color}1A` }]}
                  onPress={() => setActivity(k)}>
                  <Ionicons name={m.icon as any} size={15} color={on ? m.color : colors.textSecondary} />
                  <Text style={[styles.actChipText, on && { color: m.color, fontWeight: '700' }]}>{m.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={styles.label}>Duration</Text>
          <View style={styles.durationRow}>
            <TouchableOpacity style={styles.stepBtn} onPress={() => setDuration(d => Math.max(1, d - 5))}>
              <Ionicons name="remove" size={22} color={colors.text} />
            </TouchableOpacity>
            <View style={styles.durationVal}>
              <Text style={styles.durationNum}>{duration}</Text>
              <Text style={styles.durationUnit}>min</Text>
            </View>
            <TouchableOpacity style={styles.stepBtn} onPress={() => setDuration(d => d + 5)}>
              <Ionicons name="add" size={22} color={colors.text} />
            </TouchableOpacity>
          </View>
          <View style={styles.wrap}>
            {[10, 15, 20, 30, 45, 60].map(q => (
              <TouchableOpacity key={q} style={[styles.qChip, duration === q && styles.qChipActive]} onPress={() => setDuration(q)}>
                <Text style={[styles.qChipText, duration === q && styles.qChipTextActive]}>{q}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={styles.twoCol}>
            <View style={styles.col}>
              <Text style={styles.label}>Distance (mi)</Text>
              <TextInput style={styles.input} value={distance} onChangeText={setDistance}
                keyboardType="decimal-pad" placeholder="—" placeholderTextColor={colors.textMuted} />
            </View>
            <View style={styles.col}>
              <Text style={styles.label}>Avg HR</Text>
              <TextInput style={styles.input} value={avgHr} onChangeText={setAvgHr}
                keyboardType="number-pad" placeholder="—" placeholderTextColor={colors.textMuted} />
            </View>
          </View>

          <Text style={styles.label}>Zone</Text>
          <View style={styles.wrap}>
            {ZONES.map(z => (
              <TouchableOpacity key={z.key} style={[styles.pill, zone === z.key && styles.pillActive]}
                onPress={() => setZone(zone === z.key ? null : z.key)}>
                <Text style={[styles.pillText, zone === z.key && styles.pillTextActive]}>{z.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.label}>Effort (RPE)</Text>
          <View style={styles.wrap}>
            {[3, 4, 5, 6, 7, 8, 9].map(n => (
              <TouchableOpacity key={n} style={[styles.rpeChip, rpe === n && styles.rpeChipActive]}
                onPress={() => setRpe(rpe === n ? null : n)}>
                <Text style={[styles.rpeText, rpe === n && styles.rpeTextActive]}>{n}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.label}>Notes</Text>
          <TextInput style={[styles.input, styles.notes]} value={notes} onChangeText={setNotes}
            placeholder="Optional" placeholderTextColor={colors.textMuted} multiline />
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
  cancel: { color: colors.textSecondary, fontSize: fontSizes.md },
  title: { color: colors.text, fontSize: fontSizes.md, fontWeight: '700' },
  save: { color: colors.accent, fontSize: fontSizes.md, fontWeight: '700' },
  body: { padding: spacing.md, paddingBottom: spacing.xxl },
  label: {
    color: colors.accent, fontSize: fontSizes.xs, fontWeight: '700', textTransform: 'uppercase',
    letterSpacing: 0.5, marginTop: spacing.md, marginBottom: spacing.xs,
  },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  actChip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  actChipText: { color: colors.textSecondary, fontSize: fontSizes.sm },
  durationRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xl },
  stepBtn: {
    width: 48, height: 48, borderRadius: borderRadius.md, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center',
  },
  durationVal: { alignItems: 'center', minWidth: 80 },
  durationNum: { color: colors.text, fontSize: 40, fontWeight: '800', fontVariant: ['tabular-nums'] },
  durationUnit: { color: colors.textMuted, fontSize: fontSizes.sm, marginTop: -4 },
  qChip: {
    paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: borderRadius.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  qChipActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.accent },
  qChipText: { color: colors.textSecondary, fontSize: fontSizes.sm, fontVariant: ['tabular-nums'] },
  qChipTextActive: { color: colors.accent, fontWeight: '700' },
  twoCol: { flexDirection: 'row', gap: spacing.md },
  col: { flex: 1 },
  input: {
    backgroundColor: colors.surface, borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, color: colors.text, fontSize: fontSizes.md,
  },
  notes: { minHeight: 70, textAlignVertical: 'top' },
  pill: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.full,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  pillActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.accent },
  pillText: { color: colors.textSecondary, fontSize: fontSizes.sm },
  pillTextActive: { color: colors.accent, fontWeight: '700' },
  rpeChip: {
    width: 40, height: 40, borderRadius: borderRadius.md, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  rpeChipActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.accent },
  rpeText: { color: colors.textSecondary, fontSize: fontSizes.md, fontWeight: '600' },
  rpeTextActive: { color: colors.accent },
});

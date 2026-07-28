import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  ScrollView,
  TextInput,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import type { PerformedSet } from '../../services/workoutContracts';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * The flexible-set controls, sitting next to Log Set (plan §7.1).
 *
 * The design constraint is that the normal path must not get slower. Logging a
 * straight working set is still one tap on LOG SET; everything here lives
 * behind a compact row that is reachable but subordinate.
 *
 * Three rules this component exists to keep visible:
 *
 *  - Adding a set changes THIS workout. The header says "4 sets (3 prescribed)"
 *    rather than quietly rewriting the plan.
 *  - A drop-set series belongs to one working set. Segments add volume and
 *    reps; they do not each consume a prescribed slot.
 *  - Undo is not delete. The set stops counting toward progress, volume, PRs
 *    and progression, and stays visible as struck-through history.
 */

type Mode = 'closed' | 'drop' | 'history';

export default function WorkoutSetActions() {
  const {
    session,
    currentExercise,
    performedSets,
    addWorkingSet,
    removeUnloggedSet,
    logDropSegment,
    reviseSet,
    voidSet,
  } = useWorkoutMode();

  const [mode, setMode] = useState<Mode>('closed');
  const [busy, setBusy] = useState(false);

  const exerciseIndex = session?.current_exercise_index ?? 0;
  const exerciseName = currentExercise?.variant || currentExercise?.name || '';

  // The set list is scoped to the exercise on screen. A whole-workout history
  // would be a different screen; this one answers "what have I done here".
  const setsForExercise = useMemo(
    () => performedSets.filter((s) => s.exercise === exerciseName),
    [performedSets, exerciseName]
  );

  // Drop Set and Undo deliberately look at the whole session, not the exercise
  // on screen. Finishing an exercise advances the cursor, and both of these
  // still mean "the set I just did" — scoping them to the current exercise
  // would grey them out at exactly the moment they are wanted.
  const lastWorkingSet = useMemo(
    () => [...performedSets].reverse().find((s) => !s.voided && s.counts_toward_target),
    [performedSets]
  );
  const lastLiveSet = useMemo(
    () => [...performedSets].reverse().find((s) => !s.voided),
    [performedSets]
  );

  const prescribed = (currentExercise as any)?.prescribed_sets ?? currentExercise?.sets ?? 0;
  const effective = currentExercise?.sets ?? 0;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const confirmUndo = (set: PerformedSet) => {
    const dropNote = set.counts_toward_target
      ? '\n\nAny drop segments under it are undone too.'
      : '';
    Alert.alert(
      'Undo this set?',
      `${set.weight ?? 0} lbs × ${set.reps ?? 0} stops counting toward progress, ` +
        `volume, PRs and progression. It stays in your history, struck through.${dropNote}`,
      [
        { text: 'Keep it', style: 'cancel' },
        { text: 'Undo', style: 'destructive', onPress: () => run(() => voidSet(set.id)) },
      ]
    );
  };

  if (!currentExercise) return null;

  return (
    <>
      <View style={styles.row}>
        <Action
          icon="add-circle-outline"
          label="Add Set"
          disabled={busy}
          onPress={() => run(() => addWorkingSet(exerciseIndex))}
        />
        <Action
          icon="trending-down-outline"
          label="Drop Set"
          disabled={busy || !lastWorkingSet}
          onPress={() => setMode('drop')}
        />
        <Action
          icon="list-outline"
          label={`Sets (${setsForExercise.filter((s) => !s.voided).length})`}
          disabled={busy}
          onPress={() => setMode('history')}
        />
        <Action
          icon="arrow-undo-outline"
          label="Undo"
          disabled={busy || !lastLiveSet}
          onPress={() => lastLiveSet && confirmUndo(lastLiveSet)}
        />
      </View>

      {/* Honesty line: the number on the left is what this workout asks for,
          the number in brackets is what the program prescribed. They differ
          only because David changed it, and only for today. */}
      {effective !== prescribed && prescribed > 0 && (
        <View style={styles.deltaBanner}>
          <Ionicons name="information-circle-outline" size={14} color={colors.accent} />
          <Text style={styles.deltaText}>
            {effective} sets today ({prescribed} prescribed) — this workout only.
          </Text>
          {effective > prescribed && (
            <TouchableOpacity
              onPress={() => run(() => removeUnloggedSet(exerciseIndex))}
              disabled={busy}
              hitSlop={8}
            >
              <Text style={styles.deltaUndo}>Undo</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      <DropSetSheet
        visible={mode === 'drop'}
        onClose={() => setMode('closed')}
        parent={lastWorkingSet ?? null}
        // Named after the set it attaches to, which is not always the exercise
        // on screen once the cursor has moved on.
        exerciseName={lastWorkingSet?.exercise ?? exerciseName}
        onLog={(weight, reps) =>
          logDropSegment({ weight, reps, parentSetId: lastWorkingSet?.id })
        }
      />

      <SetHistorySheet
        visible={mode === 'history'}
        onClose={() => setMode('closed')}
        sets={setsForExercise}
        exerciseName={exerciseName}
        onRevise={reviseSet}
        onUndo={confirmUndo}
      />
    </>
  );
}

function Action({
  icon, label, onPress, disabled,
}: { icon: any; label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <TouchableOpacity
      style={[styles.action, disabled && styles.actionDisabled]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.7}
    >
      <Ionicons name={icon} size={17} color={disabled ? colors.textMuted : colors.text} />
      <Text style={[styles.actionLabel, disabled && { color: colors.textMuted }]} numberOfLines={1}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

/**
 * Drop-set entry (§7.1).
 *
 * Seeded at ~70% of the parent set as a *convenience*, clearly labelled as a
 * starting point. It is not a Sara-approved plan — pre-filling her preference
 * and calling the tap consent is the boundary the whole plan is about.
 *
 * Rest is deliberately not started between segments: a drop set is one
 * continuous effort, so the sheet stays open and offers "Add Another Drop".
 */
function DropSetSheet({
  visible, onClose, parent, exerciseName, onLog,
}: {
  visible: boolean;
  onClose: () => void;
  parent: PerformedSet | null;
  exerciseName: string;
  onLog: (weight: number, reps: number) => Promise<void>;
}) {
  const [weight, setWeight] = useState('');
  const [reps, setReps] = useState('');
  const [segments, setSegments] = useState<Array<{ weight: number; reps: number }>>([]);
  const [busy, setBusy] = useState(false);

  // Seed from the last thing performed: the parent set on the first segment,
  // then each successive drop from the one before it.
  React.useEffect(() => {
    if (!visible) {
      setSegments([]);
      return;
    }
    const from = segments.length ? segments[segments.length - 1].weight : parent?.weight ?? 0;
    setWeight(String(Math.max(0, Math.round((from * 0.7) / 5) * 5)));
    setReps(String(parent?.reps ?? 8));
  }, [visible, segments.length, parent?.weight, parent?.reps]);

  const submit = async (andAnother: boolean) => {
    const w = parseFloat(weight);
    const r = parseInt(reps, 10);
    if (!Number.isFinite(w) || !Number.isFinite(r) || r <= 0) {
      Alert.alert('Enter a weight and reps', 'Both are needed to log the segment.');
      return;
    }
    setBusy(true);
    try {
      await onLog(w, r);
      setSegments((prev) => [...prev, { weight: w, reps: r }]);
      if (!andAnother) onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Drop set · {exerciseName}</Text>
            <TouchableOpacity onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>

          <Text style={styles.sheetHint}>
            {parent
              ? `Off your ${parent.weight ?? 0} × ${parent.reps ?? 0} set. Segments add volume and reps — they don't use up another prescribed set.`
              : 'Log the working set first.'}
          </Text>

          {segments.map((s, i) => (
            <View key={i} style={styles.segmentRow}>
              <Text style={styles.segmentLabel}>Drop {i + 1}</Text>
              <Text style={styles.segmentValue}>{s.weight} lbs × {s.reps}</Text>
            </View>
          ))}

          <View style={styles.fieldRow}>
            <Field label="WEIGHT" value={weight} onChangeText={setWeight} unit="lbs" />
            <Field label="REPS" value={reps} onChangeText={setReps} />
          </View>

          <TouchableOpacity
            style={[styles.primaryButton, busy && styles.actionDisabled]}
            onPress={() => submit(true)}
            disabled={busy}
          >
            <Text style={styles.primaryButtonText}>
              {segments.length ? 'LOG & ADD ANOTHER DROP' : 'LOG DROP'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.secondaryButton}
            onPress={() => (segments.length ? onClose() : submit(false))}
            disabled={busy}
          >
            <Text style={styles.secondaryButtonText}>
              {segments.length ? 'Done' : 'Log & finish'}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

/**
 * View / edit performed sets (§7.1).
 *
 * Drop segments are indented under their working set, so a three-segment drop
 * reads as one set with three parts rather than four separate sets. Voided
 * rows stay visible and struck through — "this didn't happen" is information,
 * and hiding it makes a corrected PR inexplicable later.
 */
function SetHistorySheet({
  visible, onClose, sets, exerciseName, onRevise, onUndo,
}: {
  visible: boolean;
  onClose: () => void;
  sets: PerformedSet[];
  exerciseName: string;
  onRevise: (setId: string, changes: { weight?: number; reps?: number }) => Promise<void>;
  onUndo: (set: PerformedSet) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [weight, setWeight] = useState('');
  const [reps, setReps] = useState('');

  const beginEdit = (set: PerformedSet) => {
    setEditing(set.id);
    setWeight(String(set.weight ?? ''));
    setReps(String(set.reps ?? ''));
  };

  const commit = async (set: PerformedSet) => {
    const w = parseFloat(weight);
    const r = parseInt(reps, 10);
    setEditing(null);
    await onRevise(set.id, {
      weight: Number.isFinite(w) ? w : undefined,
      reps: Number.isFinite(r) ? r : undefined,
    });
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={[styles.sheet, { maxHeight: '80%' }]}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Sets · {exerciseName}</Text>
            <TouchableOpacity onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>

          <ScrollView>
            {sets.length === 0 && (
              <Text style={styles.sheetHint}>Nothing logged for this exercise yet.</Text>
            )}
            {sets.map((set) => {
              const isDrop = set.set_kind === 'drop';
              const isWarmup = set.set_kind === 'warmup';
              return (
                <View
                  key={set.id}
                  style={[styles.setRow, isDrop && styles.setRowDrop, set.voided && styles.setRowVoided]}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.setLabel, set.voided && styles.struck]}>
                      {isDrop ? `Drop ${set.group_sequence}` : isWarmup ? 'Warm-up' : `Set ${set.set_index}`}
                      {set.is_pr && !set.voided ? '  🏆' : ''}
                    </Text>
                    {editing === set.id ? (
                      <View style={styles.editRow}>
                        <TextInput
                          style={styles.editInput}
                          value={weight}
                          onChangeText={setWeight}
                          keyboardType="numeric"
                          selectTextOnFocus
                        />
                        <Text style={styles.editTimes}>×</Text>
                        <TextInput
                          style={styles.editInput}
                          value={reps}
                          onChangeText={setReps}
                          keyboardType="numeric"
                          selectTextOnFocus
                        />
                        <TouchableOpacity onPress={() => commit(set)} hitSlop={8}>
                          <Ionicons name="checkmark" size={20} color={colors.success} />
                        </TouchableOpacity>
                      </View>
                    ) : (
                      <Text style={[styles.setValue, set.voided && styles.struck]}>
                        {set.weight ?? 0} lbs × {set.reps ?? 0}
                        {set.rpe ? `  ·  RPE ${set.rpe}` : ''}
                        {!set.counts_toward_target && !set.voided ? '  ·  volume only' : ''}
                      </Text>
                    )}
                  </View>

                  {!set.voided && (
                    <View style={styles.setRowActions}>
                      <TouchableOpacity onPress={() => beginEdit(set)} hitSlop={8}>
                        <Ionicons name="create-outline" size={18} color={colors.textSecondary} />
                      </TouchableOpacity>
                      <TouchableOpacity onPress={() => onUndo(set)} hitSlop={8}>
                        <Ionicons name="arrow-undo-outline" size={18} color={colors.error} />
                      </TouchableOpacity>
                    </View>
                  )}
                </View>
              );
            })}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function Field({
  label, value, onChangeText, unit,
}: { label: string; value: string; onChangeText: (t: string) => void; unit?: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.fieldValueRow}>
        <TextInput
          style={styles.fieldInput}
          value={value}
          onChangeText={onChangeText}
          keyboardType="numeric"
          selectTextOnFocus
          returnKeyType="done"
        />
        {unit ? <Text style={styles.fieldUnit}>{unit}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  action: {
    flex: 1,
    alignItems: 'center',
    gap: 3,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  actionDisabled: {
    opacity: 0.45,
  },
  actionLabel: {
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: fontWeights.medium,
  },

  deltaBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.xs + 2,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
  },
  deltaText: {
    flex: 1,
    color: colors.accent,
    fontSize: fontSizes.xs,
  },
  deltaUndo: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.bold,
  },

  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.55)',
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    padding: spacing.md,
    gap: spacing.sm,
  },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sheetTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    flex: 1,
  },
  sheetHint: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    lineHeight: 17,
  },

  segmentRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.md,
  },
  segmentLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  segmentValue: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
  },

  fieldRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  field: {
    flex: 1,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.sm,
  },
  fieldLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
  },
  fieldValueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
  },
  fieldInput: {
    flex: 1,
    color: colors.text,
    fontSize: 28,
    fontWeight: fontWeights.bold,
    padding: 0,
  },
  fieldUnit: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },

  primaryButton: {
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.primary,
  },
  primaryButtonText: {
    color: colors.background,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.bold,
    letterSpacing: 0.5,
  },
  secondaryButton: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  secondaryButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },

  setRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  setRowDrop: {
    paddingLeft: spacing.lg,
    backgroundColor: colors.surfaceLight,
  },
  setRowVoided: {
    opacity: 0.5,
  },
  setLabel: {
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  setValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
    marginTop: 2,
  },
  struck: {
    textDecorationLine: 'line-through',
  },
  setRowActions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  editRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: 2,
  },
  editInput: {
    minWidth: 56,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    padding: 0,
  },
  editTimes: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
});

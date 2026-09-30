import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Animated,
  Vibration,
  TextInput,
  Keyboard,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
import ExercisePickerModal from './ExercisePickerModal';
import WorkoutSetActions from './WorkoutSetActions';

interface WorkoutPanelProps {
  onCollapse?: () => void;
  isCollapsed?: boolean;
  onFinish?: () => void;   // screen supplies this to show the summary; falls back to completeWorkout
}

type Feeling = 'light' | 'moderate' | 'hard';

// RPE feedback chips — selected before logging a set (mockup: Too Hard / Perfect / Too Easy).
const FEELINGS: { key: Feeling; label: string; emoji: string; color: string }[] = [
  { key: 'hard', label: 'Too Hard', emoji: '😣', color: colors.error },
  { key: 'moderate', label: 'Perfect', emoji: '😊', color: colors.warning },
  { key: 'light', label: 'Too Easy', emoji: '😄', color: colors.success },
];

export default function WorkoutPanel({ onCollapse, isCollapsed = false, onFinish }: WorkoutPanelProps) {
  const {
    isActive,
    session,
    currentExercise,
    currentSetNumber,
    progress,
    restTimer,
    logSet,
    skipExercise,
    selectExercise,
    setVariant,
    setPlanWeek,
    startRestTimer,
    stopRestTimer,
    completeWorkout,
    coachingNeedsHeadphones,
  } = useWorkoutMode();

  const [lastFeedback, setLastFeedback] = useState<string | null>(null);
  const [isLogging, setIsLogging] = useState(false);
  const [timerPulse] = useState(new Animated.Value(1));
  const [customWeight, setCustomWeight] = useState<string>('');
  const [customReps, setCustomReps] = useState<string>('');
  const [feeling, setFeeling] = useState<Feeling>('moderate');
  const [variantInput, setVariantInput] = useState<string>('');
  const [showVariantPicker, setShowVariantPicker] = useState(false);
  // A4 — plan-driven AM lifts (top/backoff): which chip the next Log Set
  // tap writes as. Auto-follows next_set.kind, but a manual toggle (or
  // "skip warm-ups") can override it — logging a working set while warm-up
  // entries remain unlogged still resolves correctly server-side, since
  // warm-ups and working sets are tracked as independent cursors
  // (set_plan.next_entry).
  const [warmupSelected, setWarmupSelected] = useState(false);

  const nextSet = currentExercise?.next_set;
  const resolvedPlan = currentExercise?.set_plan_resolved;

  // Reset inputs when the exercise (or its scoped suggestion, e.g. after setting a
  // machine variant) changes — or when the plan's next prescribed entry moves.
  useEffect(() => {
    if (currentExercise) {
      if (nextSet) {
        setCustomWeight(nextSet.weight != null ? nextSet.weight.toString() : '');
        const repsLow = nextSet.reps ? nextSet.reps.replace('+', '').split('-')[0] : '';
        setCustomReps(repsLow);
        setWarmupSelected(nextSet.kind === 'warmup');
      } else {
        setCustomWeight(currentExercise.suggested_weight?.toString() || '');
        const targetReps = currentExercise.reps?.toString().split('-')[0] || '';
        setCustomReps(targetReps);
        setWarmupSelected(false);
      }
      setFeeling('moderate');
      setVariantInput(currentExercise.variant || '');
    }
  }, [
    currentExercise?.name,
    session?.current_exercise_index,
    currentExercise?.variant,
    currentExercise?.suggested_weight,
    nextSet?.index,
    nextSet?.kind,
  ]);

  // Commit the machine/variation the user typed (null reverts to the base lift).
  const commitVariant = () => {
    const trimmed = variantInput.trim();
    const current = currentExercise?.variant || '';
    if (trimmed === current) return;
    setVariant(session?.current_exercise_index ?? 0, trimmed || null);
  };

  // Picking from the variant-history list (or adding a new one) commits
  // immediately — don't rely on variantInput's state, which won't have
  // updated yet inside this same handler.
  const handlePickVariant = (name: string) => {
    setVariantInput(name);
    setVariant(session?.current_exercise_index ?? 0, name || null);
  };

  // Vibrate when rest timer ends
  useEffect(() => {
    if (restTimer?.remaining_seconds === 0 && restTimer?.is_active === false) {
      Vibration.vibrate([500, 200, 500]);
    }
  }, [restTimer?.remaining_seconds]);

  // Animate timer when low
  useEffect(() => {
    if (restTimer?.remaining_seconds && restTimer.remaining_seconds <= 10) {
      Animated.sequence([
        Animated.timing(timerPulse, { toValue: 1.1, duration: 200, useNativeDriver: true }),
        Animated.timing(timerPulse, { toValue: 1, duration: 200, useNativeDriver: true }),
      ]).start();
    }
  }, [restTimer?.remaining_seconds]);

  if (!isActive || !session) return null;

  const adjustWeight = (delta: number) => {
    const current = parseFloat(customWeight) || 0;
    setCustomWeight(Math.max(0, current + delta).toString());
  };
  const adjustReps = (delta: number) => {
    const current = parseInt(customReps, 10) || 0;
    setCustomReps(Math.max(0, current + delta).toString());
  };

  const handleLogSet = async () => {
    Keyboard.dismiss();
    setIsLogging(true);
    try {
      const weight = customWeight ? parseFloat(customWeight) : currentExercise?.suggested_weight;
      const reps = customReps ? parseInt(customReps, 10) : undefined;
      const setKind = resolvedPlan ? (warmupSelected ? 'warmup' : 'working') : undefined;
      const result = await logSet({ rpe_feeling: feeling, weight, reps, set_kind: setKind });
      if (result.coaching_feedback) {
        setLastFeedback(result.coaching_feedback);
        setTimeout(() => setLastFeedback(null), 5000);
      }
      if (result.success) {
        // A rest timer for a workout that just completed is a stray timer —
        // it fires after Sara has already closed the session, and it is
        // exactly the "phone rest_start two seconds after every completion"
        // conflict found in the 2026-09-09 audit.
        if (!result.workout_complete) {
          // Rest length is backend-driven now — scaled to the set's intensity
          // (RPE) + lift type, instead of a flat 180/90.
          startRestTimer(result.rest_seconds || 120);
        }
        if (result.pr?.is_pr) {
          const e1rm = result.pr.estimated_1rm
            ? ` Est. 1RM: ${Math.round(result.pr.estimated_1rm)} lbs.`
            : '';
          Alert.alert('🏆 New PR!', `${currentExercise?.name || 'Lift'} — new best!${e1rm}`);
        }
      } else {
        Alert.alert('Error', 'Failed to log set. Please try again.');
      }
    } catch (err: any) {
      console.error('[WorkoutPanel] Error logging set:', err);
      Alert.alert('Error', err.message || 'Failed to log set');
    } finally {
      setIsLogging(false);
    }
  };

  const handleFinish = () => {
    Alert.alert('Finish Workout?', 'End and save this workout?', [
      { text: 'Keep Going', style: 'cancel' },
      { text: 'Finish', style: 'default', onPress: () => (onFinish ? onFinish() : completeWorkout()) },
    ]);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (isCollapsed) {
    return (
      <TouchableOpacity style={styles.collapsedPanel} onPress={onCollapse}>
        <View style={styles.collapsedContent}>
          <Ionicons name="barbell" size={18} color={colors.text} />
          <Text style={styles.collapsedText}>
            {currentExercise?.name} - Set {currentSetNumber}/{currentExercise?.sets}
          </Text>
          {restTimer?.is_active && (
            <View style={styles.miniTimer}>
              <Text style={styles.miniTimerText}>{restTimer.remaining_seconds}s</Text>
            </View>
          )}
        </View>
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${progress.percentage}%` }]} />
        </View>
      </TouchableOpacity>
    );
  }

  // `sets` is the effective target for today; `prescribed_sets` is what the
  // program asked for. Saying both when they differ is what keeps an added set
  // an in-workout adjustment rather than a silent plan rewrite (§7.1).
  const prescribedSets = (currentExercise as any)?.prescribed_sets;
  const setsLabel = currentExercise
    ? (typeof prescribedSets === 'number' && prescribedSets !== currentExercise.sets
        ? `${currentExercise.sets} (${prescribedSets} prescribed)`
        : `${currentExercise.sets}`)
    : '';
  const scheme = currentExercise
    ? `${setsLabel} × ${currentExercise.reps}${currentExercise.suggested_weight ? ` @ ${currentExercise.suggested_weight} lbs` : ''}`
    : '';
  const last = currentExercise?.last_session;

  // A4 — kind-aware header for a plan-driven AM lift's next set: which warm-up
  // / top / backoff this is, and its prescribed number.
  let planKindLabel: string | null = null;
  if (nextSet && resolvedPlan) {
    if (nextSet.kind === 'warmup') {
      const total = resolvedPlan.filter(s => s.kind === 'warmup').length;
      planKindLabel = `WARM-UP ${(currentExercise?.completed_warmup_sets || 0) + 1} of ${total} · ${nextSet.weight ?? '—'} × ${nextSet.reps ?? '—'}`;
    } else if (nextSet.kind === 'top') {
      planKindLabel = `TOP SET · ${nextSet.weight ?? '—'} × ${nextSet.reps ?? '—'}${nextSet.rpe_cap ? ` · cap RPE ${nextSet.rpe_cap}` : ''}`;
    } else {
      const total = resolvedPlan.filter(s => s.kind === 'backoff').length;
      const done = Math.max(0, (currentExercise?.completed_sets || 0) - 1);
      planKindLabel = `BACKOFF ${Math.min(done + 1, total)} of ${total} · ${nextSet.weight ?? '—'} × ${nextSet.reps ?? '—'}${nextSet.rir ? ` · ${nextSet.rir} RIR` : ''}`;
    }
  }

  return (
    <View style={styles.container}>
      {/* SET x OF y + progress — working sets only; a plan-driven lift shows
          the kind-aware line below instead while a warm-up is next. */}
      {!(nextSet && nextSet.kind === 'warmup') && (
        <View style={styles.setHeader}>
          <Text style={styles.setHeaderText}>
            SET {Math.min(progress.completed + 1, progress.total)} OF {progress.total}
          </Text>
        </View>
      )}
      {planKindLabel && (
        <View style={styles.planKindHeader}>
          <Text style={styles.planKindHeaderText}>{planKindLabel}</Text>
        </View>
      )}
      <View style={styles.progressBar}>
        <View style={[styles.progressFill, { width: `${progress.percentage}%` }]} />
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* Rest timer (only while resting). Tap anywhere on it to end the rest
            early when you're ready to start your next set. */}
        {restTimer?.is_active && restTimer.remaining_seconds !== undefined && (
          <Animated.View style={{ transform: [{ scale: timerPulse }] }}>
            <TouchableOpacity
              style={styles.restTimerContainer}
              onPress={stopRestTimer}
              activeOpacity={0.8}
            >
              <Ionicons name="time-outline" size={22} color={colors.accent} />
              <Text style={styles.restTimerText}>Rest: {formatTime(restTimer.remaining_seconds)}</Text>
              <View style={styles.skipRestButton}>
                <Text style={styles.skipRestText}>Tap to skip</Text>
              </View>
            </TouchableOpacity>
          </Animated.View>
        )}

        {currentExercise && (
          <>
            {/* Deload week badge — the program intentionally backs off this week. */}
            {session?.workout_snapshot?.is_deload && (
              <View style={styles.deloadBadge}>
                <Ionicons name="refresh-outline" size={14} color="#1a1408" />
                <Text style={styles.deloadBadgeText}>
                  DELOAD WEEK · lighter loads, focus on form
                </Text>
              </View>
            )}

            {/* Exercise header */}
            <View style={styles.exerciseHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.exerciseName}>{currentExercise.name}</Text>
                <Text style={styles.exerciseScheme}>{scheme}</Text>
                {/* Why this weight — the progression reasoning, finally shown. */}
                {currentExercise.progression_note ? (
                  <Text style={styles.progressionNote}>{currentExercise.progression_note}</Text>
                ) : null}
                {/* Coaching cue from the template — a plan-driven lift shows
                    the resolved-sets table below instead. */}
                {currentExercise.notes && !resolvedPlan ? (
                  <Text style={styles.exerciseNote}>💡 {currentExercise.notes}</Text>
                ) : null}
                {/* Advanced-set hints (were captured but invisible before). */}
                {(currentExercise.is_per_side || currentExercise.set_technique || currentExercise.superset_group) ? (
                  <View style={styles.exerciseTags}>
                    {currentExercise.is_per_side ? (
                      <Text style={styles.exerciseTag}>per side</Text>
                    ) : null}
                    {currentExercise.set_technique ? (
                      <Text style={styles.exerciseTag}>{currentExercise.set_technique}</Text>
                    ) : null}
                    {currentExercise.superset_group ? (
                      <Text style={styles.exerciseTag}>superset</Text>
                    ) : null}
                  </View>
                ) : null}
              </View>
              <View style={styles.rpeTarget}>
                <Text style={styles.rpeTargetLabel}>TARGET RPE</Text>
                <Text style={styles.rpeTargetValue}>{currentExercise.rpe_target ?? '—'}</Text>
              </View>
            </View>

            {/* Held banner — the advance rule (A2) repeated a prior week's
                loads because the last top set wasn't clean. One tap overrides
                it for this session only. */}
            {currentExercise.held && (
              <View style={styles.heldBanner}>
                <Ionicons name="pause-circle-outline" size={16} color={colors.warning} />
                <Text style={styles.heldBannerText}>
                  {currentExercise.plan_note || `Holding week ${currentExercise.effective_week} loads`}
                </Text>
                <TouchableOpacity
                  onPress={() => setPlanWeek(
                    session?.current_exercise_index ?? 0,
                    (currentExercise.effective_week || 1) + 1
                  )}
                >
                  <Text style={styles.heldBannerAction}>
                    Use week {(currentExercise.effective_week || 1) + 1} anyway
                  </Text>
                </TouchableOpacity>
              </View>
            )}

            {/* Resolved top/backoff table for a plan-driven AM lift — the
                whole session's shape at a glance, replacing the notes dump. */}
            {resolvedPlan && resolvedPlan.length > 0 && (() => {
              const warmupDone = currentExercise.completed_warmup_sets || 0;
              const workingDone = currentExercise.completed_sets || 0;
              let warmupSeen = 0;
              let workingSeen = 0;
              return (
                <View style={styles.planTable}>
                  {resolvedPlan.map((entry) => {
                    const isNext = nextSet ? nextSet.index === entry.index : false;
                    const isDone = entry.kind === 'warmup'
                      ? warmupSeen++ < warmupDone
                      : workingSeen++ < workingDone;
                    const label = entry.kind === 'warmup' ? 'Warm-up'
                      : entry.kind === 'top' ? 'Top' : 'Backoff';
                    return (
                      <View
                        key={entry.index}
                        style={[styles.planRow, isNext && styles.planRowNext]}
                      >
                        <Text style={[styles.planRowLabel, isDone && styles.planRowDone]}>
                          {isDone ? '✓ ' : ''}{label}
                        </Text>
                        <Text style={[styles.planRowValue, isDone && styles.planRowDone]}>
                          {entry.weight ?? '—'} × {entry.reps ?? '—'}
                          {entry.rpe_cap ? ` · cap RPE ${entry.rpe_cap}` : ''}
                          {entry.rir ? ` · ${entry.rir} RIR` : ''}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              );
            })()}

            {/* Machine / variation — scopes weight history so a different machine
                (e.g. hack squat vs barbell squat) is tracked separately. */}
            <View style={styles.variantBox}>
              <Text style={styles.variantLabel}>MACHINE / VARIATION</Text>
              <View style={styles.variantRow}>
                <TextInput
                  style={[styles.variantInput, { flex: 1 }]}
                  value={variantInput}
                  onChangeText={setVariantInput}
                  onEndEditing={commitVariant}
                  onSubmitEditing={() => { commitVariant(); Keyboard.dismiss(); }}
                  placeholder={currentExercise.name}
                  placeholderTextColor={colors.textMuted}
                  returnKeyType="done"
                />
                <TouchableOpacity
                  style={styles.variantBrowseButton}
                  onPress={() => setShowVariantPicker(true)}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                >
                  <Ionicons name="list-outline" size={20} color={colors.accent} />
                </TouchableOpacity>
              </View>
              <Text style={styles.variantHint}>
                {currentExercise.variant
                  ? `Logging as “${currentExercise.variant}” — separate from ${currentExercise.name}.`
                  : `Using ${currentExercise.name}. Tap the list icon to see past variants or change this.`}
              </Text>
            </View>

            <ExercisePickerModal
              visible={showVariantPicker}
              onClose={() => setShowVariantPicker(false)}
              exerciseName={currentExercise.variant || currentExercise.name}
              onSelectVariant={handlePickVariant}
            />

            {/* Weight stepper */}
            <Stepper
              label="WEIGHT"
              onDec={() => adjustWeight(-5)}
              onInc={() => adjustWeight(5)}
              value={customWeight}
              unit="lbs"
              onChangeText={setCustomWeight}
              placeholder={currentExercise.suggested_weight?.toString() || '0'}
            />

            {/* Reps stepper */}
            <Stepper
              label="REPS"
              onDec={() => adjustReps(-1)}
              onInc={() => adjustReps(1)}
              value={customReps}
              onChangeText={setCustomReps}
              placeholder={currentExercise.reps?.toString().split('-')[0] || '8'}
            />

            {/* Warm-up chip — a plan-driven lift only. Auto-selected while
                next_set.kind is 'warmup'; toggling it off is how "skip
                warm-ups" works: the working-set cursor tracks independently
                server-side (set_plan.next_entry), so it lands on the top set
                as soon as a working set is logged regardless of warm-ups. */}
            {resolvedPlan && resolvedPlan.some(s => s.kind === 'warmup') && (
              <TouchableOpacity
                style={[styles.warmupChip, warmupSelected && styles.warmupChipActive]}
                onPress={() => setWarmupSelected(w => !w)}
              >
                <Ionicons
                  name={warmupSelected ? 'checkbox' : 'square-outline'}
                  size={16}
                  color={warmupSelected ? colors.background : colors.textSecondary}
                />
                <Text style={[styles.warmupChipText, warmupSelected && styles.warmupChipTextActive]}>
                  Warm-up
                </Text>
              </TouchableOpacity>
            )}

            {/* Log set */}
            <TouchableOpacity
              style={[styles.logButton, isLogging && styles.disabled]}
              onPress={handleLogSet}
              disabled={isLogging}
            >
              <Ionicons name="checkmark" size={20} color={colors.background} />
              <Text style={styles.logButtonText}>LOG SET</Text>
            </TouchableOpacity>

            {/* Add Set / Drop Set / Sets / Undo. Subordinate to LOG SET by
                design: the common path stays one tap (§7.1). */}
            <WorkoutSetActions />

            {/* RPE feedback chips */}
            <View style={styles.feelingRow}>
              {FEELINGS.map(f => {
                const active = feeling === f.key;
                return (
                  <TouchableOpacity
                    key={f.key}
                    style={[styles.feelingCard, active && { borderColor: f.color, backgroundColor: f.color + '22' }]}
                    onPress={() => setFeeling(f.key)}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.feelingEmoji}>{f.emoji}</Text>
                    <Text style={[styles.feelingLabel, active && { color: f.color, fontWeight: fontWeights.bold }]}>
                      {f.label}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* Coaching feedback */}
            {lastFeedback && (
              <View style={styles.feedbackContainer}>
                <Ionicons name="chatbubble-ellipses" size={16} color={colors.accent} />
                <Text style={styles.feedbackText}>{lastFeedback}</Text>
              </View>
            )}

            {/* Coaching wants headphones — the phone speaker is never a
                fallback, so this is the only way David learns Sara has
                something to say (2026-09-09 hygiene plan §Phase 3). */}
            {coachingNeedsHeadphones && (
              <View style={styles.feedbackContainer}>
                <Ionicons name="headset" size={16} color={colors.textSecondary} />
                <Text style={styles.feedbackText}>Put in headphones to hear Sara</Text>
              </View>
            )}

            {/* Last session + Goal */}
            <View style={styles.infoRow}>
              <View style={styles.infoCard}>
                <View style={styles.infoCardHeader}>
                  <Ionicons name="stats-chart" size={13} color={colors.textSecondary} />
                  <Text style={styles.infoCardTitle}>LAST SESSION</Text>
                </View>
                {last?.weights?.length ? (
                  last.weights.map((w, i) => (
                    <Text key={i} style={styles.infoLine}>
                      Set {i + 1}{'   '}
                      <Text style={styles.infoLineValue}>{w} lbs × {last.reps?.[i] ?? '?'}</Text>
                    </Text>
                  ))
                ) : (
                  <Text style={styles.infoMuted}>No previous data</Text>
                )}
              </View>

              <View style={styles.infoCard}>
                <View style={styles.infoCardHeader}>
                  <Ionicons name="flag" size={13} color={colors.textSecondary} />
                  <Text style={styles.infoCardTitle}>GOAL</Text>
                </View>
                <Text style={styles.goalText}>
                  {last?.weights?.length
                    ? 'Beat at least one set today.'
                    : `Log all ${currentExercise.sets} sets.`}
                </Text>
              </View>
            </View>

            {/* Exercise list — tap any exercise to jump to it (do them in any
                order; skip a busy machine and come back). */}
            <Text style={styles.listHint}>Tap an exercise to jump to it</Text>
            <View style={styles.exerciseList}>
              {(session.workout_snapshot?.exercises || []).map((exercise, index) => {
                const isCurrent = index === (session.current_exercise_index || 0);
                const done = exercise.completed_sets ?? 0;
                const isCompleted = done >= exercise.sets;
                const isPartial = done > 0 && !isCompleted;
                return (
                  <TouchableOpacity
                    key={`${exercise.name}-${index}`}
                    style={[styles.listItem, isCurrent && styles.listItemCurrent]}
                    onPress={() => selectExercise(index)}
                    disabled={isCurrent}
                    activeOpacity={0.7}
                  >
                    <View
                      style={[
                        styles.listNum,
                        isCurrent && styles.listNumCurrent,
                        isCompleted && styles.listNumDone,
                      ]}
                    >
                      {isCompleted ? (
                        <Ionicons name="checkmark" size={13} color={colors.background} />
                      ) : (
                        <Text style={[styles.listNumText, isCurrent && { color: colors.background }]}>
                          {index + 1}
                        </Text>
                      )}
                    </View>
                    <View style={styles.listContent}>
                      <Text style={[styles.listName, isCompleted && styles.listNameDone]}>
                        {exercise.name}
                        {exercise.variant ? <Text style={styles.listVariant}>{`  ›  ${exercise.variant}`}</Text> : null}
                      </Text>
                      <Text style={styles.listSets}>
                        {exercise.sets} × {exercise.reps}
                        {exercise.suggested_weight ? ` @ ${exercise.suggested_weight} lbs` : ''}
                        {isPartial ? `  ·  ${done}/${exercise.sets} done` : ''}
                      </Text>
                    </View>
                    <Ionicons
                      name={isCompleted ? 'checkmark-circle' : isCurrent ? 'ellipse' : 'ellipse-outline'}
                      size={18}
                      color={isCompleted ? colors.success : isCurrent ? colors.primary : colors.textMuted}
                    />
                  </TouchableOpacity>
                );
              })}
            </View>
          </>
        )}
      </ScrollView>

      {/* Bottom action bar */}
      <View style={styles.bottomBar}>
        <TouchableOpacity style={styles.bottomAction} onPress={() => startRestTimer(120)}>
          <Ionicons name="timer-outline" size={20} color={colors.textSecondary} />
          <Text style={styles.bottomActionText}>Rest Timer</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.bottomAction} onPress={skipExercise}>
          <Ionicons name="play-skip-forward" size={20} color={colors.textSecondary} />
          <Text style={styles.bottomActionText}>Skip Exercise</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.bottomAction} onPress={handleFinish}>
          <Ionicons name="flag" size={20} color={colors.error} />
          <Text style={[styles.bottomActionText, { color: colors.error }]}>Finish Workout</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// Reusable −/value/+ stepper row matching the mockup.
function Stepper({
  label,
  value,
  unit,
  placeholder,
  onDec,
  onInc,
  onChangeText,
}: {
  label: string;
  value: string;
  unit?: string;
  placeholder?: string;
  onDec: () => void;
  onInc: () => void;
  onChangeText: (t: string) => void;
}) {
  return (
    <View style={styles.stepper}>
      <Text style={styles.stepperLabel}>{label}</Text>
      <View style={styles.stepperRow}>
        <TouchableOpacity style={styles.stepperBtn} onPress={onDec}>
          <Ionicons name="remove" size={24} color={colors.text} />
        </TouchableOpacity>
        <View style={styles.stepperValueWrap}>
          <TextInput
            style={styles.stepperValue}
            value={value}
            onChangeText={onChangeText}
            keyboardType="numeric"
            placeholder={placeholder}
            placeholderTextColor={colors.textMuted}
            selectTextOnFocus
            returnKeyType="done"
            onSubmitEditing={() => Keyboard.dismiss()}
          />
          {unit ? <Text style={styles.stepperUnit}>{unit}</Text> : null}
        </View>
        <TouchableOpacity style={styles.stepperBtn} onPress={onInc}>
          <Ionicons name="add" size={24} color={colors.text} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  // collapsed bar (chat reveal)
  collapsedPanel: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.sm + 4,
    margin: spacing.sm,
  },
  collapsedContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  collapsedText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
    flex: 1,
  },
  miniTimer: {
    backgroundColor: colors.assistant.actionSoft,
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 3,
    borderRadius: borderRadius.full,
  },
  miniTimerText: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.bold,
  },

  setHeader: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
  },
  setHeaderText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
    letterSpacing: 1,
  },
  progressBar: {
    height: 4,
    backgroundColor: colors.surfaceLight,
    marginHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: borderRadius.full,
  },

  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.md,
    paddingBottom: spacing.lg,
    gap: spacing.md,
  },

  restTimerContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    paddingVertical: spacing.sm + 4,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.lg,
    gap: spacing.sm,
  },
  restTimerText: {
    color: colors.accent,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
    flex: 1,
    textAlign: 'center',
  },
  skipRestButton: {
    paddingHorizontal: spacing.sm + 4,
    paddingVertical: spacing.xs + 2,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
  },
  skipRestText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
  },

  exerciseHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  exerciseName: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
  },
  exerciseScheme: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  progressionNote: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    marginTop: 6,
  },
  exerciseNote: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 4,
    fontStyle: 'italic',
  },
  exerciseTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 6,
  },
  exerciseTag: {
    color: colors.text,
    fontSize: 11,
    fontWeight: fontWeights.semibold,
    backgroundColor: colors.assistant.panelRaised,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: 'hidden',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  deloadBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    backgroundColor: '#ffd24a',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
    marginBottom: 10,
  },
  deloadBadgeText: {
    color: '#1a1408',
    fontSize: 11,
    fontWeight: fontWeights.bold,
    letterSpacing: 0.3,
  },
  planKindHeader: {
    paddingHorizontal: spacing.md,
    paddingBottom: 4,
  },
  planKindHeaderText: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.bold,
    letterSpacing: 0.3,
  },
  heldBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    backgroundColor: colors.assistant.panelRaised,
    borderWidth: 1,
    borderColor: colors.warning,
    borderRadius: borderRadius.md,
    padding: 10,
    marginBottom: 10,
  },
  heldBannerText: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  heldBannerAction: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.bold,
  },
  planTable: {
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.md,
    padding: 8,
    marginBottom: 12,
    gap: 2,
  },
  planRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 5,
    paddingHorizontal: 6,
    borderRadius: 6,
  },
  planRowNext: {
    backgroundColor: colors.accent + '22',
  },
  planRowLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  planRowValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  planRowDone: {
    opacity: 0.5,
  },
  warmupChip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginBottom: 10,
  },
  warmupChipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  warmupChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  warmupChipTextActive: {
    color: colors.background,
  },
  rpeTarget: {
    alignItems: 'flex-end',
  },
  rpeTargetLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
  },
  rpeTargetValue: {
    color: colors.accent,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
  },

  variantBox: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.xl,
    padding: spacing.md,
  },
  variantLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  variantInput: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.semibold,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  variantRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  variantBrowseButton: {
    padding: spacing.xs,
  },
  variantHint: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  stepper: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.xl,
    padding: spacing.md,
  },
  stepperLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  stepperRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  stepperBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.surfaceLight,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepperValueWrap: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
  },
  stepperValue: {
    color: colors.text,
    fontSize: 40,
    fontWeight: fontWeights.bold,
    textAlign: 'center',
    minWidth: 90,
    padding: 0,
  },
  stepperUnit: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.medium,
  },

  logButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md,
  },
  logButtonText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    letterSpacing: 0.5,
  },
  disabled: {
    opacity: 0.5,
  },

  feelingRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  feelingCard: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    gap: 4,
  },
  feelingEmoji: {
    fontSize: 22,
  },
  feelingLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
  },

  feedbackContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.assistant.passiveSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    padding: spacing.sm + 4,
    borderRadius: borderRadius.lg,
  },
  feedbackText: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    flex: 1,
  },

  infoRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  infoCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.lg,
    padding: spacing.sm + 4,
  },
  infoCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  infoCardTitle: {
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.5,
  },
  infoLine: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginBottom: 3,
  },
  infoLineValue: {
    color: colors.text,
    fontWeight: fontWeights.semibold,
  },
  infoMuted: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  goalText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },

  listHint: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
    marginBottom: spacing.xs,
  },
  exerciseList: {
    gap: spacing.xs,
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  listItemCurrent: {
    borderColor: colors.assistant.borderStrong,
    backgroundColor: colors.assistant.actionSoft,
  },
  listNum: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surfaceLight,
    borderWidth: 1,
    borderColor: colors.border,
  },
  listNumCurrent: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  listNumDone: {
    backgroundColor: colors.success,
    borderColor: colors.success,
  },
  listNumText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.bold,
  },
  listContent: {
    flex: 1,
  },
  listName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  listNameDone: {
    color: colors.textMuted,
  },
  listVariant: {
    color: colors.accent,
    fontWeight: fontWeights.medium,
  },
  listSets: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 1,
  },

  bottomBar: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  bottomAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
  },
  bottomActionText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
  },
});

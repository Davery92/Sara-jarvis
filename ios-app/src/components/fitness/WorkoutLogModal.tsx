import React, { useState, useEffect } from 'react';
import {
  View,
  Modal,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import DateTimePicker from '@react-native-community/datetimepicker';
import {
  fitnessService,
  WorkoutTemplate,
  WeightSuggestion,
  CreateWorkoutSetParams,
} from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface WorkoutExercise {
  name: string;
  targetSets: number;
  targetReps: string;
  targetRpe: number;
  sets: Array<{ weight: number; reps: number; rpe: number }>;
  completed: boolean;
  suggestedWeight?: number;
  weightReasoning?: string;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onComplete: () => void;
}

type WorkoutMode = 'select' | 'today' | 'template' | 'custom';

export default function WorkoutLogModal({ visible, onClose, onComplete }: Props) {
  const [mode, setMode] = useState<WorkoutMode>('select');
  const [loading, setLoading] = useState(false);
  const [templates, setTemplates] = useState<WorkoutTemplate[]>([]);
  const [todayTemplate, setTodayTemplate] = useState<WorkoutTemplate | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<WorkoutTemplate | null>(null);

  // Template/Multi-exercise workout state
  const [workoutExercises, setWorkoutExercises] = useState<WorkoutExercise[]>([]);
  const [currentExerciseIndex, setCurrentExerciseIndex] = useState(0);

  // Custom single exercise state
  const [exerciseName, setExerciseName] = useState('');
  const [sets, setSets] = useState<Array<{ weight: number; reps: number; rpe: number }>>([
    { weight: 0, reps: 0, rpe: 7 },
  ]);
  const [notes, setNotes] = useState('');

  // Date/time picker state
  const [workoutDate, setWorkoutDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  useEffect(() => {
    if (visible) {
      loadTemplates();
      loadTodayWorkout();
    }
  }, [visible]);

  const loadTemplates = async () => {
    try {
      const data = await fitnessService.getTemplates();
      setTemplates(data.templates || []);
    } catch (error) {
      console.error('Failed to load templates:', error);
    }
  };

  const loadTodayWorkout = async () => {
    try {
      const data = await fitnessService.getTodaysTemplates();
      setTodayTemplate(data.templates?.[0] || null);
    } catch (error) {
      console.error('Failed to load today\'s workout:', error);
    }
  };

  const loadTemplateExercises = async (template: WorkoutTemplate) => {
    setLoading(true);
    try {
      const exercises = await Promise.all(
        template.exercises.map(async (ex) => {
          const targetReps = ex.reps?.includes('-')
            ? parseInt(ex.reps.split('-')[0])
            : parseInt(ex.reps || '10');

          let suggestedWeight = 0;
          let weightReasoning = 'No suggestion available';

          try {
            const suggestion = await fitnessService.getWeightSuggestion(
              ex.name,
              template.id,
              targetReps
            );
            suggestedWeight = suggestion.suggested_weight || 0;
            weightReasoning = suggestion.reasoning || 'AI suggestion';
          } catch (error) {
            console.error(`Failed to fetch weight suggestion for ${ex.name}:`, error);
          }

          return {
            name: ex.name,
            targetSets: ex.sets || 3,
            targetReps: ex.reps || '10',
            targetRpe: ex.rpe_target || 7,
            sets: Array(ex.sets || 3)
              .fill(null)
              .map(() => ({
                weight: suggestedWeight,
                reps: targetReps,
                rpe: ex.rpe_target || 7,
              })),
            completed: false,
            suggestedWeight,
            weightReasoning,
          };
        })
      );

      setWorkoutExercises(exercises);
      setCurrentExerciseIndex(0);
    } catch (error) {
      console.error('Failed to load template exercises:', error);
      Alert.alert('Error', 'Failed to load workout exercises');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectTodayWorkout = () => {
    if (!todayTemplate) return;
    setSelectedTemplate(todayTemplate);
    loadTemplateExercises(todayTemplate);
    setMode('today');
  };

  const handleSelectTemplate = (template: WorkoutTemplate) => {
    setSelectedTemplate(template);
    loadTemplateExercises(template);
    setMode('template');
  };

  const handleSelectCustom = () => {
    setExerciseName('');
    setSets([{ weight: 0, reps: 0, rpe: 7 }]);
    setNotes('');
    setMode('custom');
  };

  const handleClose = () => {
    setMode('select');
    setExerciseName('');
    setSets([{ weight: 0, reps: 0, rpe: 7 }]);
    setNotes('');
    setWorkoutExercises([]);
    setCurrentExerciseIndex(0);
    setSelectedTemplate(null);
    onClose();
  };

  const addSet = () => {
    setSets([...sets, { weight: 0, reps: 0, rpe: 7 }]);
  };

  const removeSet = (index: number) => {
    if (sets.length > 1) {
      setSets(sets.filter((_, i) => i !== index));
    }
  };

  const updateSet = (index: number, field: 'weight' | 'reps' | 'rpe', value: number) => {
    const newSets = [...sets];
    newSets[index][field] = value;
    setSets(newSets);
  };

  const updateExerciseSet = (
    exerciseIndex: number,
    setIndex: number,
    field: 'weight' | 'reps' | 'rpe',
    value: number
  ) => {
    const newExercises = [...workoutExercises];
    newExercises[exerciseIndex].sets[setIndex][field] = value;
    setWorkoutExercises(newExercises);
  };

  // Format date in local timezone without converting to UTC
  const formatLocalDateTime = (date: Date): string => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
  };

  const formatLocalDate = (date: Date): string => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const handleSubmitCustom = async () => {
    if (!exerciseName.trim() || sets.some((s) => s.weight <= 0 || s.reps <= 0)) {
      Alert.alert('Error', 'Please fill in all exercise details');
      return;
    }

    setLoading(true);
    try {
      const sessionDate = formatLocalDate(workoutDate);
      const sessionTime = formatLocalDateTime(workoutDate);

      for (let i = 0; i < sets.length; i++) {
        const set = sets[i];
        await fitnessService.createWorkoutSet({
          exercise_name: exerciseName,
          set_index: i + 1,
          weight: set.weight,
          reps: set.reps,
          rpe: set.rpe,
          notes: i === 0 ? notes : undefined,
          session_date: sessionDate,
          session_time: sessionTime,
        });
      }
      onComplete();
      handleClose();
    } catch (error) {
      console.error('Failed to log workout:', error);
      Alert.alert('Error', 'Failed to log workout');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitTemplate = async () => {
    setLoading(true);
    try {
      const sessionDate = formatLocalDate(workoutDate);
      const sessionTime = formatLocalDateTime(workoutDate);

      for (const exercise of workoutExercises) {
        for (let i = 0; i < exercise.sets.length; i++) {
          const set = exercise.sets[i];
          if (set.weight > 0 && set.reps > 0) {
            await fitnessService.createWorkoutSet({
              exercise_name: exercise.name,
              set_index: i + 1,
              weight: set.weight,
              reps: set.reps,
              rpe: set.rpe,
              session_date: sessionDate,
              session_time: sessionTime,
            });
          }
        }
      }
      onComplete();
      handleClose();
    } catch (error) {
      console.error('Failed to log workout:', error);
      Alert.alert('Error', 'Failed to log workout');
    } finally {
      setLoading(false);
    }
  };

  const completeExercise = () => {
    const newExercises = [...workoutExercises];
    newExercises[currentExerciseIndex].completed = true;
    setWorkoutExercises(newExercises);

    if (currentExerciseIndex < workoutExercises.length - 1) {
      setCurrentExerciseIndex(currentExerciseIndex + 1);
    }
  };

  const currentExercise = workoutExercises[currentExerciseIndex];

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={handleClose}
      presentationStyle="pageSheet"
    >
      <View style={styles.container}>
        <SafeAreaView edges={['top']}>
          <View style={styles.header}>
            <Text style={styles.title}>Log Workout</Text>
            <TouchableOpacity onPress={handleClose} style={styles.closeButtonContainer}>
              <Text style={styles.closeButton}>✕</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>

        <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
          {/* Selection Screen */}
          {mode === 'select' && (
            <View style={styles.selectionContainer}>
              {todayTemplate && (
                <TouchableOpacity
                  style={styles.todayButton}
                  onPress={handleSelectTodayWorkout}
                >
                  <Text style={styles.todayButtonTitle}>📅 Today's Workout</Text>
                  <Text style={styles.todayButtonSubtitle}>{todayTemplate.name}</Text>
                </TouchableOpacity>
              )}

              <View style={styles.divider}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>or choose</Text>
                <View style={styles.dividerLine} />
              </View>

              {templates.length > 0 && (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Choose Template</Text>
                  {templates.map((template) => (
                    <TouchableOpacity
                      key={template.id}
                      style={styles.templateButton}
                      onPress={() => handleSelectTemplate(template)}
                    >
                      <View>
                        <Text style={styles.templateName}>{template.name}</Text>
                        <Text style={styles.templateSubtitle}>
                          {template.exercises.length} exercises
                        </Text>
                      </View>
                      <Text style={styles.arrow}>›</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              )}

              <TouchableOpacity style={styles.customButton} onPress={handleSelectCustom}>
                <View>
                  <Text style={styles.customButtonTitle}>✏️ Custom Exercise</Text>
                  <Text style={styles.customButtonSubtitle}>Create as you go</Text>
                </View>
                <Text style={styles.arrow}>›</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Custom Exercise Form */}
          {mode === 'custom' && (
            <View style={styles.formContainer}>
              <Text style={styles.label}>Exercise Name</Text>
              <TextInput
                style={styles.input}
                value={exerciseName}
                onChangeText={setExerciseName}
                placeholder="e.g., Bench Press, Squats..."
                placeholderTextColor={colors.textMuted}
              />

              <View style={styles.dateTimeSection}>
                <Text style={styles.label}>Workout Date & Time</Text>
                <View style={styles.dateTimeRow}>
                  <TouchableOpacity
                    onPress={() => setShowDatePicker(true)}
                    style={[styles.dateTimeButton, { flex: 1, marginRight: spacing.sm }]}
                  >
                    <Text style={styles.dateTimeText}>
                      📅 {workoutDate.toLocaleDateString()}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => setShowTimePicker(true)}
                    style={[styles.dateTimeButton, { flex: 1 }]}
                  >
                    <Text style={styles.dateTimeText}>
                      🕐 {workoutDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>

              {showDatePicker && (
                <DateTimePicker
                  value={workoutDate}
                  mode="date"
                  display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                  onChange={(event, selectedDate) => {
                    setShowDatePicker(Platform.OS === 'ios');
                    if (selectedDate) {
                      // Preserve the time from current workoutDate
                      const newDate = new Date(selectedDate);
                      newDate.setHours(workoutDate.getHours());
                      newDate.setMinutes(workoutDate.getMinutes());
                      newDate.setSeconds(workoutDate.getSeconds());
                      setWorkoutDate(newDate);
                    }
                  }}
                />
              )}

              {showTimePicker && (
                <DateTimePicker
                  value={workoutDate}
                  mode="time"
                  display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                  onChange={(event, selectedTime) => {
                    setShowTimePicker(Platform.OS === 'ios');
                    if (selectedTime) {
                      // Preserve the date from current workoutDate
                      const newDate = new Date(workoutDate);
                      newDate.setHours(selectedTime.getHours());
                      newDate.setMinutes(selectedTime.getMinutes());
                      newDate.setSeconds(selectedTime.getSeconds());
                      setWorkoutDate(newDate);
                    }
                  }}
                />
              )}

              <View style={styles.setsHeader}>
                <Text style={styles.label}>Sets</Text>
                <TouchableOpacity onPress={addSet}>
                  <Text style={styles.addSetButton}>+ Add Set</Text>
                </TouchableOpacity>
              </View>

              {sets.map((set, index) => (
                <View key={index} style={styles.setRow}>
                  <Text style={styles.setLabel}>Set {index + 1}</Text>
                  <TextInput
                    style={styles.setInput}
                    value={set.weight > 0 ? set.weight.toString() : ''}
                    onChangeText={(val) => updateSet(index, 'weight', parseFloat(val) || 0)}
                    placeholder="lbs"
                    placeholderTextColor={colors.textMuted}
                    keyboardType="numeric"
                  />
                  <Text style={styles.setX}>×</Text>
                  <TextInput
                    style={styles.setInput}
                    value={set.reps > 0 ? set.reps.toString() : ''}
                    onChangeText={(val) => updateSet(index, 'reps', parseInt(val) || 0)}
                    placeholder="reps"
                    placeholderTextColor={colors.textMuted}
                    keyboardType="numeric"
                  />
                  <Text style={styles.rpeLabel}>RPE</Text>
                  <TextInput
                    style={styles.rpeInput}
                    value={set.rpe.toString()}
                    onChangeText={(val) => updateSet(index, 'rpe', parseInt(val) || 7)}
                    keyboardType="numeric"
                  />
                  {sets.length > 1 && (
                    <TouchableOpacity onPress={() => removeSet(index)}>
                      <Text style={styles.removeButton}>✕</Text>
                    </TouchableOpacity>
                  )}
                </View>
              ))}

              <Text style={styles.label}>Notes (optional)</Text>
              <TextInput
                style={styles.notesInput}
                value={notes}
                onChangeText={setNotes}
                placeholder="How did it feel? Any observations?"
                placeholderTextColor={colors.textMuted}
                multiline
                numberOfLines={3}
              />

              <View style={styles.buttonRow}>
                <TouchableOpacity
                  style={[styles.button, styles.primaryButton]}
                  onPress={handleSubmitCustom}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator color={colors.text} />
                  ) : (
                    <Text style={styles.buttonText}>Log Workout</Text>
                  )}
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.button, styles.secondaryButton]}
                  onPress={() => setMode('select')}
                >
                  <Text style={styles.secondaryButtonText}>Back</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}

          {/* Template Workout Form */}
          {(mode === 'today' || mode === 'template') && currentExercise && (
            <View style={styles.formContainer}>
              <View style={styles.exerciseHeader}>
                <Text style={styles.exerciseName}>{currentExercise.name}</Text>
                <Text style={styles.exerciseProgress}>
                  Exercise {currentExerciseIndex + 1} of {workoutExercises.length}
                </Text>
              </View>

              {/* Date/Time Picker */}
              {currentExerciseIndex === 0 && (
                <>
                  <View style={styles.dateTimeSection}>
                    <Text style={styles.label}>Workout Date & Time</Text>
                    <View style={styles.dateTimeRow}>
                      <TouchableOpacity
                        onPress={() => setShowDatePicker(true)}
                        style={[styles.dateTimeButton, { flex: 1, marginRight: spacing.sm }]}
                      >
                        <Text style={styles.dateTimeText}>
                          📅 {workoutDate.toLocaleDateString()}
                        </Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={() => setShowTimePicker(true)}
                        style={[styles.dateTimeButton, { flex: 1 }]}
                      >
                        <Text style={styles.dateTimeText}>
                          🕐 {workoutDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  </View>

                  {showDatePicker && (
                    <DateTimePicker
                      value={workoutDate}
                      mode="date"
                      display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                      onChange={(event, selectedDate) => {
                        setShowDatePicker(Platform.OS === 'ios');
                        if (selectedDate) {
                          // Preserve the time from current workoutDate
                          const newDate = new Date(selectedDate);
                          newDate.setHours(workoutDate.getHours());
                          newDate.setMinutes(workoutDate.getMinutes());
                          newDate.setSeconds(workoutDate.getSeconds());
                          setWorkoutDate(newDate);
                        }
                      }}
                    />
                  )}

                  {showTimePicker && (
                    <DateTimePicker
                      value={workoutDate}
                      mode="time"
                      display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                      onChange={(event, selectedTime) => {
                        setShowTimePicker(Platform.OS === 'ios');
                        if (selectedTime) {
                          // Preserve the date from current workoutDate
                          const newDate = new Date(workoutDate);
                          newDate.setHours(selectedTime.getHours());
                          newDate.setMinutes(selectedTime.getMinutes());
                          newDate.setSeconds(selectedTime.getSeconds());
                          setWorkoutDate(newDate);
                        }
                      }}
                    />
                  )}
                </>
              )}

              <View style={styles.targetInfo}>
                <Text style={styles.targetText}>
                  Target: {currentExercise.targetSets} sets × {currentExercise.targetReps} reps
                  @ RPE {currentExercise.targetRpe}
                </Text>
              </View>

              {currentExercise.suggestedWeight && currentExercise.suggestedWeight > 0 && (
                <View style={styles.suggestionCard}>
                  <View style={styles.suggestionHeader}>
                    <Text style={styles.suggestionTitle}>📈 AI Suggestion</Text>
                    <Text style={styles.suggestionWeight}>
                      {currentExercise.suggestedWeight}lbs
                    </Text>
                  </View>
                  <Text style={styles.suggestionReason}>{currentExercise.weightReasoning}</Text>
                </View>
              )}

              {currentExercise.sets.map((set, idx) => (
                <View key={idx} style={styles.setRow}>
                  <Text style={styles.setLabel}>Set {idx + 1}</Text>
                  <TextInput
                    style={styles.setInput}
                    value={set.weight > 0 ? set.weight.toString() : ''}
                    onChangeText={(val) =>
                      updateExerciseSet(currentExerciseIndex, idx, 'weight', parseFloat(val) || 0)
                    }
                    placeholder="lbs"
                    placeholderTextColor={colors.textMuted}
                    keyboardType="numeric"
                  />
                  <Text style={styles.setX}>×</Text>
                  <TextInput
                    style={styles.setInput}
                    value={set.reps > 0 ? set.reps.toString() : ''}
                    onChangeText={(val) =>
                      updateExerciseSet(currentExerciseIndex, idx, 'reps', parseInt(val) || 0)
                    }
                    placeholder="reps"
                    placeholderTextColor={colors.textMuted}
                    keyboardType="numeric"
                  />
                  <Text style={styles.rpeLabel}>RPE</Text>
                  <TextInput
                    style={styles.rpeInput}
                    value={set.rpe.toString()}
                    onChangeText={(val) =>
                      updateExerciseSet(currentExerciseIndex, idx, 'rpe', parseInt(val) || 7)
                    }
                    keyboardType="numeric"
                  />
                </View>
              ))}

              {/* Progress Bar */}
              <View style={styles.progressBar}>
                {workoutExercises.map((ex, idx) => (
                  <View
                    key={idx}
                    style={[
                      styles.progressSegment,
                      ex.completed
                        ? styles.progressCompleted
                        : idx === currentExerciseIndex
                        ? styles.progressCurrent
                        : styles.progressPending,
                    ]}
                  />
                ))}
              </View>

              <View style={styles.buttonRow}>
                {currentExerciseIndex < workoutExercises.length - 1 ? (
                  <>
                    <TouchableOpacity
                      style={[styles.button, styles.primaryButton]}
                      onPress={completeExercise}
                    >
                      <Text style={styles.buttonText}>Next Exercise</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.button, styles.secondaryButton]}
                      onPress={() => setMode('select')}
                    >
                      <Text style={styles.secondaryButtonText}>Cancel</Text>
                    </TouchableOpacity>
                  </>
                ) : (
                  <>
                    <TouchableOpacity
                      style={[styles.button, styles.finishButton]}
                      onPress={handleSubmitTemplate}
                      disabled={loading}
                    >
                      {loading ? (
                        <ActivityIndicator color={colors.text} />
                      ) : (
                        <Text style={styles.buttonText}>Finish Workout</Text>
                      )}
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.button, styles.secondaryButton]}
                      onPress={() => setMode('select')}
                      disabled={loading}
                    >
                      <Text style={styles.secondaryButtonText}>Cancel</Text>
                    </TouchableOpacity>
                  </>
                )}
              </View>
            </View>
          )}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.surface,
  },
  title: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
  },
  closeButtonContainer: {
    padding: spacing.sm,
    minWidth: 44,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButton: {
    fontSize: fontSizes.xxl,
    color: colors.textSecondary,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: spacing.md,
  },
  selectionContainer: {
    gap: spacing.md,
  },
  todayButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
  },
  todayButtonTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  todayButtonSubtitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    opacity: 0.9,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: spacing.md,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.surface,
  },
  dividerText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    paddingHorizontal: spacing.sm,
  },
  section: {
    gap: spacing.sm,
  },
  sectionTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  templateButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  templateName: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  templateSubtitle: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  customButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  customButtonTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  customButtonSubtitle: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  arrow: {
    fontSize: fontSizes.xxl,
    color: colors.textSecondary,
  },
  formContainer: {
    gap: spacing.md,
  },
  label: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.surface,
  },
  setsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  addSetButton: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  setRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  setLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    width: 50,
  },
  setInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
  },
  setX: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
  },
  rpeLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  rpeInput: {
    width: 50,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
  },
  removeButton: {
    fontSize: fontSizes.lg,
    color: '#FF6B6B',
    paddingHorizontal: spacing.xs,
  },
  notesInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.surface,
    minHeight: 80,
    textAlignVertical: 'top',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  button: {
    flex: 1,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  primaryButton: {
    backgroundColor: colors.primary,
  },
  secondaryButton: {
    backgroundColor: colors.surface,
  },
  finishButton: {
    backgroundColor: '#4CAF50',
  },
  buttonText: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  secondaryButtonText: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  exerciseHeader: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  exerciseName: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  exerciseProgress: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  targetInfo: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
  },
  targetText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  suggestionCard: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.3)',
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  suggestionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  suggestionTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: '#60A5FA',
  },
  suggestionWeight: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
  },
  suggestionReason: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  progressBar: {
    flexDirection: 'row',
    gap: spacing.xs,
    marginTop: spacing.md,
  },
  progressSegment: {
    flex: 1,
    height: 8,
    borderRadius: borderRadius.sm,
  },
  progressCompleted: {
    backgroundColor: '#4CAF50',
  },
  progressCurrent: {
    backgroundColor: colors.primary,
  },
  progressPending: {
    backgroundColor: colors.surface,
  },
  dateTimeSection: {
    gap: spacing.xs,
  },
  dateTimeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  dateTimeButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.surface,
  },
  dateTimeText: {
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
  },
});

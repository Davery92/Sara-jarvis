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
import { fitnessService, WorkoutSession, WorkoutSet } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Props {
  visible: boolean;
  workoutSession: WorkoutSession | null;
  onClose: () => void;
  onComplete: () => void;
}

export default function WorkoutEditModal({ visible, workoutSession, onClose, onComplete }: Props) {
  const [loading, setLoading] = useState(false);
  const [workoutDate, setWorkoutDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);
  const [sets, setSets] = useState<WorkoutSet[]>([]);

  useEffect(() => {
    if (workoutSession) {
      setSets([...workoutSession.exercises]);
      // Use session_time from the first set if available, otherwise fall back to session_date or created_at
      const firstSet = workoutSession.exercises[0];
      const dateStr = firstSet?.session_time || workoutSession.session_date || workoutSession.created_at;
      // Handle date-only strings by adding noon time
      const dateToUse = dateStr.includes('T') ? dateStr : `${dateStr}T12:00:00`;
      setWorkoutDate(new Date(dateToUse));
    }
  }, [workoutSession]);

  const updateSet = (index: number, field: 'weight' | 'reps' | 'rpe', value: number) => {
    const newSets = [...sets];
    newSets[index][field] = value;
    setSets(newSets);
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

  const handleSave = async () => {
    setLoading(true);
    try {
      // Update each set
      for (const set of sets) {
        await fitnessService.updateWorkoutSet(set.id, {
          weight: set.weight,
          reps: set.reps,
          rpe: set.rpe,
          session_date: formatLocalDate(workoutDate),
          session_time: formatLocalDateTime(workoutDate),
        });
      }
      onComplete();
      onClose();
    } catch (error) {
      console.error('Failed to update workout:', error);
      Alert.alert('Error', 'Failed to update workout');
    } finally {
      setLoading(false);
    }
  };

  if (!workoutSession) {
    return null;
  }

  // Group sets by exercise name
  const exerciseGroups: { [key: string]: WorkoutSet[] } = {};
  sets.forEach((set) => {
    const exerciseName = set.exercise_id || 'Unknown Exercise';
    if (!exerciseGroups[exerciseName]) {
      exerciseGroups[exerciseName] = [];
    }
    exerciseGroups[exerciseName].push(set);
  });

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
      presentationStyle="pageSheet"
    >
      <View style={styles.container}>
        <SafeAreaView edges={['top']}>
          <View style={styles.header}>
            <Text style={styles.title}>Edit Workout</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeButtonContainer}>
              <Text style={styles.closeButton}>✕</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>

        <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
          <View style={styles.formContainer}>
            {/* Date/Time Picker */}
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
                    setWorkoutDate(selectedDate);
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
                    setWorkoutDate(selectedTime);
                  }
                }}
              />
            )}

            {/* Exercise Sets */}
            {Object.entries(exerciseGroups).map(([exerciseName, exerciseSets]) => (
              <View key={exerciseName} style={styles.exerciseSection}>
                <Text style={styles.exerciseName}>{exerciseName}</Text>
                {exerciseSets.map((set, idx) => {
                  const globalIndex = sets.findIndex(s => s.id === set.id);
                  return (
                    <View key={set.id} style={styles.setRow}>
                      <Text style={styles.setLabel}>Set {set.set_index}</Text>
                      <TextInput
                        style={styles.setInput}
                        value={set.weight > 0 ? set.weight.toString() : ''}
                        onChangeText={(val) => updateSet(globalIndex, 'weight', parseFloat(val) || 0)}
                        placeholder="lbs"
                        placeholderTextColor={colors.textMuted}
                        keyboardType="numeric"
                      />
                      <Text style={styles.setX}>×</Text>
                      <TextInput
                        style={styles.setInput}
                        value={set.reps > 0 ? set.reps.toString() : ''}
                        onChangeText={(val) => updateSet(globalIndex, 'reps', parseInt(val) || 0)}
                        placeholder="reps"
                        placeholderTextColor={colors.textMuted}
                        keyboardType="numeric"
                      />
                      <Text style={styles.rpeLabel}>RPE</Text>
                      <TextInput
                        style={styles.rpeInput}
                        value={set.rpe ? set.rpe.toString() : ''}
                        onChangeText={(val) => updateSet(globalIndex, 'rpe', parseInt(val) || 7)}
                        keyboardType="numeric"
                        placeholderTextColor={colors.textMuted}
                      />
                    </View>
                  );
                })}
              </View>
            ))}

            {/* Action Buttons */}
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={[styles.button, styles.primaryButton]}
                onPress={handleSave}
                disabled={loading}
              >
                {loading ? (
                  <ActivityIndicator color={colors.text} />
                ) : (
                  <Text style={styles.buttonText}>Save Changes</Text>
                )}
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.button, styles.secondaryButton]}
                onPress={onClose}
                disabled={loading}
              >
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
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
  formContainer: {
    gap: spacing.md,
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
  exerciseSection: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  exerciseName: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  label: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  setRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.background,
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
    backgroundColor: colors.surface,
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
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
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
});

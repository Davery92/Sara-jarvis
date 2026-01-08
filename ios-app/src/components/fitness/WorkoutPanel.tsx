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

interface WorkoutPanelProps {
  onCollapse?: () => void;
  isCollapsed?: boolean;
}

export default function WorkoutPanel({ onCollapse, isCollapsed = false }: WorkoutPanelProps) {
  const {
    session,
    isActive,
    currentExercise,
    currentSetNumber,
    progress,
    restTimer,
    logSet,
    skipExercise,
    startRestTimer,
    stopRestTimer,
    completeWorkout,
  } = useWorkoutMode();

  const [lastFeedback, setLastFeedback] = useState<string | null>(null);
  const [isLogging, setIsLogging] = useState(false);
  const [timerPulse] = useState(new Animated.Value(1));
  const [customWeight, setCustomWeight] = useState<string>('');
  const [customReps, setCustomReps] = useState<string>('');

  // Update custom weight/reps when exercise changes
  useEffect(() => {
    if (currentExercise) {
      setCustomWeight(currentExercise.suggested_weight?.toString() || '');
      // Parse target reps (e.g., "8-10" -> "8")
      const targetReps = currentExercise.reps?.toString().split('-')[0] || '';
      setCustomReps(targetReps);
    }
  }, [currentExercise?.name, session?.current_exercise_index]);

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

  const handleLogSet = async (feeling?: 'light' | 'moderate' | 'hard') => {
    Keyboard.dismiss();
    setIsLogging(true);
    try {
      const weight = customWeight ? parseFloat(customWeight) : currentExercise?.suggested_weight;
      const reps = customReps ? parseInt(customReps, 10) : undefined;
      console.log('[WorkoutPanel] Logging set:', { feeling, weight, reps });
      const result = await logSet({
        rpe_feeling: feeling,
        weight,
        reps,
      });
      console.log('[WorkoutPanel] Log result:', result);
      if (result.coaching_feedback) {
        setLastFeedback(result.coaching_feedback);
        // Clear feedback after 5 seconds
        setTimeout(() => setLastFeedback(null), 5000);
      }
      // Start rest timer after logging
      if (result.success) {
        const isCompound = ['squat', 'deadlift', 'bench', 'press', 'row'].some(
          kw => currentExercise?.name.toLowerCase().includes(kw)
        );
        startRestTimer(isCompound ? 180 : 90);
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

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const workoutDuration = () => {
    if (!session.started_at) return '0:00';
    const start = new Date(session.started_at).getTime();
    const elapsed = Math.floor((Date.now() - start) / 1000);
    return formatTime(elapsed);
  };

  if (isCollapsed) {
    return (
      <TouchableOpacity style={styles.collapsedPanel} onPress={onCollapse}>
        <View style={styles.collapsedContent}>
          <Ionicons name="barbell" size={18} color="#fff" />
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

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.workoutName}>
            {session.workout_snapshot?.template_name || 'Workout'}
          </Text>
          <Text style={styles.duration}>{workoutDuration()}</Text>
        </View>
        <View style={styles.headerRight}>
          <Text style={styles.progressText}>
            {progress.completed}/{progress.total} sets
          </Text>
          <TouchableOpacity onPress={onCollapse} style={styles.collapseButton}>
            <Ionicons name="chevron-down" size={20} color="#888" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Progress Bar */}
      <View style={styles.progressContainer}>
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${progress.percentage}%` }]} />
        </View>
      </View>

      {/* Rest Timer */}
      {restTimer?.is_active && restTimer.remaining_seconds !== undefined && (
        <Animated.View style={[styles.restTimerContainer, { transform: [{ scale: timerPulse }] }]}>
          <Ionicons name="time-outline" size={20} color="#3b82f6" />
          <Text style={styles.restTimerText}>
            Rest: {formatTime(restTimer.remaining_seconds)}
          </Text>
          <TouchableOpacity onPress={stopRestTimer} style={styles.skipRestButton}>
            <Text style={styles.skipRestText}>Skip</Text>
          </TouchableOpacity>
        </Animated.View>
      )}

      {/* Current Exercise */}
      {currentExercise && (
        <View style={styles.currentExercise}>
          <View style={styles.exerciseHeader}>
            <Text style={styles.exerciseName}>{currentExercise.name}</Text>
            <Text style={styles.setInfo}>
              Set {currentSetNumber} of {currentExercise.sets}
            </Text>
          </View>

          <View style={styles.targetInfo}>
            <View style={styles.targetItem}>
              <Text style={styles.targetLabel}>Weight</Text>
              <View style={styles.inputRow}>
                <TouchableOpacity
                  style={styles.adjustButton}
                  onPress={() => {
                    const current = parseFloat(customWeight) || 0;
                    setCustomWeight(Math.max(0, current - 5).toString());
                  }}
                >
                  <Text style={styles.adjustButtonText}>-5</Text>
                </TouchableOpacity>
                <View style={styles.inputContainer}>
                  <TextInput
                    style={styles.input}
                    value={customWeight}
                    onChangeText={setCustomWeight}
                    keyboardType="numeric"
                    placeholder={currentExercise.suggested_weight?.toString() || '0'}
                    placeholderTextColor="#666"
                    selectTextOnFocus
                    returnKeyType="done"
                    onSubmitEditing={() => Keyboard.dismiss()}
                  />
                  <Text style={styles.inputUnit}>lbs</Text>
                </View>
                <TouchableOpacity
                  style={styles.adjustButton}
                  onPress={() => {
                    const current = parseFloat(customWeight) || 0;
                    setCustomWeight((current + 5).toString());
                  }}
                >
                  <Text style={styles.adjustButtonText}>+5</Text>
                </TouchableOpacity>
              </View>
            </View>
            <View style={styles.targetItem}>
              <Text style={styles.targetLabel}>Reps</Text>
              <View style={styles.inputContainer}>
                <TextInput
                  style={styles.input}
                  value={customReps}
                  onChangeText={setCustomReps}
                  keyboardType="numeric"
                  placeholder={currentExercise.reps?.toString().split('-')[0] || '8'}
                  placeholderTextColor="#666"
                  selectTextOnFocus
                  returnKeyType="done"
                  onSubmitEditing={() => Keyboard.dismiss()}
                />
              </View>
            </View>
            <View style={styles.targetItem}>
              <Text style={styles.targetLabel}>Target RPE</Text>
              <Text style={styles.targetValue}>{currentExercise.rpe_target || '7-8'}</Text>
            </View>
          </View>

          {currentExercise.progression_note && (
            <View style={styles.progressionNote}>
              <Ionicons name="trending-up" size={14} color="#22c55e" />
              <Text style={styles.progressionNoteText}>{currentExercise.progression_note}</Text>
            </View>
          )}

          {currentExercise.last_session?.weights?.length > 0 && (
            <View style={styles.lastSession}>
              <Text style={styles.lastSessionLabel}>Last time:</Text>
              <Text style={styles.lastSessionValue}>
                {currentExercise.last_session.weights[0]}lbs x{' '}
                {currentExercise.last_session.reps?.join(', ') || '?'} reps
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Coaching Feedback */}
      {lastFeedback && (
        <View style={styles.feedbackContainer}>
          <Ionicons name="chatbubble-ellipses" size={16} color="#8b5cf6" />
          <Text style={styles.feedbackText}>{lastFeedback}</Text>
        </View>
      )}

      {/* Quick Actions */}
      <View style={styles.quickActions}>
        <TouchableOpacity
          style={[styles.actionButton, styles.lightButton]}
          onPress={() => handleLogSet('light')}
          disabled={isLogging}
        >
          <Text style={styles.actionButtonText}>Felt Light</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionButton, styles.doneButton]}
          onPress={() => handleLogSet('moderate')}
          disabled={isLogging}
        >
          <Text style={[styles.actionButtonText, styles.doneButtonText]}>Done</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionButton, styles.hardButton]}
          onPress={() => handleLogSet('hard')}
          disabled={isLogging}
        >
          <Text style={styles.actionButtonText}>Felt Hard</Text>
        </TouchableOpacity>
      </View>

      {/* Secondary Actions */}
      <View style={styles.secondaryActions}>
        <TouchableOpacity style={styles.secondaryButton} onPress={skipExercise}>
          <Ionicons name="play-skip-forward" size={16} color="#888" />
          <Text style={styles.secondaryButtonText}>Skip Exercise</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.secondaryButton}
          onPress={() => startRestTimer(120)}
        >
          <Ionicons name="time" size={16} color="#888" />
          <Text style={styles.secondaryButtonText}>Rest Timer</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.secondaryButton, styles.completeButton]}
          onPress={completeWorkout}
        >
          <Ionicons name="checkmark-circle" size={16} color="#22c55e" />
          <Text style={[styles.secondaryButtonText, { color: '#22c55e' }]}>Finish</Text>
        </TouchableOpacity>
      </View>

      {/* Exercise List */}
      <ScrollView style={styles.exerciseList} showsVerticalScrollIndicator={false}>
        {(session.workout_snapshot?.exercises || []).map((exercise, index) => {
          const isCurrent = index === (session.current_exercise_index || 0);
          const isCompleted = index < (session.current_exercise_index || 0);
          return (
            <View
              key={`${exercise.name}-${index}`}
              style={[
                styles.exerciseListItem,
                isCurrent && styles.currentListItem,
                isCompleted && styles.completedListItem,
              ]}
            >
              <View style={styles.exerciseListIcon}>
                {isCompleted ? (
                  <Ionicons name="checkmark-circle" size={18} color="#22c55e" />
                ) : isCurrent ? (
                  <Ionicons name="radio-button-on" size={18} color="#3b82f6" />
                ) : (
                  <Ionicons name="ellipse-outline" size={18} color="#555" />
                )}
              </View>
              <View style={styles.exerciseListContent}>
                <Text
                  style={[
                    styles.exerciseListName,
                    isCompleted && styles.completedText,
                  ]}
                >
                  {exercise.name}
                </Text>
                <Text style={styles.exerciseListSets}>
                  {exercise.sets} x {exercise.reps}
                </Text>
              </View>
              {exercise.suggested_weight && (
                <Text style={styles.exerciseListWeight}>
                  {exercise.suggested_weight} lbs
                </Text>
              )}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#1a1a1a',
    borderRadius: 16,
    padding: 16,
    margin: 8,
    maxHeight: '60%',
  },
  collapsedPanel: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 12,
    margin: 8,
  },
  collapsedContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  collapsedText: {
    color: '#fff',
    flex: 1,
  },
  miniTimer: {
    backgroundColor: '#3b82f6',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  miniTimerText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  workoutName: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  },
  duration: {
    color: '#888',
    fontSize: 14,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  progressText: {
    color: '#888',
    fontSize: 14,
  },
  collapseButton: {
    padding: 4,
  },
  progressContainer: {
    marginBottom: 16,
  },
  progressBar: {
    height: 4,
    backgroundColor: '#333',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#3b82f6',
    borderRadius: 2,
  },
  restTimerContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1e3a5f',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginBottom: 16,
    gap: 8,
  },
  restTimerText: {
    color: '#3b82f6',
    fontSize: 24,
    fontWeight: '700',
    flex: 1,
    textAlign: 'center',
  },
  skipRestButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: '#333',
    borderRadius: 8,
  },
  skipRestText: {
    color: '#888',
    fontSize: 12,
  },
  currentExercise: {
    backgroundColor: '#222',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  exerciseHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  exerciseName: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    flex: 1,
  },
  setInfo: {
    color: '#3b82f6',
    fontSize: 14,
    fontWeight: '600',
  },
  targetInfo: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 12,
  },
  targetItem: {
    alignItems: 'center',
  },
  targetLabel: {
    color: '#666',
    fontSize: 12,
    marginBottom: 4,
  },
  targetValue: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#333',
    borderRadius: 8,
    paddingHorizontal: 8,
    minWidth: 80,
  },
  input: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
    paddingVertical: 6,
    minWidth: 50,
  },
  inputUnit: {
    color: '#888',
    fontSize: 14,
    marginLeft: 2,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  adjustButton: {
    backgroundColor: '#444',
    paddingHorizontal: 8,
    paddingVertical: 8,
    borderRadius: 6,
  },
  adjustButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  progressionNote: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#1a2e1a',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    marginBottom: 8,
  },
  progressionNoteText: {
    color: '#22c55e',
    fontSize: 12,
  },
  lastSession: {
    flexDirection: 'row',
    gap: 6,
  },
  lastSessionLabel: {
    color: '#666',
    fontSize: 12,
  },
  lastSessionValue: {
    color: '#888',
    fontSize: 12,
  },
  feedbackContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#2d1f4a',
    padding: 12,
    borderRadius: 10,
    marginBottom: 12,
  },
  feedbackText: {
    color: '#c4b5fd',
    fontSize: 14,
    flex: 1,
  },
  quickActions: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  actionButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: 'center',
  },
  lightButton: {
    backgroundColor: '#1e3a2e',
  },
  doneButton: {
    backgroundColor: '#3b82f6',
  },
  hardButton: {
    backgroundColor: '#3a1e1e',
  },
  actionButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  doneButtonText: {
    color: '#fff',
  },
  secondaryActions: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 16,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#333',
  },
  secondaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  secondaryButtonText: {
    color: '#888',
    fontSize: 12,
  },
  completeButton: {},
  exerciseList: {
    maxHeight: 150,
  },
  exerciseListItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: 8,
    marginBottom: 4,
  },
  currentListItem: {
    backgroundColor: '#1e3a5f',
  },
  completedListItem: {
    opacity: 0.6,
  },
  exerciseListIcon: {
    marginRight: 10,
  },
  exerciseListContent: {
    flex: 1,
  },
  exerciseListName: {
    color: '#fff',
    fontSize: 14,
  },
  completedText: {
    textDecorationLine: 'line-through',
    color: '#666',
  },
  exerciseListSets: {
    color: '#666',
    fontSize: 12,
  },
  exerciseListWeight: {
    color: '#888',
    fontSize: 12,
  },
});

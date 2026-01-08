import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  TouchableOpacity,
  Alert,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import ChatScreen from '../chat/ChatScreen';
import WorkoutPanel from '../../components/fitness/WorkoutPanel';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { RootStackParamList } from '../../types/navigation';

type WorkoutModeScreenNavigationProp = NativeStackNavigationProp<RootStackParamList, 'WorkoutMode'>;
type WorkoutModeScreenRouteProp = RouteProp<RootStackParamList, 'WorkoutMode'>;

export default function WorkoutModeScreen() {
  const navigation = useNavigation<WorkoutModeScreenNavigationProp>();
  const route = useRoute<WorkoutModeScreenRouteProp>();
  const { session, isActive, isLoading, abandonWorkout, completeWorkout } = useWorkoutMode();
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [workoutSummary, setWorkoutSummary] = useState<any>(null);

  // Handle back button - confirm before abandoning workout
  useEffect(() => {
    const unsubscribe = navigation.addListener('beforeRemove', (e) => {
      if (!isActive) return;

      e.preventDefault();

      Alert.alert(
        'End Workout?',
        'Do you want to complete or abandon this workout?',
        [
          { text: 'Continue Workout', style: 'cancel' },
          {
            text: 'Complete',
            onPress: async () => {
              const result = await completeWorkout();
              setWorkoutSummary(result.summary);
              setShowSummary(true);
            },
          },
          {
            text: 'Abandon',
            style: 'destructive',
            onPress: async () => {
              await abandonWorkout();
              navigation.dispatch(e.data.action);
            },
          },
        ]
      );
    });

    return unsubscribe;
  }, [navigation, isActive, completeWorkout, abandonWorkout]);

  // If loading, show a loading state
  if (isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.noSessionContainer}>
          <Text style={styles.noSessionText}>Loading workout...</Text>
        </View>
      </SafeAreaView>
    );
  }

  // If workout ended, show summary
  if (showSummary && workoutSummary) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.summaryContainer}>
          <Ionicons name="trophy" size={64} color="#22c55e" />
          <Text style={styles.summaryTitle}>Workout Complete!</Text>

          <View style={styles.summaryStats}>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{workoutSummary.duration_minutes || 0}</Text>
              <Text style={styles.statLabel}>Minutes</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{workoutSummary.total_sets || 0}</Text>
              <Text style={styles.statLabel}>Sets</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>
                {Math.round((workoutSummary.total_volume || 0) / 1000)}k
              </Text>
              <Text style={styles.statLabel}>lbs Volume</Text>
            </View>
          </View>

          <TouchableOpacity
            style={styles.doneButton}
            onPress={() => navigation.goBack()}
          >
            <Text style={styles.doneButtonText}>Done</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // If no active session, prompt to start one
  if (!isActive) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.noSessionContainer}>
          <Ionicons name="barbell-outline" size={64} color="#555" />
          <Text style={styles.noSessionText}>No active workout</Text>
          <Text style={styles.noSessionSubtext}>
            Start a workout from the Fitness tab to begin training with Sara
          </Text>
          <TouchableOpacity
            style={styles.goBackButton}
            onPress={() => navigation.goBack()}
          >
            <Text style={styles.goBackButtonText}>Go to Fitness</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Ionicons name="chevron-back" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {session?.workout_snapshot?.template_name || 'Workout'}
          </Text>
          <TouchableOpacity
            onPress={() => setIsPanelCollapsed(!isPanelCollapsed)}
          >
            <Ionicons
              name={isPanelCollapsed ? 'chevron-up' : 'chevron-down'}
              size={24}
              color="#fff"
            />
          </TouchableOpacity>
        </View>

        {/* Workout Panel */}
        <WorkoutPanel
          isCollapsed={isPanelCollapsed}
          onCollapse={() => setIsPanelCollapsed(!isPanelCollapsed)}
        />

        {/* Chat Interface */}
        <View style={styles.chatContainer}>
          <ChatScreen isEmbedded={true} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#222',
  },
  headerTitle: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '600',
  },
  chatContainer: {
    flex: 1,
  },
  noSessionContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  noSessionText: {
    color: '#888',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 16,
  },
  noSessionSubtext: {
    color: '#555',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 8,
    marginHorizontal: 32,
  },
  goBackButton: {
    marginTop: 24,
    paddingHorizontal: 24,
    paddingVertical: 12,
    backgroundColor: '#3b82f6',
    borderRadius: 8,
  },
  goBackButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  summaryContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  summaryTitle: {
    color: '#fff',
    fontSize: 24,
    fontWeight: '700',
    marginTop: 16,
  },
  summaryStats: {
    flexDirection: 'row',
    marginTop: 32,
    gap: 32,
  },
  statItem: {
    alignItems: 'center',
  },
  statValue: {
    color: '#fff',
    fontSize: 32,
    fontWeight: '700',
  },
  statLabel: {
    color: '#888',
    fontSize: 14,
    marginTop: 4,
  },
  doneButton: {
    marginTop: 48,
    paddingHorizontal: 48,
    paddingVertical: 14,
    backgroundColor: '#22c55e',
    borderRadius: 10,
  },
  doneButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});

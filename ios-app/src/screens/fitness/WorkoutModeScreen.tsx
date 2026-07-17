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
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

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
          <Ionicons name="trophy" size={64} color={colors.success} />
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

          {/* Heart rate / calories melded from the Apple Watch workout, if it
              overlapped this session and has synced. */}
          {workoutSummary.heart_rate && (
            <View style={{ alignItems: 'center', marginTop: 4 }}>
              <Text style={{ color: colors.textSecondary, fontSize: 12, marginBottom: 8 }}>
                ❤️ From your watch · {workoutSummary.heart_rate.activity}
              </Text>
              <View style={styles.summaryStats}>
                {workoutSummary.heart_rate.avg_heart_rate ? (
                  <View style={styles.statItem}>
                    <Text style={styles.statValue}>{workoutSummary.heart_rate.avg_heart_rate}</Text>
                    <Text style={styles.statLabel}>Avg BPM</Text>
                  </View>
                ) : null}
                {workoutSummary.heart_rate.max_heart_rate ? (
                  <View style={styles.statItem}>
                    <Text style={styles.statValue}>{workoutSummary.heart_rate.max_heart_rate}</Text>
                    <Text style={styles.statLabel}>Max BPM</Text>
                  </View>
                ) : null}
                {workoutSummary.heart_rate.calories ? (
                  <View style={styles.statItem}>
                    <Text style={styles.statValue}>{workoutSummary.heart_rate.calories}</Text>
                    <Text style={styles.statLabel}>Cal</Text>
                  </View>
                ) : null}
              </View>
            </View>
          )}

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
          <Ionicons name="barbell-outline" size={64} color={colors.textMuted} />
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
          <TouchableOpacity onPress={() => navigation.goBack()} hitSlop={8}>
            <Ionicons name="chevron-back" size={24} color={colors.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle} numberOfLines={1}>
            {session?.workout_snapshot?.template_name || 'Workout'}
          </Text>
          <TouchableOpacity onPress={() => setIsPanelCollapsed(!isPanelCollapsed)} hitSlop={8}>
            <Ionicons
              name={isPanelCollapsed ? 'chatbubble-ellipses' : 'ellipsis-vertical'}
              size={22}
              color={colors.text}
            />
          </TouchableOpacity>
        </View>

        {/* Workout Panel — fills the screen while capturing; the ⋮ collapses it to
            a bar and reveals Sara's coaching chat. */}
        <WorkoutPanel
          isCollapsed={isPanelCollapsed}
          onCollapse={() => setIsPanelCollapsed(!isPanelCollapsed)}
          onFinish={async () => {
            const result = await completeWorkout();
            setWorkoutSummary(result.summary);
            setShowSummary(true);
          }}
        />

        {/* Chat only appears once the workout panel is collapsed */}
        {isPanelCollapsed && (
          <View style={styles.chatContainer}>
            <ChatScreen isEmbedded={true} />
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    marginHorizontal: spacing.sm,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    letterSpacing: 0.2,
  },
  chatContainer: {
    flex: 1,
  },
  noSessionContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  noSessionText: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
    marginTop: spacing.md,
  },
  noSessionSubtext: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    lineHeight: 20,
    marginTop: spacing.sm,
    marginHorizontal: spacing.xl,
  },
  goBackButton: {
    marginTop: spacing.lg,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 4,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
  },
  goBackButtonText: {
    color: colors.background,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.bold,
  },
  summaryContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  summaryTitle: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
    marginTop: spacing.md,
  },
  summaryStats: {
    flexDirection: 'row',
    marginTop: spacing.xl,
    gap: spacing.sm,
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.xl,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  statValue: {
    color: colors.accent,
    fontSize: fontSizes.xxxl,
    fontWeight: fontWeights.bold,
  },
  statLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  doneButton: {
    marginTop: spacing.xxl,
    alignSelf: 'stretch',
    alignItems: 'center',
    paddingVertical: spacing.md,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
  },
  doneButtonText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
  },
});

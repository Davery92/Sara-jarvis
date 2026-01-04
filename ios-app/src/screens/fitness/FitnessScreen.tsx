import React, { useState, useEffect } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import {
  fitnessService,
  FoodLog,
  WorkoutLog,
  WorkoutSession,
  RecoveryLog,
  HabitStreak,
  Phase,
  WorkoutTemplate,
  NutritionGoals,
} from '../../services/fitness';
import FoodLogItem from '../../components/fitness/FoodLogItem';
import WorkoutSessionItem from '../../components/fitness/WorkoutSessionItem';
import RecoveryCard from '../../components/fitness/RecoveryCard';
import WorkoutLogModal from '../../components/fitness/WorkoutLogModal';
import WorkoutEditModal from '../../components/fitness/WorkoutEditModal';
import FoodLogModal from '../../components/fitness/FoodLogModal';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

type Props = MainTabScreenProps<'Fitness'>;

type ViewMode = 'dashboard' | 'nutrition' | 'workout' | 'recovery' | 'habits' | 'programs';

export default function FitnessScreen({ navigation }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showWorkoutModal, setShowWorkoutModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedWorkout, setSelectedWorkout] = useState<WorkoutSession | null>(null);
  const [showFoodModal, setShowFoodModal] = useState(false);
  const [selectedMealType, setSelectedMealType] = useState('snack');
  const [selectedDate, setSelectedDate] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  });

  // Data states
  const [foodLogs, setFoodLogs] = useState<FoodLog[]>([]);
  const [workoutLogs, setWorkoutLogs] = useState<WorkoutSession[]>([]);
  const [recoveryLogs, setRecoveryLogs] = useState<RecoveryLog[]>([]);
  const [habitStreaks, setHabitStreaks] = useState<HabitStreak[]>([]);
  const [dailySummary, setDailySummary] = useState<any>(null);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [templates, setTemplates] = useState<WorkoutTemplate[]>([]);
  const [nutritionGoals, setNutritionGoals] = useState<NutritionGoals | null>(null);
  const [activePhase, setActivePhase] = useState<Phase | null>(null);

  useEffect(() => {
    loadData();
    loadNutritionGoalsWithPhase();
  }, []);

  const loadNutritionGoalsWithPhase = async () => {
    try {
      // First load base goals
      const goals = await fitnessService.getNutritionGoals();
      setNutritionGoals(goals);

      // Then check for active phase to override
      try {
        const activePhases = await fitnessService.getActivePhases();
        if (activePhases.phases && activePhases.phases.length > 0) {
          const phase = activePhases.phases[0];
          setActivePhase(phase);
          // Override goals with phase targets if they exist
          setNutritionGoals(prev => ({
            calories: phase.calories_target || prev?.calories || 2000,
            protein: phase.protein_target || prev?.protein || 150,
            carbs: phase.carbs_target || prev?.carbs || 200,
            fats: phase.fat_target || prev?.fats || 70,
          }));
        }
      } catch (phaseError) {
        console.error('Failed to load active phase:', phaseError);
      }
    } catch (error) {
      console.error('Failed to load nutrition goals:', error);
    }
  };

  // Helper function to convert UTC timestamp to local date string (YYYY-MM-DD)
  const getLocalDateString = (utcTimestamp: string): string => {
    const date = new Date(utcTimestamp);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const loadData = async () => {
    try {
      setLoading(true);
      // Use local date helper to avoid UTC timezone issues
      const today = getLocalDateString(new Date().toISOString());
      const weekAgoDate = new Date();
      weekAgoDate.setDate(weekAgoDate.getDate() - 7);
      const weekAgo = getLocalDateString(weekAgoDate.toISOString());

      // Load food logs for the last week to support date browsing
      const food = await fitnessService.getFoodLogs(weekAgo, today).catch(() => []);
      const workouts = await fitnessService.getWorkoutSessions(weekAgo, today).catch(() => []);
      const recovery = await fitnessService.getRecoveryLogs(weekAgo, today).catch(() => []);
      const streaks = await fitnessService.getHabitStreaks().catch(() => []);
      const summary = await fitnessService.getDailySummary(today).catch(() => null);
      const phasesData = await fitnessService.getPhases().catch(() => ({ phases: [] }));
      const templatesData = await fitnessService.getTemplates().catch(() => ({ templates: [] }));

      setFoodLogs(food);
      setWorkoutLogs(workouts);
      setRecoveryLogs(recovery);
      setHabitStreaks(streaks);
      setDailySummary(summary);
      setPhases(phasesData.phases);
      setTemplates(templatesData.templates);
    } catch (error) {
      console.error('Failed to load fitness data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  // Food logging
  const handleLogFood = (mealType: string = 'snack') => {
    setSelectedMealType(mealType);
    setShowFoodModal(true);
  };

  const handleEditNutritionGoals = () => {
    navigation.navigate('NutritionGoalsForm', {
      onSave: () => {
        loadNutritionGoalsWithPhase();
      },
    });
  };

  const handleDeleteFood = (log: FoodLog) => {
    Alert.alert(
      'Delete Food Log',
      `Delete ${log.food_name}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await fitnessService.deleteFoodLog(log.meal_log_id);
              loadData();
            } catch (error) {
              console.error('Failed to delete food log:', error);
              Alert.alert('Error', 'Failed to delete food log');
            }
          },
        },
      ]
    );
  };

  // Workout logging
  const handleLogWorkout = () => {
    setShowWorkoutModal(true);
  };

  const handleLongPressWorkout = (session: WorkoutSession) => {
    Alert.alert(
      'Workout Options',
      `${session.title || 'Workout'} - ${session.session_date || session.created_at}`,
      [
        {
          text: 'Edit',
          onPress: () => handleEditWorkout(session),
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              // session.id is a UUID string, pass it directly (don't parseInt)
              await fitnessService.deleteWorkoutSession(session.id);
              loadData();
            } catch (error) {
              console.error('Delete workout error:', error);
              Alert.alert('Error', 'Failed to delete workout');
            }
          },
        },
        { text: 'Cancel', style: 'cancel' },
      ]
    );
  };

  const handleViewWorkout = (session: WorkoutSession) => {
    // Show read-only view with workout details
    const exerciseGroups: { [key: string]: any[] } = {};
    session.exercises.forEach((set) => {
      if (!exerciseGroups[set.exercise_id]) {
        exerciseGroups[set.exercise_id] = [];
      }
      exerciseGroups[set.exercise_id].push(set);
    });

    const details = Object.entries(exerciseGroups)
      .map(([exercise, sets]) => {
        const setList = sets
          .map((s: any) => `Set ${s.set_index}: ${s.weight}lb × ${s.reps} reps @ RPE ${s.rpe || 'N/A'}`)
          .join('\n');
        return `${exercise}:\n${setList}`;
      })
      .join('\n\n');

    Alert.alert(session.title || 'Workout Details', details, [{ text: 'OK' }]);
  };

  const handleEditWorkout = (session: WorkoutSession) => {
    setSelectedWorkout(session);
    setShowEditModal(true);
  };

  // Recovery logging
  const handleLogRecovery = () => {
    navigation.navigate('RecoveryForm' as any, {
      onSave: loadData,
    });
  };

  const handleEditRecovery = (log: RecoveryLog) => {
    navigation.navigate('RecoveryForm' as any, {
      log,
      onSave: loadData,
    });
  };

  const handleDeleteRecovery = (log: RecoveryLog) => {
    Alert.alert(
      'Delete Recovery Log',
      `Delete recovery log from ${log.log_date}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await fitnessService.deleteRecoveryLog(log.id);
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete recovery log');
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const renderDashboard = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      {/* Daily Summary */}
      <View style={styles.summaryCard}>
        <Text style={styles.summaryTitle}>Today's Summary</Text>
        <View style={styles.summaryStats}>
          <View style={styles.summaryStatItem}>
            <Text style={styles.summaryStatValue}>
              {(() => {
                const today = new Date();
                const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
                const todaysFoods = (foodLogs || []).filter(log => log.logged_at && getLocalDateString(log.logged_at) === todayStr);
                return Math.round(todaysFoods.reduce((sum, log) => sum + (log.calories || 0), 0));
              })()}
            </Text>
            <Text style={styles.summaryStatLabel}>Calories</Text>
          </View>
          <View style={styles.summaryStatItem}>
            <Text style={styles.summaryStatValue}>
              {(() => {
                const today = new Date();
                const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
                return (workoutLogs || []).filter(log => log.logged_at && getLocalDateString(log.logged_at) === todayStr).length;
              })()}
            </Text>
            <Text style={styles.summaryStatLabel}>Workouts</Text>
          </View>
          <View style={styles.summaryStatItem}>
            <Text style={styles.summaryStatValue}>
              {(() => {
                const today = new Date();
                const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
                return (foodLogs || []).filter(log => log.logged_at && getLocalDateString(log.logged_at) === todayStr).length;
              })()}
            </Text>
            <Text style={styles.summaryStatLabel}>Meals</Text>
          </View>
        </View>
      </View>

      {/* Quick Actions */}
      <View style={styles.quickActions}>
        <TouchableOpacity style={styles.quickActionButton} onPress={handleLogFood}>
          <Text style={styles.quickActionEmoji}>🍽️</Text>
          <Text style={styles.quickActionText}>Log Food</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.quickActionButton} onPress={handleLogWorkout}>
          <Text style={styles.quickActionEmoji}>💪</Text>
          <Text style={styles.quickActionText}>Log Workout</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.quickActionButton} onPress={handleLogRecovery}>
          <Text style={styles.quickActionEmoji}>💤</Text>
          <Text style={styles.quickActionText}>Log Recovery</Text>
        </TouchableOpacity>
      </View>

      {/* Recent Activity Sections */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Recent Food ({foodLogs.length})</Text>
          <TouchableOpacity onPress={() => setViewMode('food')}>
            <Text style={styles.seeAllText}>See All</Text>
          </TouchableOpacity>
        </View>
        {(foodLogs || []).slice(0, 3).map((log) => (
          <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
        ))}
        {(!foodLogs || foodLogs.length === 0) && (
          <Text style={styles.emptyText}>No food logs yet</Text>
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Recent Workouts ({(workoutLogs || []).length})</Text>
          <TouchableOpacity onPress={() => setViewMode('workout')}>
            <Text style={styles.seeAllText}>See All</Text>
          </TouchableOpacity>
        </View>
        {(workoutLogs || []).slice(0, 3).map((session) => (
          <WorkoutSessionItem
            key={session.id}
            session={session}
            onPress={handleViewWorkout}
            onLongPress={handleLongPressWorkout}
          />
        ))}
        {(!workoutLogs || workoutLogs.length === 0) && (
          <Text style={styles.emptyText}>No workouts logged yet</Text>
        )}
      </View>

      {recoveryLogs.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Latest Recovery</Text>
          <RecoveryCard
            log={recoveryLogs[0]}
            onPress={handleEditRecovery}
            onLongPress={handleDeleteRecovery}
          />
        </View>
      )}

      {/* Habit Streaks */}
      {habitStreaks.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Habit Streaks</Text>
          {habitStreaks.map((streak, index) => (
            <View key={index} style={styles.habitCard}>
              <Text style={styles.habitName}>{streak.habit_name}</Text>
              <View style={styles.habitStats}>
                <View style={styles.habitStat}>
                  <Text style={styles.habitStatValue}>🔥 {streak.current_streak}</Text>
                  <Text style={styles.habitStatLabel}>Current</Text>
                </View>
                <View style={styles.habitStat}>
                  <Text style={styles.habitStatValue}>⭐ {streak.longest_streak}</Text>
                  <Text style={styles.habitStatLabel}>Best</Text>
                </View>
                <View style={styles.habitStat}>
                  <Text style={styles.habitStatValue}>{Math.round(streak.completion_rate * 100)}%</Text>
                  <Text style={styles.habitStatLabel}>Rate</Text>
                </View>
              </View>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );

  const renderFoodView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('dashboard')}>
          <Text style={styles.backButton}>← Back</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.addButton} onPress={handleLogFood}>
          <Text style={styles.addButtonText}>+ Log Food</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.sectionTitle}>Food Logs ({foodLogs.length})</Text>
      {foodLogs.map((log) => (
        <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
      ))}
      {foodLogs.length === 0 && (
        <Text style={styles.emptyText}>No food logs yet. Tap + to add one!</Text>
      )}
    </ScrollView>
  );

  const renderWorkoutView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('dashboard')}>
          <Text style={styles.backButton}>← Back</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.addButton} onPress={handleLogWorkout}>
          <Text style={styles.addButtonText}>+ Log Workout</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.sectionTitle}>Workout Logs ({workoutLogs.length})</Text>
      {workoutLogs.map((session) => (
        <WorkoutSessionItem
          key={session.id}
          session={session}
          onPress={handleViewWorkout}
          onLongPress={handleLongPressWorkout}
        />
      ))}
      {workoutLogs.length === 0 && (
        <Text style={styles.emptyText}>No workouts logged yet. Tap + to add one!</Text>
      )}
    </ScrollView>
  );

  const renderProgramsView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('dashboard')}>
          <Text style={styles.backButton}>← Back</Text>
        </TouchableOpacity>
      </View>

      {/* Phases Section */}
      <Text style={styles.sectionTitle}>Training Phases ({phases.length})</Text>
      {phases.map((phase) => (
        <TouchableOpacity
          key={phase.id}
          style={styles.habitCard}
          onPress={() => {
            Alert.alert(
              phase.name,
              `Goal: ${phase.goal || 'No goal set'}\n\n` +
              `Dates: ${phase.start_date || 'N/A'} to ${phase.end_date || 'N/A'}\n\n` +
              `Status: ${phase.status}\n\n` +
              `Focus: ${phase.focus_areas?.join(', ') || 'N/A'}`,
              [{ text: 'OK' }]
            );
          }}
          onLongPress={() => {
            Alert.alert(
              phase.name,
              'What would you like to do?',
              [
                { text: 'Cancel', style: 'cancel' },
                {
                  text: 'Edit',
                  onPress: () => {
                    Alert.alert('Coming Soon', 'Phase editing will be available in a future update!');
                  },
                },
                {
                  text: 'Delete',
                  style: 'destructive',
                  onPress: () => {
                    Alert.alert('Coming Soon', 'Phase deletion will be available in a future update!');
                  },
                },
              ]
            );
          }}
        >
          <Text style={styles.habitName}>
            {phase.name} {phase.status === 'active' && '🔥'}
          </Text>
          <Text style={styles.emptyText}>{phase.goal || 'No goal set'}</Text>
          {phase.start_date && phase.end_date && (
            <Text style={styles.emptyText}>
              {phase.start_date} to {phase.end_date}
            </Text>
          )}
          <Text style={styles.emptyText}>Status: {phase.status}</Text>
        </TouchableOpacity>
      ))}
      {phases.length === 0 && (
        <Text style={styles.emptyText}>No training phases yet.</Text>
      )}

      {/* Templates Section */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
        Workout Templates ({templates.length})
      </Text>
      {templates.map((template) => (
        <TouchableOpacity
          key={template.id}
          style={styles.habitCard}
          onPress={() => {
            const exerciseList = template.exercises.map((ex: any, i: number) =>
              `${i + 1}. ${ex.name || ex.exercise_name} - ${ex.sets}x${ex.reps} @ ${ex.weight || 0}lbs`
            ).join('\n');

            Alert.alert(
              template.name,
              `Scheduled: ${template.scheduled_days?.join(', ') || 'Not scheduled'}\n\n` +
              `Exercises (${template.exercises.length}):\n${exerciseList || 'No exercises'}`,
              [{ text: 'OK' }]
            );
          }}
          onLongPress={() => {
            Alert.alert(
              template.name,
              'What would you like to do?',
              [
                { text: 'Cancel', style: 'cancel' },
                {
                  text: 'Edit',
                  onPress: () => {
                    Alert.alert('Coming Soon', 'Template editing will be available in a future update!');
                  },
                },
                {
                  text: 'Delete',
                  style: 'destructive',
                  onPress: () => {
                    Alert.alert('Coming Soon', 'Template deletion will be available in a future update!');
                  },
                },
              ]
            );
          }}
        >
          <Text style={styles.habitName}>{template.name}</Text>
          {template.scheduled_days.length > 0 && (
            <Text style={styles.emptyText}>
              Days: {template.scheduled_days.join(', ')}
            </Text>
          )}
          {template.exercises.length > 0 && (
            <Text style={styles.emptyText}>
              {template.exercises.length} exercises
            </Text>
          )}
        </TouchableOpacity>
      ))}
      {templates.length === 0 && (
        <Text style={styles.emptyText}>No workout templates yet.</Text>
      )}
    </ScrollView>
  );

  const renderRecoveryView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('dashboard')}>
          <Text style={styles.backButton}>← Back</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.addButton} onPress={handleLogRecovery}>
          <Text style={styles.addButtonText}>+ Log Recovery</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.sectionTitle}>Recovery Logs ({recoveryLogs.length})</Text>
      {recoveryLogs.map((log) => (
        <RecoveryCard
          key={log.id}
          log={log}
          onPress={handleEditRecovery}
          onLongPress={handleDeleteRecovery}
        />
      ))}
      {recoveryLogs.length === 0 && (
        <Text style={styles.emptyText}>No recovery logs yet. Tap + to add one!</Text>
      )}
    </ScrollView>
  );

  const renderNutritionView = () => {
    // Calculate selected date's totals from food logs (using LOCAL date comparison)
    console.log('📊 Nutrition view - selectedDate:', selectedDate);
    console.log('📊 Nutrition view - all foodLogs:', foodLogs.map(log => ({ id: log.id, meal_type: log.meal_type, logged_at: log.logged_at, localDate: log.logged_at ? getLocalDateString(log.logged_at) : 'unknown', food_name: log.food_name })));
    const selectedDateFoods = foodLogs.filter(log => log.logged_at && getLocalDateString(log.logged_at) === selectedDate);
    console.log('📊 Nutrition view - filtered foods count:', selectedDateFoods.length);

    const totalCalories = selectedDateFoods.reduce((sum, log) => sum + (log.calories || 0), 0);
    const totalProtein = selectedDateFoods.reduce((sum, log) => sum + (log.protein || 0), 0);
    const totalCarbs = selectedDateFoods.reduce((sum, log) => sum + (log.carbs || 0), 0);
    const totalFat = selectedDateFoods.reduce((sum, log) => sum + (log.fat || 0), 0);

    // Get goals with defaults
    const goalCalories = nutritionGoals?.calories || 2000;
    const goalProtein = nutritionGoals?.protein || 150;
    const goalCarbs = nutritionGoals?.carbs || 200;
    const goalFats = nutritionGoals?.fats || 70;

    // Calculate remaining
    const remainingCalories = goalCalories - totalCalories;
    const remainingProtein = goalProtein - totalProtein;
    const remainingCarbs = goalCarbs - totalCarbs;
    const remainingFat = goalFats - totalFat;

    // Calculate percentages of goal
    const proteinPercent = goalProtein > 0 ? Math.min(Math.round((totalProtein / goalProtein) * 100), 100) : 0;
    const carbsPercent = goalCarbs > 0 ? Math.min(Math.round((totalCarbs / goalCarbs) * 100), 100) : 0;
    const fatPercent = goalFats > 0 ? Math.min(Math.round((totalFat / goalFats) * 100), 100) : 0;

    // Group food logs by meal type for selected date
    const breakfastFoods = selectedDateFoods.filter((log) => log.meal_type === 'breakfast');
    const lunchFoods = selectedDateFoods.filter((log) => log.meal_type === 'lunch');
    const dinnerFoods = selectedDateFoods.filter((log) => log.meal_type === 'dinner');
    const snackFoods = selectedDateFoods.filter((log) => log.meal_type === 'snack');

    return (
      <ScrollView
        style={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        <View style={styles.viewHeader}>
          <TouchableOpacity onPress={() => setViewMode('dashboard')}>
            <Text style={styles.backButton}>← Back</Text>
          </TouchableOpacity>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            <TouchableOpacity style={styles.editButton} onPress={handleEditNutritionGoals}>
              <Text style={styles.editButtonText}>⚙️ Goals</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.addButton} onPress={handleLogFood}>
              <Text style={styles.addButtonText}>+ Log Food</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Date Navigation */}
        <View style={styles.dateNavigator}>
          <TouchableOpacity
            style={styles.dateNavButton}
            onPress={() => {
              // Parse date string and add local timezone offset to avoid timezone issues
              const [year, month, day] = selectedDate.split('-').map(Number);
              const prevDate = new Date(year, month - 1, day - 1);
              const newDateStr = `${prevDate.getFullYear()}-${String(prevDate.getMonth() + 1).padStart(2, '0')}-${String(prevDate.getDate()).padStart(2, '0')}`;
              setSelectedDate(newDateStr);
            }}
          >
            <Text style={styles.dateNavButtonText}>← Prev</Text>
          </TouchableOpacity>

          <View style={styles.dateDisplay}>
            <Text style={styles.dateDisplayText}>
              {(() => {
                const now = new Date();
                const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
                if (selectedDate === today) return 'Today';

                const [year, month, day] = selectedDate.split('-').map(Number);
                const date = new Date(year, month - 1, day);
                return date.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric'
                });
              })()}
            </Text>
          </View>

          <TouchableOpacity
            style={[
              styles.dateNavButton,
              (() => {
                const now = new Date();
                const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
                return selectedDate === today && styles.dateNavButtonDisabled;
              })()
            ]}
            onPress={() => {
              const [year, month, day] = selectedDate.split('-').map(Number);
              const nextDate = new Date(year, month - 1, day + 1);
              const newDateStr = `${nextDate.getFullYear()}-${String(nextDate.getMonth() + 1).padStart(2, '0')}-${String(nextDate.getDate()).padStart(2, '0')}`;

              const now = new Date();
              const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
              if (newDateStr <= today) {
                setSelectedDate(newDateStr);
              }
            }}
            disabled={(() => {
              const now = new Date();
              const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
              return selectedDate === today;
            })()}
          >
            <Text style={[
              styles.dateNavButtonText,
              (() => {
                const now = new Date();
                const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
                return selectedDate === today && styles.dateNavButtonTextDisabled;
              })()
            ]}>Next →</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.todayButton}
            onPress={() => {
              const now = new Date();
              const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
              setSelectedDate(today);
            }}
          >
            <Text style={styles.todayButtonText}>📅</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.sectionTitle}>Nutrition</Text>

        {/* Calorie Card */}
        <View style={styles.habitCard}>
          <Text style={styles.habitName}>📊 Daily Calories</Text>
          <View style={styles.calorieDisplay}>
            <Text style={styles.calorieNumber}>{totalCalories}</Text>
            <Text style={styles.calorieLabel}> / {goalCalories}</Text>
          </View>
          <View style={styles.remainingContainer}>
            <Text style={[styles.remainingText, remainingCalories >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
              {remainingCalories >= 0 ? `${remainingCalories} remaining` : `${Math.abs(remainingCalories)} over`}
            </Text>
          </View>
        </View>

        {/* Macros Breakdown */}
        <View style={styles.habitCard}>
          <Text style={styles.habitName}>🥗 Macronutrients</Text>

          {/* Protein */}
          <View style={styles.macroRow}>
            <View style={styles.macroHeader}>
              <Text style={styles.macroLabel}>Protein</Text>
              <Text style={styles.macroValue}>{Math.round(totalProtein)} / {goalProtein}g</Text>
            </View>
            <View style={styles.macroBar}>
              <View style={[styles.macroBarFill, { width: `${proteinPercent}%`, backgroundColor: '#FF6B6B' }]} />
            </View>
            <Text style={[styles.macroRemaining, remainingProtein >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
              {remainingProtein >= 0 ? `${Math.round(remainingProtein)}g remaining` : `${Math.abs(Math.round(remainingProtein))}g over`}
            </Text>
          </View>

          {/* Carbs */}
          <View style={styles.macroRow}>
            <View style={styles.macroHeader}>
              <Text style={styles.macroLabel}>Carbs</Text>
              <Text style={styles.macroValue}>{Math.round(totalCarbs)} / {goalCarbs}g</Text>
            </View>
            <View style={styles.macroBar}>
              <View style={[styles.macroBarFill, { width: `${carbsPercent}%`, backgroundColor: '#4ECDC4' }]} />
            </View>
            <Text style={[styles.macroRemaining, remainingCarbs >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
              {remainingCarbs >= 0 ? `${Math.round(remainingCarbs)}g remaining` : `${Math.abs(Math.round(remainingCarbs))}g over`}
            </Text>
          </View>

          {/* Fat */}
          <View style={styles.macroRow}>
            <View style={styles.macroHeader}>
              <Text style={styles.macroLabel}>Fat</Text>
              <Text style={styles.macroValue}>{Math.round(totalFat)} / {goalFats}g</Text>
            </View>
            <View style={styles.macroBar}>
              <View style={[styles.macroBarFill, { width: `${fatPercent}%`, backgroundColor: '#FFD93D' }]} />
            </View>
            <Text style={[styles.macroRemaining, remainingFat >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
              {remainingFat >= 0 ? `${Math.round(remainingFat)}g remaining` : `${Math.abs(Math.round(remainingFat))}g over`}
            </Text>
          </View>
        </View>

        {/* Meal Sections */}
        <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Today's Meals</Text>

        {/* Breakfast */}
        <View style={styles.mealSection}>
          <View style={styles.mealHeader}>
            <Text style={styles.mealTitle}>🌅 Breakfast</Text>
            <TouchableOpacity
              style={styles.addMealButton}
              onPress={() => handleLogFood('breakfast')}
            >
              <Text style={styles.addMealButtonText}>+ Add</Text>
            </TouchableOpacity>
          </View>
          {breakfastFoods.length > 0 ? (
            breakfastFoods.map((log) => (
              <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
            ))
          ) : (
            <Text style={styles.emptyMealText}>No breakfast logged yet</Text>
          )}
        </View>

        {/* Lunch */}
        <View style={styles.mealSection}>
          <View style={styles.mealHeader}>
            <Text style={styles.mealTitle}>☀️ Lunch</Text>
            <TouchableOpacity
              style={styles.addMealButton}
              onPress={() => handleLogFood('lunch')}
            >
              <Text style={styles.addMealButtonText}>+ Add</Text>
            </TouchableOpacity>
          </View>
          {lunchFoods.length > 0 ? (
            lunchFoods.map((log) => (
              <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
            ))
          ) : (
            <Text style={styles.emptyMealText}>No lunch logged yet</Text>
          )}
        </View>

        {/* Dinner */}
        <View style={styles.mealSection}>
          <View style={styles.mealHeader}>
            <Text style={styles.mealTitle}>🌙 Dinner</Text>
            <TouchableOpacity
              style={styles.addMealButton}
              onPress={() => handleLogFood('dinner')}
            >
              <Text style={styles.addMealButtonText}>+ Add</Text>
            </TouchableOpacity>
          </View>
          {dinnerFoods.length > 0 ? (
            dinnerFoods.map((log) => (
              <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
            ))
          ) : (
            <Text style={styles.emptyMealText}>No dinner logged yet</Text>
          )}
        </View>

        {/* Snacks */}
        <View style={styles.mealSection}>
          <View style={styles.mealHeader}>
            <Text style={styles.mealTitle}>🍎 Snacks</Text>
            <TouchableOpacity
              style={styles.addMealButton}
              onPress={() => handleLogFood('snack')}
            >
              <Text style={styles.addMealButtonText}>+ Add</Text>
            </TouchableOpacity>
          </View>
          {snackFoods.length > 0 ? (
            snackFoods.map((log) => (
              <FoodLogItem key={log.id} log={log} onLongPress={handleDeleteFood} />
            ))
          ) : (
            <Text style={styles.emptyMealText}>No snacks logged yet</Text>
          )}
        </View>
      </ScrollView>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <WorkoutLogModal
        visible={showWorkoutModal}
        onClose={() => setShowWorkoutModal(false)}
        onComplete={() => {
          setShowWorkoutModal(false);
          loadData();
        }}
      />
      <WorkoutEditModal
        visible={showEditModal}
        workoutSession={selectedWorkout}
        onClose={() => {
          setShowEditModal(false);
          setSelectedWorkout(null);
        }}
        onComplete={() => {
          loadData();
        }}
      />
      <FoodLogModal
        visible={showFoodModal}
        onClose={() => setShowFoodModal(false)}
        onComplete={() => {
          setShowFoodModal(false);
          loadData();
        }}
        initialMealType={selectedMealType}
      />

      {/* Navigation Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'dashboard' && styles.tabActive]}
          onPress={() => setViewMode('dashboard')}
        >
          <Text style={[styles.tabText, viewMode === 'dashboard' && styles.tabTextActive]}>
            Dashboard
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'nutrition' && styles.tabActive]}
          onPress={() => setViewMode('nutrition')}
        >
          <Text style={[styles.tabText, viewMode === 'nutrition' && styles.tabTextActive]}>
            Nutrition
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'workout' && styles.tabActive]}
          onPress={() => setViewMode('workout')}
        >
          <Text style={[styles.tabText, viewMode === 'workout' && styles.tabTextActive]}>
            Workouts
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'recovery' && styles.tabActive]}
          onPress={() => setViewMode('recovery')}
        >
          <Text style={[styles.tabText, viewMode === 'recovery' && styles.tabTextActive]}>
            Recovery
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'programs' && styles.tabActive]}
          onPress={() => setViewMode('programs')}
        >
          <Text style={[styles.tabText, viewMode === 'programs' && styles.tabTextActive]}>
            Programs
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      {viewMode === 'dashboard' && renderDashboard()}
      {viewMode === 'nutrition' && renderNutritionView()}
      {viewMode === 'workout' && renderWorkoutView()}
      {viewMode === 'recovery' && renderRecoveryView()}
      {viewMode === 'programs' && renderProgramsView()}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  tabs: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    borderRadius: borderRadius.md,
  },
  tabActive: {
    backgroundColor: colors.primary,
  },
  tabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  tabTextActive: {
    color: colors.text,
  },
  content: {
    flex: 1,
  },
  viewHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
  },
  backButton: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  addButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  addButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  editButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  editButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  summaryCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    margin: spacing.md,
  },
  summaryTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
  summaryStats: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  summaryStatItem: {
    alignItems: 'center',
  },
  summaryStatValue: {
    color: colors.primary,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  summaryStatLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  quickActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  quickActionButton: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  quickActionEmoji: {
    fontSize: 32,
    marginBottom: spacing.xs,
  },
  quickActionText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  section: {
    marginBottom: spacing.lg,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  seeAllText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
    padding: spacing.xl,
  },
  habitCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  habitName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  habitStats: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  habitStat: {
    alignItems: 'center',
  },
  habitStatValue: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  habitStatLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  calorieDisplay: {
    alignItems: 'center',
    paddingVertical: spacing.lg,
  },
  calorieNumber: {
    color: colors.primary,
    fontSize: 48,
    fontWeight: '700',
  },
  calorieLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    marginTop: spacing.xs,
  },
  macroRow: {
    marginBottom: spacing.lg,
  },
  macroHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  macroLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  macroValue: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  macroBar: {
    height: 8,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    overflow: 'hidden',
    marginBottom: spacing.xs,
  },
  macroBarFill: {
    height: '100%',
    borderRadius: borderRadius.sm,
  },
  macroCalories: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  macroRemaining: {
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  remainingContainer: {
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  remainingText: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  remainingPositive: {
    color: colors.primary,
  },
  remainingNegative: {
    color: '#FF6B6B',
  },
  mealSection: {
    marginBottom: spacing.lg,
  },
  mealHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  mealTitle: {
    fontSize: fontSizes.md,
    fontWeight: '700',
    color: colors.text,
  },
  addMealButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  addMealButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  emptyMealText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
    fontStyle: 'italic',
  },
  dateNavigator: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginVertical: spacing.sm,
    borderRadius: borderRadius.md,
    gap: spacing.sm,
  },
  dateNavButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minWidth: 70,
  },
  dateNavButtonDisabled: {
    backgroundColor: colors.surface,
    opacity: 0.5,
  },
  dateNavButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    textAlign: 'center',
  },
  dateNavButtonTextDisabled: {
    color: colors.textMuted,
  },
  dateDisplay: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dateDisplayText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  todayButton: {
    backgroundColor: colors.accent,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    minWidth: 40,
  },
  todayButtonText: {
    fontSize: fontSizes.lg,
    textAlign: 'center',
  },
});

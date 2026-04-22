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
  Modal,
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
  Program,
  WorkoutTemplate,
  NutritionGoals,
  getEffectiveTargets,
} from '../../services/fitness';
import FoodLogItem from '../../components/fitness/FoodLogItem';
import WorkoutSessionItem from '../../components/fitness/WorkoutSessionItem';
import RecoveryCard from '../../components/fitness/RecoveryCard';
import WorkoutLogModal from '../../components/fitness/WorkoutLogModal';
import WorkoutEditModal from '../../components/fitness/WorkoutEditModal';
import FoodLogModal from '../../components/fitness/FoodLogModal';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { Ionicons } from '@expo/vector-icons';
import { navigateToChat } from '../../services/navigation';
import Markdown from 'react-native-markdown-display';

type Props = MainTabScreenProps<'Fitness'>;

type ViewMode = 'dashboard' | 'plan' | 'nutrition' | 'workout' | 'recovery' | 'habits' | 'programs';

export default function FitnessScreen({ navigation }: Props) {
  const { isActive: hasActiveWorkout, startWorkout } = useWorkoutMode();
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showWorkoutModal, setShowWorkoutModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedWorkout, setSelectedWorkout] = useState<WorkoutSession | null>(null);
  const [showFoodModal, setShowFoodModal] = useState(false);
  const [selectedMealType, setSelectedMealType] = useState('snack');
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
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
  const [activeProgram, setActiveProgram] = useState<Program | null>(null);
  const [todaysTemplates, setTodaysTemplates] = useState<WorkoutTemplate[]>([]);
  const [planViewMode, setPlanViewMode] = useState<'sections' | 'full'>('sections');
  const [expandedPlanSections, setExpandedPlanSections] = useState<Set<number>>(new Set());
  const [isTrainingDayFromApi, setIsTrainingDayFromApi] = useState<boolean | null>(null);
  const [togglingTrainingDay, setTogglingTrainingDay] = useState(false);

  useEffect(() => {
    loadData();
    loadNutritionGoalsWithPhase();
    loadTodayTarget();
  }, []);

  // Training day state: prefer API response, fall back to template-based detection
  const isTrainingDay: boolean | null = (() => {
    // If the API told us explicitly, use that
    if (isTrainingDayFromApi !== null) return isTrainingDayFromApi;
    if (!activePhase) return null;
    const cycles =
      activePhase.calories_training_day != null ||
      activePhase.calories_rest_day != null ||
      activePhase.carbs_training_day != null ||
      activePhase.carbs_rest_day != null ||
      activePhase.fat_training_day != null ||
      activePhase.fat_rest_day != null;
    if (!cycles) return null;
    return todaysTemplates.length > 0;
  })();

  const loadTodayTarget = async () => {
    try {
      const data = await fitnessService.getTodayTarget();
      setIsTrainingDayFromApi(data.is_training_day);
      if (data.target) {
        setNutritionGoals({
          calories: data.target.calories,
          protein: data.target.protein,
          carbs: data.target.carbs,
          fats: data.target.fat,
        });
      }
    } catch (error) {
      console.error('Failed to load today target:', error);
    }
  };

  const handleToggleTrainingDay = async () => {
    setTogglingTrainingDay(true);
    try {
      const result = await fitnessService.toggleTrainingDay();
      setIsTrainingDayFromApi(result.is_training_day);
      // Re-fetch targets since macros change
      await loadTodayTarget();
    } catch (error) {
      console.error('Failed to toggle training day:', error);
    } finally {
      setTogglingTrainingDay(false);
    }
  };

  useEffect(() => {
    if (!activePhase) return;
    setNutritionGoals(prev => getEffectiveTargets(activePhase, isTrainingDay, prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePhase, isTrainingDay]);

  // Derive Phase progress (week X of Y, days remaining)
  const phaseProgress = (() => {
    if (!activePhase) return null;
    const start = activePhase.start_date ? new Date(activePhase.start_date + 'T00:00:00') : null;
    const end = activePhase.end_date ? new Date(activePhase.end_date + 'T00:00:00') : null;
    const now = new Date();
    const totalWeeks = activePhase.duration_weeks ?? (start && end
      ? Math.max(1, Math.round((end.getTime() - start.getTime()) / (7 * 24 * 3600 * 1000)))
      : null);
    const currentWeek = start
      ? Math.max(1, Math.floor((now.getTime() - start.getTime()) / (7 * 24 * 3600 * 1000)) + 1)
      : null;
    const daysRemaining = end
      ? Math.max(0, Math.ceil((end.getTime() - now.getTime()) / (24 * 3600 * 1000)))
      : null;
    return { currentWeek, totalWeeks, daysRemaining };
  })();

  const loadNutritionGoalsWithPhase = async () => {
    try {
      const baseGoals = await fitnessService.getNutritionGoals().catch(() => null);
      if (baseGoals) setNutritionGoals(baseGoals);

      // Prefer active program (gives us plan_markdown + phases); fall back to /phases/active
      let phase: Phase | null = null;
      try {
        const programResp = await fitnessService.getActiveProgram();
        if (programResp?.program) setActiveProgram(programResp.program);
        if (programResp?.phases?.length) {
          phase = programResp.phases.find(p => p.status === 'active') ?? programResp.phases[0];
        }
      } catch {
        /* fall through to phase-only fetch */
      }

      if (!phase) {
        const activePhases = await fitnessService.getActivePhases().catch(() => ({ phases: [] }));
        if (activePhases.phases?.length) phase = activePhases.phases[0];
      }

      if (phase) {
        setActivePhase(phase);
        // Use effective targets (training-day aware once we know isTrainingDay).
        // At this point we don't know yet — caller updates again after loadData.
        setNutritionGoals(getEffectiveTargets(phase, null, baseGoals));
      }
    } catch (error) {
      console.error('Failed to load nutrition goals / active phase:', error);
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
      const todayTemplatesData = await fitnessService.getTodaysTemplates().catch(() => ({ templates: [] }));

      setFoodLogs(food);
      setWorkoutLogs(workouts);
      setRecoveryLogs(recovery);
      setHabitStreaks(streaks);
      setDailySummary(summary);
      setPhases(phasesData.phases);
      setTemplates(templatesData.templates);
      setTodaysTemplates(todayTemplatesData.templates || []);
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

  const handleEditFood = (log: FoodLog) => {
    const mealTypes = ['breakfast', 'lunch', 'dinner', 'snack'];
    Alert.alert(
      'Change Meal Type',
      `${log.food_name}\nCurrently: ${log.meal_type || 'none'}`,
      [
        ...mealTypes.map((type) => ({
          text: `${type === 'breakfast' ? '🌅' : type === 'lunch' ? '🌞' : type === 'dinner' ? '🌙' : '🍎'} ${type.charAt(0).toUpperCase() + type.slice(1)}`,
          onPress: async () => {
            try {
              await fitnessService.updateFoodLogMealType(log.meal_log_id, type);
              loadData();
            } catch (error) {
              console.error('Failed to update meal type:', error);
              Alert.alert('Error', 'Failed to update meal type');
            }
          },
        })),
        { text: 'Cancel', style: 'cancel' },
      ]
    );
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

  const openFitnessPrompt = (message: string) => {
    navigateToChat({
      quickReply: {
        title: 'Fitness',
        message,
        nudgeType: 'fitness_focus',
      },
    });
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const renderDashboard = () => {
    const todayStr = (() => {
      const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    })();
    const todaysFoods = (foodLogs || []).filter(log => log.logged_at && getLocalDateString(log.logged_at) === todayStr);
    const todaysWorkouts = (workoutLogs || []).filter(log => {
      const dateStr = log.session_date || (log.created_at && getLocalDateString(log.created_at));
      return dateStr === todayStr;
    });

    const totalCalories = Math.round(todaysFoods.reduce((s, l) => s + (l.calories || 0), 0));
    const totalProtein = Math.round(todaysFoods.reduce((s, l) => s + (l.protein || 0), 0));
    const totalCarbs = Math.round(todaysFoods.reduce((s, l) => s + (l.carbs || 0), 0));
    const totalFats = Math.round(todaysFoods.reduce((s, l) => s + (l.fat || 0), 0));

    const goals = nutritionGoals ?? { calories: 2000, protein: 150, carbs: 200, fats: 70 };
    const pct = (v: number, g: number) => (g > 0 ? Math.min(100, Math.round((v / g) * 100)) : 0);

    const hasActivePlan = !!activePhase;
    const hasWorkoutToday = todaysTemplates.length > 0;
    const firstTemplate = todaysTemplates[0];
    const guidanceTitle = !hasActivePlan
      ? 'Next move: set a training direction'
      : hasWorkoutToday
        ? `Next move: ${hasActiveWorkout ? 'resume' : 'start'} ${firstTemplate.name}`
        : 'Next move: recover and stay on target';
    const guidanceBody = !hasActivePlan
      ? 'You need a plan before the rest of this screen becomes useful.'
      : hasWorkoutToday
        ? 'Your main win today is getting the scheduled work done and staying close to nutrition targets.'
        : 'No training block is scheduled, so the best use of this screen is recovery and nutrition.';

    return (
      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.dashboardContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        {/* Active Phase hero */}
        {hasActivePlan ? (
          <TouchableOpacity
            style={styles.phaseHero}
            onPress={() => setViewMode('plan')}
            activeOpacity={0.85}
          >
            <View style={styles.phaseHeroHeader}>
              <View style={{ flex: 1 }}>
                {activeProgram?.name ? (
                  <Text style={styles.phaseHeroProgram}>{activeProgram.name}</Text>
                ) : null}
                <Text style={styles.phaseHeroName}>{activePhase!.name}</Text>
                {activePhase!.goal ? (
                  <Text style={styles.phaseHeroGoal}>{activePhase!.goal}</Text>
                ) : null}
              </View>
              {activePhase!.deload_week ? (
                <View style={styles.deloadBadge}>
                  <Text style={styles.deloadBadgeText}>DELOAD</Text>
                </View>
              ) : null}
            </View>

            {phaseProgress && (phaseProgress.currentWeek || phaseProgress.totalWeeks) ? (
              <View style={styles.phaseProgressRow}>
                <Text style={styles.phaseProgressText}>
                  {phaseProgress.currentWeek && phaseProgress.totalWeeks
                    ? `Week ${Math.min(phaseProgress.currentWeek, phaseProgress.totalWeeks)} of ${phaseProgress.totalWeeks}`
                    : phaseProgress.currentWeek
                      ? `Week ${phaseProgress.currentWeek}`
                      : ''}
                </Text>
                {phaseProgress.daysRemaining != null ? (
                  <Text style={styles.phaseProgressDays}>
                    {phaseProgress.daysRemaining === 0 ? 'Last day' : `${phaseProgress.daysRemaining}d left`}
                  </Text>
                ) : null}
              </View>
            ) : null}

            {phaseProgress && phaseProgress.currentWeek && phaseProgress.totalWeeks ? (
              <View style={styles.phaseProgressBar}>
                <View
                  style={[
                    styles.phaseProgressBarFill,
                    { width: `${Math.min(100, (phaseProgress.currentWeek / phaseProgress.totalWeeks) * 100)}%` },
                  ]}
                />
              </View>
            ) : null}

            <Text style={styles.phaseHeroTap}>View plan →</Text>
          </TouchableOpacity>
        ) : (
          <View style={[styles.phaseHero, styles.phaseHeroEmpty]}>
            <Text style={styles.phaseHeroName}>No active program</Text>
            <Text style={styles.phaseHeroGoal}>Ask Sara to build a plan, or set one up in Programs.</Text>
          </View>
        )}

        {/* Today card — training vs rest day */}
        <View
          style={[
            styles.todayCard,
            isTrainingDay === true && styles.todayCardTraining,
            isTrainingDay === false && styles.todayCardRest,
          ]}
        >
          <View style={styles.todayHeader}>
            <Ionicons
              name={isTrainingDay === true ? 'flash' : isTrainingDay === false ? 'moon' : 'calendar-outline'}
              size={18}
              color={
                isTrainingDay === true
                  ? colors.fitness.trainingDay
                  : isTrainingDay === false
                    ? colors.fitness.restDay
                    : colors.textSecondary
              }
            />
            <Text style={styles.todayHeaderLabel}>
              {isTrainingDay === true ? 'Training day' : isTrainingDay === false ? 'Rest day' : 'Today'}
            </Text>
            <View style={{ flex: 1 }} />
            {isTrainingDay !== null && (
              <TouchableOpacity
                onPress={handleToggleTrainingDay}
                disabled={togglingTrainingDay}
                style={{
                  paddingHorizontal: 10,
                  paddingVertical: 4,
                  borderRadius: 12,
                  backgroundColor: isTrainingDay
                    ? 'rgba(234, 179, 8, 0.15)'
                    : 'rgba(99, 102, 241, 0.15)',
                  borderWidth: 1,
                  borderColor: isTrainingDay
                    ? 'rgba(234, 179, 8, 0.3)'
                    : 'rgba(99, 102, 241, 0.3)',
                  opacity: togglingTrainingDay ? 0.5 : 1,
                }}
              >
                <Text style={{
                  fontSize: 11,
                  fontWeight: '600',
                  color: isTrainingDay
                    ? colors.fitness.trainingDay
                    : colors.fitness.restDay,
                }}>
                  {isTrainingDay ? 'Switch to rest' : 'Switch to training'}
                </Text>
              </TouchableOpacity>
            )}
          </View>

          {hasWorkoutToday ? (
            <>
              <Text style={styles.todayWorkoutName}>{firstTemplate.name}</Text>
              {firstTemplate.exercises?.length ? (
                <Text style={styles.todayWorkoutMeta}>{firstTemplate.exercises.length} exercises</Text>
              ) : null}
              <TouchableOpacity
                style={styles.todayStartButton}
                onPress={() => {
                  if (hasActiveWorkout) {
                    navigation.navigate('WorkoutMode' as any);
                  } else {
                    handleStartWorkout(firstTemplate.id);
                  }
                }}
              >
                <Ionicons name={hasActiveWorkout ? 'play' : 'barbell'} size={16} color="#fff" />
                <Text style={styles.todayStartButtonText}>
                  {hasActiveWorkout ? 'Resume workout' : 'Start workout'}
                </Text>
              </TouchableOpacity>
            </>
          ) : (
            <Text style={styles.todayEmpty}>
              {isTrainingDay === false
                ? 'No workout scheduled — recovery focus.'
                : 'No workout scheduled for today.'}
            </Text>
          )}
        </View>

        <View style={styles.guidanceCard}>
          <View style={styles.guidanceHeader}>
            <View style={styles.guidanceIcon}>
              <Ionicons name="compass-outline" size={18} color={colors.accent} />
            </View>
            <View style={styles.guidanceCopy}>
              <Text style={styles.guidanceEyebrow}>What can I do next?</Text>
              <Text style={styles.guidanceTitle}>{guidanceTitle}</Text>
              <Text style={styles.guidanceBody}>{guidanceBody}</Text>
            </View>
          </View>
          <View style={styles.guidanceActions}>
            {!hasActivePlan ? (
              <>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonPrimary]}
                  onPress={() => openFitnessPrompt('Build me a training plan that fits my current goals and schedule.')}
                >
                  <Text style={styles.guidanceButtonPrimaryText}>Ask Sara for a Plan</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonSecondary]}
                  onPress={() => setViewMode('programs')}
                >
                  <Text style={styles.guidanceButtonSecondaryText}>Open Programs</Text>
                </TouchableOpacity>
              </>
            ) : hasWorkoutToday ? (
              <>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonPrimary]}
                  onPress={() => {
                    if (hasActiveWorkout) {
                      navigation.navigate('WorkoutMode' as any);
                    } else {
                      handleStartWorkout(firstTemplate.id);
                    }
                  }}
                >
                  <Text style={styles.guidanceButtonPrimaryText}>
                    {hasActiveWorkout ? 'Resume Workout' : 'Start Workout'}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonSecondary]}
                  onPress={() => setViewMode('nutrition')}
                >
                  <Text style={styles.guidanceButtonSecondaryText}>Open Nutrition</Text>
                </TouchableOpacity>
              </>
            ) : (
              <>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonPrimary]}
                  onPress={handleLogRecovery}
                >
                  <Text style={styles.guidanceButtonPrimaryText}>Log Recovery</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.guidanceButton, styles.guidanceButtonSecondary]}
                  onPress={() => openFitnessPrompt('What should I focus on today for recovery, food, and training readiness?')}
                >
                  <Text style={styles.guidanceButtonSecondaryText}>Ask Sara</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        </View>

        {/* Today's macros */}
        <View style={styles.macrosCard}>
          <View style={styles.macrosHeader}>
            <Text style={styles.macrosTitle}>Today's nutrition</Text>
            <TouchableOpacity onPress={() => setViewMode('nutrition')}>
              <Text style={styles.seeAllText}>Details →</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.caloriesRow}>
            <Text style={styles.caloriesValue}>{totalCalories}</Text>
            <Text style={styles.caloriesGoal}> / {goals.calories} kcal</Text>
          </View>
          <View style={styles.macroBarTrack}>
            <View
              style={[
                styles.macroBarFill,
                { width: `${pct(totalCalories, goals.calories)}%`, backgroundColor: colors.fitness.calories },
              ]}
            />
          </View>

          {([
            { label: 'Protein', value: totalProtein, goal: goals.protein, color: colors.fitness.protein },
            { label: 'Carbs', value: totalCarbs, goal: goals.carbs, color: colors.fitness.carbs },
            { label: 'Fats', value: totalFats, goal: goals.fats, color: colors.fitness.fats },
          ] as const).map(m => (
            <View key={m.label} style={styles.macroRowCompact}>
              <View style={styles.macroRowLabels}>
                <Text style={styles.macroRowLabel}>{m.label}</Text>
                <Text style={styles.macroRowValue}>{m.value} / {m.goal}g</Text>
              </View>
              <View style={styles.macroBarTrack}>
                <View style={[styles.macroBarFill, { width: `${pct(m.value, m.goal)}%`, backgroundColor: m.color }]} />
              </View>
            </View>
          ))}
        </View>

        {/* Quick actions */}
        <View style={styles.quickActions}>
          <TouchableOpacity style={styles.quickActionButton} onPress={() => handleLogFood()}>
            <Ionicons name="restaurant-outline" size={22} color={colors.text} />
            <Text style={styles.quickActionText}>Food</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.quickActionButton} onPress={handleLogWorkout}>
            <Ionicons name="barbell-outline" size={22} color={colors.text} />
            <Text style={styles.quickActionText}>Workout</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.quickActionButton} onPress={handleLogRecovery}>
            <Ionicons name="bed-outline" size={22} color={colors.text} />
            <Text style={styles.quickActionText}>Recovery</Text>
          </TouchableOpacity>
        </View>

        {/* Recent activity — compact */}
        {todaysWorkouts.length > 0 || todaysFoods.length > 0 || recoveryLogs.length > 0 ? (
          <View style={styles.recentSection}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Today's activity</Text>
            </View>
            {todaysWorkouts.slice(0, 2).map(session => (
              <WorkoutSessionItem
                key={`w-${session.id}`}
                session={session}
                onPress={handleViewWorkout}
                onLongPress={handleLongPressWorkout}
              />
            ))}
            {todaysFoods.slice(0, 3).map(log => (
              <FoodLogItem key={`f-${log.id}`} log={log} onPress={handleEditFood} onLongPress={handleDeleteFood} />
            ))}
            {recoveryLogs.length > 0 &&
              recoveryLogs[0].log_date === todayStr ? (
              <RecoveryCard
                log={recoveryLogs[0]}
                onPress={handleEditRecovery}
                onLongPress={handleDeleteRecovery}
              />
            ) : null}
          </View>
        ) : (
          <View style={styles.recentSection}>
            <Text style={styles.emptyText}>Nothing logged today yet.</Text>
          </View>
        )}
      </ScrollView>
    );
  };

  const renderPlanView = () => {
    const markdown = activeProgram?.plan_markdown || null;

    if (!markdown) {
      return (
        <ScrollView
          style={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
        >
          <View style={styles.planEmpty}>
            <Ionicons name="book-outline" size={48} color={colors.textMuted} />
            <Text style={styles.planEmptyTitle}>No training plan attached</Text>
            <Text style={styles.planEmptyBody}>
              {activeProgram
                ? `${activeProgram.name} doesn't have a plan document yet. Ask Sara to generate one.`
                : 'No active program. Set one up in Programs or ask Sara to build a plan.'}
            </Text>
          </View>
        </ScrollView>
      );
    }

    // Parse into header + sections (## headings)
    const lines = markdown.split('\n');
    const sections: { title: string; content: string }[] = [];
    const headerLines: string[] = [];
    let currentTitle = '';
    let currentLines: string[] = [];
    let seenFirstSection = false;

    for (const line of lines) {
      const h2 = line.match(/^##\s+(.+)/);
      if (h2) {
        if (seenFirstSection) {
          sections.push({ title: currentTitle, content: currentLines.join('\n').trim() });
        }
        currentTitle = h2[1];
        currentLines = [];
        seenFirstSection = true;
      } else if (seenFirstSection) {
        currentLines.push(line);
      } else {
        headerLines.push(line);
      }
    }
    if (seenFirstSection) {
      sections.push({ title: currentTitle, content: currentLines.join('\n').trim() });
    }
    const headerMd = headerLines.join('\n').trim();

    const toggleSection = (idx: number) => {
      setExpandedPlanSections(prev => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx);
        else next.add(idx);
        return next;
      });
    };

    const expandAll = () => setExpandedPlanSections(new Set(sections.map((_, i) => i)));
    const collapseAll = () => setExpandedPlanSections(new Set());

    return (
      <ScrollView
        style={styles.content}
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        {headerMd ? (
          <View style={[styles.planFullCard, { marginTop: spacing.md }]}>
            <Markdown style={planMarkdownStyles}>{headerMd}</Markdown>
          </View>
        ) : null}

        <View style={styles.planControls}>
          <View style={styles.planModeToggle}>
            <TouchableOpacity
              style={[styles.planModeButton, planViewMode === 'sections' && styles.planModeButtonActive]}
              onPress={() => setPlanViewMode('sections')}
            >
              <Text
                style={[styles.planModeButtonText, planViewMode === 'sections' && styles.planModeButtonTextActive]}
              >
                Sections
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.planModeButton, planViewMode === 'full' && styles.planModeButtonActive]}
              onPress={() => setPlanViewMode('full')}
            >
              <Text
                style={[styles.planModeButtonText, planViewMode === 'full' && styles.planModeButtonTextActive]}
              >
                Full Plan
              </Text>
            </TouchableOpacity>
          </View>
          {planViewMode === 'sections' && sections.length > 0 ? (
            <TouchableOpacity
              onPress={expandedPlanSections.size === sections.length ? collapseAll : expandAll}
            >
              <Text style={styles.planExpandAllText}>
                {expandedPlanSections.size === sections.length ? 'Collapse all' : 'Expand all'}
              </Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {planViewMode === 'full' ? (
          <View style={styles.planFullCard}>
            <Markdown style={planMarkdownStyles}>{markdown}</Markdown>
          </View>
        ) : (
          sections.map((section, idx) => {
            const isExpanded = expandedPlanSections.has(idx);
            const isPhase = section.title.toLowerCase().startsWith('phase');
            const isNutrition = section.title.toLowerCase().includes('nutrition');

            return (
              <View
                key={idx}
                style={[
                  styles.planSection,
                  isPhase && styles.planSectionPhase,
                  isNutrition && styles.planSectionNutrition,
                ]}
              >
                <TouchableOpacity
                  style={styles.planSectionHeader}
                  onPress={() => toggleSection(idx)}
                  activeOpacity={0.7}
                >
                  <Ionicons
                    name={isExpanded ? 'chevron-down' : 'chevron-forward'}
                    size={18}
                    color={colors.textSecondary}
                  />
                  <Text style={styles.planSectionTitle}>{section.title}</Text>
                </TouchableOpacity>
                {isExpanded ? (
                  <View style={styles.planSectionBody}>
                    <Markdown style={planMarkdownStyles}>{section.content}</Markdown>
                  </View>
                ) : null}
              </View>
            );
          })
        )}
      </ScrollView>
    );
  };

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

  const handleStartWorkout = async (templateId: string) => {
    setShowTemplatePicker(false);
    const session = await startWorkout(templateId);
    if (session) {
      // Small delay to allow context state to propagate before navigation
      setTimeout(() => {
        navigation.navigate('WorkoutMode' as any);
      }, 50);
    } else {
      Alert.alert('Error', 'Failed to start workout. Please try again.');
    }
  };

  const renderWorkoutView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('dashboard')}>
          <Text style={styles.backButton}>← Back</Text>
        </TouchableOpacity>
        <View style={styles.headerButtons}>
          <TouchableOpacity
            style={[styles.startWorkoutButton, hasActiveWorkout && styles.resumeWorkoutButton]}
            onPress={() => {
              if (hasActiveWorkout) {
                navigation.navigate('WorkoutMode' as any);
              } else {
                setShowTemplatePicker(true);
              }
            }}
          >
            <Ionicons
              name={hasActiveWorkout ? 'play' : 'barbell'}
              size={16}
              color="#fff"
            />
            <Text style={styles.startWorkoutButtonText}>
              {hasActiveWorkout ? 'Resume' : 'Start Workout'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.addButton} onPress={handleLogWorkout}>
            <Text style={styles.addButtonText}>+ Log</Text>
          </TouchableOpacity>
        </View>
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

        {/* Training/rest day context — only for today, only if phase cycles macros */}
        {selectedDate === (() => {
          const d = new Date();
          return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        })() && isTrainingDay != null ? (
          <View
            style={[
              styles.nutritionDayBadge,
              isTrainingDay ? styles.nutritionDayBadgeTraining : styles.nutritionDayBadgeRest,
            ]}
          >
            <Ionicons
              name={isTrainingDay ? 'flash' : 'moon'}
              size={14}
              color={isTrainingDay ? colors.fitness.trainingDay : colors.fitness.restDay}
            />
            <Text style={styles.nutritionDayBadgeText}>
              {isTrainingDay ? 'Training-day targets' : 'Rest-day targets'}
            </Text>
          </View>
        ) : null}

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
              <FoodLogItem key={log.id} log={log} onPress={handleEditFood} onLongPress={handleDeleteFood} />
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
              <FoodLogItem key={log.id} log={log} onPress={handleEditFood} onLongPress={handleDeleteFood} />
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
              <FoodLogItem key={log.id} log={log} onPress={handleEditFood} onLongPress={handleDeleteFood} />
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
              <FoodLogItem key={log.id} log={log} onPress={handleEditFood} onLongPress={handleDeleteFood} />
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

      {/* Template Picker Modal */}
      <Modal
        visible={showTemplatePicker}
        transparent={true}
        animationType="fade"
        onRequestClose={() => setShowTemplatePicker(false)}
      >
        <View style={styles.templatePickerOverlay}>
          <View style={styles.templatePicker}>
            <Text style={styles.templatePickerTitle}>Select Workout</Text>
            <ScrollView style={styles.templateList}>
              {templates.map((template: any) => (
                <TouchableOpacity
                  key={template.id}
                  style={[
                    styles.templateItem,
                    template.is_today && styles.templateItemToday
                  ]}
                  onPress={() => handleStartWorkout(template.id)}
                >
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                      <Text style={styles.templateName}>{template.name}</Text>
                      {template.is_today && (
                        <View style={styles.todayBadge}>
                          <Text style={styles.todayBadgeText}>TODAY</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.templateExercises}>
                      {template.exercises?.length || 0} exercises
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={20} color={template.is_today ? '#22c55e' : '#666'} />
                </TouchableOpacity>
              ))}
              {templates.length === 0 && (
                <Text style={styles.emptyText}>
                  No workout templates yet. Create one in Programs!
                </Text>
              )}
            </ScrollView>
            <TouchableOpacity
              style={styles.templatePickerCancel}
              onPress={() => setShowTemplatePicker(false)}
            >
              <Text style={styles.templatePickerCancelText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Navigation Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabs}
        contentContainerStyle={styles.tabsContent}
      >
        <TouchableOpacity
          style={[styles.tab, viewMode === 'dashboard' && styles.tabActive]}
          onPress={() => setViewMode('dashboard')}
        >
          <Text style={[styles.tabText, viewMode === 'dashboard' && styles.tabTextActive]}>
            Dashboard
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'plan' && styles.tabActive]}
          onPress={() => setViewMode('plan')}
        >
          <Text style={[styles.tabText, viewMode === 'plan' && styles.tabTextActive]}>
            Plan
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
      </ScrollView>

      {/* Content */}
      {viewMode === 'dashboard' && renderDashboard()}
      {viewMode === 'plan' && renderPlanView()}
      {viewMode === 'nutrition' && renderNutritionView()}
      {viewMode === 'workout' && renderWorkoutView()}
      {viewMode === 'recovery' && renderRecoveryView()}
      {viewMode === 'programs' && renderProgramsView()}
    </SafeAreaView>
  );
}

const planMarkdownStyles = {
  body: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 22,
  },
  heading1: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700' as const,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  heading2: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700' as const,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  heading3: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600' as const,
    marginTop: spacing.sm,
    marginBottom: 4,
  },
  paragraph: {
    color: colors.text,
    marginBottom: spacing.sm,
  },
  strong: {
    color: colors.text,
    fontWeight: '700' as const,
  },
  em: {
    color: colors.text,
    fontStyle: 'italic' as const,
  },
  bullet_list: {
    marginBottom: spacing.sm,
  },
  ordered_list: {
    marginBottom: spacing.sm,
  },
  list_item: {
    color: colors.text,
  },
  code_inline: {
    color: colors.primary,
    backgroundColor: 'rgba(255,255,255,0.08)',
    fontSize: fontSizes.sm,
    paddingHorizontal: 4,
    borderRadius: 3,
  },
  fence: {
    color: colors.text,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    fontSize: fontSizes.xs,
  },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.sm,
  },
  table: {
    borderColor: colors.border,
  },
  th: {
    color: colors.text,
    fontWeight: '700' as const,
  },
  td: {
    color: colors.text,
  },
};

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
    backgroundColor: colors.surface,
    flexGrow: 0,
    flexShrink: 0,
    maxHeight: 44,
  },
  tab: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
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
  headerButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  startWorkoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#22c55e',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 6,
  },
  resumeWorkoutButton: {
    backgroundColor: '#3b82f6',
  },
  startWorkoutButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  templatePickerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  templatePicker: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    width: '85%',
    maxHeight: '70%',
  },
  templatePickerTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  templateList: {
    maxHeight: 400,
  },
  templateItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.background,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  templateItemToday: {
    backgroundColor: '#1a2e1a',
    borderWidth: 1,
    borderColor: '#22c55e',
  },
  todayBadge: {
    backgroundColor: '#22c55e',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  todayBadgeText: {
    color: '#000',
    fontSize: 10,
    fontWeight: '700',
  },
  templateName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  templateExercises: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  templatePickerCancel: {
    marginTop: spacing.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  templatePickerCancelText: {
    color: colors.primary,
    fontSize: fontSizes.md,
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
  guidanceCard: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  guidanceHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  guidanceIcon: {
    width: 34,
    height: 34,
    borderRadius: borderRadius.full,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: `${colors.accent}1a`,
  },
  guidanceCopy: {
    flex: 1,
  },
  guidanceEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  guidanceTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  guidanceBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  guidanceActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  guidanceButton: {
    flex: 1,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  guidanceButtonPrimary: {
    backgroundColor: colors.primary,
  },
  guidanceButtonSecondary: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  guidanceButtonPrimaryText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  guidanceButtonSecondaryText: {
    color: colors.textSecondary,
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

  // --- Dashboard redesign ---
  tabsContent: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    gap: spacing.xs,
    alignItems: 'center',
  },
  dashboardContent: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },

  // Phase hero card
  phaseHero: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.fitness.phaseAccent,
  },
  phaseHeroEmpty: {
    borderColor: colors.border,
    opacity: 0.9,
  },
  phaseHeroHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  phaseHeroProgram: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  phaseHeroName: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
  },
  phaseHeroGoal: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  phaseHeroTap: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    marginTop: spacing.sm,
    textAlign: 'right',
  },
  deloadBadge: {
    backgroundColor: colors.warning,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.sm,
  },
  deloadBadgeText: {
    color: '#000',
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  phaseProgressRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.md,
  },
  phaseProgressText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  phaseProgressDays: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  phaseProgressBar: {
    height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginTop: spacing.xs,
    overflow: 'hidden',
  },
  phaseProgressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
  },

  // Today card
  todayCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  todayCardTraining: {
    borderColor: colors.fitness.trainingDay,
    backgroundColor: colors.fitness.trainingDayBg,
  },
  todayCardRest: {
    borderColor: colors.fitness.restDay,
    backgroundColor: colors.fitness.restDayBg,
  },
  todayHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  todayHeaderLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  todayWorkoutName: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  todayWorkoutMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  todayEmpty: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  todayStartButton: {
    marginTop: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.primary,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  todayStartButtonText: {
    color: '#fff',
    fontSize: fontSizes.md,
    fontWeight: '700',
  },

  // Macros card
  macrosCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  macrosHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  macrosTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  caloriesRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginBottom: spacing.xs,
  },
  caloriesValue: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  caloriesGoal: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  macroRowCompact: {
    marginTop: spacing.sm,
  },
  macroRowLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  macroRowLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  macroRowValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  macroBarTrack: {
    height: 6,
    backgroundColor: colors.border,
    borderRadius: 3,
    overflow: 'hidden',
  },
  macroBarFill: {
    height: '100%',
    borderRadius: 3,
  },

  // Recent activity
  recentSection: {
    gap: spacing.xs,
  },

  // Nutrition day-type badge
  nutritionDayBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    alignSelf: 'flex-start',
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
  },
  nutritionDayBadgeTraining: {
    backgroundColor: colors.fitness.trainingDayBg,
    borderColor: colors.fitness.trainingDay,
  },
  nutritionDayBadgeRest: {
    backgroundColor: colors.fitness.restDayBg,
    borderColor: colors.fitness.restDay,
  },
  nutritionDayBadgeText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },

  // Plan view
  planEmpty: {
    padding: spacing.xl,
    alignItems: 'center',
    gap: spacing.sm,
  },
  planEmptyTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  planEmptyBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    textAlign: 'center',
  },
  planControls: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.background,
  },
  planModeToggle: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  planModeButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surface,
  },
  planModeButtonActive: {
    backgroundColor: colors.primary,
  },
  planModeButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  planModeButtonTextActive: {
    color: '#fff',
  },
  planExpandAllText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  planSection: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
  },
  planSectionPhase: {
    borderColor: colors.fitness.phaseAccent,
  },
  planSectionNutrition: {
    borderColor: colors.fitness.nutritionAccent,
  },
  planSectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
  },
  planSectionTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    flex: 1,
  },
  planSectionBody: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  planFullCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
});

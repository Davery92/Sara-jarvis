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
import WorkoutDetailModal from '../../components/fitness/WorkoutDetailModal';
import FoodLogModal from '../../components/fitness/FoodLogModal';
import NutritionGuide from '../../components/fitness/NutritionGuide';
import ProgressView from '../../components/fitness/views/ProgressView';
import { MacroRings, RecoveryScoreCard, StatTile, MuscleMap, musclesForWorkout } from '../../components/fitness/ui';
import { computeBaseline, computeReadinessScore } from '../../utils/recovery';
import { computePRs } from '../../utils/fitnessStats';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import ActiveWorkoutBanner from '../../components/fitness/ActiveWorkoutBanner';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { Ionicons } from '@expo/vector-icons';
import { navigateToChat } from '../../services/navigation';
import Markdown from 'react-native-markdown-display';

type Props = MainTabScreenProps<'Fitness'>;

type ViewMode = 'dashboard' | 'plan' | 'nutrition' | 'guide' | 'workout' | 'recovery' | 'programs' | 'progress';

// Time-of-day greeting (matches SaraPresenceFace convention).
function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning, David';
  if (h < 17) return 'Good afternoon, David';
  if (h < 22) return 'Good evening, David';
  return 'Still up, David';
}

export default function FitnessScreen({ navigation }: Props) {
  const { isActive: hasActiveWorkout, startWorkout } = useWorkoutMode();
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showWorkoutModal, setShowWorkoutModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedWorkout, setSelectedWorkout] = useState<WorkoutSession | null>(null);
  const [viewWorkout, setViewWorkout] = useState<WorkoutSession | null>(null);
  const [showViewModal, setShowViewModal] = useState(false);
  const [showFoodModal, setShowFoodModal] = useState(false);
  const [selectedMealType, setSelectedMealType] = useState('snack');
  const [editingFoodLog, setEditingFoodLog] = useState<FoodLog | null>(null);
  // The other detailed_items in editingFoodLog's meal, so FoodLogModal's save
  // can send the whole meal back instead of silently dropping siblings.
  const [editingFoodSiblings, setEditingFoodSiblings] = useState<any[]>([]);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [selectedDate, setSelectedDate] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  });

  // Data states
  const [foodLogs, setFoodLogs] = useState<FoodLog[]>([]);
  // Earliest date loadData/loadOlderFoodLogs has actually fetched food logs
  // for. selectedDate can be navigated further back than this (Prev has no
  // lower bound) - when it does, foodLogs legitimately has zero rows for
  // that day because it was never fetched, not because nothing was logged.
  const [loadedFoodRangeStart, setLoadedFoodRangeStart] = useState<string | null>(null);
  const [loadingHistoricalDate, setLoadingHistoricalDate] = useState(false);
  const [workoutLogs, setWorkoutLogs] = useState<WorkoutSession[]>([]);
  const [recoveryLogs, setRecoveryLogs] = useState<RecoveryLog[]>([]);
  const [dailySummary, setDailySummary] = useState<any>(null);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [templates, setTemplates] = useState<WorkoutTemplate[]>([]);
  const [nutritionGoals, setNutritionGoals] = useState<NutritionGoals | null>(null);
  const [activePhase, setActivePhase] = useState<Phase | null>(null);
  const [activeProgram, setActiveProgram] = useState<Program | null>(null);
  const [todaysTemplates, setTodaysTemplates] = useState<WorkoutTemplate[]>([]);
  const [planViewMode, setPlanViewMode] = useState<'sections' | 'full'>('sections');
  const [expandedPlanSections, setExpandedPlanSections] = useState<Set<number>>(new Set());
  // Programs tab accordion: which phases / templates are expanded
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [expandedTemplates, setExpandedTemplates] = useState<Set<string>>(new Set());
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

  // Auto-expand the active phase in the Programs accordion once it's known.
  useEffect(() => {
    if (activePhase?.id) {
      setExpandedPhases(prev => (prev.has(activePhase.id) ? prev : new Set(prev).add(activePhase.id)));
    }
  }, [activePhase?.id]);

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
      const summary = await fitnessService.getDailySummary(today).catch(() => null);
      const phasesData = await fitnessService.getPhases().catch(() => ({ phases: [] }));
      const templatesData = await fitnessService.getTemplates().catch(() => ({ templates: [] }));
      const todayTemplatesData = await fitnessService.getTodaysTemplates().catch(() => ({ templates: [] }));

      setFoodLogs(food);
      setLoadedFoodRangeStart(weekAgo);
      setWorkoutLogs(workouts);
      setRecoveryLogs(recovery);
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

  // After creating/editing/deleting a phase or starting a block from PhaseForm.
  const refreshPhasesAndProgram = async () => {
    await Promise.all([loadData(), loadNutritionGoalsWithPhase()]);
  };

  // Prev/Next in the nutrition diary can navigate selectedDate arbitrarily
  // far back, past the week loadData fetched. Extend the loaded window
  // backward to cover it instead of letting the diary render 0 entries for
  // a day that was simply never fetched.
  useEffect(() => {
    if (!loadedFoodRangeStart || selectedDate >= loadedFoodRangeStart) return;

    let cancelled = false;
    setLoadingHistoricalDate(true);
    const rangeEnd = (() => {
      // Fetch up to (but not overlapping) the currently loaded start.
      const [y, m, d] = loadedFoodRangeStart.split('-').map(Number);
      const dayBefore = new Date(y, m - 1, d - 1);
      return `${dayBefore.getFullYear()}-${String(dayBefore.getMonth() + 1).padStart(2, '0')}-${String(dayBefore.getDate()).padStart(2, '0')}`;
    })();

    fitnessService.getFoodLogs(selectedDate, rangeEnd)
      .then((older) => {
        if (cancelled) return;
        setFoodLogs((prev) => [...older, ...prev]);
        setLoadedFoodRangeStart(selectedDate);
      })
      .catch((error) => {
        console.error('Failed to load older food logs:', error);
      })
      .finally(() => {
        if (!cancelled) setLoadingHistoricalDate(false);
      });

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate, loadedFoodRangeStart]);

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
    // Full edit (quantity/serving/macros) needs this item's own rehydratable
    // detailed_item snapshot. For a multi-item meal it ALSO needs every
    // sibling item in that meal to carry one, since saving replaces the
    // whole row's items — an unreconstructable sibling would otherwise be
    // silently dropped. Recipe entries collapse to a single FoodLog row (see
    // fitness.ts isRecipe branch) so they never reach the sibling check.
    const siblings = foodLogs.filter(
      (l) => l.meal_log_id === log.meal_log_id && l.id !== log.id
    );
    const canFullyEdit = !!log.detailed_item
      && siblings.every((s) => !!s.detailed_item);

    if (canFullyEdit) {
      setEditingFoodLog(log);
      setEditingFoodSiblings(siblings.map((s) => s.detailed_item));
      return;
    }

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
    // Open the clean read-only detail modal (replaces the old Alert text dump).
    setViewWorkout(session);
    setShowViewModal(true);
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

    // Recovery hero — score today's recovery against the loaded window baseline.
    const sortedRecovery = [...recoveryLogs].filter(l => l.log_date).sort((a, b) => (a.log_date < b.log_date ? -1 : 1));
    const latestRecovery = sortedRecovery[sortedRecovery.length - 1] ?? null;
    const recoveryBaseline = computeBaseline(recoveryLogs);
    const recoveryScore = computeReadinessScore(latestRecovery, recoveryBaseline);
    const recoveryScores = sortedRecovery
      .map(l => computeReadinessScore(l, recoveryBaseline)?.score)
      .filter((s): s is number => typeof s === 'number');
    const avgRecovery = recoveryScores.length
      ? Math.round(recoveryScores.reduce((s, v) => s + v, 0) / recoveryScores.length)
      : null;
    const recoveryDelta = recoveryScore && avgRecovery != null ? recoveryScore.score - avgRecovery : null;
    const proteinHit = totalProtein >= goals.protein * 0.9;
    const workoutDoneToday = todaysWorkouts.length > 0;
    const recoveryLoggedToday = !!latestRecovery && latestRecovery.log_date === todayStr;
    const tasks = [
      { label: 'Log workout', done: workoutDoneToday, onPress: handleLogWorkout },
      { label: 'Hit protein goal', done: proteinHit, onPress: () => setViewMode('nutrition') },
      { label: 'Log recovery', done: recoveryLoggedToday, onPress: handleLogRecovery },
    ];
    const tasksDone = tasks.filter(t => t.done).length;

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
        {/* A workout started on the Watch has to be one obvious tap away the
            moment David opens the app — without the app ever forcing itself
            to the foreground mid-set (§9.2). */}
        <ActiveWorkoutBanner />

        {/* Greeting */}
        <View style={styles.greetingRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.greetingText}>{greeting()} 👋</Text>
            <Text style={styles.greetingSub}>Let's crush today.</Text>
          </View>
        </View>

        {/* Recovery score hero */}
        <View style={{ marginBottom: spacing.md }}>
          <RecoveryScoreCard
            score={recoveryScore}
            log={latestRecovery}
            delta={recoveryDelta}
            onPress={() => setViewMode('progress')}
          />
        </View>

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
                <Ionicons name={hasActiveWorkout ? 'play' : 'barbell'} size={16} color={colors.text} />
                <Text style={styles.todayStartButtonText}>
                  {hasActiveWorkout ? 'Resume workout' : 'Start workout'}
                </Text>
              </TouchableOpacity>
              {!hasActiveWorkout && (
                <TouchableOpacity
                  style={styles.todaySwitchButton}
                  onPress={() => setShowTemplatePicker(true)}
                >
                  <Ionicons name="swap-horizontal" size={14} color={colors.textSecondary} />
                  <Text style={styles.todaySwitchButtonText}>Do a different workout</Text>
                </TouchableOpacity>
              )}
            </>
          ) : (
            <>
              <Text style={styles.todayEmpty}>
                {isTrainingDay === false
                  ? 'No workout scheduled — recovery focus.'
                  : 'No workout scheduled for today.'}
              </Text>
              <TouchableOpacity
                style={[styles.todayStartButton, { marginTop: spacing.sm }]}
                onPress={() => setShowTemplatePicker(true)}
              >
                <Ionicons name="barbell" size={16} color={colors.text} />
                <Text style={styles.todayStartButtonText}>Choose a workout</Text>
              </TouchableOpacity>
            </>
          )}
        </View>

        <TouchableOpacity style={styles.cardioEntry} onPress={() => navigation.navigate('Cardio' as any)}>
          <View style={styles.cardioEntryIcon}>
            <Ionicons name="pulse" size={20} color={colors.accent} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardioEntryTitle}>Cardio</Text>
            <Text style={styles.cardioEntrySub}>Weekly dose, menu quick-log & Tabata timer</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.textSecondary} />
        </TouchableOpacity>

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

        {/* Today's macros — ring summary */}
        <View style={styles.macrosCard}>
          <View style={styles.macrosHeader}>
            <Text style={styles.macrosTitle}>Nutrition</Text>
            <TouchableOpacity onPress={() => setViewMode('nutrition')}>
              <Text style={styles.seeAllText}>Details →</Text>
            </TouchableOpacity>
          </View>
          <MacroRings
            compact
            totals={{ calories: totalCalories, protein: totalProtein, carbs: totalCarbs, fats: totalFats }}
            goals={goals}
          />
        </View>

        {/* Today's tasks */}
        <View style={styles.macrosCard}>
          <View style={styles.macrosHeader}>
            <Text style={styles.macrosTitle}>Today's tasks</Text>
            <Text style={styles.tasksCount}>{tasksDone} / {tasks.length} completed</Text>
          </View>
          {tasks.map(task => (
            <TouchableOpacity key={task.label} style={styles.taskRow} onPress={task.onPress} activeOpacity={0.7}>
              <Ionicons
                name={task.done ? 'checkbox' : 'square-outline'}
                size={22}
                color={task.done ? colors.primary : colors.textMuted}
              />
              <Text style={[styles.taskLabel, task.done && styles.taskLabelDone]}>{task.label}</Text>
            </TouchableOpacity>
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

  const renderWorkoutView = () => {
    const todaysTemplate = todaysTemplates[0] ?? null;
    const focusMuscles = todaysTemplate?.exercises?.length
      ? Array.from(
          new Set(
            todaysTemplate.exercises
              .map((e: any) => e.muscle_group || e.target)
              .filter(Boolean),
          ),
        ).slice(0, 3).join(', ')
      : null;
    const prs = computePRs(workoutLogs, 3);

    return (
      <ScrollView
        style={styles.content}
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        {/* Today's workout hero */}
        <Text style={styles.trainSectionTitle}>Today's Workout</Text>
        <View style={styles.trainHero}>
          {todaysTemplate ? (
            <>
              <View style={styles.trainHeroTopRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.trainHeroName}>{todaysTemplate.name}</Text>
                  <Text style={styles.trainHeroMeta}>
                    {todaysTemplate.exercises?.length || 0} exercises
                    {todaysTemplate.exercises?.length ? ` · ~${Math.max(30, todaysTemplate.exercises.length * 9)} min` : ''}
                  </Text>
                  {focusMuscles ? (
                    <Text style={styles.trainHeroFocus}>Focus: {focusMuscles}</Text>
                  ) : null}
                </View>
                <View style={styles.trainHeroMuscle}>
                  <MuscleMap highlighted={musclesForWorkout(todaysTemplate)} width={86} height={126} />
                </View>
              </View>
              <TouchableOpacity
                style={styles.trainStartButton}
                onPress={() => {
                  if (hasActiveWorkout) {
                    navigation.navigate('WorkoutMode' as any);
                  } else {
                    handleStartWorkout(todaysTemplate.id);
                  }
                }}
              >
                <Ionicons name={hasActiveWorkout ? 'play' : 'barbell'} size={16} color={colors.background} />
                <Text style={styles.trainStartButtonText}>
                  {hasActiveWorkout ? 'Resume Workout' : 'Start Workout'}
                </Text>
              </TouchableOpacity>
              {!hasActiveWorkout && (
                <TouchableOpacity
                  style={styles.todaySwitchButton}
                  onPress={() => setShowTemplatePicker(true)}
                >
                  <Ionicons name="swap-horizontal" size={14} color={colors.textSecondary} />
                  <Text style={styles.todaySwitchButtonText}>Do a different workout</Text>
                </TouchableOpacity>
              )}
            </>
          ) : (
            <>
              <Text style={styles.trainHeroName}>No workout scheduled</Text>
              <Text style={styles.trainHeroMeta}>Pick a session to start training.</Text>
              <TouchableOpacity
                style={[styles.trainStartButton, { marginTop: spacing.md }]}
                onPress={() => setShowTemplatePicker(true)}
              >
                <Ionicons name="barbell" size={16} color={colors.background} />
                <Text style={styles.trainStartButtonText}>Choose Workout</Text>
              </TouchableOpacity>
            </>
          )}
        </View>

        {/* Recent workouts */}
        <View style={styles.listHeader}>
          <Text style={styles.listHeaderTitle}>Recent Workouts</Text>
          <TouchableOpacity onPress={handleLogWorkout}>
            <Text style={styles.seeAllText}>+ Log</Text>
          </TouchableOpacity>
        </View>
        {workoutLogs.length ? (
          workoutLogs.slice(0, 6).map((session) => (
            <WorkoutSessionItem
              key={session.id}
              session={session}
              onPress={handleViewWorkout}
              onLongPress={handleLongPressWorkout}
            />
          ))
        ) : (
          <Text style={styles.emptyText}>No workouts logged yet. Tap + Log to add one!</Text>
        )}

        {/* Personal records */}
        {prs.length ? (
          <>
            <View style={[styles.listHeader, { marginTop: spacing.md }]}>
              <Text style={styles.listHeaderTitle}>Personal Records</Text>
            </View>
            <View style={styles.prRow}>
              {prs.map(pr => (
                <StatTile key={pr.exercise} label={pr.exercise} value={pr.weight} unit="lbs" accent={colors.accent} />
              ))}
            </View>
          </>
        ) : null}
      </ScrollView>
    );
  };

  // Per-phase week progress (mirrors the dashboard hero calc, for any phase).
  const phaseProgressFor = (phase: Phase) => {
    const start = phase.start_date ? new Date(phase.start_date + 'T00:00:00') : null;
    const end = phase.end_date ? new Date(phase.end_date + 'T00:00:00') : null;
    const now = new Date();
    const totalWeeks = phase.duration_weeks ?? (start && end
      ? Math.max(1, Math.round((end.getTime() - start.getTime()) / (7 * 24 * 3600 * 1000)))
      : null);
    const currentWeek = start
      ? Math.max(1, Math.floor((now.getTime() - start.getTime()) / (7 * 24 * 3600 * 1000)) + 1)
      : null;
    return { currentWeek, totalWeeks };
  };

  const togglePhase = (id: string) =>
    setExpandedPhases(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleTemplate = (id: string) =>
    setExpandedTemplates(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const formatDays = (days?: string[]) =>
    (days && days.length)
      ? days.map(d => d.charAt(0).toUpperCase() + d.slice(1, 3)).join(', ')
      : null;

  const formatExercise = (ex: any): { name: string; detail: string } => {
    const sets = ex.sets ?? ex.target_sets;
    const reps = ex.reps ?? ex.target_reps;
    const rpe = ex.rpe_target ?? ex.rpe;
    const name = ex.name || ex.exercise_name || 'Exercise';
    let detail = '';
    if (sets != null && reps != null) detail = `${sets}×${reps}`;
    else if (sets != null) detail = `${sets} sets`;
    else if (reps != null) detail = `${reps} reps`;
    if (rpe != null) detail += `${detail ? ' ' : ''}@ RPE ${rpe}`;
    return { name, detail };
  };

  // Build the macro target chips for a phase (cycling-aware).
  const phaseMacroChips = (phase: Phase): { label: string; value: string }[] => {
    const cyc = (t?: number, r?: number, base?: number): string | null => {
      if (t != null || r != null) return `${t ?? '–'} / ${r ?? '–'}`;
      return base != null ? String(base) : null;
    };
    const chips: { label: string; value: string }[] = [];
    const cal = cyc(phase.calories_training_day, phase.calories_rest_day, phase.calories_target);
    if (cal) chips.push({ label: 'Cal', value: cal });
    if (phase.protein_target != null) chips.push({ label: 'Protein', value: `${phase.protein_target}g` });
    const carbs = cyc(phase.carbs_training_day, phase.carbs_rest_day, phase.carbs_target);
    if (carbs) chips.push({ label: 'Carbs', value: `${carbs}g` });
    const fat = cyc(phase.fat_training_day, phase.fat_rest_day, phase.fat_target);
    if (fat) chips.push({ label: 'Fat', value: `${fat}g` });
    return chips;
  };

  const renderTemplateCard = (template: WorkoutTemplate) => {
    const isOpen = expandedTemplates.has(template.id);
    const days = formatDays(template.scheduled_days);
    const exCount = template.exercises?.length || 0;
    return (
      <View key={template.id} style={styles.templateCard}>
        <TouchableOpacity
          style={styles.templateHeader}
          onPress={() => toggleTemplate(template.id)}
          activeOpacity={0.7}
        >
          <Ionicons
            name={isOpen ? 'chevron-down' : 'chevron-forward'}
            size={16}
            color={colors.textSecondary}
          />
          <View style={{ flex: 1 }}>
            <Text style={styles.templateCardTitle}>{template.name}</Text>
            <Text style={styles.templateCardMeta}>
              {days ? `${days} · ` : ''}{exCount} exercise{exCount === 1 ? '' : 's'}
            </Text>
          </View>
        </TouchableOpacity>

        {isOpen ? (
          <View style={styles.templateBody}>
            {exCount > 0 ? (
              template.exercises.map((ex: any, i: number) => {
                const { name, detail } = formatExercise(ex);
                return (
                  <View key={i} style={styles.exerciseRow}>
                    <Text style={styles.exerciseName}>{name}</Text>
                    {detail ? <Text style={styles.exerciseDetail}>{detail}</Text> : null}
                  </View>
                );
              })
            ) : (
              <Text style={styles.exerciseDetail}>No exercises in this template yet.</Text>
            )}
            <TouchableOpacity
              style={styles.startTemplateBtn}
              onPress={() => {
                if (hasActiveWorkout) {
                  navigation.navigate('WorkoutMode' as any);
                } else {
                  handleStartWorkout(template.id);
                }
              }}
            >
              <Ionicons name={hasActiveWorkout ? 'play' : 'barbell'} size={15} color={colors.text} />
              <Text style={styles.startTemplateBtnText}>
                {hasActiveWorkout ? 'Resume workout' : 'Start workout'}
              </Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </View>
    );
  };

  const renderProgramsView = () => {
    // Only the active program's phases. The full /phases list also carries
    // phases from old/swapped-out programs (program_id differs); showing them
    // clutters the tab. Fall back to active/planned phases when there's no
    // program wrapper at all.
    const activeProgramId = activeProgram?.id ?? null;
    const visiblePhases = activeProgramId
      ? phases.filter(p => p.program_id === activeProgramId)
      : phases.filter(p => p.status === 'active' || p.status === 'planned');
    const phaseIds = new Set(visiblePhases.map(p => p.id));
    const sortedPhases = [...visiblePhases].sort((a, b) => {
      const oa = a.order_index ?? 999;
      const ob = b.order_index ?? 999;
      if (oa !== ob) return oa - ob;
      return (a.start_date || '').localeCompare(b.start_date || '');
    });
    const templatesForPhase = (phaseId: string) =>
      templates
        .filter(t => t.phase_id === phaseId)
        .sort((a, b) => (a.order_in_phase ?? 999) - (b.order_in_phase ?? 999));
    // Standalone workouts only (no phase). Templates tied to another program's
    // phase are intentionally dropped, not surfaced as "orphans".
    const orphanTemplates = templates.filter(t => !t.phase_id);

    return (
      <ScrollView
        style={styles.content}
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        <View style={styles.viewHeader}>
          <TouchableOpacity onPress={() => setViewMode('dashboard')}>
            <Text style={styles.backButton}>← Back</Text>
          </TouchableOpacity>
        </View>

        {/* Program header */}
        {activeProgram ? (
          <View style={styles.programHeader}>
            <Text style={styles.programEyebrow}>Current program</Text>
            <Text style={styles.programName}>{activeProgram.name}</Text>
            {activeProgram.goal ? (
              <Text style={styles.programGoal}>{activeProgram.goal}</Text>
            ) : null}
            {activeProgram.plan_markdown ? (
              <TouchableOpacity style={styles.programPlanLink} onPress={() => setViewMode('plan')}>
                <Ionicons name="book-outline" size={14} color={colors.primary} />
                <Text style={styles.programPlanLinkText}>Read full plan</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ) : (
          <View style={[styles.programHeader, { borderColor: colors.border }]}>
            <Text style={styles.programName}>No active program</Text>
            <Text style={styles.programGoal}>Ask Sara to build a plan, or import one on the web app.</Text>
          </View>
        )}

        {/* Phases accordion */}
        <View style={styles.phasesSectionHeader}>
          <Text style={[styles.sectionTitle, { paddingHorizontal: 0, marginBottom: 0 }]}>
            Phases ({visiblePhases.length})
          </Text>
          {activeProgram ? (
            <TouchableOpacity
              style={styles.startBlockButton}
              onPress={() => navigation.navigate('PhaseForm', { mode: 'block', onSave: refreshPhasesAndProgram })}
            >
              <Ionicons name="cut-outline" size={14} color={colors.warning} />
              <Text style={styles.startBlockButtonText}>Start a block…</Text>
            </TouchableOpacity>
          ) : null}
        </View>
        {sortedPhases.map((phase) => {
          const isOpen = expandedPhases.has(phase.id);
          const isActive = phase.status === 'active';
          const prog = phaseProgressFor(phase);
          const phaseTemplates = templatesForPhase(phase.id);
          const chips = phaseMacroChips(phase);
          return (
            <View
              key={phase.id}
              style={[styles.phaseCard, isActive && styles.phaseCardActive]}
            >
              <View style={styles.phaseHeader}>
                <TouchableOpacity
                  style={styles.phaseHeaderToggle}
                  onPress={() => togglePhase(phase.id)}
                  activeOpacity={0.7}
                >
                  <Ionicons
                    name={isOpen ? 'chevron-down' : 'chevron-forward'}
                    size={18}
                    color={colors.textSecondary}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.phaseTitle}>
                      {isActive ? '🔥 ' : ''}{phase.name}
                    </Text>
                    <Text style={styles.phaseSubtitle}>
                      {phase.status}
                      {prog.currentWeek && prog.totalWeeks
                        ? ` · wk ${Math.min(prog.currentWeek, prog.totalWeeks)}/${prog.totalWeeks}`
                        : ''}
                      {phaseTemplates.length ? ` · ${phaseTemplates.length} workouts` : ''}
                    </Text>
                  </View>
                </TouchableOpacity>
                {phase.deload_week ? (
                  <View style={styles.deloadBadge}>
                    <Text style={styles.deloadBadgeText}>DELOAD</Text>
                  </View>
                ) : null}
                <TouchableOpacity
                  style={styles.phaseEditButton}
                  onPress={() => navigation.navigate('PhaseForm', { phase, mode: 'edit', onSave: refreshPhasesAndProgram })}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                >
                  <Ionicons name="pencil" size={16} color={colors.textSecondary} />
                </TouchableOpacity>
              </View>

              {isOpen ? (
                <View style={styles.phaseBody}>
                  {phase.goal ? <Text style={styles.phaseGoal}>{phase.goal}</Text> : null}

                  {/* Week progress bar */}
                  {prog.currentWeek && prog.totalWeeks ? (
                    <View style={styles.phaseProgressBar}>
                      <View
                        style={[
                          styles.phaseProgressBarFill,
                          { width: `${Math.min(100, (prog.currentWeek / prog.totalWeeks) * 100)}%` },
                        ]}
                      />
                    </View>
                  ) : null}

                  {/* Macro target chips */}
                  {chips.length ? (
                    <View style={styles.macroChips}>
                      {chips.map(c => (
                        <View key={c.label} style={styles.macroChip}>
                          <Text style={styles.macroChipLabel}>{c.label}</Text>
                          <Text style={styles.macroChipVal}>{c.value}</Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  {(phase.calories_training_day != null || phase.carbs_training_day != null) ? (
                    <Text style={styles.macroHint}>Training / Rest day targets</Text>
                  ) : null}

                  {/* Templates under this phase */}
                  {phaseTemplates.length ? (
                    phaseTemplates.map(renderTemplateCard)
                  ) : (
                    <Text style={styles.phaseEmptyText}>No workouts in this phase yet.</Text>
                  )}
                </View>
              ) : null}
            </View>
          );
        })}
        {visiblePhases.length === 0 ? (
          <Text style={styles.emptyText}>No training phases yet.</Text>
        ) : null}

        {/* Templates not tied to any phase */}
        {orphanTemplates.length ? (
          <>
            <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
              Other workouts ({orphanTemplates.length})
            </Text>
            <View style={styles.orphanWrap}>
              {orphanTemplates.map(renderTemplateCard)}
            </View>
          </>
        ) : null}
      </ScrollView>
    );
  };

  const renderGuideView = () => (
    <ScrollView
      style={styles.content}
      contentContainerStyle={{ paddingBottom: spacing.xxl }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.viewHeader}>
        <TouchableOpacity onPress={() => setViewMode('nutrition')}>
          <Text style={styles.backButton}>← Nutrition</Text>
        </TouchableOpacity>
      </View>
      <NutritionGuide />
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

        {/* Prev navigated past the loaded week — fetching that date's real
            data now, so meal sections below don't render a false "nothing
            logged" for a day that just hasn't loaded yet. */}
        {loadingHistoricalDate && (
          <View style={styles.historicalLoadingBanner}>
            <ActivityIndicator size="small" color={colors.accent} />
            <Text style={styles.historicalLoadingText}>Loading {selectedDate}…</Text>
          </View>
        )}

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

        {/* Link to the recomp nutrition guide */}
        <TouchableOpacity style={styles.guideLink} onPress={() => setViewMode('guide')}>
          <Ionicons name="book-outline" size={16} color={colors.accent} />
          <Text style={styles.guideLinkText}>Recomp Nutrition Guide</Text>
          <View style={{ flex: 1 }} />
          <Ionicons name="chevron-forward" size={16} color={colors.textSecondary} />
        </TouchableOpacity>

        {/* Macro rings summary */}
        <View style={styles.eatRingsCard}>
          <MacroRings
            totals={{ calories: totalCalories, protein: totalProtein, carbs: totalCarbs, fats: totalFat }}
            goals={{ calories: goalCalories, protein: goalProtein, carbs: goalCarbs, fats: goalFats }}
          />
          <View style={styles.eatRemainingRow}>
            <Text style={[styles.eatRemaining, remainingCalories >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
              {remainingCalories >= 0 ? `${remainingCalories} kcal remaining` : `${Math.abs(remainingCalories)} kcal over`}
            </Text>
          </View>
          {/* Per-macro remaining (grams) — not just calories */}
          <View style={{ flexDirection: 'row', justifyContent: 'space-around', width: '100%', marginTop: spacing.sm }}>
            {[
              { label: 'Protein', val: remainingProtein },
              { label: 'Carbs', val: remainingCarbs },
              { label: 'Fat', val: remainingFat },
            ].map((m) => (
              <View key={m.label} style={{ alignItems: 'center' }}>
                <Text style={[{ fontSize: 15, fontWeight: '700' }, m.val >= 0 ? styles.remainingPositive : styles.remainingNegative]}>
                  {m.val >= 0 ? `${Math.round(m.val)}g` : `+${Math.abs(Math.round(m.val))}g`}
                </Text>
                <Text style={{ fontSize: 11, color: colors.textSecondary }}>
                  {m.label}{m.val >= 0 ? ' left' : ' over'}
                </Text>
              </View>
            ))}
          </View>
        </View>

        {/* Meal Sections */}
        <View style={styles.listHeader}>
          <Text style={styles.listHeaderTitle}>Meals</Text>
          <TouchableOpacity onPress={handleLogFood}>
            <Text style={styles.seeAllText}>+ Add</Text>
          </TouchableOpacity>
        </View>

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
      <WorkoutDetailModal
        visible={showViewModal}
        session={viewWorkout}
        onClose={() => {
          setShowViewModal(false);
          setViewWorkout(null);
        }}
        onEdit={(session) => {
          setShowViewModal(false);
          setViewWorkout(null);
          handleEditWorkout(session);
        }}
      />
      <FoodLogModal
        visible={showFoodModal || !!editingFoodLog}
        onClose={() => {
          setShowFoodModal(false);
          setEditingFoodLog(null);
          setEditingFoodSiblings([]);
        }}
        onComplete={() => {
          setShowFoodModal(false);
          setEditingFoodLog(null);
          setEditingFoodSiblings([]);
          loadData();
        }}
        initialMealType={selectedMealType}
        editEntry={editingFoodLog ? {
          id: editingFoodLog.meal_log_id,
          meal_type: editingFoodLog.meal_type,
          logged_at: editingFoodLog.logged_at,
          notes: editingFoodLog.notes,
          item: editingFoodLog.detailed_item,
          siblingItems: editingFoodSiblings,
        } : null}
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
                  <Ionicons name="chevron-forward" size={20} color={template.is_today ? colors.success : colors.textMuted} />
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
          style={[styles.tab, viewMode === 'guide' && styles.tabActive]}
          onPress={() => setViewMode('guide')}
        >
          <Text style={[styles.tabText, viewMode === 'guide' && styles.tabTextActive]}>
            Guide
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
          style={[styles.tab, viewMode === 'progress' && styles.tabActive]}
          onPress={() => setViewMode('progress')}
        >
          <Text style={[styles.tabText, viewMode === 'progress' && styles.tabTextActive]}>
            Progress
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
      {viewMode === 'guide' && renderGuideView()}
      {viewMode === 'workout' && renderWorkoutView()}
      {viewMode === 'progress' && (
        <ProgressView
          onLogRecovery={handleLogRecovery}
          onEditRecovery={handleEditRecovery}
          onDeleteRecovery={handleDeleteRecovery}
        />
      )}
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
    backgroundColor: colors.background,
    flexGrow: 0,
    flexShrink: 0,
    maxHeight: 50,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  tab: {
    paddingVertical: spacing.xs + 3,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabActive: {
    backgroundColor: colors.assistant.actionSoft,
    borderColor: colors.assistant.borderStrong,
  },
  tabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  tabTextActive: {
    color: colors.accent,
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
    backgroundColor: colors.success,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 6,
  },
  resumeWorkoutButton: {
    backgroundColor: colors.primary,
  },
  startWorkoutButtonText: {
    color: colors.text,
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
    backgroundColor: colors.assistant.successSoft,
    borderWidth: 1,
    borderColor: colors.success,
  },
  todayBadge: {
    backgroundColor: colors.success,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  todayBadgeText: {
    color: colors.background,
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
  cardioEntry: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  cardioEntryIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.assistant.actionSoft,
  },
  cardioEntryTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  cardioEntrySub: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
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
    color: colors.error,
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
  historicalLoadingBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  historicalLoadingText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
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

  // Greeting
  greetingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  greetingText: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
  },
  greetingSub: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },

  // Today's tasks
  tasksCount: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  taskRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs + 2,
  },
  taskLabel: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  taskLabelDone: {
    color: colors.textMuted,
    textDecorationLine: 'line-through',
  },

  // Shared list header (row title + action), inset to match list items
  listHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  listHeaderTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },

  // Train view
  trainSectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    paddingHorizontal: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  trainHero: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.lg,
    overflow: 'hidden',
  },
  trainHeroTopRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  trainHeroName: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  trainHeroMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 4,
  },
  trainHeroFocus: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 6,
  },
  trainHeroMuscle: {
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: spacing.sm,
  },
  trainStartButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.sm + 2,
    marginTop: spacing.md,
  },
  trainStartButtonText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  prRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
  },

  // Eat view
  eatRingsCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  eatRemainingRow: {
    alignItems: 'center',
    marginTop: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  eatRemaining: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
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
    color: colors.background,
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
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  todaySwitchButton: {
    marginTop: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.xs,
  },
  todaySwitchButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },

  // Macros card
  macrosCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
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
    color: colors.text,
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

  // --- Nutrition guide link (in Nutrition view) ---
  guideLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  guideLinkText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },

  // --- Programs accordion ---
  programHeader: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.fitness.phaseAccent,
    padding: spacing.md,
    marginHorizontal: spacing.md,
  },
  programEyebrow: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  programName: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
  },
  programGoal: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
    lineHeight: 20,
  },
  programPlanLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  programPlanLinkText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  phaseCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
  },
  phaseCardActive: {
    borderColor: colors.fitness.phaseAccent,
  },
  phaseHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
  },
  phaseHeaderToggle: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  phaseEditButton: {
    padding: spacing.xs,
  },
  phasesSectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  startBlockButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.warning,
    backgroundColor: 'rgba(251, 191, 36, 0.1)',
  },
  startBlockButtonText: {
    color: colors.warning,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  phaseTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  phaseSubtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: 2,
    textTransform: 'capitalize',
  },
  phaseBody: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.sm,
    paddingTop: spacing.sm,
  },
  phaseGoal: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  phaseEmptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
  macroChips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  macroChip: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  macroChipLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  macroChipVal: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
  macroHint: {
    color: colors.textMuted,
    fontSize: 11,
    fontStyle: 'italic',
  },
  orphanWrap: {
    marginBottom: spacing.sm,
  },
  templateCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginHorizontal: spacing.md,
    marginBottom: spacing.xs,
    overflow: 'hidden',
  },
  templateHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.sm,
  },
  templateCardTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  templateCardMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: 1,
    textTransform: 'capitalize',
  },
  templateBody: {
    paddingHorizontal: spacing.sm,
    paddingBottom: spacing.sm,
    gap: spacing.xs,
  },
  exerciseRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 4,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  exerciseName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    flex: 1,
    paddingRight: spacing.sm,
  },
  exerciseDetail: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  startTemplateBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    marginTop: spacing.xs,
  },
  startTemplateBtnText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
});

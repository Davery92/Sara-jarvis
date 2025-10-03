/**
 * Habits Store - Zustand
 *
 * Manages habit tracking state:
 * - Today's habits
 * - Habit definitions
 * - Streaks
 * - Progress tracking
 */

import { create } from 'zustand';

export interface Habit {
  id: string;
  title: string;
  type: 'binary' | 'quantitative' | 'checklist' | 'time_based';
  target_numeric?: number;
  unit?: string;
  rrule?: string;
  created_at: string;
  updated_at: string;
}

export interface HabitInstance {
  id: string;
  habit_id: string;
  date: string;
  window?: string;
  expected: boolean;
  status: 'pending' | 'in_progress' | 'complete' | 'skipped';
  progress: number;
  total_amount?: number;
  target?: number;
  title: string;
  type: string;
  unit?: string;
}

export interface HabitStreak {
  habit_id: string;
  current_streak: number;
  best_streak: number;
  last_completed?: string;
}

interface HabitTodayStats {
  total: number;
  completed: number;
  in_progress: number;
  completion_rate: number;
}

interface HabitsState {
  habits: Habit[];
  todayHabits: HabitInstance[];
  streaks: Map<string, HabitStreak>;
  todayStats: HabitTodayStats | null;
  selectedDate: string;

  // Actions
  setHabits: (habits: Habit[]) => void;
  setTodayHabits: (habits: HabitInstance[]) => void;
  setStreak: (habitId: string, streak: HabitStreak) => void;
  setTodayStats: (stats: HabitTodayStats) => void;
  updateHabitInstance: (instanceId: string, updates: Partial<HabitInstance>) => void;
  setSelectedDate: (date: string) => void;

  // Computed
  getHabitById: (id: string) => Habit | undefined;
  getTodayHabitByHabitId: (habitId: string) => HabitInstance | undefined;
  getCompletionRate: () => number;
}

export const useHabitsStore = create<HabitsState>((set, get) => ({
  habits: [],
  todayHabits: [],
  streaks: new Map(),
  todayStats: null,
  selectedDate: new Date().toISOString().split('T')[0],

  setHabits: (habits) => set({ habits }),

  setTodayHabits: (habits) => set({ todayHabits: habits }),

  setStreak: (habitId, streak) => set((state) => {
    const newStreaks = new Map(state.streaks);
    newStreaks.set(habitId, streak);
    return { streaks: newStreaks };
  }),

  setTodayStats: (stats) => set({ todayStats: stats }),

  updateHabitInstance: (instanceId, updates) => set((state) => ({
    todayHabits: state.todayHabits.map(habit =>
      habit.id === instanceId ? { ...habit, ...updates } : habit
    )
  })),

  setSelectedDate: (date) => set({ selectedDate: date }),

  getHabitById: (id) => {
    const { habits } = get();
    return habits.find(h => h.id === id);
  },

  getTodayHabitByHabitId: (habitId) => {
    const { todayHabits } = get();
    return todayHabits.find(h => h.habit_id === habitId);
  },

  getCompletionRate: () => {
    const { todayStats } = get();
    return todayStats?.completion_rate || 0;
  },
}));

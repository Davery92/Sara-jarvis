import React, { useState, useEffect } from 'react';
import { CheckCircle, Circle, Target, Zap, Calendar, Plus, TrendingUp, Edit3, Trash2 } from 'lucide-react';
import { apiRequest } from '../utils/api';

interface HabitInstance {
  instance_id: string;
  habit_id: string;
  title: string;
  type: 'binary' | 'quantitative' | 'checklist' | 'time';
  status: 'pending' | 'in_progress' | 'complete';
  progress: number;
  target_numeric?: number;
  unit?: string;
  total_amount?: number;
  window?: string;
  current_streak: number;
  best_streak: number;
  checklist_items?: Array<{
    id: string;
    label: string;
    completed: boolean;
  }>;
}

interface HabitsResponse {
  date: string;
  habits: HabitInstance[];
  stats: {
    total: number;
    completed: number;
    in_progress: number;
    completion_rate: number;
  };
}

export default function HabitToday() {
  const [habits, setHabits] = useState<HabitInstance[]>([]);
  const [stats, setStats] = useState({
    total: 0,
    completed: 0,
    in_progress: 0,
    completion_rate: 0
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingHabit, setEditingHabit] = useState<HabitInstance | null>(null);
  const [showEditModal, setShowEditModal] = useState(false);

  useEffect(() => {
    loadTodaysHabits();
  }, []);

  const loadTodaysHabits = async () => {
    try {
      setLoading(true);
      const response = await apiRequest<HabitsResponse>('/habits/today');
      setHabits(response.habits);
      setStats(response.stats);
    } catch (err) {
      setError('Failed to load today\'s habits');
      console.error('Error loading habits:', err);
    } finally {
      setLoading(false);
    }
  };

  const logHabit = async (habitId: string, amount?: number) => {
    try {
      const payload: any = {};
      if (amount !== undefined) {
        payload.amount = amount;
      }

      await apiRequest(`/habits/${habitId}/log`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      // Reload habits to get updated progress
      await loadTodaysHabits();
    } catch (err) {
      console.error('Error logging habit:', err);
    }
  };

  const handleEditHabit = (habit: HabitInstance) => {
    setEditingHabit(habit);
    setShowEditModal(true);
  };

  const handleSaveEdit = async (updatedData: any) => {
    if (!editingHabit) return;
    
    try {
      await apiRequest(`/habits/${editingHabit.habit_id}`, {
        method: 'PATCH',
        body: JSON.stringify(updatedData)
      });
      
      setShowEditModal(false);
      setEditingHabit(null);
      await loadTodaysHabits(); // Refresh the list
    } catch (err) {
      console.error('Error updating habit:', err);
    }
  };

  const handleDeleteHabit = async (habitId: string, habitTitle: string) => {
    if (!confirm(`Are you sure you want to delete "${habitTitle}"? This will permanently remove all data for this habit.`)) {
      return;
    }
    
    try {
      await apiRequest(`/habits/${habitId}`, {
        method: 'DELETE'
      });
      
      // Refresh the list after deletion
      await loadTodaysHabits();
    } catch (err) {
      console.error('Error deleting habit:', err);
    }
  };

  const getProgressColor = (progress: number, status: string) => {
    if (status === 'complete') return 'text-green-400';
    if (progress > 0) return 'text-blue-400';
    return 'text-gray-500';
  };

  const getProgressBg = (progress: number, status: string) => {
    if (status === 'complete') return 'bg-green-900/30 border-green-700';
    if (progress > 0) return 'bg-blue-900/30 border-blue-700';
    return 'bg-gray-800 border-gray-700';
  };

  const renderHabitCard = (habit: HabitInstance) => {
    const progressColor = getProgressColor(habit.progress, habit.status);
    const progressBg = getProgressBg(habit.progress, habit.status);

    return (
      <div
        key={habit.instance_id}
        className={`p-4 rounded-lg transition-all duration-200 hover:bg-gray-750 ${progressBg}`}
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1">
            <h3 className="font-medium text-white mb-1">{habit.title}</h3>
            <div className="flex items-center space-x-3 text-sm text-gray-400">
              <span className="flex items-center">
                <Target className="w-4 h-4 mr-1" />
                {habit.type}
              </span>
              {habit.current_streak > 0 && (
                <span className="flex items-center">
                  <Zap className="w-4 h-4 mr-1 text-orange-500" />
                  {habit.current_streak} day streak
                </span>
              )}
            </div>
          </div>
          
          {/* Action Buttons */}
          <div className="flex items-center space-x-2">
            <button
              onClick={() => handleEditHabit(habit)}
              className="p-1.5 text-gray-400 hover:text-gray-300 hover:bg-gray-700 rounded-lg transition-colors"
              title="Edit habit"
            >
              <Edit3 className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleDeleteHabit(habit.habit_id, habit.title)}
              className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
              title="Delete habit"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <div className={`p-2 rounded-full ${progressColor}`}>
              {habit.status === 'complete' ? (
                <CheckCircle className="w-6 h-6" />
              ) : (
                <Circle className="w-6 h-6" />
              )}
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="mb-3">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-400">Progress</span>
            <span className={progressColor}>{Math.round(habit.progress * 100)}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all duration-300 ${
                habit.status === 'complete' ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${habit.progress * 100}%` }}
            />
          </div>
        </div>

        {/* Type-specific content */}
        {habit.type === 'quantitative' && (
          <div className="mb-3">
            <div className="text-sm text-gray-400 mb-2">
              {habit.total_amount || 0} / {habit.target_numeric} {habit.unit}
            </div>
            <div className="flex space-x-2">
              <QuickLogButton 
                habitId={habit.habit_id}
                amount={habit.target_numeric ? habit.target_numeric * 0.25 : 1}
                unit={habit.unit}
                onLog={logHabit}
                disabled={habit.status === 'complete'}
              />
              <QuickLogButton 
                habitId={habit.habit_id}
                amount={habit.target_numeric ? habit.target_numeric * 0.5 : 2}
                unit={habit.unit}
                onLog={logHabit}
                disabled={habit.status === 'complete'}
              />
            </div>
          </div>
        )}

        {habit.type === 'binary' && (
          <div className="flex justify-center">
            <button
              onClick={() => logHabit(habit.habit_id)}
              disabled={habit.status === 'complete'}
              className={`px-6 py-2 rounded-lg font-medium transition-colors ${
                habit.status === 'complete'
                  ? 'bg-green-100 text-green-800 cursor-not-allowed'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
              }`}
            >
              {habit.status === 'complete' ? 'Completed!' : 'Mark Complete'}
            </button>
          </div>
        )}

        {/* Window indicator */}
        {habit.window && (
          <div className="mt-2 text-xs text-gray-500 flex items-center">
            <Calendar className="w-3 h-3 mr-1" />
            {habit.window}
          </div>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="text-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-2 text-gray-400">Loading today's habits...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-600 mb-4">{error}</p>
        <button
          onClick={loadTodaysHabits}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Stats */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-white">Today's Habits</h2>
          <button
            onClick={loadTodaysHabits}
            className="p-2 text-gray-400 hover:text-gray-300 rounded-lg hover:bg-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
        
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-sm text-gray-400">Total Habits</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{stats.completed}</div>
            <div className="text-sm text-gray-400">Completed</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.in_progress}</div>
            <div className="text-sm text-gray-400">In Progress</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-purple-600">{Math.round(stats.completion_rate)}%</div>
            <div className="text-sm text-gray-400">Completion Rate</div>
          </div>
        </div>
      </div>

      {/* Habits List */}
      {habits.length === 0 ? (
        <div className="text-center py-12 bg-gray-800 rounded-lg border border-gray-700">
          <Target className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No habits for today</h3>
          <p className="text-gray-400 mb-4">Get started by creating your first habit!</p>
          <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center mx-auto">
            <Plus className="w-4 h-4 mr-2" />
            Create Habit
          </button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {habits.map(renderHabitCard)}
        </div>
      )}

      {/* Quick Actions */}
      {habits.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <button className="flex items-center px-3 py-2 text-blue-600 hover:bg-blue-50 rounded-lg">
                <Plus className="w-4 h-4 mr-2" />
                Add Habit
              </button>
              <button className="flex items-center px-3 py-2 text-gray-400 hover:bg-gray-700 rounded-lg">
                <TrendingUp className="w-4 h-4 mr-2" />
                View Insights
              </button>
            </div>
            <div className="text-sm text-gray-500">
              {new Date().toLocaleDateString('en-US', { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
              })}
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && editingHabit && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-md w-full border border-gray-700">
            <div className="p-6">
              <h3 className="text-lg font-semibold text-white mb-4">Edit Habit</h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">
                    Habit Title
                  </label>
                  <input
                    type="text"
                    defaultValue={editingHabit.title}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:ring-2 focus:ring-blue-500"
                    id="edit-title"
                  />
                </div>
                
                {editingHabit.type === 'quantitative' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">
                      Target Amount
                    </label>
                    <input
                      type="number"
                      defaultValue={editingHabit.target_numeric || 0}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:ring-2 focus:ring-blue-500"
                      id="edit-target"
                    />
                  </div>
                )}
              </div>
              
              <div className="flex space-x-3 mt-6">
                <button
                  onClick={() => {
                    const title = (document.getElementById('edit-title') as HTMLInputElement)?.value;
                    const target = (document.getElementById('edit-target') as HTMLInputElement)?.value;
                    
                    const updateData: any = { title };
                    if (target) updateData.target_numeric = parseFloat(target);
                    
                    handleSaveEdit(updateData);
                  }}
                  className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
                >
                  Save Changes
                </button>
                <button
                  onClick={() => {
                    setShowEditModal(false);
                    setEditingHabit(null);
                  }}
                  className="flex-1 bg-gray-600 text-white px-4 py-2 rounded-lg hover:bg-gray-700"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Quick log button component
function QuickLogButton({ 
  habitId, 
  amount, 
  unit, 
  onLog, 
  disabled 
}: {
  habitId: string;
  amount: number;
  unit?: string;
  onLog: (habitId: string, amount: number) => void;
  disabled: boolean;
}) {
  return (
    <button
      onClick={() => onLog(habitId, amount)}
      disabled={disabled}
      className={`px-3 py-1 text-sm rounded-lg transition-colors ${
        disabled
          ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
      }`}
    >
      +{amount} {unit}
    </button>
  );
}
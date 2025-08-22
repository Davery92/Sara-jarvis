import React, { useState, useEffect } from 'react';
import { TrendingUp, Calendar, Target, Zap, Award, BarChart3, PieChart, Clock, CheckCircle } from 'lucide-react';
import { apiRequest } from '../utils/api';
import { HabitProgressRing } from './HabitProgress';

interface InsightData {
  overview: {
    total_habits: number;
    active_habits: number;
    total_completions: number;
    average_completion_rate: number;
    current_streaks: number;
    longest_streak: number;
  };
  weekly_stats: {
    this_week: {
      completed: number;
      total: number;
      completion_rate: number;
    };
    last_week: {
      completed: number;
      total: number;
      completion_rate: number;
    };
    trend: 'up' | 'down' | 'stable';
  };
  habit_performance: Array<{
    habit_id: string;
    title: string;
    type: string;
    completion_rate: number;
    current_streak: number;
    best_streak: number;
    total_completions: number;
  }>;
  patterns: {
    best_day_of_week: string;
    best_time_of_day: string;
    most_consistent_habit: string;
    improvement_suggestions: string[];
  };
}

export default function HabitInsights() {
  const [insights, setInsights] = useState<InsightData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'week' | 'month' | 'year'>('month');

  useEffect(() => {
    loadInsights();
  }, [timeRange]);

  const loadInsights = async () => {
    try {
      setLoading(true);
      const response = await apiRequest<InsightData>(`/insights/habits?period=${timeRange}`);
      setInsights(response);
    } catch (err) {
      setError('Failed to load insights');
      console.error('Error loading insights:', err);
    } finally {
      setLoading(false);
    }
  };

  const getTrendIcon = (trend: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up': return <TrendingUp className="w-4 h-4 text-green-400" />;
      case 'down': return <TrendingUp className="w-4 h-4 text-red-400 transform rotate-180" />;
      default: return <TrendingUp className="w-4 h-4 text-gray-400 transform rotate-90" />;
    }
  };

  const getTrendColor = (trend: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up': return 'text-green-400';
      case 'down': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border border-gray-700-b-2 border border-gray-700-blue-600 mx-auto"></div>
          <p className="mt-2 text-gray-400">Loading insights...</p>
        </div>
      </div>
    );
  }

  if (error || !insights) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">{error}</p>
        <button
          onClick={loadInsights}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 text-white">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Habit Insights</h2>
          <p className="text-gray-400">Analyze your habit patterns and progress</p>
        </div>
        
        <div className="flex space-x-2">
          {(['week', 'month', 'year'] as const).map((period) => (
            <button
              key={period}
              onClick={() => setTimeRange(period)}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                timeRange === period
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              {period.charAt(0).toUpperCase() + period.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <InsightCard
          title="Total Habits"
          value={insights.overview.total_habits}
          subtitle={`${insights.overview.active_habits} active`}
          icon={<Target className="w-6 h-6" />}
          color="blue"
        />
        
        <InsightCard
          title="Completion Rate"
          value={`${Math.round(insights.overview.average_completion_rate)}%`}
          subtitle={`${insights.overview.total_completions} total`}
          icon={<CheckCircle className="w-6 h-6" />}
          color="green"
        />
        
        <InsightCard
          title="Active Streaks"
          value={insights.overview.current_streaks}
          subtitle={`Best: ${insights.overview.longest_streak} days`}
          icon={<Zap className="w-6 h-6" />}
          color="orange"
        />
        
        <InsightCard
          title="Weekly Trend"
          value={`${Math.round(insights.weekly_stats.this_week.completion_rate)}%`}
          subtitle={
            <div className="flex items-center space-x-1">
              {getTrendIcon(insights.weekly_stats.trend)}
              <span className={getTrendColor(insights.weekly_stats.trend)}>
                {insights.weekly_stats.trend === 'up' ? 'Improving' : 
                 insights.weekly_stats.trend === 'down' ? 'Declining' : 'Stable'}
              </span>
            </div>
          }
          icon={<BarChart3 className="w-6 h-6" />}
          color="purple"
        />
      </div>

      {/* Performance Chart */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-white">Habit Performance</h3>
          <PieChart className="w-5 h-5 text-gray-400" />
        </div>
        
        <div className="grid gap-4">
          {insights.habit_performance.map((habit, index) => (
            <div key={habit.habit_id} className="flex items-center space-x-4 p-4 bg-gray-700 rounded-lg">
              <div className="flex-shrink-0">
                <HabitProgressRing 
                  progress={habit.completion_rate / 100} 
                  size={60} 
                  strokeWidth={6}
                />
              </div>
              
              <div className="flex-1 min-w-0">
                <h4 className="font-medium text-white truncate">{habit.title}</h4>
                <div className="flex items-center space-x-4 mt-1 text-sm text-gray-400">
                  <span className="flex items-center">
                    <Target className="w-3 h-3 mr-1" />
                    {habit.type}
                  </span>
                  <span className="flex items-center">
                    <Zap className="w-3 h-3 mr-1 text-orange-500" />
                    {habit.current_streak} day streak
                  </span>
                  <span className="flex items-center">
                    <Award className="w-3 h-3 mr-1 text-indigo-500" />
                    Best: {habit.best_streak}
                  </span>
                </div>
              </div>
              
              <div className="text-right">
                <div className="text-lg font-semibold text-white">
                  {Math.round(habit.completion_rate)}%
                </div>
                <div className="text-sm text-gray-400">
                  {habit.total_completions} completions
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Patterns & Insights */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Patterns */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Patterns</h3>
          
          <div className="space-y-4">
            <div className="flex items-center justify-between p-3 bg-blue-900/30 rounded-lg">
              <div className="flex items-center space-x-3">
                <Calendar className="w-5 h-5 text-blue-400" />
                <span className="font-medium text-blue-300">Best Day</span>
              </div>
              <span className="text-blue-300">{insights.patterns.best_day_of_week}</span>
            </div>
            
            <div className="flex items-center justify-between p-3 bg-green-900/30 rounded-lg">
              <div className="flex items-center space-x-3">
                <Clock className="w-5 h-5 text-green-400" />
                <span className="font-medium text-green-300">Best Time</span>
              </div>
              <span className="text-green-300">{insights.patterns.best_time_of_day}</span>
            </div>
            
            <div className="flex items-center justify-between p-3 bg-purple-900/30 rounded-lg">
              <div className="flex items-center space-x-3">
                <Award className="w-5 h-5 text-purple-400" />
                <span className="font-medium text-purple-300">Most Consistent</span>
              </div>
              <span className="text-purple-300 text-sm truncate max-w-32">
                {insights.patterns.most_consistent_habit}
              </span>
            </div>
          </div>
        </div>

        {/* Suggestions */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Improvement Suggestions</h3>
          
          <div className="space-y-3">
            {insights.patterns.improvement_suggestions.map((suggestion, index) => (
              <div key={index} className="flex items-start space-x-3 p-3 bg-yellow-900/30 rounded-lg">
                <TrendingUp className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-yellow-300">{suggestion}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Weekly Comparison */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Weekly Comparison</h3>
        
        <div className="grid md:grid-cols-2 gap-6">
          <div className="text-center p-4 bg-blue-900/30 rounded-lg">
            <div className="text-2xl font-bold text-blue-400 mb-1">
              {insights.weekly_stats.this_week.completed}/{insights.weekly_stats.this_week.total}
            </div>
            <div className="text-sm text-blue-300 mb-2">This Week</div>
            <div className="text-lg font-semibold text-blue-400">
              {Math.round(insights.weekly_stats.this_week.completion_rate)}%
            </div>
          </div>
          
          <div className="text-center p-4 bg-gray-700 rounded-lg">
            <div className="text-2xl font-bold text-gray-400 mb-1">
              {insights.weekly_stats.last_week.completed}/{insights.weekly_stats.last_week.total}
            </div>
            <div className="text-sm text-gray-400 mb-2">Last Week</div>
            <div className="text-lg font-semibold text-gray-400">
              {Math.round(insights.weekly_stats.last_week.completion_rate)}%
            </div>
          </div>
        </div>
        
        <div className="mt-4 flex items-center justify-center space-x-2">
          {getTrendIcon(insights.weekly_stats.trend)}
          <span className={`font-medium ${getTrendColor(insights.weekly_stats.trend)}`}>
            {insights.weekly_stats.trend === 'up' ? 'You\'re improving!' : 
             insights.weekly_stats.trend === 'down' ? 'Room for improvement' : 'Staying consistent'}
          </span>
        </div>
      </div>
    </div>
  );
}

// Reusable insight card component
function InsightCard({ 
  title, 
  value, 
  subtitle, 
  icon, 
  color 
}: {
  title: string;
  value: string | number;
  subtitle: React.ReactNode;
  icon: React.ReactNode;
  color: 'blue' | 'green' | 'orange' | 'purple';
}) {
  const colorClasses = {
    blue: 'bg-blue-900/30 text-blue-400',
    green: 'bg-green-900/30 text-green-400',
    orange: 'bg-orange-900/30 text-orange-400',
    purple: 'bg-purple-900/30 text-purple-400'
  };

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className={`p-3 rounded-lg ${colorClasses[color]}`}>
          {icon}
        </div>
      </div>
      
      <div className="text-2xl font-bold text-white mb-1">
        {value}
      </div>
      
      <div className="text-sm font-medium text-gray-700 mb-1">
        {title}
      </div>
      
      <div className="text-sm text-gray-400">
        {subtitle}
      </div>
    </div>
  );
}
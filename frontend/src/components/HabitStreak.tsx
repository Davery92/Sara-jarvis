import React from 'react';
import { Zap, TrendingUp, Award, Calendar, Fire, Target } from 'lucide-react';

interface StreakData {
  current: number;
  best: number;
  lastCompleted?: string;
  totalDays: number;
  missedDays: number;
  currentWeekStreak: number;
  longestStreakThisYear: number;
}

interface HabitStreakProps {
  habitTitle: string;
  streak: StreakData;
  completionHistory: Array<{
    date: string;
    completed: boolean;
    progress: number;
  }>;
  showVisualCalendar?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export default function HabitStreak({ 
  habitTitle, 
  streak, 
  completionHistory, 
  showVisualCalendar = true,
  size = 'md' 
}: HabitStreakProps) {
  const getStreakLevel = (days: number) => {
    if (days >= 365) return { name: 'Legendary', color: 'purple', icon: '👑' };
    if (days >= 100) return { name: 'Master', color: 'indigo', icon: '🏆' };
    if (days >= 50) return { name: 'Champion', color: 'blue', icon: '🥇' };
    if (days >= 30) return { name: 'Expert', color: 'green', icon: '🌟' };
    if (days >= 14) return { name: 'Achiever', color: 'yellow', icon: '⭐' };
    if (days >= 7) return { name: 'Committed', color: 'orange', icon: '🔥' };
    if (days >= 3) return { name: 'Building', color: 'blue', icon: '💪' };
    return { name: 'Starting', color: 'gray', icon: '🌱' };
  };

  const currentLevel = getStreakLevel(streak.current);
  const bestLevel = getStreakLevel(streak.best);

  const sizeClasses = {
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6'
  };

  return (
    <div className={`bg-gray-800 rounded-lg border border border-gray-700 ${sizeClasses[size]}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className={`font-semibold text-white ${size === 'sm' ? 'text-sm' : 'text-lg'}`}>
          {habitTitle} Streak
        </h3>
        <div className="flex items-center space-x-2">
          <Zap className={`text-orange-500 ${size === 'sm' ? 'w-4 h-4' : 'w-5 h-5'}`} />
          <span className={`font-bold text-orange-600 ${size === 'sm' ? 'text-sm' : 'text-lg'}`}>
            {streak.current}
          </span>
        </div>
      </div>

      {/* Current Streak Card */}
      <div className={`bg-gradient-to-r from-orange-50 to-red-50 rounded-lg p-4 mb-4 border border-orange-200`}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-2">
            <span className="text-2xl">{currentLevel.icon}</span>
            <div>
              <div className={`font-semibold text-${currentLevel.color}-800`}>
                {currentLevel.name}
              </div>
              <div className="text-sm text-gray-400">Current Level</div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-orange-600">{streak.current}</div>
            <div className="text-sm text-gray-400">days</div>
          </div>
        </div>
        
        {streak.current > 0 && (
          <div className="text-sm text-gray-400">
            {streak.lastCompleted ? (
              `Last completed: ${new Date(streak.lastCompleted).toLocaleDateString()}`
            ) : (
              'Keep going!'
            )}
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="text-center">
          <div className="flex items-center justify-center mb-1">
            <Award className="w-5 h-5 text-indigo-600 mr-1" />
            <span className="text-lg font-bold text-indigo-600">{streak.best}</span>
          </div>
          <div className="text-sm text-gray-400">Best Streak</div>
          {streak.best > 0 && (
            <div className="text-xs text-indigo-600">{bestLevel.name}</div>
          )}
        </div>
        
        <div className="text-center">
          <div className="flex items-center justify-center mb-1">
            <TrendingUp className="w-5 h-5 text-green-600 mr-1" />
            <span className="text-lg font-bold text-green-600">{streak.totalDays}</span>
          </div>
          <div className="text-sm text-gray-400">Total Days</div>
          <div className="text-xs text-gray-500">
            {streak.missedDays} missed
          </div>
        </div>
      </div>

      {/* Weekly Progress */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">This Week</span>
          <span className="text-sm text-gray-400">{streak.currentWeekStreak}/7</span>
        </div>
        <WeeklyStreakBar 
          completions={completionHistory.slice(-7)} 
          size={size}
        />
      </div>

      {/* Visual Calendar */}
      {showVisualCalendar && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-700">Recent Activity</span>
            <Calendar className="w-4 h-4 text-gray-400" />
          </div>
          <StreakCalendar 
            history={completionHistory.slice(-28)} 
            size={size}
          />
        </div>
      )}

      {/* Motivation Message */}
      {streak.current > 0 && (
        <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-200">
          <div className="flex items-center space-x-2">
            <Fire className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-medium text-blue-800">
              {getMotivationMessage(streak.current)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// Weekly streak progress bar
function WeeklyStreakBar({ 
  completions, 
  size 
}: { 
  completions: Array<{ date: string; completed: boolean; progress: number }>; 
  size: 'sm' | 'md' | 'lg';
}) {
  const days = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  const barHeight = size === 'sm' ? 'h-1' : 'h-2';
  
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-7 gap-1">
        {days.map((day, i) => (
          <div key={i} className="text-center">
            <div className="text-xs text-gray-500 mb-1">{day}</div>
            <div className={`${barHeight} rounded-full ${
              i < completions.length && completions[i].completed
                ? 'bg-green-500'
                : i < completions.length && completions[i].progress > 0
                ? 'bg-yellow-500'
                : 'bg-gray-200'
            }`} />
          </div>
        ))}
      </div>
    </div>
  );
}

// Mini calendar view
function StreakCalendar({ 
  history, 
  size 
}: { 
  history: Array<{ date: string; completed: boolean; progress: number }>; 
  size: 'sm' | 'md' | 'lg';
}) {
  const cellSize = size === 'sm' ? 'w-3 h-3' : size === 'md' ? 'w-4 h-4' : 'w-5 h-5';
  
  // Group by weeks (4 weeks = 28 days)
  const weeks = [];
  for (let i = 0; i < history.length; i += 7) {
    weeks.push(history.slice(i, i + 7));
  }
  
  return (
    <div className="space-y-1">
      {weeks.map((week, weekIndex) => (
        <div key={weekIndex} className="flex space-x-1">
          {week.map((day, dayIndex) => (
            <div
              key={dayIndex}
              className={`${cellSize} rounded-sm border ${
                day.completed
                  ? 'bg-green-500 border-green-600'
                  : day.progress > 0
                  ? 'bg-yellow-400 border-yellow-500'
                  : 'bg-gray-700 border-gray-200'
              }`}
              title={`${day.date}: ${day.completed ? 'Completed' : day.progress > 0 ? 'Partial' : 'Not done'}`}
            />
          ))}
        </div>
      ))}
      
      {/* Legend */}
      <div className="flex items-center justify-center space-x-4 mt-2 text-xs text-gray-400">
        <div className="flex items-center space-x-1">
          <div className="w-2 h-2 bg-gray-700 border border-gray-600 rounded-sm" />
          <span>None</span>
        </div>
        <div className="flex items-center space-x-1">
          <div className="w-2 h-2 bg-yellow-400 border border-yellow-500 rounded-sm" />
          <span>Partial</span>
        </div>
        <div className="flex items-center space-x-1">
          <div className="w-2 h-2 bg-green-500 border border-green-600 rounded-sm" />
          <span>Complete</span>
        </div>
      </div>
    </div>
  );
}

// Compact streak display
export function HabitStreakCompact({ 
  current, 
  best, 
  showIcon = true 
}: { 
  current: number; 
  best: number; 
  showIcon?: boolean;
}) {
  const level = current >= 7 ? getStreakLevel(current) : null;
  
  return (
    <div className="flex items-center space-x-2">
      {showIcon && <Zap className="w-4 h-4 text-orange-500" />}
      <span className="font-medium text-orange-600">{current}</span>
      {level && (
        <span className="text-xs px-1 py-0.5 rounded bg-orange-100 text-orange-800">
          {level.icon}
        </span>
      )}
      {best > current && (
        <span className="text-xs text-gray-500">
          (best: {best})
        </span>
      )}
    </div>
  );
}

// Streak milestone component
export function StreakMilestone({ 
  current, 
  nextMilestone 
}: { 
  current: number; 
  nextMilestone: number;
}) {
  const progress = (current / nextMilestone) * 100;
  const remaining = nextMilestone - current;
  
  return (
    <div className="bg-gradient-to-r from-purple-50 to-pink-50 p-4 rounded-lg border border-purple-200">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-purple-800">
          Next Milestone: {nextMilestone} days
        </span>
        <span className="text-sm text-purple-600">
          {remaining} to go
        </span>
      </div>
      <div className="w-full bg-purple-200 rounded-full h-2">
        <div
          className="h-2 bg-purple-500 rounded-full transition-all duration-500"
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>
    </div>
  );
}

function getStreakLevel(days: number) {
  if (days >= 365) return { name: 'Legendary', color: 'purple', icon: '👑' };
  if (days >= 100) return { name: 'Master', color: 'indigo', icon: '🏆' };
  if (days >= 50) return { name: 'Champion', color: 'blue', icon: '🥇' };
  if (days >= 30) return { name: 'Expert', color: 'green', icon: '🌟' };
  if (days >= 14) return { name: 'Achiever', color: 'yellow', icon: '⭐' };
  if (days >= 7) return { name: 'Committed', color: 'orange', icon: '🔥' };
  if (days >= 3) return { name: 'Building', color: 'blue', icon: '💪' };
  return { name: 'Starting', color: 'gray', icon: '🌱' };
}

function getMotivationMessage(streak: number): string {
  if (streak >= 365) return "Incredible! You've built a life-changing habit!";
  if (streak >= 100) return "Amazing! You're in the top 1% of habit builders!";
  if (streak >= 50) return "Outstanding! You've proven true commitment!";
  if (streak >= 30) return "Fantastic! This habit is becoming second nature!";
  if (streak >= 21) return "Great job! You're forming a lasting habit!";
  if (streak >= 14) return "Two weeks strong! You're building momentum!";
  if (streak >= 7) return "One week down! You're on fire! 🔥";
  if (streak >= 3) return "Keep it up! Consistency is key! 💪";
  return "Great start! Every day counts! 🌟";
}
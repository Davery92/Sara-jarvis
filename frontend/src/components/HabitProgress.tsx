import React from 'react';
import { TrendingUp, TrendingDown, Minus, Zap, Target, Calendar, Award } from 'lucide-react';

interface ProgressData {
  current: number;
  target: number;
  percentage: number;
  trend: 'up' | 'down' | 'stable';
  unit?: string;
}

interface StreakData {
  current: number;
  best: number;
  lastCompleted?: string;
}

interface HabitProgressProps {
  title: string;
  type: 'binary' | 'quantitative' | 'checklist' | 'time';
  progress: ProgressData;
  streak: StreakData;
  status: 'pending' | 'in_progress' | 'complete';
  size?: 'sm' | 'md' | 'lg';
  showDetails?: boolean;
}

export default function HabitProgress({ 
  title, 
  type, 
  progress, 
  streak, 
  status, 
  size = 'md',
  showDetails = true 
}: HabitProgressProps) {
  const sizeClasses = {
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6'
  };

  const progressSize = {
    sm: 'h-2',
    md: 'h-3',
    lg: 'h-4'
  };

  const getStatusColor = () => {
    switch (status) {
      case 'complete': return 'bg-green-50 border-green-200';
      case 'in_progress': return 'bg-blue-50 border-blue-200';
      default: return 'bg-gray-50 border-gray-200';
    }
  };

  const getProgressColor = () => {
    if (status === 'complete') return 'bg-green-500';
    if (progress.percentage >= 0.8) return 'bg-blue-500';
    if (progress.percentage >= 0.5) return 'bg-yellow-500';
    return 'bg-gray-400';
  };

  const getTrendIcon = () => {
    switch (progress.trend) {
      case 'up': return <TrendingUp className="w-4 h-4 text-green-600" />;
      case 'down': return <TrendingDown className="w-4 h-4 text-red-600" />;
      default: return <Minus className="w-4 h-4 text-gray-600" />;
    }
  };

  const getTypeIcon = () => {
    switch (type) {
      case 'binary': return <Target className="w-5 h-5" />;
      case 'quantitative': return <TrendingUp className="w-5 h-5" />;
      case 'checklist': return <Award className="w-5 h-5" />;
      case 'time': return <Calendar className="w-5 h-5" />;
    }
  };

  return (
    <div className={`rounded-lg border transition-all duration-200 hover:shadow-md ${getStatusColor()} ${sizeClasses[size]}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center space-x-2 mb-1">
            <div className="text-gray-600">
              {getTypeIcon()}
            </div>
            <h3 className={`font-medium text-gray-900 ${size === 'sm' ? 'text-sm' : 'text-base'}`}>
              {title}
            </h3>
          </div>
          
          {showDetails && (
            <div className="flex items-center space-x-3 text-xs text-gray-600">
              <span className="flex items-center">
                <Zap className="w-3 h-3 mr-1 text-orange-500" />
                {streak.current} day streak
              </span>
              {streak.best > streak.current && (
                <span className="text-gray-500">
                  Best: {streak.best}
                </span>
              )}
            </div>
          )}
        </div>
        
        <div className="flex items-center space-x-2">
          {getTrendIcon()}
          <span className={`text-right ${size === 'sm' ? 'text-sm' : 'text-lg'} font-semibold ${
            status === 'complete' ? 'text-green-600' : 'text-gray-900'
          }`}>
            {Math.round(progress.percentage * 100)}%
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-600">Progress</span>
          {type !== 'binary' && (
            <span className="text-gray-600">
              {progress.current} / {progress.target} {progress.unit}
            </span>
          )}
        </div>
        <div className={`w-full bg-gray-200 rounded-full ${progressSize[size]}`}>
          <div
            className={`${progressSize[size]} rounded-full transition-all duration-500 ${getProgressColor()}`}
            style={{ width: `${Math.min(progress.percentage * 100, 100)}%` }}
          />
        </div>
      </div>

      {/* Details */}
      {showDetails && (
        <div className="space-y-2">
          {/* Status Badge */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className={`px-2 py-1 text-xs rounded-full font-medium ${
                status === 'complete' 
                  ? 'bg-green-100 text-green-800'
                  : status === 'in_progress'
                  ? 'bg-blue-100 text-blue-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {status === 'complete' ? 'Completed' : status === 'in_progress' ? 'In Progress' : 'Pending'}
              </span>
              
              {streak.current > 0 && (
                <div className="flex items-center space-x-1">
                  {Array.from({ length: Math.min(streak.current, 7) }).map((_, i) => (
                    <div
                      key={i}
                      className={`w-2 h-2 rounded-full ${
                        i < streak.current ? 'bg-orange-400' : 'bg-gray-300'
                      }`}
                    />
                  ))}
                  {streak.current > 7 && (
                    <span className="text-xs text-gray-600">+{streak.current - 7}</span>
                  )}
                </div>
              )}
            </div>
            
            <div className="text-xs text-gray-500">
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </div>
          </div>

          {/* Streak Achievement */}
          {streak.current >= 7 && (
            <div className="bg-gradient-to-r from-yellow-50 to-orange-50 border border-yellow-200 rounded-lg p-2">
              <div className="flex items-center space-x-2">
                <Award className="w-4 h-4 text-yellow-600" />
                <span className="text-xs font-medium text-yellow-800">
                  {streak.current >= 30 ? 'Legendary' : 
                   streak.current >= 21 ? 'Master' : 
                   streak.current >= 14 ? 'Champion' : 'Achiever'} Streak!
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Compact version for lists
export function HabitProgressCompact({ 
  title, 
  progress, 
  streak, 
  status 
}: Pick<HabitProgressProps, 'title' | 'progress' | 'streak' | 'status'>) {
  return (
    <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-50">
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-medium text-gray-900 truncate">{title}</h4>
          <span className={`text-sm font-semibold ${
            status === 'complete' ? 'text-green-600' : 'text-gray-600'
          }`}>
            {Math.round(progress.percentage * 100)}%
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all duration-300 ${
              status === 'complete' ? 'bg-green-500' : 'bg-blue-500'
            }`}
            style={{ width: `${Math.min(progress.percentage * 100, 100)}%` }}
          />
        </div>
      </div>
      
      {streak.current > 0 && (
        <div className="flex items-center text-xs text-orange-600">
          <Zap className="w-3 h-3 mr-1" />
          {streak.current}
        </div>
      )}
    </div>
  );
}

// Weekly progress grid
export function HabitWeeklyProgress({ 
  title, 
  weekData 
}: { 
  title: string;
  weekData: Array<{ date: string; completed: boolean; progress: number }>;
}) {
  const days = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  
  return (
    <div className="bg-white p-4 rounded-lg border">
      <h4 className="font-medium text-gray-900 mb-3">{title}</h4>
      <div className="grid grid-cols-7 gap-2">
        {days.map((day, i) => (
          <div key={i} className="text-center">
            <div className="text-xs text-gray-600 mb-1">{day}</div>
            <div 
              className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-medium ${
                i < weekData.length && weekData[i].completed
                  ? 'bg-green-100 text-green-800'
                  : i < weekData.length && weekData[i].progress > 0
                  ? 'bg-blue-100 text-blue-800'
                  : 'bg-gray-100 text-gray-400'
              }`}
            >
              {i < weekData.length ? (
                weekData[i].completed ? '✓' : Math.round(weekData[i].progress * 100)
              ) : '-'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Progress ring for dashboard
export function HabitProgressRing({ 
  progress, 
  size = 120, 
  strokeWidth = 8 
}: { 
  progress: number; 
  size?: number; 
  strokeWidth?: number; 
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const strokeDasharray = circumference;
  const strokeDashoffset = circumference - (progress * circumference);
  
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg
        className="transform -rotate-90"
        width={size}
        height={size}
      >
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          className="text-gray-700"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={strokeDasharray}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className={`transition-all duration-1000 ${
            progress >= 1 ? 'text-green-500' : 'text-blue-500'
          }`}
        />
      </svg>
      {/* Percentage text */}
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-xl font-bold text-white">
          {Math.round(progress * 100)}%
        </span>
      </div>
    </div>
  );
}
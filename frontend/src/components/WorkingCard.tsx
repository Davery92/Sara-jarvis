/**
 * Working Card Component - Phase 3 TODO
 * 
 * This component displays progress for background tasks:
 * - Task title and description
 * - Progress percentage and ETA
 * - Cancel action (if supported)
 * - Results summary when complete
 * 
 * TODO: Implement in Phase 3
 */

import React from 'react';

interface BackgroundTask {
  id: number;
  kind: 'research' | 'draft' | 'compare' | 'summarize' | 'analyze';
  title: string;
  description?: string;
  state: 'queued' | 'running' | 'waiting_confirm' | 'done' | 'failed';
  progress: number; // 0-100
  estimated_duration_minutes?: number;
  started_at?: string;
  summary?: string;
}

interface WorkingCardProps {
  className?: string;
}

export const WorkingCard: React.FC<WorkingCardProps> = ({ className }) => {
  // TODO: Implement working card functionality
  // - Fetch active tasks from /api/work/status
  // - Real-time progress updates
  // - Handle task completion and results
  // - Cancel task action
  // - Show/hide based on active tasks

  const activeTasks: BackgroundTask[] = []; // TODO: Fetch from API

  if (activeTasks.length === 0) {
    return null; // Hide when no active tasks
  }

  return (
    <div className={`working-card bg-blue-50 border border-blue-200 rounded-lg p-4 ${className || ''}`}>
      <div className="working-card-header flex items-center justify-between mb-3">
        <h3 className="font-semibold text-blue-900 flex items-center">
          <div className="animate-spin w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full mr-2" />
          Working on {activeTasks.length} task(s)
        </h3>
        <button className="text-blue-600 hover:text-blue-800 text-sm">
          View Details
        </button>
      </div>

      {activeTasks.map(task => (
        <div key={task.id} className="task-item mb-3 last:mb-0">
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium text-sm">{task.title}</span>
            <span className="text-xs text-gray-600">{task.progress}%</span>
          </div>
          
          <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
            <div 
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${task.progress}%` }}
            />
          </div>
          
          {task.description && (
            <p className="text-xs text-gray-600 mb-2">{task.description}</p>
          )}
          
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>State: {task.state}</span>
            {task.estimated_duration_minutes && (
              <span>ETA: ~{task.estimated_duration_minutes} min</span>
            )}
          </div>
          
          {task.state === 'waiting_confirm' && (
            <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs">
              ⚠️ Waiting for confirmation to proceed
              <div className="mt-1">
                <button className="bg-green-500 text-white px-2 py-1 rounded mr-2 text-xs">
                  Approve
                </button>
                <button className="bg-gray-500 text-white px-2 py-1 rounded text-xs">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default WorkingCard;
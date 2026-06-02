import React, { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService } from '../services/backgroundTasks';
import AgentClarificationModal from '../components/AgentClarificationModal';
import { startEvent, updateEvent, endEvent } from '../services/eventActivity';

interface BackgroundTasksContextType {
  tasks: BackgroundTask[];
  activeCount: number;
  clarificationTask: BackgroundTask | null;
  refreshTasks: () => Promise<void>;
}

const BackgroundTasksContext = createContext<BackgroundTasksContextType | undefined>(undefined);

interface BackgroundTasksProviderProps {
  children: ReactNode;
}

export function BackgroundTasksProvider({ children }: BackgroundTasksProviderProps) {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [clarificationTask, setClarificationTask] = useState<BackgroundTask | null>(null);
  const [dismissedTaskId, setDismissedTaskId] = useState<string | null>(null);

  // Start polling when provider mounts (30s default, scales to 60s when idle)
  useEffect(() => {
    // 10s while a task is active (snappy Live Activity step updates), 60s when idle.
    backgroundTaskService.startPolling(10000);

    return () => {
      backgroundTaskService.stopPolling();
    };
  }, []);

  // Subscribe to task updates
  useEffect(() => {
    const unsubscribe = backgroundTaskService.subscribe(setTasks);
    return () => unsubscribe();
  }, []);

  // Subscribe to clarification requests
  useEffect(() => {
    const unsubscribe = backgroundTaskService.subscribeToClarifications((task) => {
      // Don't show if user dismissed this task
      if (task && task.id === dismissedTaskId) {
        return;
      }
      setClarificationTask(task);
    });
    return () => unsubscribe();
  }, [dismissedTaskId]);

  // "Sara is working on…" Live Activity for the currently-running task.
  const taskActivityRef = useRef<string | null>(null);
  useEffect(() => {
    const running = tasks.find((t) => t.status === 'running');
    if (running) {
      // Prefer the live current-step label (code mode emits "editing X",
      // "running tests", "pushing branch"); fall back to the original request.
      const subtitle = (running.status_label || running.original_query || running.task_type || 'Working…').slice(0, 80);
      const startMsRaw = running.started_at ? new Date(running.started_at).getTime() : Date.now();
      const startMs = isNaN(startMsRaw) ? Date.now() : startMsRaw;
      if (taskActivityRef.current !== running.id) {
        if (taskActivityRef.current) endEvent(taskActivityRef.current);
        startEvent(running.id, 'task', 'Sara is working', subtitle, startMs);
        taskActivityRef.current = running.id;
      } else {
        updateEvent(running.id, subtitle, startMs);
      }
    } else if (taskActivityRef.current) {
      endEvent(taskActivityRef.current);
      taskActivityRef.current = null;
    }
  }, [tasks]);

  const refreshTasks = useCallback(async () => {
    await backgroundTaskService.fetchTasks();
  }, []);

  const activeCount = tasks.filter(t =>
    t.status === 'pending' || t.status === 'running'
  ).length;

  const handleCloseClarification = () => {
    setClarificationTask(null);
  };

  const handleDismissClarification = () => {
    if (clarificationTask) {
      setDismissedTaskId(clarificationTask.id);
    }
    setClarificationTask(null);
  };

  return (
    <BackgroundTasksContext.Provider
      value={{
        tasks,
        activeCount,
        clarificationTask,
        refreshTasks,
      }}
    >
      {children}

      {/* Global clarification modal */}
      <AgentClarificationModal
        visible={!!clarificationTask}
        task={clarificationTask}
        onClose={handleCloseClarification}
        onDismiss={handleDismissClarification}
      />
    </BackgroundTasksContext.Provider>
  );
}

export function useBackgroundTasks() {
  const context = useContext(BackgroundTasksContext);
  if (context === undefined) {
    throw new Error('useBackgroundTasks must be used within a BackgroundTasksProvider');
  }
  return context;
}

export default BackgroundTasksContext;

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService } from '../services/backgroundTasks';
import AgentClarificationModal from '../components/AgentClarificationModal';

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
    backgroundTaskService.startPolling(30000);

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

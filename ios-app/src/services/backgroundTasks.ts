import { BackgroundTask, BackgroundTasksResponse } from '../types/api';
import apiClient from './api';

class BackgroundTaskService {
  private pollingInterval: NodeJS.Timeout | null = null;
  private listeners: Set<(tasks: BackgroundTask[]) => void> = new Set();
  private clarificationListeners: Set<(task: BackgroundTask | null) => void> = new Set();
  private lastTasks: BackgroundTask[] = [];
  private baseIntervalMs: number = 30000;

  /**
   * Start polling for background tasks
   */
  startPolling(intervalMs: number = 30000): void {
    if (this.pollingInterval) {
      return; // Already polling
    }

    this.baseIntervalMs = intervalMs;

    // Fetch immediately
    this.fetchTasks();

    // Start adaptive polling
    this.scheduleNextPoll();

    console.log('[BackgroundTasks] Started polling');
  }

  private scheduleNextPoll(): void {
    const hasActive = this.lastTasks.some(t => t.status === 'pending' || t.status === 'running');
    const interval = hasActive ? this.baseIntervalMs : 60000; // active: base (10s); idle: 60s

    this.pollingInterval = setTimeout(() => {
      this.fetchTasks().then(() => this.scheduleNextPoll());
    }, interval);
  }

  /**
   * Stop polling for background tasks
   */
  stopPolling(): void {
    if (this.pollingInterval) {
      clearTimeout(this.pollingInterval);
      this.pollingInterval = null;
      console.log('[BackgroundTasks] Stopped polling');
    }
  }

  /**
   * Fetch active background tasks from API
   */
  async fetchTasks(): Promise<BackgroundTask[]> {
    try {
      const response = await apiClient.get<BackgroundTasksResponse>(
        '/api/background-tasks/active',
        { timeout: 10000 } // 10s timeout for background polling
      );
      const tasks = response.tasks || [];

      this.lastTasks = tasks;

      // Notify listeners
      this.notifyListeners(tasks);

      // Check for tasks needing clarification
      const clarificationTask = tasks.find(t =>
        t.status === 'needs_clarification' &&
        t.clarification_question &&
        t.clarification_question.length > 0
      );
      this.notifyClarificationListeners(clarificationTask || null);

      return tasks;
    } catch (error: any) {
      // Silently fail - don't log errors for background polling
      // This prevents Expo's LogBox from showing timeout errors
      return [];
    }
  }

  /**
   * Fetch recent tasks (including completed)
   */
  async fetchRecentTasks(limit: number = 10): Promise<BackgroundTask[]> {
    try {
      const response = await apiClient.get<BackgroundTasksResponse>(
        `/api/background-tasks/recent?limit=${limit}`,
        { timeout: 10000 } // 10s timeout for background polling
      );
      return response.tasks || [];
    } catch (error: any) {
      // Silently fail for background polling
      return [];
    }
  }

  /**
   * Submit clarification response
   */
  async submitClarification(taskId: string, response: string): Promise<boolean> {
    try {
      await apiClient.post(`/api/background-tasks/${taskId}/clarify`, {
        response: response.trim()
      });
      console.log('[BackgroundTasks] Clarification submitted for task:', taskId);

      // Refresh tasks
      await this.fetchTasks();
      return true;
    } catch (error) {
      console.error('[BackgroundTasks] Error submitting clarification:', error);
      return false;
    }
  }

  /**
   * Get the count of active tasks
   */
  getActiveCount(): number {
    return this.lastTasks.filter(t =>
      t.status === 'pending' || t.status === 'running'
    ).length;
  }

  /**
   * Get all cached tasks
   */
  getTasks(): BackgroundTask[] {
    return this.lastTasks;
  }

  /**
   * Subscribe to task updates
   */
  subscribe(listener: (tasks: BackgroundTask[]) => void): () => void {
    this.listeners.add(listener);

    // Immediately call with current tasks
    listener(this.lastTasks);

    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Subscribe to clarification requests
   */
  subscribeToClarifications(listener: (task: BackgroundTask | null) => void): () => void {
    this.clarificationListeners.add(listener);

    // Check current tasks for clarification
    const clarificationTask = this.lastTasks.find(t =>
      t.status === 'needs_clarification' &&
      t.clarification_question &&
      t.clarification_question.length > 0
    );
    listener(clarificationTask || null);

    return () => {
      this.clarificationListeners.delete(listener);
    };
  }

  private notifyListeners(tasks: BackgroundTask[]): void {
    this.listeners.forEach(listener => {
      try {
        listener(tasks);
      } catch (error) {
        console.error('[BackgroundTasks] Error in listener:', error);
      }
    });
  }

  private notifyClarificationListeners(task: BackgroundTask | null): void {
    this.clarificationListeners.forEach(listener => {
      try {
        listener(task);
      } catch (error) {
        console.error('[BackgroundTasks] Error in clarification listener:', error);
      }
    });
  }
}

// Export singleton instance
export const backgroundTaskService = new BackgroundTaskService();
export default backgroundTaskService;

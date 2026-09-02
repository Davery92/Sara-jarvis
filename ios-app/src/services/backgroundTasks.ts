import { DeviceEventEmitter } from 'react-native';
import { BackgroundTask, BackgroundTasksResponse } from '../types/api';
import apiClient from './api';

/**
 * Emitted by api.ts when a chat turn runs a dispatch tool, and again when the
 * turn ends. Polling alone leaves a 10–60s hole where Sara says "I've handed
 * that off" and the phone shows nothing — which is precisely how David ended up
 * having to take her word for it, then asking twice more (2026-09-01).
 */
export const TASK_DISPATCH_HINT_EVENT = 'saraTaskDispatchHint';
export const CHAT_TURN_COMPLETE_EVENT = 'saraChatTurnComplete';

/** Chat tools that mean "something is now running in the background". */
export const DISPATCH_TOOL_NAMES = [
  'create_research_plan',
  'dispatch_agent_task',
  'dispatch_and_monitor',
  'queue_for_sara',
  'code_mode',
];

/** How long an optimistic pill survives with no server confirmation. */
const OPTIMISTIC_TTL_MS = 90_000;

/** A failure stays loud for this long, so it can't be missed by looking away. */
export const FAILURE_VISIBLE_MS = 60 * 60 * 1000;

class BackgroundTaskService {
  private pollingInterval: NodeJS.Timeout | null = null;
  private listeners: Set<(tasks: BackgroundTask[]) => void> = new Set();
  private clarificationListeners: Set<(task: BackgroundTask | null) => void> = new Set();
  private lastTasks: BackgroundTask[] = [];
  private baseIntervalMs: number = 30000;
  private optimisticSince: number | null = null;
  private optimisticTool: string | null = null;
  private subscriptions: { remove: () => void }[] = [];

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

    this.attachChatHooks();

    console.log('[BackgroundTasks] Started polling');
  }

  /**
   * Listen for dispatch signals coming out of the chat stream so the indicator
   * appears the instant Sara hands work off, not on the next poll tick.
   */
  private attachChatHooks(): void {
    if (this.subscriptions.length > 0) return;

    this.subscriptions.push(
      DeviceEventEmitter.addListener(TASK_DISPATCH_HINT_EVENT, (tool?: string) => {
        this.noteDispatchStarted(tool);
      })
    );
    this.subscriptions.push(
      DeviceEventEmitter.addListener(CHAT_TURN_COMPLETE_EVENT, () => {
        // The dispatch row exists by the time the turn ends; reconcile at once.
        void this.fetchTasks();
      })
    );
  }

  /**
   * Optimistically show activity. Reconciled (or dropped) by the next fetch.
   */
  noteDispatchStarted(tool?: string): void {
    this.optimisticSince = Date.now();
    this.optimisticTool = tool || null;
    this.notifyListeners(this.lastTasks);
    // Give the backend a beat to write the row, then confirm for real.
    setTimeout(() => { void this.fetchTasks(); }, 1500);
  }

  /**
   * True while we believe a dispatch is in flight but the server hasn't shown
   * it to us yet. Expires on its own so a mis-fire can't pin the pill open.
   */
  hasPendingDispatch(): boolean {
    if (this.optimisticSince === null) return false;
    if (Date.now() - this.optimisticSince > OPTIMISTIC_TTL_MS) {
      this.optimisticSince = null;
      this.optimisticTool = null;
      return false;
    }
    return true;
  }

  getPendingDispatchLabel(): string | null {
    if (!this.hasPendingDispatch()) return null;
    return this.optimisticTool === 'create_research_plan'
      ? 'Starting research…'
      : 'Handing off…';
  }

  private scheduleNextPoll(): void {
    const hasActive = this.lastTasks.some(t => t.status === 'pending' || t.status === 'running');
    const interval = (hasActive || this.hasPendingDispatch()) ? this.baseIntervalMs : 60000;

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
    this.subscriptions.forEach(s => s.remove());
    this.subscriptions = [];
  }

  /**
   * Fetch the merged agent-activity feed (active + recently finished).
   *
   * This reads /recent rather than /active on purpose: failures have to be as
   * visible as activity, and a task that already failed is by definition not
   * active. Every consumer filters by status anyway.
   */
  async fetchTasks(): Promise<BackgroundTask[]> {
    try {
      const response = await apiClient.get<BackgroundTasksResponse>(
        '/api/background-tasks/recent?limit=15&include_active=true',
        { timeout: 10000 } // 10s timeout for background polling
      );
      const tasks = response.tasks || [];

      this.lastTasks = tasks;

      // Once the server shows us anything in flight, the optimistic guess has
      // done its job.
      if (tasks.some(t => t.status === 'pending' || t.status === 'running')) {
        this.optimisticSince = null;
        this.optimisticTool = null;
      }

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
   * Cancel an in-flight task. Research plans additionally revoke their worker
   * server-side, so this really does free the LLM lane.
   */
  async cancelTask(taskId: string): Promise<boolean> {
    try {
      await apiClient.post(`/api/background-tasks/${taskId}/cancel`, {});
      await this.fetchTasks();
      return true;
    } catch (error) {
      console.error('[BackgroundTasks] Error cancelling task:', error);
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

/** A task that ended badly recently enough that the user still needs to know. */
export function recentFailure(tasks: BackgroundTask[]): BackgroundTask | null {
  const cutoff = Date.now() - FAILURE_VISIBLE_MS;
  const failed = tasks
    .filter(t => t.status === 'failed')
    .filter(t => {
      const when = Date.parse(t.completed_at || t.updated_at || t.created_at || '');
      return !isNaN(when) && when >= cutoff;
    })
    .sort((a, b) =>
      Date.parse(b.completed_at || b.created_at) - Date.parse(a.completed_at || a.created_at)
    );
  return failed[0] || null;
}

// Export singleton instance
export const backgroundTaskService = new BackgroundTaskService();
export default backgroundTaskService;

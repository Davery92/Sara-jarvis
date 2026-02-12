import { Platform, Alert, Vibration } from 'react-native';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import apiClient from './api';

// Configure how notifications appear when app is in foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

// Notification action identifiers
const NOTIFICATION_ACTIONS = {
  LOG_MEAL: 'LOG_MEAL',
  REPLY: 'REPLY',
  VIEW_DETAILS: 'VIEW_DETAILS',
  DISMISS: 'DISMISS',
};

// Notification category identifiers
const NOTIFICATION_CATEGORIES = {
  MEAL_NUDGE: 'MEAL_NUDGE',
  MORNING_CHECKIN: 'MORNING_CHECKIN',
  HEALTH_ALERT: 'HEALTH_ALERT',
  GENERAL_NUDGE: 'GENERAL_NUDGE',
  SARA_INSIGHT: 'SARA_INSIGHT',
  THREAD_FOLLOWUP: 'THREAD_FOLLOWUP',
  LEARNING_REVIEW: 'LEARNING_REVIEW',
};

// Set up interactive notification categories
async function setupNotificationCategories() {
  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.MEAL_NUDGE, [
    {
      identifier: NOTIFICATION_ACTIONS.LOG_MEAL,
      buttonTitle: 'Log Meal',
      options: { opensAppToForeground: true },
    },
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Tell Sara...' },
    },
  ]);

  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.MORNING_CHECKIN, [
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Tell Sara...' },
    },
  ]);

  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.HEALTH_ALERT, [
    {
      identifier: NOTIFICATION_ACTIONS.VIEW_DETAILS,
      buttonTitle: 'View Details',
      options: { opensAppToForeground: true },
    },
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Ask Sara...' },
    },
  ]);

  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.GENERAL_NUDGE, [
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Tell Sara...' },
    },
  ]);

  // Sara proactive observations/insights
  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.SARA_INSIGHT, [
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Reply to Sara...' },
    },
    {
      identifier: NOTIFICATION_ACTIONS.VIEW_DETAILS,
      buttonTitle: 'View',
      options: { opensAppToForeground: true },
    },
    {
      identifier: NOTIFICATION_ACTIONS.DISMISS,
      buttonTitle: 'Not Now',
      options: { opensAppToForeground: false },
    },
  ]);

  // Thread follow-ups (Sara following up on a prior topic)
  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.THREAD_FOLLOWUP, [
    {
      identifier: NOTIFICATION_ACTIONS.REPLY,
      buttonTitle: 'Reply',
      options: { opensAppToForeground: true },
      textInput: { submitButtonTitle: 'Send', placeholder: 'Reply...' },
    },
    {
      identifier: NOTIFICATION_ACTIONS.DISMISS,
      buttonTitle: 'Dismiss',
      options: { opensAppToForeground: false },
    },
  ]);

  // Learning spaced repetition review reminders
  await Notifications.setNotificationCategoryAsync(NOTIFICATION_CATEGORIES.LEARNING_REVIEW, [
    {
      identifier: NOTIFICATION_ACTIONS.VIEW_DETAILS,
      buttonTitle: 'Start Review',
      options: { opensAppToForeground: true },
    },
    {
      identifier: NOTIFICATION_ACTIONS.DISMISS,
      buttonTitle: 'Later',
      options: { opensAppToForeground: false },
    },
  ]);

  console.log('[PushNotifications] Notification categories set up');
}

// Initialize categories on module load
setupNotificationCategories();

export interface PushNotificationState {
  expoPushToken: string | null;
  notification: Notifications.Notification | null;
}

class PushNotificationService {
  private expoPushToken: string | null = null;
  private notificationListener: Notifications.Subscription | null = null;
  private responseListener: Notifications.Subscription | null = null;
  private onNotificationReceived: ((notification: Notifications.Notification) => void) | null = null;
  private onNotificationResponse: ((response: Notifications.NotificationResponse) => void) | null = null;
  // Store pending notification response that launched the app (before callbacks are ready)
  private pendingNotificationResponse: Notifications.NotificationResponse | null = null;
  private callbacksReady: boolean = false;

  /**
   * Initialize push notifications
   */
  async initialize(): Promise<string | null> {
    try {
      // Log presence - user opened the app
      await apiClient.logPresence('app_open');

      // Register for push notifications
      const token = await this.registerForPushNotifications();

      if (token) {
        this.expoPushToken = token;

        // Check if app was launched from a notification BEFORE setting up listeners
        // This prevents a race condition where the listener fires before we capture the pending response
        const lastResponse = await Notifications.getLastNotificationResponseAsync();
        if (lastResponse) {
          console.log('[PushNotifications] App launched from notification:', lastResponse);
          // Store it - will be processed when callbacks are ready
          this.pendingNotificationResponse = lastResponse;
        }

        // Send token to backend
        await this.sendTokenToBackend(token);

        // Set up notification listeners (after capturing pending response)
        this.setupNotificationListeners();
      }

      return token;
    } catch (error) {
      console.error('[PushNotifications] Initialization error:', error);
      return null;
    }
  }

  /**
   * Mark callbacks as ready and process any pending notification response
   * Call this after all callbacks (setOnNudgeTapped, setOnQuickReply, etc.) are set up
   */
  markCallbacksReady(): void {
    this.callbacksReady = true;
    console.log('[PushNotifications] Callbacks marked as ready');

    // Process pending notification if any
    if (this.pendingNotificationResponse) {
      console.log('[PushNotifications] Processing pending notification response');
      const response = this.pendingNotificationResponse;
      this.pendingNotificationResponse = null;

      // Extract action identifier and user text
      const actionIdentifier = response.actionIdentifier;
      const userText = (response as any).userText;
      const data = response.notification.request.content.data;

      this.handleNotificationNavigation(data, actionIdentifier, userText);
    }
  }

  /**
   * Register for push notifications and get token
   */
  private async registerForPushNotifications(): Promise<string | null> {
    // Check if we're on a real device
    if (!Device.isDevice) {
      console.log('[PushNotifications] Must use physical device for push notifications');
      return null;
    }

    // Check existing permissions
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    // Request permissions if not granted
    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== 'granted') {
      console.log('[PushNotifications] Permission not granted');
      return null;
    }

    // Get the Expo push token
    try {
      const projectId = Constants.expoConfig?.extra?.eas?.projectId;

      const tokenResponse = await Notifications.getExpoPushTokenAsync({
        projectId: projectId,
      });

      console.log('[PushNotifications] Token:', tokenResponse.data);
      return tokenResponse.data;
    } catch (error) {
      console.error('[PushNotifications] Error getting token:', error);
      return null;
    }
  }

  /**
   * Send push token to backend for server-side notifications
   */
  private async sendTokenToBackend(token: string): Promise<void> {
    try {
      await apiClient.post('/api/push-tokens', {
        token,
        platform: Platform.OS,
        device_name: Device.deviceName || 'Unknown Device',
      });
      console.log('[PushNotifications] Token sent to backend');
    } catch (error) {
      console.error('[PushNotifications] Failed to send token to backend:', error);
    }
  }

  /**
   * Set up notification listeners
   */
  private setupNotificationListeners(): void {
    // Listener for when a notification is received while app is in foreground
    this.notificationListener = Notifications.addNotificationReceivedListener(
      (notification) => {
        console.log('[PushNotifications] Notification received:', notification);
        if (this.onNotificationReceived) {
          this.onNotificationReceived(notification);
        }
      }
    );

    // Listener for when user interacts with a notification
    this.responseListener = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        console.log('[PushNotifications] Notification response:', response);
        if (this.onNotificationResponse) {
          this.onNotificationResponse(response);
        }

        // Extract action identifier and user text input (if any)
        const actionIdentifier = response.actionIdentifier;
        const userText = (response as any).userText; // Text from reply action

        // Handle navigation based on notification data
        const data = response.notification.request.content.data;
        this.handleNotificationNavigation(data, actionIdentifier, userText);
      }
    );
  }

  /**
   * Handle navigation when user taps a notification
   */
  private handleNotificationNavigation(data: any, actionIdentifier?: string, userText?: string): void {
    if (!data) return;

    // Handle action button taps with text input
    if (userText && this.onQuickReply) {
      console.log('[PushNotifications] Quick reply from notification:', userText);
      this.onQuickReply(userText, {
        nudgeType: data.nudge_type || data.type,
        title: data.title,
      });
      return;
    }

    // Handle specific action buttons
    if (actionIdentifier === NOTIFICATION_ACTIONS.LOG_MEAL) {
      console.log('[PushNotifications] Log meal action tapped');
      if (this.onLogMealAction) {
        this.onLogMealAction();
      }
      return;
    }

    // Handle different notification types
    switch (data.type) {
      case 'timer_complete':
        // Navigate to timers or show alert
        Vibration.vibrate([0, 500, 200, 500]);
        break;
      case 'reminder':
        // Navigate to reminders
        break;
      case 'message':
        // Navigate to chat
        break;
      case 'health_sync':
        // Navigate to health/fitness screen
        console.log('[PushNotifications] Health sync notification:', data);
        if (this.onHealthAlertTapped) {
          this.onHealthAlertTapped(data.severity || 'info');
        }
        break;
      case 'health_alert':
        // Health watchdog alert - navigate to chat to discuss with Sara
        console.log('[PushNotifications] Health alert notification:', data);
        Vibration.vibrate([0, 300, 100, 300]); // Attention pattern
        if (this.onHealthAlertTapped) {
          this.onHealthAlertTapped(
            data.severity || 'warning',
            data.insight_id,
            data.title,
            data.body
          );
        } else {
          // Callback not ready yet - store for later processing
          console.log('[PushNotifications] Health alert callback not ready, storing for later');
          this.pendingHealthAlertData = {
            severity: data.severity || 'warning',
            insightId: data.insight_id,
            title: data.title,
            body: data.body,
          };
        }
        break;
      case 'subconscious_nudge':
        // Subconscious nudge (meal reminders, morning check-ins, etc.)
        console.log('[PushNotifications] Subconscious nudge tapped:', data);
        if (this.onNudgeTapped) {
          this.onNudgeTapped(
            data.nudge_type || 'general',
            data.title || '',
            data.message || data.body || '',
            data.action_suggestion
          );
        }
        break;
      case 'background_task':
        // Background task completed - notify listeners
        console.log('[PushNotifications] Background task notification:', data);
        if (this.onBackgroundTaskComplete) {
          this.onBackgroundTaskComplete(data.task_id, data.result_note_id);
        }
        break;
      case 'agent_clarification':
        // Agent needs clarification
        console.log('[PushNotifications] Agent clarification needed:', data);
        if (this.onAgentClarificationNeeded) {
          this.onAgentClarificationNeeded(data.task_id);
        }
        break;
      case 'chat_response':
        // Background chat response is ready - just open the app
        // ChatScreen's AppState listener will reload the conversation
        console.log('[PushNotifications] Chat response ready:', data.conversation_id);
        break;
      case 'sara_insight':
      case 'observation':
        // Sara proactive insight — open chat to discuss
        console.log('[PushNotifications] Sara insight notification:', data);
        if (this.onHeartbeatTapped) {
          this.onHeartbeatTapped(
            data.title || 'Sara noticed something',
            data.message || data.body || '',
            data.priority || 'normal'
          );
        }
        break;
      case 'thread_followup':
        // Thread follow-up — Sara following up on a prior conversation topic
        console.log('[PushNotifications] Thread follow-up notification:', data);
        if (this.onHeartbeatTapped) {
          this.onHeartbeatTapped(
            data.title || 'Following up',
            data.message || data.body || '',
            data.priority || 'normal'
          );
        }
        break;
      case 'learning_review':
        // Learning spaced repetition review reminder
        console.log('[PushNotifications] Learning review notification:', data);
        if (this.onNudgeTapped) {
          this.onNudgeTapped(
            'learning_review',
            data.title || 'Review time',
            data.message || data.body || 'You have topics due for review',
            'Open Learning tab to review'
          );
        }
        break;
      case 'heartbeat':
      case 'unified_heartbeat':
      case 'checkin':
        // Heartbeat/check-in notification from Sara - open chat
        console.log('[PushNotifications] Heartbeat notification:', data);
        if (this.onHeartbeatTapped) {
          this.onHeartbeatTapped(
            data.title || 'Sara noticed something',
            data.message || '',
            data.priority || 'normal'
          );
        }
        break;
      default:
        // Any other notification type - navigate to chat as default
        console.log('[PushNotifications] Unknown notification type, navigating to chat:', data.type);
        if (this.onHeartbeatTapped) {
          this.onHeartbeatTapped(
            data.title || 'Sara',
            data.message || '',
            data.priority || 'normal'
          );
        }
        break;
    }
  }

  // Callback for background task completion
  private onBackgroundTaskComplete: ((taskId: string, noteId?: string) => void) | null = null;
  private onAgentClarificationNeeded: ((taskId: string) => void) | null = null;
  private onHealthAlertTapped: ((severity: string, insightId?: string, title?: string, body?: string) => void) | null = null;
  // Callback for heartbeat notifications (proactive check-ins from Sara)
  private onHeartbeatTapped: ((title: string, message: string, priority: string) => void) | null = null;
  // Pending health alert data (stored if callback wasn't ready when notification was tapped)
  private pendingHealthAlertData: { severity: string; insightId?: string; title?: string; body?: string } | null = null;
  // Callback for subconscious nudges (meal reminders, morning check-ins, etc.)
  private onNudgeTapped: ((nudgeType: string, title: string, message: string, actionSuggestion?: string) => void) | null = null;
  // Callback for quick reply from notification
  private onQuickReply: ((message: string, context?: { nudgeType?: string; title?: string }) => void) | null = null;
  // Callback for log meal action
  private onLogMealAction: (() => void) | null = null;

  /**
   * Set callback for background task completion
   */
  setOnBackgroundTaskComplete(
    callback: (taskId: string, noteId?: string) => void
  ): void {
    this.onBackgroundTaskComplete = callback;
  }

  /**
   * Set callback for agent clarification needed
   */
  setOnAgentClarificationNeeded(
    callback: (taskId: string) => void
  ): void {
    this.onAgentClarificationNeeded = callback;
  }

  /**
   * Set callback for health alert tapped
   */
  setOnHealthAlertTapped(
    callback: (severity: string, insightId?: string, title?: string, body?: string) => void
  ): void {
    this.onHealthAlertTapped = callback;

    // Process any pending health alert that was stored before callback was ready
    if (this.pendingHealthAlertData) {
      console.log('[PushNotifications] Processing pending health alert data');
      const { severity, insightId, title, body } = this.pendingHealthAlertData;
      this.pendingHealthAlertData = null;
      // Call asynchronously to avoid blocking
      setTimeout(() => {
        callback(severity, insightId, title, body);
      }, 100);
    }
  }

  /**
   * Set callback for subconscious nudge tapped (meal reminders, morning check-ins, etc.)
   */
  setOnNudgeTapped(
    callback: (nudgeType: string, title: string, message: string, actionSuggestion?: string) => void
  ): void {
    this.onNudgeTapped = callback;
  }

  /**
   * Set callback for quick reply from notification action button
   */
  setOnQuickReply(
    callback: (message: string, context?: { nudgeType?: string; title?: string }) => void
  ): void {
    this.onQuickReply = callback;
  }

  /**
   * Set callback for log meal action button
   */
  setOnLogMealAction(callback: () => void): void {
    this.onLogMealAction = callback;
  }

  /**
   * Set callback for heartbeat notifications (proactive check-ins from Sara)
   * When tapped, opens the chat with context about what Sara noticed
   */
  setOnHeartbeatTapped(
    callback: (title: string, message: string, priority: string) => void
  ): void {
    this.onHeartbeatTapped = callback;
  }

  /**
   * Set callback for when notification is received in foreground
   */
  setOnNotificationReceived(
    callback: (notification: Notifications.Notification) => void
  ): void {
    this.onNotificationReceived = callback;
  }

  /**
   * Set callback for when user interacts with notification
   */
  setOnNotificationResponse(
    callback: (response: Notifications.NotificationResponse) => void
  ): void {
    this.onNotificationResponse = callback;
  }

  /**
   * Schedule a local notification
   */
  async scheduleLocalNotification(
    title: string,
    body: string,
    trigger: Notifications.NotificationTriggerInput,
    data?: Record<string, any>
  ): Promise<string> {
    const id = await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: data || {},
        sound: true,
        priority: Notifications.AndroidNotificationPriority.HIGH,
      },
      trigger,
    });

    console.log('[PushNotifications] Scheduled notification:', id);
    return id;
  }

  /**
   * Schedule a timer notification
   */
  async scheduleTimerNotification(title: string, seconds: number): Promise<string> {
    return this.scheduleLocalNotification(
      'Timer Complete',
      title,
      { seconds, repeats: false },
      { type: 'timer_complete', timer_name: title }
    );
  }

  /**
   * Schedule a reminder notification
   */
  async scheduleReminderNotification(
    title: string,
    body: string,
    date: Date,
    reminderId?: string
  ): Promise<string> {
    return this.scheduleLocalNotification(
      title,
      body,
      { date },
      { type: 'reminder', reminder_id: reminderId }
    );
  }

  /**
   * Cancel a scheduled notification
   */
  async cancelNotification(notificationId: string): Promise<void> {
    await Notifications.cancelScheduledNotificationAsync(notificationId);
    console.log('[PushNotifications] Cancelled notification:', notificationId);
  }

  /**
   * Cancel all scheduled notifications
   */
  async cancelAllNotifications(): Promise<void> {
    await Notifications.cancelAllScheduledNotificationsAsync();
    console.log('[PushNotifications] Cancelled all notifications');
  }

  /**
   * Get all scheduled notifications
   */
  async getScheduledNotifications(): Promise<Notifications.NotificationRequest[]> {
    return Notifications.getAllScheduledNotificationsAsync();
  }

  /**
   * Show an immediate local notification
   */
  async showImmediateNotification(title: string, body: string, data?: Record<string, any>): Promise<string> {
    const id = await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: data || {},
        sound: true,
      },
      trigger: null, // Show immediately
    });

    return id;
  }

  /**
   * Set badge count
   */
  async setBadgeCount(count: number): Promise<void> {
    await Notifications.setBadgeCountAsync(count);
  }

  /**
   * Get current push token
   */
  getToken(): string | null {
    return this.expoPushToken;
  }

  /**
   * Clean up listeners
   */
  cleanup(): void {
    if (this.notificationListener) {
      Notifications.removeNotificationSubscription(this.notificationListener);
      this.notificationListener = null;
    }
    if (this.responseListener) {
      Notifications.removeNotificationSubscription(this.responseListener);
      this.responseListener = null;
    }
  }
}

// Export singleton instance
export const pushNotificationService = new PushNotificationService();
export default pushNotificationService;

// Legacy exports for backward compatibility
export async function registerForPushNotificationsAsync(): Promise<string | null> {
  return pushNotificationService.initialize();
}

export async function scheduleTimerNotification(title: string, seconds: number): Promise<string | null> {
  try {
    return await pushNotificationService.scheduleTimerNotification(title, seconds);
  } catch (error) {
    console.error('[PushNotifications] Error scheduling timer:', error);
    return null;
  }
}

export function showTimerCompleteAlert(title: string): void {
  // Vibrate to get user's attention
  if (Platform.OS === 'ios') {
    Vibration.vibrate([0, 500, 200, 500]);
  } else {
    Vibration.vibrate(1000);
  }

  // Show alert
  Alert.alert('Timer Complete', title, [{ text: 'OK' }]);
}

export async function cancelAllNotifications(): Promise<void> {
  await pushNotificationService.cancelAllNotifications();
}

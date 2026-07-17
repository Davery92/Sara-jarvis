import { Platform, Alert, Vibration } from 'react-native';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import apiClient from './api';
import { navigateToChat, navigateToInbox, navigateToNoteEditor, navigateToFitness, navigateToNotifications, navigate } from './navigation';
import { endEvent } from './eventActivity';

// Push types that mean a background task reached a terminal state — the
// "Sara is working" Live Activity for it must be torn down on sight.
const TASK_TERMINAL_PUSH_TYPES = new Set([
  'background_task',
  'research_complete',
  'task_chat_inject',
]);

/** Ends the task Live Activity named by a terminal-task push, if any. */
function endTaskActivityFromPush(data: any): void {
  if (data?.task_id && TASK_TERMINAL_PUSH_TYPES.has(data?.type)) {
    endEvent(String(data.task_id));
  }
}

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
  DISLIKE: 'DISLIKE',
};

// Notification category identifiers
const NOTIFICATION_CATEGORIES = {
  MEAL_NUDGE: 'MEAL_NUDGE',
  MORNING_CHECKIN: 'MORNING_CHECKIN',
  HEALTH_ALERT: 'HEALTH_ALERT',
  GENERAL_NUDGE: 'GENERAL_NUDGE',
  SARA_INSIGHT: 'SARA_INSIGHT',
  ACS_DISCOVERY: 'ACS_DISCOVERY',
  THREAD_FOLLOWUP: 'THREAD_FOLLOWUP',
  LEARNING_REVIEW: 'LEARNING_REVIEW',
};

// Set up interactive notification categories
async function setupNotificationCategories() {
  // A "Dislike" action is appended to EVERY category so David can tell Sara, at
  // notify-time (long-press), that he didn't want this. It runs in the
  // background (no app open) and feeds the learner's fast 'stop' signal.
  const DISLIKE = {
    identifier: NOTIFICATION_ACTIONS.DISLIKE,
    buttonTitle: '👎 Dislike',
    options: { opensAppToForeground: false, isDestructive: true },
  };

  const REPLY = (placeholder: string) => ({
    identifier: NOTIFICATION_ACTIONS.REPLY,
    buttonTitle: 'Reply',
    options: { opensAppToForeground: true },
    textInput: { submitButtonTitle: 'Send', placeholder },
  });
  const VIEW = (buttonTitle = 'View') => ({
    identifier: NOTIFICATION_ACTIONS.VIEW_DETAILS,
    buttonTitle,
    options: { opensAppToForeground: true },
  });
  const DISMISS = (buttonTitle = 'Not Now') => ({
    identifier: NOTIFICATION_ACTIONS.DISMISS,
    buttonTitle,
    options: { opensAppToForeground: false },
  });

  const categoryActions: Record<string, any[]> = {
    [NOTIFICATION_CATEGORIES.MEAL_NUDGE]: [
      { identifier: NOTIFICATION_ACTIONS.LOG_MEAL, buttonTitle: 'Log Meal', options: { opensAppToForeground: true } },
      REPLY('Tell Sara...'),
    ],
    [NOTIFICATION_CATEGORIES.MORNING_CHECKIN]: [REPLY('Tell Sara...')],
    [NOTIFICATION_CATEGORIES.HEALTH_ALERT]: [VIEW('View Details'), REPLY('Ask Sara...')],
    [NOTIFICATION_CATEGORIES.GENERAL_NUDGE]: [REPLY('Tell Sara...')],
    [NOTIFICATION_CATEGORIES.SARA_INSIGHT]: [REPLY('Reply to Sara...'), VIEW(), DISMISS('Not Now')],
    [NOTIFICATION_CATEGORIES.ACS_DISCOVERY]: [VIEW(), DISMISS('Not Now')],
    [NOTIFICATION_CATEGORIES.THREAD_FOLLOWUP]: [REPLY('Reply...'), DISMISS('Dismiss')],
    [NOTIFICATION_CATEGORIES.LEARNING_REVIEW]: [VIEW('Start Review'), DISMISS('Later')],
  };

  for (const [category, actions] of Object.entries(categoryActions)) {
    await Notifications.setNotificationCategoryAsync(category, [...actions, DISLIKE]);
  }

  console.log('[PushNotifications] Notification categories set up (with Dislike)');
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
      // Merge canonical title/body from the notification content into `data`
      // so handlers can always rely on data.title / data.body, even when the
      // backend didn't duplicate them into the data dict.
      const content = response.notification.request.content;
      const data = {
        ...(content.data || {}),
        ...(content.title && !((content.data || {}) as any).title ? { title: content.title } : {}),
        ...(content.body && !((content.data || {}) as any).body ? { body: content.body } : {}),
      };

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
        // Task finished while the app is foregrounded — don't wait for the
        // next poll cycle (or a tap) to clear the Live Activity.
        endTaskActivityFromPush(notification.request.content.data);
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

        // Track notification feedback. Merge canonical title/body from the
        // notification content into `data` so handlers can always rely on
        // data.title / data.body — see the matching block in
        // markCallbacksReady() for why.
        const content = response.notification.request.content;
        const data = {
          ...(content.data || {}),
          ...(content.title && !((content.data || {}) as any).title ? { title: content.title } : {}),
          ...(content.body && !((content.data || {}) as any).body ? { body: content.body } : {}),
        };
        if (data?.notification_id) {
          const notifId = Number(data.notification_id);
          if (!isNaN(notifId)) {
            if (actionIdentifier === NOTIFICATION_ACTIONS.DISLIKE) {
              // Explicit "I dislike this" — strongest negative signal.
              apiClient.sendNotificationFeedback(notifId, 'dislike');
            } else if (actionIdentifier === NOTIFICATION_ACTIONS.DISMISS) {
              apiClient.sendNotificationFeedback(notifId, 'dismissed');
            } else {
              // Any other interaction (tap, reply, view) counts as engaged
              apiClient.sendNotificationFeedback(
                notifId,
                'engaged',
                userText || undefined,
              );
            }
          }
        }

        // Handle navigation based on notification data
        this.handleNotificationNavigation(data, actionIdentifier, userText);
      }
    );
  }

  /**
   * Handle navigation when user taps a notification
   */
  /**
   * Generic deep-link router. The server sets `data.target` (+ optional
   * `data.params`) on every push so a tap opens the relevant area. Returns true
   * if it handled the target. Falls through to type-based routing otherwise.
   */
  private routeByTarget(target?: string, params?: any, data?: any): boolean {
    if (!target) return false;
    const p = params || {};
    try {
      switch (String(target).toLowerCase()) {
        case 'chat': {
          // Proactive check-ins / follow-ups are Sara *talking to you* — they
          // should drop her message into the chat so you can just reply, NOT
          // open the "Discuss this" templated-prompt flow (that's for reviewing
          // an ACS discovery/notification). Route those through the heartbeat
          // param, which ChatScreen renders as an assistant message + open
          // composer. Everything else keeps the old notification behaviour.
          const ptype = String(data?.type || '').toLowerCase();
          const pcat = String(data?.category || '').toLowerCase();
          const isCheckin =
            ptype === 'proactive_checkin' ||
            ptype === 'heartbeat' ||
            ptype === 'unified_heartbeat' ||
            pcat === 'checkin' ||
            pcat === 'followup';
          if (!p.chat && isCheckin) {
            navigateToChat({
              heartbeat: {
                title: data?.title || 'Checking in',
                message: data?.message || data?.body || '',
                priority: data?.priority || 'normal',
              },
            });
          } else {
            navigateToChat(p.chat || { notification: data });
          }
          return true;
        }
        case 'inbox': navigateToInbox({ focus: p.focus || 'new' }); return true;
        case 'notifications': navigateToNotifications(); return true;
        case 'email': navigate('Email', p); return true;
        case 'agent_tasks': navigate('AgentTasks', p); return true;
        case 'calendar': navigate('Calendar', p); return true;
        case 'fitness': navigateToFitness(); return true;
        case 'learn': navigate('Learning', p); return true;
        case 'acs': navigate('ACS', p); return true;
        case 'knowledge': navigate('Knowledge', p); return true;
        // "System" = Sara's awareness/proactive thoughts → open the System hub.
        case 'system': navigate('System'); return true;
        case 'notes':
          if (data?.note_id) navigateToNoteEditor(data.note_id);
          else navigate('Notes', p);
          return true;
        default: return false;
      }
    } catch (e) {
      console.warn('[PushNotifications] routeByTarget failed', e);
      return false;
    }
  }

  private handleNotificationNavigation(data: any, actionIdentifier?: string, userText?: string): void {
    if (!data) return;

    // "Dislike" is a pure background feedback signal — never open or navigate.
    if (actionIdentifier === NOTIFICATION_ACTIONS.DISLIKE) return;

    // Tapping a "task done" notification must also clear its Live Activity —
    // the app may have been backgrounded/killed when the push landed.
    endTaskActivityFromPush(data);

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

    // Generic deep-link target wins over type-based routing (server sets it on
    // every push). A body TAP uses the DEFAULT action identifier (which is a
    // non-empty string), so treat tap + "View" as open-intents. Quick-reply,
    // Log-Meal, and Dislike are handled and returned above this point.
    const isOpenIntent =
      !actionIdentifier ||
      actionIdentifier === Notifications.DEFAULT_ACTION_IDENTIFIER ||
      actionIdentifier === NOTIFICATION_ACTIONS.VIEW_DETAILS;
    if (isOpenIntent && this.routeByTarget(data.target, data.params, data)) {
      return;
    }

    // Handle different notification types
    switch (data.type) {
      case 'timer_complete':
        // Navigate to timers or show alert
        Vibration.vibrate([0, 500, 200, 500]);
        break;
      case 'reminder':
        // Reminder-style notifications belong in the assistant inbox
        console.log('[PushNotifications] Reminder notification:', data);
        navigateToInbox({ focus: 'new' });
        break;
      case 'message':
        // Direct conversational messages should land in chat
        console.log('[PushNotifications] Message notification:', data);
        navigateToChat();
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
      case 'task_chat_inject':
        // Background task result was persisted to conversation — reload chat
        console.log('[PushNotifications] Task chat inject:', data);
        if (this.onTaskChatInject) {
          this.onTaskChatInject(data.task_id, data.conversation_id, data.note_id);
        }
        break;
      case 'background_task': {
        // Background task completed. If it produced a report note, deep-link
        // straight to it; otherwise fall back to the inbox. (Backend sends the
        // id as both `note_id` and `result_note_id`.)
        console.log('[PushNotifications] Background task notification:', data);
        const bgNoteId = data.note_id || data.result_note_id;
        if (this.onBackgroundTaskComplete) {
          this.onBackgroundTaskComplete(data.task_id, bgNoteId);
        }
        if (bgNoteId) {
          navigateToNoteEditor(bgNoteId);
        } else {
          navigateToInbox({ focus: 'done' });
        }
        break;
      }
      case 'research_complete':
        // Chat-initiated research plan finished — open the report note directly.
        console.log('[PushNotifications] Research complete:', data);
        if (data.note_id) {
          navigateToNoteEditor(data.note_id);
        } else {
          navigateToInbox({ focus: 'done' });
        }
        break;
      case 'acs_daemon':
        // The in-VM ACS daemon (Sara) is pinging David. If she included a
        // note_id, deep-link to the note she just wrote. Otherwise route
        // to chat — the conversation is the closest thing to "go talk to her."
        console.log('[PushNotifications] ACS daemon notification:', data);
        if (data.note_id) {
          navigateToNoteEditor(data.note_id);
        } else {
          navigateToChat();
        }
        break;
      case 'agent_clarification':
        // Agent needs clarification
        console.log('[PushNotifications] Agent clarification needed:', data);
        if (this.onAgentClarificationNeeded) {
          this.onAgentClarificationNeeded(data.task_id);
        }
        navigateToInbox({ focus: 'waiting' });
        break;
      case 'chat_response':
        // Background chat response is ready - return to Sara chat
        console.log('[PushNotifications] Chat response ready:', data.conversation_id);
        navigateToChat();
        break;
      case 'sara_insight':
      case 'observation':
        // Sara proactive insight — open the assistant inbox
        console.log('[PushNotifications] Sara insight notification:', data);
        navigateToInbox({ focus: 'new' });
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
      case 'inbox_digest':
      case 'inbox':
        // Morning inbox summary - open Inbox directly
        console.log('[PushNotifications] Inbox digest notification:', data);
        navigateToInbox({ focus: 'new' });
        break;
      case 'attention_digest':
        // Attention backlog summary - open Inbox Attention tab
        console.log('[PushNotifications] Attention digest notification:', data);
        navigateToInbox({ focus: 'waiting' });
        break;
      case 'heartbeat':
      case 'unified_heartbeat':
      case 'checkin':
        // Heartbeat/check-in notification from Sara
        console.log('[PushNotifications] Heartbeat notification:', data);
        navigateToInbox({ focus: 'new' });
        break;
      default:
        // Unknown async notifications should still land in the assistant inbox
        console.log('[PushNotifications] Notification tapped, opening assistant inbox:', data.type);
        navigateToInbox({ focus: 'new' });
        break;
    }
  }

  // Callback for task chat inject (result persisted to conversation — reload chat)
  private onTaskChatInject: ((taskId: string, conversationId?: string, noteId?: string) => void) | null = null;
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
   * Set callback for task chat inject (task result was persisted — reload conversation)
   */
  setOnTaskChatInject(
    callback: (taskId: string, conversationId?: string, noteId?: string) => void
  ): void {
    this.onTaskChatInject = callback;
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

// Re-export everything from the new push notification service
// This file is kept for backward compatibility
export {
  registerForPushNotificationsAsync,
  scheduleTimerNotification,
  showTimerCompleteAlert,
  cancelAllNotifications,
  pushNotificationService,
} from '../services/pushNotifications';

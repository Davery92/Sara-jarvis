/**
 * Navigation Service
 *
 * Provides navigation capabilities from outside React components.
 * Used for deep linking from push notifications.
 */

import { createNavigationContainerRef, CommonActions } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

export const navigationRef = createNavigationContainerRef<RootStackParamList>();

// Queue for pending navigations when navigator isn't ready
type PendingNavigation =
  | { kind: 'tab'; name: string; params?: object }
  | { kind: 'stack'; name: string; params?: object };

let pendingNavigation: PendingNavigation | null = null;

/**
 * Process any pending navigation once navigator is ready
 * Call this from NavigationContainer's onReady callback
 */
export function onNavigatorReady() {
  console.log('[Navigation] Navigator is ready');
  if (pendingNavigation) {
    console.log('[Navigation] Processing pending navigation to:', pendingNavigation.name);
    const { kind, name, params } = pendingNavigation;
    pendingNavigation = null;
    if (kind === 'tab') {
      navigateToTab(name, params);
    } else {
      navigateToStackScreen(name, params);
    }
  }
}

/**
 * Navigate to a screen
 */
export function navigate(name: string, params?: object) {
  if (navigationRef.isReady()) {
    navigationRef.dispatch(
      CommonActions.navigate({
        name,
        params,
      })
    );
  } else {
    console.log('[Navigation] Navigator not ready, queueing navigation to:', name);
    // Could queue navigation for later, but usually the ref is ready quickly
  }
}

/**
 * Navigate to a specific tab with optional params
 */
export function navigateToTab(tabName: string, params?: object) {
  if (navigationRef.isReady()) {
    try {
      // Navigate through the nested structure: Main -> MainTabs -> tabName
      // @ts-ignore
      navigationRef.navigate('Main', {
        screen: 'MainTabs',
        params: {
          screen: tabName,
          params: params,
        },
      });
    } catch (error) {
      console.error('[Navigation] Error navigating to', tabName, error);
    }
  } else {
    console.log('[Navigation] Navigator not ready, queueing navigation to:', tabName);
    pendingNavigation = { kind: 'tab', name: tabName, params };
  }
}

function navigateToStackScreen(screenName: string, params?: object) {
  if (navigationRef.isReady()) {
    try {
      // @ts-ignore
      navigationRef.navigate('Main', {
        screen: screenName,
        params,
      });
    } catch (error) {
      console.error('[Navigation] Error navigating to screen:', screenName, error);
    }
  } else {
    console.log('[Navigation] Navigator not ready, queueing stack navigation to:', screenName);
    pendingNavigation = { kind: 'stack', name: screenName, params };
  }
}

/**
 * Navigate to Fitness tab
 */
export function navigateToFitness() {
  navigateToTab('Fitness');
}

/**
 * Navigate to Chat tab with optional context
 */
export function navigateToChat(params?: {
  healthAlert?: { severity: string; insightId?: string; title?: string; body?: string };
  nudge?: { nudgeType: string; title: string; message: string; actionSuggestion?: string };
  quickReply?: { message: string; nudgeType?: string; title?: string };
  heartbeat?: { title: string; message: string; priority: string };
  inboxItem?: { id: string; title: string };
  taskInject?: { taskId: string; conversationId?: string; noteId?: string };
  notification?: { id: string; title: string; message: string; category: string; item_type: string };
}) {
  console.log('[Navigation] navigateToChat called with params:', params);
  navigateToTab('Sara', params);
}

/**
 * Navigate to Inbox screen
 */
export function navigateToInbox(
  params: { tab?: 'content' | 'attention' } = { tab: 'content' }
) {
  navigateToStackScreen('Inbox', params);
}

export function navigateToNotifications(params?: { notificationId?: number }) {
  navigateToStackScreen('Notifications', params);
}

/**
 * Go back
 */
export function goBack() {
  if (navigationRef.isReady() && navigationRef.canGoBack()) {
    navigationRef.goBack();
  }
}

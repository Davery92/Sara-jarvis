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
let pendingNavigation: { tabName: string; params?: object } | null = null;

/**
 * Process any pending navigation once navigator is ready
 * Call this from NavigationContainer's onReady callback
 */
export function onNavigatorReady() {
  console.log('[Navigation] Navigator is ready');
  if (pendingNavigation) {
    console.log('[Navigation] Processing pending navigation to:', pendingNavigation.tabName);
    const { tabName, params } = pendingNavigation;
    pendingNavigation = null;
    navigateToTab(tabName, params);
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
    navigationRef.dispatch(
      CommonActions.navigate({
        name: 'Main',
        params: {
          screen: tabName,
          params: params,
        },
      })
    );
  } else {
    // Queue the navigation for when navigator is ready
    console.log('[Navigation] Navigator not ready, queueing tab navigation to:', tabName);
    pendingNavigation = { tabName, params };
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
}) {
  navigateToTab('Chat', params);
}

/**
 * Go back
 */
export function goBack() {
  if (navigationRef.isReady() && navigationRef.canGoBack()) {
    navigationRef.goBack();
  }
}

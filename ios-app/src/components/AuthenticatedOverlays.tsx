/**
 * AuthenticatedOverlays Component
 *
 * Container for overlay components that should only be visible when authenticated.
 * Includes TimerOverlayContainer and FloatingAssistant (Sara orb/mini-chat overlay).
 * Also handles authenticated-only initialization like push notifications.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Platform, AppState, AppStateStatus, DeviceEventEmitter } from 'react-native';
import { useAuth } from '../context/AuthContext';
import TimerOverlayContainer from './TimerOverlayContainer';
import FloatingAssistant from './sara/FloatingAssistant';
import { pushNotificationService } from '../services/pushNotifications';
import { healthSyncService } from '../services/healthSync';
import { registerBackgroundHealthSync, triggerManualSync } from '../services/backgroundHealthSync';
import { iosCalendarSyncService } from '../services/iosCalendarSync';
import { navigateToChat } from '../services/navigation';
import apiClient from '../services/api';
import { consumeSiriPrompt } from '../services/siriDeepLink';
import { refreshWidgetData } from '../services/widgetBridge';

export const AuthenticatedOverlays: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const [pushToken, setPushToken] = useState<string | null>(null);
  const hasInitialized = useRef(false);

  // Initialize services that require authentication
  useEffect(() => {
    if (!isAuthenticated || hasInitialized.current) {
      return;
    }

    hasInitialized.current = true;

    // Initialize push notifications (now that we're authenticated)
    const initNotifications = async () => {
      try {
        const token = await pushNotificationService.initialize();
        if (token) {
          setPushToken(token);
          console.log('[AuthenticatedOverlays] Push notifications initialized with token:', token);

          // Set up health alert tap handler - navigate to chat so Sara can explain
          pushNotificationService.setOnHealthAlertTapped((severity, insightId, title, body) => {
            console.log('[AuthenticatedOverlays] Health alert tapped, navigating to chat');
            // Delay navigation slightly to allow app initialization to complete
            setTimeout(() => {
              console.log('[AuthenticatedOverlays] Executing delayed navigation to chat');
              navigateToChat({
                healthAlert: { severity, insightId, title, body }
              });
            }, 500);
          });

          // Set up nudge tap handler - navigate to chat with Sara's message in context
          pushNotificationService.setOnNudgeTapped((nudgeType, title, message, actionSuggestion) => {
            console.log('[AuthenticatedOverlays] Nudge tapped, navigating to chat:', nudgeType);
            navigateToChat({
              nudge: { nudgeType, title, message, actionSuggestion }
            });
          });

          // Set up quick reply handler - user replied from notification action
          pushNotificationService.setOnQuickReply((message, context) => {
            console.log('[AuthenticatedOverlays] Quick reply from notification:', message);
            navigateToChat({
              quickReply: { message, nudgeType: context?.nudgeType, title: context?.title }
            });
          });

          // Set up heartbeat tap handler - proactive check-ins from Sara
          pushNotificationService.setOnHeartbeatTapped((title, message, priority) => {
            console.log('[AuthenticatedOverlays] Heartbeat notification tapped:', title);
            navigateToChat({
              heartbeat: { title, message, priority }
            });
          });

          // Set up log meal action handler - navigate to fitness tab to log meal
          pushNotificationService.setOnLogMealAction(() => {
            console.log('[AuthenticatedOverlays] Log meal action tapped');
            // Navigate to fitness screen where user can log a meal
            navigateToChat({
              quickReply: { message: 'I want to log a meal' }
            });
          });

          // Set up task chat inject handler - task result was persisted, reload conversation
          pushNotificationService.setOnTaskChatInject((taskId, conversationId, noteId) => {
            console.log('[AuthenticatedOverlays] Task chat inject, reloading conversation:', taskId);
            navigateToChat({ taskInject: { taskId, conversationId, noteId } });
          });

          // Mark callbacks as ready - this will process any pending notification that launched the app
          pushNotificationService.markCallbacksReady();
        } else {
          console.log('[AuthenticatedOverlays] Push notifications not available (requires native build)');
        }
      } catch (error) {
        console.log('[AuthenticatedOverlays] Failed to initialize push notifications:', error);
      }
    };

    // Register background health sync
    const initBackgroundHealthSync = async () => {
      try {
        const registered = await registerBackgroundHealthSync();
        if (registered) {
          console.log('[AuthenticatedOverlays] Background health sync registered (15-min interval)');
        }
      } catch (error) {
        console.log('[AuthenticatedOverlays] Failed to register background health sync:', error);
      }
    };

    // Sync HealthKit data on app open
    const syncHealth = async () => {
      try {
        const result = await healthSyncService.forceSync();
        console.log('[AuthenticatedOverlays] Health sync result:', result.message);

        // Also trigger granular metrics sync
        const granularResult = await triggerManualSync();
        console.log(`[AuthenticatedOverlays] Granular health sync: ${granularResult.metricCount} metrics`);
      } catch (error) {
        console.log('[AuthenticatedOverlays] Health sync failed:', error);
      }
    };

    // Sync iOS calendar on app open
    const syncIOSCalendar = async () => {
      if (Platform.OS !== 'ios') return;

      try {
        const result = await iosCalendarSyncService.syncSelectedCalendars();
        if (result.synced > 0) {
          console.log(`[AuthenticatedOverlays] iOS calendar sync: ${result.synced} events synced`);
        }
      } catch (error) {
        console.log('[AuthenticatedOverlays] iOS calendar sync failed:', error);
      }
    };

    // Log presence — tells Sara the app is open
    const logPresence = async (activityType: string) => {
      try {
        await apiClient.post('/api/presence', { activity_type: activityType, platform: 'ios' });
      } catch {}
    };

    // Heartbeat — reports current screen every 30s for smart delivery routing
    const clientId = `ios_${Math.random().toString(36).slice(2, 10)}`;
    let currentScreen = 'sara'; // default tab
    const sendHeartbeat = async () => {
      try {
        await apiClient.post('/api/presence/heartbeat', {
          platform: 'ios',
          client_id: clientId,
          current_view: currentScreen,
          visible: true,
        });
      } catch {}
    };
    sendHeartbeat();
    const heartbeatInterval = setInterval(sendHeartbeat, 30_000);

    // Sync the icon badge to the server's unread notification count, so the
    // number on the icon always matches the Notifications screen (and clears
    // once everything is read) instead of being wiped on every app open.
    const syncBadge = async () => {
      try {
        const data = await apiClient.get<{ unread: number }>('/api/notifications/unread-count');
        await pushNotificationService.setBadgeCount(data?.unread ?? 0);
      } catch {
        // Offline or endpoint unavailable — leave the badge as-is.
      }
    };

    // Check backend health on startup
    const checkHealth = async () => {
      try {
        const data = await apiClient.get('/health');
        if ((data as any)?.status === 'degraded') {
          console.log('[AuthenticatedOverlays] Backend health: degraded');
        }
      } catch {}
    };

    // Run all initializations
    initNotifications();
    initBackgroundHealthSync();
    syncHealth();
    syncIOSCalendar();
    logPresence('app_open');
    checkHealth();
    refreshWidgetData();

    // Siri "Ask Sara": consume any prompt stashed by the App Intent (cold start).
    consumeSiriPrompt();

    // Log presence on app resume + pause heartbeat when backgrounded
    const appStateSubscription = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (nextState === 'active') {
        logPresence('app_resume');
        sendHeartbeat();
        refreshWidgetData();
        // The App Intent foregrounds the app via openAppWhenRun → pick up the prompt.
        consumeSiriPrompt();
        // Sync badge to real unread count when app comes to foreground
        syncBadge();
      }
    });

    // Sync badge on initial open too
    syncBadge();

    // Re-sync when notifications get marked read in-app (Notifications screen
    // and inbox emit this after read/mark-all-read).
    const badgeRefreshSub = DeviceEventEmitter.addListener('assistantInboxBadgeRefresh', syncBadge);

    // Cleanup on unmount
    return () => {
      pushNotificationService.cleanup();
      appStateSubscription.remove();
      clearInterval(heartbeatInterval);
      badgeRefreshSub.remove();
    };
  }, [isAuthenticated]);

  // Don't render overlays if not authenticated
  if (!isAuthenticated) {
    return null;
  }

  return (
    <>
      <TimerOverlayContainer />
      <FloatingAssistant />
    </>
  );
};

export default AuthenticatedOverlays;

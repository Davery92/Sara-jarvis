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
import { isLocationTrackingEnabled, startTracking as startLocationTracking, resyncGeofences } from '../services/locationTracking';
import { iosCalendarSyncService } from '../services/iosCalendarSync';
import { navigateToChat, navigationRef, getCurrentViewName } from '../services/navigation';
import apiClient from '../services/api';
import { consumeSiriPrompt } from '../services/siriDeepLink';
import { refreshWidgetData } from '../services/widgetBridge';
import { watchWorkout } from '../services/watchWorkout';
import { workoutCoordinator } from '../services/workoutCoordinator';

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

    // Resume location tracking if the user previously enabled it
    const initLocationTracking = async () => {
      try {
        const enabled = await isLocationTrackingEnabled();
        if (enabled) {
          await startLocationTracking();
          console.log('[AuthenticatedOverlays] Location tracking resumed');
        }
      } catch (error) {
        console.log('[AuthenticatedOverlays] Failed to resume location tracking:', error);
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

    // Heartbeat — reports the REAL current screen (mapped to the web canonical
    // view vocabulary) every 30s + on view change, so Sara knows where David is.
    const clientId = `ios_${Math.random().toString(36).slice(2, 10)}`;
    let lastReportedView = getCurrentViewName();
    const sendHeartbeat = async (visibleOverride?: boolean) => {
      try {
        await apiClient.post('/api/presence/heartbeat', {
          platform: 'ios',
          client_id: clientId,
          current_view: getCurrentViewName(),
          visible: visibleOverride ?? (AppState.currentState === 'active'),
        });
      } catch {}
    };
    sendHeartbeat();
    const heartbeatInterval = setInterval(sendHeartbeat, 30_000);

    // Fire an immediate heartbeat when the active screen changes, so
    // app_current_view tracks within seconds rather than up to 30s late.
    const navStateSub = navigationRef.addListener('state', () => {
      const view = getCurrentViewName();
      if (view !== lastReportedView) {
        lastReportedView = view;
        sendHeartbeat();
      }
    });

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

    /**
     * Apple Watch workout mirror (plan §7.2, §9.2).
     *
     * Must run at authenticated startup, not when the Fitness screen mounts:
     * a workout David starts on his wrist arrives through a HealthKit handler
     * that fires whether or not any Sara screen is open. If nothing is
     * listening, the phone simply never learns a workout is underway — the
     * exact failure this feature exists to remove.
     *
     * Hydrating the coordinator first restores any commands queued before the
     * app was killed mid-workout, then flushes them; the backend replays
     * duplicates rather than logging a second set.
     */
    const initWatchWorkout = async () => {
      try {
        await workoutCoordinator.hydrate();
        watchWorkout.start();
        await workoutCoordinator.flush();
        await watchWorkout.syncCatalog();
      } catch (e) {
        // Never fatal: the phone workout must work with no Watch at all.
        console.log('[AuthenticatedOverlays] Watch workout init skipped:', e);
      }
    };

    // Run all initializations
    initNotifications();
    initWatchWorkout();
    initBackgroundHealthSync();
    initLocationTracking();
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
        sendHeartbeat(true);
        refreshWidgetData();
        // The App Intent foregrounds the app via openAppWhenRun → pick up the prompt.
        consumeSiriPrompt();
        // Sync badge to real unread count when app comes to foreground
        syncBadge();
        // Keep native geofence regions current with armed triggers/places
        resyncGeofences();
        // Reconcile the workout after time away — mirrored messages are the
        // primary transport, this is the fallback that catches what was
        // missed while backgrounded, and retries anything still queued (§4.4).
        void workoutCoordinator.sync().then(() => workoutCoordinator.flush());
        void watchWorkout.syncCatalog();
      } else if (nextState === 'background' || nextState === 'inactive') {
        // Final hidden heartbeat so the backend reaper ends the session
        // promptly instead of waiting a full TTL.
        sendHeartbeat(false);
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
      watchWorkout.stop();
      appStateSubscription.remove();
      clearInterval(heartbeatInterval);
      navStateSub();
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

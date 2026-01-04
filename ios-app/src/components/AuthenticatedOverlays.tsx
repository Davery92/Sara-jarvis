/**
 * AuthenticatedOverlays Component
 *
 * Container for overlay components that should only be visible when authenticated.
 * Includes TimerOverlayContainer and PushToTalkButton.
 * Also handles authenticated-only initialization like push notifications.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { useAuth } from '../context/AuthContext';
import TimerOverlayContainer from './TimerOverlayContainer';
import { PushToTalkButton } from './PushToTalkButton';
import { pushNotificationService } from '../services/pushNotifications';
import { healthSyncService } from '../services/healthSync';
import { registerBackgroundHealthSync, triggerManualSync } from '../services/backgroundHealthSync';
import { iosCalendarSyncService } from '../services/iosCalendarSync';
import { navigateToChat } from '../services/navigation';

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

          // Set up log meal action handler - navigate to fitness tab to log meal
          pushNotificationService.setOnLogMealAction(() => {
            console.log('[AuthenticatedOverlays] Log meal action tapped');
            // Navigate to fitness screen where user can log a meal
            navigateToChat({
              quickReply: { message: 'I want to log a meal' }
            });
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

    // Run all initializations
    initNotifications();
    initBackgroundHealthSync();
    syncHealth();
    syncIOSCalendar();

    // Cleanup on unmount
    return () => {
      pushNotificationService.cleanup();
    };
  }, [isAuthenticated]);

  // Don't render overlays if not authenticated
  if (!isAuthenticated) {
    return null;
  }

  return (
    <>
      <TimerOverlayContainer />
      <PushToTalkButton />
    </>
  );
};

export default AuthenticatedOverlays;

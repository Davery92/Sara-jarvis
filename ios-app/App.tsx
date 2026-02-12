import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from './src/context/AuthContext';
import { TimerProvider } from './src/context/TimerContext';
import { BackgroundTasksProvider } from './src/context/BackgroundTasksContext';
import { WorkoutModeProvider } from './src/context/WorkoutModeContext';
import { ToastProvider } from './src/context/ToastContext';
import RootNavigator from './src/navigation/RootNavigator';
import AuthenticatedOverlays from './src/components/AuthenticatedOverlays';
import ErrorBoundary from './src/components/ErrorBoundary';
import { SaraOverlayProvider } from './src/context/SaraOverlayContext';

/**
 * Main App Component
 *
 * Services that require authentication (push notifications, health sync, calendar sync)
 * are initialized in AuthenticatedOverlays after user login to avoid 401 errors.
 */
export default function App() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <ToastProvider>
          <AuthProvider>
            <TimerProvider>
              <BackgroundTasksProvider>
                <WorkoutModeProvider>
                  <SaraOverlayProvider>
                    <RootNavigator />
                    <AuthenticatedOverlays />
                    <StatusBar style="dark" />
                  </SaraOverlayProvider>
                </WorkoutModeProvider>
              </BackgroundTasksProvider>
            </TimerProvider>
          </AuthProvider>
        </ToastProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

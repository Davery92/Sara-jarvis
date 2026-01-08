import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from './src/context/AuthContext';
import { TimerProvider } from './src/context/TimerContext';
import { BackgroundTasksProvider } from './src/context/BackgroundTasksContext';
import { WorkoutModeProvider } from './src/context/WorkoutModeContext';
import RootNavigator from './src/navigation/RootNavigator';
import AuthenticatedOverlays from './src/components/AuthenticatedOverlays';

/**
 * Main App Component
 *
 * Services that require authentication (push notifications, health sync, calendar sync)
 * are initialized in AuthenticatedOverlays after user login to avoid 401 errors.
 */
export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <TimerProvider>
          <BackgroundTasksProvider>
            <WorkoutModeProvider>
              <RootNavigator />
              <AuthenticatedOverlays />
              <StatusBar style="dark" />
            </WorkoutModeProvider>
          </BackgroundTasksProvider>
        </TimerProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}

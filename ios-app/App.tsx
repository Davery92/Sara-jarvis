import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from './src/context/AuthContext';
import { TimerProvider } from './src/context/TimerContext';
import RootNavigator from './src/navigation/RootNavigator';
import TimerOverlayContainer from './src/components/TimerOverlayContainer';

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <TimerProvider>
          <RootNavigator />
          <TimerOverlayContainer />
          <StatusBar style="dark" />
        </TimerProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}

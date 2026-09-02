import React from 'react';
import { ActivityIndicator, View, StyleSheet, Platform } from 'react-native';
import { NavigationContainer, LinkingOptions } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import * as ExpoLinking from 'expo-linking';
import { useAuth } from '../context/AuthContext';
import AuthNavigator from './AuthNavigator';
import AppNavigator from './AppNavigator';
import RecoveryFormScreen from '../screens/fitness/RecoveryFormScreen';
import EventFormScreen from '../screens/calendar/EventFormScreen';
import ReminderFormScreen from '../screens/calendar/ReminderFormScreen';
import NoteEditorScreen from '../screens/notes/NoteEditorScreen';
import NutritionGoalsFormScreen from '../screens/fitness/NutritionGoalsFormScreen';
import PhaseFormScreen from '../screens/fitness/PhaseFormScreen';
import RecipeFormScreen from '../screens/recipes/RecipeFormScreen';
import WorkoutModeScreen from '../screens/fitness/WorkoutModeScreen';
import CardioScreen from '../screens/fitness/CardioScreen';
import TabataTimerScreen from '../screens/fitness/TabataTimerScreen';
import DailyPlanScreen from '../screens/sara/DailyPlanScreen';
import { RootStackParamList } from '../types/navigation';
import { colors } from '../styles/theme';
import { navigationRef, onNavigatorReady } from '../services/navigation';

const Stack = createNativeStackNavigator<RootStackParamList>();

const linking: LinkingOptions<RootStackParamList> = {
  prefixes: [ExpoLinking.createURL('/'), 'sara://'],
  config: {
    screens: {
      Main: {
        // Inbox is a stack screen in AppNavigator (not a tab in MainNavigator)
        screens: {
          Inbox: 'inbox/share',
        },
      },
    },
  },
};

export default function RootNavigator() {
  const { isAuthenticated, loading } = useAuth();

  console.log('[RootNavigator] isAuthenticated:', isAuthenticated, 'loading:', loading);

  if (loading) {
    console.log('[RootNavigator] Showing loading screen');
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  console.log('[RootNavigator] Rendering navigator, isAuthenticated:', isAuthenticated);

  return (
    <NavigationContainer ref={navigationRef} onReady={onNavigatorReady} linking={linking}>
      <Stack.Navigator>
        {isAuthenticated ? (
          <>
            <Stack.Screen name="Main" component={AppNavigator} options={{ headerShown: false }} />
            <Stack.Screen
              name="RecoveryForm"
              component={RecoveryFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="EventForm"
              component={EventFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="ReminderForm"
              component={ReminderFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="NoteEditor"
              component={NoteEditorScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="NutritionGoalsForm"
              component={NutritionGoalsFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="PhaseForm"
              component={PhaseFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="RecipeForm"
              component={RecipeFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
              }}
            />
            <Stack.Screen
              name="WorkoutMode"
              component={WorkoutModeScreen}
              options={{
                presentation: 'fullScreenModal',
                headerShown: false,
                gestureEnabled: false,  // Prevent accidental swipe-to-close
              }}
            />
            <Stack.Screen
              name="Cardio"
              component={CardioScreen}
              options={{ headerShown: false }}
            />
            <Stack.Screen
              name="TabataTimer"
              component={TabataTimerScreen}
              options={{
                presentation: 'fullScreenModal',
                headerShown: false,
                gestureEnabled: false,
              }}
            />
            <Stack.Screen
              name="DailyPlan"
              component={DailyPlanScreen}
              options={{
                title: "Sara's Focus",
                headerStyle: { backgroundColor: colors.background },
                headerTintColor: colors.text,
              }}
            />
          </>
        ) : (
          <Stack.Screen name="Auth" component={AuthNavigator} options={{ headerShown: false }} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
});

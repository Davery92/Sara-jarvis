import React from 'react';
import { ActivityIndicator, View, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuth } from '../context/AuthContext';
import AuthNavigator from './AuthNavigator';
import AppNavigator from './AppNavigator';
import RecoveryFormScreen from '../screens/fitness/RecoveryFormScreen';
import EventFormScreen from '../screens/calendar/EventFormScreen';
import ReminderFormScreen from '../screens/calendar/ReminderFormScreen';
import NoteEditorScreen from '../screens/notes/NoteEditorScreen';
import NutritionGoalsFormScreen from '../screens/fitness/NutritionGoalsFormScreen';
import RecipeFormScreen from '../screens/recipes/RecipeFormScreen';
import { RootStackParamList } from '../types/navigation';
import { colors } from '../styles/theme';

const Stack = createNativeStackNavigator<RootStackParamList>();

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
    <NavigationContainer>
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
              name="RecipeForm"
              component={RecipeFormScreen}
              options={{
                presentation: 'modal',
                headerShown: false,
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

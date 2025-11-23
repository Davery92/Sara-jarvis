import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import MainNavigator from './MainNavigator';
import RecipesScreen from '../screens/recipes/RecipesScreen';
import DocumentsScreen from '../screens/documents/DocumentsScreen';
import CalendarScreen from '../screens/calendar/CalendarScreen';
import BriefingsScreen from '../screens/briefings/BriefingsScreen';
import ContextModeScreen from '../screens/insights/ContextModeScreen';
import SmartInsightsScreen from '../screens/insights/SmartInsightsScreen';
import HealthDataScreen from '../screens/health/HealthDataScreen';
import SettingsScreen from '../screens/settings/SettingsScreen';
import { colors, fontSizes } from '../styles/theme';

export type AppStackParamList = {
  MainTabs: undefined;
  Recipes: undefined;
  Documents: undefined;
  Calendar: undefined;
  Briefings: undefined;
  ContextMode: undefined;
  SmartInsights: undefined;
  Health: undefined;
  Settings: undefined;
};

const Stack = createNativeStackNavigator<AppStackParamList>();

export default function AppNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: {
          backgroundColor: colors.surface,
        },
        headerTintColor: colors.text,
        headerTitleStyle: {
          fontWeight: '600',
          fontSize: fontSizes.lg,
        },
      }}
    >
      <Stack.Screen
        name="MainTabs"
        component={MainNavigator}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Recipes"
        component={RecipesScreen}
        options={{ title: 'Recipes' }}
      />
      <Stack.Screen
        name="Documents"
        component={DocumentsScreen}
        options={{ title: 'Documents' }}
      />
      <Stack.Screen
        name="Calendar"
        component={CalendarScreen}
        options={{ title: 'Calendar' }}
      />
      <Stack.Screen
        name="Briefings"
        component={BriefingsScreen}
        options={{ title: 'Daily Briefings' }}
      />
      <Stack.Screen
        name="ContextMode"
        component={ContextModeScreen}
        options={{ title: 'Context Mode' }}
      />
      <Stack.Screen
        name="SmartInsights"
        component={SmartInsightsScreen}
        options={{ title: 'Smart Insights' }}
      />
      <Stack.Screen
        name="Health"
        component={HealthDataScreen}
        options={{ title: 'Apple Health' }}
      />
      <Stack.Screen
        name="Settings"
        component={SettingsScreen}
        options={{ title: 'Settings' }}
      />
    </Stack.Navigator>
  );
}

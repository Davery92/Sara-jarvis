import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import MainNavigator from './MainNavigator';
import RecipesScreen from '../screens/recipes/RecipesScreen';
import DocumentsScreen from '../screens/documents/DocumentsScreen';
import CalendarScreen from '../screens/calendar/CalendarScreen';
import BriefingsScreen from '../screens/briefings/BriefingsScreen';
import HealthDataScreen from '../screens/health/HealthDataScreen';
import SettingsScreen from '../screens/settings/SettingsScreen';
import ProjectsScreen from '../screens/projects/ProjectsScreen';
import InboxScreen from '../screens/inbox/InboxScreen';
import SaraActivityScreen from '../screens/sara/SaraActivityScreen';
import KnowledgeScreen from '../screens/knowledge/KnowledgeScreen';
import IntelligenceScreen from '../screens/intelligence/IntelligenceScreen';
import NotesListScreen from '../screens/notes/NotesListScreen';
import AgentTasksScreen from '../screens/agents/AgentTasksScreen';
import TemerantScreen from '../screens/temerant/TemerantScreen';
import TemerantRpgScreen from '../screens/temerant/TemerantRpgScreen';
import { colors, fontSizes } from '../styles/theme';

export type AppStackParamList = {
  MainTabs: undefined;
  Notes: undefined;
  Recipes: undefined;
  Documents: undefined;
  Calendar: undefined;
  Briefings: undefined;
  Health: undefined;
  Settings: undefined;
  Projects: undefined;
  Inbox: undefined;
  SaraActivity: undefined;
  Knowledge: undefined;
  Intelligence: undefined;
  AgentTasks: undefined;
  Temerant: undefined;
  TemerantRpg: undefined;
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
        name="Notes"
        component={NotesListScreen}
        options={{ title: 'Notes' }}
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
        options={{ title: 'Morning Brief' }}
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
      <Stack.Screen
        name="Projects"
        component={ProjectsScreen}
        options={{ title: 'Projects' }}
      />
      <Stack.Screen
        name="Inbox"
        component={InboxScreen}
        options={{ title: 'Inbox' }}
      />
      <Stack.Screen
        name="SaraActivity"
        component={SaraActivityScreen}
        options={{ title: "Sara's Mind" }}
      />
      <Stack.Screen
        name="Knowledge"
        component={KnowledgeScreen}
        options={{ title: 'Knowledge' }}
      />
      <Stack.Screen
        name="Intelligence"
        component={IntelligenceScreen}
        options={{ title: 'Intelligence Feed' }}
      />
      <Stack.Screen
        name="AgentTasks"
        component={AgentTasksScreen}
        options={{ title: 'Agent Tasks' }}
      />
      <Stack.Screen
        name="Temerant"
        component={TemerantScreen}
        options={{ title: 'Temerant' }}
      />
      <Stack.Screen
        name="TemerantRpg"
        component={TemerantRpgScreen}
        options={{ title: 'Temerant RPG' }}
      />
    </Stack.Navigator>
  );
}

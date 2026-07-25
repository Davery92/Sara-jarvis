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
import AssistantAnalyticsScreen from '../screens/analytics/AssistantAnalyticsScreen';
import AssistantInboxScreen from '../screens/inbox/AssistantInboxScreen';
import InboxScreen from '../screens/inbox/InboxScreen';
import KnowledgeScreen from '../screens/knowledge/KnowledgeScreen';
import NotesListScreen from '../screens/notes/NotesListScreen';
import AgentTasksScreen from '../screens/agents/AgentTasksScreen';
import DailyTasksScreen from '../screens/tasks/DailyTasksScreen';
import AutomationsScreen from '../screens/automations/AutomationsScreen';
import EmailListScreen from '../screens/email/EmailListScreen';
import EmailDetailScreen from '../screens/email/EmailDetailScreen';
import LearningScreen from '../screens/learning/LearningScreen';
import NotificationsScreen from '../screens/notifications/NotificationsScreen';
import ACSScreen from '../screens/acs/ACSScreen';
import InteriorScreen from '../screens/interior/InteriorScreen';
import FitnessScreen from '../screens/fitness/FitnessScreen';
import LifeScreen from '../screens/life/LifeScreen';
import SystemScreen from '../screens/system/SystemScreen';
import MachinesScreen from '../screens/machines/MachinesScreen';
import StudioScreen from '../screens/studio/StudioScreen';
import ChatScreen from '../screens/chat/ChatScreen';
import { ChatScreenParams } from '../types/navigation';
import { colors, fontSizes } from '../styles/theme';

export type AppStackParamList = {
  MainTabs: undefined;
  Notes: undefined;
  Recipes: undefined;
  Documents: undefined;
  Studio: { id?: string } | undefined;
  Calendar: undefined;
  Briefings: undefined;
  Health: undefined;
  Settings: undefined;
  Projects: undefined;
  Chat: ChatScreenParams | undefined;
  AssistantAnalytics: undefined;
  AssistantInbox: { focus?: 'all' | 'waiting' | 'in_progress' | 'new' | 'done' | 'archived' } | undefined;
  Inbox: { tab?: 'content' | 'attention' } | undefined;
  Knowledge: undefined;
  AgentTasks: undefined;
  DailyTasks: undefined;
  Automations: undefined;
  Email: undefined;
  EmailDetail: { emailId: string };
  Learning: undefined;
  Notifications: { notificationId?: number } | undefined;
  ACS: undefined;
  System: undefined;
  Machines: undefined;
  Interior: undefined;
  Fitness: undefined;
  Life: undefined;
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
        name="System"
        component={SystemScreen}
        options={{ title: 'The System' }}
      />
      <Stack.Screen
        name="Machines"
        component={MachinesScreen}
        options={{ title: 'Machines' }}
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
        name="Studio"
        component={StudioScreen}
        options={{ title: 'Studio' }}
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
        name="Chat"
        component={ChatScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="AssistantAnalytics"
        component={AssistantAnalyticsScreen}
        options={{ title: 'Assistant Usage' }}
      />
      <Stack.Screen
        name="AssistantInbox"
        component={AssistantInboxScreen}
        options={{ title: 'Inbox' }}
      />
      <Stack.Screen
        name="Inbox"
        component={InboxScreen}
        options={{ title: 'Captured Content' }}
      />
      <Stack.Screen
        name="Knowledge"
        component={KnowledgeScreen}
        options={{ title: 'Knowledge' }}
      />
      <Stack.Screen
        name="AgentTasks"
        component={AgentTasksScreen}
        options={{ title: 'Agent Tasks' }}
      />
      <Stack.Screen
        name="DailyTasks"
        component={DailyTasksScreen}
        options={{ title: 'Daily Tasks' }}
      />
      <Stack.Screen
        name="Automations"
        component={AutomationsScreen}
        options={{ title: 'Automations' }}
      />
      <Stack.Screen
        name="Email"
        component={EmailListScreen}
        options={{ title: 'Email' }}
      />
      <Stack.Screen
        name="EmailDetail"
        component={EmailDetailScreen}
        options={{ title: 'Email' }}
      />
      <Stack.Screen
        name="Learning"
        component={LearningScreen}
        options={{ title: 'Learning' }}
      />
      <Stack.Screen
        name="Notifications"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
      <Stack.Screen
        name="ACS"
        component={ACSScreen}
        options={{ title: 'Autonomous Cognition' }}
      />
      <Stack.Screen
        name="Interior"
        component={InteriorScreen}
        options={{ title: 'Interior' }}
      />
      <Stack.Screen
        name="Fitness"
        component={FitnessScreen}
        options={{ title: 'Fitness' }}
      />
      <Stack.Screen
        name="Life"
        component={LifeScreen}
        options={{ title: 'Life' }}
      />
    </Stack.Navigator>
  );
}

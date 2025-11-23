import React from 'react';
import { Text } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import HomeScreen from '../screens/home/HomeScreen';
import ChatScreen from '../screens/chat/ChatScreen';
import NotesListScreen from '../screens/notes/NotesListScreen';
import FitnessScreen from '../screens/fitness/FitnessScreen';
import RecipesScreen from '../screens/recipes/RecipesScreen';
import DocumentsScreen from '../screens/documents/DocumentsScreen';
import CalendarScreen from '../screens/calendar/CalendarScreen';
import SettingsScreen from '../screens/settings/SettingsScreen';
import BriefingsScreen from '../screens/briefings/BriefingsScreen';
import ContextModeScreen from '../screens/insights/ContextModeScreen';
import SmartInsightsScreen from '../screens/insights/SmartInsightsScreen';
import HealthDataScreen from '../screens/health/HealthDataScreen';
import MoreScreen from '../screens/more/MoreScreen';
import CustomTabBar from '../components/CustomTabBar';
import { MainTabParamList } from '../types/navigation';
import { colors, fontSizes } from '../styles/theme';

const Tab = createBottomTabNavigator<MainTabParamList>();

export default function MainNavigator() {
  return (
    <Tab.Navigator
      tabBar={(props) => <CustomTabBar {...props} />}
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
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{
          title: 'Home',
          tabBarLabel: 'Home',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="🏠" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Chat"
        component={ChatScreen}
        options={{
          title: 'Chat with Sara',
          tabBarLabel: 'Chat',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="💬" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Notes"
        component={NotesListScreen}
        options={{
          title: 'Notes',
          tabBarLabel: 'Notes',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="📝" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Fitness"
        component={FitnessScreen}
        options={{
          title: 'Fitness',
          tabBarLabel: 'Fitness',
          tabBarIcon: ({ color, size}) => (
            <TabBarIcon name="💪" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="More"
        component={MoreScreen}
        options={{
          title: 'More',
          tabBarLabel: 'More',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="⋯" color={color} size={size} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

// Simple emoji icon component
function TabBarIcon({ name, color, size }: { name: string; color: string; size: number }) {
  const isActive = color === colors.primary;
  return (
    <Text style={{
      fontSize: 36,
      opacity: isActive ? 1 : 0.5,
      textAlign: 'center',
      lineHeight: 40,
    }}>
      {name}
    </Text>
  );
}

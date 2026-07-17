import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import SaraScreen from '../screens/sara/SaraScreen';
import AssistantInboxScreen from '../screens/inbox/AssistantInboxScreen';
import FitnessScreen from '../screens/fitness/FitnessScreen';
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
        name="Sara"
        component={SaraScreen}
        options={{
          title: 'Sara',
          headerShown: false,
          tabBarLabel: 'Sara',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="sparkles" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="AssistantInboxTab"
        component={AssistantInboxScreen}
        options={{
          title: 'Inbox',
          headerShown: false,
          tabBarLabel: 'Inbox',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="file-tray-full-outline" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Fitness"
        component={FitnessScreen}
        options={{
          title: 'Fitness',
          tabBarLabel: 'Fitness',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="barbell-outline" color={color} size={size} />
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
            <TabBarIcon name="grid-outline" color={color} size={size} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

function TabBarIcon({
  name,
  color,
  size,
}: {
  name: React.ComponentProps<typeof Ionicons>['name'];
  color: string;
  size: number;
}) {
  return (
    <Ionicons name={name} color={color} size={size} />
  );
}

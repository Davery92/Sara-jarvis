import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import SaraScreen from '../screens/sara/SaraScreen';
import AssistantInboxScreen from '../screens/inbox/AssistantInboxScreen';
import ChatScreen from '../screens/chat/ChatScreen';
import LifeScreen from '../screens/life/LifeScreen';
import MoreScreen from '../screens/more/MoreScreen';
import CustomTabBar from '../components/CustomTabBar';
import { MainTabParamList } from '../types/navigation';
import { colors, fontSizes } from '../styles/theme';

const Tab = createBottomTabNavigator<MainTabParamList>();

// SINGULAR_SARA_MASTER_PLAN §U8 recommended iOS tabs: Sara, Today, Chat,
// Life, More. `AssistantInboxTab`/`Fitness` route keys are unchanged from
// before this pass (existing navigate() call sites keep working) — only
// the tab bar's composition and labels changed: Fitness folded into Life
// (still reachable from there, and from the app stack directly via
// navigation.navigate('Fitness')), Chat promoted from a stack-only screen
// to a persistent tab, Inbox relabeled "Today".
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
          title: 'Today',
          headerShown: false,
          tabBarLabel: 'Today',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="file-tray-full-outline" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Chat"
        component={ChatScreen}
        options={{
          title: 'Chat',
          headerShown: false,
          tabBarLabel: 'Chat',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="chatbubble-ellipses-outline" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Life"
        component={LifeScreen}
        options={{
          title: 'Life',
          headerShown: false,
          tabBarLabel: 'Life',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="heart-outline" color={color} size={size} />
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

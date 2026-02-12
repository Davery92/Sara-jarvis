import React from 'react';
import { Text } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import SaraScreen from '../screens/sara/SaraScreen';
import FitnessScreen from '../screens/fitness/FitnessScreen';
import LearningScreen from '../screens/learning/LearningScreen';
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
            <TabBarIcon name="✨" color={color} size={size} />
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
            <TabBarIcon name="💪" color={color} size={size} />
          ),
        }}
      />
      <Tab.Screen
        name="Learning"
        component={LearningScreen}
        options={{
          title: 'Learning',
          tabBarLabel: 'Learn',
          tabBarIcon: ({ color, size }) => (
            <TabBarIcon name="📚" color={color} size={size} />
          ),
          headerShown: false,
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

import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { colors, fontSizes } from '../../styles/theme';

interface MenuItem {
  name: string;
  icon: string;
  label: string;
  screen: string;
}

const menuItems: MenuItem[] = [
  { name: 'Recipes', icon: '🍳', label: 'Recipes', screen: 'Recipes' },
  { name: 'Documents', icon: '📄', label: 'Documents', screen: 'Documents' },
  { name: 'Calendar', icon: '📅', label: 'Calendar', screen: 'Calendar' },
  { name: 'Briefings', icon: '📋', label: 'Daily Briefings', screen: 'Briefings' },
  { name: 'ContextMode', icon: '🎛️', label: 'Context Mode', screen: 'ContextMode' },
  { name: 'SmartInsights', icon: '✨', label: 'Smart Insights', screen: 'SmartInsights' },
  { name: 'Health', icon: '⚕️', label: 'Apple Health', screen: 'Health' },
  { name: 'Settings', icon: '⚙️', label: 'Settings', screen: 'Settings' },
];

export default function MoreScreen() {
  const navigation = useNavigation();

  const handleItemPress = (screen: string) => {
    (navigation as any).navigate(screen);
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>More</Text>
      <View style={styles.menuGrid}>
        {menuItems.map((item) => (
          <TouchableOpacity
            key={item.name}
            style={styles.menuItem}
            onPress={() => handleItemPress(item.screen)}
          >
            <Text style={styles.menuIcon}>{item.icon}</Text>
            <Text style={styles.menuLabel}>{item.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    padding: 20,
  },
  title: {
    fontSize: fontSizes.xxl,
    fontWeight: 'bold',
    color: colors.text,
    marginBottom: 24,
  },
  menuGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
  },
  menuItem: {
    width: '47%',
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 20,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  menuIcon: {
    fontSize: 40,
    marginBottom: 8,
  },
  menuLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
    fontWeight: '500',
  },
});

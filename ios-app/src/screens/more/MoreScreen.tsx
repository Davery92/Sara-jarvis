import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useFocusEffect } from '@react-navigation/native';
import apiClient from '../../services/api';
import { colors, fontSizes } from '../../styles/theme';

interface MenuItem {
  name: string;
  icon: string;
  label: string;
  screen: string;
}

const menuItems: MenuItem[] = [
  { name: 'Notes', icon: '📝', label: 'Notes', screen: 'Notes' },
  { name: 'Calendar', icon: '📅', label: 'Calendar', screen: 'Calendar' },
  { name: 'Inbox', icon: '📥', label: 'Inbox', screen: 'Inbox' },
  { name: 'AgentTasks', icon: '🤖', label: 'Agent Tasks', screen: 'AgentTasks' },
  { name: 'SaraActivity', icon: '🧠', label: "Sara's Mind", screen: 'SaraActivity' },
  { name: 'Knowledge', icon: '🧬', label: 'Knowledge', screen: 'Knowledge' },
  { name: 'Documents', icon: '📄', label: 'Documents', screen: 'Documents' },
  { name: 'Projects', icon: '📋', label: 'Projects', screen: 'Projects' },
  { name: 'Recipes', icon: '🍳', label: 'Recipes', screen: 'Recipes' },
  { name: 'Intelligence', icon: '📡', label: 'Intelligence', screen: 'Intelligence' },
  { name: 'Temerant', icon: '🗝️', label: 'Temerant', screen: 'Temerant' },
  { name: 'TemerantRpg', icon: '🎭', label: 'Temerant RPG', screen: 'TemerantRpg' },
  { name: 'Briefings', icon: '☀️', label: 'Morning Brief', screen: 'Briefings' },
  { name: 'Health', icon: '⚕️', label: 'Apple Health', screen: 'Health' },
  { name: 'Settings', icon: '⚙️', label: 'Settings', screen: 'Settings' },
];

export default function MoreScreen() {
  const navigation = useNavigation();
  const [inboxUnread, setInboxUnread] = useState(0);
  const [temerantEnabled, setTemerantEnabled] = useState(true);
  const [temerantRpgEnabled, setTemerantRpgEnabled] = useState(true);

  useFocusEffect(
    React.useCallback(() => {
      const loadBadges = async () => {
        try {
          const stats = await apiClient.getInboxStats();
          setInboxUnread(stats?.unread || 0);
        } catch {}
      };
      loadBadges();
    }, [])
  );

  useEffect(() => {
    const loadFlags = async () => {
      try {
        const flags = await apiClient.getAutonomyFlags();
        if (typeof flags?.temerant_enabled === 'boolean') {
          setTemerantEnabled(flags.temerant_enabled);
        }
        if (typeof flags?.temerant_rpg_enabled === 'boolean') {
          setTemerantRpgEnabled(flags.temerant_rpg_enabled);
        }
      } catch {
        // Keep default if flags endpoint is unavailable.
      }
    };
    loadFlags();
  }, []);

  const handleItemPress = (screen: string) => {
    (navigation as any).navigate(screen);
  };

  const visibleMenuItems = menuItems.filter((item) => {
    if (item.name === 'Temerant' && !temerantEnabled) return false;
    if (item.name === 'TemerantRpg' && !temerantRpgEnabled) return false;
    return true;
  });

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>More</Text>
      <View style={styles.menuGrid}>
        {visibleMenuItems.map((item) => (
          <TouchableOpacity
            key={item.name}
            style={styles.menuItem}
            onPress={() => handleItemPress(item.screen)}
          >
            <View>
              <Text style={styles.menuIcon}>{item.icon}</Text>
              {item.name === 'Inbox' && inboxUnread > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{inboxUnread}</Text>
                </View>
              )}
            </View>
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
  badge: {
    position: 'absolute',
    top: -4,
    right: -8,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.error,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
});

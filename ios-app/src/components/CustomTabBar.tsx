import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { colors } from '../styles/theme';
import apiClient from '../services/api';

// Hook to poll for badge data
function useSaraBadges() {
  const [chatBadge, setChatBadge] = useState(false);
  const [moreBadge, setMoreBadge] = useState(0);

  const fetchBadges = useCallback(async () => {
    try {
      const [statusData, inboxData] = await Promise.allSettled([
        apiClient.get('/api/sara/status'),
        apiClient.getInboxStats(),
      ]);

      if (statusData.status === 'fulfilled') {
        const status = statusData.value as any;
        setChatBadge((status?.pending_observations || 0) > 0);
      }
      if (inboxData.status === 'fulfilled') {
        const inbox = inboxData.value as any;
        setMoreBadge(inbox?.unread || 0);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchBadges();
    const interval = setInterval(fetchBadges, 60000);
    return () => clearInterval(interval);
  }, [fetchBadges]);

  return { chatBadge, moreBadge };
}

export default function CustomTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const { chatBadge, moreBadge } = useSaraBadges();

  return (
    <View style={styles.tabBar}>
      {state.routes.map((route, index) => {
        const { options } = descriptors[route.key];
        const rawLabel = options.tabBarLabel ?? options.title ?? route.name;
        const label = typeof rawLabel === 'string' ? rawLabel : route.name;
        const isFocused = state.index === index;

        const icon = options.tabBarIcon
          ? options.tabBarIcon({
              focused: isFocused,
              color: isFocused ? colors.primary : colors.textMuted,
              size: 28,
            })
          : null;

        // Determine badge for this tab
        const showDot = route.name === 'Sara' && chatBadge;
        const badgeCount = route.name === 'More' ? moreBadge : 0;

        const onPress = () => {
          const event = navigation.emit({
            type: 'tabPress',
            target: route.key,
            canPreventDefault: true,
          });

          if (!isFocused && !event.defaultPrevented) {
            navigation.navigate(route.name);
          }
        };

        return (
          <TouchableOpacity
            key={route.key}
            accessibilityRole="button"
            accessibilityState={isFocused ? { selected: true } : {}}
            accessibilityLabel={options.tabBarAccessibilityLabel}
            testID={options.tabBarTestID}
            onPress={onPress}
            style={styles.tabItem}
          >
            <View style={styles.iconContainer}>
              {icon}
              {showDot && <View style={styles.badgeDot} />}
              {badgeCount > 0 && (
                <View style={styles.badgeCount}>
                  <Text style={styles.badgeCountText}>
                    {badgeCount > 99 ? '99+' : badgeCount}
                  </Text>
                </View>
              )}
            </View>
            <Text
              style={[
                styles.label,
                { color: isFocused ? colors.primary : colors.textMuted },
              ]}
            >
              {label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    height: 85,
    paddingBottom: 8,
    paddingTop: 8,
    paddingHorizontal: 8,
  },
  tabItem: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 4,
  },
  iconContainer: {
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 2,
  },
  label: {
    fontSize: 12,
    fontWeight: '600',
    textAlign: 'center',
  },
  badgeDot: {
    position: 'absolute',
    top: 4,
    right: -2,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.error,
  },
  badgeCount: {
    position: 'absolute',
    top: 0,
    right: -8,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.error,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 3,
  },
  badgeCountText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '700',
  },
});

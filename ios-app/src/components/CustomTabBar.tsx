import React, { useState, useEffect, useCallback, useRef } from 'react';
import { AppState, DeviceEventEmitter } from 'react-native';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../styles/theme';
import apiClient from '../services/api';

// Hook to poll for badge data
function useSaraBadges() {
  const [chatBadge, setChatBadge] = useState(false);
  const [assistantInboxBadge, setAssistantInboxBadge] = useState(0);
  const appStateRef = useRef(AppState.currentState);

  const fetchBadges = useCallback(async () => {
    try {
      const [statusData, badgeData] = await Promise.allSettled([
        apiClient.get('/api/sara/status'),
        // Shared server-side formula — same number as the app icon badge and
        // the inbox screen counts.
        apiClient.getInboxBadge(),
      ]);

      if (statusData.status === 'fulfilled') {
        const status = statusData.value as any;
        setChatBadge((status?.pending_observations || 0) > 0);
      }
      if (badgeData.status === 'fulfilled') {
        setAssistantInboxBadge(badgeData.value || 0);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchBadges();
    const interval = setInterval(fetchBadges, 15000);
    const badgeRefreshSubscription = DeviceEventEmitter.addListener(
      'assistantInboxBadgeRefresh',
      fetchBadges,
    );
    const appStateSubscription = AppState.addEventListener('change', (nextState) => {
      const wasBackgrounded = appStateRef.current.match(/inactive|background/);
      appStateRef.current = nextState;

      if (wasBackgrounded && nextState === 'active') {
        fetchBadges();
      }
    });

    return () => {
      clearInterval(interval);
      badgeRefreshSubscription.remove();
      appStateSubscription.remove();
    };
  }, [fetchBadges]);

  return { chatBadge, assistantInboxBadge };
}

export default function CustomTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const { chatBadge, assistantInboxBadge } = useSaraBadges();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.tabBarContainer,
        { paddingBottom: Math.max(insets.bottom, spacing.sm) },
      ]}
    >
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
                size: 24,
              })
            : null;

          // Determine badge for this tab
          const showDot = route.name === 'Sara' && chatBadge;
          const badgeCount = route.name === 'AssistantInboxTab' ? assistantInboxBadge : 0;

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
              style={[styles.tabItem, isFocused && styles.tabItemActive]}
            >
              <View style={[styles.iconContainer, isFocused && styles.iconContainerActive]}>
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
                  { color: isFocused ? colors.text : colors.textMuted },
                ]}
              >
                {label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  tabBarContainer: {
    backgroundColor: colors.background,
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.xs,
  },
  tabBar: {
    flexDirection: 'row',
    backgroundColor: colors.assistant.panel,
    borderTopWidth: 1,
    borderTopColor: colors.assistant.border,
    borderRadius: borderRadius.xl,
    minHeight: 72,
    paddingBottom: spacing.xs,
    paddingTop: spacing.sm,
    paddingHorizontal: spacing.sm,
    ...shadows.sm,
  },
  tabItem: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    marginHorizontal: spacing.xs,
    borderRadius: borderRadius.lg,
  },
  tabItemActive: {
    backgroundColor: colors.assistant.actionSoft,
  },
  iconContainer: {
    width: 36,
    height: 30,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.xs,
    borderRadius: borderRadius.full,
  },
  iconContainerActive: {
    backgroundColor: colors.assistant.panelRaised,
  },
  label: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textAlign: 'center',
  },
  badgeDot: {
    position: 'absolute',
    top: 0,
    right: -4,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.assistant.alert,
  },
  badgeCount: {
    position: 'absolute',
    top: -2,
    right: -10,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.assistant.alert,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  badgeCountText: {
    color: colors.text,
    fontSize: 10,
    fontWeight: '700',
  },
});

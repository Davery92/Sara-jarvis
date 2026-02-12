import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Animated } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ToolStatusIndicatorProps {
  toolName: string;
  status: 'executing' | 'completed';
}

const TOOL_DESCRIPTIONS: Record<string, string> = {
  search_notes: 'Searching your notes...',
  list_notes: 'Searching your notes...',
  calendar_list: 'Checking your calendar...',
  list_events: 'Checking your calendar...',
  log_food: 'Logging food...',
  start_timer: 'Starting timer...',
  search_memory: 'Searching memories...',
  web_search: 'Looking this up...',
  open_page: 'Looking this up...',
  handoff_to_agents: 'Handing off to agents...',
};

const TOOL_PREFIXES: [string, string][] = [
  ['food_log_', 'Logging food...'],
  ['email_', 'Checking your email...'],
  ['search_email', 'Checking your email...'],
  ['home_', 'Controlling your home...'],
  ['get_home_', 'Controlling your home...'],
  ['health_', 'Analyzing health data...'],
];

function getToolDescription(toolName: string): string {
  if (TOOL_DESCRIPTIONS[toolName]) {
    return TOOL_DESCRIPTIONS[toolName];
  }
  for (const [prefix, description] of TOOL_PREFIXES) {
    if (toolName.startsWith(prefix)) {
      return description;
    }
  }
  return 'Working on it...';
}

export default function ToolStatusIndicator({ toolName, status }: ToolStatusIndicatorProps) {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const [visible, setVisible] = useState(true);
  const description = getToolDescription(toolName);

  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: 1,
      duration: 200,
      useNativeDriver: true,
    }).start();
  }, []);

  useEffect(() => {
    if (status === 'completed') {
      const hideTimer = setTimeout(() => {
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 300,
          useNativeDriver: true,
        }).start(() => {
          setVisible(false);
        });
      }, 800);
      return () => clearTimeout(hideTimer);
    }
  }, [status]);

  if (!visible) {
    return null;
  }

  return (
    <Animated.View style={[styles.container, { opacity: fadeAnim }]}>
      <View style={styles.content}>
        {status === 'executing' ? (
          <ActivityIndicator size="small" color={colors.primary} style={styles.indicator} />
        ) : (
          <Text style={styles.checkmark}>{'✓'}</Text>
        )}
        <Text style={styles.description}>{description}</Text>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    alignSelf: 'flex-start',
  },
  indicator: {
    marginRight: spacing.sm,
  },
  checkmark: {
    color: colors.success,
    fontSize: fontSizes.sm,
    fontWeight: '700',
    marginRight: spacing.sm,
  },
  description: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

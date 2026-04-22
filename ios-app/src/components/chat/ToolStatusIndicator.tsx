import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
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

function getToolHint(toolName: string): string {
  if (toolName.startsWith('search_') || toolName.startsWith('web_') || toolName === 'open_page') {
    return 'Gathering context before replying.';
  }
  if (toolName.startsWith('calendar_') || toolName.startsWith('list_events')) {
    return 'Checking timing and details for you.';
  }
  if (toolName.startsWith('log_') || toolName.startsWith('food_log_')) {
    return 'Updating the right place in the background.';
  }
  return 'You can keep typing while this finishes.';
}

export default function ToolStatusIndicator({ toolName, status }: ToolStatusIndicatorProps) {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const [visible, setVisible] = useState(true);
  const description = getToolDescription(toolName);
  const hint = getToolHint(toolName);

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
        <View style={styles.badge}>
          {status === 'executing' ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Ionicons name="checkmark" size={14} color={colors.success} />
          )}
        </View>
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>
            {status === 'executing' ? 'Sara is working' : 'Done'}
          </Text>
          <Text style={styles.description}>{description}</Text>
          <Text style={styles.hint}>
            {status === 'executing' ? hint : 'The result is ready to use in the conversation.'}
          </Text>
        </View>
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
    alignItems: 'flex-start',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    alignSelf: 'stretch',
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  badge: {
    width: 28,
    height: 28,
    borderRadius: borderRadius.full,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 2,
  },
  copy: {
    flex: 1,
  },
  eyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: 2,
  },
  description: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: 2,
  },
  hint: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 17,
  },
});

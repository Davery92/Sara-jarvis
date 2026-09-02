import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, Animated, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { AssistantActivity } from '../../types/cards';
import { colors, fontSizes, spacing } from '../../styles/theme';

type Props = {
  activity: AssistantActivity;
};

const TOOL_LABELS: Record<string, string> = {
  web_search: 'Searching the web',
  open_page: 'Reading a web page',
  get_page_details: 'Reading web results',
  get_web_search_details: 'Reading web results',
  notes_search: 'Searching your notes',
  notes_list: 'Checking your notes',
  notes_list_folders: 'Checking your note folders',
  documents_search: 'Searching your documents',
  memory_search: 'Searching your memories',
  calendar_list: 'Checking your calendar',
  dispatch_and_monitor: 'Starting durable background work',
  dispatch_agent_task: 'Starting background work',
  create_research_plan: 'Starting a background research plan',
};

const TOOL_PREFIXES: Array<[string, string]> = [
  ['calendar_', 'Working with your calendar'],
  ['email_', 'Checking your email'],
  ['food_', 'Working with your food log'],
  ['fitness_', 'Checking your fitness data'],
  ['workout_', 'Working with your workouts'],
  ['recovery_', 'Checking your recovery'],
  ['phase_', 'Checking your training phase'],
  ['program_', 'Working with your training program'],
  ['template_', 'Working with your workout templates'],
  ['home_', 'Working with your home'],
  ['notes_', 'Working with your notes'],
  ['memory_', 'Checking your memories'],
];

function toolLabel(tool?: string): string {
  if (!tool) return 'Using a tool';
  if (TOOL_LABELS[tool]) return TOOL_LABELS[tool];
  const prefix = TOOL_PREFIXES.find(([value]) => tool.startsWith(value));
  if (prefix) return prefix[1];
  return tool
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function activityLabel(activity: AssistantActivity): string {
  switch (activity.phase) {
    case 'tool_running':
      return toolLabel(activity.tool);
    case 'tool_complete':
      return `Finished: ${toolLabel(activity.tool)}`;
    case 'synthesizing':
      return 'Putting the results together';
    case 'responding':
      return 'Writing the response';
    case 'thinking':
    default:
      return 'Thinking through your request';
  }
}

export default function AssistantActivityIndicator({ activity }: Props) {
  const opacity = useRef(new Animated.Value(0)).current;
  const complete = activity.phase === 'tool_complete';

  useEffect(() => {
    opacity.setValue(0);
    Animated.timing(opacity, {
      toValue: 1,
      duration: 160,
      useNativeDriver: true,
    }).start();
  }, [activity.phase, activity.tool, opacity]);

  return (
    <Animated.View
      style={[styles.container, { opacity }]}
      accessibilityRole="text"
      accessibilityLabel={`Sara is ${activityLabel(activity)}`}
    >
      <View style={styles.icon}>
        {complete ? (
          <Ionicons name="checkmark" size={13} color={colors.success} />
        ) : (
          <ActivityIndicator size="small" color={colors.primary} />
        )}
      </View>
      <Text style={styles.label}>{activityLabel(activity)}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    gap: spacing.xs,
  },
  icon: {
    width: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
});

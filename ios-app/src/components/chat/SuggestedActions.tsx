import React, { useEffect, useRef } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, Animated } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

export interface SuggestedAction {
  label: string;
  message?: string;
  action?: string;
  target?: string;
  icon?: string;
}

interface SuggestedActionsProps {
  actions: SuggestedAction[];
  onAction: (action: SuggestedAction) => void;
}

const MAX_DISPLAYED = 4;

function AnimatedChip({
  action,
  onPress,
  index,
}: {
  action: SuggestedAction;
  onPress: () => void;
  index: number;
}) {
  const translateX = useRef(new Animated.Value(40)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const delay = index * 50;
    Animated.parallel([
      Animated.timing(translateX, {
        toValue: 0,
        duration: 250,
        delay,
        useNativeDriver: true,
      }),
      Animated.timing(opacity, {
        toValue: 1,
        duration: 250,
        delay,
        useNativeDriver: true,
      }),
    ]).start();
  }, []);

  return (
    <Animated.View style={{ transform: [{ translateX }], opacity }}>
      <TouchableOpacity
        style={styles.chip}
        onPress={onPress}
        activeOpacity={0.7}
      >
        {action.icon && <Text style={styles.chipIcon}>{action.icon}</Text>}
        <Text style={styles.chipLabel} numberOfLines={1}>
          {action.label}
        </Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

export default function SuggestedActions({ actions, onAction }: SuggestedActionsProps) {
  if (!actions || actions.length === 0) {
    return null;
  }

  const displayedActions = actions.slice(0, MAX_DISPLAYED);

  return (
    <View style={styles.container}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scrollContent}
      >
        {displayedActions.map((action, index) => (
          <AnimatedChip
            key={`${action.label}-${index}`}
            action={action}
            onPress={() => onAction(action)}
            index={index}
          />
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: spacing.sm,
  },
  scrollContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(13, 127, 242, 0.15)',
    backgroundColor: 'rgba(13, 127, 242, 0.06)',
  },
  chipIcon: {
    fontSize: fontSizes.sm,
    marginRight: spacing.xs,
  },
  chipLabel: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
});

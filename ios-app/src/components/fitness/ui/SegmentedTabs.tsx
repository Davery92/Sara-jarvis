// SegmentedTabs — pill-style tab row used for the Progress sub-tabs
// (Overview / Training / Nutrition / Recovery) and other in-screen switchers.
// Horizontally scrollable so it degrades gracefully with many items.
import React from 'react';
import { ScrollView, TouchableOpacity, Text, StyleSheet, StyleProp, ViewStyle } from 'react-native';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../../styles/theme';

export interface SegmentOption<T extends string> {
  key: T;
  label: string;
}

interface SegmentedTabsProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (key: T) => void;
  style?: StyleProp<ViewStyle>;
}

export default function SegmentedTabs<T extends string>({
  options,
  value,
  onChange,
  style,
}: SegmentedTabsProps<T>) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={[styles.scroll, style]}
      contentContainerStyle={styles.content}
    >
      {options.map(opt => {
        const active = opt.key === value;
        return (
          <TouchableOpacity
            key={opt.key}
            style={[styles.pill, active && styles.pillActive]}
            onPress={() => onChange(opt.key)}
            activeOpacity={0.8}
          >
            <Text style={[styles.pillText, active && styles.pillTextActive]}>{opt.label}</Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    flexGrow: 0,
  },
  content: {
    gap: spacing.xs + 2,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  pill: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 3,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  pillActive: {
    backgroundColor: colors.assistant.actionSoft,
    borderColor: colors.assistant.borderStrong,
  },
  pillText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
  },
  pillTextActive: {
    color: colors.accent,
    fontWeight: fontWeights.semibold,
  },
});

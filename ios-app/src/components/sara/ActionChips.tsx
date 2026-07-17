import React from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from 'react-native';
import { SuggestedAction } from '../../types/cards';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ActionChipsProps {
  actions: SuggestedAction[];
  onAction: (action: SuggestedAction) => void;
}

export default function ActionChips({ actions, onAction }: ActionChipsProps) {
  if (!actions || actions.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.container}
    >
      {actions.map((action, i) => (
        <TouchableOpacity
          key={`${action.label}-${i}`}
          style={styles.chip}
          onPress={() => onAction(action)}
          activeOpacity={0.7}
        >
          {action.icon && <Text style={styles.chipIcon}>{action.icon}</Text>}
          <Text style={styles.chipText}>{action.label}</Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    gap: spacing.sm,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(13, 127, 242, 0.08)',
    borderWidth: 1,
    borderColor: 'rgba(13, 127, 242, 0.2)',
  },
  chipIcon: {
    fontSize: 14,
  },
  chipText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
});

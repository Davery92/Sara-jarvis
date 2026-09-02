import React from 'react';
import { Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
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
  onDismiss?: () => void;
}

const MAX_DISPLAYED = 4;

/**
 * One scrollable chip row, ~40pt tall, with a dismiss control.
 *
 * This used to be a ~150pt card: a "TRY NEXT" eyebrow, a full-sentence
 * description, the first suggestion blown up into a hero button with its own
 * caption and arrow, then a chip row underneath — and no way to get rid of it
 * short of sending a message. Since suggestions attach to nearly every turn,
 * it reclaimed the bottom third of the screen after every reply.
 */
export default function SuggestedActions({ actions, onAction, onDismiss }: SuggestedActionsProps) {
  if (!actions || actions.length === 0) {
    return null;
  }

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      keyboardShouldPersistTaps="handled"
    >
      {actions.slice(0, MAX_DISPLAYED).map((action, index) => (
        <TouchableOpacity
          key={`${action.label}-${index}`}
          style={[styles.chip, index === 0 && styles.chipPrimary]}
          onPress={() => onAction(action)}
          activeOpacity={0.75}
        >
          {action.icon ? <Text style={styles.chipIcon}>{action.icon}</Text> : null}
          <Text
            style={[styles.chipText, index === 0 && styles.chipTextPrimary]}
            numberOfLines={1}
          >
            {action.label}
          </Text>
        </TouchableOpacity>
      ))}

      {onDismiss ? (
        <TouchableOpacity
          style={styles.dismissChip}
          onPress={onDismiss}
          activeOpacity={0.75}
          accessibilityLabel="Dismiss suggestions"
          hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
        >
          <Ionicons name="close" size={14} color={colors.textMuted} />
        </TouchableOpacity>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
    alignItems: 'center',
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 34,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    gap: spacing.xs,
  },
  chipPrimary: {
    borderColor: colors.primary,
    backgroundColor: 'rgba(45, 212, 191, 0.12)',
  },
  chipIcon: {
    fontSize: fontSizes.sm,
  },
  chipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    maxWidth: 220,
  },
  chipTextPrimary: {
    color: colors.text,
  },
  dismissChip: {
    width: 34,
    height: 34,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

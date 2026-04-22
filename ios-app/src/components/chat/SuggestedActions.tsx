import React from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
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
}

const MAX_DISPLAYED = 4;

export default function SuggestedActions({ actions, onAction }: SuggestedActionsProps) {
  if (!actions || actions.length === 0) {
    return null;
  }

  const displayedActions = actions.slice(0, MAX_DISPLAYED);
  const [primaryAction, ...secondaryActions] = displayedActions;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>Try next</Text>
        <Text style={styles.description}>Sara can take one of these follow-up steps right away.</Text>
      </View>

      <TouchableOpacity
        style={styles.primaryAction}
        onPress={() => onAction(primaryAction)}
        activeOpacity={0.85}
      >
        <View style={styles.primaryCopy}>
          <View style={styles.primaryLabelRow}>
            {primaryAction.icon ? <Text style={styles.primaryIcon}>{primaryAction.icon}</Text> : null}
            <Text style={styles.primaryLabel}>{primaryAction.label}</Text>
          </View>
          <Text style={styles.primaryCaption}>Use this as the next step in the conversation.</Text>
        </View>
        <Ionicons name="arrow-forward" size={18} color={colors.text} />
      </TouchableOpacity>

      {secondaryActions.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.secondaryRow}
        >
          {secondaryActions.map((action, index) => (
            <TouchableOpacity
              key={`${action.label}-${index}`}
              style={styles.secondaryChip}
              onPress={() => onAction(action)}
              activeOpacity={0.75}
            >
              {action.icon ? <Text style={styles.secondaryChipIcon}>{action.icon}</Text> : null}
              <Text style={styles.secondaryChipText} numberOfLines={1}>
                {action.label}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingTop: spacing.xs,
    paddingBottom: spacing.sm,
  },
  header: {
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
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
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
  primaryAction: {
    marginHorizontal: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.primary,
  },
  primaryCopy: {
    flex: 1,
  },
  primaryLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  primaryIcon: {
    fontSize: fontSizes.md,
  },
  primaryLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
    flexShrink: 1,
  },
  primaryCaption: {
    color: 'rgba(248, 250, 252, 0.78)',
    fontSize: fontSizes.sm,
    lineHeight: 18,
  },
  secondaryRow: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  secondaryChip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    gap: spacing.xs,
  },
  secondaryChipIcon: {
    fontSize: fontSizes.sm,
  },
  secondaryChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
});

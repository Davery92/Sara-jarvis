import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface GenericCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatItems(items: any[]): string {
  try {
    const json = JSON.stringify(items, null, 2);
    if (json.length > 200) {
      return json.slice(0, 200) + '...';
    }
    return json;
  } catch {
    return String(items).slice(0, 200);
  }
}

export default function GenericCard({ card, onAction }: GenericCardProps) {
  const title = card.title || card.card_type || 'Card';
  const hasItems = card.items && card.items.length > 0;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      {card.summary && (
        <Text style={styles.summary}>{card.summary}</Text>
      )}
      {hasItems && (
        <View style={styles.itemsContainer}>
          <Text style={styles.itemsText}>{formatItems(card.items)}</Text>
        </View>
      )}
      {!card.summary && !hasItems && (
        <Text style={styles.emptyText}>No content available</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  summary: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.5,
    marginBottom: spacing.sm,
  },
  itemsContainer: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
  },
  itemsText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontFamily: 'monospace',
    lineHeight: fontSizes.xs * 1.6,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

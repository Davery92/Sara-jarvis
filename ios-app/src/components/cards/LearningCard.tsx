import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface LearningCardProps {
  card: any;
  onAction: (action: any) => void;
}

export default function LearningCard({ card, onAction }: LearningCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && <Text style={styles.title}>{card.title}</Text>}
      {items.map((item: any, index: number) => {
        const mastery = Math.min(Math.max(item.mastery ?? item.progress ?? 0, 0), 100);
        return (
          <View key={item.id ?? index} style={styles.topicRow}>
            <View style={styles.topicHeader}>
              <Text style={styles.topicName} numberOfLines={1}>
                {item.name || item.topic || item.title || 'Untitled Topic'}
              </Text>
              <Text style={styles.percentageText}>{Math.round(mastery)}%</Text>
            </View>
            <View style={styles.progressBarBackground}>
              <View
                style={[
                  styles.progressBarFill,
                  { width: `${mastery}%` },
                ]}
              />
            </View>
          </View>
        );
      })}
      {items.length === 0 && (
        <Text style={styles.emptyText}>No learning topics</Text>
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
  topicRow: {
    marginBottom: spacing.sm,
  },
  topicHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  topicName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
    flex: 1,
    marginRight: spacing.sm,
  },
  percentageText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  progressBarBackground: {
    height: 6,
    backgroundColor: colors.border,
    borderRadius: borderRadius.full,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: borderRadius.full,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

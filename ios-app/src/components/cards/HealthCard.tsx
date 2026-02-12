import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface HealthCardProps {
  card: any;
  onAction: (action: any) => void;
}

export default function HealthCard({ card }: HealthCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No health data</Text>
      ) : (
        <View style={styles.grid}>
          {items.map((metric: any, index: number) => (
            <View key={metric.id ?? metric.name ?? index} style={styles.metricBadge}>
              <Text style={styles.metricValue} numberOfLines={1}>
                {metric.value}{metric.unit ? ` ${metric.unit}` : ''}
              </Text>
              <Text style={styles.metricName} numberOfLines={1}>
                {metric.name || metric.label || metric.metric}
              </Text>
            </View>
          ))}
        </View>
      )}

      {card.summary ? (
        <Text style={styles.summary}>{card.summary}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  metricBadge: {
    width: '47%',
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    alignItems: 'center',
  },
  metricValue: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 2,
  },
  metricName: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    textTransform: 'capitalize',
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});

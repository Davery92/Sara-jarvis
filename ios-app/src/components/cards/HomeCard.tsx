import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface HomeCardProps {
  card: any;
  onAction: (action: any) => void;
}

function isOnState(state: string): boolean {
  const s = (state || '').toLowerCase();
  return s === 'on' || s === 'open' || s === 'playing' || s === 'home' || s === 'active';
}

export default function HomeCard({ card, onAction }: HomeCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && <Text style={styles.title}>{card.title}</Text>}
      {items.map((item: any, index: number) => {
        const on = isOnState(item.state);
        return (
          <View key={item.id ?? index} style={styles.deviceRow}>
            <View style={styles.deviceInfo}>
              <Text style={styles.deviceName} numberOfLines={1}>
                {item.name || item.entity_id || 'Unknown Device'}
              </Text>
              {item.domain && (
                <Text style={styles.deviceDomain}>{item.domain}</Text>
              )}
            </View>
            <View style={[styles.stateChip, on && styles.stateChipOn]}>
              <View style={[styles.stateDot, on ? styles.dotOn : styles.dotOff]} />
              <Text style={[styles.stateText, on ? styles.stateOn : styles.stateOff]}>
                {item.state || 'unknown'}
              </Text>
            </View>
          </View>
        );
      })}
      {items.length === 0 && (
        <Text style={styles.emptyText}>No devices</Text>
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
  deviceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(63, 63, 70, 0.5)',
  },
  deviceInfo: {
    flex: 1,
    marginRight: spacing.sm,
  },
  deviceName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  deviceDomain: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  stateChip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(63, 63, 70, 0.3)',
  },
  stateChipOn: {
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
  },
  stateDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: spacing.xs,
  },
  dotOn: {
    backgroundColor: colors.success,
  },
  dotOff: {
    backgroundColor: colors.textMuted,
  },
  stateText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  stateOn: {
    color: colors.success,
  },
  stateOff: {
    color: colors.textMuted,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
});

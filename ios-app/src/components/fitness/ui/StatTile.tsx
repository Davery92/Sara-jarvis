// StatTile — a compact metric tile (e.g. personal records: "Bench Press 225 lbs",
// or a recovery sub-metric). Renders inside a bordered surface; optional accent
// colors the value.
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, StyleProp, ViewStyle } from 'react-native';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../../styles/theme';

interface StatTileProps {
  label: string;
  value: string | number;
  unit?: string;
  accent?: string;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
}

export default function StatTile({ label, value, unit, accent, onPress, style }: StatTileProps) {
  const Wrapper: any = onPress ? TouchableOpacity : View;
  return (
    <Wrapper style={[styles.tile, style]} onPress={onPress} activeOpacity={0.85}>
      <Text style={styles.label} numberOfLines={1}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[styles.value, accent ? { color: accent } : null]} numberOfLines={1}>
          {value}
        </Text>
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
    </Wrapper>
  );
}

const styles = StyleSheet.create({
  tile: {
    flex: 1,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.sm + 2,
  },
  label: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginBottom: 6,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  value: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: fontWeights.bold,
  },
  unit: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginLeft: 3,
  },
});

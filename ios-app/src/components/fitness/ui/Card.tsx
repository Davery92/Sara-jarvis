// Card — the base surface used across the restyled Fitness section. Matches the
// mockups: rounded panel, hairline border, deep navy surface. Use `onPress` to
// make it tappable (renders a TouchableOpacity), otherwise a plain View.
import React from 'react';
import { View, TouchableOpacity, StyleSheet, ViewStyle, StyleProp } from 'react-native';
import { colors, spacing, borderRadius } from '../../../styles/theme';

interface CardProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  onLongPress?: () => void;
  padded?: boolean;       // default true
  accent?: string;        // optional left/border accent color
}

export default function Card({
  children,
  style,
  onPress,
  onLongPress,
  padded = true,
  accent,
}: CardProps) {
  const cardStyle: StyleProp<ViewStyle> = [
    styles.card,
    padded && styles.padded,
    accent ? { borderColor: accent } : null,
    style,
  ];

  if (onPress || onLongPress) {
    return (
      <TouchableOpacity
        style={cardStyle}
        onPress={onPress}
        onLongPress={onLongPress}
        activeOpacity={0.85}
      >
        {children}
      </TouchableOpacity>
    );
  }
  return <View style={cardStyle}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
  },
  padded: {
    padding: spacing.md,
  },
});

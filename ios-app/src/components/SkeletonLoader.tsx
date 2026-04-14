import React, { useEffect, useRef } from 'react';
import { View, Animated, StyleSheet, ViewStyle } from 'react-native';
import { colors, spacing, borderRadius } from '../styles/theme';

interface SkeletonLoaderProps {
  width?: number | string;
  height?: number;
  borderRadiusValue?: number;
  style?: ViewStyle;
}

function SkeletonItem({ width = '100%', height = 16, borderRadiusValue = borderRadius.sm, style }: SkeletonLoaderProps) {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 1000, useNativeDriver: true }),
        Animated.timing(shimmer, { toValue: 0, duration: 1000, useNativeDriver: true }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, []);

  const opacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.7],
  });

  return (
    <Animated.View
      style={[
        {
          width: width as any,
          height,
          borderRadius: borderRadiusValue,
          backgroundColor: colors.surfaceLight,
          opacity,
        },
        style,
      ]}
    />
  );
}

export function SkeletonListItem() {
  return (
    <View style={styles.listItem}>
      <SkeletonItem width={40} height={40} borderRadiusValue={borderRadius.full} />
      <View style={styles.listItemContent}>
        <SkeletonItem width="60%" height={14} />
        <SkeletonItem width="90%" height={12} style={{ marginTop: spacing.xs }} />
      </View>
    </View>
  );
}

export function SkeletonCard() {
  return (
    <View style={styles.card}>
      <SkeletonItem width="70%" height={18} />
      <SkeletonItem width="100%" height={12} style={{ marginTop: spacing.sm }} />
      <SkeletonItem width="40%" height={12} style={{ marginTop: spacing.xs }} />
    </View>
  );
}

export function SkeletonList({ count = 5 }: { count?: number }) {
  return (
    <View style={styles.list}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonListItem key={`skeleton-${i}`} />
      ))}
    </View>
  );
}

export default SkeletonItem;

const styles = StyleSheet.create({
  listItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  listItemContent: {
    flex: 1,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  list: {
    paddingTop: spacing.sm,
  },
});

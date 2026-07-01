// Ring — a donut progress ring with an arbitrary centered overlay. Used for the
// macro rings (calories/protein/carbs/fat) and the recovery score dial. The arc
// starts at 12 o'clock and sweeps clockwise.
//
// Rendered with react-native-svg (NOT Skia): Skia's Canvas hard-requires
// react-native-reanimated, which isn't installed in this build, so it crashes at
// runtime. SVG renders reliably with no native rebuild — same choice the presence
// orb makes (see SaraOrbHaze).
import React from 'react';
import { View, StyleSheet } from 'react-native';
import Svg, { Circle, G } from 'react-native-svg';

interface RingProps {
  size: number;
  strokeWidth: number;
  progress: number;        // 0..1 (clamped)
  color: string;
  trackColor?: string;
  children?: React.ReactNode;   // centered overlay (numbers, labels)
}

export default function Ring({
  size,
  strokeWidth,
  progress,
  color,
  trackColor = 'rgba(130, 151, 182, 0.16)',
  children,
}: RingProps) {
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, progress));
  const dashOffset = circumference * (1 - pct);

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size}>
        {/* rotate -90° so the arc starts at the top and sweeps clockwise */}
        <G rotation={-90} origin={`${cx}, ${cy}`}>
          <Circle
            cx={cx}
            cy={cy}
            r={r}
            stroke={trackColor}
            strokeWidth={strokeWidth}
            fill="none"
          />
          <Circle
            cx={cx}
            cy={cy}
            r={r}
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
          />
        </G>
      </Svg>
      {children ? (
        <View style={[StyleSheet.absoluteFill, styles.center]} pointerEvents="none">
          {children}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});

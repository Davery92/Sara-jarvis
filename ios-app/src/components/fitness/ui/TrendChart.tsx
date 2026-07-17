// TrendChart — a line chart with a soft gradient area fill, matching the recovery
// / body-weight trend charts in the mockups. Smooths the line with a Catmull-Rom
// spline and marks the latest point. Axis labels are plain RN Text.
//
// Rendered with react-native-svg (NOT Skia): Skia's Canvas hard-requires
// react-native-reanimated, which isn't installed in this build. SVG renders
// reliably with no native rebuild.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Path, Line, Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import { colors } from '../../../styles/theme';

interface TrendChartProps {
  data: number[];
  width: number;
  height: number;
  color?: string;
  fillColor?: string;          // gradient top color (defaults to color)
  xLabels?: string[];          // rendered evenly below the chart
  yTicks?: number[];           // horizontal gridlines + left labels
  min?: number;                // y-axis floor (default: data min)
  max?: number;                // y-axis ceil (default: data max)
  showDot?: boolean;           // mark the last point (default true)
  strokeWidth?: number;
}

const PAD_TOP = 8;
const PAD_BOTTOM = 8;
const PAD_RIGHT = 6;

export default function TrendChart({
  data,
  width,
  height,
  color = colors.primary,
  fillColor,
  xLabels,
  yTicks,
  min,
  max,
  showDot = true,
  strokeWidth = 2.5,
}: TrendChartProps) {
  const gradId = React.useId();
  const yLabelWidth = yTicks && yTicks.length ? 30 : 0;
  const chartW = width - PAD_RIGHT - yLabelWidth;
  const chartH = height - PAD_TOP - PAD_BOTTOM;
  const x0 = yLabelWidth;

  const lo = min != null ? min : (data.length ? Math.min(...data) : 0);
  const hi = max != null ? max : (data.length ? Math.max(...data) : 1);
  const span = hi - lo || 1;

  const toX = (i: number) =>
    data.length === 1 ? x0 + chartW / 2 : x0 + (i / (data.length - 1)) * chartW;
  const toY = (v: number) => PAD_TOP + chartH - ((v - lo) / span) * chartH;

  const { lineD, areaD, lastPt } = React.useMemo(() => {
    if (!data.length) return { lineD: '', areaD: '', lastPt: null as null | { x: number; y: number } };
    const pts = data.map((v, i) => ({ x: toX(i), y: toY(v) }));

    let d = `M ${pts[0].x} ${pts[0].y}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i === 0 ? 0 : i - 1];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[i + 2 < pts.length ? i + 2 : i + 1];
      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
    }

    const baseY = PAD_TOP + chartH;
    const area = `${d} L ${pts[pts.length - 1].x} ${baseY} L ${pts[0].x} ${baseY} Z`;

    return { lineD: d, areaD: area, lastPt: pts[pts.length - 1] };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, chartW, chartH, x0, lo, hi]);

  return (
    <View style={{ width }}>
      <Svg width={width} height={height}>
        <Defs>
          <LinearGradient id={`grad-${gradId}`} x1="0" y1={PAD_TOP} x2="0" y2={PAD_TOP + chartH} gradientUnits="userSpaceOnUse">
            <Stop offset="0" stopColor={fillColor ?? color} stopOpacity={0.35} />
            <Stop offset="1" stopColor={fillColor ?? color} stopOpacity={0} />
          </LinearGradient>
        </Defs>

        {/* gridlines */}
        {(yTicks ?? []).map((t, i) => {
          const y = toY(t);
          return (
            <Line
              key={`g-${i}`}
              x1={x0}
              y1={y}
              x2={x0 + chartW}
              y2={y}
              stroke={colors.divider}
              strokeWidth={1}
              strokeDasharray="3,4"
            />
          );
        })}

        {areaD ? <Path d={areaD} fill={`url(#grad-${gradId})`} /> : null}
        {lineD ? (
          <Path
            d={lineD}
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        ) : null}
        {showDot && lastPt ? <Circle cx={lastPt.x} cy={lastPt.y} r={4} fill={color} /> : null}
      </Svg>

      {/* y tick labels (overlaid on the left gutter) */}
      {yTicks && yTicks.length ? (
        <View style={[StyleSheet.absoluteFill, { width: yLabelWidth }]} pointerEvents="none">
          {yTicks.map((t, i) => (
            <Text key={`yl-${i}`} style={[styles.yLabel, { top: toY(t) - 6 }]}>
              {t}
            </Text>
          ))}
        </View>
      ) : null}

      {/* x labels */}
      {xLabels && xLabels.length ? (
        <View style={[styles.xLabels, { marginLeft: x0 }]}>
          {xLabels.map((l, i) => (
            <Text key={`xl-${i}`} style={styles.xLabel}>
              {l}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  yLabel: {
    position: 'absolute',
    left: 0,
    width: 26,
    textAlign: 'right',
    color: colors.textMuted,
    fontSize: 10,
  },
  xLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 4,
  },
  xLabel: {
    color: colors.textMuted,
    fontSize: 10,
  },
});

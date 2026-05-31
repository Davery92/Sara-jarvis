import React, { useRef, useEffect } from 'react'
import { Animated, StyleSheet, Easing, View } from 'react-native'
import Svg, { Defs, RadialGradient, Stop, Ellipse } from 'react-native-svg'

/**
 * SaraOrb — Sara's presence as a soft, churning cool haze.
 *
 * Several round, very soft, low-opacity radial puffs sit off-center and rotate
 * around the middle at different speeds/directions while fading in and out of
 * phase. Because they're faint and heavily overlapping, no single shape reads as
 * a distinct circle/oval — it churns like cool smoke. Core SVG only (radial
 * gradients), so it renders reliably with no native rebuild and no filters.
 * (True volumetric smoke would want Skia, which isn't installed.)
 *
 * Decorative — pointerEvents="none" so taps pass to the Pressable underneath.
 */

const AnimatedView = Animated.View

// Cool "ghost" palette; round puffs, off-center so rotation makes them churn.
const PUFFS = [
  { id: 'p1', color: '#5eead4', cx: 44, cy: 40, r: 32 }, // teal
  { id: 'p2', color: '#22d3ee', cx: 58, cy: 48, r: 34 }, // cyan
  { id: 'p3', color: '#67e8f9', cx: 46, cy: 58, r: 28 }, // light cyan
  { id: 'p4', color: '#2dd4bf', cx: 52, cy: 46, r: 36 }, // teal-green
  { id: 'p5', color: '#818cf8', cx: 50, cy: 52, r: 26 }, // soft indigo accent
]

function Puff({ id, color, cx, cy, r }: (typeof PUFFS)[number]) {
  return (
    <Svg width="100%" height="100%" viewBox="0 0 100 100">
      <Defs>
        <RadialGradient id={id} cx="50%" cy="50%" r="50%">
          <Stop offset="0%" stopColor={color} stopOpacity="0.55" />
          <Stop offset="45%" stopColor={color} stopOpacity="0.18" />
          <Stop offset="100%" stopColor={color} stopOpacity="0" />
        </RadialGradient>
      </Defs>
      <Ellipse cx={cx} cy={cy} rx={r} ry={r} fill={`url(#${id})`} />
    </Svg>
  )
}

export default function SaraOrbHaze({ size = 56 }: { size?: number }) {
  const rot = useRef(PUFFS.map(() => new Animated.Value(0))).current
  const fade = useRef(PUFFS.map(() => new Animated.Value(0.5))).current
  const breath = useRef(new Animated.Value(0)).current

  useEffect(() => {
    const durations = [28000, 36000, 22000, 41000, 31000]
    const fadeDur = [4300, 5200, 4700, 5800, 5000]

    const spins = rot.map((v, i) =>
      Animated.loop(
        Animated.timing(v, {
          toValue: 1,
          duration: durations[i],
          easing: Easing.linear,
          useNativeDriver: true,
        })
      )
    )
    const fades = fade.map((v, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.timing(v, { toValue: 0.85, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
          Animated.timing(v, { toValue: 0.2, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        ])
      )
    )
    const breathe = Animated.loop(
      Animated.sequence([
        Animated.timing(breath, { toValue: 1, duration: 3200, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(breath, { toValue: 0, duration: 3200, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ])
    )

    const all = [...spins, ...fades, breathe]
    all.forEach((a) => a.start())
    return () => all.forEach((a) => a.stop())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scale = breath.interpolate({ inputRange: [0, 1], outputRange: [0.97, 1.03] })

  return (
    <AnimatedView
      pointerEvents="none"
      style={[
        styles.container,
        { width: size, height: size, borderRadius: size / 2, transform: [{ scale }] },
      ]}
    >
      <View style={[StyleSheet.absoluteFill, styles.base, { borderRadius: size / 2 }]} />
      {PUFFS.map((p, i) => {
        const rotate = rot[i].interpolate({
          inputRange: [0, 1],
          outputRange: i % 2 === 0 ? ['0deg', '360deg'] : ['0deg', '-360deg'],
        })
        return (
          <AnimatedView
            key={p.id}
            style={[StyleSheet.absoluteFill, { opacity: fade[i], transform: [{ rotate }] }]}
          >
            <Puff {...p} />
          </AnimatedView>
        )
      })}
    </AnimatedView>
  )
}

const styles = StyleSheet.create({
  container: {
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0f1f',
  },
  base: { backgroundColor: '#0a0f1f' },
})

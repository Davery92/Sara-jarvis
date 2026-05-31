import React, { useRef, useEffect } from 'react'
import { Animated, StyleSheet, Easing, View } from 'react-native'
import Svg, { Defs, RadialGradient, Stop, Ellipse, G } from 'react-native-svg'

/**
 * SaraOrb — a swirling, ghostly presence orb made of slow smoke tendrils.
 *
 * Each tendril is a thin, tilted, soft-edged wisp (elongated radial gradient).
 * They rotate around the center at different speeds/directions and fade in and
 * out of phase, so the whole thing curls and drifts like cool smoke — distinct
 * from Siri's round multicolor swirl. Pure RN + react-native-svg (no rebuild);
 * all transform/opacity so it stays on the native driver.
 *
 * Decorative only — `pointerEvents="none"` so taps pass through to the Pressable.
 */

const AnimatedView = Animated.View

// Cool, ethereal "ghost smoke" palette + base tilt per tendril.
const TENDRILS = [
  { id: 't1', color: '#5eead4', angle: 0 },   // teal
  { id: 't2', color: '#22d3ee', angle: 55 },  // cyan
  { id: 't3', color: '#67e8f9', angle: 110 }, // light cyan
  { id: 't4', color: '#818cf8', angle: 152 }, // soft indigo accent
]

function Tendril({ id, color, angle }: (typeof TENDRILS)[number]) {
  return (
    <Svg width="100%" height="100%" viewBox="0 0 100 100">
      <Defs>
        <RadialGradient id={id} cx="50%" cy="50%" r="50%">
          <Stop offset="0%" stopColor={color} stopOpacity="0.9" />
          <Stop offset="50%" stopColor={color} stopOpacity="0.28" />
          <Stop offset="100%" stopColor={color} stopOpacity="0" />
        </RadialGradient>
      </Defs>
      {/* thin, tilted wisp; offset above center so layer rotation makes it curl around */}
      <G rotation={angle} origin="50, 50">
        <Ellipse cx="50" cy="40" rx="48" ry="12" fill={`url(#${id})`} />
      </G>
    </Svg>
  )
}

export default function SaraOrb({ size = 56 }: { size?: number }) {
  const rot = useRef(TENDRILS.map(() => new Animated.Value(0))).current
  const fade = useRef(TENDRILS.map(() => new Animated.Value(0.6))).current
  const breath = useRef(new Animated.Value(0)).current

  useEffect(() => {
    const durations = [26000, 33000, 21000, 38000]
    const fadeDur = [4200, 5200, 4700, 5600]

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
          Animated.timing(v, { toValue: 0.9, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
          Animated.timing(v, { toValue: 0.2, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        ])
      )
    )
    const breathe = Animated.loop(
      Animated.sequence([
        Animated.timing(breath, { toValue: 1, duration: 3000, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(breath, { toValue: 0, duration: 3000, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ])
    )

    const all = [...spins, ...fades, breathe]
    all.forEach((a) => a.start())
    return () => all.forEach((a) => a.stop())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scale = breath.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1.04] })

  return (
    <AnimatedView
      pointerEvents="none"
      style={[
        styles.container,
        { width: size, height: size, borderRadius: size / 2, transform: [{ scale }] },
      ]}
    >
      <View style={[StyleSheet.absoluteFill, styles.base, { borderRadius: size / 2 }]} />
      {TENDRILS.map((t, i) => {
        const rotate = rot[i].interpolate({
          inputRange: [0, 1],
          outputRange: i % 2 === 0 ? ['0deg', '360deg'] : ['0deg', '-360deg'],
        })
        return (
          <AnimatedView
            key={t.id}
            style={[StyleSheet.absoluteFill, { opacity: fade[i], transform: [{ rotate }] }]}
          >
            <Tendril {...t} />
          </AnimatedView>
        )
      })}
      <View style={[styles.core, { borderRadius: size / 2 }]} />
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
  core: {
    position: 'absolute',
    width: '30%',
    height: '30%',
    backgroundColor: 'rgba(220,255,250,0.10)',
  },
})

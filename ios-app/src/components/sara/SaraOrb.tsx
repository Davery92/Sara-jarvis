import React, { useRef, useEffect } from 'react'
import { Animated, StyleSheet, Easing, View } from 'react-native'
import Svg, { Defs, RadialGradient, Stop, Ellipse } from 'react-native-svg'

/**
 * SaraOrb — a swirling, ghostly, color-shifting orb that represents Sara's presence.
 *
 * Pure RN + react-native-svg (already linked via lucide-react-native), so it needs
 * no native rebuild. Several soft radial-gradient blobs orbit the center at different
 * speeds and fade in/out of phase, so the colors continuously morph and swirl. All
 * animations are transform/opacity → native-driver friendly and smooth.
 *
 * Note: this is the in-app orb. The widget can't animate (WidgetKit renders static
 * snapshots), so there it'll be a static gradient orb tinted by mood.
 */

const AnimatedView = Animated.View

// Ethereal palette — cyans, indigos, violets, magenta.
const BLOBS = [
  { id: 'b1', color: '#22d3ee', cx: 36, cy: 40, rx: 42, ry: 42 },
  { id: 'b2', color: '#6366f1', cx: 64, cy: 44, rx: 46, ry: 46 },
  { id: 'b3', color: '#a855f7', cx: 48, cy: 64, rx: 40, ry: 40 },
  { id: 'b4', color: '#ec4899', cx: 40, cy: 56, rx: 34, ry: 34 },
]

function Blob({ id, color, cx, cy, rx, ry }: (typeof BLOBS)[number]) {
  return (
    <Svg width="100%" height="100%" viewBox="0 0 100 100">
      <Defs>
        <RadialGradient id={id} cx="50%" cy="50%" r="50%">
          <Stop offset="0%" stopColor={color} stopOpacity="0.95" />
          <Stop offset="60%" stopColor={color} stopOpacity="0.3" />
          <Stop offset="100%" stopColor={color} stopOpacity="0" />
        </RadialGradient>
      </Defs>
      <Ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={`url(#${id})`} />
    </Svg>
  )
}

export default function SaraOrb({ size = 56 }: { size?: number }) {
  // One rotation driver per blob (varied speed/direction) + per-blob opacity phase.
  const rot = useRef(BLOBS.map(() => new Animated.Value(0))).current
  const fade = useRef(BLOBS.map(() => new Animated.Value(0.6))).current
  const breath = useRef(new Animated.Value(0)).current

  useEffect(() => {
    const durations = [16000, 11000, 20000, 13000]
    const dirs = [1, -1, 1, -1]
    const fadeDur = [3200, 4100, 3700, 4600]

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
          Animated.timing(v, { toValue: 0.95, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
          Animated.timing(v, { toValue: 0.25, duration: fadeDur[i], easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        ])
      )
    )
    const breathe = Animated.loop(
      Animated.sequence([
        Animated.timing(breath, { toValue: 1, duration: 2800, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(breath, { toValue: 0, duration: 2800, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ])
    )

    const all = [...spins, ...fades, breathe]
    // Stagger fade starts so colors don't pulse in unison.
    all.forEach((a) => a.start())
    return () => all.forEach((a) => a.stop())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scale = breath.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1.04] })

  return (
    <AnimatedView
      style={[
        styles.container,
        { width: size, height: size, borderRadius: size / 2, transform: [{ scale }] },
      ]}
    >
      {/* dark base so the gradients glow */}
      <View style={[StyleSheet.absoluteFill, styles.base, { borderRadius: size / 2 }]} />
      {BLOBS.map((blob, i) => {
        const rotate = rot[i].interpolate({
          inputRange: [0, 1],
          outputRange: dirsDeg(i),
        })
        return (
          <AnimatedView
            key={blob.id}
            style={[StyleSheet.absoluteFill, { opacity: fade[i], transform: [{ rotate }] }]}
          >
            <Blob {...blob} />
          </AnimatedView>
        )
      })}
      {/* soft bright core */}
      <View style={[styles.core, { borderRadius: size / 2 }]} pointerEvents="none" />
    </AnimatedView>
  )
}

function dirsDeg(i: number): [string, string] {
  return i % 2 === 0 ? ['0deg', '360deg'] : ['0deg', '-360deg']
}

const styles = StyleSheet.create({
  container: {
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0f1f',
  },
  base: {
    backgroundColor: '#0a0f1f',
  },
  core: {
    position: 'absolute',
    width: '38%',
    height: '38%',
    backgroundColor: 'rgba(255,255,255,0.18)',
  },
})

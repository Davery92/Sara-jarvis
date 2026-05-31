import React from 'react'
import SaraOrbHaze from './SaraOrbHaze'

/**
 * SaraOrb — presence orb switcher.
 *
 * Uses the Skia volumetric-smoke orb when the native Skia module is actually
 * present in the build; otherwise falls back to the pure-SVG haze. This keeps a
 * dev client that predates the Skia native module from crashing — the probe
 * below calls a real native function (RuntimeEffect.Make) inside try/catch, so
 * if Skia isn't linked we quietly use the haze.
 */

let SkiaOrb: React.ComponentType<{ size?: number }> | null = null
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const skia = require('@shopify/react-native-skia')
  // Calling Make exercises the native binding; throws if Skia isn't linked.
  const probe = skia?.Skia?.RuntimeEffect?.Make?.('half4 main(float2 xy){ return half4(0.0); }')
  if (probe) {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    SkiaOrb = require('./SaraOrbSkia').default
  }
} catch {
  SkiaOrb = null
}

export default function SaraOrb(props: { size?: number }) {
  const Component = SkiaOrb ?? SaraOrbHaze
  return <Component {...props} />
}

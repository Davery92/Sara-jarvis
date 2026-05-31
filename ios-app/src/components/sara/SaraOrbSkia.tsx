import React, { useEffect, useState } from 'react'
import { View, StyleSheet } from 'react-native'
import { Canvas, Fill, Shader, Skia } from '@shopify/react-native-skia'

/**
 * SaraOrbSkia — real volumetric smoke via a Skia fractal-noise (fbm) shader.
 *
 * An SkSL fragment shader builds domain-warped fbm noise that drifts over time
 * for genuine wispy smoke, tinted with Sara's cool teal/cyan/indigo palette and
 * faded out in a circle. Time is driven by a requestAnimationFrame loop (Skia's
 * useClock needs reanimated, which we don't depend on).
 *
 * REQUIRES the native Skia module — only render this in a build that bundled
 * @shopify/react-native-skia. pointerEvents="none" (decorative).
 */

const SMOKE_SKSL = `
uniform float u_time;
uniform float2 u_resolution;

float hash(float2 p) {
  return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453);
}

float noise(float2 p) {
  float2 i = floor(p);
  float2 f = fract(p);
  float a = hash(i);
  float b = hash(i + float2(1.0, 0.0));
  float c = hash(i + float2(0.0, 1.0));
  float d = hash(i + float2(1.0, 1.0));
  float2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(float2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = p * 2.02;
    a = a * 0.5;
  }
  return v;
}

half4 main(float2 fragcoord) {
  float2 uv = fragcoord / u_resolution;
  float2 p = (uv - 0.5) * 2.0;
  float r = length(p);

  float t = u_time * 0.06;
  // domain warp for swirling smoke
  float2 q = float2(fbm(uv * 3.0 + t), fbm(uv * 3.0 - t + 5.2));
  float n = fbm(uv * 3.5 + q * 1.7 + float2(0.0, t * 0.5));

  half3 teal = half3(0.37, 0.92, 0.83);
  half3 cyan = half3(0.13, 0.83, 0.93);
  half3 indigo = half3(0.51, 0.55, 0.97);
  half3 col = mix(teal, cyan, half(n));
  col = mix(col, indigo, half(smoothstep(0.55, 1.0, n)));

  float density = smoothstep(0.18, 0.85, n);
  float edge = smoothstep(1.0, 0.32, r); // soft circular falloff
  float alpha = density * edge;

  return half4(col, half(alpha));
}
`

const effect = Skia.RuntimeEffect.Make(SMOKE_SKSL)

export default function SaraOrbSkia({ size = 56 }: { size?: number }) {
  const [time, setTime] = useState(0)

  useEffect(() => {
    let raf: number
    let acc = 0
    let last = 0
    const loop = (ts: number) => {
      if (last) acc += (ts - last) / 1000
      last = ts
      setTime(acc)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  // If the shader failed to compile, render just the dark base (no crash).
  return (
    <View
      pointerEvents="none"
      style={[styles.container, { width: size, height: size, borderRadius: size / 2 }]}
    >
      {effect ? (
        <Canvas style={{ width: size, height: size }}>
          <Fill>
            <Shader source={effect} uniforms={{ u_time: time, u_resolution: [size, size] }} />
          </Fill>
        </Canvas>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    overflow: 'hidden',
    backgroundColor: '#0a0f1f',
  },
})

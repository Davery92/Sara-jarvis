// useSpriteState (stub)
// Purpose: Subscribe to spriteBus events and compute effective
// base state, overlay, and tone for the Sprite component.
//
// Implementation status: scaffold only. Returns simple reactive state;
// add dwell telemetry, cooldown handling, and reduced-motion logic later.

import { useEffect, useMemo, useRef, useState } from 'react'
import { spriteBus, type SpriteBaseState, type SpriteOverlay, type SpriteTone } from '../state/spriteBus'
import { APP_CONFIG } from '../config'

export interface SpriteEffectiveState {
  base: SpriteBaseState
  overlay?: SpriteOverlay
  tone?: SpriteTone
}

export interface UseSpriteStateOptions {
  initialBase?: SpriteBaseState
  initialTone?: SpriteTone
}

export function useSpriteState(options: UseSpriteStateOptions = {}) {
  const { initialBase = 'idle', initialTone } = options
  const [base, setBase] = useState<SpriteBaseState>(initialBase)
  const [overlay, setOverlay] = useState<SpriteOverlay | undefined>(undefined)
  const [tone, setTone] = useState<SpriteTone | undefined>(initialTone)
  const [energyScale, setEnergyScale] = useState<number>(1)
  const [tempoBreatheSec, setTempoBreatheSec] = useState<number>(3.6)
  const [tempoShimmerSec, setTempoShimmerSec] = useState<number>(11)
  const [brightnessScale, setBrightnessScale] = useState<number>(1)
  const [saturationScale, setSaturationScale] = useState<number>(1)

  // Track dwell time (stub; accumulate in ref)
  const lastBaseChange = useRef<number>(Date.now())
  const dwellMs = useRef<Record<SpriteBaseState, number>>({ idle: 0, listening: 0, thinking: 0 })

  useEffect(() => {
    const unsub = spriteBus.subscribe(evt => {
      switch (evt.type) {
        case 'setBase': {
          // accumulate dwell for previous base
          const now = evt.ts || Date.now()
          dwellMs.current[base] += now - lastBaseChange.current
          lastBaseChange.current = now
          setBase(evt.base)
          break
        }
        case 'setOverlay': {
          setOverlay(evt.overlay)
          // Note: handle autoClearMs and cooldowns in future iteration
          if (evt.autoClearMs && evt.overlay) {
            const o = evt.overlay
            const t = window.setTimeout(() => {
              // clear only if same overlay still present
              setOverlay(prev => (prev === o ? undefined : prev))
            }, evt.autoClearMs)
            return () => clearTimeout(t)
          }
          break
        }
        case 'setTone': {
          setTone(evt.tone)
          break
        }
        case 'setVisuals': {
          if (typeof evt.energyScale === 'number') setEnergyScale(evt.energyScale)
          if (typeof evt.tempoBreatheSec === 'number') setTempoBreatheSec(evt.tempoBreatheSec)
          if (typeof evt.tempoShimmerSec === 'number') setTempoShimmerSec(evt.tempoShimmerSec)
          if (typeof evt.brightnessScale === 'number') setBrightnessScale(evt.brightnessScale)
          if (typeof evt.saturationScale === 'number') setSaturationScale(evt.saturationScale)
          break
        }
        case 'ack': {
          // Clear overlays and tone bias on acknowledge for now
          setOverlay(undefined)
          setTone(undefined)
          break
        }
      }
    })
    return () => unsub()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base])

  // Telemetry: periodic dwell logging
  useEffect(() => {
    const interval = window.setInterval(() => {
      const now = Date.now()
      // Include current state's ongoing dwell
      const snapshot: Record<SpriteBaseState, number> = { ...dwellMs.current }
      snapshot[base] += now - lastBaseChange.current
      lastBaseChange.current = now
      dwellMs.current = { idle: 0, listening: 0, thinking: 0 }
      const total = snapshot.idle + snapshot.listening + snapshot.thinking
      if (total > 0) {
        console.log('[sprite.telemetry] dwell_ms', snapshot)
        // POST telemetry (best-effort)
        try {
          fetch(`${APP_CONFIG.apiUrl}/sprite/telemetry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ type: 'dwell', value_ms: snapshot, ts: now }),
          })
        } catch {}
      }
    }, 60000)
    return () => clearInterval(interval)
  }, [base])

  const effective: SpriteEffectiveState = useMemo(() => ({ base, overlay, tone }), [base, overlay, tone])

  // Expose a lightweight API for components
  return {
    effective,
    setBase: (b: SpriteBaseState, source?: string) => spriteBus.setBase(b, source),
    setOverlay: (o?: SpriteOverlay, opts?: { source?: string; importance?: 'low' | 'medium' | 'high'; autoClearMs?: number }) => spriteBus.setOverlay(o, opts),
    setTone: (t?: SpriteTone, source?: string) => spriteBus.setTone(t, source),
    acknowledge: (source?: string) => spriteBus.acknowledge(source),
    visuals: { energyScale, tempoBreatheSec, tempoShimmerSec, brightnessScale, saturationScale },
    setVisuals: (v: { energyScale?: number; tempoBreatheSec?: number; tempoShimmerSec?: number; brightnessScale?: number; saturationScale?: number }, source?: string) => spriteBus.setVisuals(v, source),
    // TODO: expose dwell data and a flush/reset for telemetry
  }
}

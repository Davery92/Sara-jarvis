// Sprite Event Bus (stub)
// Purpose: Centralize sprite state events (base, overlays, tone),
// apply cooldowns, and provide a single place to subscribe.
//
// Implementation status: scaffold only. Fill in logic during Phase 1.

export type SpriteBaseState = 'idle' | 'listening' | 'thinking'
export type SpriteOverlay = 'alert' | 'celebrate' | 'speaking' | 'notifying'
export type SpriteTone = 'neutral' | 'focused' | 'playful' | 'serious'

export interface SpriteEventBase {
  ts?: number
  source?: string // e.g., 'chat', 'insight', 'vuln', 'system'
}

export interface SetBaseEvent extends SpriteEventBase {
  type: 'setBase'
  base: SpriteBaseState
}

export interface SetOverlayEvent extends SpriteEventBase {
  type: 'setOverlay'
  overlay?: SpriteOverlay // undefined clears overlay
  importance?: 'low' | 'medium' | 'high'
  autoClearMs?: number // default varies by overlay type
}

export interface SetToneEvent extends SpriteEventBase {
  type: 'setTone'
  tone?: SpriteTone // undefined clears tone bias
}

export interface SetVisualsEvent extends SpriteEventBase {
  type: 'setVisuals'
  // Visual tuning parameters (optional: only apply provided ones)
  energyScale?: number // e.g., 1.0 normal, <1 calmer
  tempoBreatheSec?: number // e.g., 3.6 normal, higher is slower
  tempoShimmerSec?: number // e.g., 11 normal
  brightnessScale?: number // e.g., 1.0 normal, <1 dimmer
  saturationScale?: number // e.g., 1.0 normal, <1 desaturated
}

export interface AcknowledgeEvent extends SpriteEventBase {
  type: 'ack'
}

export type SpriteBusEvent = SetBaseEvent | SetOverlayEvent | SetToneEvent | SetVisualsEvent | AcknowledgeEvent

export type SpriteBusSubscriber = (evt: SpriteBusEvent) => void

// Minimal singleton bus (no cooldowns yet — TODO in implementation)
import { APP_CONFIG } from '../config'

async function postTelemetry(payload: any) {
  try {
    if (!APP_CONFIG?.apiUrl) return
    await fetch(`${APP_CONFIG.apiUrl}/sprite/telemetry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
  } catch {
    // ignore network errors in client
  }
}

class SpriteBus {
  private subs: Set<SpriteBusSubscriber> = new Set()
  // Cooldown + dedupe
  private lastFired: Record<string, number> = {}
  private lastPayload: Record<string, string> = {}
  private lastAlertAt?: number
  private defaultCooldownMs = {
    alert: 3000,
    celebrate: 1200,
    speaking: 600,
    notifying: 600,
  } as const
  private overlayPriority: Record<SpriteOverlay, number> = {
    alert: 3,
    celebrate: 2,
    speaking: 1,
    notifying: 1,
  }
  private activeOverlay?: { kind: SpriteOverlay; until: number }

  subscribe(fn: SpriteBusSubscriber) {
    this.subs.add(fn)
    return () => this.subs.delete(fn)
  }

  emit(evt: SpriteBusEvent) {
    // Apply cooldown/dedupe for overlays (alert/celebrate/speaking/notifying)
    if (evt.type === 'setOverlay') {
      const ov = evt.overlay
      if (ov) {
        const source = evt.source || 'global'
        const key = `ov:${ov}:${source}`
        const now = evt.ts || Date.now()
        // Priority gate: allow only if higher than current active overlay (and active not expired)
        if (this.activeOverlay && now < this.activeOverlay.until) {
          const currentPrio = this.overlayPriority[this.activeOverlay.kind]
          const incomingPrio = this.overlayPriority[ov]
          if (incomingPrio <= currentPrio) {
            return
          }
        }
        const cooldown = this.defaultCooldownMs[ov] ?? 0
        const last = this.lastFired[key] || 0
        if (cooldown && now - last < cooldown) {
          // Dedupe identical overlay payload within cooldown window
          return
        }
        this.lastFired[key] = now
        // Track last payload for potential future dedupe of message-based alerts
        const payloadSig = `${ov}|${evt.importance || ''}`
        this.lastPayload[key] = payloadSig
        // Normalize default autoClearMs if not specified
        if (!evt.autoClearMs) {
          // slightly longer for celebrate
          ;(evt as SetOverlayEvent).autoClearMs = ov === 'celebrate' ? 1200 : 900
        }
        // Mark active overlay window
        const duration = (evt.autoClearMs as number) || (ov === 'celebrate' ? 1200 : 900)
        this.activeOverlay = { kind: ov, until: now + duration }
        if (ov === 'alert') {
          this.lastAlertAt = now
        }
      }
      else {
        // explicit clear
        this.activeOverlay = undefined
      }
    }
    if (evt.type === 'ack') {
      const now = evt.ts || Date.now()
      if (this.lastAlertAt) {
        const latency = now - this.lastAlertAt
        // Telemetry stub: log ack latency
        console.log(`[sprite.telemetry] ack_latency_ms=${latency}`)
        postTelemetry({ type: 'ack_latency', value_ms: latency, ts: now })
        this.lastAlertAt = undefined
      }
    }
    for (const fn of this.subs) fn(evt)
  }

  // Convenience APIs (align with planning.md)
  setBase(base: SpriteBaseState, source?: string) {
    this.emit({ type: 'setBase', base, source, ts: Date.now() })
  }
  setOverlay(overlay: SpriteOverlay | undefined, opts?: { source?: string; importance?: 'low' | 'medium' | 'high'; autoClearMs?: number }) {
    this.emit({ type: 'setOverlay', overlay, importance: opts?.importance, autoClearMs: opts?.autoClearMs, source: opts?.source, ts: Date.now() })
  }
  alert(opts?: { source?: string; importance?: 'low' | 'medium' | 'high'; autoClearMs?: number }) {
    this.setOverlay('alert', opts)
  }
  celebrate(opts?: { source?: string; autoClearMs?: number }) {
    this.setOverlay('celebrate', { ...opts })
  }
  setTone(tone: SpriteTone | undefined, source?: string) {
    this.emit({ type: 'setTone', tone, source, ts: Date.now() })
  }
  acknowledge(source?: string) {
    this.emit({ type: 'ack', source, ts: Date.now() })
  }
  setVisuals(params: { energyScale?: number; tempoBreatheSec?: number; tempoShimmerSec?: number; brightnessScale?: number; saturationScale?: number }, source?: string) {
    this.emit({ type: 'setVisuals', ...params, source, ts: Date.now() })
  }
}

export const spriteBus = new SpriteBus()

// TODO (Phase 1):
// - Add per-source cooldowns (e.g., alert:vuln 5s).
// - Deduplicate identical alert bursts.
// - Optional queue/priority for overlays.

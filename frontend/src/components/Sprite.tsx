import React, { useRef, useEffect, useImperativeHandle, forwardRef, useState } from 'react'
import './sprite.css'
// TODO (sprite integration):
// - Integrate spriteBus + useSpriteState for authoritative base/overlay/tone
//   state instead of local class toggles.
// - Mount <SpriteHUD /> anchored to this element; toggle on click.
// - Add aria-live region to politely announce key state changes.
// - Respect prefers-reduced-motion by simplifying animation classes.
//
// Planned imports (Phase 1): now active
import { useSpriteState } from '../hooks/useSpriteState'
import { spriteBus } from '../state/spriteBus'
import SpriteHUD from './SpriteHUD'
import { APP_CONFIG } from '../config'
import { getCalmMode } from '../utils/prefs'
import SpriteHaloCanvas from './SpriteHaloCanvas'

type SpriteState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'notifying'
type PersonalityMode = 'coach' | 'analyst' | 'companion' | 'guardian' | 'concierge' | 'librarian'

export interface SpriteHandle {
  setState: (state: SpriteState) => void
  setMode: (mode: PersonalityMode) => void
  getMode: () => PersonalityMode
  closeHUD?: () => void
  toggleHUD?: () => void
  notify: (message: string, options?: {
    showToast?: boolean
    keepBadge?: boolean
    autoHide?: number
    importance?: 'low' | 'medium' | 'high'
    onReply?: () => void
    onOpen?: () => void
  }) => void
  clearBadge: () => void
  pulse: (intensity?: 'subtle' | 'normal' | 'strong') => void
}

interface SpriteProps {
  className?: string
  onNavigate?: (view: string) => void
}

const Sprite = forwardRef<SpriteHandle, SpriteProps>(({ className = '', onNavigate }, ref) => {
  const rootRef = useRef<HTMLDivElement>(null)
  const toastRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)
  const badgeRef = useRef<HTMLDivElement>(null)
  const [currentState, setCurrentState] = useState<SpriteState>('idle')
  const [currentMode, setCurrentMode] = useState<PersonalityMode>('companion')
  const [toastVisible, setToastVisible] = useState(false)
  const [currentToastOptions, setCurrentToastOptions] = useState<any>({})
  const [notificationText, setNotificationText] = useState<string>('')
  const [showTooltip, setShowTooltip] = useState(false)
  const [notificationImportance, setNotificationImportance] = useState<'low' | 'medium' | 'high'>('medium')
  // HUD open state
  const [hudOpen, setHudOpen] = useState(false)
  // Sprite state (base/overlay/tone) from centralized bus
  const { effective, acknowledge, visuals } = useSpriteState()
  const [isCalm, setIsCalm] = useState<boolean>(false)

  useEffect(() => {
    setIsCalm(Boolean(APP_CONFIG.flags?.calmMode) || getCalmMode())
  }, [])

  // Reflect effective state in DOM classes (non-breaking; keeps imperative methods working)
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    // Base
    el.classList.remove('idle', 'listening', 'thinking')
    el.classList.add(effective.base)
    // Overlays
    el.classList.remove('overlay-alert', 'overlay-celebrate', 'speaking', 'notifying')
    if (effective.overlay === 'alert') el.classList.add('overlay-alert')
    if (effective.overlay === 'celebrate') el.classList.add('overlay-celebrate')
    if (effective.overlay === 'speaking') el.classList.add('speaking')
    if (effective.overlay === 'notifying') el.classList.add('notifying')
    // Tone
    el.classList.remove('tone-neutral', 'tone-focused', 'tone-playful', 'tone-serious')
    if (effective.tone) el.classList.add(`tone-${effective.tone}`)
  }, [effective])

  // Apply visual tuning to CSS variables
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    el.style.setProperty('--energy-scale', String(visuals.energyScale ?? 1))
    el.style.setProperty('--tempo-breathe', `${visuals.tempoBreatheSec ?? 3.6}s`)
    el.style.setProperty('--tempo-shimmer', `${visuals.tempoShimmerSec ?? 11}s`)
    el.style.setProperty('--brightness-scale', String(visuals.brightnessScale ?? 1))
    el.style.setProperty('--saturation-scale', String(visuals.saturationScale ?? 1))
  }, [visuals.energyScale, visuals.tempoBreatheSec, visuals.tempoShimmerSec, visuals.brightnessScale, visuals.saturationScale])
  
  let timer: number
  let pulseTimer: number

  const setState = (state: SpriteState) => {
    setCurrentState(state)
    const el = rootRef.current
    if (!el) return
    
    // Clear all state classes
    el.classList.remove('idle', 'listening', 'thinking', 'speaking', 'notifying', 'show-toast')
    // Add the new state
    el.classList.add(state)
    // TODO (spriteBus): emit state transitions via spriteBus.setBase(...)
    // Example mapping:
    // if (state === 'idle' || state === 'listening' || state === 'thinking') spriteBus.setBase(state)
    // if (state === 'speaking') spriteBus.setOverlay('speaking', { autoClearMs: 900 })
  }

  const setMode = (mode: PersonalityMode) => {
    setCurrentMode(mode)
    const el = rootRef.current
    if (!el) return
    
    // Clear all mode classes
    el.classList.remove('mode-coach', 'mode-analyst', 'mode-companion', 'mode-guardian', 'mode-concierge', 'mode-librarian')
    // Add the new mode
    el.classList.add(`mode-${mode}`)
  }

  const getMode = (): PersonalityMode => currentMode

  const pulse = (intensity: 'subtle' | 'normal' | 'strong' = 'normal') => {
    const el = rootRef.current
    if (!el) return

    // Clear any existing pulse
    clearTimeout(pulseTimer)
    el.classList.remove('pulse-subtle', 'pulse-normal', 'pulse-strong')
    
    // Add pulse class
    el.classList.add(`pulse-${intensity}`)
    
    // Remove after animation
    pulseTimer = window.setTimeout(() => {
      el.classList.remove(`pulse-${intensity}`)
    }, 600)
  }

  const notify: SpriteHandle['notify'] = (
    message, 
    {
      showToast = true,
      keepBadge = true,
      autoHide = 6500,
      importance = 'medium',
      onReply,
      onOpen
    } = {}
  ) => {
    const el = rootRef.current
    const toast = toastRef.current
    const text = textRef.current
    const badge = badgeRef.current
    
    if (!el || !toast || !text || !badge) return

    text.textContent = message
    setNotificationText(message)
    setNotificationImportance(importance)
    setCurrentToastOptions({ onReply, onOpen })
    
    // Add importance-based animations
    if (importance === 'high') {
      el.classList.add('notification-high')
      setTimeout(() => el.classList.remove('notification-high'), 2000)
    } else if (importance === 'medium') {
      el.classList.add('notification-medium')
      setTimeout(() => el.classList.remove('notification-medium'), 1500)
    }
    
    setState('notifying')
    // Bridge notify to bus alert (cooldown handled in bus)
    spriteBus.alert({ source: 'notification', importance, autoClearMs: importance === 'high' ? 1200 : 900 })
    
    if (showToast) {
      toast.hidden = false
      setToastVisible(true)
      requestAnimationFrame(() => {
        el.classList.add('show-toast')
      })
      
      clearTimeout(timer)
      if (autoHide) {
        timer = window.setTimeout(() => {
          el.classList.remove('show-toast')
          setTimeout(() => {
            toast.hidden = true
            setToastVisible(false)
          }, 200)
          if (keepBadge) badge.hidden = false
          setState('idle')
        }, autoHide)
      }
    } else {
      badge.hidden = !keepBadge
      setState('idle')
    }
  }

  const clearBadge = () => {
    if (badgeRef.current) {
      badgeRef.current.hidden = true
    }
    setNotificationText('')
    setShowTooltip(false)
  }

  useImperativeHandle(ref, () => ({
    setState,
    setMode,
    getMode,
    closeHUD: () => setHudOpen(false),
    toggleHUD: () => setHudOpen(v => !v),
    notify,
    clearBadge,
    pulse
  }), [])

  // Handle sprite click
  const handleSpriteClick = () => {
    const badge = badgeRef.current
    const el = rootRef.current
    const toast = toastRef.current
    
    // If there's a visible badge, navigate to insights
    const hasBadge = badge && !badge.hidden
    
    if (badge) badge.hidden = true
    if (el) {
      el.classList.remove('show-toast')
      setToastVisible(false)
    }
    if (toast) toast.hidden = true
    
    setState('speaking')
    setTimeout(() => setState('idle'), 900)
    // Toggle HUD and acknowledge overlays/tone bias
    setHudOpen(v => !v)
    spriteBus.acknowledge('sprite:click')
    acknowledge('sprite:click')
    
    // Navigate to insights if there was a badge
    if (hasBadge && onNavigate) {
      setTimeout(() => onNavigate('insights'), 500)
    }
  }

  // Handle toast button clicks
  const handleReply = () => {
    const el = rootRef.current
    const toast = toastRef.current
    const badge = badgeRef.current
    
    if (currentToastOptions.onReply) {
      currentToastOptions.onReply()
    }
    
    if (el) el.classList.remove('show-toast')
    if (toast) toast.hidden = true
    if (badge) badge.hidden = true
    setToastVisible(false)
    setState('idle')
  }

  const handleOpen = () => {
    const el = rootRef.current
    const toast = toastRef.current
    const badge = badgeRef.current
    
    if (currentToastOptions.onOpen) {
      currentToastOptions.onOpen()
    }
    
    if (el) el.classList.remove('show-toast')
    if (toast) toast.hidden = true
    if (badge) badge.hidden = true
    setToastVisible(false)
    setState('idle')
  }

  return (
    <div 
      id="sara-sprite" 
      ref={rootRef}
      className={`sprite idle mode-${currentMode} ${className}`}
      aria-label="Sara"
      onClick={handleSpriteClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleSpriteClick()
        }
        if (e.key === 'Escape') {
          setHudOpen(false)
        }
      }}
      onMouseEnter={() => {
        if (notificationText && !badgeRef.current?.hidden) {
          setShowTooltip(true)
        }
      }}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {/* Enhanced visuals halo (feature-flagged) */}
      {APP_CONFIG.flags?.enhancedVisuals && (
        <SpriteHaloCanvas energy={visuals.energyScale ?? 1} />
      )}
      <div className="halo"></div>
      <div className="core"></div>
      <div className="ring"></div>
      <div className="badge" ref={badgeRef} hidden></div>

      {/* Hover tooltip: show notifications and Calm Mode hint */}
      {showTooltip && (notificationText || isCalm) && (
        <div className="tooltip">
          {notificationText || (isCalm ? 'Calm mode on' : '')}
        </div>
      )}

      <div className="toast" ref={toastRef} hidden>
        <span className="toast-text" ref={textRef}>...</span>
        <button 
          className="toast-btn reply"
          onClick={(e) => {
            e.stopPropagation()
            handleReply()
          }}
        >
          Reply
        </button>
        <button 
          className="toast-btn open"
          onClick={(e) => {
            e.stopPropagation()
            handleOpen()
          }}
        >
          Open
        </button>
      </div>
      {/* Polite live region for state announcements */}
      <span className="sr-only" aria-live="polite">
        {currentState === 'thinking' ? 'Sara is analyzing' :
         currentState === 'listening' ? 'Awaiting input' :
         currentState === 'notifying' ? 'New alert' : ''}
      </span>
      {/* Mini HUD anchored near the sprite */}
      <SpriteHUD open={hudOpen} onClose={() => setHudOpen(false)} onNavigate={onNavigate} />
    </div>
  )
})

Sprite.displayName = 'Sprite'

export default Sprite

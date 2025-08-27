import React, { useRef, useEffect, useImperativeHandle, forwardRef, useState } from 'react'
import './sprite.css'

type SpriteState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'notifying'
type PersonalityMode = 'coach' | 'analyst' | 'companion' | 'guardian' | 'concierge' | 'librarian'

export interface SpriteHandle {
  setState: (state: SpriteState) => void
  setMode: (mode: PersonalityMode) => void
  getMode: () => PersonalityMode
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
      }}
      onMouseEnter={() => {
        if (notificationText && !badgeRef.current?.hidden) {
          setShowTooltip(true)
        }
      }}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <div className="halo"></div>
      <div className="core"></div>
      <div className="ring"></div>
      <div className="badge" ref={badgeRef} hidden></div>

      {/* Hover tooltip */}
      {showTooltip && notificationText && (
        <div className="tooltip">
          {notificationText}
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
    </div>
  )
})

Sprite.displayName = 'Sprite'

export default Sprite
import React, { useRef, useEffect, useImperativeHandle, forwardRef, useState } from 'react'
import './sprite.css'

type SpriteState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'notifying'

export interface SpriteHandle {
  setState: (state: SpriteState) => void
  notify: (message: string, options?: {
    showToast?: boolean
    keepBadge?: boolean
    autoHide?: number
    onReply?: () => void
    onOpen?: () => void
  }) => void
  clearBadge: () => void
}

interface SpriteProps {
  className?: string
}

const Sprite = forwardRef<SpriteHandle, SpriteProps>(({ className = '' }, ref) => {
  const rootRef = useRef<HTMLDivElement>(null)
  const toastRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)
  const badgeRef = useRef<HTMLDivElement>(null)
  const [currentState, setCurrentState] = useState<SpriteState>('idle')
  const [toastVisible, setToastVisible] = useState(false)
  const [currentToastOptions, setCurrentToastOptions] = useState<any>({})
  
  let timer: number

  const setState = (state: SpriteState) => {
    setCurrentState(state)
    const el = rootRef.current
    if (!el) return
    
    // Clear all state classes
    el.classList.remove('idle', 'listening', 'thinking', 'speaking', 'notifying', 'show-toast')
    // Add the new state
    el.classList.add(state)
  }

  const notify: SpriteHandle['notify'] = (
    message, 
    {
      showToast = true,
      keepBadge = true,
      autoHide = 6500,
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
    setCurrentToastOptions({ onReply, onOpen })
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
  }

  useImperativeHandle(ref, () => ({
    setState,
    notify,
    clearBadge
  }), [])

  // Handle sprite click
  const handleSpriteClick = () => {
    const badge = badgeRef.current
    const el = rootRef.current
    const toast = toastRef.current
    
    if (badge) badge.hidden = true
    if (el) {
      el.classList.remove('show-toast')
      setToastVisible(false)
    }
    if (toast) toast.hidden = true
    
    setState('speaking')
    setTimeout(() => setState('idle'), 900)
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
      className={`sprite idle ${className}`}
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
    >
      <div className="halo"></div>
      <div className="core"></div>
      <div className="ring"></div>
      <div className="badge" ref={badgeRef} hidden></div>

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
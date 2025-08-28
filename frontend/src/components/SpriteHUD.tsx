// SpriteHUD (stub)
// Purpose: Compact, anchored mini-HUD that opens from the sprite.
// Shows quick status (Now / You / Brain / Threat) and recent insights.
//
// Implementation status: scaffold only. Replace placeholders with
// real data hooks and subcomponents during Phase 1.

import React, { useEffect, useRef } from 'react'
import { spriteBus } from '../state/spriteBus'

export interface SpriteHUDProps {
  open: boolean
  anchorId?: string // default: 'sara-sprite'
  onClose?: () => void
  onNavigate?: (view: string) => void // e.g., 'chat', 'habits', 'vulnerability-watch', 'insights'
}

const SpriteHUD: React.FC<SpriteHUDProps> = ({ open, anchorId = 'sara-sprite', onClose, onNavigate }) => {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    // Focus management: focus container on open
    containerRef.current?.focus()

    const onDocMouseDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (containerRef.current && !containerRef.current.contains(target)) {
        onClose?.()
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose?.()
        return
      }
      if (e.key === 'Tab') {
        // Simple focus trap: keep focus within HUD
        const root = containerRef.current
        if (!root) return
        const focusables = Array.from(root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
        )).filter(el => !el.hasAttribute('disabled') && !el.getAttribute('aria-hidden'))
        if (focusables.length === 0) {
          e.preventDefault()
          return
        }
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        const active = document.activeElement as HTMLElement
        const shift = e.shiftKey
        if (shift && active === first) {
          e.preventDefault()
          last.focus()
        } else if (!shift && active === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('mousedown', onDocMouseDown, true)
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown, true)
      document.removeEventListener('keydown', onKeyDown, true)
      // Return focus to sprite anchor if present
      const anchor = document.getElementById(anchorId)
      if (anchor) {
        ;(anchor as HTMLElement).focus()
      }
    }
  }, [open, onClose])

  if (!open) return null

  // NOTE: Positioning — in Phase 1, position relative to the sprite
  // via fixed offsets. Later, compute from anchor bounding client rect.
  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby="sprite-hud-title"
      tabIndex={-1}
      className="fixed z-[1100] right-[96px] bottom-[24px] w-[320px] max-w-[90vw] rounded-xl bg-slate-900/95 text-slate-100 shadow-xl border border-white/10 backdrop-blur-md"
      data-anchor={anchorId}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <h2 id="sprite-hud-title" className="text-sm font-semibold tracking-wide text-slate-200">Sara — Quick HUD</h2>
        <button className="text-slate-400 hover:text-slate-200" onClick={onClose} aria-label="Close HUD">×</button>
      </div>

      <div className="p-3 grid grid-cols-2 gap-2">
        {/* Now */}
        <button className="rounded-lg bg-slate-800/70 hover:bg-slate-800 p-3 text-left" onClick={() => onNavigate?.('chat')}>
          <div className="text-xs text-slate-400">Now</div>
          <div className="text-sm">Open Chat</div>
        </button>

        {/* You (Habits) */}
        <button className="rounded-lg bg-slate-800/70 hover:bg-slate-800 p-3 text-left" onClick={() => onNavigate?.('habits')}>
          <div className="text-xs text-slate-400">You</div>
          <div className="text-sm">Habits & Streak</div>
        </button>

        {/* Brain (Insights) */}
        <button className="rounded-lg bg-slate-800/70 hover:bg-slate-800 p-3 text-left" onClick={() => onNavigate?.('insights')}>
          <div className="text-xs text-slate-400">Brain</div>
          <div className="text-sm">Insights</div>
        </button>

        {/* Threat (Vuln) */}
        <button className="rounded-lg bg-slate-800/70 hover:bg-slate-800 p-3 text-left" onClick={() => {
          spriteBus.setTone(undefined, 'vuln:ack')
          onNavigate?.('vulnerability-watch')
          onClose?.()
        }}>
          <div className="text-xs text-slate-400">Threat</div>
          <div className="text-sm">Vulnerability Watch</div>
        </button>
      </div>

      <div className="px-4 pb-4">
        <div className="text-xs uppercase tracking-wider text-slate-400 mb-2">Recent</div>
        <div className="text-sm text-slate-300">
          {/* TODO: render most recent autonomous insight or alert summary */}
          <em>Coming soon: latest insight or alert summary here.</em>
        </div>
      </div>
    </div>
  )
}

export default SpriteHUD

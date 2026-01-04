import { useCallback } from 'react'
import type { Mode, VoiceState } from '../App'

interface FloatingCircleProps {
  state: VoiceState
  mode: Mode
  chatOpen?: boolean
  onClick: () => void
  onRightClick: () => void
}

export default function FloatingCircle({ state, mode, chatOpen, onClick, onRightClick }: FloatingCircleProps) {
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    onRightClick()
  }, [onRightClick])

  // Get animation class based on state
  const getAnimationClass = () => {
    switch (state) {
      case 'listening':
        return 'animate-listening'
      case 'processing':
        return 'animate-spin'
      case 'speaking':
        return 'animate-speaking'
      default:
        return 'animate-glow'
    }
  }

  // Get color scheme based on state
  const getColorClass = () => {
    switch (state) {
      case 'listening':
        return 'bg-gradient-to-br from-red-500 to-pink-500 shadow-red-500/50'
      case 'processing':
        return 'bg-gradient-to-br from-yellow-500 to-orange-500 shadow-yellow-500/50'
      case 'speaking':
        return 'bg-gradient-to-br from-green-500 to-emerald-500 shadow-green-500/50'
      default:
        return 'bg-gradient-to-br from-indigo-500 to-purple-600 shadow-indigo-500/50'
    }
  }

  // Get mode indicator
  const getModeIcon = () => {
    switch (mode) {
      case 'wakeWord':
        return (
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15a.998.998 0 0 0-.98-.85c-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08a6.993 6.993 0 0 0 5.91-5.78c.1-.6-.39-1.14-1-1.14z" />
          </svg>
        )
      case 'pushToTalk':
        return (
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          </svg>
        )
      case 'silent':
        return (
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z" />
          </svg>
        )
    }
  }

  return (
    <div className="w-full h-full flex items-center justify-center">
      <button
        onClick={onClick}
        onContextMenu={handleContextMenu}
        className={`
          no-drag
          relative
          w-16 h-16
          rounded-full
          ${getColorClass()}
          shadow-lg
          cursor-pointer
          transition-all duration-300
          hover:scale-110
          active:scale-95
          ${getAnimationClass()}
        `}
      >
        {/* Inner glow effect */}
        <div className="absolute inset-2 rounded-full bg-white/20 backdrop-blur-sm" />

        {/* Sara icon/initial */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-white text-2xl font-bold select-none">S</span>
        </div>

        {/* Mode indicator */}
        <div className="absolute -bottom-1 -right-1 bg-gray-900 rounded-full p-1 text-white/80">
          {getModeIcon()}
        </div>

        {/* State indicator ring */}
        {state === 'listening' && (
          <div className="absolute -inset-2 rounded-full border-2 border-red-400 animate-ping opacity-75" />
        )}
        {state === 'speaking' && (
          <div className="absolute -inset-1 rounded-full border-2 border-green-400 animate-pulse" />
        )}
      </button>
    </div>
  )
}

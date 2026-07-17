import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '../services/api'

interface FloatingCircleProps {
  onClick: () => void
  onRightClick: () => void
}

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'attention' | 'alert'

const ORB_COLORS: Record<OrbState, { primary: string; secondary: string; tertiary: string }> = {
  idle: { primary: '255, 130, 200', secondary: '200, 100, 255', tertiary: '150, 80, 220' }, // pink/purple (default)
  listening: { primary: '110, 231, 255', secondary: '56, 189, 248', tertiary: '14, 165, 233' }, // cyan
  thinking: { primary: '253, 224, 71', secondary: '250, 204, 21', tertiary: '202, 138, 4' }, // amber
  speaking: { primary: '110, 231, 183', secondary: '52, 211, 153', tertiary: '5, 150, 105' }, // emerald
  attention: { primary: '45, 212, 191', secondary: '20, 184, 166', tertiary: '15, 118, 110' }, // teal
  alert: { primary: '252, 165, 165', secondary: '248, 113, 113', tertiary: '220, 38, 38' }, // red
}

class SmokeRing {
  private ctx: CanvasRenderingContext2D
  private width: number
  private height: number
  private centerX: number
  private centerY: number
  private time: number
  private baseRadius: number
  private ringThickness: number
  private segments: number
  private animationId: number | null = null
  private state: OrbState = 'idle'

  constructor(canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext('2d')!

    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    this.ctx.scale(dpr, dpr)
    this.width = rect.width
    this.height = rect.height

    this.centerX = this.width / 2
    this.centerY = this.height / 2
    this.time = 0

    // Ring parameters - sized for 100x100 container
    this.baseRadius = 30
    this.ringThickness = 12
    this.segments = 80
  }

  setState(state: OrbState) {
    this.state = state
  }

  // Smooth noise function
  private noise(x: number, seed: number = 0): number {
    const n = Math.sin(x * 1.2 + seed) * 0.5 +
              Math.sin(x * 2.3 + seed * 1.5) * 0.3 +
              Math.sin(x * 4.1 + seed * 0.7) * 0.2
    return n
  }

  private getColors(): { primary: string; secondary: string; tertiary: string } {
    return ORB_COLORS[this.state] || ORB_COLORS.idle
  }

  // Thinking/alert pulse a bit faster and tighter than the idle drift.
  private speedMultiplier(): number {
    if (this.state === 'thinking') return 2.2
    if (this.state === 'alert') return 1.8
    if (this.state === 'listening' || this.state === 'speaking') return 1.4
    return 1
  }

  private draw() {
    this.ctx.clearRect(0, 0, this.width, this.height)

    const time = this.time * 0.0005 * this.speedMultiplier()

    // Draw multiple smoke layers for depth
    for (let layer = 0; layer < 5; layer++) {
      const layerOffset = layer * 0.3
      const layerAlpha = 0.15 - layer * 0.02
      const layerThickness = this.ringThickness + layer * 4

      this.drawSmokeLayer(time, layerOffset, layerAlpha, layerThickness, layer)
    }
  }

  private drawSmokeLayer(time: number, offset: number, alpha: number, thickness: number, layerIndex: number) {
    const colors = this.getColors()

    this.ctx.beginPath()

    for (let i = 0; i <= this.segments; i++) {
      const angle = (i / this.segments) * Math.PI * 2

      // Rotating offset
      const rotatedAngle = angle + time * (0.15 + layerIndex * 0.03)

      // Radius variation - organic wobble
      const radiusNoise =
        this.noise(rotatedAngle * 3 + time * 0.6 + offset, layerIndex) * 8 +
        this.noise(rotatedAngle * 5 + time * 0.9 + offset, layerIndex + 10) * 4 +
        Math.sin(rotatedAngle * 2 + time * 1.2) * 3

      // Vertical displacement for 3D torus effect
      const verticalNoise =
        this.noise(rotatedAngle * 2 + time * 0.4, layerIndex + 5) * 10 +
        Math.sin(rotatedAngle * 3 + time * 0.7) * 5

      const radius = this.baseRadius + radiusNoise

      const x = this.centerX + Math.cos(angle) * radius
      const y = this.centerY + Math.sin(angle) * radius * 0.5 + verticalNoise

      if (i === 0) {
        this.ctx.moveTo(x, y)
      } else {
        this.ctx.lineTo(x, y)
      }
    }

    this.ctx.closePath()

    // Gradient stroke for smoke effect
    const gradient = this.ctx.createRadialGradient(
      this.centerX, this.centerY, this.baseRadius - 15,
      this.centerX, this.centerY, this.baseRadius + 25
    )
    gradient.addColorStop(0, `rgba(${colors.primary}, ${alpha})`)
    gradient.addColorStop(0.5, `rgba(${colors.secondary}, ${alpha * 0.8})`)
    gradient.addColorStop(1, `rgba(${colors.tertiary}, ${alpha * 0.5})`)

    this.ctx.strokeStyle = gradient
    this.ctx.lineWidth = thickness
    this.ctx.lineCap = 'round'
    this.ctx.lineJoin = 'round'
    this.ctx.stroke()
  }

  start() {
    const animate = () => {
      this.time += 16
      this.draw()
      this.animationId = requestAnimationFrame(animate)
    }
    animate()
  }

  stop() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId)
      this.animationId = null
    }
  }
}

interface FlyoutData {
  timers: Array<{ id: string; title: string; remaining_seconds: number }>
  nextEvent: { title: string; start_time: string; all_day: boolean } | null
  statusLine: string | null
  listening: boolean
}

function FlyoutPanel({ attentionCount, onOpenChat }: { attentionCount: number; onOpenChat: () => void }) {
  const [data, setData] = useState<FlyoutData | null>(null)
  const [muteBusy, setMuteBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      apiClient.getActiveTimers(),
      apiClient.getNextCalendarEvent(),
      apiClient.getSaraStatusLine(),
      apiClient.getVoiceListening(),
    ]).then(([timers, nextEvent, statusLine, listening]) => {
      if (!cancelled) setData({ timers, nextEvent, statusLine, listening })
    })
    return () => {
      cancelled = true
    }
  }, [])

  const toggleMute = useCallback(async () => {
    if (!data) return
    setMuteBusy(true)
    const next = !data.listening
    const confirmed = await apiClient.setVoiceListening(next)
    setData((d) => (d ? { ...d, listening: confirmed } : d))
    setMuteBusy(false)
  }, [data])

  return (
    <div
      className="no-drag absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-64 rounded-xl bg-gray-900/95 border border-gray-700 shadow-2xl p-3 text-xs text-gray-200 backdrop-blur-sm"
      onClick={(e) => e.stopPropagation()}
    >
      {!data ? (
        <p className="text-gray-500 animate-pulse">Loading…</p>
      ) : (
        <>
          <p className="text-gray-300 mb-2 leading-snug">
            {data.statusLine || "Nothing on Sara's mind right now."}
          </p>
          <div
            className={`flex items-center justify-between text-gray-400 mb-1 ${attentionCount > 0 ? 'cursor-pointer hover:text-gray-200' : ''}`}
            onClick={() => {
              if (attentionCount > 0) window.electronAPI?.openOverlay('inbox', {})
            }}
          >
            <span>Attention</span>
            <span className={attentionCount > 0 ? 'text-teal-400 font-semibold' : ''}>
              {attentionCount}
            </span>
          </div>
          {data.timers.length > 0 && (
            <div className="flex items-center justify-between text-gray-400 mb-1">
              <span>Timer</span>
              <span>{data.timers[0].title} — {Math.ceil(data.timers[0].remaining_seconds / 60)}m</span>
            </div>
          )}
          {data.nextEvent && (
            <div className="flex items-center justify-between text-gray-400 mb-2">
              <span>Next</span>
              <span className="truncate max-w-[140px]">
                {data.nextEvent.all_day ? 'All day' : new Date(data.nextEvent.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} {data.nextEvent.title}
              </span>
            </div>
          )}
          <div className="grid grid-cols-2 gap-1 mt-2 pt-2 border-t border-gray-800">
            <button
              className="rounded-lg bg-gray-800 hover:bg-gray-700 px-2 py-1.5 text-left"
              onClick={() => window.electronAPI?.openQuickNote()}
            >
              New note
            </button>
            <button
              className="rounded-lg bg-gray-800 hover:bg-gray-700 px-2 py-1.5 text-left"
              onClick={() => window.electronAPI?.requestVoiceNote()}
            >
              Record voice note
            </button>
            <button
              className="rounded-lg bg-gray-800 hover:bg-gray-700 px-2 py-1.5 text-left"
              onClick={() => window.electronAPI?.requestScreenshotAndAsk()}
            >
              Screenshot &amp; ask
            </button>
            <button
              className="rounded-lg bg-gray-800 hover:bg-gray-700 px-2 py-1.5 text-left"
              disabled={muteBusy}
              onClick={toggleMute}
            >
              {data.listening ? 'Mute voice' : 'Unmute voice'}
            </button>
            <button
              className="col-span-2 rounded-lg bg-gray-800 hover:bg-gray-700 px-2 py-1.5 text-left"
              onClick={onOpenChat}
            >
              Open chat
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default function FloatingCircle({ onClick, onRightClick }: FloatingCircleProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const smokeRingRef = useRef<SmokeRing | null>(null)
  const [attentionCount, setAttentionCount] = useState(0)
  const [orbState, setOrbState] = useState<OrbState>('idle')
  const [showFlyout, setShowFlyout] = useState(false)
  const [screenshotsEnabled, setScreenshotsEnabled] = useState(true)

  // Fetch attention count periodically (via the app's configured backend,
  // not a hardcoded dev URL — this previously always hit 10.185.1.180:8000
  // regardless of the user's configured API URL).
  useEffect(() => {
    const fetchCount = async () => {
      const count = await apiClient.getAttentionCount()
      setAttentionCount(count)
    }
    fetchCount()
    const interval = setInterval(fetchCount, 30000)
    return () => clearInterval(interval)
  }, [])

  // Orb state driven by backend/sidecar realtime events (A1/A3).
  useEffect(() => {
    window.electronAPI?.onVoiceState((state) => {
      if (state === 'listening' || state === 'thinking' || state === 'speaking' || state === 'idle') {
        setOrbState(state as OrbState)
      }
    })
    window.electronAPI?.onBackendEvent((event, data) => {
      if (event === 'hud_state' && data?.state) {
        setOrbState(data.state as OrbState)
      }
      if (event === 'attention_count' && typeof data?.count === 'number') {
        setAttentionCount(data.count)
      }
    })
    // Voice-note mic level (A4): show 'listening' while recording, drop
    // back to idle the moment the level meter reports silence/stopped.
    window.electronAPI?.onVoiceNoteLevel((level) => {
      setOrbState(level > 0 ? 'listening' : 'idle')
    })
    // Camera-off badge (A5) — be honest about whether ambient screenshots
    // are currently on.
    window.electronAPI?.onScreenshotConfig(setScreenshotsEnabled)
  }, [])

  // Fall back to an 'attention' tint when idle and there's something unread,
  // without stomping on an active listening/thinking/speaking state.
  useEffect(() => {
    if (orbState === 'idle' && attentionCount > 0) {
      setOrbState('attention')
    } else if (orbState === 'attention' && attentionCount === 0) {
      setOrbState('idle')
    }
  }, [attentionCount]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    smokeRingRef.current?.setState(orbState)
  }, [orbState])

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    onRightClick()
  }, [onRightClick])

  const handleQuickNote = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    window.electronAPI?.openQuickNote()
  }, [])

  const handleQuickTimer = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    // Show a quick 5-minute timer
    window.electronAPI?.showTimer({ id: `quick-${Date.now()}`, name: 'Quick Timer', remainingSeconds: 300 })
  }, [])

  // Initialize smoke ring animation
  useEffect(() => {
    if (canvasRef.current && !smokeRingRef.current) {
      smokeRingRef.current = new SmokeRing(canvasRef.current)
      smokeRingRef.current.start()
    }

    return () => {
      if (smokeRingRef.current) {
        smokeRingRef.current.stop()
        smokeRingRef.current = null
      }
    }
  }, [])

  return (
    <div
      className="w-full h-full flex items-center justify-center p-2 relative"
      style={{ background: 'transparent' }}
      onMouseEnter={() => setShowFlyout(true)}
      onMouseLeave={() => setShowFlyout(false)}
    >
      {showFlyout && <FlyoutPanel attentionCount={attentionCount} onOpenChat={onClick} />}

      {/* Container: parent div is draggable (inherits from .circle-window), only buttons/canvas are no-drag */}
      <div className="flex items-center gap-4">
        {/* Quick Note button - left side */}
        <button
          onClick={handleQuickNote}
          className="no-drag w-10 h-10 rounded-full flex items-center justify-center text-white/70 hover:text-white hover:scale-110 transition-all duration-200"
          style={{
            background: 'rgba(255, 130, 200, 0.3)',
            backdropFilter: 'blur(4px)',
            border: '1px solid rgba(255, 130, 200, 0.4)'
          }}
          title="Quick Note"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
        </button>

        {/* Main smoke ring button - center */}
        <button
          onClick={onClick}
          onContextMenu={handleContextMenu}
          className="no-drag relative w-[100px] h-[100px] cursor-pointer transition-transform duration-300 hover:scale-105 active:scale-95"
          style={{ background: 'transparent' }}
        >
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full"
            style={{ width: '100px', height: '100px', background: 'transparent' }}
          />
          {/* Attention count badge — opens the inbox overlay so the count
              is never just a number with no way to see what it means. */}
          {attentionCount > 0 && (
            <div
              className="absolute -top-1 -right-1 min-w-[20px] h-5 rounded-full flex items-center justify-center text-xs font-bold text-white no-drag cursor-pointer hover:scale-110 transition-transform"
              style={{ background: 'rgba(20, 184, 166, 0.9)', padding: '0 5px' }}
              title="View what needs your attention"
              onClick={(e) => {
                e.stopPropagation()
                window.electronAPI?.openOverlay('inbox', {})
              }}
            >
              {attentionCount > 9 ? '9+' : attentionCount}
            </div>
          )}
          {/* Camera-off badge: ambient screenshots are disabled */}
          {!screenshotsEnabled && (
            <div
              className="absolute -bottom-1 -left-1 w-5 h-5 rounded-full flex items-center justify-center text-xs no-drag"
              style={{ background: 'rgba(75, 85, 99, 0.9)' }}
              title="Ambient screenshots off"
            >
              🚫
            </div>
          )}
        </button>

        {/* Quick Timer button - right side */}
        <button
          onClick={handleQuickTimer}
          className="no-drag w-10 h-10 rounded-full flex items-center justify-center text-white/70 hover:text-white hover:scale-110 transition-all duration-200"
          style={{
            background: 'rgba(200, 100, 255, 0.3)',
            backdropFilter: 'blur(4px)',
            border: '1px solid rgba(200, 100, 255, 0.4)'
          }}
          title="Quick Timer (5 min)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </button>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef } from 'react'

interface FloatingCircleProps {
  chatOpen?: boolean
  onClick: () => void
  onRightClick: () => void
}

class SmokeRing {
  private canvas: HTMLCanvasElement
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

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
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

  // Smooth noise function
  private noise(x: number, seed: number = 0): number {
    const n = Math.sin(x * 1.2 + seed) * 0.5 +
              Math.sin(x * 2.3 + seed * 1.5) * 0.3 +
              Math.sin(x * 4.1 + seed * 0.7) * 0.2
    return n
  }

  // Get colors (pink/purple theme)
  private getColors(): { primary: string; secondary: string; tertiary: string } {
    return {
      primary: '255, 130, 200',    // Pink
      secondary: '200, 100, 255',  // Purple
      tertiary: '150, 80, 220'     // Dark purple
    }
  }

  private draw() {
    this.ctx.clearRect(0, 0, this.width, this.height)

    const time = this.time * 0.0005

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

export default function FloatingCircle({ chatOpen, onClick, onRightClick }: FloatingCircleProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const smokeRingRef = useRef<SmokeRing | null>(null)

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    onRightClick()
  }, [onRightClick])

  const handleQuickNote = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    // Show a new note window
    window.electronAPI?.showNote({ id: 'new', title: 'Quick Note', content: '' })
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
    <div className="w-full h-full flex items-center justify-center p-2" style={{ background: 'transparent' }}>
      {/* Container for smoke ring and buttons - p-2 on parent creates draggable border */}
      <div className="flex items-center gap-4 no-drag">
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

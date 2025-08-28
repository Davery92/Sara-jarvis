import React, { useEffect, useRef } from 'react'

interface Props {
  energy: number
}

const SpriteHaloCanvas: React.FC<Props> = ({ energy }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>()
  const reduceMotion = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    if (reduceMotion) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let running = true
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1))

    const resize = () => {
      const parent = canvas.parentElement as HTMLElement
      const rect = parent.getBoundingClientRect()
      const w = Math.max(1, rect.width + 36) // extend beyond sprite size
      const h = Math.max(1, rect.height + 36)
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
    }
    resize()
    const onResize = () => resize()
    window.addEventListener('resize', onResize)

    // Simple particle system
    const count = 60
    type P = { x: number; y: number; r: number; a: number; vx: number; vy: number; life: number; maxLife: number }
    const parts: P[] = []
    const rand = (min: number, max: number) => min + Math.random() * (max - min)
    const reset = (p: P) => {
      const cx = canvas.width / 2
      const cy = canvas.height / 2
      const angle = Math.random() * Math.PI * 2
      const radius = rand(0, Math.min(cx, cy) * 0.35)
      p.x = cx + Math.cos(angle) * radius
      p.y = cy + Math.sin(angle) * radius
      p.r = rand(0.5, 1.8) * dpr
      p.a = rand(0.08, 0.22)
      const speed = rand(0.05, 0.25) * (0.9 + energy * 0.3)
      p.vx = Math.cos(angle + Math.PI / 2) * speed
      p.vy = Math.sin(angle + Math.PI / 2) * speed
      p.maxLife = rand(120, 360)
      p.life = p.maxLife
    }
    for (let i = 0; i < count; i++) parts.push({} as P), reset(parts[i])

    const step = () => {
      if (!running) return
      const w = canvas.width
      const h = canvas.height
      ctx.clearRect(0, 0, w, h)
      ctx.globalCompositeOperation = 'lighter'

      for (let i = 0; i < parts.length; i++) {
        const p = parts[i]
        p.x += p.vx
        p.y += p.vy
        p.life -= 1
        if (p.life <= 0) reset(p)
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(100, 170, 255, ${p.a})`
        ctx.fill()
      }

      rafRef.current = requestAnimationFrame(step)
    }
    rafRef.current = requestAnimationFrame(step)

    return () => {
      running = false
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      window.removeEventListener('resize', onResize)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduceMotion])

  if (reduceMotion) return null

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'absolute',
        inset: '-18px',
        borderRadius: '50%',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  )
}

export default SpriteHaloCanvas


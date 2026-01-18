import { useRef, useEffect, useCallback } from 'react'
import { useCanvasStore } from '../store/canvasStore'
import Window from './Window'
import { WindowContent } from './WindowContentRegistry'
import MapLayer from './maps/MapLayer'

export default function Canvas() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { transform, windows, pan, zoom, bringToFront, closeWindow, moveWindow, resizeWindow } = useCanvasStore()

  // Track if we're panning
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })

  // Global mouse handlers for middle-click panning (works everywhere)
  useEffect(() => {
    const handleGlobalMouseDown = (e: MouseEvent) => {
      // Middle mouse button for panning
      if (e.button === 1) {
        e.preventDefault()
        isPanning.current = true
        lastMouse.current = { x: e.clientX, y: e.clientY }
      }
    }

    const handleGlobalMouseMove = (e: MouseEvent) => {
      if (isPanning.current) {
        const dx = e.clientX - lastMouse.current.x
        const dy = e.clientY - lastMouse.current.y
        pan(dx, dy)
        lastMouse.current = { x: e.clientX, y: e.clientY }
      }
    }

    const handleGlobalMouseUp = (e: MouseEvent) => {
      if (e.button === 1) {
        isPanning.current = false
      }
    }

    window.addEventListener('mousedown', handleGlobalMouseDown)
    window.addEventListener('mousemove', handleGlobalMouseMove)
    window.addEventListener('mouseup', handleGlobalMouseUp)

    return () => {
      window.removeEventListener('mousedown', handleGlobalMouseDown)
      window.removeEventListener('mousemove', handleGlobalMouseMove)
      window.removeEventListener('mouseup', handleGlobalMouseUp)
    }
  }, [pan])

  // Handle wheel for pan (two-finger scroll) and zoom (pinch/ctrl+scroll)
  const handleWheel = useCallback((e: WheelEvent) => {
    // Check if the event target is inside a scrollable window content area
    const target = e.target as HTMLElement
    const scrollableParent = target.closest('.custom-scrollbar, [data-scrollable="true"]')

    if (scrollableParent) {
      // Check if the element can actually scroll
      const canScrollVertically = scrollableParent.scrollHeight > scrollableParent.clientHeight
      const canScrollHorizontally = scrollableParent.scrollWidth > scrollableParent.clientWidth

      if (canScrollVertically || canScrollHorizontally) {
        // Allow native scrolling inside windows
        return
      }
    }

    e.preventDefault()

    // Ctrl/Cmd + scroll = zoom (also handles trackpad pinch)
    if (e.ctrlKey || e.metaKey) {
      const delta = -e.deltaY * 0.01
      zoom(delta, e.clientX, e.clientY)
    } else {
      // Regular scroll = pan (two-finger drag on trackpad)
      pan(-e.deltaX, -e.deltaY)
    }
  }, [zoom, pan])



  // Add wheel listener with passive: false
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => container.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative overflow-hidden cursor-default"
      style={{
        background: 'transparent',
      }}
    >
      {/* Viewport with transform */}
      <div
        className="absolute inset-0 origin-top-left"
        style={{
          transform: `translate3d(${transform.x}px, ${transform.y}px, 0) scale(${transform.scale})`,
        }}
      >
        {/* Render maps (behind windows) */}
        <MapLayer />

        {/* Render windows */}
        {windows.map((window) => (
          <Window
            key={window.id}
            id={window.id}
            title={window.title}
            position={window.position}
            size={window.size}
            zIndex={window.zIndex}
            onClose={() => closeWindow(window.id)}
            onFocus={() => bringToFront(window.id)}
            onMove={(pos) => moveWindow(window.id, pos)}
            onResize={(size) => resizeWindow(window.id, size)}
          >
            <WindowContent type={window.type} data={window.data} windowId={window.id} />
          </Window>
        ))}
      </div>

      {/* Help text */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-canvas-muted text-xs pointer-events-none text-center">
        <div>Middle-click drag to pan | Ctrl+scroll to zoom | R reset view</div>
        <div className="mt-1 opacity-70">C chat | N notes | M maps | S search | P projects | T timers | G gym | ? help</div>
      </div>
    </div>
  )
}

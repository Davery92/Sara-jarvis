import { useRef, useEffect, useCallback } from 'react'
import { useCanvasStore } from '../store/canvasStore'
import Window from './Window'
import { WindowContent } from './WindowContentRegistry'

export default function Canvas() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { transform, windows, pan, zoom, bringToFront, closeWindow, moveWindow, resizeWindow } = useCanvasStore()

  // Track if we're panning
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })

  // Handle wheel zoom (but allow scrolling inside windows)
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

    // Otherwise, zoom the canvas
    e.preventDefault()
    const delta = -e.deltaY * 0.001
    zoom(delta, e.clientX, e.clientY)
  }, [zoom])

  // Handle mouse down for panning (middle click or space+click)
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Middle mouse button for panning
    if (e.button === 1) {
      e.preventDefault()
      isPanning.current = true
      lastMouse.current = { x: e.clientX, y: e.clientY }
    }
  }, [])

  // Handle mouse move for panning
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning.current) {
      const dx = e.clientX - lastMouse.current.x
      const dy = e.clientY - lastMouse.current.y
      pan(dx, dy)
      lastMouse.current = { x: e.clientX, y: e.clientY }
    }
  }, [pan])

  // Handle mouse up to stop panning
  const handleMouseUp = useCallback(() => {
    isPanning.current = false
  }, [])

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
      className="w-full h-full relative overflow-hidden cursor-default select-none pointer-events-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
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
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-canvas-muted text-xs pointer-events-none">
        Drop 3D models | Click to select | Drag to rotate | Shift+drag to move | Scroll to scale | Delete to remove
      </div>
    </div>
  )
}

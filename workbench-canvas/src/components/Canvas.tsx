import { useRef, useEffect, useCallback, useState } from 'react'
import { useCanvasStore } from '../store/canvasStore'
import Window from './Window'
import { WindowContent } from './WindowContentRegistry'
import type { FileViewerWindowData } from '../types'

export default function Canvas() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { transform, windows, pan, zoom, bringToFront, closeWindow, moveWindow, resizeWindow, openWindow } = useCanvasStore()
  const [isDragOver, setIsDragOver] = useState(false)

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

  // Handle drag and drop files
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    // Calculate drop position in canvas coordinates
    const rect = containerRef.current?.getBoundingClientRect()
    const dropX = rect ? (e.clientX - rect.left - transform.x) / transform.scale : 100
    const dropY = rect ? (e.clientY - rect.top - transform.y) / transform.scale : 100

    // Process each file
    files.forEach((file, index) => {
      const reader = new FileReader()
      reader.onload = (event) => {
        const content = event.target?.result as string
        const fileData: FileViewerWindowData = {
          filename: file.name,
          content,
          mimeType: file.type || undefined,
          source: 'local',
        }
        // Offset each window slightly
        openWindow('fileviewer', fileData, {
          title: file.name,
          position: { x: dropX + index * 30, y: dropY + index * 30 },
        })
      }
      reader.readAsText(file)
    })
  }, [openWindow, transform])

  // Add wheel listener with passive: false
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => container.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  // Grid pattern for visual reference
  const gridSize = 40 * transform.scale
  const gridOffsetX = transform.x % gridSize
  const gridOffsetY = transform.y % gridSize

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative overflow-hidden cursor-default select-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        background: `
          radial-gradient(circle at ${gridOffsetX}px ${gridOffsetY}px, #1a1a1a 1px, transparent 1px)
        `,
        backgroundSize: `${gridSize}px ${gridSize}px`,
        backgroundPosition: `${gridOffsetX}px ${gridOffsetY}px`,
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

      {/* Zoom indicator */}
      <div className="absolute bottom-4 left-4 bg-canvas-surface/80 px-3 py-1 rounded text-sm text-canvas-muted">
        {Math.round(transform.scale * 100)}%
      </div>

      {/* Help text */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-canvas-muted text-xs">
        Scroll to zoom | Middle-click drag to pan | Drop files to view
      </div>

      {/* Drag overlay */}
      {isDragOver && (
        <div className="absolute inset-0 bg-purple-500/20 border-4 border-dashed border-purple-500 flex items-center justify-center pointer-events-none z-50">
          <div className="bg-canvas-surface/90 px-8 py-4 rounded-lg shadow-xl">
            <p className="text-white text-lg font-medium">Drop files here to view</p>
          </div>
        </div>
      )}
    </div>
  )
}

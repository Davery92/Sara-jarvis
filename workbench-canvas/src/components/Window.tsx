import { useRef, useCallback, useState, useEffect, type ReactNode } from 'react'
import { X, GripHorizontal } from 'lucide-react'
import type { Position, Size } from '../types'
import { APP_CONFIG } from '../config'

interface WindowProps {
  id: string
  title: string
  position: Position
  size: Size
  zIndex: number
  children: ReactNode
  onClose: () => void
  onFocus: () => void
  onMove: (position: Position) => void
  onResize: (size: Size) => void
}

export default function Window({
  title,
  position,
  size,
  zIndex,
  children,
  onClose,
  onFocus,
  onMove,
  onResize,
}: WindowProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const [resizeDirection, setResizeDirection] = useState<string>('')

  const dragStart = useRef({ x: 0, y: 0 })
  const initialPos = useRef({ x: 0, y: 0 })
  const initialSize = useRef({ width: 0, height: 0 })

  // Handle drag start
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return // Only left click
    e.preventDefault()
    e.stopPropagation()
    onFocus()
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialPos.current = { ...position }
  }, [onFocus, position])

  // Handle resize start
  const handleResizeStart = useCallback((e: React.MouseEvent, direction: string) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    onFocus()
    setIsResizing(true)
    setResizeDirection(direction)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialSize.current = { ...size }
    initialPos.current = { ...position }
  }, [onFocus, size, position])

  // Global mouse move handler (attached to window when dragging/resizing)
  useEffect(() => {
    if (!isDragging && !isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x
      const dy = e.clientY - dragStart.current.y

      if (isDragging) {
        onMove({
          x: initialPos.current.x + dx,
          y: initialPos.current.y + dy,
        })
      }

      if (isResizing) {
        const { minWidth, minHeight } = APP_CONFIG.window

        let newWidth = initialSize.current.width
        let newHeight = initialSize.current.height
        let newX = initialPos.current.x
        let newY = initialPos.current.y

        if (resizeDirection.includes('e')) {
          newWidth = Math.max(minWidth, initialSize.current.width + dx)
        }
        if (resizeDirection.includes('w')) {
          const deltaWidth = Math.min(dx, initialSize.current.width - minWidth)
          newWidth = initialSize.current.width - deltaWidth
          newX = initialPos.current.x + deltaWidth
        }
        if (resizeDirection.includes('s')) {
          newHeight = Math.max(minHeight, initialSize.current.height + dy)
        }
        if (resizeDirection.includes('n')) {
          const deltaHeight = Math.min(dy, initialSize.current.height - minHeight)
          newHeight = initialSize.current.height - deltaHeight
          newY = initialPos.current.y + deltaHeight
        }

        onResize({ width: newWidth, height: newHeight })
        if (resizeDirection.includes('w') || resizeDirection.includes('n')) {
          onMove({ x: newX, y: newY })
        }
      }
    }

    const handleMouseUp = () => {
      setIsDragging(false)
      setIsResizing(false)
      setResizeDirection('')
    }

    // Add global listeners
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, isResizing, resizeDirection, onMove, onResize])

  return (
    <div
      className="absolute bg-canvas-surface border border-canvas-border rounded-lg shadow-2xl overflow-hidden pointer-events-auto"
      style={{
        left: position.x,
        top: position.y,
        width: size.width,
        height: size.height,
        zIndex,
      }}
      onMouseDown={onFocus}
    >
      {/* Title bar */}
      <div
        className="h-10 bg-canvas-elevated border-b border-canvas-border flex items-center justify-between px-3 cursor-move select-none"
        onMouseDown={handleDragStart}
      >
        <div className="flex items-center gap-2 text-gray-300 text-sm font-medium truncate">
          <GripHorizontal size={16} className="text-canvas-muted flex-shrink-0" />
          <span className="truncate">{title}</span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onClose()
          }}
          className="w-8 h-8 flex items-center justify-center rounded hover:bg-red-500/20 text-canvas-muted hover:text-red-400 transition-colors touch-target"
        >
          <X size={18} />
        </button>
      </div>

      {/* Content area */}
      <div className="overflow-hidden select-text" style={{ height: size.height - 40 }}>
        {children}
      </div>

      {/* Resize handles */}
      <ResizeHandle direction="e" onStart={handleResizeStart} />
      <ResizeHandle direction="w" onStart={handleResizeStart} />
      <ResizeHandle direction="s" onStart={handleResizeStart} />
      <ResizeHandle direction="n" onStart={handleResizeStart} />
      <ResizeHandle direction="se" onStart={handleResizeStart} />
      <ResizeHandle direction="sw" onStart={handleResizeStart} />
      <ResizeHandle direction="ne" onStart={handleResizeStart} />
      <ResizeHandle direction="nw" onStart={handleResizeStart} />
    </div>
  )
}

// Resize handle component
interface ResizeHandleProps {
  direction: string
  onStart: (e: React.MouseEvent, direction: string) => void
}

function ResizeHandle({ direction, onStart }: ResizeHandleProps) {
  const handleSize = APP_CONFIG.touch.resizeHandleSize

  const getStyles = (): React.CSSProperties => {
    const base: React.CSSProperties = {
      position: 'absolute',
      zIndex: 10,
    }

    switch (direction) {
      case 'e':
        return { ...base, top: handleSize, right: 0, width: handleSize / 2, height: `calc(100% - ${handleSize * 2}px)`, cursor: 'ew-resize' }
      case 'w':
        return { ...base, top: handleSize, left: 0, width: handleSize / 2, height: `calc(100% - ${handleSize * 2}px)`, cursor: 'ew-resize' }
      case 's':
        return { ...base, bottom: 0, left: handleSize, width: `calc(100% - ${handleSize * 2}px)`, height: handleSize / 2, cursor: 'ns-resize' }
      case 'n':
        return { ...base, top: 0, left: handleSize, width: `calc(100% - ${handleSize * 2}px)`, height: handleSize / 2, cursor: 'ns-resize' }
      case 'se':
        return { ...base, bottom: 0, right: 0, width: handleSize, height: handleSize, cursor: 'nwse-resize' }
      case 'sw':
        return { ...base, bottom: 0, left: 0, width: handleSize, height: handleSize, cursor: 'nesw-resize' }
      case 'ne':
        return { ...base, top: 0, right: 0, width: handleSize, height: handleSize, cursor: 'nesw-resize' }
      case 'nw':
        return { ...base, top: 0, left: 0, width: handleSize, height: handleSize, cursor: 'nwse-resize' }
      default:
        return base
    }
  }

  return (
    <div
      style={getStyles()}
      onMouseDown={(e) => onStart(e, direction)}
    />
  )
}

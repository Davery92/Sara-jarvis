import React, { useEffect, useMemo, useRef, useState } from 'react'

export interface PanelRect {
  x: number
  y: number
  width: number
  height: number
}

interface FloatingLearningPanelProps {
  id: string
  title: string
  subtitle?: string
  icon?: string
  initialRect: PanelRect
  zIndex: number
  onFocus: (id: string) => void
  onAttach: () => void
  onClose: () => void
  onRectChange?: (rect: PanelRect) => void
  children: React.ReactNode
}

const MIN_WIDTH = 360
const MIN_HEIGHT = 260
const VIEWPORT_MARGIN = 12

function clampRect(rect: PanelRect): PanelRect {
  const maxWidth = Math.max(MIN_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2)
  const maxHeight = Math.max(MIN_HEIGHT, window.innerHeight - VIEWPORT_MARGIN * 2)

  const width = Math.max(MIN_WIDTH, Math.min(rect.width, maxWidth))
  const height = Math.max(MIN_HEIGHT, Math.min(rect.height, maxHeight))

  const maxX = Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN)
  const maxY = Math.max(VIEWPORT_MARGIN, window.innerHeight - height - VIEWPORT_MARGIN)

  return {
    x: Math.min(Math.max(rect.x, VIEWPORT_MARGIN), maxX),
    y: Math.min(Math.max(rect.y, VIEWPORT_MARGIN), maxY),
    width,
    height
  }
}

export default function FloatingLearningPanel({
  id,
  title,
  subtitle,
  icon = 'open_in_new',
  initialRect,
  zIndex,
  onFocus,
  onAttach,
  onClose,
  onRectChange,
  children
}: FloatingLearningPanelProps) {
  const [rect, setRect] = useState<PanelRect>(initialRect)
  const rectRef = useRef(rect)
  const initializedRef = useRef(false)
  const dragOffsetRef = useRef<{ x: number; y: number } | null>(null)
  const resizeStartRef = useRef<{
    x: number
    y: number
    width: number
    height: number
  } | null>(null)
  const draggingRef = useRef(false)
  const resizingRef = useRef(false)

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    setRect(clampRect(initialRect))
  }, [initialRect])

  useEffect(() => {
    rectRef.current = rect
  }, [rect])

  useEffect(() => {
    const handleViewportResize = () => {
      setRect((prev) => clampRect(prev))
    }
    window.addEventListener('resize', handleViewportResize)
    return () => window.removeEventListener('resize', handleViewportResize)
  }, [])

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (draggingRef.current && dragOffsetRef.current) {
        setRect((prev) => {
          const next = clampRect({
            ...prev,
            x: event.clientX - dragOffsetRef.current.x,
            y: event.clientY - dragOffsetRef.current.y
          })
          rectRef.current = next
          return next
        })
      }

      if (resizingRef.current && resizeStartRef.current) {
        const deltaX = event.clientX - resizeStartRef.current.x
        const deltaY = event.clientY - resizeStartRef.current.y
        setRect((prev) => {
          const next = clampRect({
            ...prev,
            width: resizeStartRef.current.width + deltaX,
            height: resizeStartRef.current.height + deltaY
          })
          rectRef.current = next
          return next
        })
      }
    }

    const handleMouseUp = () => {
      const wasMoving = draggingRef.current || resizingRef.current
      draggingRef.current = false
      resizingRef.current = false
      dragOffsetRef.current = null
      resizeStartRef.current = null
      if (wasMoving && onRectChange) {
        onRectChange(rectRef.current)
      }
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [onRectChange])

  const headerTitle = useMemo(() => title || 'Detached Panel', [title])

  const startDrag = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest('[data-panel-action]')) return
    onFocus(id)
    draggingRef.current = true
    dragOffsetRef.current = {
      x: event.clientX - rect.x,
      y: event.clientY - rect.y
    }
  }

  const startResize = (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    onFocus(id)
    resizingRef.current = true
    resizeStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      width: rect.width,
      height: rect.height
    }
  }

  return (
    <div
      className="fixed bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden flex flex-col"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.width,
        height: rect.height,
        zIndex
      }}
      onMouseDown={() => onFocus(id)}
    >
      <div
        className="flex items-center justify-between px-3 py-2 border-b border-gray-700 bg-gray-800/95 cursor-move select-none"
        onMouseDown={startDrag}
      >
        <div className="min-w-0 flex items-center gap-2">
          <span className="material-icons text-sm text-teal-400">{icon}</span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-white truncate">{headerTitle}</div>
            {subtitle && (
              <div className="text-xs text-gray-400 truncate">{subtitle}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            data-panel-action
            onClick={onAttach}
            className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
            title="Attach back"
          >
            <span className="material-icons text-sm">vertical_align_bottom</span>
          </button>
          <button
            data-panel-action
            onClick={onClose}
            className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
            title="Close"
          >
            <span className="material-icons text-sm">close</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {children}
      </div>

      <button
        data-panel-action
        className="absolute right-0 bottom-0 w-5 h-5 cursor-se-resize group"
        onMouseDown={startResize}
        title="Resize panel"
      >
        <span className="absolute right-1 bottom-1 w-2.5 h-2.5 border-r-2 border-b-2 border-gray-500 group-hover:border-teal-400" />
      </button>
    </div>
  )
}

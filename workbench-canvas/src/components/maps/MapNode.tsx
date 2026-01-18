import { useState, useRef, useCallback, useEffect } from 'react'
import { useCanvasStore } from '../../store/canvasStore'
import MapNodeContent from './MapNodeContent'
import ConnectionHandle from './ConnectionHandle'
import type { MapNode as MapNodeType, Position, Size } from '../../types'

interface MapNodeProps {
  node: MapNodeType
  mapId: string
  isSelected: boolean
  isReadonly: boolean
}

export default function MapNode({ node, mapId, isSelected, isReadonly }: MapNodeProps) {
  const {
    selectMapNode,
    moveMapNode,
    resizeMapNode,
    completeConnection,
    mapSelection,
    setEditingNodeId,
  } = useCanvasStore()

  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const [resizeDirection, setResizeDirection] = useState('')

  const dragStart = useRef({ x: 0, y: 0 })
  const initialPos = useRef<Position>({ x: 0, y: 0 })
  const initialSize = useRef<Size>({ width: 0, height: 0 })

  const isConnectionMode = mapSelection?.connectionSource !== undefined
  const isConnectionSource = mapSelection?.connectionSource === node.id

  // Handle click on node
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()

    // If in connection mode and clicking a different node, complete the connection
    if (isConnectionMode && !isConnectionSource) {
      // Default to 'left' handle when clicking node body
      completeConnection(node.id, 'left')
      return
    }

    selectMapNode(mapId, node.id, e.shiftKey)
  }

  // Handle double-click to edit
  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!isReadonly) {
      setEditingNodeId(node.id)
    }
  }

  // Handle drag start
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0 || isReadonly) return
    e.preventDefault()
    e.stopPropagation()
    selectMapNode(mapId, node.id)
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialPos.current = { ...node.position }
  }, [mapId, node.id, node.position, selectMapNode, isReadonly])

  // Handle resize start
  const handleResizeStart = useCallback((e: React.MouseEvent, direction: string) => {
    if (e.button !== 0 || isReadonly) return
    e.preventDefault()
    e.stopPropagation()
    selectMapNode(mapId, node.id)
    setIsResizing(true)
    setResizeDirection(direction)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialSize.current = { ...node.size }
    initialPos.current = { ...node.position }
  }, [mapId, node.id, node.size, node.position, selectMapNode, isReadonly])

  // Global mouse move/up handlers
  useEffect(() => {
    if (!isDragging && !isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x
      const dy = e.clientY - dragStart.current.y

      if (isDragging) {
        moveMapNode(mapId, node.id, {
          x: initialPos.current.x + dx,
          y: initialPos.current.y + dy,
        })
      }

      if (isResizing) {
        const minWidth = 100
        const minHeight = 50

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

        resizeMapNode(mapId, node.id, { width: newWidth, height: newHeight })
        if (resizeDirection.includes('w') || resizeDirection.includes('n')) {
          moveMapNode(mapId, node.id, { x: newX, y: newY })
        }
      }
    }

    const handleMouseUp = () => {
      setIsDragging(false)
      setIsResizing(false)
      setResizeDirection('')
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, isResizing, resizeDirection, mapId, node.id, moveMapNode, resizeMapNode])

  // Get node background color
  const bgColor = node.style?.backgroundColor || '#1f2937'
  const borderColor = isSelected ? '#14b8a6' : (node.style?.borderColor || '#374151')
  const borderRadius = node.style?.borderRadius ?? 8

  return (
    <div
      className={`absolute pointer-events-auto select-none
        ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}
        ${isConnectionMode && !isConnectionSource ? 'cursor-crosshair' : ''}
      `}
      style={{
        left: node.position.x,
        top: node.position.y,
        width: node.size.width,
        height: node.size.height,
        backgroundColor: bgColor,
        borderRadius,
        border: `2px solid ${borderColor}`,
        boxShadow: isSelected ? '0 0 0 2px rgba(20, 184, 166, 0.3)' : 'none',
      }}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onMouseDown={handleDragStart}
    >
      {/* Content - with overflow hidden */}
      <div className="w-full h-full overflow-hidden" style={{ borderRadius: borderRadius - 2 }}>
        <MapNodeContent content={node.content} />
      </div>

      {/* Connection handles - positioned outside, so parent needs overflow visible */}
      {!isReadonly && (
        <>
          <ConnectionHandle side="top" nodeId={node.id} mapId={mapId} />
          <ConnectionHandle side="right" nodeId={node.id} mapId={mapId} />
          <ConnectionHandle side="bottom" nodeId={node.id} mapId={mapId} />
          <ConnectionHandle side="left" nodeId={node.id} mapId={mapId} />
        </>
      )}

      {/* Resize handles */}
      {!isReadonly && (
        <>
          <ResizeHandle direction="e" onStart={handleResizeStart} />
          <ResizeHandle direction="w" onStart={handleResizeStart} />
          <ResizeHandle direction="s" onStart={handleResizeStart} />
          <ResizeHandle direction="n" onStart={handleResizeStart} />
          <ResizeHandle direction="se" onStart={handleResizeStart} />
          <ResizeHandle direction="sw" onStart={handleResizeStart} />
          <ResizeHandle direction="ne" onStart={handleResizeStart} />
          <ResizeHandle direction="nw" onStart={handleResizeStart} />
        </>
      )}
    </div>
  )
}

// Resize handle component
interface ResizeHandleProps {
  direction: string
  onStart: (e: React.MouseEvent, direction: string) => void
}

function ResizeHandle({ direction, onStart }: ResizeHandleProps) {
  const handleSize = 12

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

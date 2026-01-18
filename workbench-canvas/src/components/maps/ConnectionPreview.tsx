import { useState, useEffect } from 'react'
import { useCanvasStore } from '../../store/canvasStore'
import type { HandlePosition } from '../../types'

interface ConnectionPreviewProps {
  mapId: string
  sourceNodeId: string
}

export default function ConnectionPreview({ mapId, sourceNodeId }: ConnectionPreviewProps) {
  const { maps, transform, mapSelection } = useCanvasStore()
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })

  const map = maps.find((m) => m.id === mapId)
  const sourceNode = map?.mapData.nodes.find((n) => n.id === sourceNodeId)
  const sourceHandle = mapSelection?.sourceHandle || 'right'

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      // Convert screen coordinates to canvas coordinates
      const canvasX = (e.clientX - transform.x) / transform.scale
      const canvasY = (e.clientY - transform.y) / transform.scale
      setMousePos({ x: canvasX, y: canvasY })
    }

    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [transform])

  if (!map || !sourceNode) return null

  // Calculate source point based on the handle that was clicked
  const getSourcePoint = (handle: HandlePosition) => {
    const baseX = map.canvasPosition.x + sourceNode.position.x
    const baseY = map.canvasPosition.y + sourceNode.position.y
    switch (handle) {
      case 'top':
        return { x: baseX + sourceNode.size.width / 2, y: baseY }
      case 'right':
        return { x: baseX + sourceNode.size.width, y: baseY + sourceNode.size.height / 2 }
      case 'bottom':
        return { x: baseX + sourceNode.size.width / 2, y: baseY + sourceNode.size.height }
      case 'left':
        return { x: baseX, y: baseY + sourceNode.size.height / 2 }
      default:
        return { x: baseX + sourceNode.size.width, y: baseY + sourceNode.size.height / 2 }
    }
  }

  const sourcePoint = getSourcePoint(sourceHandle)
  const sourceX = sourcePoint.x
  const sourceY = sourcePoint.y

  // Calculate control points for bezier curve based on handle direction
  const dx = mousePos.x - sourceX
  const dy = mousePos.y - sourceY
  const distance = Math.sqrt(dx * dx + dy * dy)
  const controlOffset = Math.min(distance * 0.4, 100)

  // Adjust control points based on which handle we're drawing from
  let cx1 = sourceX, cy1 = sourceY, cx2 = mousePos.x, cy2 = mousePos.y
  switch (sourceHandle) {
    case 'top':
      cy1 = sourceY - controlOffset
      cy2 = mousePos.y + controlOffset
      break
    case 'right':
      cx1 = sourceX + controlOffset
      cx2 = mousePos.x - controlOffset
      break
    case 'bottom':
      cy1 = sourceY + controlOffset
      cy2 = mousePos.y - controlOffset
      break
    case 'left':
      cx1 = sourceX - controlOffset
      cx2 = mousePos.x + controlOffset
      break
  }

  const path = `M ${sourceX} ${sourceY} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${mousePos.x} ${mousePos.y}`

  return (
    <svg
      className="absolute inset-0 pointer-events-none overflow-visible"
      style={{ width: '100%', height: '100%' }}
    >
      <path
        d={path}
        fill="none"
        stroke="#14b8a6"
        strokeWidth={2}
        strokeDasharray="5,5"
        className="animate-pulse"
      />
      {/* Cursor dot */}
      <circle
        cx={mousePos.x}
        cy={mousePos.y}
        r={6}
        fill="#14b8a6"
        className="animate-pulse"
      />
    </svg>
  )
}

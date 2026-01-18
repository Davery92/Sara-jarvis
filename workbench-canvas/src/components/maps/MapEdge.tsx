import { useCanvasStore } from '../../store/canvasStore'
import type { MapEdge as MapEdgeType, MapNode, Position, HandlePosition } from '../../types'

interface MapEdgeProps {
  edge: MapEdgeType
  nodes: MapNode[]
  mapId: string
  isSelected: boolean
}

// Get the position of a handle on a node
function getHandlePosition(node: MapNode, handle: HandlePosition): Position {
  const { position, size } = node
  switch (handle) {
    case 'top':
      return { x: position.x + size.width / 2, y: position.y }
    case 'right':
      return { x: position.x + size.width, y: position.y + size.height / 2 }
    case 'bottom':
      return { x: position.x + size.width / 2, y: position.y + size.height }
    case 'left':
      return { x: position.x, y: position.y + size.height / 2 }
    default:
      return { x: position.x + size.width, y: position.y + size.height / 2 }
  }
}

// Generate bezier path between two points
function generateBezierPath(source: Position, target: Position, curved = true): string {
  if (!curved) {
    return `M ${source.x} ${source.y} L ${target.x} ${target.y}`
  }

  const dx = target.x - source.x
  const dy = target.y - source.y
  const distance = Math.sqrt(dx * dx + dy * dy)
  const controlOffset = Math.min(Math.abs(dx) * 0.5, Math.abs(dy) * 0.5, distance * 0.3, 150)

  // Determine control point direction based on handle positions
  // This creates a smooth curve that flows naturally
  let cx1 = source.x + controlOffset
  let cy1 = source.y
  let cx2 = target.x - controlOffset
  let cy2 = target.y

  // Adjust control points for vertical connections
  if (Math.abs(dy) > Math.abs(dx)) {
    cx1 = source.x
    cy1 = source.y + (dy > 0 ? controlOffset : -controlOffset)
    cx2 = target.x
    cy2 = target.y - (dy > 0 ? controlOffset : -controlOffset)
  }

  return `M ${source.x} ${source.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${target.x} ${target.y}`
}

export default function MapEdge({ edge, nodes, mapId, isSelected }: MapEdgeProps) {
  const { selectMapEdge } = useCanvasStore()

  const sourceNode = nodes.find((n) => n.id === edge.source)
  const targetNode = nodes.find((n) => n.id === edge.target)

  if (!sourceNode || !targetNode) return null

  const sourcePos = getHandlePosition(sourceNode, edge.sourceHandle || 'right')
  const targetPos = getHandlePosition(targetNode, edge.targetHandle || 'left')

  const path = generateBezierPath(sourcePos, targetPos, edge.style?.curved ?? true)
  const strokeColor = isSelected ? '#14b8a6' : (edge.style?.strokeColor || '#6b7280')
  const strokeWidth = edge.style?.strokeWidth || 2

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    selectMapEdge(mapId, edge.id)
  }

  return (
    <g className="pointer-events-auto">
      {/* Invisible wider path for easier clicking */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        onClick={handleClick}
        className="cursor-pointer"
      />
      {/* Visible path */}
      <path
        d={path}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        markerEnd="url(#map-arrowhead)"
        className="pointer-events-none transition-colors"
        style={{
          filter: isSelected ? 'drop-shadow(0 0 4px rgba(20, 184, 166, 0.5))' : 'none',
        }}
      />
    </g>
  )
}

import { useCanvasStore } from '../../store/canvasStore'
import type { HandlePosition } from '../../types'

interface ConnectionHandleProps {
  nodeId: string
  mapId: string
  side: HandlePosition
}

export default function ConnectionHandle({ nodeId, mapId, side }: ConnectionHandleProps) {
  const { startConnection, completeConnection, mapSelection } = useCanvasStore()
  const isConnectionMode = mapSelection?.connectionSource !== undefined
  const isSource = mapSelection?.connectionSource === nodeId

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    // If already in connection mode and this is a different node, complete the connection
    if (isConnectionMode && !isSource) {
      completeConnection(nodeId, side)
    } else {
      // Start a new connection from this node
      startConnection(mapId, nodeId, side)
    }
  }

  // Position styles for each side - positioned outside the node with high z-index
  const positionStyles: Record<HandlePosition, React.CSSProperties> = {
    top: { top: -8, left: '50%', transform: 'translateX(-50%)', zIndex: 20 },
    right: { right: -8, top: '50%', transform: 'translateY(-50%)', zIndex: 20 },
    bottom: { bottom: -8, left: '50%', transform: 'translateX(-50%)', zIndex: 20 },
    left: { left: -8, top: '50%', transform: 'translateY(-50%)', zIndex: 20 },
  }

  return (
    <div
      className={`absolute w-4 h-4 rounded-full border-2 cursor-crosshair transition-all
        ${isConnectionMode
          ? 'bg-teal-500 border-teal-400 scale-125'
          : 'bg-gray-600 border-gray-400 hover:bg-teal-500 hover:border-teal-400 hover:scale-125'
        }`}
      style={positionStyles[side]}
      onClick={handleClick}
      onMouseDown={(e) => {
        e.stopPropagation()
        e.preventDefault()
        handleClick(e)
      }}
    />
  )
}

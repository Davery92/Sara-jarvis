import { useCallback, useState, useRef, useEffect } from 'react'
import { X, Minimize2, GripHorizontal, Expand, Shrink, Loader2 } from 'lucide-react'
import { useCanvasStore } from '../../store/canvasStore'
import { mapsApi } from '../../services/api'
import MapNode from './MapNode'
import MapEdge from './MapEdge'
import type { MapInstance } from '../../types'

interface MapContainerProps {
  map: MapInstance
}

export default function MapContainer({ map }: MapContainerProps) {
  const { mapSelection, addMapNode, clearMapSelection, cancelConnection, removeMap, collapseMap, moveMapOnCanvas, updateMap } = useCanvasStore()
  const [isDragging, setIsDragging] = useState(false)
  const [isExploding, setIsExploding] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const initialPos = useRef({ x: 0, y: 0 })

  const handleExplode = async (compact: boolean = false) => {
    if (map.isReadonly || isExploding) return
    setIsExploding(true)
    try {
      // Use smaller spacing for compact, larger for explode
      const spacingFactor = compact ? 0.5 : 1.5
      const result = await mapsApi.explode(map.id, spacingFactor)
      updateMap(map.id, { mapData: result.map_data })
    } catch (err) {
      console.error('Failed to explode/compact map:', err)
    } finally {
      setIsExploding(false)
    }
  }

  const isThisMapSelected = mapSelection?.mapId === map.id
  const selectedNodeIds = isThisMapSelected ? mapSelection.nodeIds : []
  const selectedEdgeIds = isThisMapSelected ? mapSelection.edgeIds : []
  const isConnectionMode = mapSelection?.connectionSource !== undefined

  // Handle header drag to move the entire map
  const handleHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    e.stopPropagation()
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialPos.current = { ...map.canvasPosition }
  }, [map.canvasPosition])

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x
      const dy = e.clientY - dragStart.current.y
      moveMapOnCanvas(map.id, {
        x: initialPos.current.x + dx,
        y: initialPos.current.y + dy,
      })
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, map.id, moveMapOnCanvas])

  // Handle click on map background (for creating nodes with Ctrl+Click)
  const handleMapClick = useCallback((e: React.MouseEvent) => {
    // If in connection mode, cancel it
    if (isConnectionMode) {
      cancelConnection()
      return
    }

    // Check for Ctrl/Cmd + Click to create new node
    if ((e.ctrlKey || e.metaKey) && !map.isReadonly) {
      const rect = e.currentTarget.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top

      addMapNode(map.id, {
        position: { x, y },
        size: { width: 180, height: 80 },
        content: { type: 'text', data: { text: '' } },
      })
      return
    }

    // Clear selection when clicking empty space
    clearMapSelection()
  }, [map.id, map.isReadonly, addMapNode, clearMapSelection, cancelConnection, isConnectionMode])

  // Calculate bounding box of all nodes to set container size
  const nodes = map.mapData.nodes
  const edges = map.mapData.edges

  // Find bounds
  let minX = 0, minY = 0, maxX = 400, maxY = 300
  if (nodes.length > 0) {
    minX = Math.min(...nodes.map((n) => n.position.x)) - 50
    minY = Math.min(...nodes.map((n) => n.position.y)) - 50
    maxX = Math.max(...nodes.map((n) => n.position.x + n.size.width)) + 50
    maxY = Math.max(...nodes.map((n) => n.position.y + n.size.height)) + 50
  }

  const containerWidth = Math.max(400, maxX - minX)
  const containerHeight = Math.max(300, maxY - minY)

  return (
    <div
      className="absolute pointer-events-auto"
      style={{
        left: map.canvasPosition.x,
        top: map.canvasPosition.y,
        width: containerWidth,
        height: containerHeight,
      }}
      onClick={handleMapClick}
    >
      {/* Map header - draggable */}
      <div
        className={`absolute -top-7 left-0 right-0 flex items-center justify-between pointer-events-auto ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
        onMouseDown={handleHeaderMouseDown}
      >
        <div className="flex items-center gap-1 text-xs font-medium text-gray-400 bg-gray-800/90 px-2 py-1 rounded select-none">
          <GripHorizontal size={12} className="text-gray-500" />
          <span>{map.name}</span>
          {map.isReadonly && (
            <span className="ml-1 text-gray-500">(read-only)</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!map.isReadonly && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleExplode(true)
                }}
                onMouseDown={(e) => e.stopPropagation()}
                disabled={isExploding}
                className="w-5 h-5 flex items-center justify-center rounded bg-gray-700/80 hover:bg-orange-600 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
                title="Compact map - bring nodes closer"
              >
                {isExploding ? <Loader2 size={12} className="animate-spin" /> : <Shrink size={12} />}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleExplode(false)
                }}
                onMouseDown={(e) => e.stopPropagation()}
                disabled={isExploding}
                className="w-5 h-5 flex items-center justify-center rounded bg-gray-700/80 hover:bg-teal-600 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
                title="Explode map - spread nodes apart"
              >
                {isExploding ? <Loader2 size={12} className="animate-spin" /> : <Expand size={12} />}
              </button>
            </>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation()
              collapseMap(map.id, true)
            }}
            onMouseDown={(e) => e.stopPropagation()}
            className="w-5 h-5 flex items-center justify-center rounded bg-gray-700/80 hover:bg-gray-600 text-gray-400 hover:text-white transition-colors"
            title="Collapse to icon"
          >
            <Minimize2 size={12} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              removeMap(map.id)
            }}
            onMouseDown={(e) => e.stopPropagation()}
            className="w-5 h-5 flex items-center justify-center rounded bg-gray-700/80 hover:bg-red-600 text-gray-400 hover:text-white transition-colors"
            title="Close map"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* SVG layer for edges */}
      <svg
        className="absolute inset-0 overflow-visible pointer-events-none"
        style={{ width: containerWidth, height: containerHeight }}
      >
        <defs>
          <marker
            id="map-arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
          </marker>
          <marker
            id="map-arrowhead-selected"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#14b8a6" />
          </marker>
        </defs>
        {edges.map((edge) => (
          <MapEdge
            key={edge.id}
            edge={edge}
            nodes={nodes}
            mapId={map.id}
            isSelected={selectedEdgeIds.includes(edge.id)}
          />
        ))}
      </svg>

      {/* Nodes layer */}
      {nodes.map((node) => (
        <MapNode
          key={node.id}
          node={node}
          mapId={map.id}
          isSelected={selectedNodeIds.includes(node.id)}
          isReadonly={map.isReadonly}
        />
      ))}

      {/* Connection mode indicator */}
      {isConnectionMode && isThisMapSelected && (
        <div className="absolute bottom-2 left-2 text-xs text-teal-400 bg-gray-900/90 px-2 py-1 rounded">
          Click another node to connect, or click empty space to cancel
        </div>
      )}
    </div>
  )
}

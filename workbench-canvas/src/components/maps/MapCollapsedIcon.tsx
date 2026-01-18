import { useState, useRef, useEffect } from 'react'
import { GitBranch, Lock } from 'lucide-react'
import { useCanvasStore } from '../../store/canvasStore'
import type { MapInstance } from '../../types'

interface MapCollapsedIconProps {
  map: MapInstance
}

export default function MapCollapsedIcon({ map }: MapCollapsedIconProps) {
  const { collapseMap, removeMap, moveMapOnCanvas } = useCanvasStore()
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const initialPos = useRef({ x: 0, y: 0 })

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    collapseMap(map.id, false)
  }

  const handleClose = (e: React.MouseEvent) => {
    e.stopPropagation()
    removeMap(map.id)
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    e.stopPropagation()
    setIsDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    initialPos.current = { ...map.canvasPosition }
  }

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

  return (
    <div
      className={`absolute pointer-events-auto ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      style={{
        left: map.canvasPosition.x,
        top: map.canvasPosition.y,
      }}
      onDoubleClick={handleDoubleClick}
      onMouseDown={handleMouseDown}
    >
      <div className="relative group">
        {/* Icon container */}
        <div className="w-16 h-16 bg-gray-800 border border-gray-600 rounded-lg flex flex-col items-center justify-center hover:bg-gray-700 transition-colors shadow-lg">
          <GitBranch size={24} className="text-teal-400" />
          {map.isReadonly && (
            <Lock size={10} className="absolute top-1 right-1 text-gray-500" />
          )}
        </div>

        {/* Map name */}
        <div className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-xs text-gray-400 whitespace-nowrap bg-gray-900/80 px-1 rounded">
          {map.name}
        </div>

        {/* Node count badge */}
        <div className="absolute -top-1 -right-1 w-5 h-5 bg-teal-600 rounded-full flex items-center justify-center text-[10px] text-white font-medium">
          {map.mapData.nodes.length}
        </div>

        {/* Close button (on hover) */}
        <button
          className="absolute -top-2 -left-2 w-5 h-5 bg-red-600 rounded-full items-center justify-center text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity hidden group-hover:flex"
          onClick={handleClose}
        >
          &times;
        </button>

        {/* Hint text (on hover) */}
        <div className="absolute -bottom-10 left-1/2 -translate-x-1/2 text-[10px] text-gray-500 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
          Double-click to expand
        </div>
      </div>
    </div>
  )
}

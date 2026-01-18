import { useState, useMemo } from 'react'
import { X, Search, GitBranch, Loader2, Plus, Lock, Upload } from 'lucide-react'
import { useMaps } from '../../hooks/useMaps'
import { useCanvasStore } from '../../store/canvasStore'
import { mapsApi } from '../../services/api'
import type { MapInstance } from '../../types'

export default function MapPicker() {
  const { setMapPickerOpen, setMapImportModalOpen, addMap, removeMap, maps: visibleMaps } = useCanvasStore()
  const { data: maps, isLoading, error, refetch } = useMaps()
  const [search, setSearch] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [newMapName, setNewMapName] = useState('')

  // Filter maps by search
  const filteredMaps = useMemo(() => {
    if (!maps) return []
    if (!search.trim()) return maps

    const searchLower = search.toLowerCase()
    return maps.filter(
      (map) =>
        map.name.toLowerCase().includes(searchLower) ||
        (map.description && map.description.toLowerCase().includes(searchLower))
    )
  }, [maps, search])

  // Check if a map is already visible on canvas
  const isMapVisible = (mapId: string) => {
    return visibleMaps.some((m) => m.id === mapId)
  }

  const handleMapClick = async (mapSummary: typeof filteredMaps[0]) => {
    // Check if already visible
    if (isMapVisible(mapSummary.id)) {
      // Still set as current map for Sara's auto-detect
      mapsApi.setCurrentMap(mapSummary.id, mapSummary.name).catch(console.error)
      setMapPickerOpen(false)
      return
    }

    try {
      // Fetch full map data
      const mapData = await mapsApi.get(mapSummary.id)

      // Create MapInstance and add to canvas
      const mapInstance: MapInstance = {
        id: mapData.id,
        name: mapData.name,
        description: mapData.description,
        mapData: mapData.map_data,
        isReadonly: mapData.is_readonly,
        canvasPosition: { x: 200, y: 200 },
        collapsed: false,
      }

      addMap(mapInstance)

      // Notify backend for Sara's auto-detect
      mapsApi.setCurrentMap(mapData.id, mapData.name).catch(console.error)
    } catch (e) {
      console.error('Failed to load map:', e)
    }
  }

  const handleCreateMap = async () => {
    if (!newMapName.trim()) return

    try {
      const created = await mapsApi.create({
        name: newMapName.trim(),
        map_data: { nodes: [], edges: [] },
      })

      // Add to canvas
      const mapInstance: MapInstance = {
        id: created.id,
        name: created.name,
        description: created.description,
        mapData: created.map_data,
        isReadonly: false,
        canvasPosition: { x: 200, y: 200 },
        collapsed: false,
      }

      addMap(mapInstance)

      // Notify backend for Sara's auto-detect
      mapsApi.setCurrentMap(created.id, created.name).catch(console.error)

      refetch()
      setIsCreating(false)
      setNewMapName('')
    } catch (e) {
      console.error('Failed to create map:', e)
    }
  }

  const handleDeleteMap = async (e: React.MouseEvent, mapId: string) => {
    e.stopPropagation()
    if (!confirm('Delete this map permanently?')) return

    try {
      // Remove from canvas first (if visible)
      removeMap(mapId)
      // Then delete from backend
      await mapsApi.delete(mapId)
      refetch()
    } catch (e) {
      console.error('Failed to delete map:', e)
    }
  }

  return (
    <div className="absolute left-0 top-0 h-full w-80 bg-canvas-surface border-r border-canvas-border shadow-2xl flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-canvas-border">
        <h2 className="text-lg font-semibold text-white">Maps</h2>
        <button
          onClick={() => setMapPickerOpen(false)}
          className="w-10 h-10 flex items-center justify-center rounded-lg hover:bg-canvas-elevated text-canvas-muted hover:text-white transition-colors touch-target"
        >
          <X size={20} />
        </button>
      </div>

      {/* Actions */}
      <div className="p-4 border-b border-canvas-border flex gap-2">
        {isCreating ? (
          <div className="flex-1 flex gap-2">
            <input
              type="text"
              value={newMapName}
              onChange={(e) => setNewMapName(e.target.value)}
              placeholder="Map name..."
              className="flex-1 px-3 py-2 bg-canvas-elevated border border-canvas-border rounded-lg
                         text-white placeholder-canvas-muted text-sm
                         focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreateMap()
                if (e.key === 'Escape') setIsCreating(false)
              }}
            />
            <button
              onClick={handleCreateMap}
              className="px-3 py-2 bg-teal-600 text-white rounded-lg text-sm hover:bg-teal-500 transition-colors"
            >
              Create
            </button>
          </div>
        ) : (
          <>
            <button
              onClick={() => setIsCreating(true)}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-teal-600 text-white rounded-lg text-sm hover:bg-teal-500 transition-colors"
            >
              <Plus size={16} />
              New Map
            </button>
            <button
              onClick={() => setMapImportModalOpen(true)}
              className="flex items-center justify-center gap-2 px-3 py-2 bg-canvas-elevated text-canvas-muted rounded-lg text-sm hover:bg-gray-700 hover:text-white transition-colors"
              title="Import from JSON/Mermaid"
            >
              <Upload size={16} />
            </button>
          </>
        )}
      </div>

      {/* Search */}
      <div className="p-4 border-b border-canvas-border">
        <div className="relative">
          <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-canvas-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search maps..."
            className="w-full pl-10 pr-4 py-3 bg-canvas-elevated border border-canvas-border rounded-lg
                       text-white placeholder-canvas-muted
                       focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Maps list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-teal-500" />
          </div>
        )}

        {error && (
          <div className="p-4 text-red-400 text-sm">
            Failed to load maps. Please try again.
          </div>
        )}

        {!isLoading && !error && filteredMaps.length === 0 && (
          <div className="p-4 text-canvas-muted text-sm text-center">
            {search ? 'No maps match your search' : 'No maps yet. Create one to get started!'}
          </div>
        )}

        {filteredMaps.map((map) => {
          const visible = isMapVisible(map.id)
          return (
            <button
              key={map.id}
              onClick={() => handleMapClick(map)}
              className={`w-full p-4 text-left border-b border-canvas-border hover:bg-canvas-elevated transition-colors group ${
                visible ? 'bg-canvas-elevated/50' : ''
              }`}
            >
              <div className="flex items-start gap-3">
                <GitBranch size={18} className="text-teal-400 flex-shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-white font-medium truncate">
                      {map.name}
                    </h3>
                    {map.is_readonly && (
                      <Lock size={12} className="text-gray-500" />
                    )}
                    {visible && (
                      <span className="text-xs text-teal-400 px-1.5 py-0.5 bg-teal-500/20 rounded">
                        Open
                      </span>
                    )}
                  </div>
                  {map.description && (
                    <p className="text-canvas-muted text-sm line-clamp-2 mt-1">
                      {map.description}
                    </p>
                  )}
                  <div className="flex items-center gap-3 mt-2">
                    <span className="text-canvas-muted text-xs">
                      {map.node_count} nodes
                    </span>
                    <span className="text-canvas-muted text-xs">
                      {new Date(map.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                {/* Delete button (on hover) */}
                <button
                  className="w-6 h-6 flex items-center justify-center rounded text-red-400 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 transition-opacity"
                  onClick={(e) => handleDeleteMap(e, map.id)}
                  title="Delete map"
                >
                  <X size={14} />
                </button>
              </div>
            </button>
          )
        })}
      </div>

      {/* Footer with count */}
      {maps && (
        <div className="p-3 border-t border-canvas-border text-canvas-muted text-sm text-center">
          {filteredMaps.length} of {maps.length} maps
        </div>
      )}
    </div>
  )
}

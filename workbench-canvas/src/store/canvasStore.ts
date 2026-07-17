import { create } from 'zustand'
import { APP_CONFIG } from '../config'
import { workspaceApi, mapsApi, type WorkspaceStateData } from '../services/api'
import type {
  CanvasTransform, CanvasMode, WindowInstance, Position, Size, NoteWindowData,
  WindowType, WindowData, SceneObject, Position3D, Rotation3D, ModelFormat,
  MapInstance, MapNode, MapEdge, MapSelection, MapData, MapNodeContent, VisibleMapState,
  WorkspaceScene,
} from '../types'

// Window defaults for each type
const WINDOW_DEFAULTS: Record<WindowType, { width: number; height: number; title: string }> = {
  note: { width: 800, height: 500, title: 'Notes' },
  chat: { width: 600, height: 700, title: 'Chat with Sara' },
  learning: { width: 980, height: 720, title: 'Learning' },
  fitness: { width: 800, height: 600, title: 'Fitness' },
  projects: { width: 900, height: 700, title: 'Projects' },
  timers: { width: 400, height: 350, title: 'Timers' },
  settings: { width: 700, height: 600, title: 'Settings' },
  fileviewer: { width: 700, height: 600, title: 'File Viewer' },
  modelviewer: { width: 800, height: 600, title: '3D Model' },
  research: { width: 700, height: 600, title: 'Research' },
  report: { width: 500, height: 450, title: 'Report' },
  email: { width: 700, height: 600, title: 'Email' },
  documents: { width: 900, height: 650, title: 'Documents' },
  automation: { width: 900, height: 700, title: 'Automation' },
  pkg: { width: 900, height: 700, title: 'Personal Knowledge Graph' },
  intelligence: { width: 900, height: 700, title: 'Intelligence Feed' },
}

interface WindowOptions {
  title?: string
  width?: number
  height?: number
  position?: Position
}

interface CanvasState {
  // Canvas transform
  transform: CanvasTransform

  // Current mode
  mode: CanvasMode

  // UI state
  isNotesPickerOpen: boolean
  isMapPickerOpen: boolean
  isMapImportModalOpen: boolean
  editingNodeId: string | null  // Node being edited

  // Windows
  windows: WindowInstance[]
  maxZIndex: number

  // 3D Scene objects
  sceneObjects: SceneObject[]
  selectedObjectId: string | null

  // Maps (mindmaps/flowcharts)
  maps: MapInstance[]
  mapSelection: MapSelection | null

  // Workspace scenes
  scenes: WorkspaceScene[]
  activeSceneId: string | null

  // Transform actions
  setTransform: (transform: Partial<CanvasTransform>) => void
  resetTransform: () => void
  zoom: (delta: number, centerX: number, centerY: number) => void
  pan: (dx: number, dy: number) => void

  // Mode actions
  setMode: (mode: CanvasMode) => void
  cycleMode: () => void

  // UI actions
  setNotesPickerOpen: (open: boolean) => void
  toggleNotesPicker: () => void
  setMapPickerOpen: (open: boolean) => void
  setMapImportModalOpen: (open: boolean) => void
  setEditingNodeId: (nodeId: string | null) => void

  // Window actions
  openWindow: (type: WindowType, data: WindowData, options?: WindowOptions) => void
  openNoteWindow: (noteId: string, title: string, content: string) => void
  closeWindow: (id: string) => void
  moveWindow: (id: string, position: Position) => void
  resizeWindow: (id: string, size: Size) => void
  bringToFront: (id: string) => void

  // 3D Scene actions
  addSceneObject: (obj: Omit<SceneObject, 'id'>) => void
  removeSceneObject: (id: string) => void
  updateSceneObject: (id: string, updates: Partial<SceneObject>) => void
  selectObject: (id: string | null) => void

  // Map actions
  addMap: (map: MapInstance) => void
  removeMap: (mapId: string) => void
  updateMap: (mapId: string, updates: Partial<MapInstance>) => void
  moveMapOnCanvas: (mapId: string, position: Position) => void
  collapseMap: (mapId: string, collapsed: boolean) => void

  // Map node actions
  addMapNode: (mapId: string, node: Omit<MapNode, 'id'>) => string
  updateMapNode: (mapId: string, nodeId: string, updates: Partial<MapNode>) => void
  deleteMapNode: (mapId: string, nodeId: string) => void
  moveMapNode: (mapId: string, nodeId: string, position: Position) => void
  resizeMapNode: (mapId: string, nodeId: string, size: Size) => void

  // Map edge actions
  addMapEdge: (mapId: string, edge: Omit<MapEdge, 'id'>) => string
  deleteMapEdge: (mapId: string, edgeId: string) => void

  // Map selection actions
  selectMapNode: (mapId: string, nodeId: string, additive?: boolean) => void
  selectMapEdge: (mapId: string, edgeId: string) => void
  clearMapSelection: () => void
  startConnection: (mapId: string, nodeId: string, handle: 'top' | 'right' | 'bottom' | 'left') => void
  completeConnection: (targetNodeId: string, targetHandle: 'top' | 'right' | 'bottom' | 'left') => void
  cancelConnection: () => void

  // Scene actions
  saveScene: (name: string, description?: string) => void
  loadScene: (sceneId: string) => void
  deleteScene: (sceneId: string) => void

  // Persistence actions
  saveStateToServer: () => Promise<void>
  loadStateFromServer: () => Promise<void>
  isStateLoaded: boolean
}

const modes: CanvasMode[] = ['notes', 'sketch', 'reference']
const VALID_WINDOW_TYPES = new Set<WindowType>(Object.keys(WINDOW_DEFAULTS) as WindowType[])

// Helper to generate unique IDs
const generateId = () => `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

// Built-in workspace scenes
const BUILT_IN_SCENES: WorkspaceScene[] = [
  {
    id: 'builtin-morning',
    name: 'Morning',
    description: 'Chat + Food logging to start the day',
    windows: [
      { type: 'chat', title: 'Chat with Sara', position: { x: 60, y: 60 }, size: { width: 600, height: 700 }, data: {} },
      { type: 'fitness', title: 'Fitness', position: { x: 700, y: 60 }, size: { width: 600, height: 600 }, data: { initialView: 'food' } },
    ],
    transform: { x: 0, y: 0, scale: 1 },
    isBuiltIn: true,
    suggestedTimePeriods: ['morning'],
  },
  {
    id: 'builtin-focus',
    name: 'Focus',
    description: 'Chat + Projects for deep work',
    windows: [
      { type: 'chat', title: 'Chat with Sara', position: { x: 60, y: 60 }, size: { width: 550, height: 700 }, data: {} },
      { type: 'projects', title: 'Projects', position: { x: 650, y: 60 }, size: { width: 900, height: 700 }, data: {} },
    ],
    transform: { x: 0, y: 0, scale: 1 },
    isBuiltIn: true,
    suggestedTimePeriods: ['morning', 'afternoon'],
  },
  {
    id: 'builtin-learning',
    name: 'Learning',
    description: 'Learning + Notes + Research',
    windows: [
      { type: 'learning', title: 'Learning', position: { x: 60, y: 60 }, size: { width: 700, height: 700 }, data: {} },
      { type: 'note', title: 'Notes', position: { x: 800, y: 60 }, size: { width: 600, height: 400 }, data: {} },
      { type: 'research', title: 'Research', position: { x: 800, y: 500 }, size: { width: 600, height: 400 }, data: {} },
    ],
    transform: { x: 0, y: 0, scale: 1 },
    isBuiltIn: true,
    suggestedTimePeriods: ['afternoon', 'evening'],
  },
  {
    id: 'builtin-winddown',
    name: 'Wind Down',
    description: 'Fitness dashboard + Notes for the evening',
    windows: [
      { type: 'fitness', title: 'Fitness', position: { x: 60, y: 60 }, size: { width: 700, height: 600 }, data: { initialView: 'dashboard' } },
      { type: 'note', title: 'Notes', position: { x: 800, y: 60 }, size: { width: 600, height: 600 }, data: {} },
    ],
    transform: { x: 0, y: 0, scale: 1 },
    isBuiltIn: true,
    suggestedTimePeriods: ['evening', 'night'],
  },
]

const normalizeWindowType = (rawType: string): WindowType => {
  const normalized = rawType === 'learn' ? 'learning' : rawType
  if (VALID_WINDOW_TYPES.has(normalized as WindowType)) {
    return normalized as WindowType
  }
  return 'note'
}

// Debounced auto-save for window state changes
let autoSaveTimeout: NodeJS.Timeout | null = null
const AUTO_SAVE_DELAY = 2000 // 2 seconds debounce

const scheduleAutoSave = () => {
  if (autoSaveTimeout) {
    clearTimeout(autoSaveTimeout)
  }
  autoSaveTimeout = setTimeout(async () => {
    const store = useCanvasStore.getState()
    if (store.isStateLoaded) {
      console.log('[canvasStore] Auto-saving window state...')
      await store.saveStateToServer()
    }
  }, AUTO_SAVE_DELAY)
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  // Initial state
  transform: { x: 0, y: 0, scale: 1 },
  mode: 'notes',
  isNotesPickerOpen: false,
  isMapPickerOpen: false,
  isMapImportModalOpen: false,
  editingNodeId: null,
  windows: [],
  maxZIndex: 0,
  isStateLoaded: false,
  sceneObjects: [],
  selectedObjectId: null,
  maps: [],
  mapSelection: null,
  scenes: [],
  activeSceneId: null,

  // Transform actions
  setTransform: (newTransform) => {
    set((state) => ({
      transform: { ...state.transform, ...newTransform },
    }))
  },

  resetTransform: () => {
    set({ transform: { x: 0, y: 0, scale: 1 } })
  },

  zoom: (delta, centerX, centerY) => {
    set((state) => {
      const { minZoom, maxZoom } = APP_CONFIG.canvas
      const newScale = Math.min(maxZoom, Math.max(minZoom, state.transform.scale * (1 + delta)))

      // Zoom toward cursor position
      const scaleRatio = newScale / state.transform.scale
      const newX = centerX - (centerX - state.transform.x) * scaleRatio
      const newY = centerY - (centerY - state.transform.y) * scaleRatio

      return {
        transform: { x: newX, y: newY, scale: newScale },
      }
    })
  },

  pan: (dx, dy) => {
    set((state) => ({
      transform: {
        ...state.transform,
        x: state.transform.x + dx,
        y: state.transform.y + dy,
      },
    }))
  },

  // Mode actions
  setMode: (mode) => {
    set({ mode })
    // Open notes picker when entering notes mode
    if (mode === 'notes') {
      set({ isNotesPickerOpen: true })
    }
  },

  cycleMode: () => {
    set((state) => {
      const currentIndex = modes.indexOf(state.mode)
      const nextIndex = (currentIndex + 1) % modes.length
      const nextMode = modes[nextIndex]
      return {
        mode: nextMode,
        isNotesPickerOpen: nextMode === 'notes',
      }
    })
  },

  // UI actions
  setNotesPickerOpen: (open) => set({ isNotesPickerOpen: open }),
  toggleNotesPicker: () => set((state) => ({ isNotesPickerOpen: !state.isNotesPickerOpen })),
  setMapPickerOpen: (open) => set({ isMapPickerOpen: open }),
  setMapImportModalOpen: (open) => set({ isMapImportModalOpen: open }),
  setEditingNodeId: (nodeId) => set({ editingNodeId: nodeId }),

  // Window actions
  openWindow: (type, data, options = {}) => {
    const state = get()
    const defaults = WINDOW_DEFAULTS[type]
    const newZIndex = state.maxZIndex + 1

    // Calculate position (offset from center based on number of windows)
    const offset = state.windows.length * 30
    const position = options.position || {
      x: 100 + offset,
      y: 100 + offset,
    }

    const newWindow: WindowInstance = {
      id: `${type}-${Date.now()}`,
      type,
      title: options.title || defaults.title,
      position,
      size: {
        width: options.width || defaults.width,
        height: options.height || defaults.height,
      },
      zIndex: newZIndex,
      data,
    }

    set({
      windows: [...state.windows, newWindow],
      maxZIndex: newZIndex,
    })
    scheduleAutoSave()
  },

  openNoteWindow: (noteId, title, content) => {
    const state = get()

    // Check if note is already open
    const existing = state.windows.find(
      (w) => w.type === 'note' && (w.data as NoteWindowData).noteId === noteId
    )
    if (existing) {
      // Bring existing window to front
      get().bringToFront(existing.id)
      return
    }

    const newZIndex = state.maxZIndex + 1
    const defaults = WINDOW_DEFAULTS.note

    // Calculate position (offset from center based on number of windows)
    const offset = state.windows.length * 30
    const position = {
      x: 100 + offset,
      y: 100 + offset,
    }

    const newWindow: WindowInstance = {
      id: `note-${noteId}-${Date.now()}`,
      type: 'note',
      title,
      position,
      size: { width: defaults.width, height: defaults.height },
      zIndex: newZIndex,
      data: { noteId, title, content },
    }

    set({
      windows: [...state.windows, newWindow],
      maxZIndex: newZIndex,
      isNotesPickerOpen: false, // Close picker after opening note
    })
    scheduleAutoSave()
  },

  closeWindow: (id) => {
    set((state) => ({
      windows: state.windows.filter((w) => w.id !== id),
    }))
    scheduleAutoSave()
  },

  moveWindow: (id, position) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === id ? { ...w, position } : w
      ),
    }))
    scheduleAutoSave()
  },

  resizeWindow: (id, size) => {
    const { minWidth, minHeight } = APP_CONFIG.window
    const constrainedSize = {
      width: Math.max(minWidth, size.width),
      height: Math.max(minHeight, size.height),
    }
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === id ? { ...w, size: constrainedSize } : w
      ),
    }))
    scheduleAutoSave()
  },

  bringToFront: (id) => {
    set((state) => {
      const newZIndex = state.maxZIndex + 1
      return {
        maxZIndex: newZIndex,
        windows: state.windows.map((w) =>
          w.id === id ? { ...w, zIndex: newZIndex } : w
        ),
      }
    })
  },

  // 3D Scene actions
  addSceneObject: (obj) => {
    const newObject: SceneObject = {
      ...obj,
      id: `scene-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
    }
    set((state) => ({
      sceneObjects: [...state.sceneObjects, newObject],
    }))
  },

  removeSceneObject: (id) => {
    set((state) => ({
      sceneObjects: state.sceneObjects.filter((obj) => obj.id !== id),
      selectedObjectId: state.selectedObjectId === id ? null : state.selectedObjectId,
    }))
  },

  updateSceneObject: (id, updates) => {
    set((state) => ({
      sceneObjects: state.sceneObjects.map((obj) =>
        obj.id === id ? { ...obj, ...updates } : obj
      ),
    }))
  },

  selectObject: (id) => {
    set({ selectedObjectId: id })
  },

  // Map actions
  addMap: (map) => {
    set((state) => ({
      maps: [...state.maps, map],
      isMapPickerOpen: false,
    }))
  },

  removeMap: (mapId) => {
    set((state) => {
      // Check if the node being edited belongs to this map
      const map = state.maps.find((m) => m.id === mapId)
      const isEditingThisMap = map && state.editingNodeId &&
        map.mapData.nodes.some((n) => n.id === state.editingNodeId)

      return {
        maps: state.maps.filter((m) => m.id !== mapId),
        mapSelection: state.mapSelection?.mapId === mapId ? null : state.mapSelection,
        editingNodeId: isEditingThisMap ? null : state.editingNodeId,
      }
    })
  },

  updateMap: (mapId, updates) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId ? { ...m, ...updates } : m
      ),
    }))
  },

  moveMapOnCanvas: (mapId, position) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId ? { ...m, canvasPosition: position } : m
      ),
    }))
  },

  collapseMap: (mapId, collapsed) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId ? { ...m, collapsed } : m
      ),
    }))
  },

  // Map node actions
  addMapNode: (mapId, node) => {
    const nodeId = generateId()
    const newNode: MapNode = { ...node, id: nodeId }

    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? { ...m, mapData: { ...m.mapData, nodes: [...m.mapData.nodes, newNode] } }
          : m
      ),
    }))

    return nodeId
  },

  updateMapNode: (mapId, nodeId, updates) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? {
              ...m,
              mapData: {
                ...m.mapData,
                nodes: m.mapData.nodes.map((n) =>
                  n.id === nodeId ? { ...n, ...updates } : n
                ),
              },
            }
          : m
      ),
    }))
  },

  deleteMapNode: (mapId, nodeId) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? {
              ...m,
              mapData: {
                nodes: m.mapData.nodes.filter((n) => n.id !== nodeId),
                edges: m.mapData.edges.filter(
                  (e) => e.source !== nodeId && e.target !== nodeId
                ),
              },
            }
          : m
      ),
      mapSelection:
        state.mapSelection?.nodeIds.includes(nodeId)
          ? {
              ...state.mapSelection,
              nodeIds: state.mapSelection.nodeIds.filter((id) => id !== nodeId),
            }
          : state.mapSelection,
    }))
  },

  moveMapNode: (mapId, nodeId, position) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? {
              ...m,
              mapData: {
                ...m.mapData,
                nodes: m.mapData.nodes.map((n) =>
                  n.id === nodeId ? { ...n, position } : n
                ),
              },
            }
          : m
      ),
    }))
  },

  resizeMapNode: (mapId, nodeId, size) => {
    const minWidth = 100
    const minHeight = 50
    const constrainedSize = {
      width: Math.max(minWidth, size.width),
      height: Math.max(minHeight, size.height),
    }

    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? {
              ...m,
              mapData: {
                ...m.mapData,
                nodes: m.mapData.nodes.map((n) =>
                  n.id === nodeId ? { ...n, size: constrainedSize } : n
                ),
              },
            }
          : m
      ),
    }))
  },

  // Map edge actions
  addMapEdge: (mapId, edge) => {
    const edgeId = generateId()
    const newEdge: MapEdge = {
      ...edge,
      id: edgeId,
      sourceHandle: edge.sourceHandle || 'right',
      targetHandle: edge.targetHandle || 'left',
      style: edge.style || { curved: true },
    }

    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? { ...m, mapData: { ...m.mapData, edges: [...m.mapData.edges, newEdge] } }
          : m
      ),
    }))

    return edgeId
  },

  deleteMapEdge: (mapId, edgeId) => {
    set((state) => ({
      maps: state.maps.map((m) =>
        m.id === mapId
          ? {
              ...m,
              mapData: {
                ...m.mapData,
                edges: m.mapData.edges.filter((e) => e.id !== edgeId),
              },
            }
          : m
      ),
      mapSelection:
        state.mapSelection?.edgeIds.includes(edgeId)
          ? {
              ...state.mapSelection,
              edgeIds: state.mapSelection.edgeIds.filter((id) => id !== edgeId),
            }
          : state.mapSelection,
    }))
  },

  // Map selection actions
  selectMapNode: (mapId, nodeId, additive = false) => {
    set((state) => {
      if (additive && state.mapSelection?.mapId === mapId) {
        // Toggle selection in additive mode
        const isSelected = state.mapSelection.nodeIds.includes(nodeId)
        return {
          mapSelection: {
            ...state.mapSelection,
            nodeIds: isSelected
              ? state.mapSelection.nodeIds.filter((id) => id !== nodeId)
              : [...state.mapSelection.nodeIds, nodeId],
            edgeIds: [],
          },
        }
      }
      // Single selection
      return {
        mapSelection: {
          mapId,
          nodeIds: [nodeId],
          edgeIds: [],
        },
      }
    })
  },

  selectMapEdge: (mapId, edgeId) => {
    set({
      mapSelection: {
        mapId,
        nodeIds: [],
        edgeIds: [edgeId],
      },
    })
  },

  clearMapSelection: () => {
    set({ mapSelection: null })
  },

  startConnection: (mapId, nodeId, handle) => {
    set((state) => ({
      mapSelection: {
        mapId,
        nodeIds: [nodeId],
        edgeIds: [],
        connectionSource: nodeId,
        sourceHandle: handle,
      },
    }))
  },

  completeConnection: (targetNodeId, targetHandle) => {
    const state = get()
    const selection = state.mapSelection
    if (!selection?.connectionSource || selection.connectionSource === targetNodeId) {
      // Cancel if no source or trying to connect to self
      set({ mapSelection: { ...selection!, connectionSource: undefined, sourceHandle: undefined } })
      return
    }

    // Add the edge with handle positions
    const edgeId = state.addMapEdge(selection.mapId, {
      source: selection.connectionSource,
      target: targetNodeId,
      sourceHandle: selection.sourceHandle,
      targetHandle: targetHandle,
    })

    // Clear connection mode
    set({
      mapSelection: {
        mapId: selection.mapId,
        nodeIds: [],
        edgeIds: [edgeId],
      },
    })
  },

  cancelConnection: () => {
    set((state) => ({
      mapSelection: state.mapSelection
        ? { ...state.mapSelection, connectionSource: undefined }
        : null,
    }))
  },

  // Scene actions
  saveScene: (name, description) => {
    const state = get()
    const scene: WorkspaceScene = {
      id: `scene-${Date.now()}`,
      name,
      description,
      windows: state.windows.map(w => ({
        type: w.type,
        title: w.title,
        position: { ...w.position },
        size: { ...w.size },
        data: w.data,
      })),
      transform: { ...state.transform },
      isBuiltIn: false,
    }
    set({ scenes: [...state.scenes, scene], activeSceneId: scene.id })
    scheduleAutoSave()
  },

  loadScene: (sceneId) => {
    const state = get()
    const scene = state.scenes.find(s => s.id === sceneId)
    if (!scene) return

    // Replace all windows with scene windows
    const newWindows: WindowInstance[] = scene.windows.map((w, i) => ({
      id: `${w.type}-scene-${Date.now()}-${i}`,
      type: w.type,
      title: w.title,
      position: { ...w.position },
      size: { ...w.size },
      zIndex: i + 1,
      data: w.data,
    }))

    set({
      windows: newWindows,
      transform: { ...scene.transform },
      maxZIndex: newWindows.length,
      activeSceneId: sceneId,
    })
    scheduleAutoSave()
  },

  deleteScene: (sceneId) => {
    const state = get()
    const scene = state.scenes.find(s => s.id === sceneId)
    if (!scene || scene.isBuiltIn) return
    set({
      scenes: state.scenes.filter(s => s.id !== sceneId),
      activeSceneId: state.activeSceneId === sceneId ? null : state.activeSceneId,
    })
    scheduleAutoSave()
  },

  // Persistence actions
  saveStateToServer: async () => {
    const state = get()
    const stateData: WorkspaceStateData = {
      transform: state.transform,
      windows: state.windows.map(w => ({
        id: w.id,
        type: w.type,
        title: w.title,
        position: w.position,
        size: w.size,
        zIndex: w.zIndex,
        data: w.data,
      })),
      sceneObjects: state.sceneObjects.map(obj => ({
        id: obj.id,
        modelId: obj.modelId,
        modelUrl: obj.modelUrl,
        format: obj.format,
        position: obj.position,
        rotation: obj.rotation,
        scale: obj.scale,
        filename: obj.filename,
      })),
      visibleMaps: state.maps.map(m => ({
        mapId: m.id,
        position: m.canvasPosition,
        collapsed: m.collapsed,
      })),
      scenes: state.scenes.filter(s => !s.isBuiltIn).map(s => ({
        id: s.id,
        name: s.name,
        description: s.description,
        windows: s.windows.map(w => ({
          type: w.type,
          title: w.title,
          position: w.position,
          size: w.size,
          data: w.data,
        })),
        transform: s.transform,
        isBuiltIn: false,
        suggestedTimePeriods: s.suggestedTimePeriods,
      })),
      activeSceneId: state.activeSceneId,
    }
    try {
      await workspaceApi.saveState(stateData)
      // Also save each map's data to the backend
      for (const map of state.maps) {
        try {
          await mapsApi.update(map.id, {
            map_data: map.mapData,
          })
        } catch (e) {
          console.error(`[canvasStore] Failed to save map ${map.id}:`, e)
        }
      }
      console.log('[canvasStore] State saved to server')
    } catch (error) {
      console.error('[canvasStore] Failed to save state:', error)
    }
  },

  loadStateFromServer: async () => {
    try {
      const response = await workspaceApi.getState()
      const hasData = response.state_data && (
        response.state_data.windows?.length > 0 ||
        response.state_data.sceneObjects?.length ||
        response.state_data.visibleMaps?.length
      )

      if (hasData) {
        const { transform, windows, sceneObjects, visibleMaps, scenes: savedScenes, activeSceneId: savedActiveSceneId } = response.state_data! as any
        // Find max zIndex from loaded windows
        const maxZ = (windows || []).reduce((max, w) => Math.max(max, w.zIndex || 0), 0)

        // Map loaded windows back to WindowInstance format
        const loadedWindows: WindowInstance[] = (windows || []).map(w => ({
          id: w.id,
          type: normalizeWindowType(w.type),
          title: w.title,
          position: w.position,
          size: w.size,
          zIndex: w.zIndex || 0,
          data: w.data || {},
        }))

        // Map loaded scene objects back to SceneObject format
        const loadedSceneObjects: SceneObject[] = (sceneObjects || []).map(obj => ({
          id: obj.id,
          modelId: obj.modelId,
          modelUrl: obj.modelUrl,
          format: obj.format as ModelFormat,
          position: obj.position,
          rotation: obj.rotation,
          scale: obj.scale,
          filename: obj.filename,
        }))

        // Load visible maps from backend
        const loadedMaps: MapInstance[] = []
        if (visibleMaps?.length) {
          for (const vm of visibleMaps) {
            try {
              const mapData = await mapsApi.get(vm.mapId)
              loadedMaps.push({
                id: mapData.id,
                name: mapData.name,
                description: mapData.description,
                mapData: mapData.map_data,
                isReadonly: mapData.is_readonly,
                canvasPosition: vm.position,
                collapsed: vm.collapsed,
              })
            } catch (e) {
              console.error(`[canvasStore] Failed to load map ${vm.mapId}:`, e)
            }
          }
        }

        // Load user-saved scenes and merge with built-in scenes
        const userScenes: WorkspaceScene[] = (savedScenes || []).map((s: any) => ({
          id: s.id,
          name: s.name,
          description: s.description,
          windows: s.windows || [],
          transform: s.transform || { x: 0, y: 0, scale: 1 },
          isBuiltIn: false,
          suggestedTimePeriods: s.suggestedTimePeriods,
        }))
        const allScenes = [...BUILT_IN_SCENES, ...userScenes]

        set({
          transform: transform || { x: 0, y: 0, scale: 1 },
          windows: loadedWindows,
          sceneObjects: loadedSceneObjects,
          maps: loadedMaps,
          maxZIndex: maxZ,
          scenes: allScenes,
          activeSceneId: savedActiveSceneId || null,
          isStateLoaded: true,
        })
        console.log('[canvasStore] State loaded from server:', loadedWindows.length, 'windows,', loadedSceneObjects.length, 'scene objects,', loadedMaps.length, 'maps,', allScenes.length, 'scenes')
      } else {
        set({ isStateLoaded: true, scenes: [...BUILT_IN_SCENES] })
        console.log('[canvasStore] No saved state found, loaded built-in scenes')
      }
    } catch (error) {
      console.error('[canvasStore] Failed to load state:', error)
      set({ isStateLoaded: true })
    }
  },
}))

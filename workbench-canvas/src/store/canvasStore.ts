import { create } from 'zustand'
import { APP_CONFIG } from '../config'
import type { CanvasTransform, CanvasMode, WindowInstance, Position, Size, NoteWindowData, WindowType, WindowData } from '../types'

// Window defaults for each type
const WINDOW_DEFAULTS: Record<WindowType, { width: number; height: number; title: string }> = {
  note: { width: 500, height: 400, title: 'Note' },
  chat: { width: 600, height: 700, title: 'Chat with Sara' },
  fitness: { width: 800, height: 600, title: 'Fitness' },
  projects: { width: 900, height: 700, title: 'Projects' },
  timers: { width: 400, height: 350, title: 'Timers' },
  settings: { width: 700, height: 600, title: 'Settings' },
  fileviewer: { width: 700, height: 600, title: 'File Viewer' },
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

  // Windows
  windows: WindowInstance[]
  maxZIndex: number

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

  // Window actions
  openWindow: (type: WindowType, data: WindowData, options?: WindowOptions) => void
  openNoteWindow: (noteId: string, title: string, content: string) => void
  closeWindow: (id: string) => void
  moveWindow: (id: string, position: Position) => void
  resizeWindow: (id: string, size: Size) => void
  bringToFront: (id: string) => void
}

const modes: CanvasMode[] = ['notes', 'sketch', 'reference']

export const useCanvasStore = create<CanvasState>((set, get) => ({
  // Initial state
  transform: { x: 0, y: 0, scale: 1 },
  mode: 'notes',
  isNotesPickerOpen: false,
  windows: [],
  maxZIndex: 0,

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
  },

  closeWindow: (id) => {
    set((state) => ({
      windows: state.windows.filter((w) => w.id !== id),
    }))
  },

  moveWindow: (id, position) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === id ? { ...w, position } : w
      ),
    }))
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
}))

import { useCanvasStore } from '../store/canvasStore'
import type { WindowType } from '../types'
import { workspaceApi } from './api'

const WINDOW_TYPE_MAP: Record<string, WindowType> = {
  notes: 'note',
  note: 'note',
  note_editor: 'note',
  chat: 'chat',
  learning: 'learning',
  learn: 'learning',
  fitness: 'fitness',
  settings: 'settings',
  projects: 'projects',
  timers: 'timers',
  research: 'research',
  report: 'report',
  email: 'email',
  documents: 'documents',
  fileviewer: 'fileviewer',
  modelviewer: 'modelviewer',
  automation: 'automation',
  pkg: 'pkg',
}

function normalizeWindowType(raw?: string): WindowType {
  return WINDOW_TYPE_MAP[(raw || '').toLowerCase()] || 'note'
}

const RECENT_WINDOW_OPEN = new Map<string, number>()
const RECENT_OPEN_TTL_MS = 5000

function getWindowIdentity(type: WindowType, title?: string, data?: any): string {
  if (type === 'email' && data?.emailId) return `email:${data.emailId}`
  if (type === 'note' && data?.note_id) return `note:${data.note_id}`
  if (type === 'documents' && data?.initialQuery) return `documents:q:${String(data.initialQuery).toLowerCase()}`
  if (type === 'email' && data?.initialQuery) return `email:q:${String(data.initialQuery).toLowerCase()}`
  return `${type}:${(title || '').toLowerCase()}`
}

function shouldSkipRecentOpen(identity: string): boolean {
  const now = Date.now()
  for (const [key, ts] of RECENT_WINDOW_OPEN.entries()) {
    if (now - ts > RECENT_OPEN_TTL_MS) RECENT_WINDOW_OPEN.delete(key)
  }
  const last = RECENT_WINDOW_OPEN.get(identity)
  if (last && now - last <= RECENT_OPEN_TTL_MS) {
    return true
  }
  RECENT_WINDOW_OPEN.set(identity, now)
  return false
}

function arrangeWindows(arrangement: 'tile' | 'cascade' | 'stack' | 'center') {
  const state = useCanvasStore.getState()
  const windows = [...state.windows]
  if (windows.length === 0) return

  if (arrangement === 'cascade') {
    windows.forEach((w, i) => state.moveWindow(w.id, { x: 80 + i * 36, y: 80 + i * 28 }))
    return
  }

  if (arrangement === 'stack') {
    windows.forEach((w, i) => state.moveWindow(w.id, { x: 120, y: 80 + i * 56 }))
    return
  }

  if (arrangement === 'center') {
    windows.forEach((w, i) => state.moveWindow(w.id, { x: 320 + i * 20, y: 180 + i * 20 }))
    return
  }

  // tile
  const cols = Math.max(1, Math.ceil(Math.sqrt(windows.length)))
  const cellW = 440
  const cellH = 280
  windows.forEach((w, i) => {
    const row = Math.floor(i / cols)
    const col = i % cols
    state.moveWindow(w.id, { x: 60 + col * cellW, y: 60 + row * cellH })
  })
}

export function executeWorkspaceCommand(data: any, source: string = 'workspace') {
  if (!data || typeof data !== 'object') return

  if (Array.isArray(data.workspace_commands)) {
    for (const cmd of data.workspace_commands) {
      executeWorkspaceCommand(cmd, source)
    }
    return
  }

  const command = data.workspace_command
  const state = useCanvasStore.getState()
  const { openWindow, closeWindow, bringToFront, windows, addMap, updateMap, removeMap, collapseMap } = state

  switch (command) {
    case 'open_window': {
      if (data.window_type === 'note_editor' && data.data?.note_id) {
        state.openNoteWindow(data.data.note_id, data.data.title || data.title || 'Note', data.data.content || '')
        return
      }
      const windowType = normalizeWindowType(data.window_type)
      const identity = getWindowIdentity(windowType, data.title, data.data)

      // Reuse existing matching window where possible instead of opening duplicates
      const existing = windows.find((w: any) => {
        const wd = w.data as any
        if (windowType === 'email' && data.data?.emailId) {
          return w.type === 'email' && wd?.emailId === data.data.emailId
        }
        if (windowType === 'documents' && data.data?.initialQuery) {
          return w.type === 'documents' && String(wd?.initialQuery || '').toLowerCase() === String(data.data.initialQuery).toLowerCase()
        }
        return w.type === windowType && w.title === (data.title || w.title)
      })
      if (existing) {
        bringToFront(existing.id)
        return
      }

      if (shouldSkipRecentOpen(identity)) {
        return
      }
      openWindow(windowType, data.data || {}, { title: data.title })
      return
    }

    case 'close_window': {
      if (data.window_id) {
        closeWindow(data.window_id)
      } else if (data.window_title) {
        const target = windows.find((w) => w.title.toLowerCase().includes(String(data.window_title).toLowerCase()))
        if (target) closeWindow(target.id)
      }
      return
    }

    case 'focus_window': {
      if (data.window_id) {
        bringToFront(data.window_id)
      } else if (data.window_title) {
        const target = windows.find((w) => w.title.toLowerCase().includes(String(data.window_title).toLowerCase()))
        if (target) bringToFront(target.id)
      }
      return
    }

    case 'save_state': {
      state.saveStateToServer().catch((err) => console.error('[workspaceCommands] save_state failed:', err))
      return
    }

    case 'arrange_windows': {
      const arrangement = data.arrangement || 'tile'
      arrangeWindows(arrangement)
      return
    }

    case 'show_map':
    case 'update_map': {
      const mapData = data.map
      if (!mapData) return
      const existing = useCanvasStore.getState().maps.find((m) => m.id === mapData.id)
      if (existing) {
        updateMap(mapData.id, {
          mapData: mapData.map_data,
          collapsed: data.collapsed ?? existing.collapsed,
        })
      } else {
        addMap({
          id: mapData.id,
          name: mapData.name,
          description: mapData.description,
          mapData: mapData.map_data,
          isReadonly: mapData.is_readonly || false,
          canvasPosition: data.position || { x: 200, y: 200 },
          collapsed: data.collapsed || false,
        })
      }
      return
    }

    case 'hide_map':
      if (data.map_id) removeMap(data.map_id)
      return

    case 'collapse_map':
      if (data.map_id) collapseMap(data.map_id, true)
      return

    default:
      console.warn(`[workspaceCommands] Unknown command from ${source}:`, command, data)
  }
}

export async function pollPendingWorkspaceCommands(source: string = 'workspace') {
  try {
    const result = await workspaceApi.getPendingCommands()
    if (result.commands?.length) {
      for (const cmd of result.commands) {
        executeWorkspaceCommand(cmd, source)
      }
    }
  } catch {
    // intentionally silent polling failure
  }
}

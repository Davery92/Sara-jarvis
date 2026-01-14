// Canvas types
export interface CanvasTransform {
  x: number
  y: number
  scale: number
}

export type CanvasMode = 'notes' | 'sketch' | 'reference'

// Window types
export type WindowType = 'note' | 'chat' | 'fitness' | 'projects' | 'timers' | 'settings' | 'fileviewer'

export interface Position {
  x: number
  y: number
}

export interface Size {
  width: number
  height: number
}

export interface WindowInstance {
  id: string
  type: WindowType
  title: string
  position: Position
  size: Size
  zIndex: number
  data: WindowData
}

// Window data types
export interface NoteWindowData {
  noteId?: string
  title?: string
  content?: string
}

export interface ChatWindowData {
  conversationId?: string
}

export interface FitnessWindowData {
  initialView?: 'dashboard' | 'food' | 'workout' | 'recovery' | 'programs'
}

export interface ProjectsWindowData {
  projectId?: string
}

export interface TimersWindowData {}

export interface SettingsWindowData {
  section?: 'ai' | 'devices' | 'tokens'
}

export interface FileViewerWindowData {
  filename: string
  content: string
  mimeType?: string
  source?: 'project' | 'local' // Where the file came from
  projectId?: string
  fileId?: string
}

export type WindowData =
  | NoteWindowData
  | ChatWindowData
  | FitnessWindowData
  | ProjectsWindowData
  | TimersWindowData
  | SettingsWindowData
  | FileViewerWindowData

// API types
export interface Note {
  id: string
  title: string
  content: string
  folder_id: string | null
  user_id?: string
  created_at: string
  updated_at: string
}

export interface Folder {
  id: string
  name: string
  parent_id: string | null
  notes_count: number
  subfolders_count: number
  created_at: string
  updated_at: string
}

export interface User {
  id: string
  email: string
  created_at: string
}

export interface LoginResponse {
  id: string
  email: string
  created_at: string
  access_token: string
}

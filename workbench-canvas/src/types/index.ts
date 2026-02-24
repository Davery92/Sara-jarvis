// Canvas types
export interface CanvasTransform {
  x: number
  y: number
  scale: number
}

export type CanvasMode = 'notes' | 'sketch' | 'reference'

// 3D Scene Object types
export interface Position3D {
  x: number
  y: number
  z: number
}

export interface Rotation3D {
  x: number
  y: number
  z: number
}

export type ModelFormat = 'stl' | 'obj' | 'gltf' | 'glb'

export interface SceneObject {
  id: string
  modelId: string           // Reference to backend model
  modelUrl: string          // API URL for the model file
  format: ModelFormat
  position: Position3D
  rotation: Rotation3D
  scale: number             // Uniform scale factor
  filename: string
}

// Window types
export type WindowType = 'note' | 'chat' | 'learning' | 'fitness' | 'projects' | 'timers' | 'settings' | 'fileviewer' | 'modelviewer' | 'research' | 'report' | 'email' | 'documents' | 'automation' | 'pkg' | 'intelligence' | 'temerant'

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
  initialQuery?: string
}

export interface ChatWindowData {
  conversationId?: string
}

export interface LearningWindowData {
  topicId?: string
  initialTab?: 'chat' | 'library'
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

export interface ModelViewerWindowData {
  modelId: string
  filename: string
  modelUrl: string
  format: 'stl' | 'obj' | 'gltf' | 'glb'
}

export interface ResearchWindowData {
  initialQuery?: string
  mode?: 'simple' | 'deep'
}

export interface ReportWindowData {
  title?: string
  content: string
}

export interface EmailWindowData {
  emailId?: string
  initialQuery?: string
}

export interface DocumentsWindowData {
  initialQuery?: string
}

export interface AutomationWindowData {
  taskId?: string  // Optional: open specific task details
  initialTab?: 'list' | 'endpoints'  // Which view to show
}

export type WindowData =
  | NoteWindowData
  | ChatWindowData
  | LearningWindowData
  | FitnessWindowData
  | ProjectsWindowData
  | TimersWindowData
  | SettingsWindowData
  | FileViewerWindowData
  | ModelViewerWindowData
  | ResearchWindowData
  | ReportWindowData
  | EmailWindowData
  | DocumentsWindowData
  | AutomationWindowData
  | PKGWindowData
  | IntelligenceWindowData
  | TemerantWindowData

export interface PKGWindowData {
  category?: string  // Filter by category on open
}

export interface IntelligenceWindowData {
  sourceCategory?: string  // Filter by source category on open
}

export interface TemerantWindowData {
  focus?: 'dashboard' | 'oracle' | 'journal'
}

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

// Map types (mindmaps/flowcharts)
export type MapNodeContentType = 'text' | 'image' | 'code' | 'embed'

export interface MapNodeContent {
  type: MapNodeContentType
  data: {
    text?: string
    imageUrl?: string
    code?: string
    language?: string
    embedUrl?: string
    embedType?: string
  }
}

export interface MapNodeStyle {
  backgroundColor?: string
  borderColor?: string
  borderWidth?: number
  borderRadius?: number
}

export interface MapNode {
  id: string
  position: Position
  size: Size
  content: MapNodeContent
  style?: MapNodeStyle
}

export interface MapEdgeStyle {
  strokeColor?: string
  strokeWidth?: number
  curved?: boolean
}

export type HandlePosition = 'top' | 'right' | 'bottom' | 'left'

export interface MapEdge {
  id: string
  source: string
  target: string
  sourceHandle?: HandlePosition
  targetHandle?: HandlePosition
  style?: MapEdgeStyle
}

export interface MapData {
  nodes: MapNode[]
  edges: MapEdge[]
}

export interface MapInstance {
  id: string
  name: string
  description?: string
  mapData: MapData
  isReadonly: boolean
  canvasPosition: Position  // Where on the infinite canvas
  collapsed: boolean        // Whether showing as icon
}

export interface MapSelection {
  mapId: string
  nodeIds: string[]
  edgeIds: string[]
  connectionSource?: string  // Node ID being connected from
  sourceHandle?: HandlePosition  // Which handle on source node
}

// API response types for maps
export interface MapResponse {
  id: string
  user_id: string
  name: string
  description?: string
  map_data: MapData
  is_readonly: boolean
  import_source?: string
  created_at: string
  updated_at: string
}

export interface MapSummary {
  id: string
  name: string
  description?: string
  is_readonly: boolean
  node_count: number
  edge_count: number
  created_at: string
  updated_at: string
}

// Visible map state for workspace persistence
export interface VisibleMapState {
  mapId: string
  position: Position
  collapsed: boolean
}

// Workspace scenes
export interface WorkspaceScene {
  id: string
  name: string
  description?: string
  windows: Array<{
    type: WindowType
    title: string
    position: Position
    size: Size
    data: WindowData
  }>
  transform: CanvasTransform
  isBuiltIn: boolean
  suggestedTimePeriods?: string[] // 'morning' | 'afternoon' | 'evening' | 'night'
}

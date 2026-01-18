import axios from 'axios'
import { APP_CONFIG } from '../config'
import type { Note, User, LoginResponse } from '../types'

// Create axios instance with default config
const api = axios.create({
  baseURL: APP_CONFIG.apiUrl,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Include cookies for auth
})

// Token storage
let authToken: string | null = localStorage.getItem('workbench_token')

// Add auth header to requests
api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      authToken = null
      localStorage.removeItem('workbench_token')
    }
    return Promise.reject(error)
  }
)

// Auth functions
export const setToken = (token: string | null) => {
  authToken = token
  if (token) {
    localStorage.setItem('workbench_token', token)
  } else {
    localStorage.removeItem('workbench_token')
  }
}

export const getToken = () => authToken

export const authApi = {
  login: async (email: string, password: string): Promise<LoginResponse> => {
    const response = await api.post<LoginResponse>('/auth/login', { email, password })
    setToken(response.data.access_token)
    return response.data
  },

  logout: async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // Ignore errors on logout
    }
    setToken(null)
  },

  me: async (): Promise<User> => {
    const response = await api.get<User>('/auth/me')
    return response.data
  },
}

// Notes functions
export const notesApi = {
  list: async (): Promise<Note[]> => {
    const response = await api.get<Note[]>('/notes')
    return response.data
  },

  get: async (id: string): Promise<Note> => {
    const response = await api.get<Note>(`/notes/${id}`)
    return response.data
  },

  create: async (title: string, content: string, folderId?: string | null): Promise<Note> => {
    const response = await api.post<Note>('/notes', { title, content, folder_id: folderId })
    return response.data
  },

  update: async (id: string, data: { title?: string; content?: string; folder_id?: string | null }): Promise<Note> => {
    const response = await api.put<Note>(`/notes/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/notes/${id}`)
  },

  search: async (query: string): Promise<Note[]> => {
    const response = await api.get<Note[]>('/api/notes/search', {
      params: { q: query },
    })
    return response.data
  },
}

// Folder types
export interface Folder {
  id: string
  name: string
  parent_id: string | null
  notes_count: number
  subfolders_count: number
  created_at: string
  updated_at: string
}

export interface TreeNode {
  id: string
  name: string
  type: 'folder' | 'note'
  parent_id: string | null
  created_at: string
  updated_at: string
  children: TreeNode[]
}

// Folders functions
export const foldersApi = {
  list: async (): Promise<Folder[]> => {
    const response = await api.get<Folder[]>('/folders')
    return response.data
  },

  getTree: async (): Promise<TreeNode[]> => {
    const response = await api.get<{ tree: TreeNode[] }>('/folders/tree')
    return response.data.tree || []
  },

  create: async (name: string, parentId?: string | null): Promise<Folder> => {
    const response = await api.post<Folder>('/folders', { name, parent_id: parentId })
    return response.data
  },

  update: async (id: string, data: { name?: string; parent_id?: string | null }): Promise<Folder> => {
    const response = await api.put<Folder>(`/folders/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/folders/${id}`)
  },
}

// Chat types
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface StreamEvent {
  type: 'content' | 'text_chunk' | 'tool_start' | 'tool_end' | 'done' | 'final_response' | 'response_ready' | 'error' | 'workspace_command'
  content?: string
  data?: { content?: string; workspace_command?: string; [key: string]: any }
  tool?: string
  tool_input?: any
  tool_result?: any
  error?: string
}

export interface ChatModel {
  id: string
  name: string
  provider: 'anthropic' | 'google' | 'local'
}

export interface ChatModelsResponse {
  models: ChatModel[]
  default: string
}

export interface ChatOptions {
  model?: string
  ephemeral?: boolean
}

// Chat functions with SSE streaming
export const chatApi = {
  getModels: async (): Promise<ChatModelsResponse> => {
    const response = await api.get<ChatModelsResponse>('/chat/models')
    return response.data
  },

  sendMessage: async (
    messages: ChatMessage[],
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
    options?: ChatOptions
  ): Promise<void> => {
    console.log('[chatApi] sendMessage called, url:', `${APP_CONFIG.apiUrl}/chat/stream`, 'model:', options?.model)
    const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: JSON.stringify({
        messages,
        model: options?.model,
        ephemeral: options?.ephemeral,
        source: 'workspace', // Identify as workspace chat for context-aware tools
      }),
      signal,
      credentials: 'include', // Include cookies for auth
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body reader available')
    }

    const decoder = new TextDecoder()

    try {
      while (true) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const eventData = JSON.parse(line.slice(6))
              onEvent(eventData)
            } catch (e) {
              // Skip malformed JSON
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  getHistory: async (): Promise<any[]> => {
    const response = await api.get('/chat/history')
    return response.data
  },

  clearHistory: async (): Promise<void> => {
    await api.delete('/chat/history')
  },
}

// Timer types
export interface Timer {
  id: string
  name: string
  duration_seconds: number
  remaining_seconds: number
  status: 'running' | 'paused' | 'completed' | 'cancelled'
  created_at: string
  completed_at?: string
}

// Timers functions
export const timersApi = {
  list: async (): Promise<Timer[]> => {
    const response = await api.get<Timer[]>('/timers')
    return response.data
  },

  create: async (name: string, durationSeconds: number): Promise<Timer> => {
    const response = await api.post<Timer>('/timers', {
      name,
      duration_seconds: durationSeconds,
    })
    return response.data
  },

  pause: async (id: string): Promise<Timer> => {
    const response = await api.post<Timer>(`/timers/${id}/pause`)
    return response.data
  },

  resume: async (id: string): Promise<Timer> => {
    const response = await api.post<Timer>(`/timers/${id}/resume`)
    return response.data
  },

  cancel: async (id: string): Promise<void> => {
    await api.delete(`/timers/${id}`)
  },
}

// Settings types
export interface AISettings {
  ai_provider?: string
  openai_api_key?: string
  openai_base_url: string
  openai_model: string
  openai_notification_model: string
  embedding_base_url: string
  embedding_model: string
  embedding_dimension: number
}

export interface TokenStats {
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_requests: number
  last_reset_at: string | null
  updated_at: string | null
}

export interface Device {
  device_id: string
  friendly_name: string | null
  hostname: string | null
  platform: string | null
  is_online: boolean
  activity_level: string
  last_activity_at: string | null
  last_heartbeat_at: string | null
}

// Settings functions
export const settingsApi = {
  getAI: async (): Promise<AISettings> => {
    const response = await api.get<AISettings>('/settings/ai')
    return response.data
  },

  updateAI: async (settings: Partial<AISettings>): Promise<any> => {
    const response = await api.put('/settings/ai', settings)
    return response.data
  },

  testAI: async (): Promise<any> => {
    const response = await api.post('/settings/ai/test')
    return response.data
  },

  getTokenStats: async (): Promise<TokenStats> => {
    const response = await api.get<TokenStats>('/api/token-usage/stats')
    return response.data
  },

  resetTokenStats: async (): Promise<void> => {
    await api.post('/api/token-usage/reset')
  },

  getDevices: async (): Promise<{ devices: Device[] }> => {
    const response = await api.get('/api/devices/list')
    return response.data
  },

  updateDeviceName: async (deviceId: string, friendlyName: string): Promise<void> => {
    await api.patch(`/api/devices/${encodeURIComponent(deviceId)}/name`, {
      friendly_name: friendlyName,
    })
  },

  removeDevice: async (deviceId: string): Promise<void> => {
    await api.delete(`/api/devices/${encodeURIComponent(deviceId)}`)
  },
}

// Fitness types
export interface FoodLogEntry {
  id: string
  food_id: string
  food_name: string
  meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  servings: number
  calories: number
  protein: number
  carbs: number
  fat: number
  logged_at: string
}

export interface WorkoutLog {
  id: string
  workout_type: string
  duration_minutes: number
  notes?: string
  exercises: any[]
  logged_at: string
}

// Raw workout from API
interface RawWorkoutLog {
  id: string
  title: string
  duration_min: number | null
  status: string
  session_date: string | null
  created_at: string
  exercises: any[]
}

// Transform raw API response to expected WorkoutLog format
function transformWorkout(raw: RawWorkoutLog): WorkoutLog {
  return {
    id: raw.id,
    workout_type: raw.title,
    duration_minutes: raw.duration_min || 0,
    notes: raw.status,
    exercises: raw.exercises || [],
    logged_at: raw.session_date || raw.created_at,
  }
}

export interface RecoveryLog {
  id: string
  sleep_hours: number
  sleep_quality: number
  energy_level: number
  soreness_level: number
  stress_level: number
  notes?: string
  logged_at: string
}

// Raw recovery log from API
interface RawRecoveryLog {
  id: string
  log_date: string
  hrv: number | null
  heart_rate: number | null
  sleep_hours: number | null
  soreness_level: number | null
  body_weight: number | null
  notes: string | null
  created_at: string
}

// Transform raw API response to expected RecoveryLog format
function transformRecoveryLog(raw: RawRecoveryLog): RecoveryLog {
  // Map HRV (0-100) to sleep quality (0-10)
  const sleepQuality = raw.hrv ? Math.min(10, Math.round(raw.hrv / 10)) : 5
  // Map resting heart rate inversely to energy (lower HR = more energy)
  const energyLevel = raw.heart_rate ? Math.max(1, Math.min(10, Math.round((100 - raw.heart_rate) / 5))) : 5

  return {
    id: raw.id,
    sleep_hours: raw.sleep_hours || 0,
    sleep_quality: sleepQuality,
    energy_level: energyLevel,
    soreness_level: raw.soreness_level || 0,
    stress_level: 5, // Not tracked in API
    notes: raw.notes || undefined,
    logged_at: raw.log_date || raw.created_at,
  }
}

// Raw food log entry from API
interface RawFoodLogEntry {
  log_id: string
  meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  food_items: { name: string; unit: string; quantity: number }[]
  calories: number | null
  protein: number | null
  carbs: number | null
  fats: number | null
  logged_at: string
}

// Transform raw API response to expected FoodLogEntry format
function transformFoodLog(raw: RawFoodLogEntry): FoodLogEntry {
  const firstItem = raw.food_items?.[0]
  return {
    id: raw.log_id,
    food_id: raw.log_id,
    food_name: firstItem?.name || 'Unknown',
    meal_type: raw.meal_type,
    servings: firstItem?.quantity || 1,
    calories: raw.calories || 0,
    protein: raw.protein || 0,
    carbs: raw.carbs || 0,
    fat: raw.fats || 0,
    logged_at: raw.logged_at,
  }
}

// Fitness functions
export const fitnessApi = {
  // Food log - use search endpoint for date filtering
  getFoodLogs: async (date?: string): Promise<FoodLogEntry[]> => {
    if (date) {
      // Use search endpoint with start_date and end_date for same day
      const response = await api.get<{ entries: RawFoodLogEntry[] } | RawFoodLogEntry[]>(
        `/api/fitness/food-log/search?start_date=${date}&end_date=${date}&limit=100`
      )
      const entries = Array.isArray(response.data) ? response.data : (response.data?.entries || [])
      return entries.map(transformFoodLog)
    }
    // No date - return recent entries
    const response = await api.get<RawFoodLogEntry[]>('/api/fitness/food-log')
    return (response.data || []).map(transformFoodLog)
  },

  logFood: async (data: {
    food_id: string
    meal_type: string
    servings: number
    logged_at?: string
  }): Promise<FoodLogEntry> => {
    const response = await api.post<FoodLogEntry>('/api/fitness/food-log', data)
    return response.data
  },

  deleteFoodLog: async (id: string): Promise<void> => {
    await api.delete(`/api/fitness/food-log/${id}`)
  },

  searchFoods: async (query: string): Promise<any[]> => {
    const response = await api.get(`/api/fitness/foods/search?q=${encodeURIComponent(query)}`)
    return response.data
  },

  // Workouts
  getWorkouts: async (date?: string): Promise<WorkoutLog[]> => {
    const url = date ? `/api/fitness/workouts?date=${date}` : '/api/fitness/workouts'
    const response = await api.get<{ workouts: RawWorkoutLog[] } | RawWorkoutLog[]>(url)
    // Handle both wrapped and unwrapped responses
    let rawWorkouts: RawWorkoutLog[]
    if (Array.isArray(response.data)) {
      rawWorkouts = response.data
    } else {
      rawWorkouts = response.data.workouts || []
    }
    return rawWorkouts.map(transformWorkout)
  },

  logWorkout: async (data: any): Promise<WorkoutLog> => {
    const response = await api.post<WorkoutLog>('/api/fitness/workouts', data)
    return response.data
  },

  deleteWorkout: async (id: string): Promise<void> => {
    await api.delete(`/api/fitness/workouts/${id}`)
  },

  // Recovery
  getRecoveryLogs: async (days?: number): Promise<RecoveryLog[]> => {
    const url = `/api/fitness/recovery/recent/list${days ? `?days=${days}` : ''}`
    const response = await api.get<RawRecoveryLog[]>(url)
    return (response.data || []).map(transformRecoveryLog)
  },

  logRecovery: async (data: any): Promise<RecoveryLog> => {
    const response = await api.post<RecoveryLog>('/api/fitness/recovery', data)
    return response.data
  },

  // Dashboard
  getDashboard: async (): Promise<any> => {
    const response = await api.get('/api/fitness/dashboard')
    return response.data
  },

  // Programs
  getPrograms: async (): Promise<any[]> => {
    const response = await api.get<{ programs: any[] } | any[]>('/api/fitness/programs')
    // Handle both wrapped and unwrapped responses
    if (Array.isArray(response.data)) {
      return response.data
    }
    return response.data.programs || []
  },
}

// Project types
export interface Project {
  id: string
  name: string
  prefix?: string
  description?: string
  github_url?: string
  github_repo_owner?: string
  github_repo_name?: string
  tech_stack?: string
  status: 'active' | 'completed' | 'archived'
  is_active?: boolean
  task_counts?: { backlog: number; in_progress: number; completed: number }
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  description?: string
  status: 'backlog' | 'in_progress' | 'in_qa' | 'done'
  priority: 'low' | 'medium' | 'high'
  created_at: string
  updated_at: string
}

export interface Commit {
  id: string
  sha: string
  short_sha: string
  message: string
  author_name: string
  author_email: string
  committed_at: string
  branch: string
  additions: number | null
  deletions: number | null
  linked_tasks: any[]
}

export interface ProjectFile {
  id: string
  filename: string
  folder_id: string | null
  mime_type: string | null
  file_size: number
  file_size_formatted: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface ProjectFolder {
  id: string
  name: string
  parent_id: string | null
  created_at: string
  updated_at: string
  children?: ProjectFolder[]
}

// Projects functions
export const projectsApi = {
  list: async (): Promise<Project[]> => {
    const response = await api.get<{ projects: Project[]; total: number }>('/api/projects')
    return response.data.projects || []
  },

  get: async (id: string): Promise<Project> => {
    const response = await api.get<Project>(`/api/projects/${id}`)
    return response.data
  },

  create: async (data: { name: string; description?: string; github_url?: string }): Promise<Project> => {
    const response = await api.post<Project>('/api/projects', data)
    return response.data
  },

  update: async (id: string, data: Partial<Project>): Promise<Project> => {
    const response = await api.put<Project>(`/api/projects/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/api/projects/${id}`)
  },

  // Tasks
  getTasks: async (projectId: string): Promise<Task[]> => {
    const response = await api.get<{ tasks: Task[]; total: number }>(`/api/projects/${projectId}/tasks`)
    return response.data.tasks || []
  },

  createTask: async (projectId: string, data: { title: string; description?: string; priority?: string }): Promise<Task> => {
    const response = await api.post<Task>(`/api/projects/${projectId}/tasks`, data)
    return response.data
  },

  updateTask: async (taskId: string, data: Partial<Task>): Promise<Task> => {
    const response = await api.put<Task>(`/api/tasks/${taskId}`, data)
    return response.data
  },

  deleteTask: async (taskId: string): Promise<void> => {
    await api.delete(`/api/tasks/${taskId}`)
  },

  // Commits
  getCommits: async (projectId: string, limit = 50): Promise<Commit[]> => {
    const response = await api.get<{ commits: Commit[] }>(`/api/projects/${projectId}/commits?limit=${limit}`)
    return response.data.commits || []
  },

  // Files & Folders
  getFolders: async (projectId: string): Promise<ProjectFolder[]> => {
    const response = await api.get<{ tree: ProjectFolder[]; total: number }>(`/api/projects/${projectId}/files/folders`)
    return response.data.tree || []
  },

  getFiles: async (projectId: string, folderId?: string | null): Promise<{
    files: ProjectFile[]
    folders: ProjectFolder[]
    breadcrumb: ProjectFolder[]
  }> => {
    const url = folderId
      ? `/api/projects/${projectId}/files?folder_id=${folderId}`
      : `/api/projects/${projectId}/files`
    const response = await api.get<{
      files: ProjectFile[]
      folders: ProjectFolder[]
      breadcrumb: ProjectFolder[]
    }>(url)
    return {
      files: response.data.files || [],
      folders: response.data.folders || [],
      breadcrumb: response.data.breadcrumb || [],
    }
  },

  downloadFile: (projectId: string, fileId: string): string => {
    return `${APP_CONFIG.apiUrl}/api/projects/${projectId}/files/${fileId}/download`
  },

  getFileContent: async (projectId: string, fileId: string): Promise<{ content: string; mimeType: string }> => {
    const response = await api.get(`/api/projects/${projectId}/files/${fileId}/download`, {
      responseType: 'text',
    })
    // Try to get mime type from headers
    const mimeType = response.headers['content-type'] || 'text/plain'
    return { content: response.data, mimeType }
  },
}

// Workspace State types
export interface WindowPosition {
  x: number
  y: number
}

export interface WindowSize {
  width: number
  height: number
}

export interface CanvasTransform {
  x: number
  y: number
  scale: number
}

export interface WindowState {
  id: string
  type: string
  title: string
  position: WindowPosition
  size: WindowSize
  zIndex: number
  data?: any
}

export interface SceneObjectState {
  id: string
  modelId: string
  modelUrl: string
  format: string
  position: { x: number; y: number; z: number }
  rotation: { x: number; y: number; z: number }
  scale: number
  filename: string
}

export interface VisibleMapState {
  mapId: string
  position: { x: number; y: number }
  collapsed: boolean
}

export interface WorkspaceStateData {
  transform: CanvasTransform
  windows: WindowState[]
  sceneObjects?: SceneObjectState[]
  visibleMaps?: VisibleMapState[]
}

export interface WorkspaceStateResponse {
  id: string
  user_id: string
  state_data: WorkspaceStateData | null
  created_at: string | null
  updated_at: string | null
}

// Workspace State functions
export const workspaceApi = {
  getState: async (): Promise<WorkspaceStateResponse> => {
    const response = await api.get<WorkspaceStateResponse>('/api/workspace/state')
    return response.data
  },

  saveState: async (stateData: WorkspaceStateData): Promise<WorkspaceStateResponse> => {
    const response = await api.put<WorkspaceStateResponse>('/api/workspace/state', {
      state_data: stateData,
    })
    return response.data
  },

  clearState: async (): Promise<void> => {
    await api.delete('/api/workspace/state')
  },
}

// 3D Model types
export interface Model3D {
  id: string
  filename: string
  display_name: string
  file_format: string
  file_size: number
  download_url: string
  created_at: string
  updated_at: string
}

// 3D Model functions
export const modelsApi = {
  list: async (): Promise<Model3D[]> => {
    const response = await api.get<Model3D[]>('/models')
    return response.data
  },

  get: async (id: string): Promise<Model3D> => {
    const response = await api.get<Model3D>(`/models/${id}`)
    return response.data
  },

  upload: async (file: File): Promise<Model3D> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<Model3D>('/models/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/models/${id}`)
  },

  getDownloadUrl: (id: string): string => {
    return `${APP_CONFIG.apiUrl}/models/${id}/file`
  },
}

// Maps types (mindmaps/flowcharts)
export interface MapNodeContent {
  type: 'text' | 'image' | 'code' | 'embed'
  data: {
    text?: string
    imageUrl?: string
    code?: string
    language?: string
  }
}

export interface MapNode {
  id: string
  position: { x: number; y: number }
  size: { width: number; height: number }
  content: MapNodeContent
  style?: {
    backgroundColor?: string
    borderColor?: string
    borderWidth?: number
    borderRadius?: number
  }
}

export interface MapEdge {
  id: string
  source: string
  target: string
  sourceHandle?: 'top' | 'right' | 'bottom' | 'left'
  targetHandle?: 'top' | 'right' | 'bottom' | 'left'
  style?: {
    strokeColor?: string
    strokeWidth?: number
    curved?: boolean
  }
}

export interface MapData {
  nodes: MapNode[]
  edges: MapEdge[]
}

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

export interface MapCreateData {
  name: string
  description?: string
  map_data?: MapData
  is_readonly?: boolean
}

export interface MapUpdateData {
  name?: string
  description?: string
  map_data?: MapData
  is_readonly?: boolean
}

export interface MapImportData {
  name: string
  format: 'json' | 'mermaid'
  content: string
  is_readonly?: boolean
  description?: string
}

// Maps functions
export const mapsApi = {
  list: async (): Promise<MapSummary[]> => {
    const response = await api.get<MapSummary[]>('/api/maps')
    return response.data
  },

  get: async (id: string): Promise<MapResponse> => {
    const response = await api.get<MapResponse>(`/api/maps/${id}`)
    return response.data
  },

  create: async (data: MapCreateData): Promise<MapResponse> => {
    const response = await api.post<MapResponse>('/api/maps', data)
    return response.data
  },

  update: async (id: string, data: MapUpdateData): Promise<MapResponse> => {
    const response = await api.put<MapResponse>(`/api/maps/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/api/maps/${id}`)
  },

  // Node operations
  addNode: async (mapId: string, node: Omit<MapNode, 'id'>): Promise<{ node: MapNode; map: MapResponse }> => {
    const response = await api.post<{ node: MapNode; map: MapResponse }>(`/api/maps/${mapId}/nodes`, node)
    return response.data
  },

  updateNode: async (mapId: string, nodeId: string, data: Partial<MapNode>): Promise<MapResponse> => {
    const response = await api.put<MapResponse>(`/api/maps/${mapId}/nodes/${nodeId}`, data)
    return response.data
  },

  deleteNode: async (mapId: string, nodeId: string): Promise<MapResponse> => {
    const response = await api.delete<MapResponse>(`/api/maps/${mapId}/nodes/${nodeId}`)
    return response.data
  },

  // Edge operations
  addEdge: async (mapId: string, edge: Omit<MapEdge, 'id'>): Promise<{ edge: MapEdge; map: MapResponse }> => {
    const response = await api.post<{ edge: MapEdge; map: MapResponse }>(`/api/maps/${mapId}/edges`, edge)
    return response.data
  },

  deleteEdge: async (mapId: string, edgeId: string): Promise<MapResponse> => {
    const response = await api.delete<MapResponse>(`/api/maps/${mapId}/edges/${edgeId}`)
    return response.data
  },

  // Import
  import: async (data: MapImportData): Promise<MapResponse> => {
    const response = await api.post<MapResponse>('/api/maps/import', data)
    return response.data
  },

  // Current map tracking (for Sara's auto-detect)
  setCurrentMap: async (mapId: string, mapName: string): Promise<void> => {
    await api.post('/api/maps/current', { map_id: mapId, map_name: mapName })
  },

  clearCurrentMap: async (): Promise<void> => {
    await api.delete('/api/maps/current')
  },

  getCurrentMap: async (): Promise<{ current_map: { map_id: string; map_name: string } | null }> => {
    const response = await api.get<{ current_map: { map_id: string; map_name: string } | null }>('/api/maps/current')
    return response.data
  },

  // Explode map - resize nodes and spread apart
  explode: async (mapId: string, spacingFactor: number = 1.5): Promise<MapResponse> => {
    const response = await api.post<MapResponse>(`/api/maps/${mapId}/explode`, {
      spacing_factor: spacingFactor
    })
    return response.data
  },
}

// Research types
export interface ResearchSource {
  url: string
  title: string
  snippet: string
}

export interface ResearchEvent {
  type: 'sources' | 'content' | 'done' | 'error'
  data?: ResearchSource[] | string | { message: string }
}

export interface SaveResearchResponse {
  note_id: string
  folder_id: string
}

// Research functions with SSE streaming
export const researchApi = {
  search: async (
    query: string,
    model: string,
    onEvent: (event: ResearchEvent) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const response = await fetch(`${APP_CONFIG.apiUrl}/api/research/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: JSON.stringify({
        query,
        model,
        mode: 'simple',
      }),
      signal,
      credentials: 'include',
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body reader available')
    }

    const decoder = new TextDecoder()

    try {
      while (true) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const eventData = JSON.parse(line.slice(6))
              onEvent(eventData)
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  save: async (
    query: string,
    content: string,
    sources?: ResearchSource[]
  ): Promise<SaveResearchResponse> => {
    const response = await api.post<SaveResearchResponse>('/api/research/save', {
      query,
      content,
      sources,
    })
    return response.data
  },
}

export default api

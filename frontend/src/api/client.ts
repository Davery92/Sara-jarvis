import axios, { AxiosInstance, AxiosRequestConfig } from 'axios'
import { APP_CONFIG } from '../config'

// Types for API responses
export interface User {
  id: string
  email: string
  name: string
  preferences: {
    theme: 'light' | 'dark'
    notifications: boolean
    timezone: string
  }
}

export interface AuthResponse {
  user: User
  message: string
}

export interface ChatMessage {
  id: string
  content: string
  role: 'user' | 'assistant'
  timestamp: Date
  citations?: Citation[]
  tool_effects?: ToolEffect[]
}

export interface Citation {
  source: string
  content: string
  type: 'memory' | 'document' | 'note'
}

export interface ToolEffect {
  tool: string
  action: string
  result: string
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

export interface Note {
  id: string
  title: string
  content: string
  tags: string[]
  created_at: Date
  updated_at: Date
}

export interface Document {
  id: string
  filename: string
  original_filename: string
  title: string
  file_size: number
  mime_type: string
  content_text?: string
  is_processed: string
  created_at: string
  updated_at: string
}

export interface Reminder {
  id: string
  title: string
  description?: string
  due_date: Date
  completed: boolean
  priority: 'low' | 'medium' | 'high'
  created_at: Date
}

export interface CalendarEvent {
  id: string
  title: string
  description?: string
  start_time: Date
  end_time: Date
  location?: string
  attendees?: string[]
  created_at: Date
}

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

export interface AISettingsUpdate {
  ai_provider?: string
  openai_api_key?: string
  openai_base_url?: string
  openai_model?: string
  openai_notification_model?: string
  embedding_base_url?: string
  embedding_model?: string
  embedding_dimension?: number
}

export interface TokenStats {
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_requests: number
  last_reset_at: string | null
  updated_at: string | null
}

export interface UsageBreakdownItem {
  model: string
  operation_type: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  request_count: number
}

export interface UsageBreakdown {
  period_days: number
  breakdown: UsageBreakdownItem[]
}

export interface NotificationRequest {
  type: string
  title: string
  message: string
  reference_id?: string
}

export interface NotificationResponse {
  id: string
  notification_type: string
  title: string
  message: string
  sent_at: string
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

export interface DeviceListResponse {
  devices: Device[]
}

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: APP_CONFIG.apiUrl,
      withCredentials: true,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        // Add any additional headers or processing here
        return config
      },
      (error) => {
        return Promise.reject(error)
      }
    )

    // Response interceptor
    this.client.interceptors.response.use(
      (response) => {
        return response
      },
      (error) => {
        // Handle authentication errors
        if (error.response?.status === 401) {
          // Don't automatically redirect - let components handle auth state
          // The main App-interactive.tsx handles its own authentication flow
          console.warn('API request failed with 401 - authentication may be required')
        }
        return Promise.reject(error)
      }
    )
  }

  // Authentication endpoints
  async register(email: string, password: string, name: string): Promise<AuthResponse> {
    const response = await this.client.post('/auth/register', { email, password, name })
    return response.data
  }

  async login(email: string, password: string): Promise<AuthResponse> {
    const response = await this.client.post('/auth/login', { email, password })
    return response.data
  }

  async logout(): Promise<void> {
    await this.client.post('/auth/logout')
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get('/auth/me')
    return response.data
  }

  async updateProfile(data: Partial<User>): Promise<User> {
    const response = await this.client.put('/auth/profile', data)
    return response.data
  }

  // Chat endpoints
  async getChatHistory(): Promise<ChatMessage[]> {
    const response = await this.client.get('/chat/history')
    return response.data
  }

  async sendMessage(content: string): Promise<ChatMessage> {
    const response = await this.client.post('/chat/message', { content })
    return response.data
  }

  // Get available chat models
  async getChatModels(): Promise<ChatModelsResponse> {
    const response = await this.client.get('/chat/models')
    return response.data
  }

  // Streaming chat method
  async sendMessageStream(
    content: string,
    onEvent: (event: any) => void,
    options?: ChatOptions
  ): Promise<void> {
    const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        messages: [{ role: 'user', content }],
        model: options?.model,
        ephemeral: options?.ephemeral,
      })
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
              console.warn('Failed to parse SSE data:', line)
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  async clearChatHistory(): Promise<void> {
    await this.client.delete('/chat/history')
  }

  // Notes endpoints
  async getNotes(): Promise<Note[]> {
    const response = await this.client.get('/notes')
    return response.data
  }

  async getNote(id: string): Promise<Note> {
    const response = await this.client.get(`/notes/${id}`)
    return response.data
  }

  async createNote(data: Omit<Note, 'id' | 'created_at' | 'updated_at'>): Promise<Note> {
    const response = await this.client.post('/notes', data)
    return response.data
  }

  async updateNote(id: string, data: Partial<Note>): Promise<Note> {
    const response = await this.client.put(`/notes/${id}`, data)
    return response.data
  }

  async deleteNote(id: string): Promise<void> {
    await this.client.delete(`/notes/${id}`)
  }

  async searchNotes(query: string): Promise<Note[]> {
    const response = await this.client.get(`/notes/search?q=${encodeURIComponent(query)}`)
    return response.data
  }

  // Documents endpoints
  async getDocuments(): Promise<Document[]> {
    const response = await this.client.get('/documents')
    return response.data
  }

  async uploadDocument(file: File, chatContext: boolean = false): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    
    const url = chatContext ? `/documents?chat_context=true` : '/documents'
    
    const response = await this.client.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }

  async deleteDocument(id: string): Promise<void> {
    await this.client.delete(`/documents/${id}`)
  }

  async downloadDocument(id: string): Promise<Blob> {
    const response = await this.client.get(`/documents/${id}/download`, {
      responseType: 'blob',
    })
    return response.data
  }

  // Reminders endpoints
  async getReminders(): Promise<Reminder[]> {
    const response = await this.client.get('/reminders')
    return response.data
  }

  async createReminder(data: Omit<Reminder, 'id' | 'created_at'>): Promise<Reminder> {
    const response = await this.client.post('/reminders', data)
    return response.data
  }

  async updateReminder(id: string, data: Partial<Reminder>): Promise<Reminder> {
    const response = await this.client.put(`/reminders/${id}`, data)
    return response.data
  }

  async deleteReminder(id: string): Promise<void> {
    await this.client.delete(`/reminders/${id}`)
  }

  async markReminderComplete(id: string): Promise<Reminder> {
    const response = await this.client.patch(`/reminders/${id}/complete`)
    return response.data
  }

  // Calendar endpoints
  async getCalendarEvents(): Promise<CalendarEvent[]> {
    const response = await this.client.get('/calendar/events')
    return response.data
  }

  async createCalendarEvent(data: Omit<CalendarEvent, 'id' | 'created_at'>): Promise<CalendarEvent> {
    const response = await this.client.post('/calendar/events', data)
    return response.data
  }

  async updateCalendarEvent(id: string, data: Partial<CalendarEvent>): Promise<CalendarEvent> {
    const response = await this.client.put(`/calendar/events/${id}`, data)
    return response.data
  }

  async deleteCalendarEvent(id: string): Promise<void> {
    await this.client.delete(`/calendar/events/${id}`)
  }

  // Memory/Knowledge endpoints
  async searchMemory(query: string): Promise<any[]> {
    const response = await this.client.get(`/memory/search?q=${encodeURIComponent(query)}`)
    return response.data
  }

  async addMemory(content: string, tags?: string[]): Promise<any> {
    const response = await this.client.post('/memory', { content, tags })
    return response.data
  }

  // Settings endpoints
  async getAISettings(): Promise<AISettings> {
    const response = await this.client.get('/settings/ai')
    return response.data
  }

  async updateAISettings(settings: AISettingsUpdate): Promise<any> {
    const response = await this.client.put('/settings/ai', settings)
    return response.data
  }

  async testAISettings(): Promise<any> {
    const response = await this.client.post('/settings/ai/test')
    return response.data
  }

  // Token Usage endpoints
  async getTokenStats(): Promise<TokenStats> {
    const response = await this.client.get('/api/token-usage/stats')
    return response.data
  }

  async getTokenBreakdown(days: number = 30): Promise<UsageBreakdown> {
    const response = await this.client.get(`/api/token-usage/breakdown?days=${days}`)
    return response.data
  }

  async resetTokenStats(): Promise<{ success: boolean; message: string }> {
    const response = await this.client.post('/api/token-usage/reset')
    return response.data
  }

  async sendNtfyNotification(notification: NotificationRequest): Promise<NotificationResponse> {
    const response = await this.client.post('/api/notifications/ntfy', notification)
    return response.data
  }

  async getNotificationHistory(): Promise<NotificationResponse[]> {
    const response = await this.client.get('/api/notifications/history')
    return response.data
  }

  // Food Database endpoints
  async searchFoods(query: string, limit: number = 20): Promise<any[]> {
    const response = await this.client.get(`/api/fitness/foods/search?q=${encodeURIComponent(query)}&limit=${limit}`)
    return response.data
  }

  async getRecentFoods(limit: number = 20): Promise<any[]> {
    try {
      const response = await this.client.get(`/api/fitness/food-log/recent-foods?limit=${limit}`)
      return response.data.recent_foods || []
    } catch (error) {
      console.error('Failed to fetch recent foods:', error)
      return []
    }
  }

  async getYesterdayFoods(): Promise<any> {
    try {
      const response = await this.client.get('/api/fitness/food-log/yesterday')
      return response.data
    } catch (error) {
      console.error('Failed to fetch yesterday foods:', error)
      return { meals: {}, all_foods: [] }
    }
  }

  async createFood(data: any): Promise<any> {
    const response = await this.client.post('/api/fitness/foods', data)
    return response.data
  }

  async getFoodDetails(foodId: string): Promise<any> {
    const response = await this.client.get(`/api/fitness/foods/${foodId}/details`)
    return response.data
  }

  // Food Log endpoints
  async logFood(data: any): Promise<any> {
    const response = await this.client.post('/api/fitness/food-log', data)
    return response.data
  }

  async updateFoodLog(id: string, data: any): Promise<any> {
    const response = await this.client.put(`/api/fitness/food-log/${id}`, data)
    return response.data
  }

  async getFoodLogs(date?: string): Promise<any[]> {
    const url = date ? `/api/fitness/food-log?date=${date}` : '/api/fitness/food-log'
    const response = await this.client.get(url)
    return response.data
  }

  async deleteFoodLog(id: string): Promise<void> {
    await this.client.delete(`/api/fitness/food-log/${id}`)
  }

  // Recipe endpoints
  async getRecipes(limit?: number): Promise<any[]> {
    const params = limit ? `?limit=${limit}` : ''
    const response = await this.client.get(`/api/fitness/recipes${params}`)
    return response.data
  }

  // Daily Briefings endpoints
  async getDailyBriefings(): Promise<any[]> {
    const response = await this.client.get('/api/briefings')
    return response.data
  }

  async getBriefingSettings(): Promise<any> {
    const response = await this.client.get('/api/briefings/settings')
    return response.data
  }

  async updateBriefingSettings(settings: any): Promise<any> {
    const response = await this.client.put('/api/briefings/settings', settings)
    return response.data
  }

  async generateBriefing(type: 'morning' | 'evening'): Promise<any> {
    const response = await this.client.post('/api/briefings/generate', { briefing_type: type })
    return response.data
  }

  async markBriefingRead(briefingId: string): Promise<void> {
    await this.client.patch(`/api/briefings/${briefingId}/read`)
  }

  // Context Mode endpoints
  async getContextMode(): Promise<any> {
    const response = await this.client.get('/api/context/mode')
    return response.data
  }

  async setContextMode(mode: string): Promise<any> {
    const response = await this.client.put('/api/context/mode', { mode })
    return response.data
  }

  async getContextStats(): Promise<any> {
    const response = await this.client.get('/api/context/stats')
    return response.data
  }

  // Intelligence Reports endpoints
  async getIntelligenceReports(): Promise<any[]> {
    const response = await this.client.get('/api/reports/list')
    return response.data
  }

  async getIntelligenceReport(reportId: string): Promise<any> {
    const response = await this.client.get(`/api/reports/${reportId}`)
    return response.data
  }

  async generateIntelligenceReport(type: 'weekly' | 'monthly' | 'quarterly'): Promise<any> {
    const response = await this.client.post('/api/reports/generate', { report_type: type })
    return response.data
  }

  // Proactive Suggestions endpoints
  async getProactiveSuggestions(): Promise<any[]> {
    const response = await this.client.get('/api/suggestions')
    return response.data
  }

  async updateSuggestionStatus(suggestionId: string, status: 'accepted' | 'dismissed'): Promise<any> {
    const response = await this.client.patch(`/api/suggestions/${suggestionId}`, { status })
    return response.data
  }

  // Detected Patterns endpoints
  async getDetectedPatterns(): Promise<any[]> {
    const response = await this.client.get('/api/patterns')
    return response.data
  }

  async getPattern(patternId: string): Promise<any> {
    const response = await this.client.get(`/api/patterns/${patternId}`)
    return response.data
  }

  // Device Management endpoints
  async getDevices(): Promise<DeviceListResponse> {
    const response = await this.client.get('/api/devices/list')
    return response.data
  }

  async updateDeviceName(deviceId: string, friendlyName: string): Promise<void> {
    await this.client.patch(`/api/devices/${encodeURIComponent(deviceId)}/name`, {
      friendly_name: friendlyName
    })
  }

  async removeDevice(deviceId: string): Promise<void> {
    await this.client.delete(`/api/devices/${encodeURIComponent(deviceId)}`)
  }
}

// Create and export a singleton instance
export const apiClient = new ApiClient()
export default apiClient
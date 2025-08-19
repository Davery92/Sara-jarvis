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
  size: number
  type: string
  uploaded_at: Date
  processed: boolean
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
  openai_base_url: string
  openai_model: string
  embedding_base_url: string
  embedding_model: string
  embedding_dimension: number
}

export interface AISettingsUpdate {
  openai_base_url?: string
  openai_model?: string
  embedding_base_url?: string
  embedding_model?: string
  embedding_dimension?: number
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
          // Redirect to login or handle unauthorized access
          window.location.href = '/login'
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

  async uploadDocument(file: File): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    
    const response = await this.client.post('/documents/upload', formData, {
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
}

// Create and export a singleton instance
export const apiClient = new ApiClient()
export default apiClient
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
  provider: 'anthropic' | 'google' | 'local' | 'openai' | 'codex'
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
  // Background processing settings
  bg_llm_primary_url?: string
  bg_llm_primary_model?: string
  bg_llm_fallback_url?: string
  bg_llm_fallback_model?: string
  codex_oauth_connected?: boolean
  codex_oauth_email?: string
  codex_oauth_expires_at?: string
  codex_oauth_account_id?: string
  // VM sandbox settings
  vm_sandbox_host?: string
  vm_sandbox_username?: string
  vm_sandbox_ssh_key_path?: string
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
  // Background processing settings
  bg_llm_primary_url?: string
  bg_llm_primary_model?: string
  bg_llm_fallback_url?: string
  bg_llm_fallback_model?: string
  // VM sandbox settings
  vm_sandbox_host?: string
  vm_sandbox_username?: string
  vm_sandbox_ssh_key_path?: string
}

export interface CodexOAuthStatus {
  connected: boolean
  email?: string
  account_id?: string
  expires_at?: string
  expires_in_seconds?: number | null
  error?: string | null
}

export interface TemerantRpgModelSetting {
  model: string
  updated_at?: string | null
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

export interface AutonomyFlags {
  autonomy_traces_enabled: boolean
  autonomy_structured_plan: boolean
  autonomy_policy_engine: boolean
  autonomy_attention_enabled: boolean
  autonomy_missions_enabled: boolean
  autonomy_policy_candidates_enabled: boolean
  temerant_enabled: boolean
  temerant_oracle_enabled: boolean
  temerant_narrative_enabled: boolean
  temerant_auto_ingestion_enabled: boolean
  temerant_rpg_enabled: boolean
  temerant_rpg_narrative_enabled: boolean
  automation_admin_configured: boolean
  automation_admin_email_count: number
  automation_admin_role_count: number
}

export interface NotificationPrefItem {
  category: string
  enabled: boolean
  custom_ban_phrases: string[]
}

export interface NotificationPrefsResponse {
  preferences: NotificationPrefItem[]
}

export interface AutonomyRolloutEvaluation {
  status: 'flag_off' | 'insufficient_data' | 'healthy' | 'unhealthy'
  healthy: boolean | null
  rollback_recommended: boolean
  reasons: string[]
}

export interface AutonomyRolloutSummary {
  window_hours: number
  flags: {
    autonomy_traces_enabled: boolean
    autonomy_structured_plan: boolean
    autonomy_policy_engine: boolean
    autonomy_attention_enabled: boolean
    autonomy_missions_enabled: boolean
    autonomy_policy_candidates_enabled: boolean
  }
  trace_stats: {
    total: number
    failed: number
    succeeded?: number
    runs?: number
    unique_actions?: number
    avg_duration_ms?: number | null
  }
  run_log: {
    total_runs: number
    fallback_runs: number
    fallback_rate: number
  }
  notifications: {
    sent_total: number
    dedup_blocked_total: number
    attention_linked_sent: number
    direct_sent: number
  }
  attention_queue: {
    new: number
    in_progress: number
    done: number
  }
  missions: {
    total: number
    by_state: Array<{ state: string; count: number }>
  }
  thresholds: {
    min_runs_for_eval: number
    max_fallback_rate: number
    max_action_failure_rate: number
    max_dedup_block_rate: number
    max_attention_backlog_ratio: number
    max_mission_failure_rate: number
    max_mission_nonterminal_ratio: number
  }
  rates: {
    fallback_rate: number
    action_failure_rate: number
    dedup_block_rate: number
    attention_backlog_ratio: number
    mission_failure_rate: number
    mission_nonterminal_ratio: number
  }
  evaluations: Record<string, AutonomyRolloutEvaluation>
  rollback_recommendations: Array<{ flag: string; reasons: string[] }>
}

export type TemerantAttribute = 'body' | 'mind' | 'craft' | 'coin' | 'name'

export interface TemerantCharacterCreateRequest {
  character_name?: string
  backstory?: string
  origin?: string
  starter_profile?: string
}

export interface TemerantCharacterUpdateRequest {
  character_name?: string
  backstory?: string
  origin?: string
  specialization_track?: string
}

export interface TemerantCharacterResponse {
  id: string
  user_id: string
  character_name: string
  backstory?: string | null
  origin?: string | null
  current_rank: 'elir' | 'relar' | 'elthe'
  coin_balance: number
  alar_strength: number
  naming_affinity: number
  specialization_track?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TemerantAttributeStateResponse {
  attribute: TemerantAttribute
  xp_total: number
  xp_term: number
  level: number
  xp_today: number
}

export interface TemerantOracleEventResponse {
  id: string
  local_date: string
  tier: 'notable' | 'major'
  category: 'academic' | 'social' | 'discovery' | 'financial' | 'challenge' | 'mystery'
  title: string
  hook: string
  stakes?: string | null
  options?: string[] | null
  resolution?: string | null
  status: 'open' | 'resolved' | 'dismissed'
  created_at?: string | null
  resolved_at?: string | null
}

export interface TemerantDailyStateResponse {
  local_date: string
  categories_completed: number
  body_xp: number
  mind_xp: number
  craft_xp: number
  coin_xp: number
  name_xp: number
  oracle_roll_raw?: number | null
  oracle_roll_modified?: number | null
  term_month: string
}

export interface TemerantDashboardResponse {
  date: string
  character: TemerantCharacterResponse
  attributes: Record<TemerantAttribute, TemerantAttributeStateResponse>
  daily: TemerantDailyStateResponse
  oracle_event?: TemerantOracleEventResponse | null
  rank_progress: {
    next_rank?: string | null
    requirements: Record<string, number>
  }
}

export interface TemerantManualLogRequest {
  action_type: string
  action_label?: string
  notes?: string
  quantity?: number
  source_ref_id?: string
  occurred_at?: string
  metadata?: Record<string, any>
}

export interface TemerantManualLogResponse {
  ledger_entry_id: string
  local_date: string
  attribute: TemerantAttribute
  xp_delta: number
  coin_delta: number
  rank_after: 'elir' | 'relar' | 'elthe'
  duplicate: boolean
}

export interface TemerantLedgerEntryResponse {
  id: string
  source_type: string
  source_ref_id?: string | null
  occurred_at: string
  local_date: string
  attribute: TemerantAttribute
  subdomain?: string | null
  xp_delta: number
  coin_delta: number
  name_delta: number
  meta: Record<string, any>
}

export interface TemerantTermResponse {
  id: string
  term_month: string
  completion_pct: number
  admissions_result: 'excellent' | 'good' | 'poor' | 'terrible'
  tuition_talents: number
  xp_multiplier: number
  coin_delta: number
  review_markdown?: string | null
  locked_at?: string | null
}

export interface TemerantJournalEntryResponse {
  id: string
  local_date: string
  summary_structured: Record<string, any>
  summary_markdown: string
  source_event_count: number
  generated_by: string
  model?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TemerantMappingRuleResponse {
  id: string
  source_kind: string
  source_ref?: string | null
  target_attribute: TemerantAttribute
  target_subdomain?: string | null
  xp_base: number
  bonus_rules: Record<string, any>
  daily_cap?: number | null
  enabled: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface TemerantMappingRuleUpdateRequest {
  source_kind?: string
  source_ref?: string
  target_attribute?: TemerantAttribute
  target_subdomain?: string
  xp_base?: number
  bonus_rules?: Record<string, any>
  daily_cap?: number
  enabled?: boolean
}

export interface TemerantStarterProfileResponse {
  id: string
  name: string
  description: string
  character_name: string
  origin?: string | null
  backstory: string
  current_rank: 'elir' | 'relar' | 'elthe'
  coin_balance: number
  alar_strength: number
  naming_affinity: number
  attribute_xp: Record<TemerantAttribute, number>
  inventory: string[]
  patron?: string | null
  personality?: string | null
  flaw?: string | null
  key_npcs: string[]
}

export interface TemerantRpgCharacterCreateRequest {
  character_name?: string
  origin?: string
  backstory?: string
}

export interface TemerantRpgCharacterResponse {
  id: string
  user_id: string
  character_name: string
  origin?: string | null
  backstory?: string | null
  body: number
  mind: number
  craft: number
  voice: number
  luck: number
  coin_talents: number
  rank: string
  conditions: Record<string, any>
  skills: Record<string, number>
  inventory: string[]
  term_index: number
  current_scene_id?: string | null
}

export interface TemerantRpgSceneResponse {
  id: string
  scene_number: number
  local_date: string
  day_slot: string
  location: string
  title: string
  opening_text: string
  status: string
  summary?: string | null
  consequences: Array<Record<string, any>>
  opened_at?: string | null
  closed_at?: string | null
}

export interface TemerantRpgRelationshipResponse {
  npc_key: string
  display_name: string
  disposition: string
  trust: string
  respect: string
  debt_balance: number
  notes?: string | null
}

export interface TemerantRpgStateResponse {
  character: TemerantRpgCharacterResponse
  world: {
    local_date: string
    day_slot: string
    weather: string
    location_hint: string
    ambient_events: string[]
    pending_consequences: Array<Record<string, any>>
    last_advance_summary?: string | null
  }
  open_scene?: TemerantRpgSceneResponse | null
  relationships: TemerantRpgRelationshipResponse[]
}

export interface TemerantRpgTurnResponse {
  scene_id: string
  turn_index: number
  outcome: 'triumph' | 'success' | 'partial' | 'failure' | 'disaster'
  total: number
  difficulty: number
  margin: number
  response_text: string
  consequence?: Record<string, any> | null
}

export interface TemerantRpgJournalEntryResponse {
  id: string
  local_date: string
  summary_markdown: string
  scene_ids: string[]
  created_at?: string | null
  updated_at?: string | null
}

export interface TemerantRpgTermResponse {
  id: string
  term_index: number
  month: string
  admissions_result: string
  tuition_talents: number
  summary: string
  created_at?: string | null
  updated_at?: string | null
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

  async getCodexOAuthStatus(): Promise<CodexOAuthStatus> {
    const response = await this.client.get('/settings/ai/codex/oauth/status')
    return response.data
  }

  async startCodexOAuth(returnTo?: string): Promise<{ auth_url: string; redirect_uri: string; return_to: string; requires_manual_code?: boolean }> {
    const response = await this.client.post('/settings/ai/codex/oauth/start', {
      return_to: returnTo,
    })
    return response.data
  }

  async completeCodexOAuth(payload: { redirect_url?: string; code?: string; state?: string }): Promise<{ ok: boolean; connected: boolean; email: string; expires_at: string }> {
    const response = await this.client.post('/settings/ai/codex/oauth/complete', payload)
    return response.data
  }

  async disconnectCodexOAuth(): Promise<{ ok: boolean; message: string }> {
    const response = await this.client.post('/settings/ai/codex/oauth/disconnect')
    return response.data
  }

  async getAutonomyFlags(): Promise<AutonomyFlags> {
    const response = await this.client.get('/api/settings/autonomy-flags')
    return response.data
  }

  async getNotificationPreferences(): Promise<NotificationPrefsResponse> {
    const response = await this.client.get('/api/settings/notification-preferences')
    return response.data
  }

  async updateNotificationPreferences(prefs: NotificationPrefItem[]): Promise<NotificationPrefsResponse> {
    const response = await this.client.put('/api/settings/notification-preferences', { preferences: prefs })
    return response.data
  }

  async getAutonomyRolloutSummary(hours: number = 24): Promise<AutonomyRolloutSummary> {
    const response = await this.client.get(`/autonomy/rollout/summary?hours=${hours}`)
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
    const response = await this.client.get('/api/detected-patterns')
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

  // Agent Orchestration endpoints
  async testVMConnection(): Promise<{ status: string; host: string; username: string }> {
    const response = await this.client.post('/api/agents/vm/test')
    return response.data
  }

  async dispatchAgentTask(data: { task_description: string; mode?: string; working_directory?: string }): Promise<any> {
    const response = await this.client.post('/api/agents/dispatch', data)
    return response.data
  }

  async listAgentTasks(limit?: number): Promise<{ tasks: any[] }> {
    const params = limit ? `?limit=${limit}` : ''
    const response = await this.client.get(`/api/agents/tasks${params}`)
    return response.data
  }

  async getAgentTask(taskId: string): Promise<any> {
    const response = await this.client.get(`/api/agents/tasks/${taskId}`)
    return response.data
  }

  async resumeAgentTask(taskId: string, instruction: string): Promise<any> {
    const response = await this.client.post(`/api/agents/tasks/${taskId}/resume`, { instruction })
    return response.data
  }

  async listCandidateSkills(status?: string): Promise<{ candidates: any[] }> {
    const params = status ? `?status=${status}` : ''
    const response = await this.client.get(`/api/agents/skills/candidates${params}`)
    return response.data
  }

  async getCandidateSkill(skillId: string): Promise<any> {
    const response = await this.client.get(`/api/agents/skills/candidates/${skillId}`)
    return response.data
  }

  async reviewCandidateSkill(skillId: string, action: string, reviewNotes?: string): Promise<any> {
    const response = await this.client.post(`/api/agents/skills/candidates/${skillId}/review`, {
      action,
      review_notes: reviewNotes,
    })
    return response.data
  }

  async sendNotificationFeedback(
    notificationId: number,
    action: 'read' | 'engaged' | 'dismissed',
    responseText?: string,
  ): Promise<void> {
    try {
      await this.client.post(`/api/notifications/${notificationId}/feedback`, {
        action,
        response_text: responseText || undefined,
      })
    } catch (error) {
      // Best-effort — don't fail the calling flow
      console.warn('[API] Notification feedback failed (non-critical):', error)
    }
  }

  async getNotificationEngagementStats(days: number = 7): Promise<any> {
    const response = await this.client.get(`/api/notifications/engagement-stats?days=${days}`)
    return response.data
  }

  async getTemerantRpgModelSetting(): Promise<TemerantRpgModelSetting> {
    const response = await this.client.get('/api/settings/temerant-rpg-model')
    return response.data
  }

  async updateTemerantRpgModelSetting(model: string): Promise<TemerantRpgModelSetting> {
    const response = await this.client.put('/api/settings/temerant-rpg-model', { model })
    return response.data
  }

  // Temerant endpoints
  async createTemerantCharacter(payload: TemerantCharacterCreateRequest): Promise<TemerantCharacterResponse> {
    const response = await this.client.post('/api/temerant/character', payload)
    return response.data
  }

  async getTemerantStarterProfiles(): Promise<TemerantStarterProfileResponse[]> {
    const response = await this.client.get('/api/temerant/starter-profiles')
    return response.data
  }

  async getTemerantCharacter(): Promise<TemerantCharacterResponse> {
    const response = await this.client.get('/api/temerant/character')
    return response.data
  }

  async updateTemerantCharacter(payload: TemerantCharacterUpdateRequest): Promise<TemerantCharacterResponse> {
    const response = await this.client.patch('/api/temerant/character', payload)
    return response.data
  }

  async getTemerantDashboard(date?: string): Promise<TemerantDashboardResponse> {
    const response = await this.client.get('/api/temerant/dashboard', {
      params: date ? { date } : undefined,
    })
    return response.data
  }

  async listTemerantLedger(params?: { from?: string; to?: string; limit?: number }): Promise<TemerantLedgerEntryResponse[]> {
    const response = await this.client.get('/api/temerant/ledger', { params })
    return response.data
  }

  async createTemerantManualLog(payload: TemerantManualLogRequest): Promise<TemerantManualLogResponse> {
    const response = await this.client.post('/api/temerant/logs/manual', payload)
    return response.data
  }

  async rollTemerantOracle(date?: string): Promise<TemerantOracleEventResponse | null> {
    const response = await this.client.post('/api/temerant/oracle/roll', null, {
      params: date ? { date } : undefined,
    })
    return response.data
  }

  async listTemerantOracleEvents(status?: string, limit: number = 50): Promise<TemerantOracleEventResponse[]> {
    const response = await this.client.get('/api/temerant/oracle/events', {
      params: { status, limit },
    })
    return response.data
  }

  async resolveTemerantOracleEvent(
    eventId: string,
    payload: { status?: 'resolved' | 'dismissed'; resolution?: string }
  ): Promise<TemerantOracleEventResponse> {
    const response = await this.client.post(`/api/temerant/oracle/events/${eventId}/resolve`, payload)
    return response.data
  }

  async getTemerantCurrentTerm(): Promise<TemerantTermResponse> {
    const response = await this.client.get('/api/temerant/terms/current')
    return response.data
  }

  async listTemerantTermHistory(limit: number = 12): Promise<TemerantTermResponse[]> {
    const response = await this.client.get('/api/temerant/terms/history', {
      params: { limit },
    })
    return response.data
  }

  async closeTemerantTerm(payload: { term_month?: string; review_markdown?: string }): Promise<TemerantTermResponse> {
    const response = await this.client.post('/api/temerant/terms/close', payload)
    return response.data
  }

  async listTemerantJournal(params?: { from?: string; to?: string; limit?: number }): Promise<TemerantJournalEntryResponse[]> {
    const response = await this.client.get('/api/temerant/journal', { params })
    return response.data
  }

  async generateTemerantJournal(journalDate: string): Promise<TemerantJournalEntryResponse> {
    const response = await this.client.post(`/api/temerant/journal/${journalDate}`)
    return response.data
  }

  async listTemerantMappings(): Promise<TemerantMappingRuleResponse[]> {
    const response = await this.client.get('/api/temerant/mappings')
    return response.data
  }

  async updateTemerantMapping(
    ruleId: string,
    payload: TemerantMappingRuleUpdateRequest
  ): Promise<TemerantMappingRuleResponse> {
    const response = await this.client.put(`/api/temerant/mappings/${ruleId}`, payload)
    return response.data
  }

  // Separate scene-based Temerant RPG endpoints
  async createTemerantRpgCharacter(payload: TemerantRpgCharacterCreateRequest): Promise<TemerantRpgCharacterResponse> {
    const response = await this.client.post('/api/temerant-rpg/characters', payload)
    return response.data
  }

  async getTemerantRpgState(): Promise<TemerantRpgStateResponse> {
    const response = await this.client.get('/api/temerant-rpg/state')
    return response.data
  }

  async openTemerantRpgScene(payload?: { title?: string; location?: string; opening_prompt?: string }): Promise<TemerantRpgSceneResponse> {
    const response = await this.client.post('/api/temerant-rpg/scenes/open', payload || {})
    return response.data
  }

  async actTemerantRpgScene(
    sceneId: string,
    payload: { action: string; attribute?: string; skill?: string; difficulty?: number; circumstance_mod?: number }
  ): Promise<TemerantRpgTurnResponse> {
    const response = await this.client.post(`/api/temerant-rpg/scenes/${sceneId}/act`, payload)
    return response.data
  }

  async closeTemerantRpgScene(sceneId: string, summary?: string): Promise<TemerantRpgSceneResponse> {
    const response = await this.client.post(`/api/temerant-rpg/scenes/${sceneId}/close`, { summary })
    return response.data
  }

  async advanceTemerantRpgTime(slots: number = 1): Promise<{ local_date: string; day_slot: string; summary: string }> {
    const response = await this.client.post('/api/temerant-rpg/time/advance', { slots })
    return response.data
  }

  async listTemerantRpgJournal(limit: number = 20): Promise<TemerantRpgJournalEntryResponse[]> {
    const response = await this.client.get('/api/temerant-rpg/journal', { params: { limit } })
    return response.data
  }

  async generateTemerantRpgJournal(localDate?: string): Promise<TemerantRpgJournalEntryResponse> {
    const response = await this.client.post('/api/temerant-rpg/journal/generate', {
      local_date: localDate,
      regenerate: true,
    })
    return response.data
  }

  async runTemerantRpgAdmissions(termIndex?: number): Promise<TemerantRpgTermResponse> {
    const response = await this.client.post('/api/temerant-rpg/admissions/run', {
      term_index: termIndex,
    })
    return response.data
  }

  async listTemerantRpgTerms(limit: number = 12): Promise<TemerantRpgTermResponse[]> {
    const response = await this.client.get('/api/temerant-rpg/terms', { params: { limit } })
    return response.data
  }
}

// Create and export a singleton instance
export const apiClient = new ApiClient()
export default apiClient

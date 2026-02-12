import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// API Configuration
const API_URL = __DEV__
  ? 'http://10.185.1.180:8000'  // Development - LAN backend
  : 'https://sara-api.avery.cloud';  // Production

const TOKEN_KEY = '@sara_auth_token';

// Chat model types
export interface ChatModel {
  id: string;
  name: string;
  provider: 'anthropic' | 'google' | 'local';
}

export interface ChatModelsResponse {
  models: ChatModel[];
  default: string;
}

export interface ChatOptions {
  model?: string;
  ephemeral?: boolean;
  notifyOnComplete?: boolean;  // Send push notification when response is ready (for background completion)
  inboxItemId?: string;  // Pre-load inbox item content for discussion
  source?: string;  // 'ios' | 'ios_overlay' | 'workspace'
  currentScreen?: string;  // Current iOS screen for context-aware tool loading
  onContentCard?: (card: any) => void;  // Content card callback
  onToolStatus?: (status: { tool: string; status: string }) => void;  // Tool execution status
  onSuggestedActions?: (actions: any[]) => void;  // Suggested follow-up actions
}

class ApiClient {
  private client: AxiosInstance;
  public baseURL: string;
  private onAuthError: (() => void) | null = null;

  constructor() {
    this.baseURL = API_URL;
    this.client = axios.create({
      baseURL: API_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor to add auth token
    this.client.interceptors.request.use(
      async (config) => {
        const token = await AsyncStorage.getItem(TOKEN_KEY);
        if (token && config.headers) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      async (error) => {
        if (error.response?.status === 401) {
          // Token expired or invalid - clear it
          await AsyncStorage.removeItem(TOKEN_KEY);
          console.log('[API] 401 received - token expired, triggering logout');
          // Notify AuthContext to clear user state
          if (this.onAuthError) {
            this.onAuthError();
          }
        }
        return Promise.reject(error);
      }
    );
  }

  /**
   * Set callback to be called when authentication fails (401)
   * This allows AuthContext to be notified and trigger logout
   */
  setOnAuthError(callback: () => void) {
    this.onAuthError = callback;
  }

  async get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.get(url, config);
    return response.data;
  }

  async post<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.post(url, data, config);
    return response.data;
  }

  async put<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.put(url, data, config);
    return response.data;
  }

  async patch<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.patch(url, data, config);
    return response.data;
  }

  async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.delete(url, config);
    return response.data;
  }

  async upload<T>(url: string, formData: FormData, config?: AxiosRequestConfig): Promise<T> {
    const response: AxiosResponse<T> = await this.client.post(url, formData, {
      ...config,
      headers: {
        ...config?.headers,
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  }

  getBaseUrl(): string {
    return this.baseURL;
  }

  async setAuthToken(token: string) {
    await AsyncStorage.setItem(TOKEN_KEY, token);
  }

  async clearAuthToken() {
    await AsyncStorage.removeItem(TOKEN_KEY);
  }

  async getAuthToken(): Promise<string | null> {
    return await AsyncStorage.getItem(TOKEN_KEY);
  }

  async getToken(): Promise<string | null> {
    return await this.getAuthToken();
  }

  // Fetch available chat models
  async getChatModels(): Promise<ChatModelsResponse> {
    const response = await this.client.get('/chat/models');
    return response.data;
  }

  // Streaming support for chat using XMLHttpRequest (works in React Native)
  async streamChat(
    messages: any[],
    onChunk: (chunk: string) => void,
    onComplete: (conversationId?: string, episodeId?: string) => void,
    onError: (error: Error) => void,
    sessionId?: string,
    options?: ChatOptions
  ) {
    try {
      const token = await this.getAuthToken();
      console.log('[API] Sending chat request to:', `${API_URL}/chat/stream`);

      return new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        let buffer = '';
        let lastProcessedIndex = 0;
        let receivedConversationId: string | undefined = undefined;
        let receivedEpisodeId: string | undefined = undefined;

        xhr.open('POST', `${API_URL}/chat/stream`, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        if (token) {
          xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        }

        xhr.onprogress = () => {
          // Get the new chunk of data
          const newData = xhr.responseText.substring(lastProcessedIndex);
          lastProcessedIndex = xhr.responseText.length;

          // Add new data to buffer
          buffer += newData;

          // Process complete lines
          const lines = buffer.split('\n');
          // Keep the last incomplete line in buffer
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmedLine = line.trim();
            if (trimmedLine.startsWith('data: ')) {
              const data = trimmedLine.slice(6);

              if (data === '[DONE]') {
                continue;
              }

              try {
                const parsed = JSON.parse(data);
                // Handle text_chunk events from backend
                if (parsed.type === 'text_chunk' && parsed.data?.content) {
                  onChunk(parsed.data.content);
                } else if (parsed.type === 'final_response') {
                  // Final response event - extract conversation_id and episode_id
                  console.log('[API] Received final_response event');
                  console.log('[API] Full final_response data:', JSON.stringify(parsed.data));
                  if (parsed.data?.conversation_id) {
                    receivedConversationId = parsed.data.conversation_id;
                    console.log('[API] ✅ Got conversation_id:', receivedConversationId);
                  } else {
                    console.warn('[API] ⚠️ No conversation_id in final_response!');
                  }
                  if (parsed.data?.episode_id) {
                    receivedEpisodeId = parsed.data.episode_id;
                    console.log('[API] ✅ Got episode_id:', receivedEpisodeId);
                  } else {
                    console.warn('[API] ⚠️ No episode_id in final_response!');
                  }
                } else if (parsed.type === 'content_card' && options?.onContentCard) {
                  options.onContentCard(parsed.data);
                } else if (parsed.type === 'tool_executing' && options?.onToolStatus) {
                  options.onToolStatus({ tool: parsed.data?.tool, status: 'executing' });
                } else if (parsed.type === 'tool_completed' && options?.onToolStatus) {
                  options.onToolStatus({ tool: parsed.data?.tool, status: 'completed' });
                } else if (parsed.type === 'suggested_actions' && options?.onSuggestedActions) {
                  options.onSuggestedActions(parsed.data?.actions || []);
                } else if (parsed.content) {
                  // Fallback for other formats
                  onChunk(parsed.content);
                }
              } catch (e) {
                // Skip invalid JSON or non-JSON lines
                console.warn('[API] Failed to parse SSE line:', trimmedLine);
              }
            }
          }
        };

        xhr.onload = () => {
          if (xhr.status === 200) {
            // Process any remaining buffered data
            if (buffer.trim()) {
              const trimmedLine = buffer.trim();
              if (trimmedLine.startsWith('data: ')) {
                const data = trimmedLine.slice(6);
                try {
                  const parsed = JSON.parse(data);
                  if (parsed.type === 'text_chunk' && parsed.data?.content) {
                    onChunk(parsed.data.content);
                  } else if (parsed.type === 'final_response') {
                    if (parsed.data?.conversation_id) {
                      receivedConversationId = parsed.data.conversation_id;
                      console.log('[API] ✅ Got conversation_id from final buffer:', receivedConversationId);
                    }
                    if (parsed.data?.episode_id) {
                      receivedEpisodeId = parsed.data.episode_id;
                      console.log('[API] ✅ Got episode_id from final buffer:', receivedEpisodeId);
                    }
                  }
                } catch (e) {
                  // Ignore parse errors for final buffer
                }
              }
            }

            if (receivedConversationId) {
              console.log('[API] ✅ Stream complete - calling onComplete with conversation_id:', receivedConversationId, 'episode_id:', receivedEpisodeId);
            } else {
              console.warn('[API] ⚠️ Stream complete but NO conversation_id received!');
            }
            // Call onComplete with the conversation_id and episode_id from backend
            onComplete(receivedConversationId, receivedEpisodeId);
            resolve();
          } else {
            const error = new Error(`HTTP error! status: ${xhr.status} - ${xhr.responseText}`);
            console.error('[API] Chat error:', error);
            onError(error);
            reject(error);
          }
        };

        xhr.onerror = () => {
          const error = new Error('Network error during streaming');
          console.error('[API] Network error:', error);
          onError(error);
          reject(error);
        };

        const requestBody: any = { messages };
        if (sessionId) {
          requestBody.conversation_id = sessionId;  // Backend expects conversation_id
        }
        if (options?.model) {
          requestBody.model = options.model;
        }
        if (options?.ephemeral) {
          requestBody.ephemeral = options.ephemeral;
        }
        if (options?.notifyOnComplete) {
          requestBody.notify_on_complete = options.notifyOnComplete;
        }
        if (options?.inboxItemId) {
          requestBody.inbox_item_id = options.inboxItemId;
        }
        if (options?.source) {
          requestBody.source = options.source;
        }
        if (options?.currentScreen) {
          requestBody.current_screen = options.currentScreen;
        }
        xhr.send(JSON.stringify(requestBody));
      });
    } catch (error) {
      console.error('[API] Chat error:', error);
      onError(error as Error);
    }
  }

  // Daily Briefings endpoints
  async getDailyBriefings(): Promise<any[]> {
    const response = await this.client.get('/api/briefings');
    return response.data;
  }

  async getBriefingSettings(): Promise<any> {
    const response = await this.client.get('/api/briefings/settings');
    return response.data;
  }

  async updateBriefingSettings(settings: any): Promise<any> {
    const response = await this.client.put('/api/briefings/settings', settings);
    return response.data;
  }

  async generateBriefing(type: 'morning' | 'evening'): Promise<any> {
    const response = await this.client.post('/api/briefings/generate', { briefing_type: type });
    return response.data;
  }

  async markBriefingRead(briefingId: string): Promise<void> {
    await this.client.patch(`/api/briefings/${briefingId}/read`);
  }

  // Context Mode endpoints
  async getContextMode(): Promise<any> {
    const response = await this.client.get('/api/context/mode');
    return response.data;
  }

  async setContextMode(mode: string): Promise<any> {
    const response = await this.client.put('/api/context/mode', { mode });
    return response.data;
  }

  async getContextStats(): Promise<any> {
    const response = await this.client.get('/api/context/stats');
    return response.data;
  }

  // Intelligence Reports endpoints
  async getIntelligenceReports(): Promise<any[]> {
    const response = await this.client.get('/api/reports/list');
    return response.data;
  }

  async generateIntelligenceReport(type: 'weekly' | 'monthly' | 'quarterly'): Promise<any> {
    const response = await this.client.post('/api/reports/generate', { report_type: type });
    return response.data;
  }

  // Proactive Suggestions endpoints
  async getProactiveSuggestions(): Promise<any[]> {
    const response = await this.client.get('/api/suggestions');
    return response.data;
  }

  async updateSuggestionStatus(suggestionId: string, status: 'accepted' | 'dismissed'): Promise<any> {
    const response = await this.client.patch(`/api/suggestions/${suggestionId}`, { status });
    return response.data;
  }

  // Detected Patterns endpoints
  async getDetectedPatterns(): Promise<any[]> {
    const response = await this.client.get('/api/patterns');
    return response.data;
  }

  // AI Settings endpoints
  async getAISettings(): Promise<any> {
    const response = await this.client.get('/settings/ai');
    return response.data;
  }

  async updateAISettings(settings: any): Promise<any> {
    const response = await this.client.put('/settings/ai', settings);
    return response.data;
  }

  async testAISettings(): Promise<any> {
    const response = await this.client.post('/settings/ai/test');
    return response.data;
  }

  // ==================== CONTENT INBOX ====================

  async getInboxItems(status?: string, limit: number = 50): Promise<any[]> {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    params.set('limit', String(limit));
    const response = await this.client.get(`/api/inbox?${params.toString()}`);
    return response.data;
  }

  async getInboxStats(): Promise<{ unread: number; read: number; kept: number; total: number }> {
    const response = await this.client.get('/api/inbox/stats');
    return response.data;
  }

  async getInboxItem(id: string): Promise<any> {
    const response = await this.client.get(`/api/inbox/${id}`);
    return response.data;
  }

  async shareToInbox(url: string, title?: string): Promise<any> {
    const response = await this.client.post('/api/inbox/share', { url, title });
    return response.data;
  }

  async shareTextToInbox(text: string, title?: string): Promise<any> {
    const response = await this.client.post('/api/inbox/share/text', { text, title });
    return response.data;
  }

  async updateInboxItemStatus(id: string, status: 'kept' | 'discarded'): Promise<any> {
    const response = await this.client.patch(`/api/inbox/${id}/status`, { status });
    return response.data;
  }

  async deleteInboxItem(id: string): Promise<void> {
    await this.client.delete(`/api/inbox/${id}`);
  }

  // ==================== PRESENCE LOGGING ====================

  /**
   * Log user presence/activity. Called on app open, resume, etc.
   */
  async logPresence(activityType: string = 'app_open'): Promise<void> {
    try {
      await this.client.post('/api/presence', {
        activity_type: activityType,
        platform: 'ios',
      });
      console.log(`[API] Presence logged: ${activityType}`);
    } catch (error) {
      // Don't throw - presence logging is best-effort
      console.warn('[API] Failed to log presence:', error);
    }
  }

  // ==================== AUTONOMY (Cortana Evolution) ====================

  async getAttentionItems(status?: string, limit: number = 50): Promise<any[]> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (status) params.append('status', status);
    const response = await this.client.get(`/autonomy/attention?${params}`);
    return (response.data as any)?.items || [];
  }

  async getAttentionCount(): Promise<{ counts: Record<string, number>; unread: number }> {
    const response = await this.client.get('/autonomy/attention/count');
    return response.data as any;
  }

  async markAttentionRead(id: string): Promise<void> {
    await this.client.post(`/autonomy/attention/${id}/read`);
  }

  async archiveAttentionItem(id: string): Promise<void> {
    await this.client.post(`/autonomy/attention/${id}/archive`);
  }

  async getMissions(state?: string): Promise<any[]> {
    const params = state ? `?state=${state}` : '';
    const response = await this.client.get(`/autonomy/missions${params}`);
    return (response.data as any)?.missions || [];
  }

  async getMission(id: string): Promise<any> {
    const response = await this.client.get(`/autonomy/missions/${id}`);
    return response.data;
  }

  async cancelMission(id: string): Promise<void> {
    await this.client.post(`/autonomy/missions/${id}/cancel`);
  }

  async confirmMission(id: string): Promise<void> {
    await this.client.post(`/autonomy/missions/${id}/confirm`);
  }

  async getActionTraces(hours: number = 24, limit: number = 50): Promise<any[]> {
    const response = await this.client.get(`/autonomy/traces?hours=${hours}&limit=${limit}`);
    return (response.data as any)?.traces || [];
  }

  async getTraceStats(hours: number = 24): Promise<any> {
    const response = await this.client.get(`/autonomy/traces/stats?hours=${hours}`);
    return response.data;
  }

  async getPolicyCandidates(status?: string): Promise<any[]> {
    const params = status ? `?status=${status}` : '';
    const response = await this.client.get(`/autonomy/policy-candidates${params}`);
    return (response.data as any)?.candidates || [];
  }

  async acceptPolicyCandidate(id: string): Promise<any> {
    const response = await this.client.post(`/autonomy/policy-candidates/${id}/accept`);
    return response.data;
  }

  async rejectPolicyCandidate(id: string): Promise<any> {
    const response = await this.client.post(`/autonomy/policy-candidates/${id}/reject`);
    return response.data;
  }
}

export const apiClient = new ApiClient();
export default apiClient;

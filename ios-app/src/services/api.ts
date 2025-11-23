import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// API Configuration
const API_URL = __DEV__
  ? 'http://10.185.1.180:8000'  // Development - LAN backend
  : 'https://sara-api.avery.cloud';  // Production

const TOKEN_KEY = '@sara_auth_token';

class ApiClient {
  private client: AxiosInstance;
  public baseURL: string;

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
          // Could trigger navigation to login here
        }
        return Promise.reject(error);
      }
    );
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

  // Streaming support for chat using XMLHttpRequest (works in React Native)
  async streamChat(
    messages: any[],
    onChunk: (chunk: string) => void,
    onComplete: (conversationId?: string) => void,
    onError: (error: Error) => void,
    sessionId?: string
  ) {
    try {
      const token = await this.getAuthToken();
      console.log('[API] Sending chat request to:', `${API_URL}/chat/stream`);

      return new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        let buffer = '';
        let lastProcessedIndex = 0;
        let receivedConversationId: string | undefined = undefined;

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
                  // Final response event - extract conversation_id
                  console.log('[API] Received final_response event');
                  console.log('[API] Full final_response data:', JSON.stringify(parsed.data));
                  if (parsed.data?.conversation_id) {
                    receivedConversationId = parsed.data.conversation_id;
                    console.log('[API] ✅ Got conversation_id:', receivedConversationId);
                  } else {
                    console.warn('[API] ⚠️ No conversation_id in final_response!');
                  }
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
                    } else {
                      console.warn('[API] ⚠️ No conversation_id in final buffer!');
                    }
                  }
                } catch (e) {
                  // Ignore parse errors for final buffer
                }
              }
            }

            if (receivedConversationId) {
              console.log('[API] ✅ Stream complete - calling onComplete with conversation_id:', receivedConversationId);
            } else {
              console.warn('[API] ⚠️ Stream complete but NO conversation_id received!');
            }
            // Call onComplete with the conversation_id from backend
            onComplete(receivedConversationId);
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
}

export const apiClient = new ApiClient();
export default apiClient;

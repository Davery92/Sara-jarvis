import apiClient from './api';
import AsyncStorage from '@react-native-async-storage/async-storage';

export interface User {
  id: string;
  email: string;
  username?: string;
  created_at: string;
  preferences?: UserPreferences;
}

export interface UserPreferences {
  theme?: 'light' | 'dark';
  notifications_enabled?: boolean;
  reminder_notifications?: boolean;
  email_notifications?: boolean;
  default_reminder_time?: number;
  timezone?: string;
}

export interface Episode {
  id: string;
  content: string;
  episode_type: string;
  timestamp: string;
  importance_score: number;
  source?: string;
  role?: string;
  metadata?: any;
}

interface EpisodesApiItem {
  id: string;
  source?: string;
  role?: string;
  content?: string;
  importance?: number;
  meta?: any;
  created_at?: string;
}

interface EpisodesApiResponse {
  episodes?: EpisodesApiItem[];
  total?: number;
  page?: number;
  per_page?: number;
}

export interface UpdateUserParams {
  username?: string;
  email?: string;
}

export interface UpdatePreferencesParams {
  theme?: 'light' | 'dark';
  notifications_enabled?: boolean;
  reminder_notifications?: boolean;
  email_notifications?: boolean;
  default_reminder_time?: number;
  timezone?: string;
}

class SettingsService {
  // User Management

  /**
   * Get current user profile
   */
  async getCurrentUser(): Promise<User> {
    return await apiClient.get<User>('/auth/me');
  }

  /**
   * Update user profile
   */
  async updateUser(params: UpdateUserParams): Promise<User> {
    return await apiClient.put<User>('/auth/me', params);
  }

  /**
   * Get user preferences
   */
  async getPreferences(): Promise<UserPreferences> {
    return await apiClient.get<UserPreferences>('/settings/preferences');
  }

  /**
   * Update user preferences
   */
  async updatePreferences(params: UpdatePreferencesParams): Promise<UserPreferences> {
    return await apiClient.put<UserPreferences>('/settings/preferences', params);
  }

  // Memory/Episodes

  /**
   * Get memory episodes
   */
  async getEpisodes(limit?: number, offset?: number): Promise<Episode[]> {
    const perPage = limit ?? 20;
    const page = offset !== undefined ? Math.floor(offset / perPage) + 1 : 1;

    const params = new URLSearchParams();
    params.append('per_page', perPage.toString());
    params.append('page', page.toString());

    const raw = await apiClient.get<EpisodesApiResponse | EpisodesApiItem[]>(`/memory/episodes?${params.toString()}`);
    const items = Array.isArray(raw) ? raw : (raw.episodes || []);

    return items.map((item) => ({
      id: String(item.id),
      content: item.content || '',
      episode_type: item.meta?.memory_type || item.source || 'memory',
      timestamp: item.created_at || new Date().toISOString(),
      importance_score: typeof item.importance === 'number' ? item.importance : 0,
      source: item.source,
      role: item.role,
      metadata: item.meta,
    }));
  }

  /**
   * Delete a specific episode
   */
  async deleteEpisode(episodeId: string): Promise<void> {
    await apiClient.delete(`/memory/episodes/${episodeId}`);
  }

  /**
   * Clear all episodes
   */
  async clearAllEpisodes(): Promise<void> {
    await apiClient.delete('/memory/episodes');
  }

  // Local Storage Helpers

  /**
   * Save local preference
   */
  async saveLocalPreference(key: string, value: string): Promise<void> {
    await AsyncStorage.setItem(`pref_${key}`, value);
  }

  /**
   * Get local preference
   */
  async getLocalPreference(key: string): Promise<string | null> {
    return await AsyncStorage.getItem(`pref_${key}`);
  }

  /**
   * Clear local preferences
   */
  async clearLocalPreferences(): Promise<void> {
    const keys = await AsyncStorage.getAllKeys();
    const prefKeys = keys.filter((key) => key.startsWith('pref_'));
    await AsyncStorage.multiRemove(prefKeys);
  }

  // Helper Methods

  /**
   * Format episode timestamp
   */
  formatEpisodeTime(timestamp: string): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;

    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    });
  }

  /**
   * Get episode type emoji
   */
  getEpisodeTypeEmoji(episodeType: string): string {
    const typeMap: Record<string, string> = {
      user_message: '👤',
      assistant_message: '🤖',
      action: '⚡',
      tool_use: '🔧',
      memory: '💭',
      note: '📝',
      reminder: '🔔',
      event: '📅',
    };
    return typeMap[episodeType] || '💬';
  }

  /**
   * Get importance color
   */
  getImportanceColor(score: number): string {
    if (score >= 0.8) return '#ef4444'; // high
    if (score >= 0.5) return '#f59e0b'; // medium
    return '#6b7280'; // low
  }

  /**
   * Format importance score
   */
  formatImportanceScore(score: number): string {
    return `${Math.round(score * 100)}%`;
  }
}

export const settingsService = new SettingsService();
export default settingsService;

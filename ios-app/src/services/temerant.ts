import apiClient from './api';

export type TemerantAttribute = 'body' | 'mind' | 'craft' | 'coin' | 'name';

export interface TemerantCharacter {
  id: string;
  user_id: string;
  character_name: string;
  backstory?: string | null;
  origin?: string | null;
  current_rank: 'elir' | 'relar' | 'elthe';
  coin_balance: number;
  alar_strength: number;
  naming_affinity: number;
}

export interface TemerantOracleEvent {
  id: string;
  local_date: string;
  tier: 'notable' | 'major';
  category: 'academic' | 'social' | 'discovery' | 'financial' | 'challenge' | 'mystery';
  title: string;
  hook: string;
  status: 'open' | 'resolved' | 'dismissed';
  resolution?: string | null;
}

export interface TemerantDashboard {
  date: string;
  character: TemerantCharacter;
  attributes: Record<TemerantAttribute, {
    attribute: TemerantAttribute;
    xp_total: number;
    xp_term: number;
    level: number;
    xp_today: number;
  }>;
  daily: {
    local_date: string;
    categories_completed: number;
    body_xp: number;
    mind_xp: number;
    craft_xp: number;
    coin_xp: number;
    name_xp: number;
    oracle_roll_raw?: number | null;
    oracle_roll_modified?: number | null;
    term_month: string;
  };
  oracle_event?: TemerantOracleEvent | null;
  rank_progress: {
    next_rank?: string | null;
    requirements: Record<string, number>;
  };
}

export interface TemerantTerm {
  id: string;
  term_month: string;
  completion_pct: number;
  admissions_result: 'excellent' | 'good' | 'poor' | 'terrible';
  tuition_talents: number;
  xp_multiplier: number;
  coin_delta: number;
}

export interface TemerantJournalEntry {
  id: string;
  local_date: string;
  summary_markdown: string;
  source_event_count: number;
}

export interface TemerantStarterProfile {
  id: string;
  name: string;
  description: string;
  character_name: string;
  origin?: string | null;
  backstory: string;
  current_rank: 'elir' | 'relar' | 'elthe';
  coin_balance: number;
  alar_strength: number;
  naming_affinity: number;
  attribute_xp: Partial<Record<TemerantAttribute, number>>;
  inventory: string[];
  patron?: string | null;
  personality?: string | null;
  flaw?: string | null;
  key_npcs: string[];
}

class TemerantService {
  async createCharacter(payload: { character_name?: string; backstory?: string; origin?: string; starter_profile?: string }): Promise<TemerantCharacter> {
    return apiClient.post('/api/temerant/character', payload);
  }

  async getStarterProfiles(): Promise<TemerantStarterProfile[]> {
    return apiClient.get('/api/temerant/starter-profiles');
  }

  async getCharacter(): Promise<TemerantCharacter> {
    return apiClient.get('/api/temerant/character');
  }

  async getDashboard(date?: string): Promise<TemerantDashboard> {
    const query = date ? `?date=${encodeURIComponent(date)}` : '';
    return apiClient.get(`/api/temerant/dashboard${query}`);
  }

  async getCurrentTerm(): Promise<TemerantTerm> {
    return apiClient.get('/api/temerant/terms/current');
  }

  async listJournal(limit: number = 5): Promise<TemerantJournalEntry[]> {
    return apiClient.get(`/api/temerant/journal?limit=${limit}`);
  }

  async createManualLog(payload: { action_type: string; action_label?: string; quantity?: number; notes?: string }): Promise<any> {
    return apiClient.post('/api/temerant/logs/manual', payload);
  }

  async rollOracle(): Promise<TemerantOracleEvent | null> {
    return apiClient.post('/api/temerant/oracle/roll');
  }

  async listOracleEvents(status?: string, limit: number = 10): Promise<TemerantOracleEvent[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    params.append('limit', String(limit));
    return apiClient.get(`/api/temerant/oracle/events?${params.toString()}`);
  }

  async resolveOracleEvent(eventId: string, payload: { status?: 'resolved' | 'dismissed'; resolution?: string }): Promise<TemerantOracleEvent> {
    return apiClient.post(`/api/temerant/oracle/events/${eventId}/resolve`, payload);
  }
}

export const temerantService = new TemerantService();
export default temerantService;

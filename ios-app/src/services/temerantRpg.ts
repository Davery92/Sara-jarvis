import apiClient from './api';

export interface TemerantRpgCharacter {
  id: string;
  user_id: string;
  character_name: string;
  origin?: string | null;
  backstory?: string | null;
  body: number;
  mind: number;
  craft: number;
  voice: number;
  luck: number;
  coin_talents: number;
  rank: string;
  conditions: Record<string, any>;
  skills: Record<string, number>;
  inventory: string[];
  term_index: number;
  current_scene_id?: string | null;
}

export interface TemerantRpgWorldState {
  local_date: string;
  day_slot: string;
  weather: string;
  location_hint: string;
  ambient_events: string[];
  pending_consequences: Array<Record<string, any>>;
  last_advance_summary?: string | null;
}

export interface TemerantRpgScene {
  id: string;
  scene_number: number;
  local_date: string;
  day_slot: string;
  location: string;
  title: string;
  opening_text: string;
  status: 'open' | 'closed';
  summary?: string | null;
  consequences: Array<Record<string, any>>;
  opened_at: string;
  closed_at?: string | null;
}

export interface TemerantRpgRelationship {
  npc_key: string;
  display_name: string;
  disposition: string;
  trust: string;
  respect: string;
  debt_balance: number;
  notes?: string | null;
}

export interface TemerantRpgState {
  character: TemerantRpgCharacter;
  world: TemerantRpgWorldState;
  open_scene?: TemerantRpgScene | null;
  relationships: TemerantRpgRelationship[];
}

export interface TemerantRpgTurnResponse {
  scene_id: string;
  turn_index: number;
  outcome: string;
  total: number;
  difficulty: number;
  margin: number;
  response_text: string;
  consequence?: Record<string, any> | null;
}

export interface TemerantRpgJournalEntry {
  id: string;
  local_date: string;
  summary_markdown: string;
  scene_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface TemerantRpgTerm {
  id: string;
  term_index: number;
  month: string;
  admissions_result: string;
  tuition_talents: number;
  summary: string;
  created_at: string;
  updated_at: string;
}

class TemerantRpgService {
  async createCharacter(payload: {
    character_name: string;
    origin?: string;
    backstory?: string;
  }): Promise<TemerantRpgCharacter> {
    return apiClient.post('/api/temerant-rpg/characters', payload);
  }

  async getState(): Promise<TemerantRpgState> {
    return apiClient.get('/api/temerant-rpg/state');
  }

  async openScene(payload?: {
    title?: string;
    location?: string;
    opening_prompt?: string;
  }): Promise<TemerantRpgScene> {
    return apiClient.post('/api/temerant-rpg/scenes/open', payload || {});
  }

  async actInScene(sceneId: string, payload: {
    action: string;
    attribute?: string;
    skill?: string;
  }): Promise<TemerantRpgTurnResponse> {
    return apiClient.post(`/api/temerant-rpg/scenes/${sceneId}/act`, payload);
  }

  async closeScene(sceneId: string, summary?: string): Promise<TemerantRpgScene> {
    return apiClient.post(`/api/temerant-rpg/scenes/${sceneId}/close`, { summary });
  }

  async advanceTime(slots: number = 1): Promise<{ local_date: string; day_slot: string; summary: string }> {
    return apiClient.post('/api/temerant-rpg/time/advance', { slots });
  }

  async listJournal(limit: number = 10): Promise<TemerantRpgJournalEntry[]> {
    return apiClient.get(`/api/temerant-rpg/journal?limit=${limit}`);
  }

  async runAdmissions(term_index?: number): Promise<TemerantRpgTerm> {
    return apiClient.post('/api/temerant-rpg/admissions/run', { term_index });
  }

  async listTerms(limit: number = 6): Promise<TemerantRpgTerm[]> {
    return apiClient.get(`/api/temerant-rpg/terms?limit=${limit}`);
  }
}

export const temerantRpgService = new TemerantRpgService();
export default temerantRpgService;

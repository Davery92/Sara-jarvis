import apiClient from './api';

// Cardio tracker service — sibling of fitnessService, cardio-shaped
// (minutes / distance / HR / zone). Talks to /api/fitness/cardio/*.

export interface CardioLog {
  id: string;
  activity_type: string;   // walk | ruck | kb_swings | coaching | commute | run | row | bike | tabata | other
  title: string;
  duration_minutes: number;
  distance_miles?: number | null;
  avg_hr?: number | null;
  max_hr?: number | null;
  zone?: string | null;
  calories_burned?: number | null;
  rpe?: number | null;
  source: string;          // manual | tabata | apple_health
  tabata_detail?: TabataDetail | null;
  notes: string;
  session_date: string;    // YYYY-MM-DD
  logged_at: string;       // ISO
}

export interface TabataDetail {
  work: number;
  rest: number;
  rounds: number;
  sets: number;
  completed_rounds?: number;
  preset_name?: string;
}

export interface CreateCardioLogParams {
  activity_type: string;
  title?: string;
  duration_minutes: number;
  distance_miles?: number | null;
  avg_hr?: number | null;
  max_hr?: number | null;
  zone?: string | null;
  calories_burned?: number | null;
  rpe?: number | null;
  source?: string;
  tabata_detail?: TabataDetail | null;
  notes?: string;
  session_date?: string;
}

export interface CardioMenuItem {
  key: string;
  label: string;
  typical_minutes: number;
  worth_minutes: number;
  note: string;
}

export interface CardioSettings {
  weekly_min_minutes: number;
  weekly_max_minutes: number;
  steps_floor: number;
  menu: CardioMenuItem[];
}

export interface CardioByActivity {
  activity_type: string;
  minutes: number;
  count: number;
}

export interface CardioTrendPoint {
  week_start: string;
  minutes: number;
}

export interface CardioStats {
  week_start: string;
  week_end: string;
  target_min: number;
  target_max: number;
  total_minutes: number;
  pct_of_min: number;
  session_count: number;
  steps_today: number | null;
  steps_floor: number;
  by_activity: CardioByActivity[];
  trend: CardioTrendPoint[];
}

export interface TabataPreset {
  id: string;
  name: string;
  prepare_seconds: number;
  work_seconds: number;
  rest_seconds: number;
  rounds: number;          // intervals per set
  sets: number;
  rest_between_sets_seconds: number;
  activity_type: string;
  color?: string | null;
  is_built_in: boolean;
  sort_order: number;
}

export interface CreateTabataPresetParams {
  name: string;
  prepare_seconds?: number;
  work_seconds: number;
  rest_seconds: number;
  rounds: number;
  sets?: number;
  rest_between_sets_seconds?: number;
  activity_type?: string;
  color?: string | null;
}

const BASE = '/api/fitness/cardio';

class CardioService {
  // ---- logs ----
  async getLogs(start?: string, end?: string): Promise<{ logs: CardioLog[]; start: string; end: string }> {
    const params = new URLSearchParams();
    if (start) params.append('start', start);
    if (end) params.append('end', end);
    const qs = params.toString();
    return apiClient.get(`${BASE}/logs${qs ? `?${qs}` : ''}`);
  }

  async createLog(params: CreateCardioLogParams): Promise<CardioLog> {
    return apiClient.post<CardioLog>(`${BASE}/log`, params);
  }

  async updateLog(id: string, patch: Partial<CreateCardioLogParams>): Promise<CardioLog> {
    return apiClient.patch<CardioLog>(`${BASE}/log/${id}`, patch);
  }

  async deleteLog(id: string): Promise<void> {
    await apiClient.delete(`${BASE}/log/${id}`);
  }

  // ---- stats ----
  async getStats(weekOffset = 0): Promise<CardioStats> {
    return apiClient.get<CardioStats>(`${BASE}/stats?week_offset=${weekOffset}`);
  }

  // ---- settings ----
  async getSettings(): Promise<CardioSettings> {
    return apiClient.get<CardioSettings>(`${BASE}/settings`);
  }

  async updateSettings(patch: Partial<CardioSettings>): Promise<CardioSettings> {
    return apiClient.put<CardioSettings>(`${BASE}/settings`, patch);
  }

  // ---- tabata presets ----
  async getPresets(): Promise<TabataPreset[]> {
    const res = await apiClient.get<{ presets: TabataPreset[] }>(`${BASE}/tabata-presets`);
    return res.presets;
  }

  async createPreset(params: CreateTabataPresetParams): Promise<TabataPreset> {
    return apiClient.post<TabataPreset>(`${BASE}/tabata-presets`, params);
  }

  async updatePreset(id: string, patch: Partial<CreateTabataPresetParams> & { sort_order?: number }): Promise<TabataPreset> {
    return apiClient.patch<TabataPreset>(`${BASE}/tabata-presets/${id}`, patch);
  }

  async deletePreset(id: string): Promise<void> {
    await apiClient.delete(`${BASE}/tabata-presets/${id}`);
  }
}

export const cardioService = new CardioService();
export default cardioService;

// ---- shared helpers (used by the timer + activity labels) ----

export const ACTIVITY_META: Record<string, { label: string; icon: string; color: string }> = {
  walk: { label: 'Walk', icon: 'walk', color: '#34d399' },
  ruck: { label: 'Ruck', icon: 'trail-sign', color: '#f59e0b' },
  kb_swings: { label: 'KB Swings', icon: 'barbell', color: '#fb923c' },
  coaching: { label: 'Coaching', icon: 'baseball', color: '#38bdf8' },
  commute: { label: 'Commute', icon: 'car', color: '#a78bfa' },
  run: { label: 'Run', icon: 'walk', color: '#22d3ee' },
  row: { label: 'Row', icon: 'boat', color: '#22d3ee' },
  bike: { label: 'Bike', icon: 'bicycle', color: '#22d3ee' },
  hike: { label: 'Hike', icon: 'trail-sign', color: '#34d399' },
  cycle: { label: 'Cycle', icon: 'bicycle', color: '#22d3ee' },
  tabata: { label: 'Tabata', icon: 'timer', color: '#ef4444' },
  other: { label: 'Cardio', icon: 'pulse', color: '#94a3b8' },
};

export function activityMeta(type: string) {
  return ACTIVITY_META[type] || ACTIVITY_META.other;
}

// A single phase in a running interval timer.
export type TabataPhaseKind = 'prepare' | 'work' | 'rest' | 'rest_set' | 'done';

export interface TabataPhase {
  kind: TabataPhaseKind;
  seconds: number;
  round: number;   // 1-based within the current set
  set: number;     // 1-based
  label: string;
}

// Expand a preset into a flat ordered list of phases.
export function buildTabataSequence(p: {
  prepare_seconds: number;
  work_seconds: number;
  rest_seconds: number;
  rounds: number;
  sets: number;
  rest_between_sets_seconds: number;
}): TabataPhase[] {
  const seq: TabataPhase[] = [];
  if (p.prepare_seconds > 0) {
    seq.push({ kind: 'prepare', seconds: p.prepare_seconds, round: 1, set: 1, label: 'Get ready' });
  }
  for (let s = 1; s <= p.sets; s++) {
    for (let r = 1; r <= p.rounds; r++) {
      seq.push({ kind: 'work', seconds: p.work_seconds, round: r, set: s, label: 'Work' });
      // rest after every work except the very last round of the last set
      const isLastRound = r === p.rounds;
      const isLastSet = s === p.sets;
      if (!(isLastRound && isLastSet) && p.rest_seconds > 0 && !isLastRound) {
        seq.push({ kind: 'rest', seconds: p.rest_seconds, round: r, set: s, label: 'Rest' });
      }
    }
    // rest between sets (not after the last set)
    if (s < p.sets && p.rest_between_sets_seconds > 0) {
      seq.push({ kind: 'rest_set', seconds: p.rest_between_sets_seconds, round: p.rounds, set: s, label: 'Set break' });
    }
  }
  return seq;
}

// Total workout seconds for a preset (excludes the final trailing state).
export function tabataTotalSeconds(p: {
  prepare_seconds: number;
  work_seconds: number;
  rest_seconds: number;
  rounds: number;
  sets: number;
  rest_between_sets_seconds: number;
}): number {
  return buildTabataSequence(p).reduce((sum, ph) => sum + ph.seconds, 0);
}

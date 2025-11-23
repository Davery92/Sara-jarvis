import apiClient from './api';

export interface Timer {
  id: string;
  user_id: string;
  title: string;
  duration_minutes: number;
  start_time: string;
  end_time: string;
  is_active: boolean;
  is_completed: boolean;
  created_at: string;
}

export interface TimerCreate {
  title: string;
  duration_minutes?: number;
  duration_seconds?: number;
}

class TimerService {
  async getActiveTimers(): Promise<Timer[]> {
    return apiClient.get<Timer[]>('/timers');
  }

  async startTimer(title: string, durationSeconds: number): Promise<Timer> {
    return apiClient.post<Timer>('/timers', { title, duration_seconds: durationSeconds });
  }

  async stopTimer(timerId: string): Promise<void> {
    return apiClient.patch<void>(`/timers/${timerId}/stop`, {});
  }
}

export const timerService = new TimerService();
export default timerService;

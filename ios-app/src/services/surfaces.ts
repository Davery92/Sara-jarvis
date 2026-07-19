/**
 * Surfaces service — post interaction events and refetch surface state.
 */
import { apiClient } from './api';

export interface SurfaceModel {
  id: string;
  title: string;
  spec: { components: any[] };
  state: Record<string, any>;
  status: string;
  version: number;
}

export interface SurfaceEventPayload {
  component_id: string;
  event: 'check' | 'step' | 'submit' | 'click' | 'set';
  value?: Record<string, any>;
}

class SurfacesService {
  async get(id: string): Promise<SurfaceModel> {
    return apiClient.get<SurfaceModel>(`/api/surfaces/${id}`);
  }

  async list(params: { status?: string; conversation_id?: string } = {}): Promise<SurfaceModel[]> {
    const qs = new URLSearchParams();
    qs.append('status', params.status || 'active');
    if (params.conversation_id) qs.append('conversation_id', params.conversation_id);
    return apiClient.get<SurfaceModel[]>(`/api/surfaces?${qs.toString()}`);
  }

  async postEvent(id: string, payload: SurfaceEventPayload): Promise<{ state: Record<string, any> }> {
    return apiClient.post<{ state: Record<string, any> }>(`/api/surfaces/${id}/events`, payload);
  }
}

export const surfacesService = new SurfacesService();

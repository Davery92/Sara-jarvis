/**
 * Artifacts Hook
 * Manages artifact state and API interactions
 */
import { useState, useCallback, useEffect } from 'react';
import { APP_CONFIG } from '../../../config';
import { Artifact, ArtifactType, ArtifactContent, ArtifactMetadata } from '../types';

// Simple fetch wrapper with credentials
const api = {
  async get(url: string) {
    const response = await fetch(`${APP_CONFIG.apiUrl}${url}`, {
      credentials: 'include',
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return { data: await response.json() };
  },
  async post(url: string, data: any) {
    const response = await fetch(`${APP_CONFIG.apiUrl}${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return { data: await response.json() };
  },
  async put(url: string, data: any) {
    const response = await fetch(`${APP_CONFIG.apiUrl}${url}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return { data: await response.json() };
  },
  async delete(url: string) {
    const response = await fetch(`${APP_CONFIG.apiUrl}${url}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return { data: response.status === 204 ? null : await response.json() };
  },
};

interface UseArtifactsOptions {
  conversationId?: string;
  autoLoad?: boolean;
}

interface UseArtifactsReturn {
  artifacts: Artifact[];
  loading: boolean;
  error: string | null;
  createArtifact: (
    type: ArtifactType,
    title: string,
    content: ArtifactContent,
    metadata?: ArtifactMetadata
  ) => Promise<Artifact | null>;
  updateArtifact: (
    id: string,
    updates: Partial<Pick<Artifact, 'title' | 'content' | 'metadata' | 'is_pinned'>>
  ) => Promise<Artifact | null>;
  deleteArtifact: (id: string) => Promise<boolean>;
  refreshArtifacts: () => Promise<void>;
  getArtifact: (id: string) => Artifact | undefined;
}

export function useArtifacts(options: UseArtifactsOptions = {}): UseArtifactsReturn {
  const { conversationId, autoLoad = true } = options;

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load artifacts
  const refreshArtifacts = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      let url = '/api/artifacts';
      if (conversationId) {
        url = `/api/artifacts/conversation/${conversationId}`;
      }

      const response = await api.get(url);
      setArtifacts(response.data);
    } catch (e: any) {
      setError(e.message || 'Failed to load artifacts');
      console.error('Failed to load artifacts:', e);
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  // Auto-load on mount
  useEffect(() => {
    if (autoLoad) {
      refreshArtifacts();
    }
  }, [autoLoad, refreshArtifacts]);

  // Create artifact
  const createArtifact = useCallback(async (
    type: ArtifactType,
    title: string,
    content: ArtifactContent,
    metadata?: ArtifactMetadata
  ): Promise<Artifact | null> => {
    try {
      const response = await api.post('/api/artifacts', {
        artifact_type: type,
        title,
        content,
        metadata: metadata || {},
        conversation_id: conversationId,
      });

      const newArtifact = response.data;
      setArtifacts(prev => [newArtifact, ...prev]);
      return newArtifact;
    } catch (e: any) {
      setError(e.message || 'Failed to create artifact');
      console.error('Failed to create artifact:', e);
      return null;
    }
  }, [conversationId]);

  // Update artifact
  const updateArtifact = useCallback(async (
    id: string,
    updates: Partial<Pick<Artifact, 'title' | 'content' | 'metadata' | 'is_pinned'>>
  ): Promise<Artifact | null> => {
    try {
      const response = await api.put(`/api/artifacts/${id}`, updates);
      const updatedArtifact = response.data;

      setArtifacts(prev => prev.map(a =>
        a.id === id ? updatedArtifact : a
      ));

      return updatedArtifact;
    } catch (e: any) {
      setError(e.message || 'Failed to update artifact');
      console.error('Failed to update artifact:', e);
      return null;
    }
  }, []);

  // Delete artifact
  const deleteArtifact = useCallback(async (id: string): Promise<boolean> => {
    try {
      await api.delete(`/api/artifacts/${id}`);
      setArtifacts(prev => prev.filter(a => a.id !== id));
      return true;
    } catch (e: any) {
      setError(e.message || 'Failed to delete artifact');
      console.error('Failed to delete artifact:', e);
      return false;
    }
  }, []);

  // Get artifact by ID
  const getArtifact = useCallback((id: string): Artifact | undefined => {
    return artifacts.find(a => a.id === id);
  }, [artifacts]);

  return {
    artifacts,
    loading,
    error,
    createArtifact,
    updateArtifact,
    deleteArtifact,
    refreshArtifacts,
    getArtifact,
  };
}

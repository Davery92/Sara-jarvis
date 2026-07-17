import * as DocumentPicker from 'expo-document-picker';
import apiClient from './api';

export interface LearningBlueprintSummary {
  id: string;
  title: string;
  subtitle?: string | null;
  description?: string | null;
  status: string;
  import_confidence?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface GuideGenerationJob {
  id: string;
  status: string;
  progress: number;
  current_step?: string | null;
  total_modules?: number;
  completed_modules?: number;
  artifacts_created?: number;
  model?: string | null;
  error_message?: string | null;
}

export interface GuideArtifact {
  id: string;
  topic_id?: string | null;
  artifact_type: string;
  title?: string | null;
  version?: number;
  content?: {
    module_code?: string;
    module_title?: string;
    guide_markdown?: string;
    model?: string;
    num_ctx?: number;
    generated_at?: string;
    sources?: Array<{ title?: string; url?: string | null }>;
  };
  updated_at?: string | null;
  created_at?: string | null;
}

export interface LessonArtifact {
  id: string;
  topic_id?: string | null;
  artifact_type: string;
  title?: string | null;
  version?: number;
  content?: {
    module_code?: string;
    module_title?: string;
    lesson_markdown?: string;
    model?: string;
    num_ctx?: number;
    generated_at?: string;
    word_count?: number;
    estimated_read_time_minutes?: number;
    sources?: Array<{ title?: string; url?: string | null }>;
  };
  updated_at?: string | null;
  created_at?: string | null;
}

export interface BlueprintSource {
  id: string;
  topic_id: string;
  topic_title: string;
  source_type: string;
  url?: string | null;
  title?: string | null;
  quality_score: number;
  fetch_status: string;
  chunk_count: number;
  has_chapters: boolean;
  chapter_count: number;
  created_at: string;
}

class LearningService {
  async listBlueprints(): Promise<LearningBlueprintSummary[]> {
    const response = await apiClient.get<{ blueprints?: LearningBlueprintSummary[] }>('/api/learn/blueprints');
    return Array.isArray(response?.blueprints) ? response.blueprints : [];
  }

  async generateBlueprintGuides(
    blueprintId: string,
    options?: { model?: string; force_regenerate?: boolean; module_limit?: number; num_ctx?: number }
  ): Promise<{ job_id: string; status: string }> {
    return apiClient.post(`/api/learn/blueprints/${blueprintId}/guides/generate`, {
      // Omit model unless explicitly chosen — the backend picks its default
      // (the old hardcoded gpt-oss:120b no longer exists anywhere).
      ...(options?.model ? { model: options.model } : {}),
      force_regenerate: options?.force_regenerate ?? false,
      module_limit: options?.module_limit,
      num_ctx: options?.num_ctx ?? 32768,
    });
  }

  async listGuideJobs(blueprintId: string, limit: number = 20): Promise<GuideGenerationJob[]> {
    const response = await apiClient.get<{ jobs?: GuideGenerationJob[] }>(
      `/api/learn/blueprints/${blueprintId}/guides/jobs?limit=${limit}`
    );
    return Array.isArray(response?.jobs) ? response.jobs : [];
  }

  async getGuideJob(blueprintId: string, jobId: string): Promise<GuideGenerationJob> {
    return apiClient.get(`/api/learn/blueprints/${blueprintId}/guides/jobs/${jobId}`);
  }

  async cancelGuideJob(blueprintId: string, jobId: string): Promise<GuideGenerationJob | null> {
    const response = await apiClient.post<{ job?: GuideGenerationJob }>(
      `/api/learn/blueprints/${blueprintId}/guides/jobs/${jobId}/cancel`
    );
    return response?.job || null;
  }

  async listGuides(blueprintId: string): Promise<GuideArtifact[]> {
    const response = await apiClient.get<{ guides?: GuideArtifact[] }>(`/api/learn/blueprints/${blueprintId}/guides`);
    return Array.isArray(response?.guides) ? response.guides : [];
  }

  async listBlueprintSources(blueprintId: string): Promise<BlueprintSource[]> {
    const response = await apiClient.get<{ sources?: BlueprintSource[] }>(
      `/api/learn/blueprints/${blueprintId}/sources`
    );
    return Array.isArray(response?.sources) ? response.sources : [];
  }

  async discoverResources(blueprintId: string): Promise<{ status: string; task_id: string }> {
    return apiClient.post(`/api/learn/blueprints/${blueprintId}/discover-resources`, {});
  }

  // ── Lesson methods ──

  async generateBlueprintLessons(
    blueprintId: string,
    options?: { model?: string; force_regenerate?: boolean; module_limit?: number; num_ctx?: number }
  ): Promise<{ job_id: string; status: string }> {
    return apiClient.post(`/api/learn/blueprints/${blueprintId}/lessons/generate`, {
      ...(options?.model ? { model: options.model } : {}),
      force_regenerate: options?.force_regenerate ?? false,
      module_limit: options?.module_limit,
      num_ctx: options?.num_ctx ?? 65536,
    });
  }

  async listLessonJobs(blueprintId: string, limit: number = 20): Promise<GuideGenerationJob[]> {
    const response = await apiClient.get<{ jobs?: GuideGenerationJob[] }>(
      `/api/learn/blueprints/${blueprintId}/lessons/jobs?limit=${limit}`
    );
    return Array.isArray(response?.jobs) ? response.jobs : [];
  }

  async listLessons(blueprintId: string): Promise<LessonArtifact[]> {
    const response = await apiClient.get<{ lessons?: LessonArtifact[] }>(
      `/api/learn/blueprints/${blueprintId}/lessons`
    );
    return Array.isArray(response?.lessons) ? response.lessons : [];
  }

  async uploadSourceToTopic(
    topicId: string,
    asset: DocumentPicker.DocumentPickerAsset,
    title?: string
  ): Promise<{
    status: string;
    source_id: string;
    topic_id: string;
    title: string;
    chunk_count?: number;
    message?: string;
  }> {
    // Use raw XMLHttpRequest for multipart upload — bypasses all axios
    // header issues while still using RN's native multipart handling.
    const token = await apiClient.getToken();
    const formData = new FormData();
    formData.append('topic_id', topicId);
    if (title?.trim()) {
      formData.append('title', title.trim());
    }
    formData.append('file', {
      uri: asset.uri,
      name: asset.name || 'source-upload',
      type: asset.mimeType || 'application/octet-stream',
    } as any);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${apiClient.baseURL}/api/learn/sources/upload`);
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }
      // Do NOT set Content-Type — RN's XHR sets it with boundary for FormData
      xhr.timeout = 300000; // 5 min
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            resolve({ status: 'processing', source_id: '', topic_id: topicId, title: '' } as any);
          }
        } else {
          reject(new Error(`Upload failed (${xhr.status}): ${xhr.responseText}`));
        }
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.ontimeout = () => reject(new Error('Upload timed out'));
      xhr.send(formData);
    });
  }
}

export const learningService = new LearningService();
export default learningService;

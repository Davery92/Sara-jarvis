// progressPhotos — physique progress photos with on-demand VLM critique.
// Mirrors the documents/inbox upload patterns: multipart upload via
// apiClient.upload (bearer auth + boundary handled by the RN layer), image
// bytes fetched from an auth-protected /file route, critique run server-side.
import apiClient from './api';

export interface ProgressPhoto {
  id: string;
  original_filename: string | null;
  mime_type: string | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  notes: string | null;
  bodyweight: number | null;
  bodyweight_unit: string | null;
  critique: string | null;
  critique_model: string | null;
  critiqued_at: string | null;
  has_critique: boolean;
  created_at: string | null;
}

export interface CritiqueResult {
  id: string;
  critique: string;
  critique_model: string | null;
  critiqued_at: string | null;
}

export interface UploadMeta {
  notes?: string;
  bodyweight?: number;
  bodyweight_unit?: string;
  taken_at?: string;
}

const BASE = '/api/fitness/progress-photos';

class ProgressPhotosService {
  /** List the user's photos, newest first (metadata only). */
  async list(): Promise<ProgressPhoto[]> {
    return apiClient.get<ProgressPhoto[]>(BASE);
  }

  /** Upload a picked/captured image. `img` comes from imagePickerService. */
  async upload(img: { uri: string; type?: string }, meta?: UploadMeta): Promise<ProgressPhoto> {
    const formData = new FormData();
    formData.append('file', {
      uri: img.uri,
      type: img.type || 'image/jpeg',
      name: 'progress.jpg',
    } as any);
    if (meta?.notes) formData.append('notes', meta.notes);
    if (meta?.bodyweight != null) formData.append('bodyweight', String(meta.bodyweight));
    if (meta?.bodyweight_unit) formData.append('bodyweight_unit', meta.bodyweight_unit);
    if (meta?.taken_at) formData.append('taken_at', meta.taken_at);
    return apiClient.upload<ProgressPhoto>(BASE, formData);
  }

  /** Run the vision model over a photo and persist its critique. Can take 10-60s. */
  async critique(id: string): Promise<CritiqueResult> {
    return apiClient.post<CritiqueResult>(`${BASE}/${id}/critique`, undefined, {
      timeout: 180000,
    });
  }

  async remove(id: string): Promise<void> {
    await apiClient.delete(`${BASE}/${id}`);
  }

  /** Auth-protected image URL. Load into <Image> with an Authorization header. */
  fileUrl(id: string, variant: 'full' | 'thumb' = 'thumb'): string {
    return `${apiClient.baseURL}${BASE}/${id}/file?variant=${variant}`;
  }
}

export const progressPhotosService = new ProgressPhotosService();
export default progressPhotosService;

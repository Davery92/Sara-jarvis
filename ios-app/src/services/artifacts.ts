/**
 * Artifacts service — the Studio's data layer.
 *
 * Lists everything Sara has built and downloads generated files (Word/PDF)
 * to the share sheet. Auth is the app's Bearer token; the download endpoint
 * streams bytes so we hand the URL + Authorization header to
 * File.downloadFileAsync and then share the local copy.
 */
import { Linking } from 'react-native';
import { apiClient } from './api';

// expo-file-system / expo-sharing are native modules. On an app binary built
// before they were added they won't exist, so we lazy-load them and fall back
// to opening the download URL in the browser. This keeps the feature working
// before a native rebuild and upgrades to the share sheet after one.
function loadNativeFileModules():
  | { File: any; Paths: any; Sharing: any }
  | null {
  try {
    const fs = require('expo-file-system');
    const Sharing = require('expo-sharing');
    if (!fs?.File || !fs?.Paths || !Sharing?.shareAsync) return null;
    return { File: fs.File, Paths: fs.Paths, Sharing };
  } catch {
    return null;
  }
}

export interface Artifact {
  id: string;
  user_id: string;
  artifact_type: string;
  title: string;
  content: Record<string, any>;
  metadata: Record<string, any> | null;
  conversation_id: string | null;
  episode_id: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

class ArtifactsService {
  async list(params?: { artifact_type?: string; limit?: number }): Promise<Artifact[]> {
    const qs = new URLSearchParams();
    if (params?.artifact_type) qs.append('artifact_type', params.artifact_type);
    qs.append('limit', String(params?.limit ?? 100));
    return apiClient.get<Artifact[]>(`/api/artifacts?${qs.toString()}`);
  }

  async get(artifactId: string): Promise<Artifact> {
    return apiClient.get<Artifact>(`/api/artifacts/${artifactId}`);
  }

  /**
   * Download a file artifact and open the iOS share sheet. If the native
   * file/sharing modules aren't in this build yet, falls back to opening the
   * authenticated download URL in the browser. Returns the shared uri.
   */
  async downloadAndShare(artifact: Pick<Artifact, 'id' | 'content'>): Promise<string> {
    const filename = artifact.content?.filename || `${artifact.id}`;
    const mime = artifact.content?.mime || 'application/octet-stream';
    const token = await apiClient.getToken();
    const baseUrl = `${apiClient.baseURL}/api/artifacts/${artifact.id}/download`;

    const native = loadNativeFileModules();
    if (native) {
      const { File, Paths, Sharing } = native;
      const destination = new File(Paths.cache, filename);
      try {
        if (destination.exists) destination.delete();
      } catch {
        // best-effort cleanup of a stale copy
      }
      const saved = await File.downloadFileAsync(baseUrl, destination, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(saved.uri, {
          mimeType: mime,
          dialogTitle: filename,
          UTI: mime === 'application/pdf' ? 'com.adobe.pdf' : undefined,
        });
      }
      return saved.uri;
    }

    // Fallback (no native modules): open the download URL with the token as a
    // query param so the browser can fetch it without an Authorization header.
    const url = token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
    await Linking.openURL(url);
    return url;
  }
}

export const artifactsService = new ArtifactsService();

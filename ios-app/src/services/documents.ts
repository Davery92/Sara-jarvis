import apiClient from './api';

export interface Document {
  id: string;  // Backend uses UUID strings
  filename: string;
  original_filename: string;
  title: string;
  file_size: number;
  mime_type: string;
  content_text: string;
  is_processed: string;  // "true", "false", or "error"
  created_at: string;
  updated_at: string;
}

export interface DocumentSearchParams {
  query?: string;
  category?: string;
  tags?: string[];
  file_type?: string;
}

export interface UploadDocumentParams {
  file: File | Blob;
  filename: string;
  category?: string;
  tags?: string[];
}

class DocumentsService {
  /**
   * Get all documents
   */
  async getAllDocuments(): Promise<Document[]> {
    return await apiClient.get<Document[]>('/documents');
  }

  /**
   * Get a single document by ID
   */
  async getDocument(documentId: string): Promise<Document> {
    return await apiClient.get<Document>(`/documents/${documentId}`);
  }

  /**
   * Upload a new document
   */
  async uploadDocument(params: UploadDocumentParams): Promise<Document> {
    const formData = new FormData();

    // React Native FormData requires specific format
    formData.append('file', {
      uri: (params.file as any).uri,
      type: (params.file as any).type || 'application/octet-stream',
      name: (params.file as any).name || 'upload',
    } as any);

    console.log('[Documents] Uploading file:', (params.file as any).name, 'type:', (params.file as any).type);

    // Note: Backend endpoint is POST /documents, not /documents/upload
    const token = await apiClient.getToken();
    const response = await fetch(`${apiClient.baseURL}/documents`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'multipart/form-data',
      },
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('[Documents] Upload error response:', errorText);
      throw new Error(`Upload failed: ${response.status}`);
    }

    const result = await response.json();
    console.log('[Documents] Upload successful:', result.id);
    return result;
  }

  /**
   * Delete a document
   */
  async deleteDocument(documentId: string): Promise<void> {
    await apiClient.delete(`/documents/${documentId}`);
  }

  /**
   * Search documents
   */
  async searchDocuments(params: DocumentSearchParams): Promise<Document[]> {
    const queryParams = new URLSearchParams();
    if (params.query) queryParams.append('q', params.query);
    if (params.category) queryParams.append('category', params.category);
    if (params.file_type) queryParams.append('file_type', params.file_type);
    if (params.tags && params.tags.length > 0) {
      queryParams.append('tags', params.tags.join(','));
    }
    return await apiClient.get<Document[]>(`/documents/search?${queryParams}`);
  }

  /**
   * Get document download URL
   */
  getDocumentUrl(document: Document): string {
    return `${apiClient.baseURL}/documents/${document.id}/download`;
  }

  /**
   * Get document categories
   */
  async getCategories(): Promise<string[]> {
    return await apiClient.get<string[]>('/documents/categories');
  }

  /**
   * Update document metadata
   */
  async updateDocument(
    documentId: string,
    updates: { title?: string }
  ): Promise<Document> {
    return await apiClient.put<Document>(`/documents/${documentId}`, updates);
  }

  /**
   * Format file size for display
   */
  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  }

  /**
   * Get file type icon
   */
  getFileTypeIcon(fileType: string): string {
    if (fileType.includes('pdf')) return '📄';
    if (fileType.includes('image')) return '🖼️';
    if (fileType.includes('video')) return '🎥';
    if (fileType.includes('audio')) return '🎵';
    if (fileType.includes('text')) return '📝';
    if (fileType.includes('spreadsheet') || fileType.includes('excel')) return '📊';
    if (fileType.includes('presentation') || fileType.includes('powerpoint')) return '📈';
    if (fileType.includes('zip') || fileType.includes('archive')) return '📦';
    return '📎';
  }
}

export const documentsService = new DocumentsService();
export default documentsService;

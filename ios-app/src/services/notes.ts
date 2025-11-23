import apiClient from './api';
import { Note, Folder } from '../types/api';

export interface CreateNoteParams {
  title: string;
  content: string;
  folder_id?: number;
}

export interface UpdateNoteParams {
  title?: string;
  content?: string;
  folder_id?: number;
}

export interface SearchNotesParams {
  query: string;
  folder_id?: number;
}

class NotesService {
  /**
   * Get all notes
   */
  async getAllNotes(): Promise<Note[]> {
    return await apiClient.get<Note[]>('/notes');
  }

  /**
   * Get notes in a specific folder
   */
  async getNotesByFolder(folderId: number): Promise<Note[]> {
    return await apiClient.get<Note[]>(`/notes?folder_id=${folderId}`);
  }

  /**
   * Get root-level notes only (notes not in any folder)
   */
  async getRootNotes(): Promise<Note[]> {
    return await apiClient.get<Note[]>('/notes?folder_id=null');
  }

  /**
   * Get a single note by ID
   */
  async getNote(noteId: number): Promise<Note> {
    return await apiClient.get<Note>(`/notes/${noteId}`);
  }

  /**
   * Create a new note
   */
  async createNote(params: CreateNoteParams): Promise<Note> {
    return await apiClient.post<Note>('/notes', params);
  }

  /**
   * Update an existing note
   */
  async updateNote(noteId: number, params: UpdateNoteParams): Promise<Note> {
    return await apiClient.put<Note>(`/notes/${noteId}`, params);
  }

  /**
   * Delete a note
   */
  async deleteNote(noteId: number): Promise<void> {
    await apiClient.delete(`/notes/${noteId}`);
  }

  /**
   * Search notes
   */
  async searchNotes(params: SearchNotesParams): Promise<Note[]> {
    const queryParams = new URLSearchParams();
    queryParams.append('q', params.query);
    if (params.folder_id) {
      queryParams.append('folder_id', params.folder_id.toString());
    }
    return await apiClient.get<Note[]>(`/notes/search?${queryParams}`);
  }

  /**
   * Get all folders
   */
  async getAllFolders(): Promise<Folder[]> {
    return await apiClient.get<Folder[]>('/folders');
  }

  /**
   * Create a new folder
   */
  async createFolder(name: string, parentId?: number): Promise<Folder> {
    return await apiClient.post<Folder>('/folders', {
      name,
      parent_id: parentId,
    });
  }

  /**
   * Delete a folder
   */
  async deleteFolder(folderId: number): Promise<void> {
    await apiClient.delete(`/folders/${folderId}`);
  }

  /**
   * Get backlinks for a note
   */
  async getBacklinks(noteId: number): Promise<Note[]> {
    return await apiClient.get<Note[]>(`/notes/${noteId}/backlinks`);
  }
}

export const notesService = new NotesService();
export default notesService;

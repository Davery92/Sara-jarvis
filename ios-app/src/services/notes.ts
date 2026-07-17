import apiClient from './api';
import { Note, Folder } from '../types/api';

export interface CreateNoteParams {
  title: string;
  content: string;
  folder_id?: string | number;
}

export interface UpdateNoteParams {
  title?: string;
  content?: string;
  folder_id?: string | number;
}

export interface SearchNotesParams {
  query: string;
  folder_id?: string | number;
}

type DailyReportLookupParams = {
  title?: string | null;
  topic?: string | null;
};

const DAILY_REPORT_PREFIX = "Sara's Daily Report";

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
  async getNotesByFolder(folderId: string | number): Promise<Note[]> {
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
  async getNote(noteId: string | number): Promise<Note> {
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
  async updateNote(noteId: string | number, params: UpdateNoteParams): Promise<Note> {
    return await apiClient.put<Note>(`/notes/${noteId}`, params);
  }

  /**
   * Delete a note
   */
  async deleteNote(noteId: string | number): Promise<void> {
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

  async findBestMatchingNoteByTitle(title: string): Promise<Note | null> {
    const normalizedTitle = title.trim().toLowerCase();
    if (!normalizedTitle) return null;

    const results = await this.searchNotes({ query: title });
    return (
      results.find((note) => note.title?.trim().toLowerCase() === normalizedTitle) ||
      results.find((note) => note.title?.trim().toLowerCase().startsWith(normalizedTitle)) ||
      results[0] ||
      null
    );
  }

  async findDailyReportNote(params: DailyReportLookupParams = {}): Promise<Note | null> {
    const topicDate = params.topic?.startsWith('daily_report:')
      ? params.topic.slice('daily_report:'.length).trim()
      : '';
    const titleDateMatch = params.title?.match(/\b\d{4}-\d{2}-\d{2}\b/);
    const reportDate = topicDate || titleDateMatch?.[0] || '';

    if (reportDate) {
      const exactTitle = `${DAILY_REPORT_PREFIX} — ${reportDate}`;
      const exactMatch = await this.findBestMatchingNoteByTitle(exactTitle);
      if (exactMatch?.title?.trim().toLowerCase() === exactTitle.toLowerCase()) {
        return exactMatch;
      }
    }

    const fallbackResults = await this.searchNotes({ query: DAILY_REPORT_PREFIX });
    return (
      fallbackResults.find((note) => note.title?.trim().startsWith(DAILY_REPORT_PREFIX)) ||
      fallbackResults[0] ||
      null
    );
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
  async createFolder(name: string, parentId?: string | number): Promise<Folder> {
    return await apiClient.post<Folder>('/folders', {
      name,
      parent_id: parentId,
    });
  }

  /**
   * Delete a folder
   */
  async deleteFolder(folderId: string | number): Promise<void> {
    await apiClient.delete(`/folders/${folderId}`);
  }

  /**
   * Get backlinks for a note
   */
  async getBacklinks(noteId: string | number): Promise<Note[]> {
    return await apiClient.get<Note[]>(`/notes/${noteId}/backlinks`);
  }
}

export const notesService = new NotesService();
export default notesService;

/**
 * Notes Store - Zustand
 *
 * Manages notes and folders state:
 * - Current note being edited
 * - Folder tree structure
 * - Note connections (knowledge graph)
 * - Search and filtering
 */

import { create } from 'zustand';

export interface Note {
  id: string;
  title: string;
  content: string;
  folder_id?: string | null;
  tags: string[];
  starred: boolean;
  created_at: string;
  updated_at: string;
}

export interface Folder {
  id: string;
  name: string;
  parent_id?: string;
  children?: Folder[];
}

export interface NoteConnection {
  id: string;
  source_note_id: string;
  target_note_id: string;
  connection_type: 'reference' | 'semantic' | 'temporal';
  strength: number;
  auto_generated: boolean;
}

interface NotesState {
  currentNote: Note | null;
  notes: Note[];
  folders: Folder[];
  connections: NoteConnection[];
  searchQuery: string;
  selectedFolderId: string | null;

  // Actions
  setCurrentNote: (note: Note | null) => void;
  updateCurrentNote: (updates: Partial<Note>) => void;
  setNotes: (notes: Note[]) => void;
  addNote: (note: Note) => void;
  updateNote: (id: string, updates: Partial<Note>) => void;
  deleteNote: (id: string) => void;
  setFolders: (folders: Folder[]) => void;
  setConnections: (connections: NoteConnection[]) => void;
  setSearchQuery: (query: string) => void;
  setSelectedFolder: (folderId: string | null) => void;

  // Computed
  getFilteredNotes: () => Note[];
  getNotesByFolder: (folderId: string | null) => Note[];
}

export const useNotesStore = create<NotesState>((set, get) => ({
  currentNote: null,
  notes: [],
  folders: [],
  connections: [],
  searchQuery: '',
  selectedFolderId: null,

  setCurrentNote: (note) => set({ currentNote: note }),

  updateCurrentNote: (updates) => set((state) => ({
    currentNote: state.currentNote
      ? { ...state.currentNote, ...updates }
      : null
  })),

  setNotes: (notes) => set({ notes }),

  addNote: (note) => set((state) => ({
    notes: [...state.notes, note]
  })),

  updateNote: (id, updates) => set((state) => ({
    notes: state.notes.map(note =>
      note.id === id ? { ...note, ...updates } : note
    ),
    currentNote: state.currentNote?.id === id
      ? { ...state.currentNote, ...updates }
      : state.currentNote
  })),

  deleteNote: (id) => set((state) => ({
    notes: state.notes.filter(note => note.id !== id),
    currentNote: state.currentNote?.id === id ? null : state.currentNote
  })),

  setFolders: (folders) => set({ folders }),

  setConnections: (connections) => set({ connections }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setSelectedFolder: (folderId) => set({ selectedFolderId: folderId }),

  getFilteredNotes: () => {
    const { notes, searchQuery, selectedFolderId } = get();

    let filtered = notes;

    // Filter by folder
    if (selectedFolderId !== null) {
      filtered = filtered.filter(note => note.folder_id === selectedFolderId);
    }

    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(note =>
        note.title.toLowerCase().includes(query) ||
        note.content.toLowerCase().includes(query)
      );
    }

    return filtered;
  },

  getNotesByFolder: (folderId) => {
    const { notes } = get();
    return notes.filter(note => note.folder_id === folderId);
  },
}));

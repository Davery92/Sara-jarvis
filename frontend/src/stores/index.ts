/**
 * Zustand Stores Export
 *
 * Central export point for all application stores
 */

export { useAuthStore } from './authStore';
export { useChatStore } from './chatStore';
export { useNotesStore } from './notesStore';
export { useHabitsStore } from './habitsStore';

// Re-export types
export type { Message } from './chatStore';
export type { Note, Folder, NoteConnection } from './notesStore';
export type { Habit, HabitInstance, HabitStreak } from './habitsStore';

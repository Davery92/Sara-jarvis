/**
 * useNoteSync Hook
 *
 * Manages auto-saving of note content from the canvas back to the notes system.
 * Uses debounced saves (1 second) matching the Notes.tsx pattern.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../../../config'

interface UseNoteSyncOptions {
  noteId: string
  initialContent: string
  initialTitle: string
  enabled?: boolean
  debounceMs?: number
}

interface UseNoteSyncReturn {
  content: string
  title: string
  setContent: (content: string) => void
  setTitle: (title: string) => void
  isDirty: boolean
  isSaving: boolean
  lastSaved: Date | null
  error: string | null
  save: () => Promise<void>
}

export function useNoteSync({
  noteId,
  initialContent,
  initialTitle,
  enabled = true,
  debounceMs = 1000
}: UseNoteSyncOptions): UseNoteSyncReturn {
  const [content, setContentState] = useState(initialContent)
  const [title, setTitleState] = useState(initialTitle)
  const [isDirty, setIsDirty] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [lastSaved, setLastSaved] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingSaveRef = useRef<{ content: string; title: string } | null>(null)

  // Reset state when noteId changes
  useEffect(() => {
    setContentState(initialContent)
    setTitleState(initialTitle)
    setIsDirty(false)
    setError(null)
    pendingSaveRef.current = null

    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
      saveTimeoutRef.current = null
    }
  }, [noteId, initialContent, initialTitle])

  // Actual save function
  const performSave = useCallback(async (saveContent: string, saveTitle: string) => {
    if (!noteId || !enabled) return

    setIsSaving(true)
    setError(null)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: saveTitle,
          content: saveContent
        })
      })

      if (!response.ok) {
        throw new Error(`Save failed: ${response.status}`)
      }

      setIsDirty(false)
      setLastSaved(new Date())
      pendingSaveRef.current = null
    } catch (e: any) {
      setError(e.message || 'Failed to save note')
      console.error('Note save failed:', e)
    } finally {
      setIsSaving(false)
    }
  }, [noteId, enabled])

  // Debounced save trigger
  const scheduleSave = useCallback((newContent: string, newTitle: string) => {
    if (!enabled) return

    pendingSaveRef.current = { content: newContent, title: newTitle }

    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
    }

    saveTimeoutRef.current = setTimeout(() => {
      if (pendingSaveRef.current) {
        performSave(pendingSaveRef.current.content, pendingSaveRef.current.title)
      }
    }, debounceMs)
  }, [enabled, debounceMs, performSave])

  // Content setter with auto-save
  const setContent = useCallback((newContent: string) => {
    setContentState(newContent)
    setIsDirty(true)
    scheduleSave(newContent, title)
  }, [title, scheduleSave])

  // Title setter with auto-save
  const setTitle = useCallback((newTitle: string) => {
    setTitleState(newTitle)
    setIsDirty(true)
    scheduleSave(content, newTitle)
  }, [content, scheduleSave])

  // Manual save (immediate)
  const save = useCallback(async () => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
      saveTimeoutRef.current = null
    }
    await performSave(content, title)
  }, [content, title, performSave])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
      // Save any pending changes before unmount
      if (pendingSaveRef.current && enabled && noteId) {
        // Fire and forget - component is unmounting
        fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(pendingSaveRef.current)
        }).catch(console.error)
      }
    }
  }, [noteId, enabled])

  return {
    content,
    title,
    setContent,
    setTitle,
    isDirty,
    isSaving,
    lastSaved,
    error,
    save
  }
}

export default useNoteSync

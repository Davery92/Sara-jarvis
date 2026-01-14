import { useQuery } from '@tanstack/react-query'
import { notesApi } from '../services/api'
import type { Note } from '../types'

export function useNotes() {
  return useQuery<Note[]>({
    queryKey: ['notes'],
    queryFn: notesApi.list,
    staleTime: 1000 * 60 * 5, // 5 minutes
  })
}

export function useNote(id: string | null) {
  return useQuery<Note>({
    queryKey: ['note', id],
    queryFn: () => notesApi.get(id!),
    enabled: !!id,
    staleTime: 1000 * 60 * 5,
  })
}

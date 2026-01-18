import { useQuery } from '@tanstack/react-query'
import { mapsApi } from '../services/api'
import type { MapSummary, MapResponse } from '../types'

export function useMaps() {
  return useQuery<MapSummary[]>({
    queryKey: ['maps'],
    queryFn: mapsApi.list,
    staleTime: 1000 * 60 * 5, // 5 minutes
  })
}

export function useMap(id: string | null) {
  return useQuery<MapResponse>({
    queryKey: ['map', id],
    queryFn: () => mapsApi.get(id!),
    enabled: !!id,
    staleTime: 1000 * 60 * 5,
  })
}

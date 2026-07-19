/**
 * useSurface — holds the active surface and posts interaction events.
 *
 * State updates optimistically (the UI feels instant) and reconciles with the
 * server's authoritative state on each event response.
 */
import { useCallback, useEffect, useState } from 'react'
import { APP_CONFIG } from '../../config'
import { SurfaceModel, SurfaceEventPayload, SurfaceState } from './types'

export function useSurface(initial: SurfaceModel | null) {
  const [surface, setSurface] = useState<SurfaceModel | null>(initial)

  useEffect(() => {
    setSurface(initial)
  }, [initial?.id, initial?.version])

  // While a surface shows a progress bar it's usually a workspace job running in
  // Celery (which can't push SSE) — poll until it swaps to its file_list/result.
  useEffect(() => {
    const hasProgress = surface?.spec?.components?.some((c: any) => c.type === 'progress')
    if (!surface || surface.status !== 'active' || !hasProgress) return
    const id = surface.id
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`${APP_CONFIG.apiUrl}/api/surfaces/${id}`, {
          credentials: 'include',
        })
        if (res.ok) {
          const fresh = (await res.json()) as SurfaceModel
          setSurface((prev) => (prev && prev.id === id ? fresh : prev))
        }
      } catch {
        // transient — keep polling
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [surface?.id, surface?.version, surface?.status])

  const patchLocalState = useCallback((mutate: (s: SurfaceState) => void) => {
    setSurface((prev) => {
      if (!prev) return prev
      const next = { ...prev, state: JSON.parse(JSON.stringify(prev.state || {})) }
      mutate(next.state)
      return next
    })
  }, [])

  const postEvent = useCallback(
    async (payload: SurfaceEventPayload) => {
      if (!surface) return
      // Optimistic apply
      patchLocalState((state) => {
        const node = state[payload.component_id] || (state[payload.component_id] = {})
        const v = payload.value || {}
        if (payload.event === 'check') {
          node.checked = node.checked || {}
          node.checked[String(v.item_id)] = !!v.checked
        } else if (payload.event === 'step') {
          node.done = node.done || {}
          node.done[String(v.step_id)] = !!v.done
        } else if (payload.event === 'submit') {
          node.values = v.values ?? v
        } else if (payload.event === 'click') {
          node.clicked = v.button_id
        } else if (payload.event === 'set') {
          Object.assign(node, v)
        }
      })

      try {
        const res = await fetch(`${APP_CONFIG.apiUrl}/api/surfaces/${surface.id}/events`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload),
        })
        if (res.ok) {
          const data = await res.json()
          if (data.state) {
            setSurface((prev) => (prev ? { ...prev, state: data.state } : prev))
          }
        }
      } catch (e) {
        console.warn('Failed to post surface event:', e)
      }
    },
    [surface, patchLocalState],
  )

  return { surface, setSurface, postEvent }
}

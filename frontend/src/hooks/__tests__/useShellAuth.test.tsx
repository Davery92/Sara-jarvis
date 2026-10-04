/**
 * The session has to reach `authStore`, because that is where the Fitness
 * Coach surface reads the athlete id from.
 *
 * This is the test that was missing on 2026-10-04. `useShellAuth` is the
 * app's real auth: it confirms the session against /auth/me and held the
 * user in local React state only. Every Coach hook, though, reads
 * `useAuthStore(s => s.user?.id)` and gates its query on it
 * (`enabled: Boolean(athleteId)`). Nothing wrote to that store, so the id
 * was permanently null and every Coach query permanently disabled —
 * Overview rendered its read-failure branch, Today never finished loading,
 * and the Science Library showed an empty review queue above 50 stored
 * papers, which is why there was no way to accept one.
 *
 * Every Coach component test mocks `authStore` and hands the component an
 * id, so all 233 of them passed against a surface no signed-in user could
 * use. A mock of the thing that was broken cannot report it; this exercises
 * the real store.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useShellAuth } from '../useShellAuth'
import { useAuthStore } from '../../stores/authStore'

const USER = { id: 'athlete-77', email: 'a@example.invalid' }

function options() {
  return {
    locationPathname: '/dashboard',
    onSessionStart: vi.fn(),
    onSessionEnd: vi.fn(),
  }
}

beforeEach(() => {
  useAuthStore.getState().setUser(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
  useAuthStore.getState().setUser(null)
})

describe('useShellAuth and the athlete id', () => {
  it('puts the confirmed session in authStore, where the Coach reads it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => USER,
    })))

    const { result } = renderHook(() => useShellAuth(options()))

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))
    // The claim that matters: not the hook's own state, the STORE's.
    expect(useAuthStore.getState().user?.id).toBe(USER.id)
  })

  it('leaves the store empty when the session is not confirmed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      json: async () => ({ detail: 'nope' }),
    })))

    const { result } = renderHook(() => useShellAuth(options()))

    await waitFor(() => expect(result.current.isAuthenticated).toBe(false))
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('clears the store on logout, so the next session inherits no id', async () => {
    // The fake session has to actually end, because logging out changes the
    // route and that re-runs checkAuth. A stub that answers /auth/me `ok`
    // forever re-authenticates immediately and the store looks un-cleared.
    let signedIn = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).endsWith('/auth/logout')) {
        signedIn = false
        return { ok: true, json: async () => ({}) }
      }
      return signedIn
        ? { ok: true, json: async () => USER }
        : { ok: false, json: async () => ({ detail: 'no session' }) }
    }))

    const { result } = renderHook(() => useShellAuth(options()))
    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe(USER.id))

    await act(async () => { await result.current.logout() })

    expect(useAuthStore.getState().user).toBeNull()
  })

  it('does not persist an identity across loads', () => {
    // The cookie is the session. A `user` surviving in localStorage is a
    // second source of truth that can disagree with it, and a stale id
    // would namespace the query cache under the wrong athlete.
    useAuthStore.getState().setUser(USER)
    const persisted = window.localStorage.getItem('auth-storage')
    expect(persisted === null || !persisted.includes(USER.id)).toBe(true)
  })
})

import { create } from 'zustand'
import { authApi, getToken } from '../services/api'
import type { User } from '../types'

interface AuthState {
  user: User | null
  isLoading: boolean
  error: string | null

  // Actions
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  error: null,

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null })
    try {
      const response = await authApi.login(email, password)
      set({
        user: {
          id: response.id,
          email: response.email,
          created_at: response.created_at,
        },
        isLoading: false,
      })
    } catch (err: any) {
      set({
        error: err.response?.data?.detail || 'Login failed',
        isLoading: false,
      })
      throw err
    }
  },

  logout: async () => {
    await authApi.logout()
    set({ user: null })
  },

  checkAuth: async () => {
    // Try to authenticate - either via token or cookies from main webapp
    try {
      const user = await authApi.me()
      set({ user, isLoading: false })
    } catch {
      set({ user: null, isLoading: false })
    }
  },

  clearError: () => set({ error: null }),
}))

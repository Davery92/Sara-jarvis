/**
 * Auth Store - Zustand
 *
 * Manages authentication state:
 * - Current user
 * - Login/logout
 * - Token management
 * - Session persistence
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  full_name?: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  // Actions
  setUser: (user: User | null) => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,

      setUser: (user) => set({
        user,
        isAuthenticated: !!user
      }),

      login: async (email: string, password: string) => {
        set({ isLoading: true });

        try {
          const response = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email, password }),
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
          }

          const data = await response.json();
          set({
            user: data,
            isAuthenticated: true,
            isLoading: false
          });
        } catch (error) {
          set({ isLoading: false });
          throw error;
        }
      },

      logout: async () => {
        try {
          await fetch('/auth/logout', {
            method: 'POST',
            credentials: 'include',
          });
        } catch (error) {
          console.error('Logout error:', error);
        } finally {
          set({
            user: null,
            isAuthenticated: false
          });
        }
      },

      checkAuth: async () => {
        set({ isLoading: true });

        try {
          const response = await fetch('/auth/me', {
            credentials: 'include',
          });

          if (response.ok) {
            const user = await response.json();
            set({
              user,
              isAuthenticated: true,
              isLoading: false
            });
          } else {
            set({
              user: null,
              isAuthenticated: false,
              isLoading: false
            });
          }
        } catch (error) {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false
          });
        }
      },
    }),
    {
      name: 'auth-storage',
      // Nothing about the identity is persisted. The cookie IS the session,
      // so a `user` kept in localStorage is a second source of truth that
      // can disagree with it — a stale id would namespace the react-query
      // cache under the wrong athlete while the server, which scopes by
      // cookie, served the right one. The store is populated only by a
      // server-confirmed session (`useShellAuth` -> /auth/me), and starts
      // empty on every load.
      partialize: () => ({}),
    }
  )
);

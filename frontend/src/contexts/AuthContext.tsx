import React, { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import { APP_CONFIG } from '../config';

interface AuthState {
  isAuthenticated: boolean;
  user: any;
  loading: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<boolean>;
  signup: (email: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    user: null,
    loading: true,
  });

  const checkAuth = useCallback(async () => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/auth/me`, { credentials: 'include' });
      if (resp.ok) {
        const user = await resp.json();
        setState({ isAuthenticated: true, user, loading: false });
      } else {
        setState({ isAuthenticated: false, user: null, loading: false });
      }
    } catch {
      setState({ isAuthenticated: false, user: null, loading: false });
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = useCallback(async (email: string, password: string): Promise<boolean> => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      if (resp.ok) {
        await checkAuth();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [checkAuth]);

  const signup = useCallback(async (email: string, password: string): Promise<boolean> => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      if (resp.ok) {
        await checkAuth();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [checkAuth]);

  const logout = useCallback(async () => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/auth/logout`, { method: 'POST', credentials: 'include' });
    } catch {
      // ignore
    }
    setState({ isAuthenticated: false, user: null, loading: false });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, signup, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

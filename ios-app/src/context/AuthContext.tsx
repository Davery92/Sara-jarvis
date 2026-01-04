import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { authService, LoginCredentials, SignupData } from '../services/auth';
import { apiClient } from '../services/api';
import { User } from '../types/api';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (credentials: LoginCredentials) => Promise<void>;
  signup: (data: SignupData) => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Handle auth errors (401) from API client - clear user state to trigger login
  const handleAuthError = useCallback(() => {
    console.log('[AuthContext] Auth error received - clearing user state');
    setUser(null);
  }, []);

  useEffect(() => {
    // Register auth error handler with API client
    apiClient.setOnAuthError(handleAuthError);
    checkAuth();
  }, [handleAuthError]);

  const checkAuth = async () => {
    try {
      const isAuth = await authService.isAuthenticated();
      if (isAuth) {
        const currentUser = await authService.getCurrentUser();
        setUser(currentUser);
      }
    } catch (error) {
      console.error('Auth check failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const login = async (credentials: LoginCredentials) => {
    try {
      const response = await authService.login(credentials);
      console.log('[AuthContext] Login response:', response);
      // Response IS the user data with access_token
      const user: User = {
        id: response.id,
        email: response.email,
        username: response.email,
        created_at: response.created_at,
      };
      console.log('[AuthContext] Setting user:', user);
      setUser(user);
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  };

  const signup = async (data: SignupData) => {
    const response = await authService.signup(data);
    console.log('[AuthContext] Signup response:', response);
    // Response IS the user data with access_token
    const user: User = {
      id: response.id,
      email: response.email,
      username: response.email,
      created_at: response.created_at,
    };
    setUser(user);
  };

  const logout = async () => {
    await authService.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        signup,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

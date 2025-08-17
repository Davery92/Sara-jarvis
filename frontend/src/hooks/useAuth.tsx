import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, User, AuthResponse } from '../api/client'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
  updateProfile: (data: Partial<User>) => Promise<void>
  error: string | null
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  // Query to get current user
  const {
    data: user,
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: ['auth', 'user'],
    queryFn: async () => {
      try {
        return await apiClient.getCurrentUser()
      } catch (err: any) {
        if (err.response?.status === 401) {
          // User is not authenticated
          return null
        }
        throw err
      }
    },
    retry: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      apiClient.login(email, password),
    onSuccess: (data: AuthResponse) => {
      setError(null)
      queryClient.setQueryData(['auth', 'user'], data.user)
      queryClient.invalidateQueries({ queryKey: ['auth'] })
    },
    onError: (err: any) => {
      setError(err.response?.data?.message || 'Login failed')
    },
  })

  // Register mutation
  const registerMutation = useMutation({
    mutationFn: ({ email, password, name }: { email: string; password: string; name: string }) =>
      apiClient.register(email, password, name),
    onSuccess: (data: AuthResponse) => {
      setError(null)
      queryClient.setQueryData(['auth', 'user'], data.user)
      queryClient.invalidateQueries({ queryKey: ['auth'] })
    },
    onError: (err: any) => {
      setError(err.response?.data?.message || 'Registration failed')
    },
  })

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: () => apiClient.logout(),
    onSuccess: () => {
      setError(null)
      queryClient.setQueryData(['auth', 'user'], null)
      queryClient.clear() // Clear all cached data
    },
    onError: (err: any) => {
      setError(err.response?.data?.message || 'Logout failed')
    },
  })

  // Update profile mutation
  const updateProfileMutation = useMutation({
    mutationFn: (data: Partial<User>) => apiClient.updateProfile(data),
    onSuccess: (updatedUser: User) => {
      setError(null)
      queryClient.setQueryData(['auth', 'user'], updatedUser)
    },
    onError: (err: any) => {
      setError(err.response?.data?.message || 'Profile update failed')
    },
  })

  // Clear error when queries change
  useEffect(() => {
    if (queryError) {
      setError((queryError as any).response?.data?.message || 'Authentication error')
    }
  }, [queryError])

  const login = async (email: string, password: string) => {
    setError(null)
    await loginMutation.mutateAsync({ email, password })
  }

  const register = async (email: string, password: string, name: string) => {
    setError(null)
    await registerMutation.mutateAsync({ email, password, name })
  }

  const logout = async () => {
    setError(null)
    await logoutMutation.mutateAsync()
  }

  const updateProfile = async (data: Partial<User>) => {
    setError(null)
    await updateProfileMutation.mutateAsync(data)
  }

  const value: AuthContextType = {
    user: user || null,
    isLoading: isLoading || loginMutation.isPending || registerMutation.isPending || logoutMutation.isPending,
    isAuthenticated: !!user,
    login,
    register,
    logout,
    updateProfile,
    error,
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

// Hook for protected routes
export function useRequireAuth() {
  const auth = useAuth()
  
  useEffect(() => {
    if (!auth.isLoading && !auth.isAuthenticated) {
      window.location.href = '/login'
    }
  }, [auth.isLoading, auth.isAuthenticated])

  return auth
}

export default useAuth
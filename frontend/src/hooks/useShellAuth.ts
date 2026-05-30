import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { APP_CONFIG } from '../config'
import type { AppView } from '../navigation/views'
import { viewForPath } from '../navigation/views'

interface UseShellAuthOptions {
  locationPathname: string
  onSessionStart: (nextView: AppView, options?: { resetChat: boolean }) => void
  onSessionEnd: () => void
}

export function useShellAuth({
  locationPathname,
  onSessionStart,
  onSessionEnd,
}: UseShellAuthOptions) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState<any>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLogin, setIsLogin] = useState(true)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  const checkAuth = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/auth/me`, {
        credentials: 'include',
      })
      if (!response.ok) return

      const userData = await response.json()
      setUser(userData)
      setIsAuthenticated(true)
      onSessionStart(
        locationPathname === '/login' ? 'dashboard' : viewForPath(locationPathname),
        { resetChat: false },
      )
    } catch {
      console.log('Not authenticated')
    }
  }, [locationPathname, onSessionStart])

  useEffect(() => {
    void checkAuth()
  }, [checkAuth])

  const handleAuth = useCallback(async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/signup'
      const response = await fetch(`${APP_CONFIG.apiUrl}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })

      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
        setIsAuthenticated(true)
        setMessage('')
        onSessionStart('dashboard', { resetChat: true })
      } else {
        const error = await response.json()
        setMessage(error.detail || 'Authentication failed')
      }
    } catch {
      setMessage('Connection error. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [email, isLogin, onSessionStart, password])

  const logout = useCallback(async () => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      })
    } catch (error) {
      console.error('Logout error:', error)
    }

    setIsAuthenticated(false)
    setUser(null)
    onSessionEnd()
  }, [onSessionEnd])

  return {
    isAuthenticated,
    user,
    email,
    setEmail,
    password,
    setPassword,
    isLogin,
    setIsLogin,
    message,
    setMessage,
    loading,
    handleAuth,
    logout,
  }
}

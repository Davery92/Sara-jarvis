import { useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { LogIn } from 'lucide-react'

export default function LoginScreen() {
  const { login, error, isLoading, clearError } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    try {
      await login(email, password)
    } catch {
      // Error is handled in store
    }
  }

  return (
    <div className="w-full h-full flex items-center justify-center bg-canvas-bg">
      <div className="w-full max-w-md p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Workbench Canvas</h1>
          <p className="text-canvas-muted">Sign in with your Sara account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-4 text-red-400 text-sm">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-300 mb-2">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full px-4 py-3 bg-canvas-surface border border-canvas-border rounded-lg
                         text-white placeholder-canvas-muted
                         focus:outline-none focus:ring-2 focus:ring-accent-blue focus:border-transparent
                         touch-target"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-4 py-3 bg-canvas-surface border border-canvas-border rounded-lg
                         text-white placeholder-canvas-muted
                         focus:outline-none focus:ring-2 focus:ring-accent-blue focus:border-transparent
                         touch-target"
              placeholder="Enter your password"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-4 bg-accent-blue hover:bg-blue-600 disabled:opacity-50
                       disabled:cursor-not-allowed rounded-lg text-white font-medium
                       flex items-center justify-center gap-2 transition-colors
                       touch-target"
          >
            <LogIn size={20} />
            {isLoading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="mt-8 text-center text-canvas-muted text-sm">
          Click anywhere to enter fullscreen mode
        </p>
      </div>
    </div>
  )
}

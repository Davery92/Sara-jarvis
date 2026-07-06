import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import App from './App'
import OverlayPage from './overlay/OverlayPage'
import 'katex/dist/katex.min.css'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Standalone, chrome-less overlay surface for Electron overlay windows
            (Desktop Jarvis Overhaul A2) — deliberately outside AuthProvider/
            QueryClientProvider so it loads fast and stays independent of the
            main app's shell/session state. */}
        <Route path="/overlay/:kind" element={<OverlayPage />} />
        <Route
          path="*"
          element={
            <QueryClientProvider client={queryClient}>
              <AuthProvider>
                <App />
              </AuthProvider>
            </QueryClientProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)

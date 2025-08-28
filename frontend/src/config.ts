// Dynamic API URL based on environment
const getApiUrl = () => {
  // If environment variable is set, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }
  
  // If we're on the production domain with HTTPS, use the API endpoint
  if (typeof window !== 'undefined' && window.location.host.includes('sara.avery.cloud')) {
    return 'https://sara.avery.cloud/api'
  }
  
  // Otherwise use local development backend
  return 'http://10.185.1.180:8000'
}

// Local preferences can override or complement env flags
const calmFromLocal = (() => {
  try { return localStorage.getItem('sprite.calmMode') === 'true' } catch { return false }
})()
const enhancedFromLocal = (() => {
  try { return localStorage.getItem('sprite.enhancedVisuals') === 'true' } catch { return false }
})()

export const APP_CONFIG = {
  assistantName: import.meta.env.VITE_ASSISTANT_NAME || 'Sara',
  domain: import.meta.env.VITE_DOMAIN || 'sara.avery.cloud',
  apiUrl: getApiUrl(),
  flags: {
    // Enable emitting spriteBus events alongside existing spriteRef controls
    spriteBus: (import.meta.env.VITE_SPRITE_BUS === 'true') || false,
    // Visual mode prefs
    enhancedVisuals: enhancedFromLocal || (import.meta.env.VITE_SPRITE_ENHANCED === 'true') || false,
    calmMode: calmFromLocal || false,
  },
  theme: {
    primary: '#6366f1',
    secondary: '#8b5cf6',
    accent: '#06b6d4',
    background: '#ffffff',
    surface: '#f8fafc',
    text: '#1e293b',
    textMuted: '#64748b'
  },
  ui: {
    title: 'Sara - Your Personal AI Hub',
    subtitle: 'Intelligent assistance, memory, and organization',
    chatPlaceholder: 'Ask Sara anything...',
    welcomeMessage: `Hi! I'm ${import.meta.env.VITE_ASSISTANT_NAME || 'Sara'}, your personal AI assistant. I can help you manage notes, reminders, calendar events, and answer questions using your personal knowledge base.`
  }
} as const

export type AppConfig = typeof APP_CONFIG

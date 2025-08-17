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

export const APP_CONFIG = {
  assistantName: import.meta.env.VITE_ASSISTANT_NAME || 'Sara',
  domain: import.meta.env.VITE_DOMAIN || 'sara.avery.cloud',
  apiUrl: getApiUrl(),
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
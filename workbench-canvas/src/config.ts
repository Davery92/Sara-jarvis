// Dynamic API URL based on environment
const getApiUrl = () => {
  // If environment variable is set, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }

  // Use current hostname with port 8000 for API
  if (typeof window !== 'undefined') {
    return `http://${window.location.hostname}:8000`
  }

  // Fallback for non-browser contexts
  return 'http://localhost:8000'
}

export const APP_CONFIG = {
  apiUrl: getApiUrl(),
  appName: 'Workbench Canvas',

  // Canvas defaults
  canvas: {
    minZoom: 0.25,
    maxZoom: 4,
    defaultZoom: 1,
    gridSize: 20,
  },

  // Window defaults
  window: {
    minWidth: 200,
    minHeight: 150,
    defaultWidth: 400,
    defaultHeight: 300,
  },

  // Touch-friendly sizing
  touch: {
    minTargetSize: 48,
    buttonSize: 64,
    resizeHandleSize: 24,
  },
} as const

export type AppConfig = typeof APP_CONFIG

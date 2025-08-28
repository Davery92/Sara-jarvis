// Simple local preferences utilities for UI-only settings

const CALM_MODE_KEY = 'sprite.calmMode'
const ENHANCED_VISUALS_KEY = 'sprite.enhancedVisuals'

export const getBoolPref = (key: string, fallback = false): boolean => {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return raw === 'true'
  } catch {
    return fallback
  }
}

export const setBoolPref = (key: string, value: boolean) => {
  try {
    localStorage.setItem(key, value ? 'true' : 'false')
  } catch {
    // ignore
  }
}

export const getCalmMode = () => getBoolPref(CALM_MODE_KEY, false)
export const setCalmMode = (v: boolean) => setBoolPref(CALM_MODE_KEY, v)

export const getEnhancedVisuals = () => getBoolPref(ENHANCED_VISUALS_KEY, false)
export const setEnhancedVisuals = (v: boolean) => setBoolPref(ENHANCED_VISUALS_KEY, v)


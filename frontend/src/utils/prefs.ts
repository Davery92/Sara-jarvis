// Simple local preferences utilities for UI-only settings

const CALM_MODE_KEY = 'sprite.calmMode'
const ENHANCED_VISUALS_KEY = 'sprite.enhancedVisuals'

// URL preference keys
const AI_PROVIDER_KEY = 'sara.aiProvider'
const AI_API_KEY_KEY = 'sara.aiApiKey'
const AI_BASE_URL_KEY = 'sara.aiBaseUrl'
const AI_MODEL_KEY = 'sara.aiModel'
const AI_NOTIFICATION_MODEL_KEY = 'sara.aiNotificationModel'
const EMBEDDING_BASE_URL_KEY = 'sara.embeddingBaseUrl'
const EMBEDDING_MODEL_KEY = 'sara.embeddingModel'
const EMBEDDING_DIMENSION_KEY = 'sara.embeddingDimension'

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

// URL preference getters and setters
export const getStringPref = (key: string, fallback = ''): string => {
  try {
    const raw = localStorage.getItem(key)
    return raw || fallback
  } catch {
    return fallback
  }
}

export const setStringPref = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

export const getNumberPref = (key: string, fallback = 0): number => {
  try {
    const raw = localStorage.getItem(key)
    return raw ? parseInt(raw, 10) : fallback
  } catch {
    return fallback
  }
}

export const setNumberPref = (key: string, value: number) => {
  try {
    localStorage.setItem(key, value.toString())
  } catch {
    // ignore
  }
}

// AI Provider and API Key preferences
export const getAIProvider = () => getStringPref(AI_PROVIDER_KEY, 'local')
export const setAIProvider = (v: string) => setStringPref(AI_PROVIDER_KEY, v)

export const getAIApiKey = () => getStringPref(AI_API_KEY_KEY, '')
export const setAIApiKey = (v: string) => setStringPref(AI_API_KEY_KEY, v)

// AI URL preferences
export const getAIBaseUrl = () => getStringPref(AI_BASE_URL_KEY, 'http://100.104.68.115:11434/v1')
export const setAIBaseUrl = (v: string) => setStringPref(AI_BASE_URL_KEY, v)

export const getAIModel = () => getStringPref(AI_MODEL_KEY, 'gpt-oss:20b')
export const setAIModel = (v: string) => setStringPref(AI_MODEL_KEY, v)

export const getAINotificationModel = () => getStringPref(AI_NOTIFICATION_MODEL_KEY, 'gpt-oss:20b')
export const setAINotificationModel = (v: string) => setStringPref(AI_NOTIFICATION_MODEL_KEY, v)

export const getEmbeddingBaseUrl = () => getStringPref(EMBEDDING_BASE_URL_KEY, 'http://100.104.68.115:11434')
export const setEmbeddingBaseUrl = (v: string) => setStringPref(EMBEDDING_BASE_URL_KEY, v)

export const getEmbeddingModel = () => getStringPref(EMBEDDING_MODEL_KEY, 'bge-m3')
export const setEmbeddingModel = (v: string) => setStringPref(EMBEDDING_MODEL_KEY, v)

export const getEmbeddingDimension = () => getNumberPref(EMBEDDING_DIMENSION_KEY, 1024)
export const setEmbeddingDimension = (v: number) => setNumberPref(EMBEDDING_DIMENSION_KEY, v)

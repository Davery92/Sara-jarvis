import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { APP_CONFIG } from '../../config'

type ControlTab =
  | 'pipeline'
  | 'wake-word'
  | 'speakers'
  | 'ambient'
  | 'models'
  | 'jobs'
  | 'logs'

interface PipelineServiceStatus {
  id: string
  name: string
  status: string
  version?: string | null
  latency_ms?: number | null
  last_reported_at?: string | null
}

interface PipelineStatus {
  generated_at?: string
  services: PipelineServiceStatus[]
  event_types: string[]
  event_stream?: {
    stream_key: string
    pubsub_channel: string
    maxlen: number
  }
}

interface VoiceConfig {
  wake_word?: {
    threshold?: number
    keyword?: string
  }
  vad?: {
    speech_threshold?: number
    silence_duration_ms?: number
  }
  ambient?: {
    sample_interval_seconds?: number
    auto_adjust_vad?: boolean
    auto_adjust_wake_threshold?: boolean
  }
}

interface ModelVersion {
  version: string
  status?: string
  created_at?: string
}

interface ModelFamily {
  active_version?: string
  versions?: ModelVersion[]
}

interface ModelRegistry {
  wake_word?: ModelFamily
  speakers?: ModelFamily
}

interface VoiceJob {
  job_id: string
  job_type: string
  status: string
  claimed_by?: string | null
  created_at?: string
  updated_at?: string
  notes?: string | null
  error?: string | null
  result?: Record<string, unknown> | null
}

interface VoiceEvent {
  stream_id?: string
  event_id?: string
  event_type: string
  source?: string
  trace_id?: string
  timestamp?: string
  payload?: Record<string, unknown>
}

interface DatasetSample {
  filename: string
  size_bytes: number
  created: string
}

interface DatasetRecordingStatus {
  status: string
  dataset_id?: string
  family?: string
  speaker_id?: string
  duration_seconds?: number
  progress?: number
  sample_count?: number
  message?: string
}

// Guided recording session (B3) — cycles through natural-speech variations
// instead of asking for 25 identical repetitions, so the resulting model
// generalizes across distance/volume/background conditions.
const WAKE_SESSION_TARGET = 25
const WAKE_PROMPT_VARIATIONS = [
  'Say it naturally, like you would to get her attention',
  'Say it from across the room',
  'Say it quietly, like you would at night',
  'Say it with music or the TV on in the background',
  'Say it while walking past, not facing the mic',
]

const WAKE_PHRASE_PRESETS: Array<{ label: string; phrase: string; datasetPrefix: string }> = [
  { label: 'Hey Sara', phrase: 'hey sara', datasetPrefix: 'hey_sara' },
  { label: 'Sara Stop', phrase: 'sara stop', datasetPrefix: 'sara_stop' },
]

const tabs: Array<{ id: ControlTab; label: string }> = [
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'wake-word', label: 'Wake Word Lab' },
  { id: 'speakers', label: 'Speaker Lab' },
  { id: 'ambient', label: 'Ambient Adaptation' },
  { id: 'models', label: 'Models' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'logs', label: 'Logs/Contracts' },
]

const statusClass = (status: string) => {
  const normalized = status.toLowerCase()
  if (normalized === 'healthy' || normalized === 'online' || normalized === 'active') {
    return 'text-green-400'
  }
  if (normalized === 'degraded' || normalized === 'queued' || normalized === 'running') {
    return 'text-yellow-400'
  }
  if (normalized === 'completed') {
    return 'text-blue-400'
  }
  if (normalized === 'failed' || normalized === 'error' || normalized === 'offline') {
    return 'text-red-400'
  }
  return 'text-gray-300'
}

const cardClass = 'rounded-lg border border-gray-700 bg-gray-800/70 p-3'

const SensoryControlPlane: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ControlTab>('pipeline')
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [config, setConfig] = useState<VoiceConfig | null>(null)
  const [models, setModels] = useState<ModelRegistry | null>(null)
  const [jobs, setJobs] = useState<VoiceJob[]>([])
  const [recentEvents, setRecentEvents] = useState<VoiceEvent[]>([])
  const [message, setMessage] = useState<string>('')
  const [busy, setBusy] = useState<boolean>(false)
  const [streamConnected, setStreamConnected] = useState<boolean>(false)

  const [wakePhrase, setWakePhrase] = useState<string>('hey sara')
  const [wakeDatasetId, setWakeDatasetId] = useState<string>('')
  const [speakerIds, setSpeakerIds] = useState<string>('david')
  const [speakerDatasetId, setSpeakerDatasetId] = useState<string>('')
  const [wakeThreshold, setWakeThreshold] = useState<number>(0.58)
  const [vadThreshold, setVadThreshold] = useState<number>(0.5)
  const [ambientInterval, setAmbientInterval] = useState<number>(120)
  const [wakeRecordDuration, setWakeRecordDuration] = useState<number>(5)
  const [speakerRecordDuration, setSpeakerRecordDuration] = useState<number>(8)
  const [speakerRecordId, setSpeakerRecordId] = useState<string>('david')
  const [wakeSamples, setWakeSamples] = useState<DatasetSample[]>([])
  const [wakeNegativeSamples, setWakeNegativeSamples] = useState<DatasetSample[]>([])
  const [wakePromptIndex, setWakePromptIndex] = useState<number>(0)
  const [speakerSamples, setSpeakerSamples] = useState<DatasetSample[]>([])
  const [datasetRecordingStatus, setDatasetRecordingStatus] = useState<DatasetRecordingStatus | null>(null)

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      ...init,
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `Request failed: ${response.status}`)
    }
    return response.json()
  }, [])

  const normalizeIdentifier = useCallback((value: string) => {
    return value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '')
  }, [])

  const formatBytes = useCallback((bytes: number) => {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  }, [])

  const loadDatasetRecordingStatus = useCallback(async () => {
    try {
      const state = await request('/api/sensory/datasets/recording-status')
      setDatasetRecordingStatus(state)
    } catch (error) {
      console.warn('Failed to load dataset recording status', error)
    }
  }, [request])

  const loadWakeSamples = useCallback(async (datasetIdRaw: string) => {
    const datasetId = normalizeIdentifier(datasetIdRaw)
    if (!datasetId) {
      setWakeSamples([])
      setWakeNegativeSamples([])
      return
    }
    try {
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/samples`)
      setWakeSamples(Array.isArray(data.samples) ? data.samples : [])
    } catch (error) {
      console.warn('Failed to load wake dataset samples', error)
      setWakeSamples([])
    }
    try {
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/samples?kind=negative`)
      setWakeNegativeSamples(Array.isArray(data.samples) ? data.samples : [])
    } catch (error) {
      console.warn('Failed to load wake negative samples', error)
      setWakeNegativeSamples([])
    }
  }, [normalizeIdentifier, request])

  const loadSpeakerSamples = useCallback(async (datasetIdRaw: string, speakerIdRaw: string) => {
    const datasetId = normalizeIdentifier(datasetIdRaw)
    const speakerId = normalizeIdentifier(speakerIdRaw)
    if (!datasetId || !speakerId) {
      setSpeakerSamples([])
      return
    }
    try {
      const data = await request(
        `/api/sensory/datasets/${encodeURIComponent(datasetId)}/speakers/${encodeURIComponent(speakerId)}/samples`,
      )
      setSpeakerSamples(Array.isArray(data.samples) ? data.samples : [])
    } catch (error) {
      console.warn('Failed to load speaker dataset samples', error)
      setSpeakerSamples([])
    }
  }, [normalizeIdentifier, request])

  const refreshDatasetViews = useCallback(async () => {
    await Promise.all([
      loadDatasetRecordingStatus(),
      loadWakeSamples(wakeDatasetId),
      loadSpeakerSamples(speakerDatasetId, speakerRecordId),
    ])
  }, [loadDatasetRecordingStatus, loadSpeakerSamples, loadWakeSamples, speakerDatasetId, speakerRecordId, wakeDatasetId])

  const load = useCallback(async () => {
    try {
      const [pipelineData, configData, modelData, jobsData, datasetStateData] = await Promise.all([
        request('/api/voice-control/pipeline/status'),
        request('/api/voice-control/config'),
        request('/api/voice-control/models'),
        request('/api/voice-control/jobs?limit=25'),
        request('/api/sensory/datasets/recording-status'),
      ])

      let eventsData: { events?: VoiceEvent[] } = {}
      try {
        eventsData = await request('/api/voice-control/events/recent?limit=40')
      } catch (eventsError) {
        console.warn('Failed to load voice events', eventsError)
      }

      setPipeline(pipelineData)
      setConfig(configData)
      setModels(modelData)
      setJobs(jobsData.jobs || [])
      setRecentEvents(eventsData.events || [])
      setDatasetRecordingStatus(datasetStateData || { status: 'idle' })

      if (configData?.wake_word?.keyword) setWakePhrase(configData.wake_word.keyword)
      if (typeof configData?.wake_word?.threshold === 'number') setWakeThreshold(configData.wake_word.threshold)
      if (typeof configData?.vad?.speech_threshold === 'number') setVadThreshold(configData.vad.speech_threshold)
      if (typeof configData?.ambient?.sample_interval_seconds === 'number') {
        setAmbientInterval(configData.ambient.sample_interval_seconds)
      }
    } catch (error) {
      console.error('Failed to load voice control plane', error)
      setMessage('Failed to load voice control plane data')
    }
  }, [request])

  useEffect(() => {
    load()
    const interval = setInterval(load, 12000)
    return () => clearInterval(interval)
  }, [load])

  useEffect(() => {
    const streamUrl = `${APP_CONFIG.apiUrl}/api/voice-control/events/stream`
    const eventSource = new EventSource(streamUrl, { withCredentials: true })

    eventSource.onopen = () => {
      setStreamConnected(true)
    }

    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as VoiceEvent
        setRecentEvents((prev) => [parsed, ...prev].slice(0, 120))
      } catch (error) {
        console.warn('Failed to parse streamed voice event', error)
      }
    }

    eventSource.onerror = () => {
      setStreamConnected(false)
    }

    return () => {
      eventSource.close()
      setStreamConnected(false)
    }
  }, [])

  useEffect(() => {
    loadWakeSamples(wakeDatasetId)
  }, [loadWakeSamples, wakeDatasetId])

  useEffect(() => {
    loadSpeakerSamples(speakerDatasetId, speakerRecordId)
  }, [loadSpeakerSamples, speakerDatasetId, speakerRecordId])

  useEffect(() => {
    const status = (datasetRecordingStatus?.status || '').toLowerCase()
    if (status !== 'recording' && status !== 'processing') {
      return undefined
    }
    const interval = setInterval(() => {
      refreshDatasetViews()
    }, 1500)
    return () => clearInterval(interval)
  }, [datasetRecordingStatus?.status, refreshDatasetViews])

  const queueWakeWordTraining = useCallback(async () => {
    setBusy(true)
    setMessage('')
    try {
      const data = await request('/api/voice-control/models/wake-word/train', {
        method: 'POST',
        body: JSON.stringify({
          target_phrase: wakePhrase.trim() || 'hey sara',
          dataset_id: wakeDatasetId.trim() || undefined,
          notes: 'Queued from Sensory Wake Word Lab',
        }),
      })
      setMessage(`Wake-word training queued: ${data.job?.job_id || 'unknown job'}`)
      await load()
    } catch (error) {
      console.error(error)
      setMessage('Failed to queue wake-word training')
    } finally {
      setBusy(false)
    }
  }, [load, request, wakeDatasetId, wakePhrase])

  const queueSpeakerTraining = useCallback(async () => {
    setBusy(true)
    setMessage('')
    try {
      const ids = speakerIds
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)

      const data = await request('/api/voice-control/models/speakers/train', {
        method: 'POST',
        body: JSON.stringify({
          speaker_ids: ids,
          dataset_id: speakerDatasetId.trim() || undefined,
          notes: 'Queued from Sensory Speaker Lab',
        }),
      })
      setMessage(`Speaker training queued: ${data.job?.job_id || 'unknown job'}`)
      await load()
    } catch (error) {
      console.error(error)
      setMessage('Failed to queue speaker training')
    } finally {
      setBusy(false)
    }
  }, [load, request, speakerDatasetId, speakerIds])

  const startWakeDatasetRecording = useCallback(async () => {
    const datasetId = normalizeIdentifier(wakeDatasetId)
    if (!datasetId) {
      setMessage('Wake dataset ID is required to record clips')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      setWakeDatasetId(datasetId)
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/start-recording`, {
        method: 'POST',
        body: JSON.stringify({
          duration_seconds: wakeRecordDuration,
          prompt: wakePhrase,
        }),
      })
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to start wake dataset recording'))
      }
      setMessage(`Wake clip recording started (${wakeRecordDuration}s)`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to start wake dataset recording')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, wakeDatasetId, wakePhrase, wakeRecordDuration])

  const startSpeakerDatasetRecording = useCallback(async () => {
    const datasetId = normalizeIdentifier(speakerDatasetId)
    const speakerId = normalizeIdentifier(speakerRecordId)
    if (!datasetId) {
      setMessage('Speaker dataset ID is required to record clips')
      return
    }
    if (!speakerId) {
      setMessage('Speaker ID is required to record clips')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      setSpeakerDatasetId(datasetId)
      setSpeakerRecordId(speakerId)
      const data = await request(
        `/api/sensory/datasets/${encodeURIComponent(datasetId)}/speakers/${encodeURIComponent(speakerId)}/start-recording`,
        {
          method: 'POST',
          body: JSON.stringify({
            duration_seconds: speakerRecordDuration,
            prompt: `speaker ${speakerId}`,
          }),
        },
      )
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to start speaker dataset recording'))
      }
      setMessage(`Speaker clip recording started for "${speakerId}" (${speakerRecordDuration}s)`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to start speaker dataset recording')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, speakerDatasetId, speakerRecordDuration, speakerRecordId])

  const clearWakeDatasetSamples = useCallback(async () => {
    const datasetId = normalizeIdentifier(wakeDatasetId)
    if (!datasetId) {
      setMessage('Wake dataset ID is required')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/samples`, {
        method: 'DELETE',
      })
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to clear wake dataset'))
      }
      setMessage(`Cleared ${String(data.deleted_count || 0)} wake samples`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to clear wake dataset')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, wakeDatasetId])

  const startWakeNegativeRecording = useCallback(async (durationSeconds: number) => {
    const datasetId = normalizeIdentifier(wakeDatasetId)
    if (!datasetId) {
      setMessage('Wake dataset ID is required to record clips')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      setWakeDatasetId(datasetId)
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/start-recording`, {
        method: 'POST',
        body: JSON.stringify({
          duration_seconds: durationSeconds,
          kind: 'negative',
          prompt: 'Ambient room noise — talk, play music/TV, or just leave it running',
        }),
      })
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to start negative recording'))
      }
      setMessage(`Ambient negative recording started (${durationSeconds}s)`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to start negative recording')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, wakeDatasetId])

  const clearWakeNegativeSamples = useCallback(async () => {
    const datasetId = normalizeIdentifier(wakeDatasetId)
    if (!datasetId) {
      setMessage('Wake dataset ID is required')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      const data = await request(`/api/sensory/datasets/${encodeURIComponent(datasetId)}/wake-word/samples?kind=negative`, {
        method: 'DELETE',
      })
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to clear negative samples'))
      }
      setMessage(`Cleared ${String(data.deleted_count || 0)} negative samples`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to clear negative samples')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, wakeDatasetId])

  const clearSpeakerDatasetSamples = useCallback(async () => {
    const datasetId = normalizeIdentifier(speakerDatasetId)
    const speakerId = normalizeIdentifier(speakerRecordId)
    if (!datasetId || !speakerId) {
      setMessage('Speaker dataset ID and speaker ID are required')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      const data = await request(
        `/api/sensory/datasets/${encodeURIComponent(datasetId)}/speakers/${encodeURIComponent(speakerId)}/samples`,
        { method: 'DELETE' },
      )
      if (data.status === 'error') {
        throw new Error(String(data.message || 'Unable to clear speaker dataset'))
      }
      setMessage(`Cleared ${String(data.deleted_count || 0)} samples for "${speakerId}"`)
      await refreshDatasetViews()
    } catch (error) {
      console.error(error)
      setMessage('Failed to clear speaker dataset')
    } finally {
      setBusy(false)
    }
  }, [normalizeIdentifier, refreshDatasetViews, request, speakerDatasetId, speakerRecordId])

  const saveThresholds = useCallback(async () => {
    setBusy(true)
    setMessage('')
    try {
      await request('/api/voice-control/config', {
        method: 'PUT',
        body: JSON.stringify({
          wake_word: { threshold: wakeThreshold, keyword: wakePhrase },
          vad: { speech_threshold: vadThreshold },
          ambient: { sample_interval_seconds: ambientInterval },
        }),
      })
      setMessage('Voice thresholds updated')
      await load()
    } catch (error) {
      console.error(error)
      setMessage('Failed to update thresholds')
    } finally {
      setBusy(false)
    }
  }, [ambientInterval, load, request, vadThreshold, wakePhrase, wakeThreshold])

  const activateVersion = useCallback(async (modelFamily: string, version: string) => {
    setBusy(true)
    setMessage('')
    try {
      await request(`/api/voice-control/models/${modelFamily}/activate`, {
        method: 'POST',
        body: JSON.stringify({ version }),
      })
      setMessage(`Activated ${modelFamily}:${version}`)
      await load()
    } catch (error) {
      console.error(error)
      setMessage(`Failed to activate ${modelFamily}:${version}`)
    } finally {
      setBusy(false)
    }
  }, [load, request])

  const simulateVoiceTurn = useCallback(async (includeError: boolean) => {
    setBusy(true)
    setMessage('')
    try {
      const data = await request('/api/voice-control/demo/simulate-turn', {
        method: 'POST',
        body: JSON.stringify({
          user_text: 'Hey Sara, status check from remote.',
          sara_text: 'Pipeline simulation complete. All services responsive.',
          speaker_id: 'david',
          include_error: includeError,
        }),
      })
      setMessage(`Simulated voice turn: ${data.trace_id}`)
      await load()
    } catch (error) {
      console.error(error)
      setMessage('Failed to simulate voice turn')
    } finally {
      setBusy(false)
    }
  }, [load, request])

  const recentTrainingJobs = useMemo(
    () => jobs.filter((job) => job.job_type.includes('train')),
    [jobs],
  )

  const normalizedWakeDatasetId = normalizeIdentifier(wakeDatasetId)
  const normalizedSpeakerDatasetId = normalizeIdentifier(speakerDatasetId)
  const normalizedSpeakerRecordId = normalizeIdentifier(speakerRecordId)
  const recordingFamily = datasetRecordingStatus?.family || ''
  const wakeRecordingMatches =
    recordingFamily === 'wake_word' &&
    datasetRecordingStatus?.dataset_id === normalizedWakeDatasetId
  const speakerRecordingMatches =
    recordingFamily === 'speakers' &&
    datasetRecordingStatus?.dataset_id === normalizedSpeakerDatasetId &&
    datasetRecordingStatus?.speaker_id === normalizedSpeakerRecordId

  return (
    <div className="mb-4 rounded-md border border-cyan-500/30 bg-gradient-to-r from-cyan-900/20 via-gray-900 to-teal-900/20 p-3">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-cyan-300">Voice Control Plane</div>
          <div className="text-sm text-gray-300">Modular rollout operations console</div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`text-[11px] ${streamConnected ? 'text-green-400' : 'text-gray-500'}`}>
            {streamConnected ? 'live stream connected' : 'stream reconnecting'}
          </div>
          {message && <div className="text-xs text-cyan-300">{message}</div>}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-md px-2 py-1 text-xs transition-colors ${
              activeTab === tab.id
                ? 'bg-cyan-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'pipeline' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => simulateVoiceTurn(false)}
              disabled={busy}
              className="rounded bg-cyan-600 px-3 py-1 text-xs text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              Simulate Voice Turn
            </button>
            <button
              onClick={() => simulateVoiceTurn(true)}
              disabled={busy}
              className="rounded bg-red-700 px-3 py-1 text-xs text-white hover:bg-red-600 disabled:opacity-50"
            >
              Simulate Error
            </button>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {(pipeline?.services || []).map((service) => (
              <div key={service.id} className={cardClass}>
                <div className="text-xs text-gray-400">{service.id}</div>
                <div className="text-sm font-semibold text-white">{service.name}</div>
                <div className={`text-sm ${statusClass(service.status || 'unknown')}`}>{service.status || 'unknown'}</div>
                <div className="mt-1 text-xs text-gray-500">
                  {service.version ? `v${service.version}` : 'no version'} {service.latency_ms ? `• ${service.latency_ms}ms` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'logs' && (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          <div className={cardClass}>
            <div className="mb-2 text-sm font-semibold text-white">Event Contracts</div>
            <div className="max-h-40 overflow-y-auto space-y-1">
              {(pipeline?.event_types || []).map((eventType) => (
                <div key={eventType} className="rounded bg-gray-900 px-2 py-1 text-xs text-gray-300">
                  {eventType}
                </div>
              ))}
            </div>
          </div>

          <div className={cardClass}>
            <div className="mb-2 text-sm font-semibold text-white">Recent Event Stream</div>
            <div className="max-h-48 overflow-y-auto space-y-1">
              {recentEvents.length === 0 && (
                <div className="text-xs text-gray-400">No events in stream yet.</div>
              )}
              {recentEvents.map((event) => (
                <div key={event.stream_id || event.event_id || `${event.event_type}-${event.timestamp}`} className="rounded bg-gray-900 px-2 py-1">
                  <div className="flex items-center justify-between">
                    <div className="text-xs text-cyan-300">{event.event_type}</div>
                    <div className="text-[11px] text-gray-500">{event.source || 'unknown'}</div>
                  </div>
                  <div className="text-[11px] text-gray-500">{event.timestamp || ''}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'wake-word' && (
        <div className={cardClass}>
          <div className="mb-2 text-sm font-semibold text-white">Wake Word Retraining</div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {WAKE_PHRASE_PRESETS.map((preset) => (
              <button
                key={preset.label}
                onClick={() => {
                  setWakePhrase(preset.phrase)
                  if (!wakeDatasetId) setWakeDatasetId(preset.datasetPrefix)
                }}
                className={`rounded px-3 py-1 text-xs ${
                  wakePhrase === preset.phrase ? 'bg-cyan-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <div className="mb-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            <input
              value={wakePhrase}
              onChange={(e) => setWakePhrase(e.target.value)}
              className="rounded bg-gray-900 px-2 py-1 text-sm text-white"
              placeholder="Wake phrase"
            />
            <input
              value={wakeDatasetId}
              onChange={(e) => setWakeDatasetId(normalizeIdentifier(e.target.value))}
              className="rounded bg-gray-900 px-2 py-1 text-sm text-white"
              placeholder="Dataset ID (required for recording/training)"
            />
            <label className="text-xs text-gray-400">
              Recording duration (seconds)
              <input
                type="number"
                min={2}
                max={60}
                value={wakeRecordDuration}
                onChange={(e) => setWakeRecordDuration(Math.min(60, Math.max(2, Number(e.target.value) || 5)))}
                className="mt-1 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
              />
            </label>
            <div className="text-xs text-gray-400">
              Active model: {models?.wake_word?.active_version || 'unknown'}
            </div>
          </div>

          <div className="mb-3 rounded bg-gray-900 px-3 py-2">
            <div className="flex items-center justify-between text-xs text-gray-400">
              <span>Guided session — positive clips</span>
              <span className="text-cyan-300">{Math.min(wakeSamples.length, WAKE_SESSION_TARGET)} of {WAKE_SESSION_TARGET}</span>
            </div>
            <div className="mt-1 h-1.5 w-full rounded bg-gray-800">
              <div
                className="h-1.5 rounded bg-cyan-600 transition-all"
                style={{ width: `${Math.min(100, (wakeSamples.length / WAKE_SESSION_TARGET) * 100)}%` }}
              />
            </div>
            <div className="mt-2 text-sm text-white">"{wakePhrase || 'hey sara'}" — {WAKE_PROMPT_VARIATIONS[wakePromptIndex]}</div>
            <button
              onClick={() => setWakePromptIndex((i) => (i + 1) % WAKE_PROMPT_VARIATIONS.length)}
              className="mt-1 text-[11px] text-gray-500 hover:text-gray-300"
            >
              Next variation ↻
            </button>
          </div>

          <div className="mb-2 flex flex-wrap items-center gap-2">
            <button
              onClick={startWakeDatasetRecording}
              disabled={busy || !normalizedWakeDatasetId}
              className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
            >
              Record Wake Clip
            </button>
            <button
              onClick={clearWakeDatasetSamples}
              disabled={busy || !normalizedWakeDatasetId}
              className="rounded bg-gray-700 px-3 py-1 text-sm text-white hover:bg-gray-600 disabled:opacity-50"
            >
              Clear Wake Dataset
            </button>
            <button
              onClick={queueWakeWordTraining}
              disabled={busy}
              className="rounded bg-cyan-600 px-3 py-1 text-sm text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              Queue Wake-Word Training
            </button>
          </div>
          {wakeRecordingMatches && (
            <div className="mb-2 rounded bg-gray-900 px-2 py-2 text-xs text-gray-300">
              <div className="font-medium text-cyan-300">
                Wake recording: {datasetRecordingStatus?.status || 'unknown'}
              </div>
              <div>
                {datasetRecordingStatus?.message || 'Processing dataset recording task...'}
              </div>
              {typeof datasetRecordingStatus?.progress === 'number' && (
                <div className="mt-1 text-[11px] text-gray-500">
                  Progress: {datasetRecordingStatus.progress}%
                </div>
              )}
            </div>
          )}
          <div className="text-xs text-gray-400">
            Wake dataset clips: {wakeSamples.length}
          </div>
          {wakeSamples.length > 0 && (
            <div className="mt-1 max-h-28 space-y-1 overflow-y-auto rounded bg-gray-900 p-2">
              {wakeSamples.map((sample) => (
                <div key={sample.filename} className="flex items-center justify-between text-[11px] text-gray-300">
                  <span>{sample.filename}</span>
                  <span className="text-gray-500">{formatBytes(sample.size_bytes)}</span>
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 border-t border-gray-800 pt-3">
            <div className="mb-1 text-xs font-semibold text-gray-300">
              Ambient negatives — room noise, music/TV, and Sara's own voice (hard negatives against self-trigger)
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <button
                onClick={() => startWakeNegativeRecording(60)}
                disabled={busy || !normalizedWakeDatasetId}
                className="rounded bg-blue-800 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Record 1 min
              </button>
              <button
                onClick={() => startWakeNegativeRecording(600)}
                disabled={busy || !normalizedWakeDatasetId}
                className="rounded bg-blue-800 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Record 10 min
              </button>
              <button
                onClick={clearWakeNegativeSamples}
                disabled={busy || !normalizedWakeDatasetId}
                className="rounded bg-gray-700 px-3 py-1 text-sm text-white hover:bg-gray-600 disabled:opacity-50"
              >
                Clear Negatives
              </button>
            </div>
            <div className="text-xs text-gray-400">
              Negative clips: {wakeNegativeSamples.length}
            </div>
          </div>

          <div className="mt-4 border-t border-gray-800 pt-3">
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-gray-300">
              Live test — detections stream from the Jetson in real time
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${streamConnected ? 'bg-green-500' : 'bg-gray-600'}`} />
            </div>
            <div className="max-h-32 space-y-1 overflow-y-auto rounded bg-gray-900 p-2">
              {recentEvents.filter((e) => e.event_type === 'wake.detected').length === 0 && (
                <div className="text-xs text-gray-500">Say the wake phrase near a live Jetson to see detections here.</div>
              )}
              {recentEvents.filter((e) => e.event_type === 'wake.detected').slice(0, 15).map((event) => {
                const confidence = Number(event.payload?.confidence ?? 0)
                const threshold = Number(event.payload?.threshold ?? 0)
                const passed = confidence >= threshold
                return (
                  <div key={event.stream_id || event.event_id || `${event.timestamp}`} className="flex items-center justify-between text-[11px]">
                    <span className="text-gray-400">{(event.payload?.keyword as string) || wakePhrase}</span>
                    <span className={passed ? 'text-green-400' : 'text-yellow-500'}>
                      {confidence.toFixed(3)} / {threshold.toFixed(3)}
                    </span>
                    <span className="text-gray-600">{event.timestamp || ''}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'speakers' && (
        <div className={cardClass}>
          <div className="mb-2 text-sm font-semibold text-white">Speaker Profile Retraining</div>
          <div className="mb-2 text-xs text-gray-400">Comma-separated speaker IDs</div>
          <input
            value={speakerIds}
            onChange={(e) => setSpeakerIds(e.target.value)}
            className="mb-2 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
            placeholder="david, sara, guest_1"
          />
          <input
            value={speakerDatasetId}
            onChange={(e) => setSpeakerDatasetId(normalizeIdentifier(e.target.value))}
            className="mb-2 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
            placeholder="Dataset ID (required for recording/training)"
          />
          <div className="mb-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            <input
              value={speakerRecordId}
              onChange={(e) => setSpeakerRecordId(normalizeIdentifier(e.target.value))}
              className="rounded bg-gray-900 px-2 py-1 text-sm text-white"
              placeholder="Speaker ID to record"
            />
            <label className="text-xs text-gray-400">
              Recording duration (seconds)
              <input
                type="number"
                min={2}
                max={60}
                value={speakerRecordDuration}
                onChange={(e) => setSpeakerRecordDuration(Math.min(60, Math.max(2, Number(e.target.value) || 8)))}
                className="mt-1 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={startSpeakerDatasetRecording}
              disabled={busy || !normalizedSpeakerDatasetId || !normalizedSpeakerRecordId}
              className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
            >
              Record Speaker Clip
            </button>
            <button
              onClick={clearSpeakerDatasetSamples}
              disabled={busy || !normalizedSpeakerDatasetId || !normalizedSpeakerRecordId}
              className="rounded bg-gray-700 px-3 py-1 text-sm text-white hover:bg-gray-600 disabled:opacity-50"
            >
              Clear Speaker Clips
            </button>
            <button
              onClick={queueSpeakerTraining}
              disabled={busy}
              className="rounded bg-teal-600 px-3 py-1 text-sm text-white hover:bg-teal-500 disabled:opacity-50"
            >
              Queue Speaker Training
            </button>
          </div>
          {speakerRecordingMatches && (
            <div className="mt-2 rounded bg-gray-900 px-2 py-2 text-xs text-gray-300">
              <div className="font-medium text-cyan-300">
                Speaker recording: {datasetRecordingStatus?.status || 'unknown'}
              </div>
              <div>
                {datasetRecordingStatus?.message || 'Processing dataset recording task...'}
              </div>
              {typeof datasetRecordingStatus?.progress === 'number' && (
                <div className="mt-1 text-[11px] text-gray-500">
                  Progress: {datasetRecordingStatus.progress}%
                </div>
              )}
            </div>
          )}
          <div className="mt-2 text-xs text-gray-400">
            Speaker clips ({normalizedSpeakerRecordId || 'speaker'}): {speakerSamples.length}
          </div>
          {speakerSamples.length > 0 && (
            <div className="mt-1 max-h-28 space-y-1 overflow-y-auto rounded bg-gray-900 p-2">
              {speakerSamples.map((sample) => (
                <div key={sample.filename} className="flex items-center justify-between text-[11px] text-gray-300">
                  <span>{sample.filename}</span>
                  <span className="text-gray-500">{formatBytes(sample.size_bytes)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'ambient' && (
        <div className={cardClass}>
          <div className="mb-2 text-sm font-semibold text-white">Adaptive VAD / Ambient Profile</div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <label className="text-xs text-gray-400">
              Wake threshold
              <input
                type="number"
                step="0.01"
                value={wakeThreshold}
                onChange={(e) => setWakeThreshold(Number(e.target.value))}
                className="mt-1 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
              />
            </label>
            <label className="text-xs text-gray-400">
              VAD speech threshold
              <input
                type="number"
                step="0.01"
                value={vadThreshold}
                onChange={(e) => setVadThreshold(Number(e.target.value))}
                className="mt-1 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
              />
            </label>
            <label className="text-xs text-gray-400">
              Ambient sample interval (s)
              <input
                type="number"
                value={ambientInterval}
                onChange={(e) => setAmbientInterval(Number(e.target.value))}
                className="mt-1 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
              />
            </label>
          </div>
          <button
            onClick={saveThresholds}
            disabled={busy}
            className="mt-3 rounded bg-indigo-600 px-3 py-1 text-sm text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            Save Adaptation Config
          </button>
        </div>
      )}

      {activeTab === 'models' && (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {(['wake_word', 'speakers'] as const).map((family) => (
            <div key={family} className={cardClass}>
              <div className="mb-2 text-sm font-semibold text-white">{family}</div>
              <div className="mb-2 text-xs text-gray-400">
                Active: {models?.[family]?.active_version || 'unknown'}
              </div>
              <div className="space-y-1">
                {(models?.[family]?.versions || []).map((version) => (
                  <div key={version.version} className="flex items-center justify-between rounded bg-gray-900 px-2 py-1">
                    <div className="text-xs text-gray-300">
                      {version.version} {version.status ? `(${version.status})` : ''}
                    </div>
                    <button
                      onClick={() => activateVersion(family, version.version)}
                      disabled={busy || models?.[family]?.active_version === version.version}
                      className="rounded bg-gray-700 px-2 py-0.5 text-xs text-white hover:bg-gray-600 disabled:opacity-50"
                    >
                      Activate
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'jobs' && (
        <div className={cardClass}>
          <div className="mb-2 text-sm font-semibold text-white">Recent Jobs</div>
          {jobs.length === 0 ? (
            <div className="text-xs text-gray-400">No jobs yet.</div>
          ) : (
            <div className="space-y-1">
              {jobs.map((job) => (
                <div key={job.job_id} className="rounded bg-gray-900 px-2 py-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-300">{job.job_type}</span>
                    <span className={`text-xs ${statusClass(job.status)}`}>{job.status}</span>
                  </div>
                  <div className="text-[11px] text-gray-500">{job.job_id}</div>
                  {job.claimed_by && (
                    <div className="text-[11px] text-cyan-400">claimed by: {job.claimed_by}</div>
                  )}
                  {job.notes && <div className="text-[11px] text-gray-400">{job.notes}</div>}
                  {job.result && (
                    <div className="text-[11px] text-gray-500">
                      result: {String(job.result.version || 'n/a')} ({String(job.result.model_family || 'model')})
                    </div>
                  )}
                  {job.error && <div className="text-[11px] text-red-400">{job.error}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'jobs' && recentTrainingJobs.length > 0 && (
        <div className="mt-2 text-[11px] text-gray-500">
          Training queue: {recentTrainingJobs.map((job) => `${job.job_type}:${job.status}`).join(' | ')}
        </div>
      )}

      {config && (
        <div className="mt-2 text-[11px] text-gray-500">
          Current config: wake `{config?.wake_word?.keyword || 'hey sara'}` / threshold `{config?.wake_word?.threshold ?? 'n/a'}` / vad `{config?.vad?.speech_threshold ?? 'n/a'}`
        </div>
      )}
    </div>
  )
}

export default SensoryControlPlane

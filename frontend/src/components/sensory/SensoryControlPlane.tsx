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

  const load = useCallback(async () => {
    try {
      const [pipelineData, configData, modelData, jobsData] = await Promise.all([
        request('/api/voice-control/pipeline/status'),
        request('/api/voice-control/config'),
        request('/api/voice-control/models'),
        request('/api/voice-control/jobs?limit=25'),
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

  return (
    <div className="mb-4 rounded-xl border border-cyan-500/30 bg-gradient-to-r from-cyan-900/20 via-gray-900 to-teal-900/20 p-3">
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
          <div className="mb-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            <input
              value={wakePhrase}
              onChange={(e) => setWakePhrase(e.target.value)}
              className="rounded bg-gray-900 px-2 py-1 text-sm text-white"
              placeholder="Wake phrase"
            />
            <input
              value={wakeDatasetId}
              onChange={(e) => setWakeDatasetId(e.target.value)}
              className="rounded bg-gray-900 px-2 py-1 text-sm text-white"
              placeholder="Dataset ID (optional)"
            />
            <div className="text-xs text-gray-400">
              Active model: {models?.wake_word?.active_version || 'unknown'}
            </div>
          </div>
          <button
            onClick={queueWakeWordTraining}
            disabled={busy}
            className="rounded bg-cyan-600 px-3 py-1 text-sm text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            Queue Wake-Word Training
          </button>
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
            onChange={(e) => setSpeakerDatasetId(e.target.value)}
            className="mb-2 w-full rounded bg-gray-900 px-2 py-1 text-sm text-white"
            placeholder="Dataset ID (optional)"
          />
          <button
            onClick={queueSpeakerTraining}
            disabled={busy}
            className="rounded bg-teal-600 px-3 py-1 text-sm text-white hover:bg-teal-500 disabled:opacity-50"
          >
            Queue Speaker Training
          </button>
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

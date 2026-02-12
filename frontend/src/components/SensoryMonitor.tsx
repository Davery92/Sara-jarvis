/**
 * Sensory Monitor - Real-time audio/visual pipeline monitoring
 * Shows mic activity, speaker identification, camera status, and speaker enrollment
 */

import React, { useState, useEffect, useRef } from 'react';
import { APP_CONFIG } from '../config';

interface AudioEvent {
  id: string;
  timestamp: string;
  type: 'transcription' | 'speaker_id' | 'wake_word' | 'processing';
  content: string;
  speaker?: string;
  confidence?: number;
  duration?: number;
}

interface SensoryStatus {
  voice_agent: {
    status: 'online' | 'offline' | 'unknown';
    last_seen?: string;
    state?: string;
  };
  nemo_diarization: {
    status: 'healthy' | 'degraded' | 'offline';
    model_loaded?: boolean;
    gpu_available?: boolean;
  };
  whisper: {
    status: 'healthy' | 'offline';
  };
  camera?: {
    status: 'active' | 'inactive' | 'offline';
    last_frame?: string;
  };
}

interface Speaker {
  speaker_id: string;
  num_samples: number;
  display_name?: string;
}

interface EnrollmentStatus {
  status: 'idle' | 'recording' | 'processing' | 'complete' | 'error';
  speaker_id?: string;
  progress?: number;
  samples_collected: number;
  samples_needed: number;
  message?: string;
}

export const SensoryMonitor: React.FC = () => {
  const [events, setEvents] = useState<AudioEvent[]>([]);
  const [status, setStatus] = useState<SensoryStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [jetsonLogs, setJetsonLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Speaker management state
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [enrollmentStatus, setEnrollmentStatus] = useState<EnrollmentStatus | null>(null);
  const [showEnrollmentModal, setShowEnrollmentModal] = useState(false);
  const [newSpeakerId, setNewSpeakerId] = useState('');
  const [recordingDuration, setRecordingDuration] = useState(10);
  const [isEnrolling, setIsEnrolling] = useState(false);

  // Wake word listening control
  const [wakeWordEnabled, setWakeWordEnabled] = useState(true);
  const [togglingWakeWord, setTogglingWakeWord] = useState(false);

  // Fetch initial status
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/status`, {
          credentials: 'include'
        });
        if (response.ok) {
          const data = await response.json();
          setStatus(data);
        }
      } catch (error) {
        console.error('Failed to fetch sensory status:', error);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Fetch wake word listening status
  useEffect(() => {
    const fetchWakeWordStatus = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/voice-agent/listening`, {
          credentials: 'include'
        });
        if (response.ok) {
          const data = await response.json();
          setWakeWordEnabled(data.listening_enabled);
        }
      } catch (error) {
        console.error('Failed to fetch wake word status:', error);
      }
    };

    fetchWakeWordStatus();
  }, []);

  // Toggle wake word listening
  const toggleWakeWord = async () => {
    setTogglingWakeWord(true);
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/voice-agent/listening`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !wakeWordEnabled })
      });
      if (response.ok) {
        const data = await response.json();
        setWakeWordEnabled(data.listening_enabled);
      }
    } catch (error) {
      console.error('Failed to toggle wake word:', error);
    } finally {
      setTogglingWakeWord(false);
    }
  };

  // Poll for Jetson logs
  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/jetson-logs?lines=50`, {
          credentials: 'include'
        });
        if (response.ok) {
          const data = await response.json();
          if (data.logs) {
            setJetsonLogs(data.logs);
            setIsConnected(true);
          }
        }
      } catch (error) {
        console.error('Failed to fetch Jetson logs:', error);
        setIsConnected(false);
      }
    };

    fetchLogs();
    const interval = setInterval(fetchLogs, 2000); // Poll every 2 seconds
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [jetsonLogs]);

  // Fetch enrolled speakers
  useEffect(() => {
    const fetchSpeakers = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers`, {
          credentials: 'include'
        });
        if (response.ok) {
          const data = await response.json();
          setSpeakers(data.speakers || []);
        }
      } catch (error) {
        console.error('Failed to fetch speakers:', error);
      }
    };

    fetchSpeakers();
    const interval = setInterval(fetchSpeakers, 10000); // Poll every 10 seconds
    return () => clearInterval(interval);
  }, []);

  // Poll enrollment status when recording/enrolling
  useEffect(() => {
    if (!showEnrollmentModal && !isEnrolling) return;

    const fetchEnrollmentStatus = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers/enrollment-status`, {
          credentials: 'include'
        });
        if (response.ok) {
          const data = await response.json();
          setEnrollmentStatus(data);

          // Reset isEnrolling when recording completes or errors
          if (data.status === 'complete' || data.status === 'error' || data.status === 'idle') {
            setIsEnrolling(false);
          }
        }
      } catch (error) {
        console.error('Failed to fetch enrollment status:', error);
      }
    };

    fetchEnrollmentStatus();
    const interval = setInterval(fetchEnrollmentStatus, 1000); // Poll every second during enrollment
    return () => clearInterval(interval);
  }, [showEnrollmentModal, isEnrolling]);

  // Speaker management handlers
  const startRecording = async (speakerId: string) => {
    try {
      setIsEnrolling(true);
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers/${speakerId}/start-recording`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ duration_seconds: recordingDuration })
      });
      const data = await response.json();
      if (data.status === 'error') {
        alert(data.message);
        setIsEnrolling(false);
      }
    } catch (error) {
      console.error('Failed to start recording:', error);
      setIsEnrolling(false);
    }
  };

  const enrollSpeaker = async (speakerId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers/${speakerId}/enroll`, {
        method: 'POST',
        credentials: 'include'
      });
      const data = await response.json();
      if (data.status === 'success') {
        setShowEnrollmentModal(false);
        setNewSpeakerId('');
        setIsEnrolling(false);
        // Refresh speakers list
        const speakersResponse = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers`, {
          credentials: 'include'
        });
        if (speakersResponse.ok) {
          const speakersData = await speakersResponse.json();
          setSpeakers(speakersData.speakers || []);
        }
      } else {
        alert(data.message);
      }
    } catch (error) {
      console.error('Failed to enroll speaker:', error);
    }
  };

  const deleteSpeaker = async (speakerId: string) => {
    if (!confirm(`Delete speaker "${speakerId}"? This cannot be undone.`)) return;

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers/${speakerId}`, {
        method: 'DELETE',
        credentials: 'include'
      });
      const data = await response.json();
      if (data.status === 'success') {
        setSpeakers(speakers.filter(s => s.speaker_id !== speakerId));
      } else {
        alert(data.message);
      }
    } catch (error) {
      console.error('Failed to delete speaker:', error);
    }
  };

  const clearSamples = async (speakerId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/sensory/speakers/${speakerId}/clear-samples`, {
        method: 'POST',
        credentials: 'include'
      });
      const data = await response.json();
      if (data.status === 'success') {
        setEnrollmentStatus(null);
      }
    } catch (error) {
      console.error('Failed to clear samples:', error);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online':
      case 'healthy':
      case 'active':
        return 'text-green-400';
      case 'degraded':
        return 'text-yellow-400';
      case 'offline':
      case 'inactive':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const getStatusDot = (status: string) => {
    const color = status === 'online' || status === 'healthy' || status === 'active'
      ? 'bg-green-500'
      : status === 'degraded'
      ? 'bg-yellow-500'
      : 'bg-red-500';

    return (
      <span className={`inline-block w-2 h-2 rounded-full ${color} ${
        status === 'online' || status === 'healthy' ? 'animate-pulse' : ''
      }`} />
    );
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="h-full bg-gray-900 text-white p-4 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <span className="text-2xl">📡</span> Sensory Monitor
        </h2>
        <div className="flex items-center gap-2 text-sm">
          <span className={isConnected ? 'text-green-400' : 'text-red-400'}>
            {isConnected ? '● Connected' : '○ Disconnected'}
          </span>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {/* Voice Agent */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Voice Agent</span>
            {getStatusDot(status?.voice_agent?.status || 'unknown')}
          </div>
          <div className={`text-lg font-semibold ${getStatusColor(status?.voice_agent?.status || 'unknown')}`}>
            {status?.voice_agent?.status || 'Unknown'}
          </div>
          {status?.voice_agent?.state && (
            <div className="text-xs text-gray-500 mt-1">
              State: {status.voice_agent.state}
            </div>
          )}
          {/* Wake Word Toggle */}
          <button
            onClick={toggleWakeWord}
            disabled={togglingWakeWord}
            className={`mt-2 w-full px-2 py-1 text-xs rounded transition-colors ${
              wakeWordEnabled
                ? 'bg-green-600 hover:bg-green-700 text-white'
                : 'bg-red-600 hover:bg-red-700 text-white'
            } ${togglingWakeWord ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {togglingWakeWord ? '...' : wakeWordEnabled ? '🎤 Listening' : '🔇 Paused'}
          </button>
        </div>

        {/* NeMo Diarization */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Speaker ID</span>
            {getStatusDot(status?.nemo_diarization?.status || 'offline')}
          </div>
          <div className={`text-lg font-semibold ${getStatusColor(status?.nemo_diarization?.status || 'offline')}`}>
            {status?.nemo_diarization?.status || 'Offline'}
          </div>
          {status?.nemo_diarization?.gpu_available && (
            <div className="text-xs text-gray-500 mt-1">GPU Active</div>
          )}
        </div>

        {/* Whisper */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Whisper STT</span>
            {getStatusDot(status?.whisper?.status || 'offline')}
          </div>
          <div className={`text-lg font-semibold ${getStatusColor(status?.whisper?.status || 'offline')}`}>
            {status?.whisper?.status || 'Offline'}
          </div>
        </div>

        {/* Camera */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Camera</span>
            {getStatusDot(status?.camera?.status || 'inactive')}
          </div>
          <div className={`text-lg font-semibold ${getStatusColor(status?.camera?.status || 'inactive')}`}>
            {status?.camera?.status || 'Inactive'}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
        {/* Audio Events */}
        <div className="bg-gray-800 rounded-lg p-3 flex flex-col min-h-0">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-2">
            <span>🎤</span> Audio Events
          </h3>
          <div className="flex-1 overflow-y-auto space-y-2">
            {events.length === 0 ? (
              <div className="text-gray-500 text-center py-8">
                Waiting for audio events...
                <div className="text-xs mt-2">Say "Hey Sara" to trigger</div>
              </div>
            ) : (
              events.map((event) => (
                <div
                  key={event.id}
                  className="bg-gray-700/50 rounded p-2 text-sm"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className={`font-medium ${
                      event.type === 'speaker_id' ? 'text-purple-400' :
                      event.type === 'transcription' ? 'text-blue-400' :
                      event.type === 'wake_word' ? 'text-green-400' :
                      'text-gray-400'
                    }`}>
                      {event.type === 'speaker_id' && '👤'}
                      {event.type === 'transcription' && '📝'}
                      {event.type === 'wake_word' && '🎯'}
                      {event.type === 'processing' && '⚙️'}
                      {' '}{event.type}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                  <div className="text-gray-300">{event.content}</div>
                  {event.speaker && (
                    <div className="text-xs text-purple-400 mt-1">
                      Speaker: {event.speaker}
                      {event.confidence && ` (${(event.confidence * 100).toFixed(0)}%)`}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Jetson Logs */}
        <div className="bg-gray-800 rounded-lg p-3 flex flex-col min-h-0">
          <h3 className="text-sm font-semibold text-gray-400 mb-2 flex items-center gap-2">
            <span>📋</span> Voice Agent Logs (Jetson)
          </h3>
          <div className="flex-1 overflow-y-auto font-mono text-xs bg-black/30 rounded p-2">
            {jetsonLogs.length === 0 ? (
              <div className="text-gray-500 text-center py-8">
                Waiting for logs...
              </div>
            ) : (
              jetsonLogs.map((log, i) => (
                <div
                  key={i}
                  className={`${
                    log.includes('Speaker: David') ? 'text-purple-400' :
                    log.includes('You:') ? 'text-blue-400' :
                    log.includes('Sara:') ? 'text-green-400' :
                    log.includes('ERROR') ? 'text-red-400' :
                    log.includes('WARNING') ? 'text-yellow-400' :
                    'text-gray-400'
                  }`}
                >
                  {log}
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      </div>

      {/* Speaker Management Section */}
      <div className="mt-4 bg-gray-800 rounded-lg p-3">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2">
            <span>👤</span> Speaker Management
          </h3>
          <button
            onClick={() => setShowEnrollmentModal(true)}
            className="px-3 py-1 bg-purple-600 hover:bg-purple-500 rounded text-sm font-medium"
          >
            + Add Speaker
          </button>
        </div>

        {/* Enrolled Speakers List */}
        <div className="grid grid-cols-3 gap-2">
          {speakers.length === 0 ? (
            <div className="col-span-3 text-center text-gray-500 py-4">
              No speakers enrolled. Click "Add Speaker" to begin.
            </div>
          ) : (
            speakers.map((speaker) => (
              <div
                key={speaker.speaker_id}
                className="bg-gray-700/50 rounded p-2 flex items-center justify-between"
              >
                <div>
                  <div className="font-medium text-sm">
                    {speaker.display_name || speaker.speaker_id}
                  </div>
                  <div className="text-xs text-gray-500">
                    {speaker.num_samples} samples
                  </div>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => {
                      setNewSpeakerId(speaker.speaker_id);
                      setShowEnrollmentModal(true);
                    }}
                    className="px-2 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs"
                    title="Add more samples"
                  >
                    Train
                  </button>
                  <button
                    onClick={() => deleteSpeaker(speaker.speaker_id)}
                    className="px-2 py-1 bg-red-600 hover:bg-red-500 rounded text-xs"
                    title="Delete speaker"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Footer with quick actions */}
      <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
        <div>
          Jetson: 10.185.1.155 | GPU Cluster: 10.185.1.8
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setEvents([])}
            className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs"
          >
            Clear Events
          </button>
          <button
            onClick={() => setJetsonLogs([])}
            className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs"
          >
            Clear Logs
          </button>
        </div>
      </div>

      {/* Enrollment Modal */}
      {showEnrollmentModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-[500px] max-w-[90vw]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">
                {enrollmentStatus?.samples_collected ? `Training: ${newSpeakerId}` : 'Speaker Enrollment'}
              </h3>
              <button
                onClick={() => {
                  setShowEnrollmentModal(false);
                  setNewSpeakerId('');
                  setIsEnrolling(false);
                }}
                className="text-gray-400 hover:text-white text-xl"
              >
                ×
              </button>
            </div>

            {/* Speaker ID Input */}
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-1">Speaker ID</label>
              <input
                type="text"
                value={newSpeakerId}
                onChange={(e) => setNewSpeakerId(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                placeholder="e.g., david, sarah, guest_1"
                className="w-full bg-gray-700 rounded px-3 py-2 text-white placeholder-gray-500"
                disabled={isEnrolling}
              />
              <p className="text-xs text-gray-500 mt-1">
                Use lowercase letters, numbers, and underscores only.
              </p>
            </div>

            {/* Recording Duration */}
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-1">Recording Duration</label>
              <div className="flex gap-2">
                {[5, 10, 15, 30].map((duration) => (
                  <button
                    key={duration}
                    onClick={() => setRecordingDuration(duration)}
                    className={`px-3 py-1 rounded ${
                      recordingDuration === duration
                        ? 'bg-purple-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                    }`}
                  >
                    {duration}s
                  </button>
                ))}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Longer recordings provide better speaker recognition accuracy.
              </p>
            </div>

            {/* Enrollment Status */}
            {enrollmentStatus && (
              <div className="mb-4 bg-gray-700/50 rounded p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm">
                    {enrollmentStatus.status === 'recording' && '🔴 Recording...'}
                    {enrollmentStatus.status === 'processing' && '⚙️ Processing...'}
                    {enrollmentStatus.status === 'complete' && '✅ Complete!'}
                    {enrollmentStatus.status === 'error' && '❌ Error'}
                    {enrollmentStatus.status === 'idle' && '⏸️ Ready'}
                  </span>
                  <span className="text-xs text-gray-400">
                    {enrollmentStatus.samples_collected}/{enrollmentStatus.samples_needed} samples
                  </span>
                </div>

                {/* Progress Bar */}
                {enrollmentStatus.status === 'recording' && enrollmentStatus.progress !== undefined && (
                  <div className="w-full bg-gray-600 rounded-full h-2">
                    <div
                      className="bg-red-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${enrollmentStatus.progress}%` }}
                    />
                  </div>
                )}

                {/* Sample Progress */}
                <div className="w-full bg-gray-600 rounded-full h-1 mt-2">
                  <div
                    className="bg-purple-500 h-1 rounded-full transition-all duration-300"
                    style={{
                      width: `${(enrollmentStatus.samples_collected / enrollmentStatus.samples_needed) * 100}%`
                    }}
                  />
                </div>

                {enrollmentStatus.message && (
                  <p className="text-xs text-gray-400 mt-2">{enrollmentStatus.message}</p>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex gap-2">
              {(!enrollmentStatus || enrollmentStatus.status === 'idle' || enrollmentStatus.status === 'complete' || enrollmentStatus.status === 'error') && (
                <button
                  onClick={() => {
                    if (newSpeakerId) {
                      startRecording(newSpeakerId);
                    }
                  }}
                  disabled={!newSpeakerId || isEnrolling}
                  className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded font-medium flex items-center justify-center gap-2"
                >
                  <span className="text-lg">🎤</span>
                  {enrollmentStatus?.samples_collected ? 'Record More' : 'Start Recording'}
                </button>
              )}

              {enrollmentStatus && enrollmentStatus.samples_collected >= enrollmentStatus.samples_needed && (
                <button
                  onClick={() => {
                    if (newSpeakerId) {
                      enrollSpeaker(newSpeakerId);
                    }
                  }}
                  className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-500 rounded font-medium"
                >
                  ✅ Enroll Speaker
                </button>
              )}

              {enrollmentStatus && enrollmentStatus.samples_collected > 0 && (
                <button
                  onClick={() => {
                    if (newSpeakerId) {
                      clearSamples(newSpeakerId);
                    }
                  }}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded"
                  title="Clear all recorded samples"
                >
                  Clear
                </button>
              )}
            </div>

            {/* Instructions */}
            <div className="mt-4 text-xs text-gray-500 border-t border-gray-700 pt-3">
              <p className="font-medium text-gray-400 mb-1">Recording Tips:</p>
              <ul className="list-disc list-inside space-y-0.5">
                <li>Speak naturally at your normal pace</li>
                <li>Vary your phrases - don't repeat the same thing</li>
                <li>Recording happens on Jetson (make sure mic is connected)</li>
                <li>3+ samples recommended for accurate identification</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SensoryMonitor;

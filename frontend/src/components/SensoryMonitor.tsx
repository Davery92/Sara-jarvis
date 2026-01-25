/**
 * Sensory Monitor - Real-time audio/visual pipeline monitoring
 * Shows mic activity, speaker identification, and camera status
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

export const SensoryMonitor: React.FC = () => {
  const [events, setEvents] = useState<AudioEvent[]>([]);
  const [status, setStatus] = useState<SensoryStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [jetsonLogs, setJetsonLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

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
    </div>
  );
};

export default SensoryMonitor;

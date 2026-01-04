import { useState, useEffect, useCallback } from 'preact/hooks';
import { StatePanel } from './components/StatePanel';
import { LLMStatusPanel } from './components/LLMStatusPanel';
import { VoiceInput } from './components/VoiceInput';
import { CalendarWidget } from './components/CalendarWidget';
import { NotesWidget } from './components/NotesWidget';
import { NoteModal } from './components/NoteModal';
import { TimerOverlay } from './components/TimerOverlay';
import { RecordingOverlay } from './components/RecordingOverlay';
import { api } from './services/api';
import { audioRecorderService } from './services/audioRecorder';
import { wakeWordClient } from './services/wakeWord';

// Get device token from localStorage or generate device name
const getStoredToken = () => localStorage.getItem('device_token');
const getDeviceName = () => {
  let name = localStorage.getItem('device_name');
  if (!name) {
    name = `pi-dashboard-${Date.now().toString(36)}`;
    localStorage.setItem('device_name', name);
  }
  return name;
};

// Worker status indicator for header
function WorkerIndicator({ workerStatus }) {
  if (!workerStatus) return null;

  const getStatusClass = (lastRun, intervalMins) => {
    if (!lastRun) return 'warning';
    const date = new Date(lastRun);
    const now = new Date();
    const diffMins = (now - date) / 60000;
    if (diffMins > intervalMins * 1.5) return 'error';
    return 'good';
  };

  const formatRelative = (isoString) => {
    if (!isoString) return 'never';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'now';
    if (diffMins < 60) return `${diffMins}m`;
    const diffHours = Math.floor(diffMins / 60);
    return `${diffHours}h`;
  };

  return (
    <div class="worker-indicators">
      {workerStatus.subconscious && (
        <div class="worker-indicator" title={`Subconscious: ${formatRelative(workerStatus.subconscious.last_run)} ago`}>
          <span class={`indicator-dot ${getStatusClass(workerStatus.subconscious.last_run, 30)}`}></span>
          <span class="indicator-label">Sub</span>
        </div>
      )}
      {workerStatus.orchestrator && (
        <div class="worker-indicator" title={`Orchestrator: ${formatRelative(workerStatus.orchestrator.last_run)} ago`}>
          <span class={`indicator-dot ${getStatusClass(workerStatus.orchestrator.last_run, 5)}`}></span>
          <span class="indicator-label">Orch</span>
        </div>
      )}
    </div>
  );
}

// Nudge popup component
function NudgePopup({ nudges, onAcknowledge, onDismiss }) {
  if (!nudges || nudges.length === 0) return null;

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'urgent': return '🚨';
      case 'gentle': return '💡';
      default: return 'ℹ️';
    }
  };

  return (
    <div class="nudge-overlay" onClick={onDismiss}>
      <div class="nudge-popup" onClick={(e) => e.stopPropagation()}>
        <div class="nudge-popup-header">
          <span class="nudge-popup-title">Nudges ({nudges.length})</span>
          <button class="nudge-close-btn" onClick={onDismiss}>×</button>
        </div>
        <div class="nudge-popup-list">
          {nudges.map((nudge) => (
            <div key={nudge.id} class={`nudge-popup-item severity-${nudge.severity}`}>
              <span class="nudge-icon">{getSeverityIcon(nudge.severity)}</span>
              <div class="nudge-content">
                <div class="nudge-title">{nudge.title}</div>
                <div class="nudge-message">{nudge.message}</div>
              </div>
              <button class="nudge-ack-btn" onClick={() => onAcknowledge(nudge.id)}>✓</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Nudge badge for header
function NudgeBadge({ count, onClick }) {
  if (count === 0) return null;
  return (
    <button class="nudge-badge" onClick={onClick}>
      <span class="nudge-badge-icon">💡</span>
      <span class="nudge-badge-count">{count}</span>
    </button>
  );
}

export function App() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [state, setState] = useState(null);
  const [nudges, setNudges] = useState([]);
  const [workerStatus, setWorkerStatus] = useState(null);
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [notes, setNotes] = useState([]);
  const [selectedNote, setSelectedNote] = useState(null);
  const [showNudges, setShowNudges] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [needsRegistration, setNeedsRegistration] = useState(!getStoredToken());
  const [email, setEmail] = useState('');
  const [activeTimers, setActiveTimers] = useState([]);
  const [isContinuousRecording, setIsContinuousRecording] = useState(false);
  const [recordingProcessing, setRecordingProcessing] = useState(false);
  const [wakeWordConnected, setWakeWordConnected] = useState(false);
  const [wakeWordTriggered, setWakeWordTriggered] = useState(false);
  const [alwaysListening, setAlwaysListening] = useState(() => {
    // Load from localStorage, default to false
    return localStorage.getItem('always_listening') === 'true';
  });

  // Reference to VoiceInput for triggering recording
  const voiceInputRef = useCallback(node => {
    if (node) {
      // Store reference for wake word trigger
      window.__voiceInputTrigger = () => {
        // Simulate tap on voice input to start recording
        node.click();
      };
    }
  }, []);

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Toggle always-listening mode
  const toggleAlwaysListening = useCallback(() => {
    setAlwaysListening(prev => {
      const newValue = !prev;
      localStorage.setItem('always_listening', String(newValue));
      return newValue;
    });
  }, []);

  // Connect to wake word service only when always-listening is enabled
  useEffect(() => {
    if (!alwaysListening) {
      // Disconnect if always-listening is off
      wakeWordClient.disconnect();
      setWakeWordConnected(false);
      return;
    }

    const handleWakeWordDetected = (data) => {
      console.log('[App] Wake word detected!', data);
      setWakeWordTriggered(true);

      // Trigger voice recording
      if (window.__voiceInputTrigger) {
        window.__voiceInputTrigger();
      }

      // Reset trigger indicator after a moment
      setTimeout(() => setWakeWordTriggered(false), 2000);
    };

    // Connect to wake word WebSocket
    wakeWordClient.connect(handleWakeWordDetected);

    // Update connection status periodically
    const statusInterval = setInterval(() => {
      setWakeWordConnected(wakeWordClient.isConnected());
    }, 1000);

    return () => {
      clearInterval(statusInterval);
      wakeWordClient.disconnect();
    };
  }, [alwaysListening]);

  // Fetch combined dashboard state
  const fetchData = useCallback(async () => {
    try {
      const data = await api.getDashboardState();
      setState(data.state);
      setNudges(data.nudges || []);
      setWorkerStatus(data.worker_status || null);
      setCalendarEvents(data.calendar_events || []);
      setNotes(data.recent_notes || []);
      setError(null);
      setNeedsRegistration(false);
    } catch (err) {
      console.error('Error fetching data:', err);
      if (err.message.includes('401') || err.message.includes('403') || err.message.includes('Not authenticated')) {
        setNeedsRegistration(true);
      }
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch and polling
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Fetch active timers
  const fetchTimers = useCallback(async () => {
    try {
      const data = await api.getActiveTimers();
      setActiveTimers(data.timers || []);
    } catch (err) {
      console.error('Error fetching timers:', err);
    }
  }, []);

  // Poll for active timers (every 10 seconds)
  useEffect(() => {
    fetchTimers();
    const interval = setInterval(fetchTimers, 10000);
    return () => clearInterval(interval);
  }, [fetchTimers]);

  // Handle timer completion (local notification)
  const handleTimerComplete = useCallback((timer) => {
    console.log('[App] Timer completed:', timer.title);
    // Re-fetch to sync with backend
    fetchTimers();
  }, [fetchTimers]);

  // Start continuous recording (for "record this" command)
  const startContinuousRecording = useCallback(async () => {
    console.log('[App] Starting continuous recording...');
    try {
      await audioRecorderService.startContinuousRecording();
      setIsContinuousRecording(true);
    } catch (err) {
      console.error('[App] Failed to start continuous recording:', err);
      setError('Failed to start recording');
    }
  }, []);

  // Stop continuous recording, transcribe, and open note modal
  const stopContinuousRecording = useCallback(async () => {
    console.log('[App] Stopping continuous recording...');
    setRecordingProcessing(true);

    try {
      // Stop recording and get audio blob
      const audioBlob = await audioRecorderService.stopRecording();
      setIsContinuousRecording(false);

      if (!audioBlob || audioBlob.size < 1000) {
        console.log('[App] Recording too short');
        setRecordingProcessing(false);
        return;
      }

      console.log('[App] Transcribing audio, size:', audioBlob.size);

      // Transcribe the audio
      const transcribeResult = await api.transcribeAudio(audioBlob);
      const text = transcribeResult.transcription;

      if (!text || text.trim().length === 0) {
        console.log('[App] No speech detected in recording');
        setRecordingProcessing(false);
        return;
      }

      console.log('[App] Transcription complete:', text.substring(0, 100) + '...');

      // Create a new note object and open in modal
      const lines = text.split('\n');
      const firstLine = lines[0].trim();
      const title = firstLine.length > 50
        ? firstLine.substring(0, 50) + '...'
        : firstLine || 'Voice Recording';

      const newNote = {
        id: null,
        title: title,
        content: text,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        isNew: true,
      };

      setSelectedNote(newNote);
    } catch (err) {
      console.error('[App] Error processing recording:', err);
      setError('Failed to process recording');
    } finally {
      setRecordingProcessing(false);
    }
  }, []);

  // Cancel continuous recording without saving
  const cancelContinuousRecording = useCallback(async () => {
    console.log('[App] Cancelling continuous recording...');
    await audioRecorderService.stopRecording();
    setIsContinuousRecording(false);
  }, []);

  // Handle nudge acknowledgment
  const handleAcknowledge = async (nudgeId) => {
    console.log('[handleAcknowledge] Called with nudgeId:', nudgeId);
    try {
      const result = await api.acknowledgeNudge(nudgeId);
      console.log('[handleAcknowledge] API result:', result);
      setNudges(nudges.filter(n => n.id !== nudgeId));
      console.log('[handleAcknowledge] Nudge removed from state');
    } catch (err) {
      console.error('[handleAcknowledge] Error:', err);
    }
  };

  // Handle voice command
  const handleVoiceCommand = (command, params) => {
    console.log('Voice command:', command, params);
    // TODO: Implement command handling for notes, etc.
  };

  // Handle device registration via bootstrap
  const handleRegister = async () => {
    if (!email.trim()) {
      setError('Please enter your email address');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.bootstrapDevice(email.trim(), getDeviceName(), 'pi_dashboard');
      setNeedsRegistration(false);
      await fetchData();
    } catch (err) {
      console.error('Registration error:', err);
      setError(`Registration failed: ${err.message}`);
      setLoading(false);
    }
  };

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    });
  };

  // Registration screen
  if (needsRegistration && !loading) {
    return (
      <div class="dashboard">
        <header class="header">
          <h1 class="header-title">Sara's Dashboard</h1>
          <span class="header-time">{formatTime(currentTime)}</span>
        </header>
        <main class="main-grid">
          <div class="card" style="grid-column: span 2; text-align: center; padding: 3rem;">
            <h2 style="margin-bottom: 1rem; color: var(--text-primary);">Device Registration Required</h2>
            <p style="margin-bottom: 2rem; color: var(--text-secondary);">
              Enter your Sara account email to register this Pi dashboard.
            </p>
            {error && (
              <p style="color: var(--accent-red); margin-bottom: 1rem;">{error}</p>
            )}
            <input
              type="email"
              value={email}
              onInput={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              style="width: 300px; padding: 0.8rem 1rem; font-size: 1.1rem; border: 2px solid var(--border-color); border-radius: 8px; background: var(--bg-secondary); color: var(--text-primary); margin-bottom: 1rem;"
              onKeyPress={(e) => e.key === 'Enter' && handleRegister()}
            />
            <br />
            <button
              onClick={handleRegister}
              style="background: var(--accent-blue); color: white; border: none; padding: 1rem 2rem; font-size: 1.2rem; border-radius: 8px; cursor: pointer;"
            >
              Register This Device
            </button>
            <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted);">
              Device: {getDeviceName()}
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div class="dashboard">
      {/* Header with worker indicators */}
      <header class="header">
        <div class="header-left">
          <h1 class="header-title">Sara's Mental Model</h1>
          <WorkerIndicator workerStatus={workerStatus} />
        </div>
        <div class="header-right">
          {/* Always-Listening Toggle */}
          <button
            class={`always-listening-toggle ${alwaysListening ? 'active' : ''}`}
            onClick={toggleAlwaysListening}
            title={alwaysListening ? 'Always-Listening: ON (Say "Hey Sara")' : 'Always-Listening: OFF (Tap to speak)'}
          >
            <span class="toggle-icon">{alwaysListening ? '👂' : '🔇'}</span>
            <span class="toggle-status">
              {alwaysListening ? (wakeWordConnected ? 'Listening' : 'Connecting...') : 'Tap Mode'}
            </span>
          </button>
          <NudgeBadge count={nudges.length} onClick={() => setShowNudges(true)} />
          <span class="header-time">{formatTime(currentTime)}</span>
        </div>
      </header>

      {/* Main content - simplified grid */}
      <main class="main-grid-simple">
        {loading ? (
          <div class="loading">
            <div class="spinner" />
          </div>
        ) : error ? (
          <div class="card">
            <div class="empty-state">
              Error: {error}
            </div>
          </div>
        ) : (
          <>
            <StatePanel state={state} />
            <LLMStatusPanel state={state} />
            <CalendarWidget events={calendarEvents} loading={false} />
          </>
        )}
      </main>

      {/* Timer overlay - shows active timers */}
      <TimerOverlay
        timers={activeTimers}
        onTimerComplete={handleTimerComplete}
      />

      {/* Continuous recording overlay */}
      <RecordingOverlay
        isActive={isContinuousRecording}
        isProcessing={recordingProcessing}
        onStop={stopContinuousRecording}
        onCancel={cancelContinuousRecording}
      />

      {/* Voice input with three-tier routing */}
      <div ref={voiceInputRef}>
        <VoiceInput
          onTranscript={(text) => console.log('[App] Transcription:', text)}
          wakeWordConnected={wakeWordConnected}
          alwaysListening={alwaysListening}
          commandContext={{
          api,
          setSelectedNote,
          setShowNudges,
          fetchData,
          fetchTimers,
          nudges,
          onAcknowledge: handleAcknowledge,
          startContinuousRecording,
          stopContinuousRecording,
        }}
        />
      </div>

      {/* Nudge popup */}
      {showNudges && (
        <NudgePopup
          nudges={nudges}
          onAcknowledge={handleAcknowledge}
          onDismiss={() => setShowNudges(false)}
        />
      )}

      {/* Note modal with markdown rendering */}
      {selectedNote && (
        <NoteModal
          note={selectedNote}
          onClose={() => setSelectedNote(null)}
        />
      )}
    </div>
  );
}

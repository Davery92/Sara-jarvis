/**
 * API service for communicating with Sara backend
 */

const API_URL = import.meta.env.VITE_API_URL || 'http://10.185.1.180:8000';

// Get base URL for direct fetch calls
const getBaseUrl = () => API_URL;

// Device token for authentication (stored in localStorage)
const getDeviceToken = () => {
  return localStorage.getItem('device_token');
};

const setDeviceToken = (token) => {
  localStorage.setItem('device_token', token);
};

// Fetch with device token auth
async function fetchWithAuth(path, options = {}) {
  const token = getDeviceToken();

  const headers = {
    'Content-Type': 'application/json',
    ...(token && { 'X-Device-Token': token }),
    ...options.headers,
  };

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include', // For cookie-based auth fallback
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }

  return response.json();
}

export const api = {
  // Get base URL
  getBaseUrl,

  // Get current subconscious state
  async getState() {
    return fetchWithAuth('/api/subconscious/state');
  },

  // Get pending nudges
  async getNudges() {
    return fetchWithAuth('/api/subconscious/nudges');
  },

  // Acknowledge a nudge (uses Pi dashboard endpoint with device token auth)
  async acknowledgeNudge(nudgeId) {
    return fetchWithAuth(`/api/pi-dashboard/nudges/${nudgeId}/acknowledge`, {
      method: 'POST',
    });
  },

  // Classify a voice command
  async classifyCommand(text) {
    return fetchWithAuth('/api/pi-dashboard/classify', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
  },

  // Get note by ID
  async getNote(noteId) {
    return fetchWithAuth(`/api/notes/${noteId}`);
  },

  // Search notes
  async searchNotes(query) {
    return fetchWithAuth(`/api/notes/search?q=${encodeURIComponent(query)}`);
  },

  // Save transcription as note
  async saveNote(content, title) {
    return fetchWithAuth('/api/notes', {
      method: 'POST',
      body: JSON.stringify({ content, title }),
    });
  },

  // Register device (requires logged-in session)
  async registerDevice(deviceName, deviceType = 'pi_dashboard') {
    const response = await fetchWithAuth('/api/devices/register', {
      method: 'POST',
      body: JSON.stringify({ device_name: deviceName, device_type: deviceType }),
    });
    if (response.device_token) {
      setDeviceToken(response.device_token);
    }
    return response;
  },

  // Bootstrap device registration (for headless devices like Pi)
  async bootstrapDevice(email, deviceName, deviceType = 'pi_dashboard') {
    const response = await fetch(`${API_URL}/api/devices/bootstrap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, device_name: deviceName, device_type: deviceType }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const data = await response.json();
    if (data.device_token) {
      setDeviceToken(data.device_token);
    }
    return data;
  },

  // Get combined dashboard state (for Pi dashboard)
  async getDashboardState() {
    return fetchWithAuth('/api/pi-dashboard/state');
  },

  // Transcribe audio via Whisper
  async transcribeAudio(audioBlob) {
    const token = getDeviceToken();
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    const response = await fetch(`${API_URL}/api/pi-dashboard/voice/transcribe`, {
      method: 'POST',
      headers: {
        ...(token && { 'X-Device-Token': token }),
      },
      credentials: 'include',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `HTTP ${response.status}`);
    }

    return response.json();
  },

  // Send message to Sara via streaming chat
  async sendChatMessage(message) {
    const token = getDeviceToken();
    const response = await fetch(`${API_URL}/api/pi-dashboard/voice/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { 'X-Device-Token': token }),
      },
      credentials: 'include',
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `HTTP ${response.status}`);
    }

    // Parse SSE stream and accumulate response
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'text_chunk') {
              fullResponse += data.content;
            } else if (data.type === 'final_response') {
              fullResponse = data.content;
            }
          } catch (e) {
            // Ignore parse errors for partial chunks
          }
        }
      }
    }

    return { response: fullResponse };
  },

  // Try fast worker for HOME, TIME, FITNESS commands
  async tryFastWorker(message) {
    const token = getDeviceToken();
    const response = await fetch(`${API_URL}/api/pi-dashboard/voice/fast`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { 'X-Device-Token': token }),
      },
      credentials: 'include',
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      return { handled: false, reason: 'Request failed' };
    }

    return response.json();
  },

  // Start transcription session
  async startTranscription() {
    return fetchWithAuth('/api/pi-dashboard/transcription/start', {
      method: 'POST',
    });
  },

  // Stop and save transcription
  async stopTranscription(sessionId) {
    return fetchWithAuth('/api/pi-dashboard/transcription/stop', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  // Get active timers for overlay
  async getActiveTimers() {
    return fetchWithAuth('/api/pi-dashboard/timers');
  },
};

// SSE subscription for real-time nudge updates
export function subscribeToNudges(onNudge) {
  const token = getDeviceToken();
  const url = new URL(`${API_URL}/api/subconscious/nudges/stream`);

  const eventSource = new EventSource(url, {
    withCredentials: true,
  });

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'nudge') {
        onNudge(data.nudge);
      }
    } catch (err) {
      console.error('Error parsing SSE message:', err);
    }
  };

  eventSource.onerror = (err) => {
    console.error('SSE error:', err);
  };

  return () => {
    eventSource.close();
  };
}

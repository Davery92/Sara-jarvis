/**
 * Wake Word Client - Streams audio to server for wake word detection
 *
 * Uses AudioWorklet (modern) with fallback to ScriptProcessor.
 * Matches tap-to-speak audio capture approach for consistency.
 */

// Derive WebSocket URL from API URL
const getWsUrl = () => {
  const apiUrl = import.meta.env.VITE_API_URL || 'http://10.185.1.180:8000';
  const url = new URL(apiUrl);
  const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${wsProtocol}//${url.host}/ws/wake-word`;
};
const WAKE_WORD_WS_URL = getWsUrl();
const RECONNECT_DELAY_MS = 5000;
const AUDIO_CHUNK_INTERVAL_MS = 100;

class WakeWordClient {
  constructor() {
    this.ws = null;
    this.onWakeDetected = null;
    this.reconnectTimer = null;
    this.connected = false;
    this.streaming = false;
    this.intentionalDisconnect = false;

    // Audio capture
    this.audioContext = null;
    this.mediaStream = null;
    this.workletNode = null;
    this.processor = null;  // Fallback ScriptProcessor
    this.analyser = null;
    this.audioChunks = [];
    this.chunkTimer = null;
    this.lastMeteringLog = null;
    this.useWorklet = false;

    // Audio metering thresholds (same as tap-to-speak)
    this.SILENCE_THRESHOLD_DB = -35;
  }

  /**
   * Connect to the wake word service and start streaming
   */
  connect(onWakeDetected) {
    console.log('[WakeWord] connect() called');
    this.intentionalDisconnect = false;
    this.onWakeDetected = onWakeDetected;
    this._connect();
  }

  async _connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('[WakeWord] Connecting to:', WAKE_WORD_WS_URL);

    try {
      this.ws = new WebSocket(WAKE_WORD_WS_URL);

      this.ws.onopen = async () => {
        console.log('[WakeWord] Connected to wake word service');
        this.connected = true;
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[WakeWord] Received:', data);

          if (data.type === 'ready') {
            console.log('[WakeWord] Server ready, starting audio capture');
            this._startAudioCapture();
          } else if (data.type === 'wake_detected') {
            console.log(`[WakeWord] Wake word detected: ${data.wake_word} (${data.confidence.toFixed(3)})`);
            if (this.onWakeDetected) {
              this.onWakeDetected(data);
            }
          } else if (data.type === 'error') {
            console.error('[WakeWord] Server error:', data.message);
          }
        } catch (e) {
          console.warn('[WakeWord] Failed to parse message:', e);
        }
      };

      this.ws.onclose = () => {
        console.log('[WakeWord] Connection closed, intentional:', this.intentionalDisconnect);
        this.connected = false;
        this._stopAudioCapture();
        if (!this.intentionalDisconnect) {
          this._scheduleReconnect();
        }
      };

      this.ws.onerror = (error) => {
        console.warn('[WakeWord] WebSocket error:', error);
        this.connected = false;
      };
    } catch (error) {
      console.warn('[WakeWord] Failed to connect:', error);
      this._scheduleReconnect();
    }
  }

  async _startAudioCapture() {
    console.log('[WakeWord] _startAudioCapture called, streaming:', this.streaming);
    if (this.streaming) {
      console.log('[WakeWord] Already streaming, skipping');
      return;
    }

    try {
      // Request microphone - SAME settings as tap-to-speak
      console.log('[WakeWord] Requesting microphone access...');
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000
        }
      });

      const tracks = this.mediaStream.getAudioTracks();
      console.log('[WakeWord] Microphone access granted, tracks:', tracks.length);
      if (tracks.length > 0) {
        const settings = tracks[0].getSettings();
        console.log('[WakeWord] Track settings:', JSON.stringify(settings));
      }

      // Create audio context
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      console.log('[WakeWord] AudioContext created, state:', this.audioContext.state, 'sampleRate:', this.audioContext.sampleRate);

      // Resume if suspended
      if (this.audioContext.state === 'suspended') {
        console.log('[WakeWord] Resuming suspended AudioContext...');
        await this.audioContext.resume();
        console.log('[WakeWord] AudioContext resumed, state:', this.audioContext.state);
      }

      const nativeSampleRate = this.audioContext.sampleRate;
      const targetSampleRate = 16000;
      const resampleRatio = nativeSampleRate / targetSampleRate;

      console.log(`[WakeWord] Native: ${nativeSampleRate}Hz, Target: ${targetSampleRate}Hz, Ratio: ${resampleRatio}`);

      // Create source from microphone
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      console.log('[WakeWord] MediaStreamSource created');

      // Create analyser for metering (same as tap-to-speak)
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.3;

      // Try AudioWorklet first, fall back to ScriptProcessor
      try {
        await this._setupAudioWorklet(source, resampleRatio);
      } catch (workletError) {
        console.warn('[WakeWord] AudioWorklet failed, using ScriptProcessor:', workletError.message);
        this._setupScriptProcessor(source, resampleRatio);
      }

      // Connect source to analyser for metering
      source.connect(this.analyser);

      this.streaming = true;

      // Start sending audio chunks and logging levels
      this.chunkTimer = setInterval(() => {
        this._sendAudioChunks();
        this._logAudioLevel();
      }, AUDIO_CHUNK_INTERVAL_MS);

      console.log('[WakeWord] Audio capture started, method:', this.useWorklet ? 'AudioWorklet' : 'ScriptProcessor');

    } catch (error) {
      console.error('[WakeWord] Failed to start audio capture:', error);
    }
  }

  async _setupAudioWorklet(source, resampleRatio) {
    // Load the audio worklet processor with cache-busting
    const processorUrl = new URL('/audio-processor.js?v=' + Date.now(), window.location.origin).href;
    console.log('[WakeWord] Loading AudioWorklet from:', processorUrl);

    await this.audioContext.audioWorklet.addModule(processorUrl);
    console.log('[WakeWord] AudioWorklet module loaded');

    this.workletNode = new AudioWorkletNode(this.audioContext, 'audio-processor');
    let messageCount = 0;

    // Handle messages from worklet
    let audioMessageCount = 0;
    this.workletNode.port.onmessage = (event) => {
      messageCount++;
      if (event.data.type === 'debug') {
        console.log('[WakeWord] Worklet debug:', event.data.message);
        return;
      }

      // Log all audio messages
      if (event.data.type === 'audio') {
        audioMessageCount++;
        if (audioMessageCount <= 5) {
          console.log('[WakeWord] Audio message #' + audioMessageCount,
            'streaming:', this.streaming,
            'bytes:', event.data.samples?.byteLength);
        }

        if (this.streaming) {
          // Resample if needed
          let samples = new Int16Array(event.data.samples);
          if (resampleRatio > 1) {
            const newLength = Math.floor(samples.length / resampleRatio);
            const resampled = new Int16Array(newLength);
            for (let i = 0; i < newLength; i++) {
              resampled[i] = samples[Math.floor(i * resampleRatio)];
            }
            samples = resampled;
          }
          this.audioChunks.push(samples);

          if (audioMessageCount <= 3) {
            console.log('[WakeWord] Pushed chunk, total chunks:', this.audioChunks.length);
          }
        }
      } else {
        console.log('[WakeWord] Unknown message type:', event.data.type);
      }
    };

    this.workletNode.port.onmessageerror = (err) => {
      console.error('[WakeWord] Worklet message error:', err);
    };

    // Connect source -> worklet -> destination
    source.connect(this.workletNode);
    this.workletNode.connect(this.audioContext.destination);
    this.useWorklet = true;
    console.log('[WakeWord] AudioWorklet connected');
  }

  _setupScriptProcessor(source, resampleRatio) {
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
    let processCount = 0;

    this.processor.onaudioprocess = (event) => {
      if (!this.streaming) return;

      processCount++;
      const inputData = event.inputBuffer.getChannelData(0);

      // Log first few to verify audio is flowing
      if (processCount <= 5) {
        const maxSample = Math.max(...Array.from(inputData).slice(0, 100).map(Math.abs));
        console.log(`[WakeWord] ScriptProcessor #${processCount}, samples: ${inputData.length}, max: ${maxSample.toFixed(4)}`);
      }

      // Downsample if needed
      let samples;
      if (resampleRatio > 1) {
        const newLength = Math.floor(inputData.length / resampleRatio);
        samples = new Float32Array(newLength);
        for (let i = 0; i < newLength; i++) {
          samples[i] = inputData[Math.floor(i * resampleRatio)];
        }
      } else {
        samples = inputData;
      }

      // Convert float32 to int16
      const int16Data = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }

      this.audioChunks.push(int16Data);
    };

    // Connect source -> processor -> destination
    source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
    this.useWorklet = false;
    console.log('[WakeWord] ScriptProcessor connected');
  }

  _logAudioLevel() {
    if (!this.analyser) return;

    const now = Date.now();
    if (this.lastMeteringLog && now - this.lastMeteringLog < 500) return;
    this.lastMeteringLog = now;

    // Get frequency data (same as tap-to-speak)
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);

    const sum = dataArray.reduce((acc, val) => acc + val * val, 0);
    const rms = Math.sqrt(sum / dataArray.length);
    const metering = rms === 0 ? -160 : 20 * Math.log10(rms / 255);
    const isSilent = metering < this.SILENCE_THRESHOLD_DB;

    console.log(`[WakeWord] Audio: ${metering.toFixed(1)} dB, Silent: ${isSilent}, Chunks: ${this.audioChunks.length}`);
  }

  _sendAudioChunks() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    if (this.audioChunks.length === 0) return;

    // Combine all chunks
    const totalLength = this.audioChunks.reduce((acc, chunk) => acc + chunk.length, 0);
    const combined = new Int16Array(totalLength);
    let offset = 0;
    for (const chunk of this.audioChunks) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }

    this.audioChunks = [];
    this.ws.send(combined.buffer);
  }

  _stopAudioCapture() {
    this.streaming = false;

    if (this.chunkTimer) {
      clearInterval(this.chunkTimer);
      this.chunkTimer = null;
    }

    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }

    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }

    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }

    this.audioChunks = [];
    this.lastMeteringLog = null;
    console.log('[WakeWord] Audio capture stopped');
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;

    console.log(`[WakeWord] Reconnecting in ${RECONNECT_DELAY_MS / 1000}s...`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._connect();
    }, RECONNECT_DELAY_MS);
  }

  ping() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'ping' }));
    }
  }

  isConnected() {
    return this.connected && this.streaming && this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  getAmplitude() {
    if (!this.analyser) return 0;

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);

    const sum = dataArray.reduce((acc, val) => acc + val, 0);
    const average = sum / dataArray.length;

    return Math.min(1, average / 128);
  }

  disconnect() {
    console.log('[WakeWord] disconnect() called');
    this.intentionalDisconnect = true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this._stopAudioCapture();

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
    console.log('[WakeWord] Fully disconnected');
  }
}

export const wakeWordClient = new WakeWordClient();
export default wakeWordClient;

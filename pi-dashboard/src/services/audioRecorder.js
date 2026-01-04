/**
 * Audio Recorder Service for Pi Dashboard
 * Provides microphone recording with Voice Activity Detection (VAD)
 * Ported from webapp TypeScript implementation
 */

class AudioRecorderService {
  constructor() {
    this.mediaRecorder = null;
    this.audioContext = null;
    this.analyser = null;
    this.stream = null;
    this.vadInterval = null;
    this.silenceStartTime = null;
    this.onSilenceCallback = null;
    this.audioChunks = [];
    this.lastMeteringLog = null;

    // VAD constants (matching iOS/webapp implementation)
    this.SILENCE_THRESHOLD_DB = -35;
    this.SPEECH_THRESHOLD_DB = -30;
    this.SILENCE_DURATION_MS = 1500;
    this.VAD_POLL_INTERVAL_MS = 100;
  }

  /**
   * Initialize audio permissions and context
   * @returns {Promise<boolean>}
   */
  async initialize() {
    try {
      console.log('[AudioRecorder] Requesting microphone permission...');

      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000,
        }
      });

      // Create audio context for metering
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.3;

      // Connect stream to analyser
      const source = this.audioContext.createMediaStreamSource(this.stream);
      source.connect(this.analyser);

      console.log('[AudioRecorder] Initialized successfully');
      return true;
    } catch (error) {
      console.error('[AudioRecorder] Initialization error:', error);
      return false;
    }
  }

  /**
   * Start recording with VAD (Voice Activity Detection)
   * @param {Function} onSilenceDetected Callback when silence is detected
   */
  async startRecording(onSilenceDetected) {
    try {
      console.log('[AudioRecorder] Starting recording with VAD...');

      // Initialize if not already done
      if (!this.stream) {
        const initialized = await this.initialize();
        if (!initialized) {
          throw new Error('Failed to initialize audio');
        }
      }

      // Stop any existing recording
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
        this.mediaRecorder.stop();
      }

      this.onSilenceCallback = onSilenceDetected;
      this.silenceStartTime = null;
      this.audioChunks = [];

      // Create new MediaRecorder
      // Try webm first (Chrome/Firefox), fall back to mp4 (Safari)
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
        mimeType = 'audio/mp4';
      }

      this.mediaRecorder = new MediaRecorder(this.stream, { mimeType });

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      // Request data every 100ms for smoother recording
      this.mediaRecorder.start(100);

      // Start VAD polling
      this.startVADPolling();

      console.log('[AudioRecorder] Recording started with VAD');
    } catch (error) {
      console.error('[AudioRecorder] Failed to start recording:', error);
      throw error;
    }
  }

  /**
   * Poll for audio metering to detect silence
   */
  startVADPolling() {
    console.log('[VAD] Starting VAD polling...');

    this.vadInterval = setInterval(() => {
      if (!this.analyser || !this.mediaRecorder || this.mediaRecorder.state !== 'recording') {
        console.log('[VAD] Exiting: analyser or recorder not active');
        this.stopVADPolling();
        return;
      }

      // Get frequency data
      const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
      this.analyser.getByteFrequencyData(dataArray);

      // Calculate RMS and convert to dB
      const sum = dataArray.reduce((acc, val) => acc + val * val, 0);
      const rms = Math.sqrt(sum / dataArray.length);

      // Convert 0-255 range to dB (approximate)
      // 0 -> -160dB (silence), 255 -> 0dB (max)
      const metering = rms === 0 ? -160 : 20 * Math.log10(rms / 255);

      const isSilent = metering < this.SILENCE_THRESHOLD_DB;

      // Log periodically (every 500ms)
      if (!this.lastMeteringLog || Date.now() - this.lastMeteringLog > 500) {
        console.log('[VAD] Metering:', metering.toFixed(1), 'dB, Silent:', isSilent);
        this.lastMeteringLog = Date.now();
      }

      if (isSilent) {
        if (this.silenceStartTime === null) {
          this.silenceStartTime = Date.now();
        } else {
          const silenceDuration = Date.now() - this.silenceStartTime;
          if (silenceDuration >= this.SILENCE_DURATION_MS) {
            console.log('[VAD] Silence detected for', silenceDuration, 'ms - stopping');
            this.stopVADPolling();
            if (this.onSilenceCallback) {
              this.onSilenceCallback();
            }
          }
        }
      } else {
        // Only reset silence timer if significant sound is detected (actual speech)
        if (metering > this.SPEECH_THRESHOLD_DB) {
          this.silenceStartTime = null;
        }
      }
    }, this.VAD_POLL_INTERVAL_MS);
  }

  /**
   * Stop VAD polling
   */
  stopVADPolling() {
    if (this.vadInterval !== null) {
      clearInterval(this.vadInterval);
      this.vadInterval = null;
    }
  }

  /**
   * Stop recording and return the audio blob
   * @returns {Promise<Blob|null>}
   */
  async stopRecording() {
    try {
      this.stopVADPolling();

      if (!this.mediaRecorder || this.mediaRecorder.state === 'inactive') {
        console.log('[AudioRecorder] No active recording');
        return null;
      }

      console.log('[AudioRecorder] Stopping recording...');

      // Clear VAD callback
      this.onSilenceCallback = null;
      this.silenceStartTime = null;

      return new Promise((resolve) => {
        if (!this.mediaRecorder) {
          resolve(null);
          return;
        }

        this.mediaRecorder.onstop = () => {
          const mimeType = this.mediaRecorder?.mimeType || 'audio/webm';
          const audioBlob = new Blob(this.audioChunks, { type: mimeType });
          this.audioChunks = [];
          console.log('[AudioRecorder] Recording stopped, blob size:', audioBlob.size);
          resolve(audioBlob);
        };

        this.mediaRecorder.stop();
      });
    } catch (error) {
      console.error('[AudioRecorder] Failed to stop recording:', error);
      this.audioChunks = [];
      this.onSilenceCallback = null;
      this.stopVADPolling();
      return null;
    }
  }

  /**
   * Get current audio amplitude (0-1) for visualization
   * @returns {number}
   */
  getAmplitude() {
    if (!this.analyser) return 0;

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);

    const sum = dataArray.reduce((acc, val) => acc + val, 0);
    const average = sum / dataArray.length;

    // Normalize to 0-1 range with some sensitivity adjustment
    return Math.min(1, average / 128);
  }

  /**
   * Start continuous recording WITHOUT VAD (for long-form dictation)
   * Recording continues until manually stopped
   */
  async startContinuousRecording() {
    try {
      console.log('[AudioRecorder] Starting continuous recording (no VAD)...');

      // Initialize if not already done
      if (!this.stream) {
        const initialized = await this.initialize();
        if (!initialized) {
          throw new Error('Failed to initialize audio');
        }
      }

      // Stop any existing recording
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
        this.mediaRecorder.stop();
      }

      // No VAD callback for continuous mode
      this.onSilenceCallback = null;
      this.silenceStartTime = null;
      this.audioChunks = [];

      // Create new MediaRecorder
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
        mimeType = 'audio/mp4';
      }

      this.mediaRecorder = new MediaRecorder(this.stream, { mimeType });

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      // Request data every 1 second for continuous recording
      this.mediaRecorder.start(1000);

      console.log('[AudioRecorder] Continuous recording started');
    } catch (error) {
      console.error('[AudioRecorder] Failed to start continuous recording:', error);
      throw error;
    }
  }

  /**
   * Check if currently recording
   * @returns {boolean}
   */
  isRecording() {
    return this.mediaRecorder?.state === 'recording';
  }

  /**
   * Cleanup resources
   */
  cleanup() {
    this.stopVADPolling();

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.mediaRecorder = null;

    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.analyser = null;
    this.audioChunks = [];
    this.onSilenceCallback = null;
    this.silenceStartTime = null;

    console.log('[AudioRecorder] Cleaned up');
  }
}

// Export singleton instance
export const audioRecorderService = new AudioRecorderService();
export default audioRecorderService;

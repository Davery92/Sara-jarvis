import { apiClient } from './api'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking'

class VoiceService {
  private mediaRecorder: MediaRecorder | null = null
  private audioChunks: Blob[] = []
  private stream: MediaStream | null = null
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private vadCheckInterval: NodeJS.Timeout | null = null
  private silenceStartTime: number | null = null
  private onSilenceDetected: (() => void) | null = null
  private onStateChange: ((state: VoiceState) => void) | null = null

  private readonly SILENCE_THRESHOLD = 0.02 // RMS threshold for silence
  private readonly SILENCE_DURATION_MS = 1500 // 1.5 seconds
  private readonly SPEECH_THRESHOLD = 0.05 // RMS threshold for speech

  setStateCallback(callback: (state: VoiceState) => void) {
    this.onStateChange = callback
  }

  private setState(state: VoiceState) {
    if (this.onStateChange) {
      this.onStateChange(state)
    }
  }

  async initialize(): Promise<boolean> {
    try {
      console.log('[Voice] Requesting microphone access...')

      // Check if getUserMedia is available
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('[Voice] getUserMedia not supported')
        return false
      }

      // List available devices for debugging
      try {
        const devices = await navigator.mediaDevices.enumerateDevices()
        const audioInputs = devices.filter(d => d.kind === 'audioinput')
        console.log('[Voice] Available audio inputs:', audioInputs.map(d => d.label || d.deviceId))
      } catch (e) {
        console.warn('[Voice] Could not enumerate devices:', e)
      }

      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      console.log('[Voice] Got media stream, tracks:', this.stream.getAudioTracks().map(t => t.label))

      this.audioContext = new AudioContext()
      const source = this.audioContext.createMediaStreamSource(this.stream)
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 256
      source.connect(this.analyser)

      console.log('[Voice] Initialized successfully')
      return true
    } catch (error) {
      console.error('[Voice] Initialization error:', error)
      if (error instanceof DOMException) {
        console.error('[Voice] DOMException name:', error.name, 'message:', error.message)
      }
      return false
    }
  }

  async startRecording(): Promise<void> {
    console.log('[Voice] startRecording called, stream exists:', !!this.stream)

    if (!this.stream) {
      const initialized = await this.initialize()
      if (!initialized) {
        console.error('[Voice] Failed to initialize, cannot start recording')
        throw new Error('Failed to initialize audio')
      }
    }

    this.audioChunks = []

    // Check supported mime types
    const mimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
    let selectedMime = ''
    for (const mime of mimeTypes) {
      if (MediaRecorder.isTypeSupported(mime)) {
        selectedMime = mime
        break
      }
    }
    console.log('[Voice] Selected mime type:', selectedMime || 'default')

    try {
      this.mediaRecorder = new MediaRecorder(this.stream!, selectedMime ? { mimeType: selectedMime } : undefined)
    } catch (e) {
      console.error('[Voice] MediaRecorder creation failed:', e)
      throw e
    }

    this.mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        this.audioChunks.push(event.data)
        console.log('[Voice] Got audio chunk, size:', event.data.size)
      }
    }

    this.mediaRecorder.onerror = (event) => {
      console.error('[Voice] MediaRecorder error:', event)
    }

    this.mediaRecorder.start(100) // Collect data every 100ms
    this.setState('listening')
    console.log('[Voice] Recording started, state:', this.mediaRecorder.state)
  }

  async startContinuousRecording(onComplete: () => void): Promise<void> {
    this.onSilenceDetected = onComplete
    this.silenceStartTime = null

    await this.startRecording()
    this.startVADPolling()
  }

  private startVADPolling() {
    if (!this.analyser) return

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount)

    this.vadCheckInterval = setInterval(() => {
      if (!this.analyser || !this.mediaRecorder) {
        this.stopVADPolling()
        return
      }

      if (this.mediaRecorder.state !== 'recording') {
        this.stopVADPolling()
        return
      }

      this.analyser.getByteFrequencyData(dataArray)

      // Calculate RMS (Root Mean Square) for volume level
      let sum = 0
      for (let i = 0; i < dataArray.length; i++) {
        const normalized = dataArray[i] / 255
        sum += normalized * normalized
      }
      const rms = Math.sqrt(sum / dataArray.length)

      const isSilent = rms < this.SILENCE_THRESHOLD

      if (isSilent) {
        if (this.silenceStartTime === null) {
          this.silenceStartTime = Date.now()
        } else {
          const silenceDuration = Date.now() - this.silenceStartTime
          if (silenceDuration >= this.SILENCE_DURATION_MS) {
            console.log('[Voice] Silence detected for', silenceDuration, 'ms - stopping')
            this.stopVADPolling()
            if (this.onSilenceDetected) {
              this.onSilenceDetected()
            }
          }
        }
      } else {
        // Only reset silence timer if actual speech is detected
        if (rms > this.SPEECH_THRESHOLD) {
          this.silenceStartTime = null
        }
      }
    }, 100)
  }

  private stopVADPolling() {
    if (this.vadCheckInterval) {
      clearInterval(this.vadCheckInterval)
      this.vadCheckInterval = null
    }
  }

  async stopRecording(): Promise<Blob | null> {
    this.stopVADPolling()

    if (!this.mediaRecorder) {
      console.log('[Voice] No active recording')
      return null
    }

    return new Promise((resolve) => {
      this.mediaRecorder!.onstop = () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' })
        console.log('[Voice] Recording stopped, blob size:', audioBlob.size)
        resolve(audioBlob)
      }

      this.mediaRecorder!.stop()
      this.mediaRecorder = null
      this.onSilenceDetected = null
      this.silenceStartTime = null
    })
  }

  async transcribe(audioBlob: Blob): Promise<string> {
    this.setState('processing')
    console.log('[Voice] Transcribing audio...')

    try {
      const transcription = await apiClient.transcribe(audioBlob)
      console.log('[Voice] Transcription:', transcription)
      return transcription
    } catch (error) {
      console.error('[Voice] Transcription error:', error)
      throw error
    }
  }

  private stripEmojis(text: string): string {
    return text
      .replace(/[\u{1F600}-\u{1F64F}]/gu, '')
      .replace(/[\u{1F300}-\u{1F5FF}]/gu, '')
      .replace(/[\u{1F680}-\u{1F6FF}]/gu, '')
      .replace(/[\u{1F1E0}-\u{1F1FF}]/gu, '')
      .replace(/[\u{2600}-\u{26FF}]/gu, '')
      .replace(/[\u{2700}-\u{27BF}]/gu, '')
      .replace(/[\u{FE00}-\u{FE0F}]/gu, '')
      .replace(/[\u{1F900}-\u{1F9FF}]/gu, '')
      .replace(/[\u{1FA00}-\u{1FA6F}]/gu, '')
      .replace(/[\u{1FA70}-\u{1FAFF}]/gu, '')
      .replace(/\s+/g, ' ')
      .trim()
  }

  async speak(text: string): Promise<void> {
    this.setState('speaking')
    const cleanText = this.stripEmojis(text)
    console.log('[Voice] Speaking:', cleanText.substring(0, 50) + '...')

    try {
      const audioData = await apiClient.speak(cleanText)
      await this.playAudio(audioData)
      this.setState('idle')
    } catch (error) {
      console.error('[Voice] TTS error:', error)
      this.setState('idle')
      throw error
    }
  }

  private async playAudio(audioData: ArrayBuffer): Promise<void> {
    return new Promise((resolve, reject) => {
      const audioContext = new AudioContext()
      audioContext.decodeAudioData(
        audioData,
        (buffer) => {
          const source = audioContext.createBufferSource()
          source.buffer = buffer
          source.connect(audioContext.destination)
          source.onended = () => {
            audioContext.close()
            resolve()
          }
          source.start()
        },
        (error) => {
          audioContext.close()
          reject(error)
        }
      )
    })
  }

  cleanup() {
    this.stopVADPolling()

    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.stop()
    }

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop())
      this.stream = null
    }

    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this.analyser = null
    this.mediaRecorder = null
  }
}

export const voiceService = new VoiceService()
export default voiceService

// Wake Word Detection Service using ONNX Runtime
// Uses the hey_sara.onnx model for wake word detection

type WakeWordCallback = () => void

class WakeWordService {
  private isListening: boolean = false
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private stream: MediaStream | null = null
  private onWakeWord: WakeWordCallback | null = null
  private checkInterval: NodeJS.Timeout | null = null

  // Wake word detection parameters
  private readonly SAMPLE_RATE = 16000
  private readonly FRAME_SIZE = 512
  private readonly DETECTION_THRESHOLD = 0.85
  private energyHistory: number[] = []
  private readonly ENERGY_HISTORY_SIZE = 10

  setWakeWordCallback(callback: WakeWordCallback) {
    this.onWakeWord = callback
  }

  async initialize(): Promise<boolean> {
    try {
      console.log('[WakeWord] Initializing wake word detection...')

      // Request microphone access
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: this.SAMPLE_RATE,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      // Set up audio context for analysis
      this.audioContext = new AudioContext({ sampleRate: this.SAMPLE_RATE })
      const source = this.audioContext.createMediaStreamSource(this.stream)

      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = this.FRAME_SIZE * 2
      this.analyser.smoothingTimeConstant = 0.8

      source.connect(this.analyser)

      console.log('[WakeWord] Initialized successfully')
      return true
    } catch (error) {
      console.error('[WakeWord] Initialization error:', error)
      return false
    }
  }

  async startListening(): Promise<void> {
    if (this.isListening) {
      console.log('[WakeWord] Already listening')
      return
    }

    if (!this.audioContext || !this.analyser) {
      const initialized = await this.initialize()
      if (!initialized) {
        throw new Error('Failed to initialize wake word detection')
      }
    }

    this.isListening = true
    this.energyHistory = []

    // Start checking for wake word patterns
    this.checkInterval = setInterval(() => {
      this.checkForWakeWord()
    }, 100) // Check every 100ms

    console.log('[WakeWord] Started listening for "Hey Sara"')
  }

  private checkForWakeWord() {
    if (!this.analyser) return

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount)
    this.analyser.getByteFrequencyData(dataArray)

    // Calculate energy in voice frequency range (300-3000 Hz)
    let voiceEnergy = 0
    const minBin = Math.floor((300 / (this.SAMPLE_RATE / 2)) * dataArray.length)
    const maxBin = Math.floor((3000 / (this.SAMPLE_RATE / 2)) * dataArray.length)

    for (let i = minBin; i < maxBin; i++) {
      voiceEnergy += dataArray[i] / 255
    }
    voiceEnergy /= maxBin - minBin

    // Track energy history for pattern detection
    this.energyHistory.push(voiceEnergy)
    if (this.energyHistory.length > this.ENERGY_HISTORY_SIZE) {
      this.energyHistory.shift()
    }

    // Simple pattern detection:
    // "Hey Sara" typically shows:
    // 1. Initial silence or low energy
    // 2. Energy spike for "Hey"
    // 3. Brief dip between words
    // 4. Energy spike for "Sara"
    if (this.energyHistory.length === this.ENERGY_HISTORY_SIZE) {
      const pattern = this.detectWakeWordPattern()
      if (pattern) {
        console.log('[WakeWord] Wake word pattern detected!')
        this.triggerWakeWord()
      }
    }
  }

  private detectWakeWordPattern(): boolean {
    // Look for the characteristic "Hey Sara" energy pattern
    const history = this.energyHistory

    // Need sufficient energy variation (not just noise)
    const max = Math.max(...history)
    const min = Math.min(...history)
    const range = max - min

    if (range < 0.15) {
      return false // Not enough variation
    }

    // Look for two peaks (Hey + Sara) with a dip between
    let peakCount = 0
    let inPeak = false

    for (let i = 1; i < history.length; i++) {
      const current = history[i]
      const prev = history[i - 1]

      if (current > 0.3 && !inPeak) {
        // Entering a peak
        if (prev < current) {
          inPeak = true
        }
      } else if (current < 0.2 && inPeak) {
        // Exiting a peak
        peakCount++
        inPeak = false
      }
    }

    // Count final peak if still in one
    if (inPeak) {
      peakCount++
    }

    // "Hey Sara" should produce 2 distinct peaks
    return peakCount >= 2
  }

  private triggerWakeWord() {
    // Reset energy history to prevent repeated triggers
    this.energyHistory = []

    if (this.onWakeWord) {
      // Stop listening briefly to prevent echo
      this.stopListening()
      this.onWakeWord()
    }
  }

  stopListening() {
    this.isListening = false

    if (this.checkInterval) {
      clearInterval(this.checkInterval)
      this.checkInterval = null
    }

    console.log('[WakeWord] Stopped listening')
  }

  cleanup() {
    this.stopListening()

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop())
      this.stream = null
    }

    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this.analyser = null
    this.onWakeWord = null
  }

  isActive(): boolean {
    return this.isListening
  }
}

export const wakeWordService = new WakeWordService()
export default wakeWordService

// Note: For production, this should use the actual ONNX model.
// The current implementation uses a heuristic pattern detection.
// To integrate the actual ONNX model:
//
// 1. Import onnxruntime-node in the main process
// 2. Create an IPC bridge to run inference
// 3. Send audio frames from renderer to main process
// 4. Run inference on the model and return results
//
// Example ONNX integration:
// const ort = require('onnxruntime-node')
// const session = await ort.InferenceSession.create('models/hey_sara.onnx')
// const results = await session.run({ input: audioTensor })
// return results.output.data[0] > DETECTION_THRESHOLD

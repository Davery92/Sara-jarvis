/**
 * AudioWorklet processor for wake word detection
 * This runs in a separate audio thread for better performance
 */
class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 2048;  // Smaller buffer for faster response
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
    this.processCount = 0;
    this.sendCount = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];

    this.processCount++;

    // Log first few calls to verify we're receiving audio
    if (this.processCount <= 3) {
      this.port.postMessage({
        type: 'debug',
        message: `process #${this.processCount}, inputs: ${inputs.length}, channels: ${input?.length || 0}, samples: ${input?.[0]?.length || 0}`
      });
    }

    if (!input || !input[0]) {
      if (this.processCount <= 5) {
        this.port.postMessage({
          type: 'debug',
          message: `process #${this.processCount} - NO INPUT DATA`
        });
      }
      return true;
    }

    const samples = input[0];

    // Accumulate samples into buffer
    for (let i = 0; i < samples.length; i++) {
      this.buffer[this.bufferIndex++] = samples[i];

      // When buffer is full, send it to main thread
      if (this.bufferIndex >= this.bufferSize) {
        this.sendCount++;

        // Convert float32 to int16 for transmission
        const int16Data = new Int16Array(this.bufferSize);
        for (let j = 0; j < this.bufferSize; j++) {
          const s = Math.max(-1, Math.min(1, this.buffer[j]));
          int16Data[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        // Log first few sends
        if (this.sendCount <= 3) {
          this.port.postMessage({
            type: 'debug',
            message: `SENDING audio chunk #${this.sendCount}, size: ${int16Data.length}`
          });
        }

        // Send to main thread (clone buffer instead of transfer to avoid issues)
        this.port.postMessage({
          type: 'audio',
          samples: int16Data.buffer.slice(0)  // Clone the buffer
        });

        this.bufferIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);

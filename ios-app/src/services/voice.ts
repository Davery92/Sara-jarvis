import * as Speech from 'expo-speech';
import { Audio } from 'expo-av';
import { apiClient } from './api';

class VoiceService {
  private recording: Audio.Recording | null = null;
  private isListening: boolean = false;
  private vadCheckInterval: NodeJS.Timeout | null = null;
  private silenceStartTime: number | null = null;
  private readonly SILENCE_THRESHOLD_MS = 1500; // Stop after 1.5 seconds of silence
  private onSilenceDetected: (() => void) | null = null;

  /**
   * Initialize audio permissions for recording
   */
  async initialize(): Promise<boolean> {
    try {
      console.log('[Voice] Requesting audio permissions...');
      const { status } = await Audio.requestPermissionsAsync();

      if (status !== 'granted') {
        console.log('[Voice] Permission denied');
        return false;
      }

      // Configure audio mode for recording and playback
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
        interruptionModeIOS: 1, // Mix with others
        interruptionModeAndroid: 1,
      });

      console.log('[Voice] Initialized successfully');
      return true;
    } catch (error) {
      console.error('[Voice] Initialization error:', error);
      return false;
    }
  }

  /**
   * Start recording audio for speech recognition
   */
  async startRecording(): Promise<void> {
    try {
      console.log('[Voice] Starting recording...');

      // Stop any existing recording
      if (this.recording) {
        await this.stopRecording();
      }

      // Create new recording with optimized settings for speech
      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );

      this.recording = recording;
      this.isListening = true;
      console.log('[Voice] Recording started');
    } catch (error) {
      console.error('[Voice] Failed to start recording:', error);
      throw error;
    }
  }

  /**
   * Start continuous recording with VAD (Voice Activity Detection)
   * Automatically stops after detecting silence
   */
  async startContinuousRecording(onComplete: () => void): Promise<void> {
    try {
      console.log('[Voice] Starting continuous recording with VAD...');

      // Stop any existing recording
      if (this.recording) {
        await this.stopRecording();
      }

      this.onSilenceDetected = onComplete;
      this.silenceStartTime = null;

      // Create recording with metering enabled
      const recordingOptions = {
        ...Audio.RecordingOptionsPresets.HIGH_QUALITY,
        android: {
          ...Audio.RecordingOptionsPresets.HIGH_QUALITY.android,
          meteringEnabled: true,
        },
        ios: {
          ...Audio.RecordingOptionsPresets.HIGH_QUALITY.ios,
          meteringEnabled: true,
        },
      };

      const { recording } = await Audio.Recording.createAsync(recordingOptions);

      this.recording = recording;
      this.isListening = true;

      // Start polling for metering data to detect silence
      this.startVADPolling();

      console.log('[Voice] Continuous recording started with VAD');
    } catch (error) {
      console.error('[Voice] Failed to start continuous recording:', error);
      throw error;
    }
  }

  /**
   * Poll for audio metering to detect silence
   */
  private startVADPolling() {
    // Poll every 100ms for metering data
    this.vadCheckInterval = setInterval(async () => {
      if (!this.recording || !this.isListening) {
        this.stopVADPolling();
        return;
      }

      try {
        const status = await this.recording.getStatusAsync();

        if (!status.isRecording) {
          this.stopVADPolling();
          return;
        }

        // Check metering level (ranges from -160 to 0)
        const metering = status.metering ?? -160;
        const SILENCE_THRESHOLD = -35; // dB threshold for silence (speech is usually > -30 dB)
        const isSilent = metering < SILENCE_THRESHOLD;

        console.log('[VAD] Metering:', metering.toFixed(1), 'dB, Silent:', isSilent);

        if (isSilent) {
          if (this.silenceStartTime === null) {
            this.silenceStartTime = Date.now();
          } else {
            const silenceDuration = Date.now() - this.silenceStartTime;
            if (silenceDuration >= this.SILENCE_THRESHOLD_MS) {
              console.log('[Voice] Silence detected for', silenceDuration, 'ms - stopping');
              this.stopVADPolling();
              if (this.onSilenceDetected) {
                this.onSilenceDetected();
              }
            }
          }
        } else {
          // Only reset silence timer if significant sound is detected (actual speech)
          // This prevents background noise from constantly resetting the timer
          if (metering > -30) { // Only speech (louder sounds) resets the timer
            this.silenceStartTime = null;
          }
        }
      } catch (error) {
        console.error('[VAD] Error checking status:', error);
      }
    }, 100); // Check every 100ms
  }

  /**
   * Stop VAD polling
   */
  private stopVADPolling() {
    if (this.vadCheckInterval) {
      clearInterval(this.vadCheckInterval);
      this.vadCheckInterval = null;
    }
  }

  /**
   * Stop recording and return the audio URI
   */
  async stopRecording(): Promise<string | null> {
    try {
      // Stop VAD polling first
      this.stopVADPolling();

      if (!this.recording) {
        console.log('[Voice] No active recording');
        return null;
      }

      console.log('[Voice] Stopping recording...');

      // Clear VAD callback
      this.onSilenceDetected = null;
      this.silenceStartTime = null;

      await this.recording.stopAndUnloadAsync();

      const uri = this.recording.getURI();
      this.recording = null;
      this.isListening = false;

      console.log('[Voice] Recording stopped, URI:', uri);
      return uri;
    } catch (error) {
      console.error('[Voice] Failed to stop recording:', error);
      this.recording = null;
      this.isListening = false;
      this.onSilenceDetected = null;
      this.stopVADPolling();
      return null;
    }
  }

  /**
   * Transcribe audio using backend Whisper API
   */
  async transcribeAudio(audioUri: string): Promise<string> {
    try {
      console.log('[Voice] Transcribing audio via Whisper:', audioUri);

      // Create FormData for file upload
      const formData = new FormData();
      formData.append('audio', {
        uri: audioUri,
        type: 'audio/m4a',
        name: 'recording.m4a',
      } as any);

      // Upload to backend for transcription
      const token = await apiClient.getToken();
      const response = await fetch(
        `${apiClient.baseURL}/api/voice-agent/transcribe`,
        {
          method: 'POST',
          headers: {
            'Authorization': token ? `Bearer ${token}` : '',
          },
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(`Transcription failed: ${response.status}`);
      }

      const data = await response.json();
      const transcription = data.transcription || data.text || '';

      console.log('[Voice] Transcription:', transcription);
      return transcription;
    } catch (error) {
      console.error('[Voice] Transcription error:', error);
      throw error;
    }
  }

  /**
   * Strip emojis and other non-speech characters from text
   */
  private stripEmojis(text: string): string {
    // Remove emojis, symbols, and other pictographic characters
    return text
      .replace(/[\u{1F600}-\u{1F64F}]/gu, '') // Emoticons
      .replace(/[\u{1F300}-\u{1F5FF}]/gu, '') // Misc Symbols and Pictographs
      .replace(/[\u{1F680}-\u{1F6FF}]/gu, '') // Transport and Map
      .replace(/[\u{1F1E0}-\u{1F1FF}]/gu, '') // Flags
      .replace(/[\u{2600}-\u{26FF}]/gu, '')   // Misc symbols
      .replace(/[\u{2700}-\u{27BF}]/gu, '')   // Dingbats
      .replace(/[\u{FE00}-\u{FE0F}]/gu, '')   // Variation Selectors
      .replace(/[\u{1F900}-\u{1F9FF}]/gu, '') // Supplemental Symbols and Pictographs
      .replace(/[\u{1FA00}-\u{1FA6F}]/gu, '') // Chess Symbols
      .replace(/[\u{1FA70}-\u{1FAFF}]/gu, '') // Symbols and Pictographs Extended-A
      .replace(/\s+/g, ' ')                    // Normalize whitespace
      .trim();
  }

  /**
   * Split text into chunks for TTS processing
   * Splits by paragraphs, sentences, or max length
   */
  private splitTextIntoChunks(text: string, maxChunkLength: number = 500): string[] {
    const chunks: string[] = [];

    // First split by double newlines (paragraphs)
    const paragraphs = text.split(/\n\n+/);

    for (const paragraph of paragraphs) {
      const trimmedParagraph = paragraph.trim();
      if (!trimmedParagraph) continue;

      if (trimmedParagraph.length <= maxChunkLength) {
        chunks.push(trimmedParagraph);
      } else {
        // Split long paragraphs by sentences
        const sentences = trimmedParagraph.match(/[^.!?]+[.!?]+/g) || [trimmedParagraph];
        let currentChunk = '';

        for (const sentence of sentences) {
          const trimmedSentence = sentence.trim();
          if ((currentChunk + ' ' + trimmedSentence).length <= maxChunkLength) {
            currentChunk = currentChunk ? currentChunk + ' ' + trimmedSentence : trimmedSentence;
          } else {
            if (currentChunk) {
              chunks.push(currentChunk);
            }
            // If single sentence is too long, split by words
            if (trimmedSentence.length > maxChunkLength) {
              const words = trimmedSentence.split(' ');
              currentChunk = '';
              for (const word of words) {
                if ((currentChunk + ' ' + word).length <= maxChunkLength) {
                  currentChunk = currentChunk ? currentChunk + ' ' + word : word;
                } else {
                  if (currentChunk) chunks.push(currentChunk);
                  currentChunk = word;
                }
              }
            } else {
              currentChunk = trimmedSentence;
            }
          }
        }
        if (currentChunk) {
          chunks.push(currentChunk);
        }
      }
    }

    return chunks;
  }

  /**
   * Speak a single chunk of text
   */
  private async speakChunk(text: string): Promise<void> {
    try {
      console.log('[Voice] Fetching TTS audio from backend...');
      const token = await apiClient.getToken();
      const response = await fetch(
        `${apiClient.baseURL}/api/voice-agent/speak`,
        {
          method: 'POST',
          headers: {
            'Authorization': token ? `Bearer ${token}` : '',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ text }),
        }
      );

      if (!response.ok) {
        throw new Error(`TTS failed: ${response.status}`);
      }

      console.log('[Voice] Got TTS response, creating audio blob...');
      // Get the audio blob
      const audioBlob = await response.blob();
      console.log('[Voice] Audio blob size:', audioBlob.size, 'type:', audioBlob.type);

      // Create a temporary file URI
      const reader = new FileReader();
      reader.readAsDataURL(audioBlob);

      await new Promise((resolve, reject) => {
        reader.onloadend = async () => {
          try {
            const base64Audio = reader.result as string;
            console.log('[Voice] Converted to base64, length:', base64Audio.length);

            // Create sound object and play
            console.log('[Voice] Creating Audio.Sound object...');
            const { sound } = await Audio.Sound.createAsync(
              { uri: base64Audio },
              { shouldPlay: true }
            );

            console.log('[Voice] Audio sound created, starting playback...');

            // Wait for playback to finish
            sound.setOnPlaybackStatusUpdate(async (status) => {
              if (status.isLoaded && status.didJustFinish) {
                console.log('[Voice] Playback finished');
                await sound.unloadAsync();
                resolve(true);
              }
              if (status.isLoaded === false && 'error' in status) {
                console.error('[Voice] Audio playback error:', status.error);
                reject(new Error(status.error));
              }
            });
          } catch (error) {
            console.error('[Voice] Chunk playback error:', error);
            reject(error);
          }
        };
        reader.onerror = (error) => {
          console.error('[Voice] FileReader error:', error);
          reject(error);
        };
      });
    } catch (error) {
      console.error('[Voice] speakChunk error:', error);
      throw error;
    }
  }

  /**
   * Speak text using backend TTS (Orpheus)
   * Automatically chunks long text to avoid timeouts
   */
  async speak(text: string): Promise<void> {
    try {
      // Strip emojis from text before sending to TTS
      const cleanText = this.stripEmojis(text);
      console.log('[Voice] Speaking via Orpheus TTS (emojis stripped):', cleanText);

      // Split into chunks to avoid timeout
      const chunks = this.splitTextIntoChunks(cleanText);
      console.log(`[Voice] Split into ${chunks.length} chunks for TTS`);

      // Set audio to use speaker (once at the start)
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
      });

      // Process each chunk sequentially
      for (let i = 0; i < chunks.length; i++) {
        console.log(`[Voice] Processing chunk ${i + 1}/${chunks.length}: "${chunks[i].substring(0, 50)}..."`);
        await this.speakChunk(chunks[i]);
      }

      console.log('[Voice] All chunks finished, resetting audio mode for recording');

      // Reset audio mode to allow recording again
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
        interruptionModeIOS: 1,
        interruptionModeAndroid: 1,
      });

      console.log('[Voice] Audio mode reset, ready for recording');

    } catch (error) {
      console.error('[Voice] Failed to speak:', error);
      throw error;
    }
  }

  /**
   * Stop speaking
   */
  async stopSpeaking(): Promise<void> {
    try {
      await Speech.stop();
      console.log('[Voice] Speech stopped');
    } catch (error) {
      console.error('[Voice] Failed to stop speech:', error);
    }
  }

  /**
   * Check if currently speaking
   */
  async isSpeaking(): Promise<boolean> {
    try {
      return await Speech.isSpeakingAsync();
    } catch {
      return false;
    }
  }

  /**
   * Get recording status
   */
  async getRecordingStatus() {
    if (!this.recording) {
      return null;
    }
    return await this.recording.getStatusAsync();
  }

  /**
   * Cleanup resources
   */
  async cleanup(): Promise<void> {
    if (this.recording) {
      await this.stopRecording();
    }
    await this.stopSpeaking();
  }
}

// Export singleton instance
export const voiceService = new VoiceService();
export default voiceService;

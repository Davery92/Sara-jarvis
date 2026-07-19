import * as Speech from 'expo-speech';
import { Audio, InterruptionModeIOS, InterruptionModeAndroid } from 'expo-av';
import { apiClient } from './api';

class VoiceService {
  private recording: Audio.Recording | null = null;
  private currentSound: Audio.Sound | null = null;
  private isListening: boolean = false;
  private vadCheckInterval: NodeJS.Timeout | null = null;
  private silenceStartTime: number | null = null;
  private readonly SILENCE_THRESHOLD_MS = 1500; // Stop after 1.5 seconds of silence
  private onSilenceDetected: (() => void) | null = null;
  private lastMeteringLog: number | null = null;
  // Set true by stopSpeaking() to abort the chunk loop in speak() so it never
  // plays chunk i+1 after a stop. Reset at the start of each speak().
  private speakCancelled: boolean = false;
  // Settle callback for the chunk currently playing — lets stopSpeaking()
  // resolve the in-flight playChunkAudio() promise immediately instead of
  // waiting for a `didJustFinish` that may never come.
  private currentChunkSettle: (() => void) | null = null;

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
        // Duck other audio (music/podcasts) while Sara records rather than
        // taking exclusive control — the old `1` was labelled "mix" but 1 is
        // actually DoNotMix, so intent and value disagreed.
        interruptionModeIOS: InterruptionModeIOS.DuckOthers,
        interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
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
      console.log('[Voice] About to call startVADPolling()...');
      this.startVADPolling();
      console.log('[Voice] startVADPolling() returned');

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
    try {
      console.log('[VAD] Starting VAD polling...');
      console.log('[VAD] this.recording:', !!this.recording, 'this.isListening:', this.isListening);
    } catch (e) {
      console.error('[VAD] Error in startVADPolling preamble:', e);
    }
    // Poll every 100ms for metering data
    this.vadCheckInterval = setInterval(async () => {
      if (!this.recording || !this.isListening) {
        console.log('[VAD] Exiting: recording=', !!this.recording, 'isListening=', this.isListening);
        this.stopVADPolling();
        return;
      }

      try {
        const status = await this.recording.getStatusAsync();

        if (!status.isRecording) {
          console.log('[VAD] Recording stopped, exiting polling');
          this.stopVADPolling();
          return;
        }

        // Check metering level (ranges from -160 to 0)
        // Note: metering is undefined if isMeteringEnabled was false in recording options
        const metering = status.metering ?? -160;
        const SILENCE_THRESHOLD = -35; // dB threshold for silence (speech is usually > -30 dB)
        const isSilent = metering < SILENCE_THRESHOLD;

        // Only log periodically to avoid spam (every 500ms)
        if (!this.lastMeteringLog || Date.now() - this.lastMeteringLog > 500) {
          console.log('[VAD] Metering:', metering.toFixed(1), 'dB, Silent:', isSilent, 'isMeteringEnabled:', status.metering !== undefined);
          this.lastMeteringLog = Date.now();
        }

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
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const response = await fetch(`${apiClient.baseURL}/api/voice-agent/transcribe`, {
        method: 'POST',
        headers,
        body: formData,
      });

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
   * Fetch TTS audio for one chunk and return it as a base64 data URI.
   * Kept separate from playback so speak() can prefetch chunk i+1 while
   * chunk i is still playing (no dead air between chunks).
   */
  private async fetchChunkAudio(text: string): Promise<string> {
    const token = await apiClient.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${apiClient.baseURL}/api/voice-agent/speak`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ text }),
    });

    if (!response.ok) {
      throw new Error(`TTS failed: ${response.status}`);
    }

    const audioBlob = await response.blob();
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error ?? new Error('FileReader error'));
      reader.readAsDataURL(audioBlob);
    });
  }

  /**
   * Play one already-fetched chunk of audio and resolve when it finishes.
   *
   * The promise ALWAYS settles: on natural finish, on playback error, on a
   * watchdog timeout (2x expected duration + 10s), or when stopSpeaking()
   * calls currentChunkSettle(). This is what keeps the hands-free loop from
   * wedging when `didJustFinish` never fires (interruption, route change,
   * mid-chunk unload).
   */
  private async playChunkAudio(base64Audio: string): Promise<void> {
    if (this.speakCancelled) return;

    return await new Promise<void>((resolve, reject) => {
      let settled = false;
      let timeoutHandle: NodeJS.Timeout | null = null;

      const settle = (err?: Error) => {
        if (settled) return;
        settled = true;
        if (timeoutHandle) {
          clearTimeout(timeoutHandle);
          timeoutHandle = null;
        }
        this.currentChunkSettle = null;
        const sound = this.currentSound;
        this.currentSound = null;
        if (sound) {
          sound.setOnPlaybackStatusUpdate(null);
          sound.unloadAsync().catch(() => {});
        }
        if (err) reject(err);
        else resolve();
      };

      // Let stopSpeaking() end this chunk immediately.
      this.currentChunkSettle = () => settle();

      Audio.Sound.createAsync({ uri: base64Audio }, { shouldPlay: true })
        .then(({ sound, status }) => {
          // Cancelled while the sound was being created — stop what we just started.
          if (settled || this.speakCancelled) {
            sound.setOnPlaybackStatusUpdate(null);
            sound.stopAsync().catch(() => {});
            sound.unloadAsync().catch(() => {});
            settle();
            return;
          }

          this.currentSound = sound;

          const durationMs =
            status && status.isLoaded && status.durationMillis ? status.durationMillis : 0;
          // Fall back to a generous fixed budget when duration is unknown.
          const expectedMs = durationMs > 0 ? durationMs : 15000;
          const timeoutMs = expectedMs * 2 + 10000;
          timeoutHandle = setTimeout(() => {
            console.warn('[Voice] Chunk playback timed out after', timeoutMs, 'ms — forcing settle');
            settle();
          }, timeoutMs);

          sound.setOnPlaybackStatusUpdate((s) => {
            if (s.isLoaded && s.didJustFinish) {
              settle();
            } else if (s.isLoaded === false && 'error' in s && s.error) {
              console.error('[Voice] Audio playback error:', s.error);
              settle(new Error(String(s.error)));
            }
          });
        })
        .catch((err) => settle(err instanceof Error ? err : new Error(String(err))));
    });
  }

  /**
   * Speak text using backend TTS (Kokoro).
   * Chunks long text to avoid timeouts and prefetches the next chunk while
   * the current one plays. Always resolves (never hangs) so callers can
   * reliably resume listening in the `finally` of their await.
   */
  async speak(text: string): Promise<void> {
    this.speakCancelled = false;
    try {
      // Strip emojis from text before sending to TTS
      const cleanText = this.stripEmojis(text);
      console.log('[Voice] Speaking via Kokoro TTS (emojis stripped):', cleanText);

      // Split into chunks to avoid timeout
      const chunks = this.splitTextIntoChunks(cleanText);
      console.log(`[Voice] Split into ${chunks.length} chunks for TTS`);
      if (chunks.length === 0) return;

      // Set audio to use speaker (once at the start)
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
      });

      // Prefetch pipeline: kick off the fetch for chunk i+1 before blocking
      // on the playback of chunk i. `.catch(noop)` keeps an abandoned prefetch
      // (after a stop) from surfacing as an unhandled rejection.
      const startFetch = (t: string): Promise<string> => {
        const p = this.fetchChunkAudio(t);
        p.catch(() => {});
        return p;
      };

      let nextAudioPromise: Promise<string> | null = startFetch(chunks[0]);
      for (let i = 0; i < chunks.length; i++) {
        if (this.speakCancelled) break;

        const currentAudioPromise = nextAudioPromise as Promise<string>;
        nextAudioPromise = i + 1 < chunks.length ? startFetch(chunks[i + 1]) : null;

        let base64Audio: string;
        try {
          base64Audio = await currentAudioPromise;
        } catch (fetchErr) {
          console.error(`[Voice] TTS fetch failed for chunk ${i + 1}:`, fetchErr);
          continue; // skip this chunk, keep going
        }

        if (this.speakCancelled) break;
        console.log(`[Voice] Playing chunk ${i + 1}/${chunks.length}`);
        await this.playChunkAudio(base64Audio);
      }

      console.log('[Voice] All chunks finished');
    } catch (error) {
      console.error('[Voice] Failed to speak:', error);
    } finally {
      // ALWAYS restore recording audio mode so continuous listening can resume,
      // even on error or cancellation.
      try {
        await Audio.setAudioModeAsync({
          allowsRecordingIOS: true,
          playsInSilentModeIOS: true,
          staysActiveInBackground: false,
          shouldDuckAndroid: true,
          playThroughEarpieceAndroid: false,
          interruptionModeIOS: InterruptionModeIOS.DuckOthers,
          interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
        });
        console.log('[Voice] Audio mode reset, ready for recording');
      } catch (resetErr) {
        console.error('[Voice] Failed to reset audio mode:', resetErr);
      }
    }
  }

  /**
   * Stop speaking. Aborts the speak() chunk loop and settles the in-flight
   * chunk immediately so the caller's await returns promptly (and continuous
   * listening can resume) instead of hanging on a playback callback.
   */
  async stopSpeaking(): Promise<void> {
    this.speakCancelled = true;

    // Resolve the currently-playing chunk's promise (also unloads its sound).
    if (this.currentChunkSettle) {
      this.currentChunkSettle();
    }

    try {
      if (this.currentSound) {
        try {
          await this.currentSound.stopAsync();
        } catch {}
        try {
          await this.currentSound.unloadAsync();
        } catch {}
        this.currentSound = null;
      }
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

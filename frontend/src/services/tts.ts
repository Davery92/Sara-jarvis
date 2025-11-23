/**
 * Text-to-Speech Service for Web
 * Uses Kokoro TTS via backend API
 */

import { APP_CONFIG } from '../config';

class TTSService {
  private currentAudio: HTMLAudioElement | null = null;
  private isPlaying: boolean = false;

  /**
   * Speak text using Kokoro TTS
   * @param text Text to convert to speech
   * @param streaming Whether to use streaming endpoint (future enhancement)
   */
  async speak(text: string, streaming: boolean = false): Promise<void> {
    try {
      // Stop any currently playing audio
      this.stop();

      console.log('[TTS] Generating speech for:', text.substring(0, 50) + '...');

      // Request TTS audio from backend
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/voice-agent/speak`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          text,
          response_format: 'mp3', // MP3 for best browser compatibility
          stream: streaming
        }),
      });

      if (!response.ok) {
        throw new Error(`TTS request failed: ${response.status}`);
      }

      // Get audio blob
      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);

      // Create and play audio element
      this.currentAudio = new Audio(audioUrl);
      this.isPlaying = true;

      // Cleanup when done
      this.currentAudio.onended = () => {
        this.cleanup();
      };

      this.currentAudio.onerror = (error) => {
        console.error('[TTS] Playback error:', error);
        this.cleanup();
      };

      // Start playback
      await this.currentAudio.play();
      console.log('[TTS] Playing audio...');
    } catch (error) {
      console.error('[TTS] Error:', error);
      this.cleanup();
      throw error;
    }
  }

  /**
   * Stop currently playing audio
   */
  stop(): void {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
      this.cleanup();
    }
  }

  /**
   * Check if currently playing
   */
  isSpeaking(): boolean {
    return this.isPlaying;
  }

  /**
   * Cleanup resources
   */
  private cleanup(): void {
    if (this.currentAudio) {
      const url = this.currentAudio.src;
      this.currentAudio = null;
      this.isPlaying = false;

      // Revoke blob URL to free memory
      if (url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
      }
    }
  }
}

// Export singleton instance
export const ttsService = new TTSService();
export default ttsService;

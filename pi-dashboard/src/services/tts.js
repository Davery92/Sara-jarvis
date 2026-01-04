/**
 * Text-to-Speech Service for Pi Dashboard
 * Uses Kokoro TTS via backend API
 * Ported from webapp TypeScript implementation
 */

import { api } from './api';

class TTSService {
  constructor() {
    this.currentAudio = null;
    this.isPlaying = false;
    this.onEndCallback = null;
  }

  /**
   * Speak text using Kokoro TTS
   * @param {string} text Text to convert to speech
   * @returns {Promise<void>}
   */
  async speak(text) {
    try {
      // Stop any currently playing audio
      this.stop();

      console.log('[TTS] Generating speech for:', text.substring(0, 50) + '...');

      // Request TTS audio from backend via pi-dashboard endpoint
      const token = localStorage.getItem('device_token');
      const response = await fetch(`${api.getBaseUrl()}/api/pi-dashboard/voice/speak`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token && { 'X-Device-Token': token }),
        },
        credentials: 'include',
        body: JSON.stringify({
          text,
          response_format: 'mp3', // MP3 for best browser compatibility
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
        console.log('[TTS] Playback complete');
        this.cleanup();
        if (this.onEndCallback) {
          this.onEndCallback();
        }
      };

      this.currentAudio.onerror = (error) => {
        console.error('[TTS] Playback error:', error);
        this.cleanup();
        if (this.onEndCallback) {
          this.onEndCallback();
        }
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
   * Set callback for when speech ends
   * @param {Function} callback
   */
  onEnd(callback) {
    this.onEndCallback = callback;
  }

  /**
   * Stop currently playing audio
   */
  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
      this.cleanup();
    }
  }

  /**
   * Check if currently playing
   * @returns {boolean}
   */
  isSpeaking() {
    return this.isPlaying;
  }

  /**
   * Cleanup resources
   */
  cleanup() {
    if (this.currentAudio) {
      const url = this.currentAudio.src;
      this.currentAudio = null;
      this.isPlaying = false;

      // Revoke blob URL to free memory
      if (url && url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
      }
    }
  }
}

// Export singleton instance
export const ttsService = new TTSService();
export default ttsService;

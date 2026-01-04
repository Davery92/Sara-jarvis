/**
 * VoiceInput - Three-tier voice routing
 *
 * Tier 1: UI Commands (frontend-local) - show calendar, open note, etc.
 * Tier 2: Tool Commands (fast worker) - home control, timers, fitness
 * Tier 3: Conversations (full Sara) - complex queries requiring reasoning
 */

import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { audioRecorderService } from '../services/audioRecorder';
import { ttsService } from '../services/tts';
import { api } from '../services/api';
import { classifyCommand, executeCommand } from '../services/commands';

// Status types: idle, recording, processing, speaking, error, listening (post-response)
export function VoiceInput({ onTranscript, commandContext, wakeWordConnected, alwaysListening }) {
  const [status, setStatus] = useState('idle');
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [error, setError] = useState(null);
  const [tier, setTier] = useState(null); // Track which tier handled the request
  const [amplitude, setAmplitude] = useState(0);
  const [inConversation, setInConversation] = useState(false); // Track if in active conversation
  const amplitudeInterval = useRef(null);
  const conversationTimeout = useRef(null);

  // Conversation phrases that end the session
  const END_PHRASES = ['goodbye', 'bye', 'thanks sara', 'thank you sara', "that's all", 'never mind', 'cancel'];

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      audioRecorderService.cleanup();
      ttsService.stop();
      if (amplitudeInterval.current) {
        clearInterval(amplitudeInterval.current);
      }
      if (conversationTimeout.current) {
        clearTimeout(conversationTimeout.current);
      }
    };
  }, []);

  // Check if phrase ends the conversation
  const isEndPhrase = useCallback((text) => {
    const lower = text.toLowerCase().trim();
    return END_PHRASES.some(phrase => lower.includes(phrase));
  }, []);

  // End the conversation and return to wake-word mode
  const endConversation = useCallback(() => {
    console.log('[VoiceInput] Ending conversation, returning to idle');
    setInConversation(false);
    setStatus('idle');
    setTranscript('');
    setResponse('');
    setTier(null);
    if (conversationTimeout.current) {
      clearTimeout(conversationTimeout.current);
      conversationTimeout.current = null;
    }
  }, []);

  // Ref to hold startRecording function for use in callbacks
  const startRecordingRef = useRef(null);

  // Handle the transcribed text through three tiers
  const handleTranscription = useCallback(async (text) => {
    console.log('[VoiceInput] Processing transcription:', text);

    // Clear any conversation timeout
    if (conversationTimeout.current) {
      clearTimeout(conversationTimeout.current);
      conversationTimeout.current = null;
    }

    // Check if user wants to end conversation
    if (inConversation && isEndPhrase(text)) {
      console.log('[VoiceInput] End phrase detected');
      ttsService.speak("Goodbye! Say 'Hey Sara' when you need me.").then(() => {
        endConversation();
      });
      return;
    }

    setTranscript(text);
    setStatus('processing');

    // Mark as in conversation for always-listening mode
    if (alwaysListening) {
      setInConversation(true);
    }

    // Notify parent if callback provided
    if (onTranscript) {
      onTranscript(text);
    }

    try {
      // =====================================================
      // TIER 1: Local UI Commands (no network call)
      // =====================================================
      const localResult = classifyCommand(text);
      console.log('[VoiceInput] Local classification:', localResult);

      if (localResult.type === 'command') {
        setTier('local');
        console.log('[VoiceInput] TIER 1: Executing local command:', localResult.command);

        // Execute the local command
        const execResult = await executeCommand(
          localResult.command,
          localResult.params,
          { api, ...commandContext }
        );

        if (execResult.success) {
          setResponse(execResult.message);

          // Skip TTS for commands that show visual content (like opening notes)
          if (localResult.skipTTS) {
            console.log('[VoiceInput] Skipping TTS for visual command');
            setStatus('idle');
            setTimeout(() => {
              setTranscript('');
              setResponse('');
              setTier(null);
            }, 1500);
            return;
          }

          // Play TTS for the confirmation
          setStatus('speaking');
          ttsService.onEnd(() => {
            // In always-listening mode, continue listening for follow-up
            if (alwaysListening && inConversation) {
              setTimeout(() => {
                setTranscript('');
                setResponse('');
                setTier(null);
                startListeningForFollowUp();
              }, 500);
            } else {
              setStatus('idle');
              setTimeout(() => {
                setTranscript('');
                setResponse('');
                setTier(null);
              }, 1500);
            }
          });
          await ttsService.speak(execResult.message);
          return;
        } else {
          // Command failed, fall through to other tiers
          console.log('[VoiceInput] Local command failed:', execResult.message);
        }
      }

      // =====================================================
      // TIER 2: Fast Worker (HOME, TIME, FITNESS)
      // =====================================================
      console.log('[VoiceInput] TIER 2: Trying fast worker...');
      const fastResult = await api.tryFastWorker(text);
      console.log('[VoiceInput] Fast worker result:', fastResult);

      if (fastResult.handled) {
        setTier('fast');
        console.log('[VoiceInput] TIER 2: Fast worker handled, intent:', fastResult.intent);

        setResponse(fastResult.response);

        // Refresh timers in case a timer was set
        if (commandContext.fetchTimers) {
          commandContext.fetchTimers();
        }

        // Play TTS response
        setStatus('speaking');
        ttsService.onEnd(() => {
          // In always-listening mode, continue listening for follow-up
          if (alwaysListening && inConversation) {
            setTimeout(() => {
              setTranscript('');
              setResponse('');
              setTier(null);
              startListeningForFollowUp();
            }, 500);
          } else {
            setStatus('idle');
            setTimeout(() => {
              setTranscript('');
              setResponse('');
              setTier(null);
            }, 2000);
          }
        });
        await ttsService.speak(fastResult.response);
        return;
      }

      // =====================================================
      // TIER 3: Full Sara (complex queries)
      // =====================================================
      console.log('[VoiceInput] TIER 3: Sending to full Sara...');
      setTier('sara');

      const saraResult = await api.sendChatMessage(text);
      const saraResponse = saraResult.response;

      if (!saraResponse) {
        console.log('[VoiceInput] No response from Sara');
        setError('No response');
        setStatus('idle');
        return;
      }

      console.log('[VoiceInput] Sara response:', saraResponse.substring(0, 100) + '...');
      setResponse(saraResponse);

      // Refresh timers in case a timer was set
      if (commandContext.fetchTimers) {
        commandContext.fetchTimers();
      }

      // Play TTS response
      setStatus('speaking');
      ttsService.onEnd(() => {
        // In always-listening mode, continue listening for follow-up
        if (alwaysListening && inConversation) {
          setTimeout(() => {
            setTranscript('');
            setResponse('');
            setTier(null);
            startListeningForFollowUp();
          }, 500);
        } else {
          setStatus('idle');
          setTimeout(() => {
            setTranscript('');
            setResponse('');
            setTier(null);
          }, 2000);
        }
      });
      await ttsService.speak(saraResponse);

    } catch (err) {
      console.error('[VoiceInput] Error:', err);
      setError(err.message || 'Processing failed');
      setStatus('idle');
      setTimeout(() => setError(null), 3000);
    }
  }, [onTranscript, commandContext, alwaysListening, inConversation, isEndPhrase, endConversation]);

  // Handle silence detected - stop recording and process
  const handleSilenceDetected = useCallback(async () => {
    console.log('[VoiceInput] Silence detected, stopping recording');

    // Stop amplitude polling
    if (amplitudeInterval.current) {
      clearInterval(amplitudeInterval.current);
      amplitudeInterval.current = null;
    }
    setAmplitude(0);

    // Stop recording and get audio blob
    const audioBlob = await audioRecorderService.stopRecording();

    if (!audioBlob || audioBlob.size < 1000) {
      console.log('[VoiceInput] Audio too short, ignoring');
      // In conversation mode, end the conversation on silence
      if (inConversation) {
        console.log('[VoiceInput] Ending conversation due to silence');
        endConversation();
      } else {
        setStatus('idle');
      }
      return;
    }

    setStatus('processing');
    setTranscript('Transcribing...');
    setError(null);

    try {
      // Transcribe audio
      console.log('[VoiceInput] Transcribing audio...');
      const transcribeResult = await api.transcribeAudio(audioBlob);
      const text = transcribeResult.transcription;

      if (!text || text.trim().length === 0) {
        console.log('[VoiceInput] No speech detected');
        setTranscript('');
        setError('No speech detected');
        setTimeout(() => {
          setError(null);
          setStatus('idle');
        }, 2000);
        return;
      }

      // Process through three-tier routing
      await handleTranscription(text);

    } catch (err) {
      console.error('[VoiceInput] Transcription error:', err);
      setError(err.message || 'Transcription failed');
      setStatus('idle');
      setTimeout(() => setError(null), 3000);
    }
  }, [handleTranscription, inConversation, endConversation]);

  // Start recording
  const startRecording = async () => {
    // Allow starting from idle or listening (follow-up) states
    if (status !== 'idle' && status !== 'listening') return;

    setError(null);
    setTranscript('');
    setResponse('');
    setTier(null);

    try {
      setStatus('recording');

      // Start recording with VAD callback
      await audioRecorderService.startRecording(handleSilenceDetected);

      // Start amplitude polling for visualization
      amplitudeInterval.current = setInterval(() => {
        const amp = audioRecorderService.getAmplitude();
        setAmplitude(amp);
      }, 50);

    } catch (err) {
      console.error('[VoiceInput] Failed to start recording:', err);
      setError('Microphone not available');
      setStatus('idle');
    }
  };

  // Store ref to startRecording for use in TTS callbacks
  startRecordingRef.current = startRecording;

  // Start listening for follow-up (after TTS completes in always-listening mode)
  const startListeningForFollowUp = useCallback(() => {
    if (!alwaysListening || !inConversation) {
      return;
    }

    console.log('[VoiceInput] Listening for follow-up...');
    setStatus('listening');

    // Set a timeout to end conversation if no speech
    conversationTimeout.current = setTimeout(() => {
      console.log('[VoiceInput] Conversation timeout, returning to idle');
      endConversation();
    }, 5000); // 5 second timeout for follow-up

    // Start recording for follow-up
    if (startRecordingRef.current) {
      startRecordingRef.current();
    }
  }, [alwaysListening, inConversation, endConversation]);

  // Manual stop (if user taps again)
  const stopRecording = async () => {
    if (status !== 'recording') return;
    handleSilenceDetected();
  };

  // Handle tap
  const handleTap = () => {
    if (status === 'idle' || status === 'listening') {
      startRecording();
    } else if (status === 'recording') {
      stopRecording();
    } else if (status === 'speaking') {
      ttsService.stop();
      setStatus('idle');
    }
  };

  // Get status icon
  const getStatusIcon = () => {
    switch (status) {
      case 'recording':
        return '\uD83D\uDD34'; // Red circle
      case 'listening':
        return '\uD83D\uDC42'; // Ear (listening for follow-up)
      case 'processing':
        return '\u26A1'; // Lightning
      case 'speaking':
        return '\uD83D\uDD0A'; // Speaker
      case 'error':
        return '\u26A0\uFE0F'; // Warning
      default:
        return '\uD83C\uDFA4'; // Microphone
    }
  };

  // Get tier badge
  const getTierBadge = () => {
    if (!tier) return null;
    const badges = {
      local: { text: 'LOCAL', color: 'var(--accent-green)' },
      fast: { text: 'FAST', color: 'var(--accent-yellow)' },
      sara: { text: 'SARA', color: 'var(--accent-purple)' },
    };
    return badges[tier];
  };

  // Get status text
  const getStatusText = () => {
    if (error) return error;
    switch (status) {
      case 'listening':
        return 'Listening for follow-up...';
      case 'recording':
        return transcript || 'Listening... (tap to stop)';
      case 'processing':
        return transcript || 'Processing...';
      case 'speaking':
        return response ? (response.length > 80 ? response.substring(0, 80) + '...' : response) : 'Speaking...';
      default:
        return inConversation ? 'In conversation...' : (alwaysListening ? 'Say "Hey Sara"' : 'Tap to speak');
    }
  };

  // Get CSS class for status
  const getStatusClass = () => {
    return `voice-indicator ${status}`;
  };

  // Calculate pulse scale based on amplitude (for recording and listening states)
  const pulseScale = (status === 'recording' || status === 'listening') ? 1 + amplitude * 0.3 : 1;
  const tierBadge = getTierBadge();

  return (
    <div class="voice-panel" onClick={handleTap}>
      <div class="voice-status">
        <div
          class={getStatusClass()}
          style={status === 'recording' ? { transform: `scale(${pulseScale})` } : {}}
        >
          {getStatusIcon()}
        </div>
        <div class="voice-text-container">
          {tierBadge && (
            <span class="tier-badge" style={{ backgroundColor: tierBadge.color }}>
              {tierBadge.text}
            </span>
          )}
          <span class={`voice-text ${status !== 'idle' ? 'active' : ''}`}>
            {getStatusText()}
          </span>
        </div>
        {/* Wake word status indicator */}
        {wakeWordConnected !== undefined && (
          <div
            class={`wake-word-indicator ${wakeWordConnected ? 'connected' : 'disconnected'}`}
            title={wakeWordConnected ? 'Wake word: listening' : 'Wake word: disconnected'}
          >
            {wakeWordConnected ? '👂' : '🔇'}
          </div>
        )}
      </div>
    </div>
  );
}

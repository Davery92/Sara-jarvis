import React, { useState, useEffect, useRef } from 'react'
import { Mic, MicOff, Radio, AlertCircle, Volume2 } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import { spriteBus } from '../../state/spriteBus'

type VoiceMode = 'off' | 'wake-word' | 'always-on'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

// Extend the Window interface for webkit speech recognition
interface IWindow extends Window {
  webkitSpeechRecognition: any
  SpeechRecognition: any
}

export default function FitnessVoice() {
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('off')
  const [messages, setMessages] = useState<Message[]>([])
  const [micPermission, setMicPermission] = useState<'granted' | 'denied' | 'prompt' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isListening, setIsListening] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [lastHeardText, setLastHeardText] = useState<string>('')
  const [wakeWordDetected, setWakeWordDetected] = useState(false)

  const mediaStreamRef = useRef<MediaStream | null>(null)
  const recognitionRef = useRef<any>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const currentAudioRef = useRef<AudioBufferSourceNode | null>(null)

  // VAD-like buffering for wake word mode
  const recordingAfterWakeWordRef = useRef<boolean>(false)
  const bufferedTranscriptRef = useRef<string>('')
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null)

  // Check microphone permission status on mount
  useEffect(() => {
    checkMicPermission()
    // Initialize audio context
    audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)()

    return () => {
      // Cleanup: stop media stream when component unmounts
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(track => track.stop())
      }
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort()
        } catch (e) {
          console.log('Cleanup abort failed:', e)
        }
      }
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current)
      }
      if (currentAudioRef.current) {
        currentAudioRef.current.stop()
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
      }
    }
  }, [])

  // Initialize speech recognition when voice mode changes
  useEffect(() => {
    if (voiceMode !== 'off' && micPermission === 'granted') {
      // Small delay to ensure cleanup from previous mode is complete
      const timeout = setTimeout(() => {
        initializeSpeechRecognition()
      }, 100)
      return () => clearTimeout(timeout)
    } else if (voiceMode === 'off') {
      setIsListening(false)
      spriteBus.setBase('idle', 'fitness-voice')
    }
  }, [voiceMode, micPermission])

  const checkMicPermission = async () => {
    try {
      if (navigator.permissions) {
        const result = await navigator.permissions.query({ name: 'microphone' as PermissionName })
        setMicPermission(result.state as 'granted' | 'denied' | 'prompt')

        // Listen for permission changes
        result.addEventListener('change', () => {
          setMicPermission(result.state as 'granted' | 'denied' | 'prompt')
        })
      }
    } catch (err) {
      console.error('Error checking microphone permission:', err)
    }
  }

  const requestMicrophoneAccess = async () => {
    try {
      setError(null)
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      setMicPermission('granted')
      return true
    } catch (err: any) {
      console.error('Microphone access denied:', err)
      setMicPermission('denied')
      setError('Microphone access denied. Please enable microphone permissions in your browser settings.')
      return false
    }
  }

  const initializeSpeechRecognition = () => {
    const SpeechRecognition = (window as any as IWindow).SpeechRecognition || (window as any as IWindow).webkitSpeechRecognition

    if (!SpeechRecognition) {
      setError('Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.')
      return
    }

    // Reset buffering state
    recordingAfterWakeWordRef.current = false
    bufferedTranscriptRef.current = ''
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true  // Enable interim results for better VAD
    recognition.lang = 'en-US'

    recognition.onstart = () => {
      console.log('Recognition started')
      setIsListening(true)
      setError(null)
      spriteBus.setBase('listening', 'fitness-voice')
    }

    recognition.onend = () => {
      console.log('Recognition ended, voiceMode:', voiceMode)
      setIsListening(false)

      // Restart if mode is still active
      if (voiceMode !== 'off') {
        try {
          setTimeout(() => {
            if (recognitionRef.current && voiceMode !== 'off') {
              recognition.start()
            }
          }, 100)
        } catch (e) {
          console.log('Recognition restart failed:', e)
        }
      }
    }

    recognition.onerror = (event: any) => {
      console.error('Speech recognition error:', event.error)
      if (event.error === 'no-speech') {
        // Just restart, don't show error
        return
      }
      if (event.error !== 'aborted') {
        setError(`Speech recognition error: ${event.error}`)
      }
    }

    recognition.onresult = async (event: any) => {
      const last = event.results.length - 1
      const result = event.results[last]
      const transcript = result[0].transcript.trim()
      const isFinal = result.isFinal

      console.log('Recognized:', transcript, 'Final:', isFinal)

      // Show what was heard
      setLastHeardText(transcript)

      if (voiceMode === 'wake-word') {
        // Check if we're recording after wake word
        if (recordingAfterWakeWordRef.current) {
          // We're buffering speech after wake word
          if (isFinal) {
            // Add to buffer
            bufferedTranscriptRef.current += ' ' + transcript
            console.log('Buffered:', bufferedTranscriptRef.current)

            // Clear previous silence timer
            if (silenceTimerRef.current) {
              clearTimeout(silenceTimerRef.current)
            }

            // Set new silence timer (2 seconds of silence = done speaking)
            silenceTimerRef.current = setTimeout(async () => {
              // User is done speaking, send the complete message
              const completeMessage = bufferedTranscriptRef.current.trim()
              console.log('Silence detected, sending:', completeMessage)

              // Reset recording state
              recordingAfterWakeWordRef.current = false
              bufferedTranscriptRef.current = ''

              // Reset visuals
              spriteBus.setVisuals({
                brightnessScale: 1.0,
                saturationScale: 1.0,
                energyScale: 1.0
              }, 'fitness-voice')

              if (completeMessage) {
                await handleUserMessage(completeMessage)
              }

              setTimeout(() => setLastHeardText(''), 1000)
            }, 2000)
          }
        } else {
          // Not recording yet, check for wake word
          if (isFinal && (transcript.toLowerCase().includes('sara') || transcript.toLowerCase().includes('sarah'))) {
            // Wake word detected!
            console.log('Wake word detected!')
            setWakeWordDetected(true)
            setTimeout(() => setWakeWordDetected(false), 2000)

            // Make sprite bright and energetic
            spriteBus.setVisuals({
              brightnessScale: 1.5,
              saturationScale: 1.3,
              energyScale: 1.4
            }, 'fitness-voice')

            // Celebrate wake word detection
            spriteBus.celebrate({ source: 'fitness-voice', autoClearMs: 1500 })

            // Extract any query in the same utterance
            const query = transcript.replace(/sara|sarah/gi, '').trim()

            // Start recording mode
            recordingAfterWakeWordRef.current = true
            bufferedTranscriptRef.current = query
            console.log('Started recording mode, initial buffer:', query)

            // Set silence timer to send after 2 seconds
            if (silenceTimerRef.current) {
              clearTimeout(silenceTimerRef.current)
            }

            silenceTimerRef.current = setTimeout(async () => {
              const completeMessage = bufferedTranscriptRef.current.trim()
              console.log('Silence detected, sending:', completeMessage)

              // Reset recording state
              recordingAfterWakeWordRef.current = false
              bufferedTranscriptRef.current = ''

              // Reset visuals
              spriteBus.setVisuals({
                brightnessScale: 1.0,
                saturationScale: 1.0,
                energyScale: 1.0
              }, 'fitness-voice')

              if (completeMessage) {
                await handleUserMessage(completeMessage)
              } else {
                // Just wake word, acknowledge
                addMessage('assistant', 'Yes? How can I help with your fitness?')
                speak('Yes? How can I help with your fitness?')
              }

              setTimeout(() => setLastHeardText(''), 1000)
            }, 2000)
          } else if (isFinal) {
            // Heard something but not wake word - clear after showing briefly
            setTimeout(() => setLastHeardText(''), 1500)
          }
        }
      } else if (voiceMode === 'always-on') {
        // Always-on mode: process final results immediately
        if (isFinal) {
          await handleUserMessage(transcript)
          setTimeout(() => setLastHeardText(''), 3000)
        }
      }
    }

    recognitionRef.current = recognition

    try {
      recognition.start()
    } catch (e) {
      console.error('Failed to start recognition:', e)
    }
  }

  const handleUserMessage = async (message: string) => {
    if (!message.trim() || isProcessing) return

    addMessage('user', message)
    setIsProcessing(true)
    spriteBus.setBase('thinking', 'fitness-voice')

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message }),
      })

      if (response.ok) {
        const data = await response.json()
        const assistantMessage = data.response
        addMessage('assistant', assistantMessage)
        speak(assistantMessage)
      } else {
        throw new Error('Failed to get response')
      }
    } catch (err) {
      console.error('Chat error:', err)
      const errorMsg = 'Sorry, I had trouble processing that. Can you try again?'
      addMessage('assistant', errorMsg)
      speak(errorMsg)
    } finally {
      setIsProcessing(false)
      spriteBus.setBase('listening', 'fitness-voice')
    }
  }

  const addMessage = (role: 'user' | 'assistant', content: string) => {
    setMessages(prev => [...prev, { role, content, timestamp: new Date() }])
  }

  const speak = async (text: string) => {
    if (!audioContextRef.current) return

    // Stop any ongoing speech
    if (currentAudioRef.current) {
      currentAudioRef.current.stop()
      currentAudioRef.current = null
    }

    setIsSpeaking(true)
    spriteBus.setOverlay('speaking', { source: 'fitness-voice', autoClearMs: text.length * 50 })

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ text })
      })

      if (!response.ok) {
        throw new Error('TTS request failed')
      }

      const audioData = await response.arrayBuffer()
      const audioBuffer = await audioContextRef.current.decodeAudioData(audioData)
      const source = audioContextRef.current.createBufferSource()
      source.buffer = audioBuffer
      source.connect(audioContextRef.current.destination)

      source.onended = () => {
        setIsSpeaking(false)
        spriteBus.setOverlay(undefined, { source: 'fitness-voice' })
        currentAudioRef.current = null
      }

      currentAudioRef.current = source
      source.start(0)
    } catch (error) {
      console.error('TTS error:', error)
      setIsSpeaking(false)
      spriteBus.setOverlay(undefined, { source: 'fitness-voice' })
    }
  }

  const handleVoiceModeChange = async (mode: VoiceMode) => {
    console.log('Switching voice mode to:', mode)

    // First, stop any existing recognition before switching modes
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
        recognitionRef.current = null
      } catch (e) {
        console.log('Recognition abort failed:', e)
      }
    }

    // Clear buffering state
    recordingAfterWakeWordRef.current = false
    bufferedTranscriptRef.current = ''
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }

    // Stop any ongoing speech
    if (currentAudioRef.current) {
      currentAudioRef.current.stop()
      currentAudioRef.current = null
    }

    if (mode === 'off') {
      // Stop listening
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(track => track.stop())
        mediaStreamRef.current = null
      }
      setVoiceMode('off')
      setIsListening(false)
      setIsSpeaking(false)
      setIsProcessing(false)
      setError(null)
      setLastHeardText('')

      // Reset sprite to idle
      spriteBus.setBase('idle', 'fitness-voice')
      spriteBus.setOverlay(undefined, { source: 'fitness-voice' })
      spriteBus.setVisuals({
        brightnessScale: 1.0,
        saturationScale: 1.0,
        energyScale: 1.0
      }, 'fitness-voice')
    } else {
      // Request microphone access before enabling voice modes
      const hasAccess = await requestMicrophoneAccess()
      if (hasAccess) {
        setVoiceMode(mode)
        addMessage('assistant', `Voice mode set to: ${mode === 'wake-word' ? 'Wake Word (say "Sara")' : 'Always On'}`)
      } else {
        // Keep mode as off if permission denied
        setVoiceMode('off')
      }
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h2 className="text-2xl font-bold">Voice Assistant</h2>
        <p className="text-gray-400 text-sm mt-1">Talk to Sara about your fitness</p>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-500/20 border border-red-500 rounded-lg p-4 mb-6 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm text-red-200">{error}</p>
          </div>
        </div>
      )}

      {/* Voice Mode Controls */}
      <div className="bg-gray-800 rounded-lg p-6 mb-6 border border-gray-700">
        <h3 className="text-lg font-semibold mb-4">Voice Mode</h3>
        <div className="mb-3 text-sm flex items-center justify-between">
          <div>
            <span className="text-gray-400">Microphone: </span>
            <span className={`font-medium ${
              micPermission === 'granted' ? 'text-green-400' :
              micPermission === 'denied' ? 'text-red-400' :
              'text-yellow-400'
            }`}>
              {micPermission === 'granted' ? 'Granted' :
               micPermission === 'denied' ? 'Denied' :
               'Not requested'}
            </span>
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            {isListening && (
              <span className="text-green-400 text-sm flex items-center gap-1">
                <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                Listening
              </span>
            )}
            {wakeWordDetected && (
              <span className="text-yellow-400 text-sm flex items-center gap-1 font-semibold animate-pulse">
                ⚡ Wake word detected!
              </span>
            )}
            {isProcessing && (
              <span className="text-blue-400 text-sm">Processing...</span>
            )}
            {isSpeaking && (
              <span className="text-purple-400 text-sm flex items-center gap-1">
                <Volume2 className="w-4 h-4" />
                Speaking
              </span>
            )}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <button
            onClick={() => handleVoiceModeChange('off')}
            className={`
              p-4 rounded-lg border-2 flex flex-col items-center gap-2 transition-colors
              ${voiceMode === 'off'
                ? 'border-red-500 bg-red-500/20'
                : 'border-gray-600 hover:border-gray-500'
              }
            `}
          >
            <MicOff className="w-6 h-6" />
            <span className="font-medium">Mic Off</span>
            <span className="text-xs text-gray-400">Not listening</span>
          </button>

          <button
            onClick={() => handleVoiceModeChange('wake-word')}
            className={`
              p-4 rounded-lg border-2 flex flex-col items-center gap-2 transition-colors
              ${voiceMode === 'wake-word'
                ? 'border-yellow-500 bg-yellow-500/20'
                : 'border-gray-600 hover:border-gray-500'
              }
            `}
          >
            <Radio className="w-6 h-6" />
            <span className="font-medium">Wake Word</span>
            <span className="text-xs text-gray-400">Say "Sara"</span>
          </button>

          <button
            onClick={() => handleVoiceModeChange('always-on')}
            className={`
              p-4 rounded-lg border-2 flex flex-col items-center gap-2 transition-colors
              ${voiceMode === 'always-on'
                ? 'border-green-500 bg-green-500/20'
                : 'border-gray-600 hover:border-gray-500'
              }
            `}
          >
            <Mic className="w-6 h-6" />
            <span className="font-medium">Always On</span>
            <span className="text-xs text-gray-400">Full chat</span>
          </button>
        </div>
      </div>

      {/* What I Heard */}
      {lastHeardText && (
        <div className="bg-gray-700 rounded-lg p-4 mb-6 border border-gray-600">
          <div className="flex items-start gap-2">
            <span className="text-xs text-gray-400 uppercase tracking-wide">Heard:</span>
            <span className="text-sm text-white font-medium">"{lastHeardText}"</span>
          </div>
        </div>
      )}

      {/* Conversation */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold mb-4">Conversation</h3>
        {messages.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <p>No conversation yet</p>
            <p className="text-sm mt-1">
              {voiceMode === 'off' && 'Enable a voice mode to start talking'}
              {voiceMode === 'wake-word' && 'Say "Sara" followed by your question'}
              {voiceMode === 'always-on' && 'Start speaking - Sara is listening'}
            </p>
          </div>
        ) : (
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-lg text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600/20 border border-blue-500/30 ml-8'
                    : 'bg-purple-600/20 border border-purple-500/30 mr-8'
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="font-semibold text-xs opacity-70">
                    {msg.role === 'user' ? 'You' : 'Sara'}
                  </span>
                  <span className="text-xs opacity-50">
                    {msg.timestamp.toLocaleTimeString()}
                  </span>
                </div>
                <p className="mt-1">{msg.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Status */}
      <div className="mt-4 text-center text-sm text-gray-400">
        <p>
          Status:{' '}
          <span className={`
            font-medium
            ${voiceMode === 'off' && 'text-red-400'}
            ${voiceMode === 'wake-word' && 'text-yellow-400'}
            ${voiceMode === 'always-on' && 'text-green-400'}
          `}>
            {voiceMode === 'off' && 'Microphone Off'}
            {voiceMode === 'wake-word' && 'Listening for Wake Word'}
            {voiceMode === 'always-on' && 'Always Listening'}
          </span>
        </p>
      </div>
    </div>
  )
}

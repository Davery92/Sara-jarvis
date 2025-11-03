"""
Audio Session Orchestrator
Main voice agent that coordinates wake word, VAD, STT, and TTS
"""
import asyncio
import logging
import numpy as np
from typing import Optional, Dict, Callable
from enum import Enum
import time
import threading
from concurrent.futures import Future

logger = logging.getLogger(__name__)

from wake_word import WakeWordDetector
from audio_buffer import PreRollBuffer
from audio_capture import AudioCapture

# Try to import torch-based VAD, fall back to lightweight VAD
try:
    from vad import VoiceActivityDetector, RecordingWindow
    logger.info("Using Silero VAD (PyTorch-based)")
except (ImportError, ModuleNotFoundError) as e:
    logger.warning(f"PyTorch not available ({e}), using lightweight WebRTC VAD")
    from vad_lightweight import VoiceActivityDetector, RecordingWindow

from wyoming_client import WyomingClient, AudioStreamSession
from tts_playback import TTSPlayer, EchoSuppressor


class VoiceAgentState(Enum):
    """Voice agent states"""
    IDLE = "idle"
    LISTENING_FOR_WAKE = "listening_for_wake"
    WAITING_FOR_SPEECH = "waiting_for_speech"  # In conversation mode, waiting for user to speak
    RECORDING = "recording"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class VoiceMode(Enum):
    """Voice agent operational modes"""
    ALWAYS_ON = "always_on"  # Always listening for wake word
    SHADOW_ONLY = "shadow_only"  # Only listen during Shadow sessions
    PUSH_TO_TALK = "push_to_talk"  # Manual activation


class VoiceAgent:
    """
    Complete voice agent orchestrator
    Manages: Wake word → VAD → STT → Tool execution → TTS → Playback
    """

    def __init__(
        self,
        backend_url: str = "ws://10.185.1.180:8000",
        voice_mode: VoiceMode = VoiceMode.ALWAYS_ON,
        on_state_change: Optional[Callable[[VoiceAgentState], None]] = None,
        on_transcript: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize voice agent

        Args:
            backend_url: Wyoming backend WebSocket URL
            voice_mode: Operating mode (always_on, shadow_only, ptt)
            on_state_change: Callback when agent state changes
            on_transcript: Callback when transcript received
        """
        self.backend_url = backend_url
        self.voice_mode = voice_mode
        self.on_state_change = on_state_change
        self.on_transcript = on_transcript

        # State
        self.state = VoiceAgentState.IDLE
        self.is_running = False
        self.is_shadow_session_active = False
        self.suppress_wake_word_until = 0  # Timestamp to suppress wake word detection
        self.in_conversation_mode = False  # Multi-turn conversation without wake word
        self.conversation_mode_timeout = 5.0  # Seconds of silence to exit conversation mode

        # Recording timeout tracking
        self.recording_start_time = 0
        self.recording_timeout_seconds = 10  # Timeout after 10 seconds of no final speech
        self.waiting_for_speech_start_time = 0  # Track when we started waiting for speech

        # Components (initialized in start())
        self.wake_detector: Optional[WakeWordDetector] = None
        self.pre_roll_buffer: Optional[PreRollBuffer] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.vad: Optional[VoiceActivityDetector] = None
        self.recording_window: Optional[RecordingWindow] = None
        self.wyoming_client: Optional[WyomingClient] = None
        self.audio_session: Optional[AudioStreamSession] = None
        self.tts_player: Optional[TTSPlayer] = None
        self.echo_suppressor: Optional[EchoSuppressor] = None

        # Event loop for async operations (runs in background thread)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._processing_task: Optional[asyncio.Task] = None

    def _run_event_loop(self):
        """Run event loop in background thread"""
        asyncio.set_event_loop(self.loop)
        logger.debug("Event loop thread started")
        self.loop.run_forever()
        logger.debug("Event loop thread stopped")

    def start(self):
        """Start the voice agent"""
        if self.is_running:
            logger.warning("Voice agent already running")
            return

        logger.info("🚀 Starting voice agent...")

        # Create dedicated event loop in background thread
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._loop_thread.start()

        # Initialize components
        self._initialize_components()

        # Set state
        self.is_running = True
        self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

        # Start audio capture
        self.audio_capture.set_callback(self._audio_callback)
        self.audio_capture.start()

        logger.info("✅ Voice agent started")
        logger.info(f"   Mode: {self.voice_mode.value}")
        logger.info(f"   Say 'sarah' to activate")

    def stop(self):
        """Stop the voice agent"""
        if not self.is_running:
            return

        logger.info("Stopping voice agent...")
        self.is_running = False

        # Stop components
        if self.audio_capture:
            self.audio_capture.stop()

        if self.tts_player:
            self.tts_player.stop()

        # Stop event loop
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

        self._set_state(VoiceAgentState.IDLE)
        logger.info("Voice agent stopped")

    def _initialize_components(self):
        """Initialize all voice components"""
        # Wake word detector with higher threshold to avoid false positives
        # (keyboard noise, etc.)
        self.wake_detector = WakeWordDetector(
            threshold=0.6,  # Increased from 0.5
            debounce_seconds=3.0  # Longer debounce to prevent loops
        )

        # Pre-roll buffer
        self.pre_roll_buffer = PreRollBuffer(duration_seconds=1.5)

        # Audio capture
        self.audio_capture = AudioCapture(sample_rate=16000, blocksize=1280)

        # VAD with very aggressive settings to filter background noise
        # Now that we process ALL frames (not just 37.5%), aggressiveness=3 works properly
        self.vad = VoiceActivityDetector(
            aggressiveness=3,  # Most aggressive - only real speech, not background noise
            min_speech_duration_ms=800,  # Require 800ms of continuous speech (filters background noise)
            min_silence_duration_ms=700   # 700ms silence to end (helps detect actual pauses)
        )

        # Recording window
        self.recording_window = RecordingWindow(
            vad=self.vad,
            on_recording_start=self._on_recording_start,
            on_recording_stop=self._on_recording_stop
        )

        # Wyoming client
        self.wyoming_client = WyomingClient(backend_url=self.backend_url)

        # Audio session
        self.audio_session = AudioStreamSession(
            wyoming_client=self.wyoming_client,
            on_transcript=self._on_transcript_received
        )

        # TTS player
        self.tts_player = TTSPlayer(
            on_playback_start=self._on_tts_start,
            on_playback_end=self._on_tts_end
        )

        # Echo suppressor
        self.echo_suppressor = EchoSuppressor(self.audio_capture)

        logger.debug("All components initialized")

    def _audio_callback(self, audio_chunk: np.ndarray):
        """Main audio processing callback"""
        # Add to pre-roll buffer
        self.pre_roll_buffer.add_chunk(audio_chunk)

        # Check if we should be listening for wake word
        if not self._should_listen_for_wake():
            return

        # State machine
        if self.state == VoiceAgentState.LISTENING_FOR_WAKE:
            # Check if wake word detection is temporarily suppressed (for TTS echo)
            current_time = time.time()
            if current_time < self.suppress_wake_word_until:
                # Still in suppression period after TTS
                return

            # Check for wake word
            detection = self.wake_detector.process_chunk(audio_chunk)

            if detection:
                # Wake word detected!
                logger.info(f"🎤 Wake word detected: {detection['name']} (score: {detection['score']:.2f})")
                self._on_wake_word_detected()

        elif self.state == VoiceAgentState.WAITING_FOR_SPEECH:
            # In conversation mode, waiting for user to start speaking
            # Check if conversation timeout exceeded
            elapsed = time.time() - self.waiting_for_speech_start_time
            if elapsed > self.conversation_mode_timeout:
                logger.info(f"⏱️ Conversation timeout ({self.conversation_mode_timeout}s) - returning to wake word mode")
                self.in_conversation_mode = False
                self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
                return

            # Check if speech started
            vad_result = self.vad.process_chunk(audio_chunk)
            if vad_result['is_speech'] or vad_result['speech_started']:
                # User started speaking! Begin recording
                logger.info("🎤 Speech detected - starting recording (conversation mode)")
                self._set_state(VoiceAgentState.RECORDING)
                # Reset VAD and recording window
                self.vad.reset()
                self.recording_window.reset()
                self.recording_window.force_start_recording()
                # Add pre-roll buffer
                pre_roll_audio = self.pre_roll_buffer.get_buffer()
                if len(pre_roll_audio) > 0:
                    self.recording_window.add_to_buffer(pre_roll_audio)
                self.recording_start_time = time.time()

        elif self.state == VoiceAgentState.RECORDING:
            # Check for recording timeout
            elapsed = time.time() - self.recording_start_time
            if elapsed > self.recording_timeout_seconds:
                logger.warning(f"⏱️ Recording timeout after {elapsed:.1f}s - no speech detected")
                logger.warning(f"   Buffer has {len(self.recording_window.recording_buffer)} chunks")
                if self.in_conversation_mode:
                    self.in_conversation_mode = False
                self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
                return

            # Log every 2 seconds to show we're processing
            if int(elapsed) % 2 == 0 and int(elapsed * 10) % 10 == 0:  # Every 2 seconds, once
                logger.debug(f"Recording... {elapsed:.1f}s / {self.recording_timeout_seconds}s")

            # Process with VAD
            self.recording_window.process_chunk(audio_chunk)

        elif self.state == VoiceAgentState.SPEAKING:
            # BARGE-IN DISABLED: Causes false positives from TTS echo
            # The TTS audio leaks into the microphone and triggers VAD
            # TODO: Implement better echo cancellation before enabling
            pass

    def _should_listen_for_wake(self) -> bool:
        """Determine if agent should listen for wake word based on mode"""
        if self.voice_mode == VoiceMode.ALWAYS_ON:
            return True
        elif self.voice_mode == VoiceMode.SHADOW_ONLY:
            return self.is_shadow_session_active
        elif self.voice_mode == VoiceMode.PUSH_TO_TALK:
            return False  # PTT handled separately
        return False

    def _on_wake_word_detected(self):
        """Handle wake word detection"""
        # Only process if in correct state (avoid loops during TTS/processing)
        if self.state not in (VoiceAgentState.LISTENING_FOR_WAKE, VoiceAgentState.SPEAKING):
            logger.debug(f"Ignoring wake word in state: {self.state.value}")
            return

        # Enter conversation mode
        self.in_conversation_mode = True
        logger.info("💬 Entering conversation mode")

        # Transition to recording state
        self._set_state(VoiceAgentState.RECORDING)

        # Start recording timeout timer
        self.recording_start_time = time.time()

        # DO NOT reset wake word debounce - let it naturally expire
        # This prevents rapid re-triggers

        # Reset VAD and recording window
        self.vad.reset()
        self.recording_window.reset()

        # IMMEDIATELY start recording (don't wait for VAD to detect speech)
        # This prevents missing the first word
        self.recording_window.force_start_recording()
        logger.info("🔴 Recording started (immediate after wake word)")

        # Get pre-roll buffer and inject it
        pre_roll_audio = self.pre_roll_buffer.get_buffer()
        if len(pre_roll_audio) > 0:
            logger.debug(f"Injecting {len(pre_roll_audio)/16000:.2f}s of pre-roll audio")
            # Add pre-roll directly to recording buffer
            self.recording_window.add_to_buffer(pre_roll_audio)

    def _on_recording_start(self):
        """Callback when VAD starts recording"""
        logger.info("🔴 Recording started")

    def _on_recording_stop(self, audio_data: np.ndarray):
        """Callback when VAD stops recording"""
        logger.info(f"⏹️ Recording stopped ({len(audio_data)/16000:.2f}s)")

        # Transition to processing
        self._set_state(VoiceAgentState.PROCESSING)

        # Schedule async processing on background event loop
        if self.loop:
            future = asyncio.run_coroutine_threadsafe(
                self._process_utterance(audio_data),
                self.loop
            )
            # Optional: handle completion/errors
            def on_done(f):
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"Processing failed: {e}")
                    self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
            future.add_done_callback(on_done)
        else:
            logger.error("Event loop not available!")
            self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

    async def _get_ai_response(self, user_message: str) -> str:
        """
        Get AI response from Sara backend

        Args:
            user_message: User's transcribed message

        Returns:
            AI response text
        """
        try:
            import aiohttp
            import socket

            # Extract HTTP URL from WebSocket URL
            http_url = self.backend_url.replace("ws://", "http://").replace("wss://", "https://")

            # Remove any /api/wyoming path
            if "/api/wyoming" in http_url:
                http_url = http_url.split("/api/wyoming")[0]

            # Send message to Sara's voice agent chat API (no auth required)
            chat_url = f"{http_url}/voice-agent/chat"

            # Use computer hostname as session ID for conversation continuity
            session_id = socket.gethostname()

            logger.info(f"💬 Sending to AI: {user_message}")

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    chat_url,
                    json={
                        "message": user_message,
                        "session_id": session_id
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        ai_response = data.get("response", "I didn't understand that.")
                        logger.info(f"🤖 AI response: {ai_response}")
                        return ai_response
                    else:
                        logger.error(f"AI backend error: {response.status}")
                        return "Sorry, I'm having trouble thinking right now."

        except Exception as e:
            logger.error(f"Error getting AI response: {e}")
            return "Sorry, I couldn't process that."

    async def _process_utterance(self, audio_data: np.ndarray):
        """Process recorded utterance through STT and get AI response"""
        try:
            # Transcribe
            transcript = await self.audio_session.process_utterance(audio_data)

            if transcript:
                # Notify callback
                if self.on_transcript:
                    self.on_transcript(transcript)

                # Get AI response from Sara backend
                response_text = await self._get_ai_response(transcript)

                # Get TTS
                tts_audio = await self.wyoming_client.synthesize_speech(response_text)

                if tts_audio:
                    # Play TTS
                    self._set_state(VoiceAgentState.SPEAKING)
                    self.tts_player.play_audio_bytes(tts_audio)
                else:
                    # No TTS, back to listening
                    self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
            else:
                # No transcript, back to listening
                self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

        except Exception as e:
            logger.error(f"Error processing utterance: {e}")
            self._set_state(VoiceAgentState.ERROR)
            time.sleep(1)
            self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

    def _on_transcript_received(self, transcript: str):
        """Handle transcript from Wyoming"""
        logger.info(f"📝 Transcript: {transcript}")

    def _on_tts_start(self):
        """Callback when TTS playback starts"""
        logger.debug("🔊 TTS playback started")
        # Enable echo suppression
        self.echo_suppressor.start_suppression()

    def _on_tts_end(self):
        """Callback when TTS playback ends"""
        logger.info("✅ TTS playback ended")

        try:
            # Add small delay to let audio settle
            time.sleep(0.3)

            # Disable echo suppression
            self.echo_suppressor.stop_suppression()

            # Clear pre-roll buffer to avoid TTS contamination
            if self.pre_roll_buffer:
                self.pre_roll_buffer.clear()

            # Check if we're in conversation mode
            if self.in_conversation_mode:
                # Stay in conversation - wait for user to speak (no wake word needed)
                logger.info("💬 Conversation mode active - waiting for your response...")
                logger.info(f"   (Will return to wake word mode after {self.conversation_mode_timeout}s of silence)")

                # Suppress wake word for 1.5 seconds to prevent TTS echo
                self.suppress_wake_word_until = time.time() + 1.5

                # Reset VAD for next speech detection
                self.vad.reset()

                # Transition to waiting for speech
                self.waiting_for_speech_start_time = time.time()
                self._set_state(VoiceAgentState.WAITING_FOR_SPEECH)

                # Shorter wait for echo to settle in conversation mode
                time.sleep(0.5)

            else:
                # Not in conversation mode - back to wake word
                self.suppress_wake_word_until = time.time() + 1.5
                logger.debug("🔇 Suppressing wake word detection for 1.5 seconds (TTS echo prevention)")

                # Reset wake word detector
                if self.wake_detector:
                    logger.debug("Resetting wake word detector debounce")
                    self.wake_detector.reset_debounce()

                self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)
                time.sleep(0.5)
                logger.info("🎧 Ready for next wake word...")

        except Exception as e:
            logger.error(f"Error in TTS end callback: {e}")
            # Force back to listening state even if error
            self.suppress_wake_word_until = 0
            self.in_conversation_mode = False
            self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

    def _set_state(self, new_state: VoiceAgentState):
        """Set agent state and notify callback"""
        if new_state != self.state:
            old_state = self.state.value
            self.state = new_state
            logger.info(f"🔄 State: {old_state} → {new_state.value}")

            if self.on_state_change:
                self.on_state_change(new_state)

    def set_voice_mode(self, mode: VoiceMode):
        """Change voice operating mode"""
        logger.info(f"Voice mode changed: {self.voice_mode.value} → {mode.value}")
        self.voice_mode = mode

    def set_shadow_session_active(self, active: bool):
        """Notify agent of Shadow session state (for shadow_only mode)"""
        self.is_shadow_session_active = active
        logger.info(f"Shadow session active: {active}")

    def trigger_manual_listen(self):
        """Manually trigger listening (for PTT mode)"""
        if self.voice_mode == VoiceMode.PUSH_TO_TALK:
            logger.info("Manual listen triggered (PTT)")
            self._on_wake_word_detected()

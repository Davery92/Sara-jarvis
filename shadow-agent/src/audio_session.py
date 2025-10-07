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

from wake_word import WakeWordDetector
from audio_buffer import PreRollBuffer
from audio_capture import AudioCapture
from vad import VoiceActivityDetector, RecordingWindow
from wyoming_client import WyomingClient, AudioStreamSession
from tts_playback import TTSPlayer, EchoSuppressor

logger = logging.getLogger(__name__)


class VoiceAgentState(Enum):
    """Voice agent states"""
    IDLE = "idle"
    LISTENING_FOR_WAKE = "listening_for_wake"
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

        # Event loop for async operations
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self):
        """Start the voice agent"""
        if self.is_running:
            logger.warning("Voice agent already running")
            return

        logger.info("🚀 Starting voice agent...")

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

        self._set_state(VoiceAgentState.IDLE)
        logger.info("Voice agent stopped")

    def _initialize_components(self):
        """Initialize all voice components"""
        # Wake word detector
        self.wake_detector = WakeWordDetector(threshold=0.5)

        # Pre-roll buffer
        self.pre_roll_buffer = PreRollBuffer(duration_seconds=1.5)

        # Audio capture
        self.audio_capture = AudioCapture(sample_rate=16000, blocksize=1280)

        # VAD
        self.vad = VoiceActivityDetector()

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
            # Check for wake word
            detection = self.wake_detector.process_chunk(audio_chunk)

            if detection:
                # Wake word detected!
                logger.info(f"🎤 Wake word detected: {detection['name']} (score: {detection['score']:.2f})")
                self._on_wake_word_detected()

        elif self.state == VoiceAgentState.RECORDING:
            # Process with VAD
            self.recording_window.process_chunk(audio_chunk)

        elif self.state == VoiceAgentState.SPEAKING:
            # Check for barge-in (user speaking while Sara is talking)
            vad_result = self.vad.process_chunk(audio_chunk)
            if vad_result['speech_started']:
                logger.info("👤 Barge-in detected!")
                self.tts_player.stop()
                self._on_wake_word_detected()  # Start new utterance

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
        # Transition to recording state
        self._set_state(VoiceAgentState.RECORDING)

        # Reset VAD and recording window
        self.vad.reset()
        self.recording_window.reset()

        # Get pre-roll buffer and inject it
        pre_roll_audio = self.pre_roll_buffer.get_buffer()
        if len(pre_roll_audio) > 0:
            logger.debug(f"Injecting {len(pre_roll_audio)/16000:.2f}s of pre-roll audio")
            # Process pre-roll through VAD to kickstart recording
            for i in range(0, len(pre_roll_audio), 1280):
                chunk = pre_roll_audio[i:i+1280]
                if len(chunk) == 1280:
                    self.recording_window.process_chunk(chunk)

    def _on_recording_start(self):
        """Callback when VAD starts recording"""
        logger.info("🔴 Recording started")

    def _on_recording_stop(self, audio_data: np.ndarray):
        """Callback when VAD stops recording"""
        logger.info(f"⏹️ Recording stopped ({len(audio_data)/16000:.2f}s)")

        # Transition to processing
        self._set_state(VoiceAgentState.PROCESSING)

        # Send to STT (async)
        asyncio.run(self._process_utterance(audio_data))

    async def _process_utterance(self, audio_data: np.ndarray):
        """Process recorded utterance through STT"""
        try:
            # Transcribe
            transcript = await self.audio_session.process_utterance(audio_data)

            if transcript:
                # Notify callback
                if self.on_transcript:
                    self.on_transcript(transcript)

                # For now, echo back (later: full Sara integration)
                response_text = f"You said: {transcript}"

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
        logger.debug("✅ TTS playback ended")
        # Disable echo suppression
        self.echo_suppressor.stop_suppression()

        # Back to listening for wake word
        self._set_state(VoiceAgentState.LISTENING_FOR_WAKE)

    def _set_state(self, new_state: VoiceAgentState):
        """Set agent state and notify callback"""
        if new_state != self.state:
            logger.debug(f"State: {self.state.value} → {new_state.value}")
            self.state = new_state

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

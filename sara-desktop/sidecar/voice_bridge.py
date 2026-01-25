"""
Voice Bridge - Connects to Jetson voice agent for audio playback.

Receives audio from the Jetson voice agent via WebSocket and plays it locally.
Sends playback_complete events back to prevent echo detection.
Reports voice state changes to Electron for tray icon updates.
Bridges voice transcripts to Sara's cognitive raw buffer.
"""

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from config import SidecarConfig

logger = logging.getLogger("voice_bridge")

# HTTP client for backend communication
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not available - raw buffer bridge disabled")

# Audio playback
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    logger.warning("sounddevice not available - voice bridge disabled")
    logger.warning("Install with: pip install sounddevice numpy")

# WebSocket client
try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets not available - voice bridge disabled")


class VoiceState:
    """Voice agent states for tray icon colors."""
    DISCONNECTED = "disconnected"  # Red
    CONNECTED = "connected"        # Green (idle)
    WAKE_WORD = "wake_word"        # Yellow (listening)
    SPEAKING = "speaking"          # Blue


class VoiceBridge:
    """
    Connects to Jetson voice agent and handles audio playback.

    The Jetson runs the wake word detection, STT, Sara API, and TTS.
    This bridge receives the TTS audio and plays it on the local machine.
    """

    def __init__(
        self,
        host: str = "10.185.1.155",
        port: int = 8765,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_transcript: Optional[Callable[[str, str], None]] = None,
        config: Optional["SidecarConfig"] = None,
    ):
        """
        Initialize the voice bridge.

        Args:
            host: Jetson IP address
            port: WebSocket port on Jetson
            on_state_change: Callback when voice state changes (for tray icon)
            on_transcript: Callback for transcripts (user_text, sara_response)
            config: Sidecar configuration for backend communication
        """
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}"

        self.on_state_change = on_state_change
        self.on_transcript = on_transcript
        self.config = config

        self.running = False
        self.connected = False
        self._state = VoiceState.DISCONNECTED

        # Audio playback
        self.audio_queue: queue.Queue = queue.Queue()
        self.sample_rate = 24000  # Kokoro TTS default
        self.is_speaking = False

        # For sending messages back to Jetson
        self._outgoing_queue: Optional[asyncio.Queue] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # Audio thread
        self._audio_thread: Optional[threading.Thread] = None

        # HTTP client for raw buffer
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def state(self) -> str:
        return self._state

    @state.setter
    def state(self, value: str):
        if self._state != value:
            self._state = value
            logger.info(f"Voice state: {value}")
            if self.on_state_change:
                try:
                    self.on_state_change(value)
                except Exception as e:
                    logger.error(f"State change callback error: {e}")

    def _audio_playback_thread(self):
        """
        Continuous audio playback thread.
        Detects when queue runs dry to signal playback complete.
        """
        if not AUDIO_AVAILABLE:
            return

        logger.info("Audio playback thread started")

        QUEUE_TIMEOUT = 0.3
        SILENCE_THRESHOLD = 0.5  # 500ms of no audio = done
        queue_empty_since = None

        try:
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                blocksize=4096
            ) as stream:
                while self.running:
                    try:
                        chunk = self.audio_queue.get(timeout=QUEUE_TIMEOUT)
                        queue_empty_since = None

                        # Play the audio
                        audio_data = np.frombuffer(chunk, dtype=np.int16)
                        stream.write(audio_data)

                    except queue.Empty:
                        if self.is_speaking:
                            if queue_empty_since is None:
                                queue_empty_since = time.time()

                            empty_duration = time.time() - queue_empty_since
                            if empty_duration >= SILENCE_THRESHOLD:
                                logger.info("Playback complete")
                                self.is_speaking = False
                                self.state = VoiceState.CONNECTED
                                self._send_playback_complete()
                                queue_empty_since = None
                        continue

                    except Exception as e:
                        logger.error(f"Playback error: {e}")

        except Exception as e:
            logger.error(f"Audio device error: {e}")

    def _send_playback_complete(self):
        """Send playback_complete message to Jetson."""
        if self._main_loop and self._outgoing_queue:
            msg = json.dumps({"event": "playback_complete"})
            try:
                asyncio.run_coroutine_threadsafe(
                    self._outgoing_queue.put(msg),
                    self._main_loop
                )
            except Exception as e:
                logger.error(f"Error sending completion signal: {e}")

    async def start(self):
        """Start the voice bridge."""
        if not AUDIO_AVAILABLE or not WEBSOCKETS_AVAILABLE:
            logger.warning("Voice bridge not starting - missing dependencies")
            return

        logger.info(f"Starting voice bridge to {self.ws_url}")
        self.running = True

        # Initialize HTTP client for raw buffer communication
        if HTTPX_AVAILABLE and self.config and self.config.auth_token:
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                headers={"Authorization": f"Bearer {self.config.auth_token}"}
            )
            logger.info("Raw buffer bridge enabled")

        # Start audio playback thread
        self._audio_thread = threading.Thread(
            target=self._audio_playback_thread,
            daemon=True
        )
        self._audio_thread.start()

        # Run WebSocket connection loop
        await self._connection_loop()

    async def stop(self):
        """Stop the voice bridge."""
        logger.info("Stopping voice bridge")
        self.running = False
        self.state = VoiceState.DISCONNECTED

        # Close HTTP client
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _send_to_raw_buffer(self, user_text: str, sara_text: Optional[str] = None):
        """
        Send voice transcript to Sara's cognitive raw buffer.

        This bridges the voice conversation to the Phase 1+ cognitive architecture
        so Sara can maintain awareness of voice interactions.
        """
        if not self._http_client or not self.config:
            return

        try:
            response = await self._http_client.post(
                f"{self.config.backend_url}/api/cognitive/raw-buffer/audio",
                json={
                    "user_text": user_text,
                    "sara_response": sara_text,
                    "source": "voice_bridge"
                }
            )
            response.raise_for_status()
            logger.debug(f"Voice transcript sent to raw buffer: {len(user_text)} chars")

        except Exception as e:
            # Don't fail voice bridge if raw buffer is unavailable
            logger.warning(f"Could not send transcript to raw buffer: {e}")

    async def _signal_wake_word(self):
        """
        Signal wake word detection to the mode controller.

        This triggers the transition from ambient to active mode.
        """
        if not self._http_client or not self.config:
            return

        try:
            response = await self._http_client.post(
                f"{self.config.backend_url}/api/cognitive/mode/wake-word"
            )
            response.raise_for_status()
            logger.debug("Wake word signaled to mode controller")

        except Exception as e:
            logger.warning(f"Could not signal wake word: {e}")

    async def _connection_loop(self):
        """Main WebSocket connection loop with auto-reconnect."""
        self._main_loop = asyncio.get_running_loop()
        self._outgoing_queue = asyncio.Queue()

        while self.running:
            try:
                logger.info(f"Connecting to {self.ws_url}...")
                self.state = VoiceState.DISCONNECTED

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    logger.info("Connected to Jetson voice agent")
                    self.connected = True
                    self.state = VoiceState.CONNECTED

                    # Run receive and send tasks concurrently
                    receive_task = asyncio.create_task(self._receive_loop(ws))
                    send_task = asyncio.create_task(self._send_loop(ws))

                    done, pending = await asyncio.wait(
                        [receive_task, send_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
            except ConnectionRefusedError:
                logger.warning("Connection refused - Jetson voice agent not running?")
            except Exception as e:
                logger.error(f"Connection error: {e}")

            self.connected = False
            self.state = VoiceState.DISCONNECTED

            if self.running:
                logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def _receive_loop(self, ws):
        """Receive messages from Jetson."""
        async for message in ws:
            if isinstance(message, bytes):
                # Audio data - queue for playback
                self.audio_queue.put(message)

                if not self.is_speaking:
                    self.is_speaking = True
                    self.state = VoiceState.SPEAKING
            else:
                # JSON event
                try:
                    event = json.loads(message)
                    self._handle_event(event)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message[:100]}")

    async def _send_loop(self, ws):
        """Send messages to Jetson."""
        while True:
            msg = await self._outgoing_queue.get()
            await ws.send(msg)
            self._outgoing_queue.task_done()

    def _handle_event(self, event: dict):
        """Handle JSON events from Jetson."""
        event_type = event.get("event", "")

        if event_type == "speaking_start":
            text = event.get("text", "")
            logger.info(f"Sara: {text[:80]}...")
            self.is_speaking = True
            self.state = VoiceState.SPEAKING

        elif event_type == "wake_word":
            logger.info("Wake word detected!")
            self.state = VoiceState.WAKE_WORD

            # Signal mode transition to backend
            asyncio.create_task(self._signal_wake_word())

        elif event_type == "transcript":
            # User's transcribed speech
            user_text = event.get("user", "")
            sara_text = event.get("sara", "")

            # Send to raw buffer for cognitive architecture
            if user_text:
                asyncio.create_task(self._send_to_raw_buffer(user_text, sara_text))

            if self.on_transcript:
                try:
                    self.on_transcript(user_text, sara_text)
                except Exception as e:
                    logger.error(f"Transcript callback error: {e}")

        elif event_type == "listening":
            # Actively listening for speech
            self.state = VoiceState.WAKE_WORD

        elif event_type == "idle":
            # Back to idle state
            self.state = VoiceState.CONNECTED


# Convenience function to check if voice bridge is available
def is_available() -> bool:
    return AUDIO_AVAILABLE and WEBSOCKETS_AVAILABLE

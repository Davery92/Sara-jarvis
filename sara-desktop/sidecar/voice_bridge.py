"""
Voice Bridge - Connects to Jetson voice agent for audio playback.

Receives audio from the Jetson voice agent via WebSocket and plays it locally.
Sends playback_complete events back to prevent echo detection.
Reports voice state changes to Electron for tray icon updates.
Bridges voice transcripts to Sara's cognitive raw buffer.
"""

import asyncio
import io
import json
import logging
import os
import queue
import sys
import threading
import time
import wave
from typing import Callable, Optional, TYPE_CHECKING
from uuid import uuid4

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

# Windows native fallback playback
try:
    if sys.platform == "win32":
        import winsound
        WINSOUND_AVAILABLE = True
    else:
        WINSOUND_AVAILABLE = False
except Exception:
    WINSOUND_AVAILABLE = False


class VoiceState:
    """Voice agent states for tray icon colors."""
    DISCONNECTED = "disconnected"  # Red
    CONNECTED = "connected"        # Green (idle)
    WAKE_WORD = "wake_word"        # Yellow (listening)
    SPEAKING = "speaking"          # Blue
    CONVERSATION = "conversation"  # Cyan (multi-turn)


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
        self._in_conversation = False  # Multi-turn conversation active
        self._stream_sample_rate = self.sample_rate
        self._stream_channels = 1
        self._stream_device = None
        backend_pref = str(os.getenv("SARA_VOICE_PLAYBACK_BACKEND", "auto")).strip().lower()
        self._playback_backend_order = self._resolve_backend_order(backend_pref)
        self._playback_backend = self._playback_backend_order[0] if self._playback_backend_order else "none"
        self._fallback_backend = self._playback_backend_order[1] if len(self._playback_backend_order) > 1 else None

        # For sending messages back to Jetson
        self._outgoing_queue: Optional[asyncio.Queue] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # Audio thread
        self._audio_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._playback_stall_seconds = float(os.getenv("SARA_VOICE_PLAYBACK_STALL_SECONDS", "12.0"))

        # Echo state reporting
        self._echo_report_interval = 1.0  # Report echo state every 1s during playback
        self._last_echo_report = 0.0

        # HTTP client for raw buffer
        self._http_client: Optional[httpx.AsyncClient] = None

        # Playback session telemetry/state
        self._playback_lock = threading.Lock()
        self._pending_utterance_id: Optional[str] = None
        self._active_utterance_id: Optional[str] = None
        self._active_chunk_count = 0
        self._active_total_bytes = 0
        self._active_started_at = 0.0
        self._active_last_progress_at = 0.0
        self._completion_sent = False

    def _resolve_backend_order(self, backend_pref: str) -> list[str]:
        """Resolve playback backend order based on preference and availability."""
        available: list[str] = []
        if AUDIO_AVAILABLE:
            available.append("sounddevice")
        if WINSOUND_AVAILABLE:
            available.append("winsound")

        if not available:
            return []

        if backend_pref in {"", "auto"}:
            # Prefer sounddevice first on Windows to avoid winsound blocking behavior.
            preferred = ["sounddevice", "winsound"]
        elif backend_pref in {"sounddevice", "winsound"}:
            secondary = "winsound" if backend_pref == "sounddevice" else "sounddevice"
            preferred = [backend_pref, secondary]
        else:
            logger.warning("Unknown SARA_VOICE_PLAYBACK_BACKEND=%s, using auto", backend_pref)
            preferred = ["sounddevice", "winsound"]

        order = [backend for backend in preferred if backend in available]
        for backend in available:
            if backend not in order:
                order.append(backend)
        return order

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
                    if self._main_loop and self._main_loop.is_running():
                        self._main_loop.call_soon_threadsafe(self.on_state_change, value)
                    else:
                        self.on_state_change(value)
                except Exception as e:
                    logger.error(f"State change callback error: {e}")

    @staticmethod
    def _safe_log_snippet(text: str, limit: int = 80) -> str:
        """Return a console-safe snippet that won't explode on cp1252 consoles."""
        snippet = (text or "")[:limit]
        return snippet.encode("ascii", errors="replace").decode("ascii")

    def _flush_audio_queue(self):
        """Flush all pending audio from the queue (for barge-in/stop)."""
        flushed = 0
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        if flushed:
            logger.info(f"Flushed {flushed} audio chunks from queue")

    def _new_utterance_id(self) -> str:
        return f"utt-{uuid4().hex[:12]}"

    def _send_playback_event(self, event: str, payload: Optional[dict] = None, utterance_id: Optional[str] = None):
        """Send playback diagnostics to Jetson."""
        if not self._main_loop or not self._outgoing_queue:
            return

        msg = {
            "event": event,
            "timestamp": time.time(),
        }
        resolved_utterance = utterance_id or self._active_utterance_id or self._pending_utterance_id
        if resolved_utterance:
            msg["utterance_id"] = resolved_utterance
        if payload:
            msg.update(payload)

        try:
            asyncio.run_coroutine_threadsafe(
                self._outgoing_queue.put(json.dumps(msg)),
                self._main_loop
            )
        except Exception as e:
            logger.debug("Error sending playback event %s: %s", event, e)

    def _begin_playback_session(self):
        """Start a new playback session for telemetry + completion tracking."""
        with self._playback_lock:
            if self.is_speaking:
                return

            self.is_speaking = True
            self.state = VoiceState.SPEAKING
            self._active_utterance_id = self._pending_utterance_id or self._new_utterance_id()
            self._pending_utterance_id = None
            self._active_chunk_count = 0
            self._active_total_bytes = 0
            self._active_started_at = time.time()
            self._active_last_progress_at = self._active_started_at
            self._completion_sent = False

        self._send_playback_event(
            "playback_started",
            {
                "backend": self._playback_backend,
                "sample_rate": self.sample_rate,
            },
        )

    def _track_received_chunk(self, chunk_size: int):
        """Track and report incoming audio chunk."""
        if not self.is_speaking:
            self._begin_playback_session()

        with self._playback_lock:
            self._active_chunk_count += 1
            self._active_total_bytes += chunk_size
            self._active_last_progress_at = time.time()
            chunk_index = self._active_chunk_count
            utterance_id = self._active_utterance_id

        self._send_playback_event(
            "chunk_received",
            {
                "chunk_index": chunk_index,
                "chunk_bytes": chunk_size,
                "queue_depth": self.audio_queue.qsize(),
            },
            utterance_id=utterance_id,
        )

    def _mark_playback_progress(self):
        with self._playback_lock:
            if self.is_speaking:
                self._active_last_progress_at = time.time()

    def _finish_playback(self, reason: str, error: Optional[str] = None, force: bool = False):
        """Complete a playback session and emit playback_complete exactly once."""
        with self._playback_lock:
            has_active_session = (
                self.is_speaking
                or self._active_started_at > 0
                or self._active_chunk_count > 0
                or bool(self._pending_utterance_id)
            )
            if not has_active_session:
                return
            if self._completion_sent:
                return
            if not self.is_speaking and not force:
                return

            utterance_id = self._active_utterance_id or self._pending_utterance_id
            chunk_count = self._active_chunk_count
            total_bytes = self._active_total_bytes
            started_at = self._active_started_at

            self._completion_sent = True
            self.is_speaking = False
            self._active_utterance_id = None
            self._active_chunk_count = 0
            self._active_total_bytes = 0
            self._active_started_at = 0.0
            self._active_last_progress_at = 0.0

        duration_ms = 0
        if started_at > 0:
            duration_ms = int((time.time() - started_at) * 1000)

        if error:
            self._send_playback_event(
                "playback_error",
                {
                    "reason": reason,
                    "error": error,
                    "backend": self._playback_backend,
                },
                utterance_id=utterance_id,
            )

        self._send_playback_complete(
            utterance_id=utterance_id,
            reason=reason,
            chunk_count=chunk_count,
            total_bytes=total_bytes,
            duration_ms=duration_ms,
            error=error,
        )
        self._send_echo_state(False)

        if self._in_conversation:
            self.state = VoiceState.CONVERSATION
        else:
            self.state = VoiceState.CONNECTED

        if error:
            logger.error(
                "Playback finished with error (%s): utterance=%s chunks=%d bytes=%d duration=%dms backend=%s",
                reason,
                utterance_id,
                chunk_count,
                total_bytes,
                duration_ms,
                self._playback_backend,
            )
        else:
            logger.info(
                "Playback complete (%s): utterance=%s chunks=%d bytes=%d duration=%dms backend=%s",
                reason,
                utterance_id,
                chunk_count,
                total_bytes,
                duration_ms,
                self._playback_backend,
            )

    def _playback_watchdog_thread(self):
        """Ensure playback cannot hang forever without completion signals."""
        logger.info(
            "Playback watchdog started (stall timeout %.1fs)",
            self._playback_stall_seconds,
        )
        while self.running:
            try:
                if self.is_speaking:
                    with self._playback_lock:
                        last_progress = self._active_last_progress_at or self._active_started_at
                    if last_progress and self.audio_queue.empty():
                        stalled_for = time.time() - last_progress
                        if stalled_for >= self._playback_stall_seconds:
                            self._finish_playback(
                                reason="watchdog_timeout",
                                error=f"no_progress_for_{stalled_for:.1f}s",
                                force=True,
                            )
                time.sleep(0.5)
            except Exception as e:
                logger.debug("Playback watchdog error: %s", e)
                time.sleep(0.5)

    def _audio_playback_thread(self):
        """
        Continuous audio playback thread.
        Detects when queue runs dry to signal playback complete.
        Supports flush for barge-in via stop_playback command.
        """
        if not self._playback_backend_order:
            logger.error("No audio playback backend available")
            return

        logger.info("Audio playback backend order: %s", " -> ".join(self._playback_backend_order))

        while self.running:
            active_backend = self._playback_backend
            if active_backend == "winsound":
                self._audio_playback_thread_winsound()
            else:
                self._audio_playback_thread_sounddevice()

            if not self.running:
                break

            if self._fallback_backend and self._playback_backend == active_backend:
                logger.warning(
                    "Switching playback backend from %s to fallback %s",
                    active_backend,
                    self._fallback_backend,
                )
                self._playback_backend = self._fallback_backend
                self._fallback_backend = None
                continue

            time.sleep(1.0)

    def _audio_playback_thread_sounddevice(self):
        """Primary playback loop using sounddevice."""
        if not AUDIO_AVAILABLE:
            logger.error("sounddevice backend unavailable")
            if self._fallback_backend:
                self._playback_backend = self._fallback_backend
                self._fallback_backend = None
            return

        logger.info("Audio playback thread started (sounddevice backend)")

        QUEUE_TIMEOUT = 0.3
        SILENCE_THRESHOLD = 0.5  # 500ms of no audio = done
        queue_empty_since = None

        while self.running:
            try:
                self._configure_output_stream()
                logger.info(
                    "Opening audio output stream: device=%s, rate=%s, channels=%s",
                    self._stream_device,
                    self._stream_sample_rate,
                    self._stream_channels,
                )

                with sd.OutputStream(
                    samplerate=self._stream_sample_rate,
                    channels=self._stream_channels,
                    dtype="float32",
                    blocksize=4096,
                    device=self._stream_device,
                ) as stream:
                    logger.info("Audio output stream ready")

                    while self.running:
                        try:
                            chunk = self.audio_queue.get(timeout=QUEUE_TIMEOUT)
                            queue_empty_since = None

                            # Play audio with format/rate adaptation when needed.
                            audio_data = self._prepare_audio_chunk(chunk)
                            if audio_data.size == 0:
                                continue
                            stream.write(audio_data)
                            self._mark_playback_progress()

                            # Periodic echo state reporting during playback
                            now = time.time()
                            if now - self._last_echo_report >= self._echo_report_interval:
                                self._send_echo_state(True)
                                self._last_echo_report = now

                        except queue.Empty:
                            if self.is_speaking:
                                if queue_empty_since is None:
                                    queue_empty_since = time.time()

                                empty_duration = time.time() - queue_empty_since
                                if empty_duration >= SILENCE_THRESHOLD:
                                    self._finish_playback(reason="queue_dry")
                                    queue_empty_since = None
                            continue

                        except Exception as e:
                            self._finish_playback(reason="chunk_error", error=str(e), force=True)

            except Exception as e:
                logger.error("Audio device error: %s", e)
                self._flush_audio_queue()
                self._finish_playback(reason="device_error", error=str(e), force=True)
                if self._fallback_backend:
                    logger.warning("sounddevice failed, switching to fallback backend %s", self._fallback_backend)
                    self._playback_backend = self._fallback_backend
                    self._fallback_backend = None
                    return
                time.sleep(2.0)

    def _play_chunk_winsound(self, chunk: bytes):
        """Play a PCM chunk with Windows native audio backend."""
        if not chunk:
            return

        wav_bytes = io.BytesIO()
        with wave.open(wav_bytes, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # int16 PCM
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(chunk)

        # Synchronous playback is default when SND_ASYNC is omitted.
        winsound.PlaySound(wav_bytes.getvalue(), winsound.SND_MEMORY)

    def _audio_playback_thread_winsound(self):
        """Fallback playback loop using Windows native winsound."""
        if not WINSOUND_AVAILABLE:
            logger.error("winsound backend unavailable")
            if self._fallback_backend:
                self._playback_backend = self._fallback_backend
                self._fallback_backend = None
            return

        logger.info("Audio playback thread started (winsound backend)")

        QUEUE_TIMEOUT = 0.3
        SILENCE_THRESHOLD = 0.5
        queue_empty_since = None

        while self.running:
            try:
                try:
                    chunk = self.audio_queue.get(timeout=QUEUE_TIMEOUT)
                    queue_empty_since = None

                    self._play_chunk_winsound(chunk)
                    self._mark_playback_progress()

                    now = time.time()
                    if now - self._last_echo_report >= self._echo_report_interval:
                        self._send_echo_state(True)
                        self._last_echo_report = now

                except queue.Empty:
                    if self.is_speaking:
                        if queue_empty_since is None:
                            queue_empty_since = time.time()

                        empty_duration = time.time() - queue_empty_since
                        if empty_duration >= SILENCE_THRESHOLD:
                            self._finish_playback(reason="queue_dry")
                            queue_empty_since = None
                    continue

            except Exception as e:
                logger.error("Winsound playback error: %s", e)
                self._flush_audio_queue()
                self._finish_playback(reason="winsound_error", error=str(e), force=True)
                if self._fallback_backend:
                    logger.warning("winsound failed, switching to fallback backend %s", self._fallback_backend)
                    self._playback_backend = self._fallback_backend
                    self._fallback_backend = None
                    return
                time.sleep(1.0)

    def _configure_output_stream(self):
        """Resolve output stream config that works on this host."""
        self._stream_sample_rate = self.sample_rate
        self._stream_channels = 1
        self._stream_device = None

        default_output = None
        try:
            default_devices = sd.default.device
            if isinstance(default_devices, (tuple, list)) and len(default_devices) >= 2:
                default_output = default_devices[1]
            elif isinstance(default_devices, int):
                default_output = default_devices
        except Exception:
            default_output = None

        try:
            info = sd.query_devices(default_output, "output")
            max_channels = int(info.get("max_output_channels", 1) or 1)
            self._stream_channels = 2 if max_channels >= 2 else 1

            # Prefer native 24k. Fallback to device default if not supported.
            try:
                sd.check_output_settings(
                    device=default_output,
                    samplerate=self.sample_rate,
                    channels=self._stream_channels,
                    dtype="float32",
                )
                self._stream_sample_rate = self.sample_rate
            except Exception:
                fallback_rate = int(info.get("default_samplerate", 48000) or 48000)
                sd.check_output_settings(
                    device=default_output,
                    samplerate=fallback_rate,
                    channels=self._stream_channels,
                    dtype="float32",
                )
                self._stream_sample_rate = fallback_rate

            self._stream_device = default_output
        except Exception as e:
            logger.warning("Falling back to default audio stream settings: %s", e)

    def _prepare_audio_chunk(self, chunk: bytes):
        """Convert int16 mono PCM@24k to stream format/rate."""
        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        if audio.size == 0:
            return np.zeros((0, self._stream_channels), dtype=np.float32)

        # Normalize to [-1, 1].
        audio = audio / 32768.0

        # Resample when output stream rate differs from incoming TTS rate.
        if self._stream_sample_rate != self.sample_rate and audio.size > 1:
            new_len = int(round(audio.size * self._stream_sample_rate / self.sample_rate))
            new_len = max(1, new_len)
            old_x = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
            new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
            audio = np.interp(new_x, old_x, audio).astype(np.float32)

        # Expand mono to configured output channels.
        if self._stream_channels > 1:
            audio = np.repeat(audio[:, None], self._stream_channels, axis=1)
        else:
            audio = audio.reshape(-1, 1)

        return audio

    def _send_playback_complete(
        self,
        utterance_id: Optional[str] = None,
        reason: str = "queue_dry",
        chunk_count: int = 0,
        total_bytes: int = 0,
        duration_ms: int = 0,
        error: Optional[str] = None,
    ):
        """Send playback_complete message to Jetson."""
        if self._main_loop and self._outgoing_queue:
            payload = {
                "event": "playback_complete",
                "reason": reason,
                "chunk_count": chunk_count,
                "total_bytes": total_bytes,
                "duration_ms": duration_ms,
                "backend": self._playback_backend,
            }
            if utterance_id:
                payload["utterance_id"] = utterance_id
            if error:
                payload["error"] = error

            msg = json.dumps(payload)
            try:
                asyncio.run_coroutine_threadsafe(
                    self._outgoing_queue.put(msg),
                    self._main_loop
                )
            except Exception as e:
                logger.error(f"Error sending completion signal: {e}")

    def _send_echo_state(self, is_playing: bool):
        """Send echo state to Jetson for AEC coordination."""
        if self._main_loop and self._outgoing_queue:
            msg = json.dumps({
                "event": "echo_state",
                "is_playing": is_playing,
                "timestamp": time.time(),
            })
            try:
                asyncio.run_coroutine_threadsafe(
                    self._outgoing_queue.put(msg),
                    self._main_loop
                )
            except Exception as e:
                logger.debug(f"Error sending echo state: {e}")

    def _send_stop_confirmed(self):
        """Send stop_confirmed after flushing audio queue."""
        if self._main_loop and self._outgoing_queue:
            msg = json.dumps({"event": "stop_confirmed"})
            try:
                asyncio.run_coroutine_threadsafe(
                    self._outgoing_queue.put(msg),
                    self._main_loop
                )
            except Exception as e:
                logger.debug(f"Error sending stop confirmed: {e}")

    async def start(self):
        """Start the voice bridge."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("Voice bridge not starting - missing websockets dependency")
            return
        if not self._playback_backend_order:
            logger.warning("Voice bridge not starting - no playback backends available")
            return

        logger.info(
            "Starting voice bridge to %s (backend=%s, fallback=%s, order=%s)",
            self.ws_url,
            self._playback_backend,
            self._fallback_backend,
            " -> ".join(self._playback_backend_order),
        )
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
        self._watchdog_thread = threading.Thread(
            target=self._playback_watchdog_thread,
            daemon=True,
        )
        self._watchdog_thread.start()

        # Run WebSocket connection loop
        await self._connection_loop()

    async def stop(self):
        """Stop the voice bridge."""
        logger.info("Stopping voice bridge")
        self.running = False
        self._finish_playback(reason="stop", force=True)
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
                self._track_received_chunk(len(message))
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
        event_type = event.get("event", event.get("type", ""))

        if event_type == "speaking_start":
            text = event.get("text", "")
            utterance_id = event.get("utterance_id")
            logger.info("Sara: %s...", self._safe_log_snippet(text, limit=80))
            if utterance_id:
                self._pending_utterance_id = utterance_id

        elif event_type == "playback_session":
            utterance_id = event.get("utterance_id")
            if utterance_id:
                self._pending_utterance_id = utterance_id
                logger.info("Playback session announced: %s", utterance_id)

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
            self._in_conversation = False
            self.state = VoiceState.CONNECTED

        elif event_type == "conversation_start":
            logger.info("Voice conversation started")
            self._in_conversation = True
            self.state = VoiceState.CONVERSATION

        elif event_type == "conversation_end":
            summary = event.get("summary", "")
            logger.info(f"Voice conversation ended: {summary[:80]}")
            self._in_conversation = False
            self.state = VoiceState.CONNECTED

        elif event_type == "stop_playback":
            # Barge-in: Jetson requests immediate audio flush
            logger.info("Stop playback requested (barge-in)")
            if self._playback_backend == "winsound" and WINSOUND_AVAILABLE:
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
            self._flush_audio_queue()
            self._finish_playback(reason="stop_playback", force=True)
            self._send_stop_confirmed()


# Convenience function to check if voice bridge is available
def is_available() -> bool:
    return (AUDIO_AVAILABLE or WINSOUND_AVAILABLE) and WEBSOCKETS_AVAILABLE

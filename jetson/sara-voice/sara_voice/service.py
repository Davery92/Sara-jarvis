"""Top-level service coordinator.

Wires all components together and manages the main voice+vision loop.
This is the brain of the Jetson agent.
"""

import asyncio
import logging
import time
from pathlib import Path

import numpy as np
import yaml

from sara_voice.audio.capture import AudioCapture
from sara_voice.audio.noise_gate import NoiseGate
from sara_voice.audio.wake_word import WakeWordDetector
from sara_voice.audio.vad import SileroVAD, VADState
from sara_voice.audio.stt import STTClient
from sara_voice.audio.aec import EchoCanceller
from sara_voice.audio.local_playback import LocalPlayback
from sara_voice.state.conversation import ConversationState, ConversationStateMachine
from sara_voice.state.echo_state import EchoStateTracker
from sara_voice.clients.backend import BackendClient
from sara_voice.clients.tts import TTSClient
from sara_voice.clients.desktop_bridge import DesktopBridge
from sara_voice.clients.raw_buffer import RawBufferClient
from sara_voice.clients.event_reporter import EventReporter
from sara_voice.clients.speaker_verification import SpeakerVerificationClient
from sara_voice.vision.camera import CameraCapture
from sara_voice.vision.face_detector import FaceDetector
from sara_voice.vision.presence import DeskPresence
from sara_voice.gpu.memory_manager import GPUMemoryManager
from sara_voice.gpu.priority_queue import GPUPriorityQueue, GPUPriority
from sara_voice.health.reporter import HealthReporter
from sara_voice.health.watchdog import SystemdWatchdog

logger = logging.getLogger(__name__)


class VoiceVisionService:
    """Main service that coordinates all voice and vision components."""

    # B2.5 interim stop-phrase fallback (until the dedicated "sara stop"
    # wake model, B3, makes this reachable from every state via audio alone).
    _STOP_PHRASES = frozenset({"stop", "stop sara", "sara stop"})

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = self._load_config(config_path)

        # ── Audio pipeline ──
        self.audio_capture = AudioCapture(self.config)
        self.noise_gate = NoiseGate(self.config)
        self.wake_word = WakeWordDetector(self.config)
        self.vad = SileroVAD(self.config)
        self.stt = STTClient(self.config)
        self.aec = EchoCanceller(self.config)
        self.local_playback = LocalPlayback(self.config)
        self._tts_sink = self.config.get("tts", {}).get("sink", "airhug")

        # ── State machines ──
        self.conversation = ConversationStateMachine(self.config)
        self.echo_state = EchoStateTracker(self.config)

        # ── Clients ──
        self.backend = BackendClient(self.config)
        self.tts = TTSClient(self.config)
        self.bridge = DesktopBridge(self.config)
        self.raw_buffer = RawBufferClient(self.config, self.backend)
        self.event_reporter = EventReporter(self.config, self.backend)
        self.speaker_verifier = SpeakerVerificationClient(self.config)

        # ── Vision ──
        self.camera = CameraCapture(self.config)
        self.face_detector = FaceDetector(self.config)
        self.presence = DeskPresence(self.config)

        # ── GPU ──
        self.gpu_manager = GPUMemoryManager(self.config)
        self.gpu_queue = GPUPriorityQueue(self.config)

        # ── Health ──
        self.health_reporter = HealthReporter(self.config, self.event_reporter, self.gpu_manager)
        self.watchdog = SystemdWatchdog(self.config)

        # ── Internal state ──
        self._conversation_start_time: float | None = None
        self._conversation_id: str | None = None
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_state_lock = asyncio.Lock()
        self._speech_end_in_flight = False
        self._barge_audio_buffer: list = []
        self._desktop_media_playing = False
        self._ambient_db_floor = self.config.get("noise_gate", {}).get("ambient_db_floor", -35.0)

        # B2.7 conversation watchdog — loop breaker of last resort.
        watchdog_cfg = self.config.get("conversation", {}).get("watchdog", {})
        self._watchdog_max_unverified_turns = watchdog_cfg.get("max_consecutive_unverified_turns", 4)
        self._watchdog_max_turns_window = watchdog_cfg.get("max_turns_per_window", 8)
        self._watchdog_window_seconds = watchdog_cfg.get("window_seconds", 180)
        self._watchdog_suppress_seconds = watchdog_cfg.get("suppress_seconds", 60)
        self._watchdog_turn_log: list = []  # (monotonic_ts, is_verified_david)

        # ── Wire callbacks ──
        self.conversation.on_state_change(self._on_conversation_state_change)
        self.presence.on_change(self._on_presence_change)
        self.bridge.set_echo_state_callback(self._on_echo_state)
        self.bridge.set_listening_change_callback(self._on_listening_changed)
        self.bridge.set_request_stop_callback(self._on_remote_stop_request)
        self.bridge.set_media_state_callback(self._on_media_state_changed)
        self.bridge.set_speak_proactive_callback(self._on_speak_proactive_request)

    @staticmethod
    def _load_config(path: str) -> dict:
        """Load YAML configuration."""
        config_path = Path(path)
        if not config_path.exists():
            logger.warning("Config file not found at %s, using defaults", path)
            return {}
        with open(config_path) as f:
            return yaml.safe_load(f) or {}

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    async def start(self):
        """Start all components."""
        logger.info("Starting Sara Voice + Vision Service...")
        self._loop = asyncio.get_running_loop()

        # 1. GPU initialization
        self.gpu_manager.initialize()

        # 2. Authenticate with backend
        if not await self.backend.authenticate():
            logger.error("Backend authentication failed — continuing in degraded mode")

        # 3. Start WebSocket bridge (desktop audio output)
        await self.bridge.start()

        # 4. Load models (CPU)
        self.wake_word.load()
        self.vad.load()

        # 5. Load vision models (GPU)
        vision_enabled = self.config.get("vision", {}).get("enabled", True)
        if vision_enabled:
            try:
                self.face_detector.load()
                self.camera.start()
            except Exception as e:
                logger.error("Vision startup failed (non-fatal): %s", e)

        # 6. Start audio capture
        self.audio_capture.start()
        self.audio_capture.add_listener(self._on_audio_chunk)

        # 7. Start background tasks
        self._tasks.append(asyncio.create_task(self._timeout_loop()))
        if vision_enabled:
            self._tasks.append(asyncio.create_task(self._vision_loop()))

        # 8. Start health + watchdog
        await self.health_reporter.start()
        await self.watchdog.start()
        self.watchdog.notify_status("Running — listening for wake word")

        logger.info("All components started successfully")

    async def stop(self):
        """Stop all components gracefully."""
        logger.info("Stopping all components...")

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Stop components
        self.audio_capture.stop()
        self.camera.stop()
        await self.bridge.stop()
        await self.stt.close()
        await self.tts.close()
        await self.speaker_verifier.close()
        await self.backend.close()
        await self.health_reporter.stop()
        await self.watchdog.stop()

        logger.info("All components stopped")

    # ──────────────────────────────────────────────────────────────────
    # Audio pipeline callback
    # ──────────────────────────────────────────────────────────────────

    def _on_audio_chunk(self, audio: np.ndarray):
        """Called for every 16kHz mono audio chunk from the capture.

        This runs in the audio thread — schedule async work on the event loop.
        """
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._process_audio(audio),
            )

    async def _process_audio(self, audio: np.ndarray):
        """Process an audio chunk through the pipeline."""
        try:
            # Serialize stateful wake/VAD processing to avoid race conditions
            # from concurrent callback tasks draining VAD buffers out-of-order.
            async with self._audio_state_lock:
                state = self.conversation.state

                # Apply noise gate
                audio = self.noise_gate.process(audio)

                # Apply echo cancellation
                audio = self.aec.process(audio)

                # ── IDLE: run wake word detection ──
                if state == ConversationState.IDLE:
                    if (
                        self.bridge.is_listening_enabled
                        and not self.echo_state.should_suppress_wake_word
                    ):
                        detected = self.wake_word.process(audio)
                        if detected:
                            await self._handle_wake_word()

                # ── LISTENING: run VAD ──
                elif state == ConversationState.LISTENING:
                    vad_state = self.vad.process(audio)
                    if vad_state == VADState.SPEECH_END and not self._speech_end_in_flight:
                        # Grab speech audio once and process on a separate task.
                        speech_audio = self.vad.get_speech_audio()
                        self._speech_end_in_flight = True
                        asyncio.ensure_future(
                            self._handle_speech_end_guarded(speech_audio)
                        )

                # ── SPEAKING: check for barge-in ──
                elif state == ConversationState.SPEAKING:
                    if not self.aec.is_suppressing:
                        self._barge_audio_buffer.append(audio)
                        # Cap the rolling buffer so it never grows past ~1s —
                        # only the tail matters for speaker verification.
                        max_samples = self.audio_capture.sample_rate
                        total = sum(len(c) for c in self._barge_audio_buffer)
                        while total > max_samples and len(self._barge_audio_buffer) > 1:
                            total -= len(self._barge_audio_buffer.pop(0))

                        confidence = self.vad.probe_confidence(audio)
                        if confidence is not None and self.conversation.check_barge_in(confidence):
                            snippet = np.concatenate(self._barge_audio_buffer)
                            self._barge_audio_buffer = []
                            asyncio.ensure_future(self._handle_barge_in(snippet))

                    # B2.5 interim escape hatch: "hey sara" heard while she's
                    # talking means "stop", not "start a new conversation" —
                    # until the dedicated "sara stop" model exists (B3).
                    if self.wake_word.process(audio, ignore_suppression=True):
                        logger.info("Wake word heard during SPEAKING — treating as stop")
                        asyncio.ensure_future(self._on_remote_stop_request())

                # ── COOLDOWN: check for continued speech ──
                elif state == ConversationState.COOLDOWN:
                    # B2.2: gate on echo_state so the TTS tail (still bleeding
                    # into the mic during tail_suppression_ms) can't extend
                    # the conversation on its own.
                    if not self.echo_state.should_suppress_stt:
                        vad_state = self.vad.process(audio)
                        if vad_state == VADState.SPEECH:
                            await self.conversation.on_cooldown_speech()

        except Exception:
            logger.exception("_process_audio error")

    async def _handle_speech_end_guarded(self, speech_audio: np.ndarray):
        """Ensure only one speech-end handler can run at a time."""
        try:
            await self._handle_speech_end(speech_audio)
        finally:
            self._speech_end_in_flight = False

    # ──────────────────────────────────────────────────────────────────
    # Event handlers
    # ──────────────────────────────────────────────────────────────────

    async def _handle_wake_word(self):
        """Handle wake word detection."""
        logger.info("Wake word detected!")

        # Suppress further detections
        self.wake_word.suppress()

        # Notify backend
        asyncio.ensure_future(self.event_reporter.report_conversation_started())

        # Notify desktop
        await self.bridge.send_conversation_start()

        # Record conversation start
        self._conversation_start_time = time.time()

        # Transition state
        await self.conversation.on_wake_word()

        # B4: local chime + desktop orb flash within 300ms — the audible/
        # visible confirmation that "hey sara" landed. Fire-and-forget so it
        # overlaps the wake confirmation delay instead of extending it.
        asyncio.ensure_future(self.local_playback.play_chime())

        # Brief wake confirmation delay, then start listening
        await asyncio.sleep(self.config.get("conversation", {}).get("wake_confirmation_ms", 300) / 1000)
        await self.conversation.on_wake_confirmation_done()

        # Activate VAD
        self.vad.activate()

        self.watchdog.notify_status("Listening...")

    async def _handle_speech_end(self, speech_audio: np.ndarray | None = None):
        """Handle end of speech detected by VAD."""
        if speech_audio is None:
            speech_audio = self.vad.get_speech_audio()
        if len(speech_audio) == 0:
            logger.warning("Empty speech audio from VAD; re-arming VAD")
            self.vad.activate()
            return

        # Transcribe
        self.watchdog.notify_status("Transcribing...")
        transcript = await self.stt.transcribe(speech_audio)
        if not transcript:
            logger.warning("Empty transcript from STT")
            self.vad.activate()  # Re-activate VAD for another try
            return

        logger.info("Transcript: '%s'", transcript)

        # B2.5 interim escape hatch: a bare "stop"/"stop sara" utterance in
        # LISTENING aborts immediately instead of round-tripping to the
        # backend as a real query — until the dedicated "sara stop" model
        # (B3) makes this reachable from every state, not just LISTENING.
        stripped = transcript.strip().lower().rstrip(".!?")
        if stripped in self._STOP_PHRASES:
            logger.info("Stop phrase heard in LISTENING — aborting")
            await self._on_remote_stop_request()
            return

        duration = len(speech_audio) / self.audio_capture.sample_rate
        speaker, diarization = await self._infer_speaker_metadata(speech_audio, duration)

        if await self._check_conversation_watchdog(speaker == "david"):
            return

        # Transition to processing
        await self.conversation.on_speech_end(transcript)

        if self.conversation.state == ConversationState.IDLE:
            # Goodbye detected: state callback will handle end-of-conversation cleanup.
            return

        # Get response from Sara backend
        self.watchdog.notify_status("Thinking...")
        await self._get_and_speak_response(
            transcript,
            duration_seconds=duration,
            speaker=speaker,
            diarization=diarization,
        )

    async def _infer_speaker_metadata(
        self,
        speech_audio: np.ndarray,
        duration_seconds: float,
    ) -> tuple[str, dict]:
        """Infer primary speaker + diarization metadata for an utterance."""
        default_speaker = "david"
        if len(speech_audio) == 0:
            return default_speaker, {}

        verification = await self.speaker_verifier.verify(speech_audio)
        confidence = float(verification.get("confidence", 0.0))
        is_match = bool(verification.get("is_match", False))
        if verification.get("error"):
            speaker = default_speaker
        else:
            speaker = default_speaker if is_match else "unknown"

        diarization = {
            "num_speakers": 1,
            "speaker_labels": [speaker],
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": duration_seconds,
                    "speaker_id": speaker,
                    "confidence": confidence,
                }
            ],
            "verification": {
                "target_speaker": verification.get("speaker_id", "david"),
                "is_match": is_match,
                "confidence": confidence,
                "latency_seconds": verification.get("latency_seconds", 0.0),
                "error": verification.get("error"),
            },
        }
        return speaker, diarization

    async def _get_and_speak_response(
        self,
        transcript: str,
        duration_seconds: float = 0.0,
        speaker: str = "david",
        diarization: dict | None = None,
    ):
        """Get response from backend and speak it, streaming TTS sentence by
        sentence as the LLM response arrives instead of waiting for the
        whole thing (B4 latency fix)."""
        try:
            sentences: list[str] = []
            started_speaking = False
            sink = self._tts_sink
            self.local_playback.rearm()

            self.watchdog.notify_status("Thinking...")
            text_stream = self.backend.voice_chat(transcript, self._conversation_id)

            async for audio_chunk, sentence_text in self.tts.synthesize_streaming(text_stream):
                sentences.append(sentence_text)

                if not started_speaking:
                    started_speaking = True
                    self._barge_audio_buffer = []
                    self.vad.reset_barge_state()
                    await self.bridge.send_event({"event": "speaking_start", "text": sentence_text[:500]})
                    await self.conversation.on_response_ready()
                    self.echo_state.on_playback_start()
                    self.aec.update_playback_state(True)
                    self.watchdog.notify_status("Speaking...")

                # Check for barge-in during synthesis
                if self.conversation.state != ConversationState.SPEAKING:
                    logger.info("Speech interrupted during TTS")
                    break
                if audio_chunk is None:
                    continue

                # D3: play locally out the AIRHUG (default), relay to desktop,
                # or both — a live Settings > Voice toggle on the desktop can
                # still request "play this on my PC" via tts.sink=desktop.
                if sink in ("airhug", "both"):
                    await self.local_playback.play_and_wait(audio_chunk)
                if sink in ("desktop", "both"):
                    await self.bridge.send_audio(audio_chunk)

            full_response = " ".join(sentences).strip()

            if not full_response:
                logger.warning("Empty response from backend")
                asyncio.ensure_future(
                    self.raw_buffer.push_transcript(
                        transcript,
                        speaker=speaker,
                        diarization=diarization,
                        duration_seconds=duration_seconds,
                    )
                )
                await self.conversation.on_error("empty response")
                return

            logger.info("Response: '%s...'", full_response[:100])
            asyncio.ensure_future(
                self.raw_buffer.push_transcript(
                    transcript,
                    speaker=speaker,
                    diarization=diarization,
                    sara_response=full_response,
                    duration_seconds=duration_seconds,
                )
            )
            await self.bridge.send_event({
                "event": "transcript",
                "user": transcript,
                "sara": full_response,
            })

            # Wait for playback to complete. Local (airhug) playback already
            # blocked per-chunk above; only the desktop relay needs an async
            # wait for its own playback-complete report.
            if sink in ("desktop", "both"):
                await self.bridge.wait_for_playback_complete(timeout=30.0)

            # End echo tracking
            self.echo_state.on_playback_stop()
            self.aec.update_playback_state(False)

            # Transition to cooldown
            await self.conversation.on_playback_complete()

            # Re-activate VAD for cooldown listening
            self.vad.activate()

            self.watchdog.notify_status("Cooldown — listening for follow-up")

        except Exception as e:
            logger.exception("Response/TTS error")
            self.echo_state.reset()
            self.aec.update_playback_state(False)
            await self.conversation.on_error(str(e))

    async def _handle_barge_in(self, speech_snippet: np.ndarray | None = None):
        """Handle user barge-in during Sara's speech.

        B2.3: sustained VAD confidence already gated this call: add a quick
        speaker-verification check (300ms budget) so background voices
        (TV, another person) don't cut Sara off — only skip the check
        (i.e. allow the barge-in) on timeout/error, never block on it.
        """
        if speech_snippet is not None and len(speech_snippet) > 0:
            verification = await self.speaker_verifier.verify(speech_snippet, timeout_override=0.3)
            if not verification.get("error") and not verification.get("is_match", True):
                logger.info(
                    "Barge-in suppressed: speaker verification says not David (confidence=%.2f)",
                    verification.get("confidence", 0.0),
                )
                return

        logger.info("Barge-in! Stopping playback and listening...")

        # Stop local (airhug) and desktop playback
        self.local_playback.stop()
        await self.bridge.send_stop_playback()

        # Reset echo state
        self.echo_state.reset()
        self.aec.update_playback_state(False)

        # Transition to listening
        await self.conversation.on_barge_in()

        # Activate VAD for new utterance
        self.vad.activate()

        self.watchdog.notify_status("Listening (barge-in)")

    async def _end_conversation(self, last_transcript: str = ""):
        """Clean up after conversation ends."""
        duration = 0.0
        if self._conversation_start_time:
            duration = time.time() - self._conversation_start_time

        # Deactivate VAD
        self.vad.deactivate()

        # Re-enable wake word only if listening is enabled.
        if self.bridge.is_listening_enabled:
            self.wake_word.unsuppress()
        else:
            self.wake_word.suppress()

        # Reset echo state
        self.echo_state.reset()

        # Report to backend
        asyncio.ensure_future(
            self.event_reporter.report_conversation_ended(
                turns=self.conversation.turn_count,
                duration_seconds=duration,
                summary=last_transcript,
            )
        )

        # Notify desktop
        await self.bridge.send_conversation_end(last_transcript)

        # Reset
        self._conversation_start_time = None
        self._conversation_id = None

        if self.bridge.is_listening_enabled:
            self.watchdog.notify_status("Running — listening for wake word")
        else:
            self.watchdog.notify_status("Listening paused")
        logger.info(
            "Conversation ended: %d turns, %.1fs",
            self.conversation.turn_count, duration,
        )

    # ──────────────────────────────────────────────────────────────────
    # State change callbacks
    # ──────────────────────────────────────────────────────────────────

    async def _on_conversation_state_change(self, old: ConversationState, new: ConversationState):
        """Handle conversation state transitions."""
        if new == ConversationState.WAKE:
            await self.bridge.send_event({"event": "wake_word", "timestamp": time.time()})
        elif new == ConversationState.LISTENING:
            await self.bridge.send_event({"event": "listening", "timestamp": time.time()})
        elif new == ConversationState.IDLE:
            if old != ConversationState.IDLE:
                await self.bridge.send_event({"event": "idle", "timestamp": time.time()})
                await self._end_conversation()

    async def _on_presence_change(self, old, new):
        """Handle desk presence state changes."""
        from sara_voice.vision.presence import PresenceState
        await self.event_reporter.report_presence_changed(
            state=new.value,
            reason=f"transition from {old.value}",
        )

    async def _on_echo_state(self, is_playing: bool):
        """Handle echo state updates from desktop bridge."""
        self.aec.update_playback_state(is_playing)
        if is_playing:
            self.echo_state.on_playback_start()
        else:
            self.echo_state.on_playback_stop()

    async def _on_listening_changed(self, enabled: bool):
        """Handle desktop/API wake-listening toggle requests."""
        if enabled:
            self.wake_word.unsuppress()
            self.watchdog.notify_status("Running — listening for wake word")
            return

        # Pause wake-word entry and return to idle cleanly.
        self.wake_word.suppress()
        self.vad.deactivate()
        await self.conversation.force_idle("listening_disabled")
        self.watchdog.notify_status("Listening paused")

    async def _on_remote_stop_request(self):
        """CANCEL_SPEECH relayed from the backend (desktop hotkey/HUD or
        webapp/iOS mute — B2.6). Halts speech from any state and returns to
        idle, same as a local barge-in but reachable remotely."""
        logger.info("Remote CANCEL_SPEECH — stopping playback and going idle")
        self.local_playback.stop()
        await self.bridge.send_stop_playback()
        self.echo_state.reset()
        self.aec.update_playback_state(False)
        await self.conversation.force_idle("remote_stop_request")
        self.watchdog.notify_status("Running — listening for wake word")

    async def _check_conversation_watchdog(self, is_verified_david: bool) -> bool:
        """B2.7 loop breaker of last resort. Returns True if it tripped —
        caller should stop processing this turn (already forced idle)."""
        now = time.monotonic()
        self._watchdog_turn_log.append((now, is_verified_david))
        self._watchdog_turn_log = [
            (ts, v) for ts, v in self._watchdog_turn_log
            if now - ts <= self._watchdog_window_seconds
        ]

        recent = self._watchdog_turn_log[-self._watchdog_max_unverified_turns:]
        consecutive_unverified = (
            len(recent) >= self._watchdog_max_unverified_turns
            and all(not v for _, v in recent)
        )
        too_many_turns = len(self._watchdog_turn_log) >= self._watchdog_max_turns_window

        if not (consecutive_unverified or too_many_turns):
            return False

        reason = "consecutive_unverified_speech" if consecutive_unverified else "too_many_turns"
        logger.warning("Conversation watchdog tripped: %s", reason)
        self._watchdog_turn_log = []

        self.local_playback.stop()
        await self.bridge.send_stop_playback()
        self.echo_state.reset()
        self.aec.update_playback_state(False)
        await self.conversation.force_idle(f"watchdog: {reason}")

        self.wake_word.suppress()
        self.watchdog.notify_status(f"Voice paused ({reason})")
        asyncio.get_event_loop().call_later(
            self._watchdog_suppress_seconds,
            lambda: asyncio.ensure_future(self._watchdog_resume()),
        )

        asyncio.ensure_future(self.event_reporter.report_watchdog_paused(reason))
        return True

    async def _watchdog_resume(self):
        """Re-enable wake word after the watchdog's suppression window,
        unless the user has explicitly muted listening in the meantime."""
        if self.bridge.is_listening_enabled:
            self.wake_word.unsuppress()
            self.watchdog.notify_status("Running — listening for wake word")

    async def _on_speak_proactive_request(self, text: str):
        """Backend-relayed proactive delivery (Desktop Jarvis Overhaul D) —
        a spoken one-liner David didn't ask for (e.g. "Your dentist
        appointment starts in 15 minutes"). Only speaks when genuinely
        idle — a query in flight or Sara already talking always wins, and
        the backend's own routing already gates this on high urgency +
        high interruptibility + a daily cap, so declining here is just the
        last-mile "don't talk over him" safety check, not the main gate."""
        if self.conversation.state != ConversationState.IDLE:
            logger.info("Proactive speak request declined — not idle (state=%s)", self.conversation.state)
            return

        try:
            sink = self._tts_sink
            self.local_playback.rearm()
            await self.conversation.on_wake_word()
            await self.conversation.on_wake_confirmation_done()
            await self.bridge.send_event({"event": "speaking_start", "text": text[:500]})
            self.echo_state.on_playback_start()
            self.aec.update_playback_state(True)
            self.watchdog.notify_status("Speaking (proactive)...")

            async for audio_chunk in self.tts.synthesize(text):
                if sink in ("airhug", "both"):
                    await self.local_playback.play_and_wait(audio_chunk)
                if sink in ("desktop", "both"):
                    await self.bridge.send_audio(audio_chunk)

            self.echo_state.on_playback_stop()
            self.aec.update_playback_state(False)
            await self.conversation.force_idle("proactive_speak_done")
            self.watchdog.notify_status("Running — listening for wake word")
        except Exception as e:
            logger.warning("Proactive speak failed: %s", e)
            await self.conversation.force_idle("proactive_speak_error")

    async def _on_media_state_changed(self, playing: bool):
        """Desktop media_state changed (B2.4) — re-evaluate ambient mode."""
        self._desktop_media_playing = playing
        self._update_ambient_mode()

    def _update_ambient_mode(self):
        """Ambient mode is active when EITHER the desktop reports media
        playing OR the Jetson's own noise-floor estimate is elevated (TV/
        music picked up directly by the mic even with no desktop signal)."""
        noisy = self.noise_gate.ambient_db > self._ambient_db_floor
        active = self._desktop_media_playing or noisy
        self.wake_word.set_ambient_active(active)
        self.conversation.set_ambient_active(active)

    # ──────────────────────────────────────────────────────────────────
    # Background loops
    # ──────────────────────────────────────────────────────────────────

    async def _timeout_loop(self):
        """Periodic timeout checks for conversation state."""
        tick = 0
        while True:
            try:
                await self.conversation.check_timeouts()
                # Re-check the local noise floor every ~2s (B2.4) — media_state
                # pushes update immediately on change, this catches ambient
                # noise the desktop doesn't know about (TV in the room, etc.)
                tick += 1
                if tick % 4 == 0:
                    self._update_ambient_mode()
            except Exception:
                logger.exception("Timeout check error")
            await asyncio.sleep(0.5)

    async def _vision_loop(self):
        """Periodic face detection and presence tracking."""
        while True:
            try:
                if self.face_detector.should_run() and self.camera.is_running:
                    frame = self.camera.get_frame()
                    if frame is not None:
                        # Acquire GPU for face detection
                        acquired = await self.gpu_queue.acquire(
                            "face_detection", GPUPriority.FACE_DETECTION
                        )
                        if acquired:
                            try:
                                faces = self.face_detector.detect(frame)
                                await self._process_face_results(faces)
                            finally:
                                self.gpu_queue.release("face_detection")

                # Update presence timeout
                await self.presence.update()

            except Exception:
                logger.exception("Vision loop error")

            await asyncio.sleep(1.0)

    async def _process_face_results(self, faces: list[dict]):
        """Process face detection results."""
        david_found = False
        for face in faces:
            if face["is_david"]:
                david_found = True
                await self.presence.on_face_detected(is_david=True)
                # Report to backend (throttled — only when significant)
                asyncio.ensure_future(
                    self.event_reporter.report_face_detected(
                        is_david=True,
                        confidence=face["confidence"],
                        similarity=face["similarity"],
                    )
                )

        if not david_found and faces:
            # Faces detected but none are David
            for face in faces:
                await self.presence.on_face_detected(is_david=False)

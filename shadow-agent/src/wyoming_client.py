"""
Wyoming Protocol Client
Communicates with Sara backend using Wyoming protocol for voice
"""
import asyncio
import json
import base64
import logging
import websockets
import numpy as np
from typing import Optional, Callable, AsyncGenerator

logger = logging.getLogger(__name__)


class WyomingClient:
    """Wyoming protocol client for STT/TTS communication"""

    def __init__(self, backend_url: str = "ws://10.185.1.180:8000"):
        """
        Initialize Wyoming client

        Args:
            backend_url: Backend WebSocket URL
        """
        self.backend_url = backend_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False

    async def connect(self):
        """Connect to Wyoming backend"""
        try:
            logger.info(f"Connecting to Wyoming backend: {self.backend_url}")
            self.websocket = await websockets.connect(
                f"{self.backend_url}/wyoming/asr",
                ping_interval=20,
                ping_timeout=10
            )
            self.is_connected = True
            logger.info("✅ Connected to Wyoming backend")
        except Exception as e:
            logger.error(f"Failed to connect to backend: {e}")
            self.is_connected = False
            raise

    async def disconnect(self):
        """Disconnect from backend"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("Disconnected from backend")

    async def transcribe_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        use_fast_path: bool = True
    ) -> Optional[str]:
        """
        Send audio to backend for transcription

        Args:
            audio_data: Audio samples (int16)
            sample_rate: Sample rate in Hz
            use_fast_path: Use direct HTTP to STT service (faster, bypasses Wyoming)

        Returns:
            Transcribed text or None if failed
        """
        if use_fast_path:
            # FAST PATH: Direct HTTP POST to STT service (3-5x faster)
            return await self._transcribe_audio_fast(audio_data, sample_rate)
        else:
            # LEGACY PATH: Wyoming protocol via WebSocket
            return await self._transcribe_audio_wyoming(audio_data, sample_rate)

    async def _transcribe_audio_fast(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000
    ) -> Optional[str]:
        """
        Fast transcription using direct HTTP POST to STT service

        Args:
            audio_data: Audio samples (int16)
            sample_rate: Sample rate in Hz

        Returns:
            Transcribed text or None if failed
        """
        try:
            import aiohttp
            import io
            import wave
            import time

            start_time = time.time()

            # Convert to WAV format in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_data.tobytes())

            wav_buffer.seek(0)

            wav_prep_time = time.time() - start_time
            logger.debug(f"⏱️ WAV prep: {wav_prep_time:.3f}s")

            # STT service URL (from backend)
            stt_url = "http://10.185.1.8:8585/v1/audio/transcriptions"

            # Send directly to STT service
            request_start = time.time()
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                form_data.add_field('file', wav_buffer, filename='audio.wav', content_type='audio/wav')
                form_data.add_field('model', 'base.en')  # Use actual model name, not OpenAI alias
                form_data.add_field('language', 'en')

                async with session.post(stt_url, data=form_data, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    request_time = time.time() - request_start
                    logger.info(f"⏱️ STT request took {request_time:.3f}s")

                    if response.status == 200:
                        result = await response.json()
                        transcript = result.get("text", "").strip()

                        total_time = time.time() - start_time
                        logger.info(f"📝 Transcript: {transcript} (total: {total_time:.3f}s)")
                        return transcript
                    else:
                        logger.error(f"STT service error: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"Error during fast transcription: {e}")
            return None

    async def _transcribe_audio_wyoming(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000
    ) -> Optional[str]:
        """
        Legacy transcription using Wyoming protocol via WebSocket

        Args:
            audio_data: Audio samples (int16)
            sample_rate: Sample rate in Hz

        Returns:
            Transcribed text or None if failed
        """
        if not self.is_connected:
            await self.connect()

        try:
            # Send audio in chunks
            chunk_size = 4096
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]

                # Convert to bytes
                audio_bytes = chunk.tobytes()
                audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

                # Send Wyoming audio-chunk message
                await self.websocket.send(json.dumps({
                    "type": "audio-chunk",
                    "rate": sample_rate,
                    "width": 2,  # 16-bit
                    "channels": 1,
                    "audio": audio_b64
                }))

            # Send audio-stop to signal end
            await self.websocket.send(json.dumps({"type": "audio-stop"}))
            logger.debug("Sent audio to backend, waiting for transcript...")

            # Wait for transcript response
            response = await self.websocket.recv()
            data = json.loads(response)

            if data["type"] == "transcript":
                transcript = data["text"]
                logger.info(f"📝 Transcript: {transcript}")
                return transcript
            else:
                logger.error(f"Unexpected response type: {data['type']}")
                return None

        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return None

    async def synthesize_speech(
        self,
        text: str,
        voice: str = "alloy"
    ) -> Optional[bytes]:
        """
        Request TTS from backend

        Args:
            text: Text to synthesize
            voice: Voice ID

        Returns:
            Audio bytes (WAV format) or None if failed
        """
        try:
            # Connect to TTS endpoint
            tts_ws = await websockets.connect(f"{self.backend_url}/wyoming/tts")

            # Send synthesize request
            await tts_ws.send(json.dumps({
                "type": "synthesize",
                "text": text,
                "voice": voice
            }))

            # Receive audio chunks
            audio_chunks = []
            while True:
                response = await tts_ws.recv()
                data = json.loads(response)

                if data["type"] == "audio-chunk":
                    # Decode audio
                    audio_bytes = base64.b64decode(data["audio"])
                    audio_chunks.append(audio_bytes)
                elif data["type"] == "audio-stop":
                    # End of stream
                    break
                else:
                    logger.warning(f"Unexpected TTS response: {data['type']}")

            await tts_ws.close()

            if audio_chunks:
                full_audio = b"".join(audio_chunks)
                logger.info(f"🔊 Received TTS audio ({len(full_audio)} bytes)")
                return full_audio
            else:
                return None

        except Exception as e:
            logger.error(f"Error during TTS: {e}")
            return None


class AudioStreamSession:
    """
    Manages a complete voice interaction session
    Wake word → VAD → STT → Response → TTS
    """

    def __init__(
        self,
        wyoming_client: WyomingClient,
        on_transcript: Optional[Callable[[str], None]] = None,
        on_response_audio: Optional[Callable[[bytes], None]] = None
    ):
        """
        Initialize audio session

        Args:
            wyoming_client: WyomingClient instance
            on_transcript: Callback when transcript received
            on_response_audio: Callback when TTS audio received
        """
        self.wyoming = wyoming_client
        self.on_transcript = on_transcript
        self.on_response_audio = on_response_audio

    async def process_utterance(self, audio_data: np.ndarray) -> Optional[str]:
        """
        Process a complete utterance: audio → transcript

        Args:
            audio_data: Recorded audio (int16, 16kHz)

        Returns:
            Transcript text
        """
        logger.info(f"Processing utterance ({len(audio_data)/16000:.2f}s of audio)")

        # Transcribe
        transcript = await self.wyoming.transcribe_audio(audio_data)

        if transcript and self.on_transcript:
            self.on_transcript(transcript)

        return transcript

    async def get_response(self, transcript: str) -> Optional[bytes]:
        """
        Get TTS response from backend

        Args:
            transcript: User's transcribed speech

        Returns:
            TTS audio bytes
        """
        # For now, this is a placeholder
        # In full implementation, this would:
        # 1. Send transcript to Sara's chat API
        # 2. Get response text
        # 3. Convert to TTS
        # For testing, we'll just echo back
        response_text = f"You said: {transcript}"

        audio = await self.wyoming.synthesize_speech(response_text)

        if audio and self.on_response_audio:
            self.on_response_audio(audio)

        return audio

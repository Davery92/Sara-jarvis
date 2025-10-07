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
        sample_rate: int = 16000
    ) -> Optional[str]:
        """
        Send audio to backend for transcription

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

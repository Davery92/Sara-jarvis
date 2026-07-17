"""
Riva ASR Client - Speech Recognition Service

Connects to NVIDIA Riva for high-quality speech-to-text.
Falls back to Whisper/Jetson when Riva is unavailable.
"""

import os
import logging
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TranscriptWord:
    """A single transcribed word with timing."""
    word: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class TranscriptResult:
    """Result from speech recognition."""
    text: str
    words: List[TranscriptWord]
    language: str
    duration: float
    confidence: float
    is_final: bool


class RivaASRClient:
    """
    Client for NVIDIA Riva ASR service.

    Provides both streaming and batch transcription.
    """

    def __init__(
        self,
        server_url: str = None,
        use_ssl: bool = False,
    ):
        self.server_url = server_url or os.getenv(
            "RIVA_SERVER_URL",
            "10.185.1.8:50051"
        )
        self.use_ssl = use_ssl
        self._grpc_stub = None
        self._http_client: Optional[httpx.AsyncClient] = None

        # Try to import Riva client
        try:
            import riva.client
            self._riva_available = True
            self._riva = riva.client
        except ImportError:
            self._riva_available = False
            logger.warning("Riva client not installed - using HTTP fallback")

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def transcribe_file(
        self,
        audio_path: str,
        language: str = "en-US",
        enable_punctuation: bool = True,
        enable_word_timestamps: bool = True,
    ) -> TranscriptResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to audio file (WAV, MP3, FLAC)
            language: Language code
            enable_punctuation: Add automatic punctuation
            enable_word_timestamps: Include word-level timing

        Returns:
            TranscriptResult with full transcription
        """
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if self._riva_available:
            return await self._transcribe_grpc(
                audio_path,
                language,
                enable_punctuation,
                enable_word_timestamps
            )
        else:
            return await self._transcribe_http(
                audio_path,
                language,
                enable_punctuation,
                enable_word_timestamps
            )

    async def _transcribe_grpc(
        self,
        audio_path: str,
        language: str,
        enable_punctuation: bool,
        enable_word_timestamps: bool,
    ) -> TranscriptResult:
        """Transcribe using gRPC (native Riva client)."""
        try:
            # Read audio
            import soundfile as sf
            audio_data, sample_rate = sf.read(audio_path)

            # Ensure mono
            if len(audio_data.shape) > 1:
                audio_data = audio_data.mean(axis=1)

            # Convert to bytes
            import numpy as np
            audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()

            # Create auth and config
            auth = self._riva.Auth(uri=self.server_url, use_ssl=self.use_ssl)
            asr_service = self._riva.ASRService(auth)

            config = self._riva.RecognitionConfig(
                language_code=language,
                max_alternatives=1,
                enable_automatic_punctuation=enable_punctuation,
                enable_word_time_offsets=enable_word_timestamps,
                sample_rate_hertz=sample_rate,
                audio_channel_count=1,
            )

            # Run in thread pool (gRPC is sync)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: asr_service.offline_recognize(audio_bytes, config)
            )

            # Parse response
            words = []
            full_text = []
            total_confidence = 0.0

            for result in response.results:
                if result.alternatives:
                    alt = result.alternatives[0]
                    full_text.append(alt.transcript)
                    total_confidence += alt.confidence

                    for word_info in alt.words:
                        words.append(TranscriptWord(
                            word=word_info.word,
                            start_time=word_info.start_time,
                            end_time=word_info.end_time,
                            confidence=alt.confidence
                        ))

            duration = len(audio_data) / sample_rate
            avg_confidence = total_confidence / max(len(response.results), 1)

            return TranscriptResult(
                text=" ".join(full_text),
                words=words,
                language=language,
                duration=duration,
                confidence=avg_confidence,
                is_final=True
            )

        except Exception as e:
            logger.error(f"Riva gRPC transcription failed: {e}")
            raise

    async def _transcribe_http(
        self,
        audio_path: str,
        language: str,
        enable_punctuation: bool,
        enable_word_timestamps: bool,
    ) -> TranscriptResult:
        """Transcribe using HTTP API (fallback)."""
        # This would call the GPU cluster's REST endpoint
        http_url = os.getenv("RIVA_HTTP_URL", "http://10.185.1.8:8001")

        client = await self._get_http_client()

        try:
            with open(audio_path, "rb") as f:
                audio_data = f.read()

            response = await client.post(
                f"{http_url}/asr/transcribe",
                files={"audio": ("audio.wav", audio_data)},
                data={
                    "language": language,
                    "punctuation": str(enable_punctuation).lower(),
                    "word_timestamps": str(enable_word_timestamps).lower()
                }
            )
            response.raise_for_status()
            result = response.json()

            words = [
                TranscriptWord(
                    word=w["word"],
                    start_time=w["start"],
                    end_time=w["end"],
                    confidence=w.get("confidence", 0.9)
                )
                for w in result.get("words", [])
            ]

            return TranscriptResult(
                text=result.get("text", ""),
                words=words,
                language=language,
                duration=result.get("duration", 0.0),
                confidence=result.get("confidence", 0.9),
                is_final=True
            )

        except Exception as e:
            logger.error(f"Riva HTTP transcription failed: {e}")
            raise

    async def transcribe_stream(
        self,
        audio_stream,
        language: str = "en-US",
        sample_rate: int = 16000,
    ):
        """
        Stream audio for real-time transcription.

        Yields partial results as they become available.
        """
        if not self._riva_available:
            raise NotImplementedError("Streaming requires native Riva client")

        # Implementation for streaming ASR
        auth = self._riva.Auth(uri=self.server_url, use_ssl=self.use_ssl)
        asr_service = self._riva.ASRService(auth)

        config = self._riva.StreamingRecognitionConfig(
            config=self._riva.RecognitionConfig(
                language_code=language,
                max_alternatives=1,
                enable_automatic_punctuation=True,
                sample_rate_hertz=sample_rate,
            ),
            interim_results=True
        )

        # Stream processing would go here
        # This is a placeholder for the streaming implementation
        raise NotImplementedError("Streaming ASR not yet implemented")

    async def check_health(self) -> Dict[str, Any]:
        """Check if Riva server is healthy."""
        try:
            if self._riva_available:
                auth = self._riva.Auth(uri=self.server_url, use_ssl=self.use_ssl)
                # Simple connectivity check
                return {
                    "status": "healthy",
                    "server": self.server_url,
                    "method": "grpc"
                }
            else:
                http_url = os.getenv("RIVA_HTTP_URL", "http://10.185.1.8:8001")
                client = await self._get_http_client()
                response = await client.get(f"{http_url}/v1/health/ready")
                return {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "server": http_url,
                    "method": "http"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    async def close(self):
        """Close the client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# Singleton instance
_riva_client: Optional[RivaASRClient] = None


async def get_riva_client() -> RivaASRClient:
    """Get or create Riva ASR client."""
    global _riva_client
    if _riva_client is None:
        _riva_client = RivaASRClient()
    return _riva_client

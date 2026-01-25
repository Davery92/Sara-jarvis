"""
Diarization Service - Speaker Identification

Connects to NeMo diarization service on GPU cluster.
Identifies who is speaking when in audio recordings.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SpeakerSegment:
    """A segment of speech attributed to a speaker."""
    start_time: float
    end_time: float
    speaker_id: str
    confidence: float
    text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiarizationResult:
    """Result from speaker diarization."""
    segments: List[SpeakerSegment]
    num_speakers: int
    total_duration: float
    speaker_labels: List[str]
    david_detected: bool = False
    david_segments: Optional[List[SpeakerSegment]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "num_speakers": self.num_speakers,
            "total_duration": self.total_duration,
            "speaker_labels": self.speaker_labels,
            "david_detected": self.david_detected,
            "david_segments": [s.to_dict() for s in (self.david_segments or [])]
        }


class DiarizationService:
    """
    Service for speaker diarization using NeMo.

    Connects to the GPU cluster's NeMo service for:
    - Speaker diarization (who spoke when)
    - Speaker identification (is this David?)
    - Speaker verification
    """

    def __init__(self, nemo_url: str = None):
        self.nemo_url = nemo_url or os.getenv(
            "NEMO_DIARIZATION_URL",
            "http://10.185.1.8:8002"
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        max_speakers: int = 8,
        min_speakers: int = 1,
    ) -> DiarizationResult:
        """
        Perform speaker diarization on audio file.

        Args:
            audio_path: Path to audio file
            num_speakers: Known number of speakers (None for auto-detect)
            max_speakers: Maximum speakers to detect
            min_speakers: Minimum speakers to detect

        Returns:
            DiarizationResult with speaker segments
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self.nemo_url}/diarize",
                json={
                    "audio_path": audio_path,
                    "num_speakers": num_speakers,
                    "max_speakers": max_speakers,
                    "min_speakers": min_speakers
                }
            )
            response.raise_for_status()
            data = response.json()

            segments = [
                SpeakerSegment(
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    speaker_id=s["speaker_id"],
                    confidence=s.get("confidence", 0.8)
                )
                for s in data.get("segments", [])
            ]

            # Check for David
            david_detected = "david" in [s.speaker_id.lower() for s in segments]
            david_segments = [s for s in segments if s.speaker_id.lower() == "david"]

            return DiarizationResult(
                segments=segments,
                num_speakers=data.get("num_speakers", len(set(s.speaker_id for s in segments))),
                total_duration=data.get("total_duration", 0.0),
                speaker_labels=data.get("speaker_labels", list(set(s.speaker_id for s in segments))),
                david_detected=david_detected,
                david_segments=david_segments if david_detected else None
            )

        except httpx.HTTPError as e:
            logger.error(f"Diarization request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            raise

    async def verify_speaker(
        self,
        audio_path: str,
        speaker_id: str,
        threshold: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Verify if audio matches a known speaker.

        Args:
            audio_path: Path to audio file
            speaker_id: ID of enrolled speaker to verify against
            threshold: Confidence threshold (0.0-1.0)

        Returns:
            {"is_match": bool, "confidence": float, "speaker_id": str}
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self.nemo_url}/verify",
                json={
                    "audio_path": audio_path,
                    "speaker_id": speaker_id,
                    "threshold": threshold
                }
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Speaker verification failed: {e}")
            return {
                "is_match": False,
                "confidence": 0.0,
                "speaker_id": speaker_id,
                "error": str(e)
            }

    async def is_david_speaking(
        self,
        audio_path: str,
        threshold: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Quick check if David is speaking in audio.

        Args:
            audio_path: Path to audio file
            threshold: Confidence threshold

        Returns:
            {"is_david": bool, "confidence": float}
        """
        result = await self.verify_speaker(audio_path, "david", threshold)
        return {
            "is_david": result.get("is_match", False),
            "confidence": result.get("confidence", 0.0)
        }

    async def get_embedding(self, audio_path: str) -> Dict[str, Any]:
        """
        Extract speaker embedding from audio.

        Useful for comparing speakers or enrollment.
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self.nemo_url}/embedding",
                json={"audio_path": audio_path}
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Embedding extraction failed: {e}")
            raise

    async def check_health(self) -> Dict[str, Any]:
        """Check if NeMo service is healthy."""
        client = await self._get_client()

        try:
            response = await client.get(f"{self.nemo_url}/health")
            return response.json()
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
_diarization_service: Optional[DiarizationService] = None


async def get_diarization_service() -> DiarizationService:
    """Get or create diarization service."""
    global _diarization_service
    if _diarization_service is None:
        _diarization_service = DiarizationService()
    return _diarization_service

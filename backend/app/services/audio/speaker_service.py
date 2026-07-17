"""
Speaker Service - Speaker Enrollment and Management

Handles speaker enrollment, profile management, and recognition.
Primary use: Enrolling David for automatic recognition.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SpeakerProfile:
    """An enrolled speaker profile."""
    speaker_id: str
    display_name: str
    num_samples: int
    enrolled_at: Optional[str] = None


class SpeakerService:
    """
    Service for speaker enrollment and management.

    Provides:
    - Speaker enrollment with audio samples
    - Profile management (list, get, delete)
    - Sample management (add additional samples)
    """

    def __init__(self, enrollment_url: str = None):
        self.enrollment_url = enrollment_url or os.getenv(
            "SPEAKER_ENROLLMENT_URL",
            "http://10.185.1.8:8003"
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def enroll_speaker(
        self,
        speaker_id: str,
        audio_paths: List[str],
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enroll a new speaker with audio samples.

        Args:
            speaker_id: Unique identifier for the speaker (e.g., "david")
            audio_paths: List of paths to audio samples (1-5 recommended)
            display_name: Human-readable name (defaults to speaker_id)

        Returns:
            Enrollment result with status
        """
        client = await self._get_client()

        # Validate paths exist
        for path in audio_paths:
            if not Path(path).exists():
                raise FileNotFoundError(f"Audio sample not found: {path}")

        try:
            # Prepare multipart upload
            files = []
            for i, path in enumerate(audio_paths):
                with open(path, "rb") as f:
                    files.append(
                        ("files", (f"sample_{i}.wav", f.read(), "audio/wav"))
                    )

            data = {}
            if display_name:
                data["display_name"] = display_name

            response = await client.post(
                f"{self.enrollment_url}/enroll/{speaker_id}",
                files=files,
                data=data
            )
            response.raise_for_status()

            result = response.json()
            logger.info(f"Enrolled speaker '{speaker_id}' with {len(audio_paths)} samples")

            return result

        except httpx.HTTPError as e:
            logger.error(f"Speaker enrollment failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Enrollment error: {e}")
            raise

    async def enroll_david(self, audio_paths: List[str]) -> Dict[str, Any]:
        """
        Convenience method to enroll David.

        Args:
            audio_paths: List of paths to David's voice samples

        Returns:
            Enrollment result
        """
        return await self.enroll_speaker(
            speaker_id="david",
            audio_paths=audio_paths,
            display_name="David"
        )

    async def list_speakers(self) -> List[SpeakerProfile]:
        """List all enrolled speakers."""
        client = await self._get_client()

        try:
            response = await client.get(f"{self.enrollment_url}/speakers")
            response.raise_for_status()
            data = response.json()

            return [
                SpeakerProfile(
                    speaker_id=s["speaker_id"],
                    display_name=s.get("display_name", s["speaker_id"]),
                    num_samples=s.get("num_samples", 0)
                )
                for s in data.get("speakers", [])
            ]

        except Exception as e:
            logger.error(f"Failed to list speakers: {e}")
            return []

    async def get_speaker(self, speaker_id: str) -> Optional[SpeakerProfile]:
        """Get a specific speaker profile."""
        client = await self._get_client()

        try:
            response = await client.get(f"{self.enrollment_url}/speakers/{speaker_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

            return SpeakerProfile(
                speaker_id=data["speaker_id"],
                display_name=data.get("display_name", data["speaker_id"]),
                num_samples=data.get("num_samples", 0)
            )

        except Exception as e:
            logger.error(f"Failed to get speaker: {e}")
            return None

    async def delete_speaker(self, speaker_id: str) -> bool:
        """Delete a speaker profile."""
        client = await self._get_client()

        try:
            response = await client.delete(f"{self.enrollment_url}/speakers/{speaker_id}")
            if response.status_code == 404:
                return False
            response.raise_for_status()
            logger.info(f"Deleted speaker '{speaker_id}'")
            return True

        except Exception as e:
            logger.error(f"Failed to delete speaker: {e}")
            return False

    async def add_sample(self, speaker_id: str, audio_path: str) -> Dict[str, Any]:
        """
        Add an additional sample to an existing speaker.

        Args:
            speaker_id: ID of the speaker
            audio_path: Path to new audio sample

        Returns:
            Updated speaker info
        """
        client = await self._get_client()

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio sample not found: {audio_path}")

        try:
            with open(audio_path, "rb") as f:
                files = {"file": ("sample.wav", f.read(), "audio/wav")}

            response = await client.post(
                f"{self.enrollment_url}/speakers/{speaker_id}/add-sample",
                files=files
            )
            response.raise_for_status()

            logger.info(f"Added sample to speaker '{speaker_id}'")
            return response.json()

        except Exception as e:
            logger.error(f"Failed to add sample: {e}")
            raise

    async def is_david_enrolled(self) -> bool:
        """Check if David is enrolled."""
        profile = await self.get_speaker("david")
        return profile is not None

    async def check_health(self) -> Dict[str, Any]:
        """Check if enrollment service is healthy."""
        client = await self._get_client()

        try:
            response = await client.get(f"{self.enrollment_url}/health")
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
_speaker_service: Optional[SpeakerService] = None


async def get_speaker_service() -> SpeakerService:
    """Get or create speaker service."""
    global _speaker_service
    if _speaker_service is None:
        _speaker_service = SpeakerService()
    return _speaker_service

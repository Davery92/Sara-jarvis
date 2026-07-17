"""
Speaker utilities for diarization and enrollment.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SpeakerSegment:
    """A segment attributed to a speaker."""
    start_time: float
    end_time: float
    speaker_id: str
    confidence: float
    text: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "speaker_id": self.speaker_id,
            "confidence": self.confidence,
            "text": self.text
        }


@dataclass
class SpeakerProfile:
    """Enrolled speaker profile."""
    speaker_id: str
    embedding: np.ndarray
    num_samples: int
    display_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "embedding": self.embedding.tolist(),
            "num_samples": self.num_samples,
            "display_name": self.display_name
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeakerProfile":
        return cls(
            speaker_id=data["speaker_id"],
            embedding=np.array(data["embedding"]),
            num_samples=data.get("num_samples", 1),
            display_name=data.get("display_name")
        )


class SpeakerProfileManager:
    """Manages speaker profiles for identification."""

    def __init__(self, profiles_dir: str = "/data/speakers"):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: Dict[str, SpeakerProfile] = {}
        self._load_profiles()

    def _load_profiles(self):
        """Load all profiles from disk."""
        for path in self.profiles_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                profile = SpeakerProfile.from_dict(data)
                self._profiles[profile.speaker_id] = profile
                logger.info(f"Loaded speaker profile: {profile.speaker_id}")
            except Exception as e:
                logger.error(f"Failed to load profile {path}: {e}")

    def get_profile(self, speaker_id: str) -> Optional[SpeakerProfile]:
        """Get a speaker profile by ID."""
        return self._profiles.get(speaker_id)

    def save_profile(self, profile: SpeakerProfile) -> str:
        """Save a speaker profile."""
        path = self.profiles_dir / f"{profile.speaker_id}.json"
        with open(path, "w") as f:
            json.dump(profile.to_dict(), f)
        self._profiles[profile.speaker_id] = profile
        return str(path)

    def delete_profile(self, speaker_id: str) -> bool:
        """Delete a speaker profile."""
        path = self.profiles_dir / f"{speaker_id}.json"
        if path.exists():
            path.unlink()
            self._profiles.pop(speaker_id, None)
            return True
        return False

    def list_profiles(self) -> List[Dict]:
        """List all speaker profiles."""
        return [
            {
                "speaker_id": p.speaker_id,
                "display_name": p.display_name,
                "num_samples": p.num_samples
            }
            for p in self._profiles.values()
        ]

    def identify_speaker(
        self,
        embedding: np.ndarray,
        threshold: float = 0.5
    ) -> Tuple[Optional[str], float]:
        """
        Identify speaker from embedding.

        Returns (speaker_id, confidence) or (None, 0.0) if no match.
        """
        if not self._profiles:
            return None, 0.0

        best_match = None
        best_score = threshold

        for speaker_id, profile in self._profiles.items():
            similarity = self._cosine_similarity(embedding, profile.embedding)
            if similarity > best_score:
                best_score = similarity
                best_match = speaker_id

        return best_match, best_score

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity."""
        a = a.flatten()
        b = b.flatten()
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def merge_adjacent_segments(
    segments: List[SpeakerSegment],
    max_gap: float = 0.5
) -> List[SpeakerSegment]:
    """Merge adjacent segments from same speaker."""
    if not segments:
        return []

    merged = [segments[0]]

    for segment in segments[1:]:
        last = merged[-1]
        gap = segment.start_time - last.end_time

        if segment.speaker_id == last.speaker_id and gap <= max_gap:
            # Merge
            last.end_time = segment.end_time
            if segment.text and last.text:
                last.text = f"{last.text} {segment.text}"
            elif segment.text:
                last.text = segment.text
        else:
            merged.append(segment)

    return merged


def align_transcript_with_diarization(
    transcript_segments: List[Dict],
    diarization_segments: List[SpeakerSegment]
) -> List[SpeakerSegment]:
    """
    Align transcript words/segments with diarization results.

    Args:
        transcript_segments: List of {"text": str, "start": float, "end": float}
        diarization_segments: List of SpeakerSegment with speaker IDs

    Returns:
        Updated diarization segments with text
    """
    if not transcript_segments or not diarization_segments:
        return diarization_segments

    # Create output segments
    output = []

    for diar_seg in diarization_segments:
        text_parts = []

        for trans_seg in transcript_segments:
            # Check overlap
            overlap_start = max(diar_seg.start_time, trans_seg["start"])
            overlap_end = min(diar_seg.end_time, trans_seg["end"])

            if overlap_end > overlap_start:
                # There's overlap - attribute this text to the speaker
                text_parts.append(trans_seg["text"])

        diar_seg.text = " ".join(text_parts) if text_parts else None
        output.append(diar_seg)

    return output

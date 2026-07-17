"""
Audio processing services for Sara's cognitive architecture.

Provides:
- Riva ASR client for speech recognition
- NeMo diarization client for speaker identification
- Speaker enrollment management
"""

from .riva_client import RivaASRClient, get_riva_client
from .diarization_service import DiarizationService, get_diarization_service
from .speaker_service import SpeakerService, get_speaker_service

__all__ = [
    "RivaASRClient",
    "get_riva_client",
    "DiarizationService",
    "get_diarization_service",
    "SpeakerService",
    "get_speaker_service",
]

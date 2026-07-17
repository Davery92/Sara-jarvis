"""
Tests for NVIDIA Audio Stack (Phase 0)

Tests for:
- Riva ASR client
- NeMo diarization service
- Speaker enrollment service
- Full audio pipeline integration
"""

import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Test fixtures
@pytest.fixture
def mock_riva_response():
    """Mock Riva ASR response."""
    return {
        "text": "Hello Sara, this is a test of the audio system.",
        "words": [
            {"word": "Hello", "start": 0.0, "end": 0.3, "confidence": 0.95},
            {"word": "Sara", "start": 0.4, "end": 0.7, "confidence": 0.92},
            {"word": "this", "start": 0.8, "end": 1.0, "confidence": 0.98},
            {"word": "is", "start": 1.1, "end": 1.2, "confidence": 0.99},
            {"word": "a", "start": 1.3, "end": 1.4, "confidence": 0.97},
            {"word": "test", "start": 1.5, "end": 1.8, "confidence": 0.96},
            {"word": "of", "start": 1.9, "end": 2.0, "confidence": 0.98},
            {"word": "the", "start": 2.1, "end": 2.2, "confidence": 0.99},
            {"word": "audio", "start": 2.3, "end": 2.6, "confidence": 0.94},
            {"word": "system", "start": 2.7, "end": 3.1, "confidence": 0.93},
        ],
        "duration": 3.1,
        "confidence": 0.96
    }


@pytest.fixture
def mock_diarization_response():
    """Mock NeMo diarization response."""
    return {
        "segments": [
            {"start_time": 0.0, "end_time": 1.5, "speaker_id": "david", "confidence": 0.92},
            {"start_time": 1.6, "end_time": 3.1, "speaker_id": "david", "confidence": 0.88},
        ],
        "num_speakers": 1,
        "total_duration": 3.1,
        "speaker_labels": ["david"]
    }


@pytest.fixture
def mock_speaker_profile():
    """Mock speaker profile."""
    return {
        "speaker_id": "david",
        "display_name": "David",
        "num_samples": 3
    }


# ==================== Riva ASR Client Tests ====================

class TestRivaASRClient:
    """Tests for RivaASRClient."""

    @pytest.mark.asyncio
    async def test_riva_client_initialization(self):
        """Test Riva client initializes correctly."""
        from app.services.audio.riva_client import RivaASRClient

        client = RivaASRClient(server_url="10.185.1.8:50051")
        assert client.server_url == "10.185.1.8:50051"
        assert client.use_ssl is False

    @pytest.mark.asyncio
    async def test_riva_client_health_check(self):
        """Test Riva health check."""
        from app.services.audio.riva_client import RivaASRClient

        client = RivaASRClient()

        with patch.object(client, '_get_http_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: {"status": "healthy"}
            ))
            mock_get.return_value = mock_client

            # Force HTTP mode
            client._riva_available = False

            health = await client.check_health()
            assert health["status"] in ["healthy", "unhealthy"]

    @pytest.mark.asyncio
    async def test_riva_transcribe_file_http_fallback(self, mock_riva_response, tmp_path):
        """Test transcription via HTTP fallback."""
        from app.services.audio.riva_client import RivaASRClient

        # Create a dummy audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)

        client = RivaASRClient()
        client._riva_available = False

        with patch.object(client, '_get_http_client') as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: mock_riva_response
            ))
            mock_get.return_value = mock_http

            result = await client.transcribe_file(str(audio_file))

            assert result.text == mock_riva_response["text"]
            assert result.duration == mock_riva_response["duration"]
            assert len(result.words) == len(mock_riva_response["words"])

    @pytest.mark.asyncio
    async def test_riva_transcribe_file_not_found(self):
        """Test transcription with missing file."""
        from app.services.audio.riva_client import RivaASRClient

        client = RivaASRClient()

        with pytest.raises(FileNotFoundError):
            await client.transcribe_file("/nonexistent/audio.wav")


# ==================== Diarization Service Tests ====================

class TestDiarizationService:
    """Tests for DiarizationService."""

    @pytest.mark.asyncio
    async def test_diarization_service_initialization(self):
        """Test diarization service initializes correctly."""
        from app.services.audio.diarization_service import DiarizationService

        service = DiarizationService(nemo_url="http://10.185.1.8:8002")
        assert service.nemo_url == "http://10.185.1.8:8002"

    @pytest.mark.asyncio
    async def test_diarize_audio(self, mock_diarization_response):
        """Test audio diarization."""
        from app.services.audio.diarization_service import DiarizationService

        service = DiarizationService()

        with patch.object(service, '_get_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: mock_diarization_response
            ))
            mock_get.return_value = mock_client

            result = await service.diarize("/path/to/audio.wav")

            assert result.num_speakers == 1
            assert len(result.segments) == 2
            assert result.david_detected is True
            assert "david" in result.speaker_labels

    @pytest.mark.asyncio
    async def test_verify_speaker(self):
        """Test speaker verification."""
        from app.services.audio.diarization_service import DiarizationService

        service = DiarizationService()

        mock_response = {
            "is_match": True,
            "confidence": 0.85,
            "speaker_id": "david"
        }

        with patch.object(service, '_get_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: mock_response
            ))
            mock_get.return_value = mock_client

            result = await service.verify_speaker("/path/to/audio.wav", "david")

            assert result["is_match"] is True
            assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_is_david_speaking(self):
        """Test David detection convenience method."""
        from app.services.audio.diarization_service import DiarizationService

        service = DiarizationService()

        with patch.object(service, 'verify_speaker') as mock_verify:
            mock_verify.return_value = {"is_match": True, "confidence": 0.9}

            result = await service.is_david_speaking("/path/to/audio.wav")

            assert result["is_david"] is True
            assert result["confidence"] == 0.9


# ==================== Speaker Service Tests ====================

class TestSpeakerService:
    """Tests for SpeakerService."""

    @pytest.mark.asyncio
    async def test_speaker_service_initialization(self):
        """Test speaker service initializes correctly."""
        from app.services.audio.speaker_service import SpeakerService

        service = SpeakerService(enrollment_url="http://10.185.1.8:8003")
        assert service.enrollment_url == "http://10.185.1.8:8003"

    @pytest.mark.asyncio
    async def test_enroll_speaker(self, mock_speaker_profile, tmp_path):
        """Test speaker enrollment."""
        from app.services.audio.speaker_service import SpeakerService

        # Create dummy audio files
        audio_files = []
        for i in range(3):
            f = tmp_path / f"sample_{i}.wav"
            f.write_bytes(b"RIFF" + b"\x00" * 100)
            audio_files.append(str(f))

        service = SpeakerService()

        with patch.object(service, '_get_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"status": "success", **mock_speaker_profile}
            ))
            mock_get.return_value = mock_client

            result = await service.enroll_speaker("david", audio_files, "David")

            assert result["speaker_id"] == "david"
            assert result["num_samples"] == 3

    @pytest.mark.asyncio
    async def test_enroll_david_convenience(self, tmp_path):
        """Test enroll_david convenience method."""
        from app.services.audio.speaker_service import SpeakerService

        # Create dummy audio files
        audio_files = [str(tmp_path / f"sample_{i}.wav") for i in range(2)]
        for f in audio_files:
            open(f, 'wb').write(b"RIFF" + b"\x00" * 100)

        service = SpeakerService()

        with patch.object(service, 'enroll_speaker') as mock_enroll:
            mock_enroll.return_value = {"status": "success", "speaker_id": "david", "num_samples": 2}

            result = await service.enroll_david(audio_files)

            mock_enroll.assert_called_once_with(
                speaker_id="david",
                audio_paths=audio_files,
                display_name="David"
            )

    @pytest.mark.asyncio
    async def test_list_speakers(self, mock_speaker_profile):
        """Test listing enrolled speakers."""
        from app.services.audio.speaker_service import SpeakerService

        service = SpeakerService()

        with patch.object(service, '_get_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"speakers": [mock_speaker_profile]}
            ))
            mock_get.return_value = mock_client

            speakers = await service.list_speakers()

            assert len(speakers) == 1
            assert speakers[0].speaker_id == "david"

    @pytest.mark.asyncio
    async def test_is_david_enrolled(self):
        """Test checking David enrollment status."""
        from app.services.audio.speaker_service import SpeakerService

        service = SpeakerService()

        with patch.object(service, 'get_speaker') as mock_get:
            # David enrolled
            mock_get.return_value = MagicMock(speaker_id="david")
            assert await service.is_david_enrolled() is True

            # David not enrolled
            mock_get.return_value = None
            assert await service.is_david_enrolled() is False

    @pytest.mark.asyncio
    async def test_delete_speaker(self):
        """Test deleting a speaker."""
        from app.services.audio.speaker_service import SpeakerService

        service = SpeakerService()

        with patch.object(service, '_get_client') as mock_get:
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=MagicMock(
                status_code=200,
                raise_for_status=lambda: None
            ))
            mock_get.return_value = mock_client

            result = await service.delete_speaker("david")
            assert result is True


# ==================== Audio Pipeline Integration Tests ====================

class TestAudioPipelineIntegration:
    """Integration tests for the full audio pipeline."""

    @pytest.mark.asyncio
    async def test_full_audio_processing_pipeline(
        self,
        mock_riva_response,
        mock_diarization_response,
        tmp_path
    ):
        """Test complete audio processing flow."""
        from app.tasks.input_processing import _process_audio_with_riva

        # Create dummy audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch('app.services.audio.riva_client.get_riva_client') as mock_riva, \
             patch('app.services.audio.diarization_service.get_diarization_service') as mock_diar:

            # Setup Riva mock
            riva_client = AsyncMock()
            riva_client.transcribe_file = AsyncMock(return_value=MagicMock(
                text=mock_riva_response["text"],
                words=[MagicMock(
                    word=w["word"],
                    start_time=w["start"],
                    end_time=w["end"],
                    confidence=w["confidence"]
                ) for w in mock_riva_response["words"]],
                duration=mock_riva_response["duration"],
                confidence=mock_riva_response["confidence"]
            ))
            mock_riva.return_value = riva_client

            # Setup diarization mock
            diar_service = AsyncMock()
            diar_service.diarize = AsyncMock(return_value=MagicMock(
                segments=[MagicMock(
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    speaker_id=s["speaker_id"],
                    confidence=s["confidence"]
                ) for s in mock_diarization_response["segments"]],
                num_speakers=mock_diarization_response["num_speakers"],
                speaker_labels=mock_diarization_response["speaker_labels"],
                david_detected=True,
                david_segments=[]
            ))
            mock_diar.return_value = diar_service

            result = await _process_audio_with_riva(str(audio_file), "test")

            assert result["status"] == "success"
            assert result["transcript"] == mock_riva_response["text"]
            assert result["speaker"] == "david"
            assert result["david_detected"] is True
            assert result["diarization"]["num_speakers"] == 1

    @pytest.mark.asyncio
    async def test_audio_processing_with_riva_failure(self, tmp_path):
        """Test graceful handling of Riva failure."""
        from app.tasks.input_processing import _process_audio_with_riva

        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch('app.services.audio.riva_client.get_riva_client') as mock_riva:
            riva_client = AsyncMock()
            riva_client.transcribe_file = AsyncMock(
                side_effect=Exception("Riva connection failed")
            )
            mock_riva.return_value = riva_client

            result = await _process_audio_with_riva(str(audio_file), "test")

            assert result["status"] == "error"
            assert "Riva" in result.get("error", "") or "connection" in result.get("error", "").lower()


# ==================== Audio Input Processing Tests ====================

class TestAudioInputProcessing:
    """Tests for audio input processing Celery tasks."""

    def test_process_audio_with_transcript(self):
        """Test processing audio with pre-transcribed text."""
        from app.tasks.input_processing import process_audio_input

        with patch('redis.from_url') as mock_redis:
            mock_r = MagicMock()
            mock_r.xadd = MagicMock(return_value=b"1234567890-0")
            mock_redis.return_value = mock_r

            result = process_audio_input(
                transcript="Hello Sara",
                speaker="david",
                duration_seconds=2.0,
                source="test"
            )

            assert result["status"] == "success"
            assert result["speaker"] == "david"
            assert result["transcript_length"] == 10

    def test_process_audio_with_diarization(self):
        """Test processing audio with diarization data."""
        from app.tasks.input_processing import process_audio_input

        diarization = {
            "segments": [
                {"start": 0, "end": 2, "speaker": "david"}
            ],
            "num_speakers": 1
        }

        with patch('redis.from_url') as mock_redis:
            mock_r = MagicMock()
            mock_r.xadd = MagicMock(return_value=b"1234567890-0")
            mock_redis.return_value = mock_r

            result = process_audio_input(
                transcript="Hello",
                speaker="david",
                diarization=diarization,
                source="test"
            )

            assert result["status"] == "success"

    def test_process_audio_missing_input(self):
        """Test error when neither transcript nor audio_path provided."""
        from app.tasks.input_processing import process_audio_input

        result = process_audio_input()

        assert result["status"] == "error"
        assert "Either transcript or audio_path must be provided" in result["message"]


# ==================== API Endpoint Tests ====================

class TestAudioAPIEndpoints:
    """Tests for audio API endpoints."""

    @pytest.mark.asyncio
    async def test_receive_processed_audio_endpoint(self):
        """Test receiving processed audio from GPU cluster."""
        from fastapi.testclient import TestClient
        from app.main_simple import app

        # This would need proper auth setup for full test
        # For now, test the endpoint exists
        pass

    @pytest.mark.asyncio
    async def test_audio_health_endpoint(self):
        """Test audio services health endpoint."""
        # Would need proper test client setup
        pass


# ==================== GPU Cluster Tests ====================

class TestGPUClusterServices:
    """Tests for GPU cluster services (when available)."""

    @pytest.mark.skipif(
        os.getenv("GPU_CLUSTER_AVAILABLE") != "true",
        reason="GPU cluster not available"
    )
    @pytest.mark.asyncio
    async def test_riva_server_health(self):
        """Test Riva server is healthy."""
        from app.services.audio.riva_client import get_riva_client

        client = await get_riva_client()
        health = await client.check_health()

        assert health["status"] == "healthy"

    @pytest.mark.skipif(
        os.getenv("GPU_CLUSTER_AVAILABLE") != "true",
        reason="GPU cluster not available"
    )
    @pytest.mark.asyncio
    async def test_nemo_server_health(self):
        """Test NeMo diarization server is healthy."""
        from app.services.audio.diarization_service import get_diarization_service

        service = await get_diarization_service()
        health = await service.check_health()

        assert health["status"] == "healthy"

    @pytest.mark.skipif(
        os.getenv("GPU_CLUSTER_AVAILABLE") != "true",
        reason="GPU cluster not available"
    )
    @pytest.mark.asyncio
    async def test_enrollment_server_health(self):
        """Test speaker enrollment server is healthy."""
        from app.services.audio.speaker_service import get_speaker_service

        service = await get_speaker_service()
        health = await service.check_health()

        assert health["status"] == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

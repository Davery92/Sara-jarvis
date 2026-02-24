"""
Audio Pipeline Worker

Processes audio files through the complete pipeline:
1. Riva ASR - Transcription
2. Diarization service - Speaker diarization (NeMo/pyannote compatible)
3. Speaker identification
4. Send results to Sara backend
"""

import os
import json
import logging
import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

import redis
import httpx

# Riva client
try:
    import riva.client
    RIVA_AVAILABLE = True
except ImportError:
    RIVA_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A segment of transcribed audio."""
    text: str
    start_time: float
    end_time: float
    speaker_id: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ProcessingResult:
    """Result of audio processing."""
    audio_path: str
    transcript: str
    segments: List[Dict]
    speakers: List[str]
    duration: float
    processing_time: float


class AudioPipelineWorker:
    """Processes audio through modular ASR + diarization pipeline."""

    def __init__(self):
        self.riva_server = os.getenv("RIVA_SERVER", "riva-server:50051")
        self.asr_url = os.getenv("ASR_SERVICE_URL", os.getenv("WHISPER_URL", "")).rstrip("/")
        self.nemo_url = os.getenv("NEMO_DIARIZATION_URL", "http://nemo-diarization:8002")
        self.diarization_url = os.getenv("DIARIZATION_SERVICE_URL", self.nemo_url).rstrip("/")
        self.enrollment_url = os.getenv("SPEAKER_ENROLLMENT_URL", "http://speaker-enrollment:8003")
        self.sara_backend = os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000")
        self.redis_url = os.getenv("REDIS_URL", "redis://audio-redis:6379/0")

        self.redis_client = redis.from_url(self.redis_url)
        self.http_client: Optional[httpx.AsyncClient] = None
        self.riva_client = None

        if RIVA_AVAILABLE:
            try:
                self.riva_client = riva.client.ASRService(
                    riva.client.Auth(uri=self.riva_server)
                )
                logger.info(f"Connected to Riva at {self.riva_server}")
            except Exception as e:
                logger.warning(f"Failed to connect to Riva: {e}")

    async def start(self):
        """Start the worker."""
        self.http_client = httpx.AsyncClient(timeout=120.0)
        logger.info("Audio Pipeline Worker started")
        logger.info(f"Riva: {self.riva_server}")
        if self.asr_url:
            logger.info(f"ASR service: {self.asr_url}")
        logger.info(f"Diarization service: {self.diarization_url}")
        logger.info(f"Sara Backend: {self.sara_backend}")

        # Process queue
        await self.process_queue()

    async def stop(self):
        """Stop the worker."""
        if self.http_client:
            await self.http_client.aclose()

    async def process_queue(self):
        """Process audio files from Redis queue."""
        queue_key = "audio:processing_queue"

        while True:
            try:
                # Block waiting for next item
                result = self.redis_client.blpop(queue_key, timeout=5)

                if result:
                    _, data = result
                    job = json.loads(data)
                    await self.process_job(job)
                else:
                    # Check for any pending jobs
                    await asyncio.sleep(1)

            except redis.RedisError as e:
                logger.error(f"Redis error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Processing error: {e}")
                await asyncio.sleep(1)

    async def process_job(self, job: Dict[str, Any]):
        """Process a single audio job."""
        audio_path = job.get("audio_path")
        job_id = job.get("job_id", "unknown")
        trace_id = str(job.get("trace_id") or job_id)
        job["trace_id"] = trace_id

        if not audio_path or not Path(audio_path).exists():
            logger.error(f"Audio file not found: {audio_path}")
            return

        self.redis_client.hset(
            f"audio:job:{job_id}",
            mapping={
                "status": "running",
                "trace_id": trace_id,
                "started_at": time.time(),
            },
        )

        logger.info("Processing job %s trace=%s: %s", job_id, trace_id, audio_path)
        start_time = time.time()

        try:
            # Step 1: Transcribe with Riva
            transcript_segments = await self.transcribe(audio_path)
            logger.info(f"Transcription complete: {len(transcript_segments)} segments")

            # Step 2: Diarize with NeMo
            diarization = await self.diarize(audio_path)
            logger.info(f"Diarization complete: {diarization.get('num_speakers', 0)} speakers")

            # Step 3: Combine transcript with diarization
            combined_segments = self.combine_results(
                transcript_segments,
                diarization.get("segments", [])
            )

            # Build result
            full_transcript = " ".join(s["text"] for s in combined_segments if s.get("text"))
            speakers = list(set(s.get("speaker_id", "unknown") for s in combined_segments))

            processing_time = time.time() - start_time

            result = ProcessingResult(
                audio_path=audio_path,
                transcript=full_transcript,
                segments=combined_segments,
                speakers=speakers,
                duration=diarization.get("total_duration", 0.0),
                processing_time=processing_time
            )

            # Step 4: Send to Sara backend
            await self.send_to_sara(result, job)

            self.redis_client.hset(
                f"audio:job:{job_id}",
                mapping={
                    "status": "completed",
                    "trace_id": trace_id,
                    "processing_time": processing_time,
                    "completed_at": time.time(),
                },
            )
            logger.info("Job %s trace=%s complete in %.2fs", job_id, trace_id, processing_time)

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            # Store error in Redis
            self.redis_client.hset(f"audio:job:{job_id}", "error", str(e))
            self.redis_client.hset(f"audio:job:{job_id}", "status", "failed")
            self.redis_client.hset(f"audio:job:{job_id}", "trace_id", trace_id)

    async def transcribe(self, audio_path: str) -> List[Dict]:
        """Transcribe audio using Riva, then ASR REST fallback."""
        if RIVA_AVAILABLE and self.riva_client:
            riva_segments = await self._transcribe_riva(audio_path)
            if riva_segments:
                return riva_segments
            logger.warning("Riva transcription empty/failed, trying ASR service fallback")

        if self.asr_url:
            return await self._transcribe_asr_service(audio_path)

        logger.warning("No ASR backend available, returning empty transcript")
        return []

    async def _transcribe_riva(self, audio_path: str) -> List[Dict]:
        """Transcribe audio using Riva ASR."""
        if not RIVA_AVAILABLE or not self.riva_client:
            return []

        try:
            # Read audio file
            import soundfile as sf
            audio_data, sample_rate = sf.read(audio_path)

            # Configure ASR
            config = riva.client.RecognitionConfig(
                language_code="en-US",
                max_alternatives=1,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True
            )

            # Run transcription
            response = self.riva_client.offline_recognize(
                audio_data.tobytes(),
                config
            )

            # Parse results
            segments = []
            for result in response.results:
                if result.alternatives:
                    alt = result.alternatives[0]

                    # Build word-level segments
                    for word_info in alt.words:
                        segments.append({
                            "text": word_info.word,
                            "start_time": word_info.start_time,
                            "end_time": word_info.end_time,
                            "confidence": alt.confidence
                        })

            return segments

        except Exception as e:
            logger.error(f"Riva transcription failed: {e}")
            return []

    async def _transcribe_asr_service(self, audio_path: str) -> List[Dict]:
        """Transcribe audio via ASR REST service (faster-whisper)."""
        try:
            response = await self.http_client.post(
                f"{self.asr_url}/transcribe",
                json={
                    "audio_path": audio_path,
                    "language": "en",
                    "beam_size": 1,
                    "vad_filter": True,
                }
            )
            response.raise_for_status()
            data = response.json()

            word_segments: List[Dict] = []
            for seg in data.get("segments", []):
                words = seg.get("words") or []
                if words:
                    for word in words:
                        word_segments.append({
                            "text": word.get("word", "").strip(),
                            "start_time": float(word.get("start_time", 0.0)),
                            "end_time": float(word.get("end_time", 0.0)),
                            "confidence": float(word.get("confidence", 0.0)),
                        })
                else:
                    # Fallback to segment-level timing when word timings are absent.
                    text = (seg.get("text") or "").strip()
                    if text:
                        word_segments.append({
                            "text": text,
                            "start_time": float(seg.get("start_time", 0.0)),
                            "end_time": float(seg.get("end_time", 0.0)),
                            "confidence": 0.0,
                        })

            if not word_segments and data.get("text"):
                word_segments.append({
                    "text": data.get("text", "").strip(),
                    "start_time": 0.0,
                    "end_time": float(data.get("duration", 0.0)),
                    "confidence": 0.0,
                })

            return word_segments
        except Exception as e:
            logger.error(f"ASR service transcription failed: {e}")
            return []

    async def diarize(self, audio_path: str) -> Dict:
        """Diarize audio using configured diarization service."""
        try:
            response = await self.http_client.post(
                f"{self.diarization_url}/diarize",
                json={
                    "audio_path": audio_path,
                    "max_speakers": 5,
                    "min_speakers": 1
                }
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            return {
                "segments": [],
                "num_speakers": 0,
                "total_duration": 0.0,
                "speaker_labels": []
            }

    def combine_results(
        self,
        transcript_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> List[Dict]:
        """Combine transcription with diarization."""
        if not diarization_segments:
            # No diarization - return transcript as-is
            return [{
                "text": " ".join(s["text"] for s in transcript_segments),
                "start_time": transcript_segments[0]["start_time"] if transcript_segments else 0,
                "end_time": transcript_segments[-1]["end_time"] if transcript_segments else 0,
                "speaker_id": "unknown",
                "confidence": sum(s.get("confidence", 0) for s in transcript_segments) / max(len(transcript_segments), 1)
            }]

        if not transcript_segments:
            # No transcript - return diarization segments
            return diarization_segments

        # Align transcript words with diarization segments
        combined = []

        for diar_seg in diarization_segments:
            seg_start = diar_seg["start_time"]
            seg_end = diar_seg["end_time"]

            # Find words that fall within this segment
            words = []
            for word in transcript_segments:
                word_mid = (word["start_time"] + word["end_time"]) / 2
                if seg_start <= word_mid <= seg_end:
                    words.append(word["text"])

            combined.append({
                "text": " ".join(words),
                "start_time": seg_start,
                "end_time": seg_end,
                "speaker_id": diar_seg.get("speaker_id", "unknown"),
                "confidence": diar_seg.get("confidence", 0.0)
            })

        return combined

    async def send_to_sara(self, result: ProcessingResult, job: Dict):
        """Send processing result to Sara backend."""
        try:
            # Determine primary speaker (for David detection)
            primary_speaker = "unknown"
            if "david" in [s.lower() for s in result.speakers]:
                primary_speaker = "david"
            elif result.speakers:
                primary_speaker = result.speakers[0]

            # Build payload for Sara's raw buffer
            payload = {
                "transcript": result.transcript,
                "speaker": primary_speaker,
                "duration_seconds": result.duration,
                "source": job.get("source", "gpu_cluster"),
                "trace_id": job.get("trace_id"),
                "diarization": {
                    "segments": result.segments,
                    "speakers": result.speakers,
                    "num_speakers": len(result.speakers)
                },
                "metadata": {
                    "job_id": job.get("job_id"),
                    "trace_id": job.get("trace_id"),
                    "processing_time": result.processing_time,
                    "audio_path": result.audio_path
                }
            }

            # Send to Sara's audio input endpoint
            response = await self.http_client.post(
                f"{self.sara_backend}/api/cognitive/audio/processed",
                json=payload,
                headers={"X-Internal-Service": "gpu-audio-worker"}
            )

            if response.status_code == 200:
                logger.info(f"Result sent to Sara: {len(result.transcript)} chars")
            else:
                logger.warning(f"Sara responded with {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to send to Sara: {e}")

    async def queue_audio(
        self,
        audio_path: str,
        source: str = "upload",
        priority: int = 5,
        trace_id: Optional[str] = None,
    ) -> str:
        """Queue an audio file for processing."""
        job_id = str(uuid.uuid4())
        resolved_trace_id = trace_id or job_id
        job = {
            "job_id": job_id,
            "trace_id": resolved_trace_id,
            "audio_path": audio_path,
            "source": source,
            "priority": priority,
            "queued_at": time.time()
        }

        # Add to queue
        self.redis_client.rpush("audio:processing_queue", json.dumps(job))

        # Store job metadata
        self.redis_client.hset(f"audio:job:{job_id}", mapping={
            "status": "queued",
            "trace_id": resolved_trace_id,
            "audio_path": audio_path,
            "source": source
        })

        return job_id


async def main():
    """Main entry point."""
    worker = AudioPipelineWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())

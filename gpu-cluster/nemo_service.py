"""
NeMo/SpeechBrain Speaker Diarization Service

Provides REST API for:
- Speaker diarization (who spoke when)
- Speaker verification (is this David?)
- Speaker embedding extraction
- Speaker enrollment

Uses SpeechBrain as primary (easier install) with NeMo as optional.
"""

import os
import asyncio
import logging
import tempfile
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict

import torch
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Speaker Diarization Service", version="1.0.0")

# Global model instances
speaker_model = None
SPEAKER_PROFILES_DIR = Path(os.getenv("SPEAKER_PROFILES_DIR", "/data/speakers"))
SPEAKER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

# Try SpeechBrain first (easier to install), then NeMo
BACKEND = None
VOICE_CONTROL_URL = os.getenv("VOICE_CONTROL_URL", "").rstrip("/")
VOICE_CONTROL_INTERNAL_TOKEN = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "").strip()
VOICE_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("VOICE_HEARTBEAT_INTERVAL_SECONDS", "15"))
heartbeat_task: Optional[asyncio.Task] = None

try:
    from speechbrain.inference.speaker import EncoderClassifier
    BACKEND = "speechbrain"
    logger.info("Using SpeechBrain backend")
except ImportError:
    try:
        from nemo.collections.asr.models import EncDecSpeakerLabelModel
        BACKEND = "nemo"
        logger.info("Using NeMo backend")
    except ImportError:
        logger.warning("Neither SpeechBrain nor NeMo available - using mock mode")
        BACKEND = "mock"


class DiarizationRequest(BaseModel):
    audio_path: str
    num_speakers: Optional[int] = None
    max_speakers: int = 8
    min_speakers: int = 1


class DiarizationSegment(BaseModel):
    start_time: float
    end_time: float
    speaker_id: str
    confidence: float


class DiarizationResponse(BaseModel):
    segments: List[DiarizationSegment]
    num_speakers: int
    total_duration: float
    speaker_labels: List[str]


class VerificationRequest(BaseModel):
    audio_path: str
    speaker_id: str
    threshold: float = 0.5


class VerificationResponse(BaseModel):
    is_match: bool
    confidence: float
    speaker_id: str


class EnrollmentRequest(BaseModel):
    speaker_id: str
    audio_paths: List[str]


@app.on_event("startup")
async def load_models():
    """Load speaker models on startup."""
    global speaker_model, heartbeat_task

    if BACKEND == "speechbrain":
        try:
            logger.info("Loading SpeechBrain ECAPA-TDNN model...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Using device: {device}")
            speaker_model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="/data/models/speechbrain",
                run_opts={"device": device}
            )
            logger.info(f"SpeechBrain model loaded successfully on {speaker_model.device}")
        except Exception as e:
            logger.error(f"Failed to load SpeechBrain model: {e}")

    elif BACKEND == "nemo":
        try:
            logger.info("Loading NeMo TitaNet model...")
            from nemo.collections.asr.models import EncDecSpeakerLabelModel
            speaker_model = EncDecSpeakerLabelModel.from_pretrained(
                "nvidia/speakerverification_en_titanet_large"
            )
            speaker_model.eval()
            if torch.cuda.is_available():
                speaker_model = speaker_model.cuda()
            logger.info("NeMo model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load NeMo model: {e}")

    if VOICE_CONTROL_URL and VOICE_CONTROL_INTERNAL_TOKEN:
        heartbeat_task = asyncio.create_task(_heartbeat_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    global heartbeat_task
    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        heartbeat_task = None


async def _heartbeat_loop() -> None:
    url = f"{VOICE_CONTROL_URL}/api/voice-control/services/speaker-diarization/heartbeat"
    headers = {
        "X-Internal-Service": "speaker-diarization",
        "X-Internal-Token": VOICE_CONTROL_INTERNAL_TOKEN,
    }
    async with httpx.AsyncClient(timeout=6.0) as client:
        while True:
            try:
                status = "healthy" if speaker_model is not None or BACKEND == "mock" else "degraded"
                response = await client.post(
                    url,
                    json={
                        "status": status,
                        "version": f"nemo-service-{BACKEND or 'unknown'}-v1.0.0",
                        "latency_ms": 0.0,
                        "details": {
                            "backend": BACKEND,
                            "model_loaded": speaker_model is not None,
                            "gpu_available": torch.cuda.is_available(),
                        },
                    },
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.debug("NeMo heartbeat failed: %s", exc)
            await asyncio.sleep(VOICE_HEARTBEAT_INTERVAL_SECONDS)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy" if speaker_model is not None or BACKEND == "mock" else "degraded",
        "backend": BACKEND,
        "model_loaded": speaker_model is not None,
        "gpu_available": torch.cuda.is_available(),
        "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0
    }


@app.post("/diarize", response_model=DiarizationResponse)
async def diarize_audio(request: DiarizationRequest):
    """Perform speaker diarization on audio file."""
    audio_path = Path(request.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    try:
        if BACKEND == "mock":
            # Return mock diarization
            return DiarizationResponse(
                segments=[DiarizationSegment(
                    start_time=0.0,
                    end_time=5.0,
                    speaker_id="speaker_0",
                    confidence=0.8
                )],
                num_speakers=1,
                total_duration=5.0,
                speaker_labels=["speaker_0"]
            )

        # Extract embeddings for segments
        embeddings, timestamps = await extract_segment_embeddings(str(audio_path))

        if len(embeddings) == 0:
            return DiarizationResponse(
                segments=[],
                num_speakers=0,
                total_duration=0.0,
                speaker_labels=[]
            )

        # Cluster embeddings
        labels, num_speakers = cluster_embeddings(
            embeddings,
            num_speakers=request.num_speakers,
            max_speakers=request.max_speakers,
            min_speakers=request.min_speakers
        )

        # Build segments
        segments = build_segments(labels, timestamps)

        # Try to identify known speakers
        segments = await identify_known_speakers(segments, embeddings, labels, timestamps)

        total_duration = timestamps[-1][1] if timestamps else 0.0
        speaker_labels = list(set(s.speaker_id for s in segments))

        return DiarizationResponse(
            segments=segments,
            num_speakers=num_speakers,
            total_duration=total_duration,
            speaker_labels=speaker_labels
        )

    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/verify", response_model=VerificationResponse)
async def verify_speaker(request: VerificationRequest):
    """Verify if audio matches a known speaker."""
    audio_path = Path(request.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    profile_path = SPEAKER_PROFILES_DIR / f"{request.speaker_id}.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {request.speaker_id}")

    try:
        with open(profile_path) as f:
            profile = json.load(f)

        enrolled_embedding = np.array(profile["embedding"])
        test_embedding = await extract_embedding(str(audio_path))

        similarity = cosine_similarity(test_embedding, enrolled_embedding)
        is_match = similarity >= request.threshold

        return VerificationResponse(
            is_match=is_match,
            confidence=float(similarity),
            speaker_id=request.speaker_id
        )

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/verify-upload", response_model=VerificationResponse)
async def verify_speaker_upload(
    file: UploadFile = File(...),
    speaker_id: str = "david",
    threshold: float = 0.5
):
    """Verify if uploaded audio matches a known speaker."""
    profile_path = SPEAKER_PROFILES_DIR / f"{speaker_id}.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with open(profile_path) as f:
                profile = json.load(f)

            enrolled_embedding = np.array(profile["embedding"])
            test_embedding = await extract_embedding(tmp_path)

            similarity = cosine_similarity(test_embedding, enrolled_embedding)
            is_match = similarity >= threshold

            return VerificationResponse(
                is_match=is_match,
                confidence=float(similarity),
                speaker_id=speaker_id
            )
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/enroll")
async def enroll_speaker(request: EnrollmentRequest):
    """Enroll a speaker with audio samples."""
    for path in request.audio_paths:
        if not Path(path).exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {path}")

    try:
        # Extract embeddings from all samples
        embeddings = []
        for audio_path in request.audio_paths:
            emb = await extract_embedding(audio_path)
            embeddings.append(emb)

        # Average embeddings
        mean_embedding = np.mean(embeddings, axis=0)
        mean_embedding = mean_embedding / np.linalg.norm(mean_embedding)

        # Save profile
        profile = {
            "speaker_id": request.speaker_id,
            "embedding": mean_embedding.tolist(),
            "num_samples": len(request.audio_paths),
            "sample_paths": request.audio_paths
        }

        profile_path = SPEAKER_PROFILES_DIR / f"{request.speaker_id}.json"
        with open(profile_path, "w") as f:
            json.dump(profile, f)

        logger.info(f"Enrolled speaker '{request.speaker_id}' with {len(request.audio_paths)} samples")

        return {
            "status": "success",
            "speaker_id": request.speaker_id,
            "num_samples": len(request.audio_paths)
        }

    except Exception as e:
        logger.error(f"Enrollment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/speakers")
async def list_speakers():
    """List all enrolled speakers."""
    speakers = []
    for profile_path in SPEAKER_PROFILES_DIR.glob("*.json"):
        try:
            with open(profile_path) as f:
                profile = json.load(f)
            speakers.append({
                "speaker_id": profile["speaker_id"],
                "num_samples": profile.get("num_samples", 0)
            })
        except Exception as e:
            logger.warning(f"Failed to load profile {profile_path}: {e}")

    return {"speakers": speakers}


@app.delete("/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """Delete an enrolled speaker."""
    profile_path = SPEAKER_PROFILES_DIR / f"{speaker_id}.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

    profile_path.unlink()
    return {"status": "deleted", "speaker_id": speaker_id}


@app.post("/embedding")
async def get_embedding(audio_path: str):
    """Extract speaker embedding from audio."""
    if not Path(audio_path).exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    try:
        embedding = await extract_embedding(audio_path)
        return {
            "embedding": embedding.tolist(),
            "dimension": len(embedding)
        }
    except Exception as e:
        logger.error(f"Embedding extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Helper Functions
# ============================================

async def extract_embedding(audio_path: str) -> np.ndarray:
    """Extract speaker embedding from audio file."""
    if BACKEND == "mock":
        return np.random.randn(192).astype(np.float32)

    if BACKEND == "speechbrain":
        signal = speaker_model.load_audio(audio_path)
        # Ensure signal is on the same device as the model
        device = next(speaker_model.mods.embedding_model.parameters()).device
        if signal.device != device:
            signal = signal.to(device)
        embedding = speaker_model.encode_batch(signal)
        return embedding.squeeze().cpu().numpy()

    elif BACKEND == "nemo":
        with torch.no_grad():
            embedding = speaker_model.get_embedding(audio_path)
            if isinstance(embedding, torch.Tensor):
                embedding = embedding.cpu().numpy()
            return embedding.flatten()

    return np.random.randn(192).astype(np.float32)


async def extract_segment_embeddings(
    audio_path: str,
    window_size: float = 1.5,
    shift: float = 0.75
) -> tuple:
    """Extract embeddings for audio segments."""
    import soundfile as sf

    audio, sr = sf.read(audio_path)
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)

    embeddings = []
    timestamps = []

    window_samples = int(window_size * sr)
    shift_samples = int(shift * sr)

    pos = 0
    while pos + window_samples <= len(audio):
        segment = audio[pos:pos + window_samples]

        # Save segment to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, segment, sr)
            temp_path = f.name

        try:
            emb = await extract_embedding(temp_path)
            embeddings.append(emb)

            start_time = pos / sr
            end_time = (pos + window_samples) / sr
            timestamps.append((start_time, end_time))
        finally:
            os.unlink(temp_path)

        pos += shift_samples

    return np.array(embeddings) if embeddings else np.array([]), timestamps


def cluster_embeddings(
    embeddings: np.ndarray,
    num_speakers: Optional[int] = None,
    max_speakers: int = 8,
    min_speakers: int = 1
) -> tuple:
    """Cluster embeddings to identify speakers."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    if len(embeddings) < 2:
        return np.zeros(len(embeddings), dtype=int), 1

    if num_speakers is not None:
        clustering = AgglomerativeClustering(
            n_clusters=num_speakers,
            metric='cosine',
            linkage='average'
        )
        labels = clustering.fit_predict(embeddings)
        return labels, num_speakers

    # Auto-detect number of speakers
    best_score = -1
    best_labels = None
    best_n = min_speakers

    for n in range(min_speakers, min(max_speakers + 1, len(embeddings))):
        try:
            clustering = AgglomerativeClustering(
                n_clusters=n,
                metric='cosine',
                linkage='average'
            )
            labels = clustering.fit_predict(embeddings)

            if n > 1 and len(set(labels)) > 1:
                score = silhouette_score(embeddings, labels, metric='cosine')
                if score > best_score:
                    best_score = score
                    best_labels = labels
                    best_n = n
        except Exception:
            continue

    if best_labels is None:
        best_labels = np.zeros(len(embeddings), dtype=int)
        best_n = 1

    return best_labels, best_n


def build_segments(labels: np.ndarray, timestamps: List[tuple]) -> List[DiarizationSegment]:
    """Build diarization segments from labels and timestamps."""
    segments = []
    current_speaker = None
    segment_start = None

    for i, (label, (start, end)) in enumerate(zip(labels, timestamps)):
        speaker_id = f"speaker_{label}"

        if speaker_id != current_speaker:
            if current_speaker is not None:
                segments.append(DiarizationSegment(
                    start_time=segment_start,
                    end_time=timestamps[i-1][1],
                    speaker_id=current_speaker,
                    confidence=0.8
                ))
            current_speaker = speaker_id
            segment_start = start

    # Add final segment
    if current_speaker is not None and timestamps:
        segments.append(DiarizationSegment(
            start_time=segment_start,
            end_time=timestamps[-1][1],
            speaker_id=current_speaker,
            confidence=0.8
        ))

    return segments


async def identify_known_speakers(
    segments: List[DiarizationSegment],
    embeddings: np.ndarray,
    labels: np.ndarray,
    timestamps: List[tuple]
) -> List[DiarizationSegment]:
    """Try to identify known speakers in segments."""
    profiles = {}
    for profile_path in SPEAKER_PROFILES_DIR.glob("*.json"):
        try:
            with open(profile_path) as f:
                profile = json.load(f)
            profiles[profile["speaker_id"]] = np.array(profile["embedding"])
        except Exception:
            continue

    if not profiles:
        return segments

    # Compute average embedding per speaker label
    unique_labels = set(labels)
    label_embeddings = {}

    for label in unique_labels:
        mask = labels == label
        label_embeddings[label] = np.mean(embeddings[mask], axis=0)

    # Match labels to known speakers
    label_mapping = {}
    for label, emb in label_embeddings.items():
        best_match = None
        best_score = 0.5  # Threshold

        for speaker_id, profile_emb in profiles.items():
            similarity = cosine_similarity(emb, profile_emb)
            if similarity > best_score:
                best_score = similarity
                best_match = speaker_id

        if best_match:
            label_mapping[f"speaker_{label}"] = best_match

    # Update segments
    updated = []
    for seg in segments:
        if seg.speaker_id in label_mapping:
            seg.speaker_id = label_mapping[seg.speaker_id]
            seg.confidence = 0.9
        updated.append(seg)

    return updated


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity."""
    a = a.flatten()
    b = b.flatten()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

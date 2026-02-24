"""
pyannote diarization service scaffold.

Compatible contract with existing NeMo diarization endpoint:
- POST /diarize
- GET /health
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pyannote_service")

app = FastAPI(title="pyannote Diarization Service", version="0.1.0")

PYANNOTE_MODEL = os.getenv(
    "PYANNOTE_MODEL",
    "pyannote/speaker-diarization-community-1",
)
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "")
VOICE_CONTROL_URL = os.getenv("VOICE_CONTROL_URL", "").rstrip("/")
VOICE_CONTROL_INTERNAL_TOKEN = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "").strip()
VOICE_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("VOICE_HEARTBEAT_INTERVAL_SECONDS", "15"))

diar_pipeline = None
DIAR_BACKEND = "mock"
heartbeat_task: Optional[asyncio.Task] = None


class DiarizationRequest(BaseModel):
    audio_path: str
    num_speakers: Optional[int] = None
    max_speakers: int = 8
    min_speakers: int = 1


class DiarizationSegment(BaseModel):
    start_time: float
    end_time: float
    speaker_id: str
    confidence: float = 0.0


class DiarizationResponse(BaseModel):
    segments: List[DiarizationSegment]
    num_speakers: int
    total_duration: float
    speaker_labels: List[str]


@app.on_event("startup")
async def startup() -> None:
    global diar_pipeline, DIAR_BACKEND, heartbeat_task
    try:
        from pyannote.audio import Pipeline

        kwargs = {"use_auth_token": HUGGINGFACE_TOKEN} if HUGGINGFACE_TOKEN else {}
        diar_pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, **kwargs)
        DIAR_BACKEND = "pyannote"
        logger.info("Loaded pyannote pipeline model=%s", PYANNOTE_MODEL)
    except Exception as exc:
        DIAR_BACKEND = "mock"
        diar_pipeline = None
        logger.warning("Falling back to mock diarization: %s", exc)

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
                status = "healthy" if DIAR_BACKEND == "pyannote" else "degraded"
                response = await client.post(
                    url,
                    json={
                        "status": status,
                        "version": "pyannote-service-v0.1.0",
                        "latency_ms": 0.0,
                        "details": {
                            "backend": DIAR_BACKEND,
                            "model": PYANNOTE_MODEL,
                        },
                    },
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.debug("pyannote heartbeat failed: %s", exc)
            await asyncio.sleep(VOICE_HEARTBEAT_INTERVAL_SECONDS)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {
        "status": "healthy" if DIAR_BACKEND == "pyannote" else "degraded",
        "backend": DIAR_BACKEND,
        "model": PYANNOTE_MODEL,
    }


@app.post("/diarize", response_model=DiarizationResponse)
async def diarize(request: DiarizationRequest) -> DiarizationResponse:
    audio_path = Path(request.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    if DIAR_BACKEND != "pyannote" or diar_pipeline is None:
        return DiarizationResponse(
            segments=[
                DiarizationSegment(
                    start_time=0.0,
                    end_time=4.0,
                    speaker_id="speaker_0",
                    confidence=0.5,
                )
            ],
            num_speakers=1,
            total_duration=4.0,
            speaker_labels=["speaker_0"],
        )

    try:
        diar_kwargs = {}
        if request.num_speakers is not None:
            diar_kwargs["num_speakers"] = request.num_speakers
        else:
            diar_kwargs["min_speakers"] = request.min_speakers
            diar_kwargs["max_speakers"] = request.max_speakers

        diarization = diar_pipeline(str(audio_path), **diar_kwargs)

        # Map pyannote speaker labels to stable speaker_N IDs.
        label_map: Dict[str, str] = {}
        segments: List[DiarizationSegment] = []
        label_index = 0

        for turn, _track, label in diarization.itertracks(yield_label=True):
            if label not in label_map:
                label_map[label] = f"speaker_{label_index}"
                label_index += 1
            segments.append(
                DiarizationSegment(
                    start_time=float(turn.start),
                    end_time=float(turn.end),
                    speaker_id=label_map[label],
                    confidence=0.8,
                )
            )

        total_duration = max((seg.end_time for seg in segments), default=0.0)
        speaker_labels = sorted({seg.speaker_id for seg in segments})
        return DiarizationResponse(
            segments=segments,
            num_speakers=len(speaker_labels),
            total_duration=total_duration,
            speaker_labels=speaker_labels,
        )
    except Exception as exc:
        logger.error("pyannote diarization failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8004)

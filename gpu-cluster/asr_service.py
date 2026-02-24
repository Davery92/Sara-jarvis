"""
ASR Service (faster-whisper scaffold)

Provides REST speech-to-text for the modular voice pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr_service")

app = FastAPI(title="ASR Service", version="0.1.0")

ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "distil-large-v3")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cuda")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")
VOICE_CONTROL_URL = os.getenv("VOICE_CONTROL_URL", "").rstrip("/")
VOICE_CONTROL_INTERNAL_TOKEN = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "").strip()
VOICE_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("VOICE_HEARTBEAT_INTERVAL_SECONDS", "15"))

asr_model = None
ASR_BACKEND = "mock"
ASR_RUNTIME_DEVICE = ASR_DEVICE
ASR_RUNTIME_COMPUTE_TYPE = ASR_COMPUTE_TYPE
heartbeat_task: Optional[asyncio.Task] = None


class TranscribeRequest(BaseModel):
    audio_path: str
    language: Optional[str] = "en"
    beam_size: int = 1
    vad_filter: bool = True


class WordResult(BaseModel):
    word: str
    start_time: float
    end_time: float
    confidence: float = 0.0


class SegmentResult(BaseModel):
    id: int
    text: str
    start_time: float
    end_time: float
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    words: List[WordResult] = []


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration: float
    segments: List[SegmentResult]
    backend: str


@app.on_event("startup")
async def startup() -> None:
    global asr_model, ASR_BACKEND, heartbeat_task
    global ASR_RUNTIME_DEVICE, ASR_RUNTIME_COMPUTE_TYPE
    try:
        from faster_whisper import WhisperModel

        tried: List[str] = []
        candidates: List[tuple[str, str]] = []

        def _add_candidate(device: str, compute: str) -> None:
            item = (device, compute)
            if item not in candidates:
                candidates.append(item)

        _add_candidate(ASR_DEVICE, ASR_COMPUTE_TYPE)
        if ASR_DEVICE == "cuda":
            for compute_type in ["int8_float16", "int8", "float32", "float16"]:
                _add_candidate("cuda", compute_type)
            for compute_type in ["int8", "float32"]:
                _add_candidate("cpu", compute_type)
        else:
            for compute_type in ["int8", "float32"]:
                _add_candidate(ASR_DEVICE, compute_type)
            _add_candidate("cpu", "int8")
            _add_candidate("cpu", "float32")

        last_exc: Optional[Exception] = None
        for device, compute_type in candidates:
            try:
                logger.info(
                    "Loading faster-whisper model=%s device=%s compute=%s",
                    ASR_MODEL_NAME,
                    device,
                    compute_type,
                )
                asr_model = WhisperModel(
                    ASR_MODEL_NAME,
                    device=device,
                    compute_type=compute_type,
                )
                ASR_BACKEND = "faster-whisper"
                ASR_RUNTIME_DEVICE = device
                ASR_RUNTIME_COMPUTE_TYPE = compute_type
                logger.info(
                    "ASR model loaded with device=%s compute=%s",
                    device,
                    compute_type,
                )
                break
            except Exception as exc:
                tried.append(f"{device}/{compute_type}: {exc}")
                last_exc = exc

        if asr_model is None:
            raise last_exc or RuntimeError("Unknown ASR initialization error")
    except Exception as exc:
        ASR_BACKEND = "mock"
        asr_model = None
        ASR_RUNTIME_DEVICE = ASR_DEVICE
        ASR_RUNTIME_COMPUTE_TYPE = ASR_COMPUTE_TYPE
        logger.warning("ASR backend unavailable, using mock mode: %s", exc)

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
    url = f"{VOICE_CONTROL_URL}/api/voice-control/services/speech-asr/heartbeat"
    headers = {
        "X-Internal-Service": "speech-asr",
        "X-Internal-Token": VOICE_CONTROL_INTERNAL_TOKEN,
    }
    async with httpx.AsyncClient(timeout=6.0) as client:
        while True:
            try:
                status = "healthy" if ASR_BACKEND != "mock" else "degraded"
                response = await client.post(
                    url,
                    json={
                        "status": status,
                        "version": "asr-service-v0.1.0",
                        "latency_ms": 0.0,
                        "details": {
                        "backend": ASR_BACKEND,
                        "model": ASR_MODEL_NAME,
                        "device": ASR_RUNTIME_DEVICE,
                        "compute_type": ASR_RUNTIME_COMPUTE_TYPE,
                        "requested_device": ASR_DEVICE,
                        "requested_compute_type": ASR_COMPUTE_TYPE,
                    },
                },
                headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.debug("ASR heartbeat failed: %s", exc)
            await asyncio.sleep(VOICE_HEARTBEAT_INTERVAL_SECONDS)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "healthy" if ASR_BACKEND != "mock" else "degraded",
        "backend": ASR_BACKEND,
        "model": ASR_MODEL_NAME,
        "device": ASR_RUNTIME_DEVICE,
        "compute_type": ASR_RUNTIME_COMPUTE_TYPE,
        "requested_device": ASR_DEVICE,
        "requested_compute_type": ASR_COMPUTE_TYPE,
    }


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    audio_path = Path(req.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

    if ASR_BACKEND == "mock" or asr_model is None:
        return TranscribeResponse(
            text="",
            language=req.language or "en",
            duration=0.0,
            segments=[],
            backend=ASR_BACKEND,
        )

    try:
        segments_gen, info = asr_model.transcribe(
            str(audio_path),
            language=req.language,
            beam_size=req.beam_size,
            vad_filter=req.vad_filter,
            word_timestamps=True,
        )

        text_parts: List[str] = []
        segments: List[SegmentResult] = []
        for idx, seg in enumerate(segments_gen):
            words: List[WordResult] = []
            for w in (seg.words or []):
                words.append(
                    WordResult(
                        word=w.word,
                        start_time=float(w.start or 0.0),
                        end_time=float(w.end or 0.0),
                        confidence=float(getattr(w, "probability", 0.0)),
                    )
                )
            cleaned = (seg.text or "").strip()
            if cleaned:
                text_parts.append(cleaned)
            segments.append(
                SegmentResult(
                    id=idx,
                    text=cleaned,
                    start_time=float(seg.start or 0.0),
                    end_time=float(seg.end or 0.0),
                    avg_logprob=float(getattr(seg, "avg_logprob", 0.0)),
                    no_speech_prob=float(getattr(seg, "no_speech_prob", 0.0)),
                    words=words,
                )
            )

        return TranscribeResponse(
            text=" ".join(text_parts).strip(),
            language=info.language or (req.language or "en"),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            segments=segments,
            backend=ASR_BACKEND,
        )
    except Exception as exc:
        logger.error("ASR transcription failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8585)

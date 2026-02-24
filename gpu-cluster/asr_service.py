"""
ASR Service (faster-whisper scaffold)

Provides REST speech-to-text for the modular voice pipeline.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr_service")

app = FastAPI(title="ASR Service", version="0.1.0")

ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "distil-large-v3")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cuda")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")

asr_model = None
ASR_BACKEND = "mock"


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
    global asr_model, ASR_BACKEND
    try:
        from faster_whisper import WhisperModel

        logger.info(
            "Loading faster-whisper model=%s device=%s compute=%s",
            ASR_MODEL_NAME,
            ASR_DEVICE,
            ASR_COMPUTE_TYPE,
        )
        asr_model = WhisperModel(
            ASR_MODEL_NAME,
            device=ASR_DEVICE,
            compute_type=ASR_COMPUTE_TYPE,
        )
        ASR_BACKEND = "faster-whisper"
        logger.info("ASR model loaded")
    except Exception as exc:
        ASR_BACKEND = "mock"
        asr_model = None
        logger.warning("ASR backend unavailable, using mock mode: %s", exc)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "healthy" if ASR_BACKEND != "mock" else "degraded",
        "backend": ASR_BACKEND,
        "model": ASR_MODEL_NAME,
        "device": ASR_DEVICE,
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


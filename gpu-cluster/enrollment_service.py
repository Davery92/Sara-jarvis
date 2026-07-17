"""
Speaker Enrollment Service

Simple REST API for enrolling speakers via the NeMo diarization service.
Handles audio file upload and management.
"""

import os
import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Speaker Enrollment Service", version="1.0.0")

NEMO_URL = os.getenv("NEMO_DIARIZATION_URL", "http://nemo-diarization:8002")
VOICE_CONTROL_URL = os.getenv("VOICE_CONTROL_URL", "").rstrip("/")
VOICE_CONTROL_INTERNAL_TOKEN = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "").strip()
VOICE_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("VOICE_HEARTBEAT_INTERVAL_SECONDS", "15"))
SAMPLES_DIR = Path("/data/samples")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
heartbeat_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def startup() -> None:
    global heartbeat_task
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
    url = f"{VOICE_CONTROL_URL}/api/voice-control/services/speaker-registry/heartbeat"
    headers = {
        "X-Internal-Service": "speaker-registry",
        "X-Internal-Token": VOICE_CONTROL_INTERNAL_TOKEN,
    }
    async with httpx.AsyncClient(timeout=6.0) as client:
        while True:
            try:
                response = await client.post(
                    url,
                    json={
                        "status": "healthy",
                        "version": "enrollment-service-v1.0.0",
                        "latency_ms": 0.0,
                        "details": {"nemo_url": NEMO_URL},
                    },
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.debug("enrollment heartbeat failed: %s", exc)
            await asyncio.sleep(VOICE_HEARTBEAT_INTERVAL_SECONDS)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy"}


@app.post("/enroll/{speaker_id}")
async def enroll_speaker(
    speaker_id: str,
    files: List[UploadFile] = File(...),
    display_name: Optional[str] = Form(None)
):
    """
    Enroll a speaker with audio samples.

    Upload 1-5 audio files (WAV/MP3) of the speaker talking.
    More samples = better recognition.
    """
    if len(files) < 1:
        raise HTTPException(status_code=400, detail="At least 1 audio sample required")
    if len(files) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 samples allowed")

    # Create speaker directory
    speaker_dir = SAMPLES_DIR / speaker_id
    speaker_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded files
    saved_paths = []
    try:
        for i, file in enumerate(files):
            # Validate file type
            if not file.filename.lower().endswith(('.wav', '.mp3', '.flac', '.ogg')):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file type: {file.filename}. Use WAV, MP3, FLAC, or OGG."
                )

            # Save file
            ext = Path(file.filename).suffix
            file_path = speaker_dir / f"sample_{i}{ext}"
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            saved_paths.append(str(file_path))

        # Call NeMo service to create enrollment
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{NEMO_URL}/enroll",
                json={
                    "speaker_id": speaker_id,
                    "audio_paths": saved_paths
                }
            )
            response.raise_for_status()
            result = response.json()

        # Save metadata
        metadata = {
            "speaker_id": speaker_id,
            "display_name": display_name or speaker_id,
            "num_samples": len(saved_paths),
            "sample_paths": saved_paths
        }
        with open(speaker_dir / "metadata.json", "w") as f:
            json.dump(metadata, f)

        logger.info(f"Enrolled speaker '{speaker_id}' with {len(saved_paths)} samples")

        return {
            "status": "success",
            "speaker_id": speaker_id,
            "display_name": display_name or speaker_id,
            "num_samples": len(saved_paths)
        }

    except httpx.HTTPError as e:
        # Clean up on failure
        shutil.rmtree(speaker_dir, ignore_errors=True)
        logger.error(f"Enrollment failed: {e}")
        raise HTTPException(status_code=500, detail=f"Enrollment failed: {str(e)}")
    except Exception as e:
        shutil.rmtree(speaker_dir, ignore_errors=True)
        logger.error(f"Enrollment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/speakers")
async def list_speakers():
    """List all enrolled speakers."""
    speakers = []
    for speaker_dir in SAMPLES_DIR.iterdir():
        if speaker_dir.is_dir():
            metadata_path = speaker_dir / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)
                speakers.append({
                    "speaker_id": metadata["speaker_id"],
                    "display_name": metadata.get("display_name", metadata["speaker_id"]),
                    "num_samples": metadata.get("num_samples", 0)
                })
    return {"speakers": speakers}


@app.get("/speakers/{speaker_id}")
async def get_speaker(speaker_id: str):
    """Get speaker details."""
    speaker_dir = SAMPLES_DIR / speaker_id
    metadata_path = speaker_dir / "metadata.json"

    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

    with open(metadata_path) as f:
        return json.load(f)


@app.delete("/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """Delete an enrolled speaker."""
    speaker_dir = SAMPLES_DIR / speaker_id

    if not speaker_dir.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

    # Delete from NeMo service
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.delete(f"{NEMO_URL}/speakers/{speaker_id}")
    except Exception as e:
        logger.warning(f"Failed to delete from NeMo: {e}")

    # Delete local files
    shutil.rmtree(speaker_dir, ignore_errors=True)

    return {"status": "deleted", "speaker_id": speaker_id}


@app.post("/speakers/{speaker_id}/add-sample")
async def add_sample(speaker_id: str, file: UploadFile = File(...)):
    """Add an additional sample to an existing speaker."""
    speaker_dir = SAMPLES_DIR / speaker_id
    metadata_path = speaker_dir / "metadata.json"

    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

    # Load metadata
    with open(metadata_path) as f:
        metadata = json.load(f)

    # Save new sample
    ext = Path(file.filename).suffix
    sample_num = metadata.get("num_samples", 0)
    file_path = speaker_dir / f"sample_{sample_num}{ext}"

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Update metadata
    metadata["num_samples"] = sample_num + 1
    metadata["sample_paths"].append(str(file_path))

    with open(metadata_path, "w") as f:
        json.dump(metadata, f)

    # Re-enroll with all samples
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{NEMO_URL}/enroll",
                json={
                    "speaker_id": speaker_id,
                    "audio_paths": metadata["sample_paths"]
                }
            )
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Re-enrollment failed: {e}")

    return {
        "status": "success",
        "speaker_id": speaker_id,
        "num_samples": metadata["num_samples"]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

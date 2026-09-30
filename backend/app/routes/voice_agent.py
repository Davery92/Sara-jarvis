"""Voice-agent STT/TTS endpoints.

Moved out of main_simple.py on 2026-09-30 (cleanup plan 4.3), paths and
response shapes unchanged. These two are pure transport to the two off-box
voice services and touch none of the chat machinery, which is why they could
move while `/api/pi-dashboard/voice/chat` could not.

Hosts are the GPU box's Whisper (10.185.1.8:8585) and Kokoro TTS
(10.185.1.9:8880), left as literals exactly as they were rather than being
quietly promoted to configuration in a move commit.
"""
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-agent"])


@router.post("/api/voice-agent/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transcribe audio using Whisper STT service.
    Returns just the transcription text.
    """
    try:
        # Save audio file temporarily
        audio_content = await audio.read()
        temp_audio_path = f"/tmp/voice_{uuid.uuid4()}.m4a"

        with open(temp_audio_path, "wb") as f:
            f.write(audio_content)

        # Known Whisper hallucinations on silence/noise
        WHISPER_HALLUCINATIONS = {
            "thank you", "thanks", "thanks for watching", "thank you for watching",
            "please subscribe", "subscribe", "bye", "goodbye", "see you next time",
            "you", "the", "i", "a", "", "so", "um", "uh", "hmm", "oh",
            "thank you.", "thanks.", "bye.", "goodbye."
        }

        # Call Whisper STT service (OpenAI-compatible API)
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(temp_audio_path, "rb") as audio_file:
                files = {"file": ("audio.m4a", audio_file, "audio/m4a")}
                data = {
                    "model": "distil-small.en",
                    "language": "en",
                    "vad_filter": "true",
                    "no_speech_threshold": "0.4",
                    "compression_ratio_threshold": "2.0",
                }
                whisper_response = await client.post(
                    "http://10.185.1.8:8585/v1/audio/transcriptions",
                    files=files,
                    data=data
                )

            if whisper_response.status_code != 200:
                logger.error(f"[Voice] Whisper error: {whisper_response.status_code} - {whisper_response.text}")
                raise HTTPException(status_code=500, detail="Transcription service error")

            result = whisper_response.json()
            transcription = result.get("text", "").strip()

        # Filter out hallucinations
        if transcription.lower() in WHISPER_HALLUCINATIONS:
            logger.info(f"[Voice] Filtered hallucination for user {current_user.id}: '{transcription}'")
            transcription = ""
        elif len(transcription.split()) <= 2 and transcription.lower().rstrip('.!?') in WHISPER_HALLUCINATIONS:
            logger.info(f"[Voice] Filtered short hallucination for user {current_user.id}: '{transcription}'")
            transcription = ""
        else:
            logger.info(f"[Voice] Transcribed audio for user {current_user.id}: {transcription}")

        # Clean up temp file
        try:
            os.remove(temp_audio_path)
        except OSError as e:
            logger.debug(f"Failed to remove temp audio file: {e}")

        return {"transcription": transcription}

    except Exception as e:
        logger.error(f"[Voice] Error transcribing audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/voice-agent/speak")
async def speak_text(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Convert text to speech using Kokoro TTS.
    Returns audio file (WAV default for iOS compatibility).
    """
    try:
        body = await request.json()
        text = body.get("text", "")
        response_format = body.get("response_format", "wav")  # Default WAV for iOS compatibility

        if not text:
            raise HTTPException(status_code=400, detail="No text provided")

        logger.info(f"[Voice] Generating speech for user {current_user.id}: {text[:50]}... (format: {response_format})")

        # Call Kokoro TTS service with blended voice
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            tts_response = await client.post(
                "http://10.185.1.9:8880/v1/audio/speech",
                json={
                    "input": text,
                    "model": "kokoro",
                    "voice": "af_sarah(1)+af_bella(1)",
                    "response_format": response_format,
                    "speed": 1.0
                }
            )

            if tts_response.status_code != 200:
                logger.error(f"[Voice] Kokoro TTS error: {tts_response.status_code} - {tts_response.text}")
                raise HTTPException(status_code=500, detail="TTS service error")

            # Determine media type based on format
            media_type_map = {
                "mp3": "audio/mpeg",
                "wav": "audio/wav",
                "opus": "audio/opus",
                "flac": "audio/flac",
                "pcm": "audio/pcm",
                "m4a": "audio/mp4"
            }
            media_type = media_type_map.get(response_format, "audio/mpeg")

            return Response(
                content=tts_response.content,
                media_type=media_type,
                headers={
                    "Content-Disposition": f"attachment; filename=speech.{response_format}"
                }
            )

    except Exception as e:
        logger.error(f"[Voice] Error generating speech: {e}")
        raise HTTPException(status_code=500, detail=str(e))

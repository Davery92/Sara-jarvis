"""
Wyoming Protocol Server for Voice
Handles STT and TTS via Wyoming protocol
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging
import json
import base64
import httpx
import io
import wave

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
STT_URL = "http://10.185.1.8:8585/v1/audio/transcriptions"
TTS_URL = "http://10.185.1.8:9000/v1/audio/speech"


@router.websocket("/wyoming/asr")
async def wyoming_asr(websocket: WebSocket):
    """
    Wyoming ASR (Automatic Speech Recognition) endpoint
    Receives audio from agents, transcribes via Faster-Whisper, returns text
    """
    await websocket.accept()
    logger.info("Wyoming ASR client connected")

    try:
        audio_chunks = []

        while True:
            # Receive Wyoming message
            message = await websocket.receive_text()
            data = json.loads(message)

            if data["type"] == "audio-chunk":
                # Decode base64 audio
                audio_bytes = base64.b64decode(data["audio"])
                audio_chunks.append(audio_bytes)
                logger.debug(f"Received audio chunk: {len(audio_bytes)} bytes")

            elif data["type"] == "audio-stop":
                # Reconstruct full audio
                full_audio = b"".join(audio_chunks)
                logger.info(f"Received complete audio: {len(full_audio)} bytes")

                # Create WAV file in memory
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(data.get("rate", 16000))
                    wav_file.writeframes(full_audio)

                wav_buffer.seek(0)

                # Send to STT service (Faster-Whisper)
                try:
                    async with httpx.AsyncClient() as client:
                        files = {
                            'file': ('audio.wav', wav_buffer, 'audio/wav')
                        }
                        form_data = {
                            'model': 'whisper-1',
                            'language': 'en'
                        }

                        response = await client.post(
                            STT_URL,
                            files=files,
                            data=form_data,
                            timeout=30.0
                        )

                        if response.status_code == 200:
                            result = response.json()
                            transcript = result.get("text", "").strip()
                            logger.info(f"📝 Transcript: {transcript}")

                            # Send transcript back via Wyoming protocol
                            await websocket.send_text(json.dumps({
                                "type": "transcript",
                                "text": transcript
                            }))
                        else:
                            logger.error(f"STT failed: {response.status_code}")
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "message": "STT service failed"
                            }))

                except Exception as e:
                    logger.error(f"Error calling STT service: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": str(e)
                    }))

                # Reset for next utterance
                audio_chunks = []

            else:
                logger.warning(f"Unknown Wyoming ASR message type: {data['type']}")

    except WebSocketDisconnect:
        logger.info("Wyoming ASR client disconnected")
    except Exception as e:
        logger.error(f"Error in Wyoming ASR: {e}")
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/wyoming/tts")
async def wyoming_tts(websocket: WebSocket):
    """
    Wyoming TTS (Text-to-Speech) endpoint
    Receives text from agents, synthesizes via TTS service, streams audio back
    """
    await websocket.accept()
    logger.info("Wyoming TTS client connected")

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)

            if data["type"] == "synthesize":
                text = data["text"]
                voice = data.get("voice", "alloy")
                logger.info(f"TTS request: {text[:50]}...")

                try:
                    # Send to TTS service
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            TTS_URL,
                            json={
                                "input": text,
                                "voice": voice,
                                "response_format": "wav"
                            },
                            timeout=30.0
                        )

                        if response.status_code == 200:
                            audio_data = response.content
                            logger.info(f"🔊 TTS generated: {len(audio_data)} bytes")

                            # Stream audio chunks back (Wyoming format)
                            chunk_size = 4096
                            for i in range(0, len(audio_data), chunk_size):
                                chunk = audio_data[i:i+chunk_size]
                                chunk_b64 = base64.b64encode(chunk).decode('utf-8')

                                await websocket.send_text(json.dumps({
                                    "type": "audio-chunk",
                                    "rate": 22050,  # TTS sample rate
                                    "width": 2,
                                    "channels": 1,
                                    "audio": chunk_b64
                                }))

                            # Signal end
                            await websocket.send_text(json.dumps({"type": "audio-stop"}))
                        else:
                            logger.error(f"TTS failed: {response.status_code}")
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "message": "TTS service failed"
                            }))

                except Exception as e:
                    logger.error(f"Error calling TTS service: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": str(e)
                    }))

            else:
                logger.warning(f"Unknown Wyoming TTS message type: {data['type']}")

    except WebSocketDisconnect:
        logger.info("Wyoming TTS client disconnected")
    except Exception as e:
        logger.error(f"Error in Wyoming TTS: {e}")
        try:
            await websocket.close()
        except:
            pass

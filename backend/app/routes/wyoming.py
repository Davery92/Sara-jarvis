"""
Wyoming Protocol Server for Voice
Handles STT and TTS via Wyoming protocol
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
import logging
import json
import base64
import httpx
import io
import wave
import os
from typing import List, Dict, Any

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
STT_URL = "http://10.185.1.8:8585/v1/audio/transcriptions"
TTS_URL = "http://10.185.1.8:9000/v1/audio/speech"

# LLM Configuration (from env)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Sara")

# In-memory conversation history (session_id -> list of messages)
# In production, this should be Redis or database
conversation_sessions = {}


class VoiceAgentChatRequest(BaseModel):
    """Chat request from voice agent (no auth required)"""
    message: str
    session_id: str = "default"  # Session ID for conversation continuity
    context: dict = {}


class VoiceAgentChatResponse(BaseModel):
    """Chat response to voice agent"""
    response: str
    metadata: dict = {}


class ClearSessionRequest(BaseModel):
    """Request to clear conversation history"""
    session_id: str = "default"


@router.post("/voice-agent/chat", response_model=VoiceAgentChatResponse)
async def voice_agent_chat(request: VoiceAgentChatRequest):
    """
    Simple chat endpoint for voice agents (no authentication required)
    Maintains conversation history per session_id
    """
    try:
        logger.info(f"Voice agent chat [{request.session_id}]: {request.message}")

        # Get or create conversation history for this session
        if request.session_id not in conversation_sessions:
            conversation_sessions[request.session_id] = []

        session_history = conversation_sessions[request.session_id]

        # Limit history to last 10 USER messages (20 total with assistant responses)
        # This is a sliding window - oldest messages drop off after 10 user turns
        if len(session_history) > 20:
            # Remove oldest 2 messages (1 user + 1 assistant)
            session_history = session_history[-20:]
            conversation_sessions[request.session_id] = session_history
            logger.debug(f"Trimmed conversation history to last 10 turns (20 messages)")

        # Build messages with conversation history
        system_prompt = f"You are {ASSISTANT_NAME}, a helpful AI assistant. Be concise and conversational in your responses, as this is voice chat. Keep responses brief (2-3 sentences max) unless more detail is requested."

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(session_history)  # Add conversation history
        messages.append({"role": "user", "content": request.message})

        # Call LLM using OpenAI-compatible endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2000
                },
                timeout=30.0
            )

            if response.status_code == 200:
                result = response.json()
                ai_response = result["choices"][0]["message"]["content"].strip()
                logger.info(f"AI response: {ai_response}")

                # Store in conversation history
                session_history.append({"role": "user", "content": request.message})
                session_history.append({"role": "assistant", "content": ai_response})

                # Calculate turn count (user messages only)
                turn_count = len([msg for msg in session_history if msg["role"] == "user"])

                return VoiceAgentChatResponse(
                    response=ai_response,
                    metadata={
                        "model": OPENAI_MODEL,
                        "session_id": request.session_id,
                        "history_length": len(session_history),
                        "turn_count": turn_count,
                        "max_turns": 10
                    }
                )
            else:
                logger.error(f"LLM API error: {response.status_code} - {response.text}")
                return VoiceAgentChatResponse(
                    response="I'm having trouble thinking right now. Can you try again?",
                    metadata={"error": "LLM API error"}
                )

    except Exception as e:
        logger.error(f"Error in voice agent chat: {e}")
        return VoiceAgentChatResponse(
            response="Sorry, I encountered an error. Please try again.",
            metadata={"error": str(e)}
        )


@router.post("/voice-agent/clear-session")
async def clear_voice_session(request: ClearSessionRequest):
    """Clear conversation history for a session"""
    if request.session_id in conversation_sessions:
        del conversation_sessions[request.session_id]
        logger.info(f"Cleared conversation history for session: {request.session_id}")
        return {"status": "cleared", "session_id": request.session_id}
    else:
        return {"status": "not_found", "session_id": request.session_id}


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


# ============================================================================
# FITNESS VOICE AGENT ENDPOINT
# ============================================================================

# In-memory fitness conversation sessions (session_id -> {history: [], episodes: []})
fitness_voice_sessions = {}


# Simple Message class for SimpleLLMClient
class SimpleMessage:
    """Simple message object compatible with SimpleLLMClient"""
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


@router.post("/voice-agent/fitness/chat", response_model=VoiceAgentChatResponse)
async def fitness_voice_chat(request: VoiceAgentChatRequest):
    """
    Fitness voice chat endpoint with SimpleLLMClient integration:
    - Uses SimpleLLMClient for tool calling, XML filtering, and streaming
    - Loads last 5 episodes from database on session start
    - Maintains 10-turn sliding window during conversation
    - Saves all exchanges to fitness_episode table
    - Supports fitness-specific tools (fitness_note_create, fitness_note_search, fitness_note_edit)
    """
    try:
        from app.prompts.fitness_system_prompt import get_fitness_system_prompt
        from sqlalchemy import text, create_engine
        from sqlalchemy.orm import sessionmaker
        from app.main_simple import SimpleLLMClient
        from app.tools.registry import ToolRegistry

        logger.info(f"Fitness voice chat [{request.session_id}]: {request.message}")

        # Get database connection
        DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        # Get or create session
        if request.session_id not in fitness_voice_sessions:
            # Load last 5 episodes from database for context
            load_sql = text("""
                SELECT role, content, created_at
                FROM fitness_episode
                WHERE session_id = :session_id
                ORDER BY created_at DESC
                LIMIT 5
            """)

            result = db.execute(load_sql, {"session_id": request.session_id})
            loaded_episodes = []

            for row in result.fetchall():
                loaded_episodes.insert(0, {  # Insert at beginning to maintain chronological order
                    "role": row.role,
                    "content": row.content
                })

            fitness_voice_sessions[request.session_id] = {
                "loaded_episodes": loaded_episodes,
                "sliding_window": []
            }

            logger.info(f"Loaded {len(loaded_episodes)} previous episodes for session {request.session_id}")

        session_data = fitness_voice_sessions[request.session_id]
        sliding_window = session_data["sliding_window"]
        loaded_episodes = session_data["loaded_episodes"]

        # Sliding window management: Keep last 10 turns (20 messages)
        if len(sliding_window) > 20:
            sliding_window = sliding_window[-20:]
            session_data["sliding_window"] = sliding_window

        # Initialize SimpleLLMClient and ToolRegistry
        llm_client = SimpleLLMClient()
        tool_registry = ToolRegistry()

        # Build messages: system prompt + loaded episodes + sliding_window + current message
        # Convert to SimpleMessage objects for SimpleLLMClient
        message_objects = [SimpleMessage("system", get_fitness_system_prompt())]

        # Add loaded episodes
        for episode in loaded_episodes:
            message_objects.append(SimpleMessage(episode["role"], episode["content"]))

        # Add sliding window
        for msg in sliding_window:
            message_objects.append(SimpleMessage(msg["role"], msg["content"]))

        # Add current user message
        message_objects.append(SimpleMessage("user", request.message))

        # Get fitness tool schemas
        fitness_tool_schemas = tool_registry.get_fitness_tool_schemas()

        # Call SimpleLLMClient with fitness tools (supports XML filtering, streaming, tool calling)
        user_id = request.context.get("user_id", "default-user")
        ai_response = await llm_client.chat_with_tools(
            messages=message_objects,
            tools=fitness_tool_schemas,
            user_id=user_id,
            conversation_id=request.session_id
        )

        logger.info(f"AI response: {ai_response}")

        # Add to sliding window
        sliding_window.append({"role": "user", "content": request.message})
        sliding_window.append({"role": "assistant", "content": ai_response})

        # Save to database for persistence
        # Save user message
        user_episode_id = str(__import__('uuid').uuid4())
        save_user_sql = text("""
            INSERT INTO fitness_episode (id, user_id, session_id, role, content, context_data, created_at)
            VALUES (:id, :user_id, :session_id, :role, :content, :context_data, NOW())
        """)
        db.execute(save_user_sql, {
            "id": user_episode_id,
            "user_id": user_id,
            "session_id": request.session_id,
            "role": "user",
            "content": request.message,
            "context_data": json.dumps({"turn": len(sliding_window) // 2})
        })

        # Save assistant message
        assistant_episode_id = str(__import__('uuid').uuid4())
        save_assistant_sql = text("""
            INSERT INTO fitness_episode (id, user_id, session_id, role, content, context_data, created_at)
            VALUES (:id, :user_id, :session_id, :role, :content, :context_data, NOW())
        """)
        db.execute(save_assistant_sql, {
            "id": assistant_episode_id,
            "user_id": user_id,
            "session_id": request.session_id,
            "role": "assistant",
            "content": ai_response,
            "context_data": json.dumps({"turn": len(sliding_window) // 2})
        })

        db.commit()
        db.close()

        # Calculate turn count
        turn_count = len(sliding_window) // 2

        return VoiceAgentChatResponse(
            response=ai_response,
            metadata={
                "model": OPENAI_MODEL,
                "session_id": request.session_id,
                "context": "fitness",
                "loaded_episodes": len(loaded_episodes),
                "sliding_window_length": len(sliding_window),
                "turn_count": turn_count,
                "max_turns": 10,
                "tool_calling_enabled": True
            }
        )

    except Exception as e:
        logger.error(f"Error in fitness voice chat: {e}")
        import traceback
        traceback.print_exc()
        return VoiceAgentChatResponse(
            response="Sorry, I encountered an error. Please try again.",
            metadata={"error": str(e)}
        )


@router.post("/voice-agent/fitness/clear-session")
async def clear_fitness_voice_session(request: ClearSessionRequest):
    """Clear fitness voice conversation history"""
    if request.session_id in fitness_voice_sessions:
        del fitness_voice_sessions[request.session_id]
        logger.info(f"Cleared fitness voice session: {request.session_id}")
        return {"status": "cleared", "session_id": request.session_id, "context": "fitness"}
    else:
        return {"status": "not_found", "session_id": request.session_id, "context": "fitness"}

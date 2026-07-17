"""
Vision API Routes - Screenshot analysis and vision model integration
Routes images to Ollama vision models (qwen3-vl, llava, etc.)
"""
import asyncio
import base64
import hashlib
import logging
import uuid
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.user import User
from app.db.session import get_db
from app.models.machine import ShadowScreenshot
from app.models.user_settings import UserSettings
from app.core.vision_formatters import OllamaVisionFormatter
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vision", tags=["vision"])

# Default configuration - can be overridden by user settings
DEFAULT_VISION_ENDPOINT = "http://10.185.1.8:11434"
DEFAULT_VISION_MODEL = "qwen3-vl:latest"


class VisionAnalyzeRequest(BaseModel):
    """Request for vision analysis"""
    image_base64: str
    prompt: str
    model: Optional[str] = None  # Override default model


class VisionAnalyzeResponse(BaseModel):
    """Response from vision analysis"""
    response: str
    model: str
    tokens_used: Optional[int] = None


class ScreenshotUploadResponse(BaseModel):
    """Response from screenshot upload"""
    screenshot_id: str
    analysis: Optional[str] = None
    image_hash: str


def _store_screenshot_blob(content: bytes, object_key: str) -> tuple[str, str]:
    """
    Store screenshot in MinIO when available, else local uploads fallback.
    Returns (storage_key, storage_backend).
    """
    # MinIO first
    try:
        from minio import Minio

        endpoint = settings.minio_url.replace("http://", "").replace("https://", "")
        secure = settings.minio_url.startswith("https://")
        client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )
        bucket = settings.minio_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(
            bucket_name=bucket,
            object_name=object_key,
            data=io.BytesIO(content),
            length=len(content),
            content_type="image/png",
        )
        return object_key, "minio"
    except Exception as e:
        logger.warning(f"MinIO screenshot upload unavailable, falling back to local disk: {e}")

    # Local filesystem fallback
    local_root = Path("uploads")
    local_path = local_root / object_key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    return f"local://{object_key}", "local"


async def get_user_vision_settings(user_id: str, db: Session) -> dict:
    """
    Get user's vision model settings.
    Returns defaults if not configured.
    """
    from sqlalchemy import select

    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    settings = db.execute(stmt).scalar_one_or_none()

    if settings:
        return {
            "vision_model": settings.vision_model or DEFAULT_VISION_MODEL,
            "vision_endpoint": settings.vision_endpoint or DEFAULT_VISION_ENDPOINT
        }

    return {
        "vision_model": DEFAULT_VISION_MODEL,
        "vision_endpoint": DEFAULT_VISION_ENDPOINT
    }


async def call_openai_vision(
    image_base64: str,
    prompt: str,
    model: str,
    endpoint: str,
    max_tokens: int = 600,
) -> dict:
    """
    Call an OpenAI-compatible chat-completions server with a multimodal
    image_url content part. Works against llama.cpp's `--mmproj` servers,
    vLLM with VL models, etc. `endpoint` is the base URL (e.g.
    `http://host:8686`); we POST to `{endpoint}/v1/chat/completions`.

    Some thinking-mode Qwen variants return the user-visible answer in
    `message.content` and the chain-of-thought in `message.reasoning_content`.
    If `content` is empty we fall back to a trimmed reasoning string so the
    caller always gets *something* usable.
    """
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    request_body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": max_tokens,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=request_body)
        response.raise_for_status()
        result = response.json()

    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message", {}) or {}
    content = (message.get("content") or "").strip()
    if not content:
        reasoning = (message.get("reasoning_content") or "").strip()
        # Trim mid-thought reasoning to the first complete-ish sentence so we
        # don't dump a paragraph of "The user is asking..." into observations.
        if reasoning:
            head = reasoning.split(". ")[0]
            content = head.strip() + ("." if not head.endswith(".") else "")
    return {
        "response": content,
        "model": result.get("model", model),
        "tokens_used": (result.get("usage") or {}).get("completion_tokens"),
    }


async def call_ollama_vision(
    image_base64: str,
    prompt: str,
    model: str,
    endpoint: str
) -> dict:
    """
    Call Ollama with a vision model.
    Uses the Ollama /api/chat endpoint with images.
    """
    formatter = OllamaVisionFormatter()

    # Format the message content
    content = [
        {"type": "image", "data": image_base64},
        {"type": "text", "text": prompt}
    ]
    formatted = formatter.format_message_content(content)

    # Build the request for Ollama chat API
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": formatted["content"],
                "images": formatted["images"]
            }
        ],
        "stream": False
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{endpoint}/api/chat",
                json=request_body
            )
            response.raise_for_status()
            result = response.json()

            return {
                "response": result.get("message", {}).get("content", ""),
                "model": model,
                "tokens_used": result.get("eval_count")
            }
        except httpx.TimeoutException:
            logger.error(f"Vision model timeout: {model} at {endpoint}")
            raise HTTPException(status_code=504, detail="Vision model timeout")
        except httpx.HTTPStatusError as e:
            logger.error(f"Vision model error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Vision model error: {e.response.text}"
            )
        except Exception as e:
            logger.exception(f"Vision model error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", response_model=VisionAnalyzeResponse)
async def analyze_image(
    request: VisionAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze an image using the configured vision model.

    The image should be base64 encoded. The prompt describes what
    analysis to perform on the image.
    """
    user_id = current_user.id
    settings = await get_user_vision_settings(user_id, db)

    model = request.model or settings["vision_model"]
    endpoint = settings["vision_endpoint"]

    logger.info(f"Vision analysis requested by user {user_id} using {model}")

    result = await call_ollama_vision(
        image_base64=request.image_base64,
        prompt=request.prompt,
        model=model,
        endpoint=endpoint
    )

    return VisionAnalyzeResponse(**result)


@router.post("/analyze-file", response_model=VisionAnalyzeResponse)
async def analyze_image_file(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze an uploaded image file using the vision model.
    Accepts image files (JPEG, PNG, etc.) directly.
    """
    user_id = current_user.id
    settings = await get_user_vision_settings(user_id, db)

    use_model = model or settings["vision_model"]
    endpoint = settings["vision_endpoint"]

    # Read and encode the file
    content = await file.read()
    image_base64 = base64.b64encode(content).decode("utf-8")

    logger.info(f"Vision file analysis requested by user {user_id} using {use_model}")

    result = await call_ollama_vision(
        image_base64=image_base64,
        prompt=prompt,
        model=use_model,
        endpoint=endpoint
    )

    return VisionAnalyzeResponse(**result)


@router.post("/screenshot", response_model=ScreenshotUploadResponse)
async def upload_screenshot(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    session_id: Optional[str] = Form(None),
    window_title: Optional[str] = Form(None),
    app_name: Optional[str] = Form(None),
    analyze: bool = Form(False),
    analyze_prompt: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload a screenshot from a desktop agent.

    Optionally analyzes the screenshot using the vision model.
    Stores the screenshot in MinIO for later reference.
    """
    user_id = current_user.id

    # Read the file content
    content = await file.read()
    file_size = len(content)

    # Calculate perceptual hash for change detection
    image_hash = hashlib.md5(content).hexdigest()

    # Generate unique ID
    screenshot_id = str(uuid.uuid4())

    storage_object_key = f"screenshots/{user_id}/{device_id}/{screenshot_id}.png"
    minio_key, storage_backend = _store_screenshot_blob(content, storage_object_key)

    # Create database record if we have a session
    if session_id:
        screenshot = ShadowScreenshot(
            id=screenshot_id,
            session_id=session_id,
            minio_key=minio_key,
            file_size_bytes=file_size,
            window_title=window_title,
            app_name=app_name,
            image_hash=image_hash
        )
        db.add(screenshot)
        db.commit()

    # Optionally analyze the screenshot synchronously (only when the caller
    # asked for the analysis text in the response). For the periodic-capture
    # case where the sidecar just wants Sara to see what's on screen, we
    # ALWAYS kick off background analysis below and publish an event — the
    # sidecar gets a fast response and the VLM result lands in working_memory.
    analysis = None
    if analyze:
        settings = await get_user_vision_settings(user_id, db)
        image_base64 = base64.b64encode(content).decode("utf-8")

        prompt = analyze_prompt or "Describe what's happening on this screen. What application is being used? What is the user doing?"

        try:
            result = await call_ollama_vision(
                image_base64=image_base64,
                prompt=prompt,
                model=settings["vision_model"],
                endpoint=settings["vision_endpoint"]
            )
            analysis = result["response"]
        except Exception as e:
            logger.error(f"Screenshot analysis failed: {e}")
            # Don't fail the upload if analysis fails

    logger.info(
        f"Screenshot uploaded: {screenshot_id} from device {device_id} "
        f"(storage={storage_backend}, key={minio_key})"
    )

    # Fire-and-forget VLM analysis + event publish. Kicked off as a background
    # asyncio task so the sidecar's POST returns immediately. If the VLM is
    # slow (3-10s typical for Qwen3-VL), we'd otherwise stall the sidecar's
    # 5-minute capture cadence. We skip this when the caller already asked
    # for synchronous analysis above so we don't re-run the model.
    if not analyze:
        asyncio.create_task(_analyze_and_publish_screen_content(
            user_id=user_id,
            device_id=device_id,
            screenshot_id=screenshot_id,
            minio_key=minio_key,
            image_bytes=content,
            window_title=window_title,
            app_name=app_name,
        ))

    return ScreenshotUploadResponse(
        screenshot_id=screenshot_id,
        analysis=analysis,
        image_hash=image_hash
    )


def _downscale_for_vlm(image_bytes: bytes, max_edge: int = 1024, jpeg_quality: int = 80) -> bytes:
    """Shrink a screenshot to something the VLM can swallow.

    A raw 1920x1080 PNG is 1-3 MB and trips up llama.cpp's image handler
    ("Server disconnected without sending a response"). The VLM's vision
    encoder downsamples internally anyway, so we lose nothing by sending
    a 1024-on-the-long-edge JPEG. Falls back to the original bytes if PIL
    isn't installed or anything goes wrong.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_edge:
            scale = max_edge / long_edge
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.warning("VLM downscale failed, sending original bytes: %s", e)
        return image_bytes


async def _analyze_and_publish_screen_content(
    *,
    user_id: str,
    device_id: str,
    screenshot_id: str,
    minio_key: str,
    image_bytes: bytes,
    window_title: Optional[str],
    app_name: Optional[str],
) -> None:
    """Run Qwen-VL on a freshly uploaded screenshot and publish the result
    as a DESKTOP_SCREEN_CONTENT event so ACS's salience pipeline picks it up.

    Failures are logged but never raised — this is best-effort.
    """
    try:
        # Fetch model + endpoint settings. We don't have a Session here so
        # we use the fallback path that reads from llm_config defaults.
        from app.core.llm_config import llm_config
        model = llm_config.vision_model
        endpoint = llm_config.vision_url

        # Downscale before base64 to keep the request body under control.
        scaled = _downscale_for_vlm(image_bytes)
        image_base64 = base64.b64encode(scaled).decode("utf-8")
        prompt = (
            "You are Sara's eyes on David's desktop. Describe what's on the "
            "screen in 2-3 sentences. Note the active application, what the "
            "user appears to be doing, and any specific text or content that "
            "would be useful for Sara to know (e.g. error messages, file "
            "names, document titles, terminal commands). Be concrete; skip "
            "filler. If the screen is empty/blank or shows only a wallpaper, "
            "say so briefly."
        )

        result = await call_openai_vision(
            image_base64=image_base64,
            prompt=prompt,
            model=model,
            endpoint=endpoint,
        )
        summary = (result.get("response") or "").strip()
        if not summary:
            logger.debug(
                "screen_content: VLM returned empty summary for %s",
                screenshot_id,
            )
            return

        from app.services.event_bus import event_bus, Event, EventType
        await event_bus.publish(Event(
            event_type=EventType.DESKTOP_SCREEN_CONTENT,
            user_id=user_id,
            source="desktop",
            payload={
                "device_id": device_id,
                "screenshot_id": screenshot_id,
                "minio_key": minio_key,
                "summary": summary,
                "app": app_name,
                "window": window_title,
            },
        ))
        logger.info(
            "screen_content event published for %s (%d chars)",
            screenshot_id, len(summary),
        )
    except Exception as e:
        logger.warning(
            "screen_content analysis failed for %s: %s", screenshot_id, e
        )


@router.get("/models")
async def list_vision_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List available vision models from Ollama.
    """
    settings = await get_user_vision_settings(current_user.id, db)
    endpoint = settings["vision_endpoint"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{endpoint}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])

            # Filter to likely vision models
            vision_keywords = ["llava", "bakllava", "moondream", "qwen", "vl", "vision"]
            vision_models = [
                m for m in models
                if any(kw in m.get("name", "").lower() for kw in vision_keywords)
            ]

            return {
                "models": vision_models,
                "current_model": settings["vision_model"],
                "endpoint": endpoint
            }
    except Exception as e:
        logger.error(f"Failed to list vision models: {e}")
        return {
            "models": [],
            "current_model": settings["vision_model"],
            "endpoint": endpoint,
            "error": str(e)
        }


@router.get("/status")
async def vision_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check vision service status.
    """
    settings = await get_user_vision_settings(current_user.id, db)
    endpoint = settings["vision_endpoint"]
    model = settings["vision_model"]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{endpoint}/api/tags")
            response.raise_for_status()

            return {
                "status": "available",
                "endpoint": endpoint,
                "model": model
            }
    except Exception as e:
        return {
            "status": "unavailable",
            "endpoint": endpoint,
            "model": model,
            "error": str(e)
        }
